"""L0 契约场景：不打模型、不入队。"""

from __future__ import annotations

from typing import Any, Protocol

from ..errors import ProbeError
from ..expect import ExpectMatcher
from ..protocol import CLOSE_SESSION, CLOSE_TICKET
from ..recorder import TraceRecorder


class _Session(Protocol):
    trace: TraceRecorder
    session_id: str | None
    last_event_id: int
    close_code: int | None

    async def connect(
        self,
        *,
        session_id: str | None = None,
        last_event_id: int = 0,
        ticket: str | None = None,
    ) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_user_message(
        self,
        text: str,
        *,
        attachments: list[dict[str, str]] | None = None,
        client_message_id: str | None = None,
    ) -> None: ...

    async def send_confirm_ack(self, ok: bool, patch: dict[str, Any] | None = None) -> None: ...

    async def send_raw(self, message: dict[str, Any]) -> None: ...

    async def wait_event(self, name: str, timeout_s: float = 20.0) -> dict[str, Any]: ...

    async def drain(self, seconds: float = 0.4) -> None: ...


async def run_unknown_event(client: _Session) -> ExpectMatcher:
    await client.send_raw({"event": "slash", "payload": {}})
    await client.wait_event("error")
    matcher = ExpectMatcher(client.trace)
    matcher.public_headers()
    matcher.event_whitelist()
    matcher.event_ids_monotonic()
    matcher.error("VALIDATION", "不支持的 WebSocket 事件")
    matcher.no_forbidden_uplink(allowed_raw=True)
    return matcher


async def run_help(client: _Session) -> ExpectMatcher:
    await client.send_user_message("/help")
    await client.wait_event("assistant_message")
    await client.wait_event("response.completed")
    matcher = ExpectMatcher(client.trace)
    matcher.public_headers()
    matcher.event_whitelist()
    matcher.help_completed()
    return matcher


async def run_cancel_empty(client: _Session) -> ExpectMatcher:
    await client.send_user_message("/cancel")
    await client.wait_event("error")
    matcher = ExpectMatcher(client.trace)
    matcher.cancel_empty()
    return matcher


async def run_stress_and_cancel_confirm(client: _Session) -> ExpectMatcher:
    await client.send_user_message("/stress")
    await client.wait_event("confirm")
    matcher = ExpectMatcher(client.trace)
    matcher.stress_confirm()
    await client.send_confirm_ack(False)
    await client.wait_event("confirm_ack")
    await client.drain(0.3)
    matcher.confirm_cancelled()
    return matcher


async def run_idempotent_client_message(client: _Session) -> ExpectMatcher:
    key = "probe-idempotent-1"
    mark = len(client.trace.frames)
    await client.send_user_message("/help", client_message_id=key)
    await client.wait_event("response.completed")
    await client.send_user_message("/help", client_message_id=key)
    await client.drain(0.4)
    matcher = ExpectMatcher(client.trace)
    matcher.completed_once(after_frame=mark)
    return matcher


async def run_reconnect_replay(client: _Session) -> ExpectMatcher:
    await client.send_user_message("/cancel")
    await client.wait_event("error")
    cursor = client.last_event_id
    await client.disconnect()
    await client.connect(session_id=client.session_id, last_event_id=cursor)
    await client.drain(0.6)
    matcher = ExpectMatcher(client.trace)
    matcher.replay_no_transient()
    return matcher


async def run_handshake_scripted(client: _Session) -> None:
    """Scripted 对等端：invalid ticket → 4401，missing session → 4404。"""
    try:
        await client.connect(ticket="invalid")
        raise ProbeError("非法 ticket 应当关闭连接")
    except Exception:
        if getattr(client, "close_code", None) != CLOSE_TICKET:
            raise ProbeError(f"非法 ticket 期望 4401，实际 {client.close_code}") from None
    try:
        await client.connect(session_id="missing", ticket="ok")
        raise ProbeError("不存在会话应当关闭连接")
    except Exception:
        if getattr(client, "close_code", None) != CLOSE_SESSION:
            raise ProbeError(f"缺失会话期望 4404，实际 {client.close_code}") from None
