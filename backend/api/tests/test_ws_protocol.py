"""WebSocket 流式事件语义回归测试。"""

import pytest

from app.models import Session as AgentSession
from app.models import User
from app.routers import ws


class _MessageDb:
    """承载用户消息写入流程的最小数据库桩。"""

    def __init__(self) -> None:
        self.row = None

    def add(self, row) -> None:
        self.row = row

    def query(self, *_args):
        """模拟幂等键查询，默认没有重复消息。"""
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return None

    def flush(self) -> None:
        self.row.id = "m-1"

    def commit(self) -> None:
        pass


@pytest.mark.asyncio
async def test_user_echo_uses_user_message_event(monkeypatch):
    """用户回显必须使用独立事件，不能再占用助手 message 语义。"""
    emitted: list[str] = []

    async def fake_emit(_db, _websocket, _state, _session_id, event, _payload):
        emitted.append(event)
        return True

    async def fake_run_turn(*_args, **_kwargs):
        return None

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_run_turn", fake_run_turn)

    task = await ws._handle_user_message(
        _MessageDb(),
        object(),
        ws._ConnectionState(),
        AgentSession(id="s-1", user_id="u-1", title="测试会话", visibility="private"),
        User(id="u-1", username="alice"),
        {"text": "你好", "attachments": [], "client_message_id": "browser-1"},
        None,
    )
    await task

    assert emitted == ["user_message"]


def test_response_completed_keeps_public_identifiers():
    """完成事件沿用公共头并携带 assistant 生命周期信息。"""
    frame = ws._frame(
        "s-1",
        "response.completed",
        8,
        {"finish_reason": "stop", "role": "assistant"},
        task_id="t-1",
    )

    assert frame["session_id"] == "s-1"
    assert frame["task_id"] == "t-1"
    assert frame["event_id"] == 8
    assert frame["payload"] == {"finish_reason": "stop", "role": "assistant"}
