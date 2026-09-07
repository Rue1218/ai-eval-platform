"""澄清问答链路回归（dsh 改进 #1，API.md V1.72：clarify / clarify_reply 转正）。

覆盖：图级 `ask_user_question` interrupt → Command(resume={id, answers}) 恢复
执行（B 路线多题 answers[]）；ws 层澄清卡落库/互斥/广播/回执与一次性语义；
与 `confirm_ack`（W5）/`tool_approval_ack`（H5）共用行锁互斥不互相干扰。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.errors import AppError, ErrorCode
from app.harness.execution import (
    NativeToolResultStore,
    build_default_registry,
    build_tool_node,
)
from app.harness.memory import GraphState, InMemoryCheckpointer
from app.routers import ws

_QUESTIONS: list[dict[str, object]] = [
    {
        "id": "q1",
        "question": "选择评测类型",
        "type": "radio",
        "options": [{"label": "benchmark"}, {"label": "rag"}],
        "required": True,
    },
    {
        "id": "q2",
        "question": "备注说明",
        "type": "text",
        "required": False,
    },
]


def _build_graph():
    """构造仅含 ToolNode 的检查点图，验证 clarify interrupt/resume 真实语义。"""
    registry = build_default_registry()
    graph = StateGraph(GraphState)
    graph.add_node("tools", build_tool_node(registry, native_tool_results=NativeToolResultStore()))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile(checkpointer=InMemoryCheckpointer())


def _initial_state() -> GraphState:
    """准备一条 ask_user_question 原生 ToolCall。"""
    return {
        "request": {
            "config": {"protocol": "openai_chat", "model": "test"},
            "messages": (),
        },
        "pending_tool": {
            "name": "ask_user_question",
            "arguments": {"questions": _QUESTIONS},
            "call_id": "call-clarify",
            "native": True,
        },
    }


async def _collect(graph, graph_input: object, config: dict) -> list[dict]:
    """收集更新帧，包含 LangGraph 的 __interrupt__ 中断载荷（ToolNode 为异步节点）。"""
    frames: list[dict] = []
    async for frame in graph.astream(graph_input, config=config, stream_mode="updates"):
        frames.append(frame)
    return frames


def _all_pending(frames: list[dict]) -> list[dict]:
    return [
        event
        for frame in frames
        for update in frame.values()
        if isinstance(update, Mapping)
        for event in update.get("pending_events", [])
    ]


def _graph_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "session": {"id": "s-1"}}}


def test_clarify_interrupts_before_any_result() -> None:
    """ask_user_question 先产生澄清中断载荷；无 resume 前不产出任何结果事件。"""
    graph = _build_graph()
    frames = asyncio.run(_collect(graph, _initial_state(), _graph_config("clarify-int-1")))

    interrupts = [frame["__interrupt__"][0].value for frame in frames if "__interrupt__" in frame]
    assert len(interrupts) == 1
    value = interrupts[0]
    assert value["type"] == "clarify"
    assert value["id"] == "call-clarify"
    questions = value["questions"]
    assert len(questions) == 2
    assert questions[0]["id"] == "q1"
    assert questions[0]["type"] == "radio"
    assert _all_pending(frames) == []


def test_clarify_resume_with_structured_answers_continues() -> None:
    """多题 answers[] resume：toolnode 按答复放行，产出成功工具结果。"""
    graph = _build_graph()
    config = _graph_config("clarify-resume-1")
    asyncio.run(_collect(graph, _initial_state(), config))
    frames = asyncio.run(
        _collect(
            graph,
            Command(
                resume={
                    "id": "call-clarify",
                    "answers": [{"id": "q1", "selected": ["benchmark"], "custom": ""}],
                }
            ),
            config,
        )
    )

    results = [
        e for e in _all_pending(frames) if e["kind"] == "tool_result" and e["payload"].get("call_id") == "call-clarify"
    ]
    assert results and results[0]["payload"]["ok"] is True
    assert results[0]["payload"]["name"] == "ask_user_question"


def test_clarify_resume_with_invalid_answers_fails_without_crash() -> None:
    """未知问题 id / 越界选项等无效答复 → 工具失败观察（不崩溃、无新中断）。"""
    graph = _build_graph()
    config = _graph_config("clarify-resume-bad")
    asyncio.run(_collect(graph, _initial_state(), config))

    frames = asyncio.run(
        _collect(
            graph,
            Command(
                resume={
                    "id": "call-clarify",
                    "answers": [{"id": "nope", "selected": ["xxx"], "custom": ""}],
                }
            ),
            config,
        )
    )
    results = [e for e in _all_pending(frames) if e["kind"] == "tool_result"]
    assert results and results[0]["payload"]["ok"] is False
    assert "__interrupt__" not in {k for frame in frames for k in frame}


# ─── ws 层：澄清卡落库 / 互斥 / 广播 / 回执 ───


class _Row:
    def __init__(self, session_id: str = "s-1") -> None:
        self.id = session_id
        self.user_id = "u-1"
        self.pending_confirm: dict | None = None
        self.pending_confirm_author_id: str | None = None
        self.compact_summary = None


class _FakeDb:
    """与 test_hybrid_h5_hitl 同构的卡行锁桩。"""

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


def _clarify_card(thread_id: str = "t-1") -> dict:
    return {
        "id": "call-clarify",
        "questions": [dict(q) for q in _QUESTIONS],
        "meta": {
            "schema_version": 2,
            "confirm_type": "clarify",
            "thread_id": thread_id,
            "owner_id": "u-1",
            "resume_nonce": "nonce-clarify",
        },
    }


def test_persist_clarify_writes_card_with_meta_and_whitelist() -> None:
    """澄清卡落库：白名单字段 + meta（confirm_type=clarify/thread_id/nonce）。"""
    db = _FakeDb()
    card = ws._persist_pending_clarify(
        db,
        "s-1",
        {
            "type": "clarify",
            "id": "call-clarify",
            "question": "选择评测类型",
            "options": None,
            "questions": [dict(q) for q in _QUESTIONS],
        },
        thread_id="t-1",
        user_id="u-1",
    )
    assert card["id"] == "call-clarify"
    assert "type" not in card  # 白名单过滤图内字段
    meta = db.row.pending_confirm["meta"]
    assert meta["schema_version"] == 2
    assert meta["confirm_type"] == "clarify"
    assert meta["thread_id"] == "t-1"
    assert meta["resume_nonce"]
    assert db.row.pending_confirm_author_id == "u-1"
    assert len(db.row.pending_confirm["questions"]) == 2


def test_persist_clarify_rejects_existing_any_card() -> None:
    """已有任何待处理卡（含 tool_approval）时澄清卡不覆盖 → CONCURRENCY。"""
    db = _FakeDb(_Row())
    db.row.pending_confirm = {"id": "call-bash", "meta": {"confirm_type": "tool_approval"}}
    with pytest.raises(AppError) as exc:
        ws._persist_pending_clarify(
            db, "s-1", {"id": "c", "questions": [dict(q) for q in _QUESTIONS]},
            thread_id="t-1", user_id="u-1",
        )
    assert exc.value.code == ErrorCode.CONCURRENCY
    assert db.row.pending_confirm["id"] == "call-bash"


def test_persist_clarify_rejects_bad_questions() -> None:
    db = _FakeDb(_Row())
    with pytest.raises(AppError) as exc:
        ws._persist_pending_clarify(
            db, "s-1", {"id": "c", "questions": [{"question": "没有 id"} ]},
            thread_id="t-1", user_id="u-1",
        )
    assert exc.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_graph_interrupt_clarify_frame_persists_and_broadcasts(monkeypatch) -> None:
    """__interrupt__ 帧（clarify）→ 行锁落卡 + clarify 事件广播（剥离 meta）。"""
    db = _FakeDb(_Row())
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    interrupt_payload = {
        "type": "clarify",
        "id": "call-9",
        "question": "选择评测类型",
        "options": ["benchmark", "rag"],
        "questions": [dict(q) for q in _QUESTIONS],
    }
    paused = await ws._handle_graph_interrupt(
        db,
        object(),
        ws._ConnectionState(),
        "s-1",
        (type("I", (), {"value": interrupt_payload})(),),
        thread_id="t-9",
        user_id="u-1",
    )
    assert paused is True
    assert db.row.pending_confirm["meta"]["confirm_type"] == "clarify"
    assert db.row.pending_confirm["meta"]["thread_id"] == "t-9"
    assert emitted and emitted[-1][0] == "clarify"
    assert emitted[-1][1]["id"] == "call-9"
    assert "meta" not in emitted[-1][1]


@pytest.mark.asyncio
async def test_clarify_reply_clears_card_emits_ack_and_resumes(monkeypatch) -> None:
    """有效作答：清卡 → clarify_ack 回执 → 原 thread_id 恢复回合。"""
    started: list[tuple[str, str, list[dict]]] = []

    def fake_start(_sid, _ws, _st, _uid, thread_id, card_id, answers) -> object:
        started.append((thread_id, card_id, answers))
        return object()

    monkeypatch.setattr(ws, "_start_clarify_resume", fake_start)
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    db = _FakeDb(_Row())
    db.row.pending_confirm = _clarify_card()
    db.row.pending_confirm_author_id = "u-1"
    await ws._handle_clarify_reply(
        db,
        object(),
        ws._ConnectionState(),
        "s-1",
        "u-1",
        {
            "id": "call-clarify",
            "answers": [{"id": "q1", "selected": ["benchmark"], "custom": ""}],
        },
    )
    assert db.row.pending_confirm is None  # 一次性清卡
    assert started == [("t-1", "call-clarify", [{"id": "q1", "selected": ["benchmark"], "custom": ""}])]
    assert emitted and emitted[-1][0] == "clarify_ack"
    assert emitted[-1][1] == {"ok": True, "id": "call-clarify"}


@pytest.mark.asyncio
async def test_clarify_reply_required_missing_rejected_keeps_card(monkeypatch) -> None:
    """必答题未答 → VALIDATION；卡保留可重答（不触发 resume）。"""
    started: list = []
    monkeypatch.setattr(ws, "_start_clarify_resume", lambda *_a, **_k: started.append(1) or object())
    db = _FakeDb(_Row())
    db.row.pending_confirm = _clarify_card()
    db.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        await ws._handle_clarify_reply(
            db, object(), ws._ConnectionState(), "s-1", "u-1",
            {"id": "call-clarify", "answers": [{"id": "q2", "custom": ""}]},
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.row.pending_confirm is not None  # 卡保留
    assert started == []


@pytest.mark.asyncio
async def test_clarify_reply_unknown_option_rejected(monkeypatch) -> None:
    """radio 越界选项 → VALIDATION；卡保留。"""
    db = _FakeDb(_Row())
    db.row.pending_confirm = _clarify_card()
    db.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        await ws._handle_clarify_reply(
            db, object(), ws._ConnectionState(), "s-1", "u-1",
            {"id": "call-clarify", "answers": [{"id": "q1", "selected": ["stress"], "custom": ""}]},
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.row.pending_confirm is not None


@pytest.mark.asyncio
async def test_clarify_reply_repeated_or_missing_card_rejected() -> None:
    """卡已消费（重复 reply）/ 无卡 → 拒绝，resume 至多一次。"""
    db = _FakeDb(_Row())  # 无卡
    with pytest.raises(AppError) as exc:
        await ws._handle_clarify_reply(
            db, object(), ws._ConnectionState(), "s-1", "u-1",
            {"id": "call-clarify", "answers": [{"id": "q1", "selected": ["benchmark"], "custom": ""}]},
        )
    assert exc.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_clarify_reply_wrong_owner_or_kind_rejected() -> None:
    """非 owner 或卡种不符（tool_approval 卡上发 clarify_reply）→ 拒绝且不改变状态。"""
    db = _FakeDb(_Row())
    db.row.pending_confirm = _clarify_card()
    db.row.pending_confirm_author_id = "u-2"
    with pytest.raises(AppError) as exc:
        await ws._handle_clarify_reply(
            db, object(), ws._ConnectionState(), "s-1", "u-1",
            {"id": "call-clarify", "answers": [{"id": "q1", "selected": ["benchmark"], "custom": ""}]},
        )
    assert exc.value.code == ErrorCode.UNAUTHORIZED

    db2 = _FakeDb(_Row())
    db2.row.pending_confirm = {
        "id": "call-bash",
        "meta": {"confirm_type": "tool_approval", "thread_id": "t-1", "resume_nonce": "x"},
    }
    db2.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        await ws._handle_clarify_reply(
            db2, object(), ws._ConnectionState(), "s-1", "u-1",
            {"id": "call-bash", "answers": [{"id": "q1", "selected": ["benchmark"], "custom": ""}]},
        )
    assert exc.value.code == ErrorCode.VALIDATION  # 审批卡不走 clarify_reply
