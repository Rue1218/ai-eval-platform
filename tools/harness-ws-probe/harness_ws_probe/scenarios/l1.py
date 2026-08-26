"""L1 编排：confirm_ack 入队，强制抽样 1 且关闭先评后压。"""

from __future__ import annotations

from typing import Any, Protocol

from ..errors import ProbeError
from ..expect import ExpectMatcher
from ..recorder import TraceRecorder


class _Session(Protocol):
    trace: TraceRecorder

    async def send_user_message(
        self,
        text: str,
        *,
        attachments: list[dict[str, str]] | None = None,
        client_message_id: str | None = None,
    ) -> None: ...

    async def send_confirm_ack(self, ok: bool, patch: dict[str, Any] | None = None) -> None: ...

    async def wait_event(self, name: str, timeout_s: float = 20.0) -> dict[str, Any]: ...


def enqueue_patch() -> dict[str, Any]:
    """L1 固定补丁：避免默认 1000 样本与派生压测。"""
    return {"run": {"sample_size": 1}, "with_stress": False}


async def run_confirm_enqueue(client: _Session, *, allow_enqueue: bool) -> ExpectMatcher:
    if not allow_enqueue:
        raise ProbeError("L1 入队需要 --allow-enqueue")
    await client.send_user_message("/stress")
    await client.wait_event("confirm")
    await client.send_confirm_ack(True, enqueue_patch())
    await client.wait_event("confirm_ack")
    matcher = ExpectMatcher(client.trace)
    matcher.confirm_enqueued()
    return matcher
