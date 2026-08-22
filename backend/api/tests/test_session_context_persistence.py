"""会话历史上下文恢复回归测试。"""

from __future__ import annotations

from app.agent.defaults import WINDOW
from app.harness.context.meter import build_context_meter
from app.harness.memory.session_context_store import SessionContextStore
from app.models import Message, WsEvent
from app.models import Session as AgentSession


class _Query:
    """按模型返回固定消息/事件的查询桩。"""

    def __init__(self, model: object, rows: dict[object, list[object]]) -> None:
        self.model = model
        self.rows = rows

    def filter(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def all(self) -> list[object]:
        return self.rows.get(self.model, [])

    def first(self) -> object | None:
        return None


class _Db:
    """覆盖 ContextMeter 所需的消息、事件和配置查询。"""

    def __init__(self, rows: dict[object, list[object]]) -> None:
        self.rows = rows

    def query(self, model: object) -> _Query:
        return _Query(model, self.rows)


def test_context_meter_restores_skill_and_mcp_usage_from_events():
    """刷新后 skill/MCP 计数应来自持久化事件，而不是固定归零。"""
    session = AgentSession(id="s-context", user_id="u-owner", title="上下文")
    messages = [
        Message(id="m-1", session_id=session.id, role="user", content="你好"),
        Message(id="m-2", session_id=session.id, role="assistant", content="你好，我是 Agent"),
    ]
    events = [
        WsEvent(session_id=session.id, event_id=1, event="thought", payload={"skill_id": "skill-benchmark"}),
        WsEvent(session_id=session.id, event_id=2, event="tool_call", payload={"name": "model.list"}),
        WsEvent(session_id=session.id, event_id=3, event="tool_call", payload={"name": "model.list"}),
        WsEvent(session_id=session.id, event_id=4, event="tool_call", payload={"name": "dataset.list"}),
    ]
    db = _Db({Message: messages, WsEvent: events})

    store = SessionContextStore(db)
    persisted_skill, mcp_tools_count = store.capability_stats(session.id)
    meter = build_context_meter(
        store.window_messages(session, max_messages=WINDOW),
        compact_summary=session.compact_summary,
        persisted_skill=persisted_skill,
        mcp_tools_count=mcp_tools_count,
        max_tokens=store.profile_context_window(),
    )

    assert meter.messages == 2
    assert meter.skills == 1
    assert meter.mcp_tools_count == 2
    assert meter.skills_tokens > 0
