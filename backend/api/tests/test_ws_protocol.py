"""WebSocket 流式事件语义回归测试。"""

import asyncio

import pytest

from app.models import Dataset, ProtocolProfile, User
from app.models import Session as AgentSession
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


def test_confirm_author_payload_uses_display_name() -> None:
    """confirm 事件补作者元数据，供前端展示与落库 author_id。"""
    user = User(id="u-1", username="alice", display_name="Alice")
    assert ws._confirm_author_payload(user) == {
        "id": "u-1",
        "username": "alice",
        "display_name": "Alice",
    }
    assert ws._confirm_author_payload(None) is None


@pytest.mark.asyncio
async def test_handle_cancel_slash_cancels_session_task(monkeypatch):
    """/cancel 只取消本会话活动任务，并下发 task.cancel tool_result。"""
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _websocket, _state, _session_id, event, payload, task_id=None):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(
        ws,
        "cancel_task_safe",
        lambda arguments, _context: {
            "task_id": arguments["task_id"],
            "status": "cancelled",
            "kind": "benchmark",
        },
    )

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def all(self):
            return [type("Task", (), {"id": "t-1"})()]

    session = AgentSession(id="s-1", user_id="u-1", title="测", visibility="private")
    await ws._handle_cancel(
        _Db(),
        object(),
        ws._ConnectionState(),
        session,
        User(id="u-1", username="alice"),
    )
    assert emitted == [
        (
            "tool_result",
            {
                "name": "task.cancel",
                "ok": True,
                "data": {"task_id": "t-1", "status": "cancelled", "kind": "benchmark"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_handle_cancel_slash_without_active_task():
    """无活动任务时 /cancel 返回 VALIDATION。"""
    from app.errors import AppError, ErrorCode

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def all(self):
            return []

    with pytest.raises(AppError) as exc:
        await ws._handle_cancel(
            _Db(),
            object(),
            ws._ConnectionState(),
            AgentSession(id="s-1", user_id="u-1", title="测", visibility="private"),
            User(id="u-1", username="alice"),
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert "没有可取消" in exc.value.message


@pytest.mark.asyncio
async def test_handle_stress_slash_emits_quality_confirm(monkeypatch):
    """/stress 发出质量任务确认卡且 with_stress=true。"""
    emitted: list[tuple[str, dict]] = []
    persisted: list[dict] = []

    async def fake_emit(_db, _websocket, _state, _session_id, event, payload, task_id=None):
        emitted.append((event, payload))
        return True

    def fake_persist(_db, _session_id, payload):
        persisted.append(payload)

    class _Query:
        def filter(self, *_args):
            return self

        def with_for_update(self):
            return self

        def first(self):
            session = AgentSession(id="s-1", user_id="u-1", title="测", visibility="private")
            session.pending_confirm = None
            return session

        def all(self):
            return []

    class _Db:
        def query(self, *_args):
            return _Query()

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_persist_pending_confirm", fake_persist)

    from app.harness import memory as memory_pkg

    monkeypatch.setattr(memory_pkg, "read_prefs", lambda _db, _user_id: {"last_kind": "rag"})

    await ws._handle_stress(
        _Db(),
        object(),
        ws._ConnectionState(),
        AgentSession(id="s-1", user_id="u-1", title="测", visibility="private"),
        User(id="u-1", username="alice", display_name="Alice"),
    )
    assert len(emitted) == 1
    event, payload = emitted[0]
    assert event == "confirm"
    assert payload["kind"] == "rag"
    assert payload["with_stress"] is True
    assert payload["kind"] != "stress"
    assert persisted and persisted[0]["kind"] == "rag"


@pytest.mark.asyncio
async def test_handle_stress_drops_deleted_pref_profiles(monkeypatch):
    """偏好里的已删除协议档不得写进 /stress 确认卡。"""
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _websocket, _state, _session_id, event, payload, task_id=None):
        emitted.append((event, payload))
        return True

    class _Db:
        def query(self, target):
            class _Query:
                def filter(self, *_args):
                    return self

                def with_for_update(self):
                    return self

                def first(self):
                    session = AgentSession(id="s-1", user_id="u-1", title="测", visibility="private")
                    session.pending_confirm = None
                    return session

                def all(self):
                    owner = getattr(target, "class_", None)
                    if owner is ProtocolProfile:
                        return [("live-p",)]
                    if owner is Dataset:
                        return [("d1",)]
                    return []

            return _Query()

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_persist_pending_confirm", lambda *_args: None)

    from app.harness import memory as memory_pkg

    monkeypatch.setattr(
        memory_pkg,
        "read_prefs",
        lambda _db, _user_id: {
            "last_kind": "benchmark",
            "last_profile_ids": ["gone-p", "live-p"],
            "last_dataset_id": "d1",
        },
    )

    await ws._handle_stress(
        _Db(),
        object(),
        ws._ConnectionState(),
        AgentSession(id="s-1", user_id="u-1", title="测", visibility="private"),
        User(id="u-1", username="alice", display_name="Alice"),
    )
    payload = emitted[0][1]
    assert payload["profile_ids"] == ["live-p"]
    assert payload["dataset_id"] == "d1"
