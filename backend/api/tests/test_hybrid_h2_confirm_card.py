"""H2 批次 2：Workflow 确认卡链路单测（W5 发卡 + ack 行锁事务 + 重放经 W6 入队）。

覆盖：W5 无确认上下文时发卡收尾（confirm 事件 + completed(stop) + engine 审计）、
回执注入后 W5 合并放行 → W6 唯一入队 → W7 收尾、必填缺失就地收尾不回环、
确认卡默认值与 agent/defaults.py 精确一致、ack 行锁事务（owner / 并发 / 深合并
/ 同源校验失败保留卡 / 清卡提交 / 取消不入队）。全部不依赖真实 DB/WS/模型。

W6/W7 的入队行为在本文件中以 ``db_factory`` 桩注入，验证「入队唯一经 W6」：
重放回合结束后 ``enqueued_task_id`` 由 W6 写入，而非 ws 层直接入队。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agent import LangGraphAgent
from app.agent.graph import iter_pending_events
from app.errors import AppError, ErrorCode
from app.harness.memory import SerializableRequest
from app.llm import ModelRequest, ModelResponse, ModelStreamEvent


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


class _StubGateway:
    """Workflow 链路不使用 LLM（L0 确定性）；保留接口以防路径回退。"""

    def __init__(self) -> None:
        self.stream_calls = 0
        self.invoke_calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
        self.invoke_calls.append(request)
        return ModelResponse(text="", latency_ms=1)

    def stream(self, request: ModelRequest, config: dict | None = None):
        self.stream_calls += 1
        return iter(
            [
                ModelStreamEvent(
                    kind="completed",
                    response=ModelResponse(text="流式答案", latency_ms=2),
                )
            ]
        )


@dataclass
class _FakeRow:
    pending_confirm: dict | None
    pending_confirm_author_id: str | None


@dataclass
class _FakeDb:
    """最小 DB 桩：支持 lock_pending_confirm 的 execute().first() 与清卡写入。"""

    row: _FakeRow
    executed: list[str] = field(default_factory=list)
    committed: int = 0
    rolled_back: int = 0
    added: list[Any] = field(default_factory=list)

    def execute(self, statement: Any, params: dict | None = None) -> Any:
        text_value = str(getattr(statement, "text", statement))
        self.executed.append(text_value)
        if text_value.startswith("SELECT pending_confirm"):
            return _Result([self.row])
        return _Result([])

    def query(self, *args: Any, **kwargs: Any) -> Any:
        # drop_stale_asset_ids 的资产查询：返回「不可用」结果（非 list），
        # 库按 _existing_ids 的容错分支处理 → 不改动 spec（见下 _EmptyQuery）。
        return _EmptyQuery()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        return None


@dataclass
class _Result:
    rows: list[Any]

    def first(self) -> Any:
        return self.rows[0] if self.rows else None


class _EmptyQuery:
    """查询结果「不可用」桩：all() 返回非 list，``_existing_ids`` 据此保持原 spec。

    与生产语义一致——资产库查询失败时不删槽，交由后续 TaskCreate 校验兜底。
    """

    def filter(self, *args: Any, **kwargs: Any) -> _EmptyQuery:
        return self

    def all(self) -> Any:
        return object()

    def first(self) -> None:
        return None


def _run(
    agent: LangGraphAgent,
    request: SerializableRequest,
    config: dict | None = None,
) -> list[tuple[str, dict]]:
    run_config = config or {
        "configurable": {"thread_id": "test-turn", "db_factory": _FakeDbFactory(), "session_id": "s-1", "user_id": "u-1"}
    }

    async def collect() -> list[tuple[str, dict]]:
        return [item async for item in agent.astream(request, config=run_config)]

    return asyncio.run(collect())


@dataclass
class _FakeDbFactory:
    """W6 入队用的会话工厂：每次调用返回独立的会话桩。"""

    sessions: list[_FakeDb] = field(default_factory=list)

    def __call__(self) -> _FakeDb:
        db = _FakeDb(row=_FakeRow(pending_confirm=None, pending_confirm_author_id=None))
        self.sessions.append(db)
        return db


def _events(events: list[tuple[str, dict]]) -> list[dict]:
    return [
        event
        for mode, chunk in events
        if mode == "updates"
        for event in iter_pending_events(chunk)
    ]


def _payload(events: list[tuple[str, dict]], kind: str) -> dict:
    payloads = [e["payload"] for e in _events(events) if e["kind"] == kind]
    assert len(payloads) == 1, kind
    return dict(payloads[0])


def _node_output(events: list[tuple[str, dict]], node: str) -> dict | None:
    for mode, chunk in events:
        if mode == "updates" and node in chunk:
            return chunk[node]
    return None


# ─── 1. W5 发卡收尾 ───


def test_w5_emits_confirm_card_and_completes_turn(hybrid_on: None) -> None:
    """首次到达 W5：发卡（confirm 事件）+ 阶段叙述 + completed(stop)，不入队。"""
    factory = _FakeDbFactory()
    events = _run(
        LangGraphAgent(_StubGateway()),
        _request("跑一次基准评测"),
        {
            "configurable": {
                "thread_id": "t1",
                "db_factory": factory,
                "session_id": "s-1",
                "user_id": "u-1",
            }
        },
    )
    kinds = [e["kind"] for e in _events(events)]
    assert "confirm" in kinds
    # 叙述在卡前，completed 收尾
    assert kinds[-1] == "response.completed"
    assert kinds.index("assistant_message") < kinds.index("confirm")
    completed = _payload(events, "response.completed")
    assert completed["finish_reason"] == "stop"
    assert completed["engine"] == "workflow"
    # 本轮不推进 W6：无入队
    assert _node_output(events, "w6_enqueue") is None
    assert factory.sessions == []  # W6 未执行 → 未开会话


def test_confirm_card_defaults_match_backend_source(hybrid_on: None) -> None:
    """卡载荷与 agent/defaults.py 唯一默认值精确一致（前端同源约束）。"""
    from app.agent.defaults import DEFAULT_RAG_MODE, DEFAULT_RUN, DEFAULT_STRESS, default_task_spec

    events = _run(
        LangGraphAgent(_StubGateway()),
        _request("跑一次基准评测"),
        {
            "configurable": {
                "thread_id": "t1",
                "db_factory": _FakeDbFactory(),
                "session_id": "s-1",
                "user_id": "u-1",
            }
        },
    )
    card = _payload(events, "confirm")
    assert card == default_task_spec("benchmark")
    assert card["run"] == DEFAULT_RUN
    assert card["stress"] == DEFAULT_STRESS
    assert card["rag_mode"] == DEFAULT_RAG_MODE
    assert card["kind"] == "benchmark"


def test_w5_records_confirm_id_and_stops_chain(hybrid_on: None) -> None:
    """发卡时写入 confirm_id（与 clarify_id 互斥），workflow_failed 短路后续节点。"""
    events = _run(
        LangGraphAgent(_StubGateway()),
        _request("帮我生成测试用例"),
        {
            "configurable": {
                "thread_id": "t1",
                "db_factory": _FakeDbFactory(),
                "session_id": "s-1",
                "user_id": "u-1",
            }
        },
    )
    w5 = _node_output(events, "w5_await_confirm")
    assert w5 is not None
    assert w5["confirm_id"]
    assert w5["workflow_failed"] is True
    assert "clarify_id" not in w5
    assert _node_output(events, "w7_summarize") is None


# ─── 2. 回执重放：W5 合并 → W6 唯一入队 → W7 收尾 ───


def test_confirm_replay_merges_spec_and_enqueues_via_w6(hybrid_on: None) -> None:
    """workflow_confirm 注入后：W5 合并槽位 → W6 入队（唯一出口）→ W7 收尾。"""
    factory = _FakeDbFactory()
    events = _run(
        LangGraphAgent(_StubGateway()),
        _request("对 profile-A 跑基准评测"),
        {
            "configurable": {
                "thread_id": "t2",
                "db_factory": factory,
                "session_id": "s-1",
                "user_id": "u-1",
                "workflow_confirm": {
                    "task_spec": {"profile_ids": ["profile-A"], "dataset_id": "ds-math-qa"}
                },
            }
        },
    )
    w5 = _node_output(events, "w5_await_confirm")
    assert w5 is not None
    assert w5["task_spec"]["profile_ids"] == ["profile-A"]
    assert w5["task_spec"]["dataset_id"] == "ds-math-qa"
    assert "workflow_failed" not in w5
    w6 = _node_output(events, "w6_enqueue")
    assert w6 is not None and w6["enqueued_task_id"]
    assert len(factory.sessions) == 1  # W6 开了一次会话并入队
    assert factory.sessions[0].committed >= 1  # enqueue_long_task 提交
    # W7 收尾：叙述 + completed 审计
    kinds = [e["kind"] for e in _events(events)]
    assert kinds[-1] == "response.completed"
    assert "confirm" not in kinds  # 已确认，不再发卡


def test_replay_missing_required_assets_stops_in_place(hybrid_on: None) -> None:
    """回执缺必填资产：W5 就地收尾（error + completed(error)），绝不入队。"""
    factory = _FakeDbFactory()
    events = _run(
        LangGraphAgent(_StubGateway()),
        _request("跑一次基准评测"),
        {
            "configurable": {
                "thread_id": "t3",
                "db_factory": factory,
                "session_id": "s-1",
                "user_id": "u-1",
                "workflow_confirm": {"task_spec": {"dataset_id": "ds-1"}},  # 缺 profile_ids
            }
        },
    )
    error = _payload(events, "error")
    assert error["code"] == "VALIDATION"
    assert "必填项" in error["message"]
    completed = _payload(events, "response.completed")
    assert completed["finish_reason"] == "error"
    assert _node_output(events, "w6_enqueue") is None
    assert factory.sessions == []


# ─── 3. ack 行锁事务（ws 层）───


def _ack_env(monkeypatch: pytest.MonkeyPatch, *, spec: dict, author_id: str):
    """构造 _handle_confirm_ack 的最小环境：返回 (db, emit 记录, replay 记录)。"""
    import app.routers.ws as ws

    emitted: list[tuple[str, dict]] = []
    replayed: list[dict] = []

    async def fake_emit(db: Any, websocket: Any, state: Any, session_id: str, event: str, payload: dict, **kwargs: Any) -> None:
        emitted.append((event, payload))

    def fake_replay(
        session_id: str,
        websocket: Any,
        state: Any,
        user_id: str,
        merged_spec: dict,
        *,
        handle: Any = None,
    ) -> None:
        replayed.append(merged_spec)
        if handle is not None:
            ws._release_turn(handle)
        return None  # type: ignore[return-value]

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_start_confirm_replay", fake_replay)
    db = _FakeDb(row=_FakeRow(pending_confirm=dict(spec), pending_confirm_author_id=author_id))
    return ws, db, emitted, replayed


def test_ack_unauthorized_member_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """非发起人确认：UNAUTHORIZED，卡保留、不派生重放。"""
    ws, db, emitted, replayed = _ack_env(
        monkeypatch, spec={"kind": "benchmark", "profile_ids": ["p1"], "dataset_id": "d1"}, author_id="owner-1"
    )
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_confirm_ack(db, None, None, "s-1", "other-user", {"ok": True, "patch": {}})
        )
    assert exc.value.code == ErrorCode.UNAUTHORIZED
    assert replayed == [] and emitted == []
    assert db.rolled_back == 1


def test_ack_repeat_or_missing_card_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """卡已被消费/不存在：拒绝（owner 校验先于并发检测 → VALIDATION「无待确认卡」），
    绝不重复入队。CONCURRENCY 为并发处理分支的防御错误码。
    """
    ws, db, emitted, replayed = _ack_env(monkeypatch, spec={"kind": "benchmark"}, author_id="u-1")
    db.row = _FakeRow(pending_confirm=None, pending_confirm_author_id="u-1")
    with pytest.raises(AppError) as exc:
        asyncio.run(ws._handle_confirm_ack(db, None, None, "s-1", "u-1", {"ok": True, "patch": {}}))
    assert exc.value.code == ErrorCode.VALIDATION
    assert "待确认卡" in str(exc.value.message)
    assert replayed == [] and emitted == []
    assert db.rolled_back == 1


def test_ack_validation_failure_keeps_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """回执缺必填：TaskCreate 同源校验失败 → 卡保留，用户补齐后可重试。"""
    ws, db, emitted, replayed = _ack_env(
        monkeypatch, spec={"kind": "benchmark", "dataset_id": "d1"}, author_id="u-1"
    )
    with pytest.raises(AppError) as exc:
        asyncio.run(ws._handle_confirm_ack(db, None, None, "s-1", "u-1", {"ok": True, "patch": {}}))
    assert exc.value.code == ErrorCode.VALIDATION
    assert replayed == []
    assert db.rolled_back == 1
    # 未执行清卡 UPDATE
    assert not any("UPDATE sessions SET pending_confirm = NULL" in sql for sql in db.executed)


def test_ack_ok_merges_patch_clears_card_and_replays(monkeypatch: pytest.MonkeyPatch) -> None:
    """批准：patch 深合并 → 清卡提交 → 以合并后的 spec 派生重放（入队经 W6）。"""
    ws, db, emitted, replayed = _ack_env(
        monkeypatch,
        spec={"kind": "benchmark", "profile_ids": ["p1"], "dataset_id": "d1", "run": {"sample_size": 1000}},
        author_id="u-1",
    )
    asyncio.run(
        ws._handle_confirm_ack(
            db, None, None, "s-1", "u-1", {"ok": True, "patch": {"dataset_id": "d2", "run": {"concurrency": 8}}}
        )
    )
    assert len(replayed) == 1
    merged = replayed[0]
    assert merged["dataset_id"] == "d2"  # patch 覆盖
    assert merged["run"] == {"sample_size": 1000, "concurrency": 8}  # 深合并
    assert db.committed == 1
    assert any("UPDATE sessions SET pending_confirm = NULL" in sql for sql in db.executed)


def test_ack_active_turn_keeps_pending_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """确认前已有交互回合时先报 CONCURRENCY，绝不清卡或启动重放。"""
    ws, db, emitted, replayed = _ack_env(
        monkeypatch,
        spec={"kind": "benchmark", "profile_ids": ["p1"], "dataset_id": "d1"},
        author_id="u-1",
    )
    active = ws._reserve_turn("s-1", "u-1")
    try:
        with pytest.raises(AppError) as exc:
            asyncio.run(
                ws._handle_confirm_ack(db, None, None, "s-1", "u-1", {"ok": True})
            )
        assert exc.value.code == ErrorCode.CONCURRENCY
        assert replayed == [] and emitted == []
        assert not any("UPDATE sessions SET pending_confirm = NULL" in sql for sql in db.executed)
    finally:
        ws._release_turn(active)


def test_confirm_replay_without_task_restores_card_without_success_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6 未写任务 ID 时恢复卡并报错，禁止发 ok=true 与空 task_id。"""
    import app.routers.ws as ws

    emitted: list[tuple[str, dict]] = []
    restored: list[dict] = []

    async def fake_run_turn(*args: Any, **kwargs: Any) -> None:
        return None  # 模拟开关切换到 chat 等未产出 W6 task_id 的路径

    async def fake_emit_persistent(
        db: Any,
        websocket: Any,
        state: Any,
        session_id: str,
        event: str,
        payload: dict,
        **kwargs: Any,
    ) -> None:
        emitted.append((event, payload))

    async def fake_emit_error(
        db: Any, websocket: Any, state: Any, session_id: str, error: AppError
    ) -> None:
        emitted.append(("error", {"code": error.code.value, "message": error.message}))

    def fake_restore(db: Any, session_id: str, task_spec: dict, user_id: str) -> None:
        restored.append(dict(task_spec))

    monkeypatch.setattr(ws, "_run_turn", fake_run_turn)
    monkeypatch.setattr(ws, "_emit_persistent", fake_emit_persistent)
    monkeypatch.setattr(ws, "_emit_error", fake_emit_error)
    monkeypatch.setattr(ws, "_restore_pending_confirm", fake_restore)
    monkeypatch.setattr(
        ws,
        "SessionLocal",
        lambda: _FakeDb(row=_FakeRow(pending_confirm=None, pending_confirm_author_id=None)),
    )

    async def drive() -> None:
        task = ws._start_confirm_replay(
            "s-replay-failure",
            None,
            ws._ConnectionState(),
            "u-1",
            {"kind": "benchmark", "profile_ids": ["p1"], "dataset_id": "d1"},
        )
        await task

    asyncio.run(drive())
    assert restored == [{"kind": "benchmark", "profile_ids": ["p1"], "dataset_id": "d1"}]
    assert emitted == [("error", {"code": "INTERNAL", "message": "确认任务未入队，请稍后重试"})]


def test_ack_cancel_only_clears_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """取消：不入队、不重放，仅清卡并回 confirm_ack(ok=false)。"""
    ws, db, emitted, replayed = _ack_env(
        monkeypatch, spec={"kind": "benchmark", "profile_ids": ["p1"]}, author_id="u-1"
    )
    asyncio.run(ws._handle_confirm_ack(db, None, None, "s-1", "u-1", {"ok": False}))
    assert replayed == []
    assert emitted == [("confirm_ack", {"ok": False, "task_id": None, "message": "已取消确认"})]
    assert db.committed == 1
