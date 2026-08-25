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


def test_next_event_id_locks_session_row():
    """与 Worker push_ws 共用会话行锁，避免并发撞号后静默丢事件。"""

    class _Db:
        def __init__(self) -> None:
            self.locked = False
            self._step = 0

        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def with_for_update(self):
            self.locked = True
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            self._step += 1
            if self._step == 1:
                return ("s-1",)
            return (4,)

    db = _Db()
    assert ws._next_event_id(db, "s-1") == 5
    assert db.locked is True


def test_persist_pending_confirm_strips_author_meta():
    """确认卡落库只保留 TaskSpec，作者写入独立列。"""

    class _Session:
        def __init__(self) -> None:
            self.pending_confirm = None
            self.pending_confirm_author_id = None
            self.user_id = "u-owner"

    session = _Session()

    class _Db:
        committed = False

        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return session

        def commit(self) -> None:
            self.committed = True

    db = _Db()
    ws._persist_pending_confirm(
        db,
        "s-1",
        {
            "kind": "benchmark",
            "dataset_id": "d1",
            "confirm_author": {"id": "u-author", "username": "alice"},
        },
    )
    assert session.pending_confirm == {"kind": "benchmark", "dataset_id": "d1"}
    assert session.pending_confirm_author_id == "u-author"
    assert db.committed is True


def test_confirm_author_payload_uses_display_name() -> None:
    """confirm 事件补作者元数据，供前端展示与落库 author_id。"""
    user = User(id="u-1", username="alice", display_name="Alice")
    assert ws._confirm_author_payload(user) == {
        "id": "u-1",
        "username": "alice",
        "display_name": "Alice",
    }
    assert ws._confirm_author_payload(None) is None
