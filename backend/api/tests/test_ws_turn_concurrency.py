"""Harness WebSocket 回合租约、回放游标与多连接广播竞态测试。"""

from __future__ import annotations

import asyncio

import pytest

from app.errors import AppError, ErrorCode
from app.routers import ws, ws_turns
from app.session_connections import SessionConnectionHub


class _Db:
    """回放测试使用的最小查询桩。"""

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return []


class _WebSocket:
    """只记录发送帧的 WebSocket 桩。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.sent.append(frame)


class _State:
    """连接 Hub 所需的游标和异步发送锁。"""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.cursor = 0


@pytest.mark.asyncio
async def test_turn_reservation_is_shared_across_connections(monkeypatch):
    """没有共享 local task 时，第二条连接也必须收到 CONCURRENCY。"""
    monkeypatch.setattr(ws_turns, "_SESSION_TURNS", {})
    monkeypatch.setattr(ws_turns, "_SESSION_ABORTS", {})
    handle = ws._reserve_turn("s-1", "u-1")
    gate = asyncio.Event()
    task = asyncio.create_task(gate.wait())
    handle.task = task
    try:
        with pytest.raises(AppError) as error:
            ws._reserve_turn("s-1", "u-2")
        assert error.value.code == ErrorCode.CONCURRENCY
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        ws._release_turn(handle, task)


@pytest.mark.asyncio
async def test_stale_turn_cleanup_keeps_new_abort(monkeypatch):
    """旧回合完成回调不得删除已经替换的新回合 abort 令牌。"""
    monkeypatch.setattr(ws_turns, "_SESSION_TURNS", {})
    monkeypatch.setattr(ws_turns, "_SESSION_ABORTS", {})
    old = ws._reserve_turn("s-1", "u-1")
    new = ws._TurnHandle("s-1:new", "u-2", asyncio.Event())
    ws_turns._SESSION_TURNS["s-1"] = new
    ws_turns._SESSION_ABORTS["s-1"] = new.abort

    ws._release_turn(old)

    assert ws_turns._SESSION_TURNS["s-1"] is new
    assert ws_turns._SESSION_ABORTS["s-1"] is new.abort


@pytest.mark.asyncio
async def test_terminal_claim_is_exactly_once(monkeypatch):
    """正常完成与 stop 竞态下只能有一个路径领取 completed。"""
    monkeypatch.setattr(ws_turns, "_SESSION_TURNS", {})
    monkeypatch.setattr(ws_turns, "_SESSION_ABORTS", {})
    handle = ws._reserve_turn("s-1", "u-1")
    try:
        assert ws._claim_terminal("s-1", handle.turn_id) is True
        assert ws._claim_terminal("s-1", handle.turn_id) is False
    finally:
        ws._release_turn(handle)


@pytest.mark.asyncio
async def test_stop_requires_turn_owner(monkeypatch):
    """共享会话中协作者不得停止其他成员发起的回合。"""
    monkeypatch.setattr(ws_turns, "_SESSION_TURNS", {})
    monkeypatch.setattr(ws_turns, "_SESSION_ABORTS", {})
    handle = ws._reserve_turn("s-1", "u-owner")
    try:
        with pytest.raises(AppError) as error:
            await ws._handle_stop(
                None,
                object(),
                ws._ConnectionState(),
                "s-1",
                None,
                "u-member",
            )
        assert error.value.code == ErrorCode.UNAUTHORIZED
    finally:
        ws._release_turn(handle)


@pytest.mark.asyncio
async def test_replay_advances_cursor_when_no_rows():
    """重连没有待补发事件时也要承接 last_event_id，避免 Worker 旧事件重发。"""
    state = ws._ConnectionState()
    websocket = _WebSocket()

    await ws._replay_events(_Db(), websocket, state, "s-1", 17)

    assert state.cursor == 17
    assert websocket.sent == []


@pytest.mark.asyncio
async def test_hub_queues_persistent_event_during_replay():
    """回放期间的持久事件先排队，激活后按 event_id 只发送一次。"""
    hub = SessionConnectionHub()
    state = _State()
    websocket = _WebSocket()
    hub.register("c-1", "s-1", "u-1", websocket, state, ready=False)
    frame = {
        "event": "assistant_message",
        "session_id": "s-1",
        "task_id": None,
        "event_id": 4,
        "ts": "2026-09-01T00:00:00Z",
        "payload": {"text": "ok"},
    }

    assert await hub.broadcast_event("s-1", frame) is True
    assert websocket.sent == []
    assert await hub.activate("s-1", "c-1") is True
    assert websocket.sent == [frame]
    assert state.cursor == 4

    # 重复广播同一 event_id 不得再次发送。
    await hub.broadcast_event("s-1", frame)
    assert websocket.sent == [frame]


@pytest.mark.asyncio
async def test_hub_drops_transient_chunk_during_replay():
    """回放期间的瞬态 chunk 不入队，激活后只接收后续增量。"""
    hub = SessionConnectionHub()
    state = _State()
    websocket = _WebSocket()
    hub.register("c-1", "s-1", "u-1", websocket, state, ready=False)

    await hub.broadcast_chunk("s-1", lambda cursor: {"event": "assistant_delta", "event_id": cursor})
    await hub.activate("s-1", "c-1")
    assert websocket.sent == []

    await hub.broadcast_chunk("s-1", lambda cursor: {"event": "assistant_delta", "event_id": cursor})
    assert len(websocket.sent) == 1
