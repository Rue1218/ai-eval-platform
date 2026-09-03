"""H5 HITL/持久化测试（开发计划 H5 验收，批次 1）。

覆盖：图级 interrupt（危险 bash）→ 检查点暂停 → ahas_pending_interrupt →
resume 恢复（approve 继续执行 / reject 拒绝）且事件不重放；审批卡协议
（行锁落卡 meta/一次性 nonce/已有卡 CONCURRENCY 不覆盖）；审批回执行锁
校验链（owner/卡种/id/action）与 resume 至多一次。不依赖 PG（检查点用
进程内 InMemoryCheckpointer，语义与 PgCheckpointer 一致——真实 PG 演练见
开发计划 §4 Linux/Docker 环境）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent import LangGraphAgent
from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.memory import SerializableRequest
from app.harness.orchestration.agents import AgentDef, AgentRegistry
from app.llm import ModelResponse
from app.routers import ws

# 图级 interrupt 用自定义注册表：general Worker 视野含 bash（危险命令需
# interrupt 审批）。生产 discover 仍排除 sandbox（H5 安全评审另行放开）。
_BASH_REGISTRY = AgentRegistry()
_BASH_REGISTRY.register(
    AgentDef(
        agent_id="worker.general",
        display_name="通用助手（测试含 bash）",
        capabilities=frozenset({"general"}),
        allowed_tools=("read", "bash", "web_search"),
        max_permission="code",
        description="测试用",
    )
)


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


_PLAN_OK = (
    '{"intent":"排查测试环境异常","skill_id":null,'
    '"slots":{"steps":["检查环境","清理脏数据","给出结论"]},'
    '"tools_needed":["bash"],"delivery":"chat",'
    '"budget":{"model_calls":8,"tool_turns":6},"allows_replan":false,'
    '"notes":"测试","protocol":"plan","version":"plan.v1"}'
)
_REACT_BASH = (
    '{"thought":"整理工作区","tool":"bash","arguments":{"command":"touch /tmp/x.txt"},'
    '"done":false,"protocol":"react","version":"react.v1"}'
)
_REACT_DONE = (
    '{"thought":"完成","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n已按计划完成。'
)


class _ScriptedGateway:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        index = self.calls
        self.calls += 1
        if index >= len(self._texts):
            raise AssertionError(f"模型调用超出脚本：{self.calls}")
        return ModelResponse(text=self._texts[index], usage={}, latency_ms=0)


def _collect_until_interrupt(agent: LangGraphAgent, text: str, config: dict):
    """跑图直到 interrupt；返回 (interrupt_value, thread_id, 事件轨迹)。"""

    async def run():
        events: list[tuple[str, dict]] = []
        interrupt_value = None
        async for mode, chunk in agent.astream(_request(text), config=config):
            events.append((mode, chunk))
            if mode == "updates" and "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                first = interrupts[0]
                interrupt_value = getattr(first, "value", first)
        return interrupt_value, events

    return asyncio.run(run())


def _resume(agent: LangGraphAgent, config: dict, resume_value: dict):
    from langgraph.types import Command

    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(
            _request("继续"), config=config, resume=Command(resume=resume_value)
        ):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _all_pending(events: list[tuple[str, dict]]) -> list[dict]:
    return [
        event
        for _mode, chunk in events
        if isinstance(chunk, dict)
        for value in chunk.values()
        if isinstance(value, dict)
        for event in value.get("pending_events", [])
    ]


def _engine_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "credentials": {"api_key": ""}}}


# ─── 1. 图级：危险 bash interrupt → resume（approve/reject）───


@pytest.fixture()
def _engine_on(monkeypatch):
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    yield


def _saver():
    """进程内检查点（BaseCheckpointSaver 契约，CI 严格类型校验兼容）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def test_graph_interrupt_then_approve_resume(_engine_on) -> None:
    """bash 危险命令 interrupt → 检查点暂停 → approve resume → 图继续收尾。"""
    thread_id = "h5-thread-1"
    # H4 失败阶梯会在工具失败后允许一次 repair，因此恢复回合需要两次收尾响应。
    gateway = _ScriptedGateway([_PLAN_OK, _REACT_BASH, _REACT_DONE, _REACT_DONE])
    agent = LangGraphAgent(
        gateway, agent_registry=_BASH_REGISTRY, checkpointer=_saver()
    )
    config = _engine_config(thread_id)
    interrupt_value, events = _collect_until_interrupt(agent, "排查一下测试环境异常", config)
    if interrupt_value is None:
        trace = [
            (node, [e["kind"] for e in update.get("pending_events", [])] if isinstance(update, dict) else type(update).__name__)
            for _mode, chunk in events
            if isinstance(chunk, dict)
            for node, update in chunk.items()
        ]
        raise AssertionError(f"未捕获 interrupt；图轨迹={trace}；调用={gateway.calls}")
    assert interrupt_value.get("type") == "tool_approval"
    assert interrupt_value.get("name") == "bash"
    assert "touch" in interrupt_value.get("command", "")
    assert "允许" not in interrupt_value.get("allowed_decisions", [])  # 只 approve/reject
    assert asyncio.run(agent.ahas_pending_interrupt(thread_id)) is True
    # 中断前已广播一次 tool_call（Act 阶段）；resume 回合不得重放
    assert len([e for e in _all_pending(events) if e["kind"] == "tool_call"]) == 1
    # resume approve：toolnode 放行执行（本机无 bwrap → 工具失败观察），H4 repair 后收尾
    resumed = _resume(agent, config, {"action": "approve", "id": interrupt_value["id"]})
    resumed_pending = _all_pending(resumed)
    tool_calls_after = [e for e in resumed_pending if e["kind"] == "tool_call"]
    assert not tool_calls_after  # 恢复回合不重放中断前的 tool_call（无重复事件）
    completed = [e for e in resumed_pending if e["kind"] == "response.completed"]
    assert completed, "resume 后回合应正常收尾"
    assert asyncio.run(agent.ahas_pending_interrupt(thread_id)) is False
    assert gateway.calls == 4  # plan + bash Act + repair 后两次收尾响应


def test_graph_interrupt_then_reject_stops_command(_engine_on) -> None:
    """reject resume：bash 不执行（rejected 观察），回合正常收尾。"""
    thread_id = "h5-thread-2"
    # reject 也会形成一次失败观察，H4 repair 阶梯需要第二次收尾响应。
    gateway = _ScriptedGateway([_PLAN_OK, _REACT_BASH, _REACT_DONE, _REACT_DONE])
    agent = LangGraphAgent(
        gateway, agent_registry=_BASH_REGISTRY, checkpointer=_saver()
    )
    config = _engine_config(thread_id)
    interrupt_value, events = _collect_until_interrupt(agent, "排查一下测试环境异常", config)
    if interrupt_value is None:
        trace = [
            (node, [e["kind"] for e in update.get("pending_events", [])] if isinstance(update, dict) else type(update).__name__)
            for _mode, chunk in events
            if isinstance(chunk, dict)
            for node, update in chunk.items()
        ]
        raise AssertionError(f"未捕获 interrupt；图轨迹={trace}；调用={gateway.calls}")
    resumed = _resume(agent, config, {"action": "reject", "id": interrupt_value["id"]})
    resumed_pending = _all_pending(resumed)
    tool_results = [e for e in resumed_pending if e["kind"] == "tool_result"]
    assert tool_results and tool_results[0]["payload"]["ok"] is False  # 拒绝不执行
    completed = [e for e in resumed_pending if e["kind"] == "response.completed"]
    assert completed


# ─── 2. 审批卡协议：落卡行锁 / meta / 一次性 nonce ───


class _Row:
    def __init__(self, session_id: str = "s-1") -> None:
        self.id = session_id
        self.user_id = "u-1"
        self.pending_confirm = None
        self.pending_confirm_author_id = None
        self.compact_summary = None


class _FakeDb:
    def __init__(self, row: _Row | None = None) -> None:
        self.row = row or _Row()
        self.committed = 0
        self.rolled_back = 0

    def query(self, _model):
        return self

    def filter(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.row

    def execute(self, statement, params=None):
        sql = str(getattr(statement, "text", statement))
        if sql.startswith("UPDATE sessions SET pending_confirm = NULL"):
            self.row.pending_confirm = None
            self.row.pending_confirm_author_id = None
        return self

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        pass


def test_persist_approval_writes_card_with_meta() -> None:
    db = _FakeDb()
    card = ws._persist_pending_approval(
        db,
        "s-1",
        {
            "type": "tool_approval",
            "id": "call-1",
            "call_id": "call-1",
            "name": "bash",
            "command": "rm -rf /tmp/x",
            "reason": "危险命令",
            "risk_level": "high",
        },
        thread_id="t-1",
        user_id="u-1",
    )
    assert db.row.pending_confirm is not None
    meta = db.row.pending_confirm["meta"]
    assert meta["schema_version"] == 1
    assert meta["confirm_type"] == "tool_approval"
    assert meta["thread_id"] == "t-1"
    assert meta["owner_id"] == "u-1"
    assert meta["resume_nonce"]
    assert db.row.pending_confirm_author_id == "u-1"
    assert card["id"] == "call-1"
    assert "type" not in card  # 白名单过滤，不留图内字段


def test_persist_approval_rejects_existing_card() -> None:
    db = _FakeDb(_Row())
    db.row.pending_confirm = {"kind": "benchmark"}
    with pytest.raises(AppError) as exc:
        ws._persist_pending_approval(
            db, "s-1", {"id": "call-1", "name": "bash"}, thread_id="t-1", user_id="u-1"
        )
    assert exc.value.code == ErrorCode.CONCURRENCY
    assert db.row.pending_confirm["kind"] == "benchmark"  # 不覆盖


def test_confirm_card_now_carries_h5_meta() -> None:
    """确认卡（H2）升级后带 meta 恢复协议字段（不破坏 spec 平铺语义）。"""
    db = _FakeDb()
    ws._persist_pending_confirm(
        db,
        "s-1",
        {"kind": "benchmark", "profile_ids": [], "confirm_author": {"id": "u-1"}},
        thread_id="t-1",
        user_id="u-1",
    )
    card = db.row.pending_confirm
    assert card["kind"] == "benchmark"
    meta = card["meta"]
    assert meta["confirm_type"] == "task_confirm"
    assert meta["thread_id"] == "t-1"
    assert meta["owner_id"] == "u-1"
    assert db.row.pending_confirm_author_id == "u-1"


def test_confirm_card_duplicate_issue_rejected() -> None:
    """会话已有卡时重复发确认卡 → CONCURRENCY（不覆盖，团队协作不抢占）。"""
    db = _FakeDb(_Row())
    db.row.pending_confirm = {"kind": "testcase"}
    with pytest.raises(AppError) as exc:
        ws._persist_pending_confirm(
            db, "s-1", {"kind": "benchmark"}, thread_id="t-2", user_id="u-1"
        )
    assert exc.value.code == ErrorCode.CONCURRENCY
    assert db.row.pending_confirm["kind"] == "testcase"


# ─── 3. 审批回执行锁校验链 ───


def _approval_card(thread_id: str = "t-1") -> dict:
    return {
        "id": "call-1",
        "call_id": "call-1",
        "name": "bash",
        "command": "rm -rf /tmp/x",
        "meta": {
            "schema_version": 1,
            "confirm_type": "tool_approval",
            "thread_id": thread_id,
            "owner_id": "u-1",
            "resume_nonce": "nonce-1",
        },
    }


def test_approval_ack_clears_card_and_resumes_once(monkeypatch) -> None:
    started: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        ws,
        "_start_approval_resume",
        lambda _sid, _ws, _st, _uid, thread_id, action, approval_id: started.append(
            (thread_id, action, approval_id)
        )
        or object(),
    )
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    db = _FakeDb(_Row())
    db.row.pending_confirm = _approval_card()
    db.row.pending_confirm_author_id = "u-1"
    asyncio.run(
        ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
    )
    assert db.row.pending_confirm is None  # 清卡（一次性）
    assert started == [("t-1", "approve", "call-1")]  # 原 thread_id 恢复
    assert emitted and emitted[-1][0] == "tool_approval_ack"
    assert db.committed >= 1


def test_approval_ack_reject_no_resume(monkeypatch) -> None:
    started: list = []
    monkeypatch.setattr(
        ws, "_start_approval_resume", lambda *_a, **_k: started.append(1) or object()
    )

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    db = _FakeDb(_Row())
    db.row.pending_confirm = _approval_card()
    db.row.pending_confirm_author_id = "u-1"
    asyncio.run(
        ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "reject", "id": "call-1"})
    )
    assert db.row.pending_confirm is None
    assert started == [1]  # reject 也 resume（toolnode 收到 reject 不执行命令）


def test_approval_ack_repeated_after_clear_rejected(monkeypatch) -> None:
    """卡已消费（重复 ack）→ 拒绝（无待确认卡），resume 至多一次。"""
    monkeypatch.setattr(ws, "_start_approval_resume", lambda *_a, **_k: None)
    db = _FakeDb(_Row())  # 无卡
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
        )
    assert exc.value.code == ErrorCode.VALIDATION


def test_approval_ack_missing_resume_nonce_rejected() -> None:
    """审批卡缺少一次性恢复令牌时拒绝消费，避免恢复协议降级。"""
    db = _FakeDb(_Row())
    card = _approval_card()
    del card["meta"]["resume_nonce"]
    db.row.pending_confirm = card
    db.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(
                db,
                object(),
                ws._ConnectionState(),
                "s-1",
                "u-1",
                {"action": "approve", "id": "call-1"},
            )
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.row.pending_confirm is card


def test_approval_ack_wrong_owner_or_kind_rejected() -> None:
    db = _FakeDb(_Row())
    db.row.pending_confirm = _approval_card()
    db.row.pending_confirm_author_id = "u-2"  # 非 owner
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
        )
    assert exc.value.code == ErrorCode.UNAUTHORIZED
    db2 = _FakeDb(_Row())
    db2.row.pending_confirm = {"kind": "benchmark", "meta": {"confirm_type": "task_confirm", "thread_id": "t-1"}}
    db2.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(db2, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
        )
    assert exc.value.code == ErrorCode.VALIDATION  # 任务确认卡不走审批 ack


# ─── 4. interrupt 帧 → 落卡广播（ws 层）───


def test_graph_interrupt_frame_persists_and_broadcasts(_engine_on, monkeypatch) -> None:
    """__interrupt__ 帧（tool_approval）→ 行锁落卡 + tool_approval 事件广播。"""
    db = _FakeDb(_Row())
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    interrupt_payload = {
        "type": "tool_approval",
        "id": "call-9",
        "call_id": "call-9",
        "name": "bash",
        "command": "rm -rf /x",
        "reason": "危险命令",
        "risk_level": "high",
        "sandbox_scope": "…",
    }
    paused = asyncio.run(
        ws._handle_graph_interrupt(
            db, object(), ws._ConnectionState(), "s-1", (type("I", (), {"value": interrupt_payload})(),),
            thread_id="t-9",
            user_id="u-1",
        )
    )
    assert paused is True
    assert db.row.pending_confirm["meta"]["confirm_type"] == "tool_approval"
    assert db.row.pending_confirm["meta"]["thread_id"] == "t-9"
    assert emitted and emitted[-1][0] == "tool_approval"
    assert emitted[-1][1]["id"] == "call-9"
    assert "meta" not in emitted[-1][1]  # 广播不带内部 meta
