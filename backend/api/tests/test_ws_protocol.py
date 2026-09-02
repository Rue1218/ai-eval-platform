"""WebSocket 流式事件语义回归测试。"""

import asyncio

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


def test_should_forward_worker_event() -> None:
    """转发循环只推 Worker 直产：progress/report，以及带 task_id 的 error。"""
    assert ws._should_forward_worker_event("progress", None) is True
    assert ws._should_forward_worker_event("report", "t-1") is True
    assert ws._should_forward_worker_event("error", "t-1") is True
    assert ws._should_forward_worker_event("error", None) is False
    assert ws._should_forward_worker_event("assistant_message", None) is False


@pytest.mark.asyncio
async def test_forward_loop_pushes_worker_events_and_skips_agent_error(monkeypatch):
    """M9-D8：按游标增量推送 Worker 事件，对话内 error 只推进游标不重发。"""

    class _Row:
        def __init__(self, event_id: int, event: str, payload: dict, task_id: str | None):
            self.event_id = event_id
            self.event = event
            self.payload = payload
            self.task_id = task_id
            self.ts = None

    batches = [
        [
            _Row(5, "progress", {"percent": 10}, "t-1"),
            _Row(6, "error", {"code": "INTERNAL", "message": "对话失败"}, None),
            _Row(7, "report", {"report_id": "r-1"}, "t-1"),
        ],
        [],
    ]

    class _Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return batches.pop(0) if batches else []

    class _Db:
        def query(self, *_args):
            return _Query()

        def close(self) -> None:
            pass

    sent: list[dict] = []

    class _WS:
        async def send_json(self, frame: dict) -> None:
            sent.append(frame)

    monkeypatch.setattr(ws, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(ws, "_FORWARD_POLL_S", 0.01)
    state = ws._ConnectionState()
    state.cursor = 4
    stop = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(ws._forward_loop(_WS(), state, "s-1", stop), _stop_soon())
    assert [frame["event"] for frame in sent] == ["progress", "report"]
    assert [frame["event_id"] for frame in sent] == [5, 7]
    assert state.cursor == 7



