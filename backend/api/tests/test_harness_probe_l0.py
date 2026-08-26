"""Harness WS 探针 L0：同一套场景 + ExpectMatcher，默认走 Scripted 对等端。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

PROBE_ROOT = Path(__file__).resolve().parents[3] / "tools" / "harness-ws-probe"
sys.path.insert(0, str(PROBE_ROOT))

from harness_ws_probe.client import ProbeClient, connect_expect_close  # noqa: E402
from harness_ws_probe.expect import ExpectMatcher, ProbeAssertion  # noqa: E402
from harness_ws_probe.protocol import FORBIDDEN_DOWNLINK  # noqa: E402
from harness_ws_probe.recorder import TraceRecorder  # noqa: E402
from harness_ws_probe.redact import redact  # noqa: E402
from harness_ws_probe.scenarios import l0  # noqa: E402
from harness_ws_probe.scripted import ScriptedProbe  # noqa: E402


def test_redact_strips_ticket_and_prompt() -> None:
    cleaned = redact(
        {"ticket": "abc", "payload": {"system_prompt": "secret", "kind": "benchmark"}}
    )
    assert cleaned["ticket"] == "<redacted>"
    assert cleaned["payload"]["system_prompt"] == "<redacted>"
    assert cleaned["payload"]["kind"] == "benchmark"


def test_forbidden_event_name() -> None:
    trace = TraceRecorder()
    trace.record_down(
        {
            "event": "message",
            "session_id": "s",
            "task_id": None,
            "event_id": 1,
            "ts": "t",
            "payload": {},
        }
    )
    with pytest.raises(ProbeAssertion, match="禁止的旧事件名"):
        ExpectMatcher(trace).event_whitelist()
    assert "message" in FORBIDDEN_DOWNLINK


def test_monotonic_event_id() -> None:
    trace = TraceRecorder()
    base = {"session_id": "s", "task_id": None, "ts": "t", "payload": {}}
    trace.record_down({**base, "event": "error", "event_id": 2})
    trace.record_down({**base, "event": "error", "event_id": 1})
    with pytest.raises(ProbeAssertion, match="严格递增"):
        ExpectMatcher(trace).event_ids_monotonic()


def test_client_rejects_fifth_uplink() -> None:
    async def _run() -> None:
        client = ProbeClient("http://127.0.0.1:9")
        client._ws = object()
        with pytest.raises(Exception, match="第五种"):
            await client._send({"event": "slash", "payload": {}})

    asyncio.run(_run())


def test_l0_handshake_scripted() -> None:
    asyncio.run(l0.run_handshake_scripted(ScriptedProbe()))


def test_l0_unknown_event() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_unknown_event(peer)

    asyncio.run(_run())


def test_l0_help() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_help(peer)

    asyncio.run(_run())


def test_l0_cancel_empty() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_cancel_empty(peer)

    asyncio.run(_run())


def test_l0_stress_and_cancel_confirm() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_stress_and_cancel_confirm(peer)

    asyncio.run(_run())


def test_l0_idempotent_client_message() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_idempotent_client_message(peer)

    asyncio.run(_run())


def test_l0_help_then_idempotent_same_session() -> None:
    """同一条 Trace 先 /help 再幂等，不得把上一轮 completed 算进本轮。"""

    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_help(peer)
        await l0.run_idempotent_client_message(peer)

    asyncio.run(_run())


def test_l0_reconnect_replay() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await l0.run_reconnect_replay(peer)

    asyncio.run(_run())


@pytest.mark.skipif(not os.environ.get("HARNESS_PROBE_BASE"), reason="未设置 HARNESS_PROBE_BASE")
def test_l0_live_handshake() -> None:
    async def _run() -> None:
        base = os.environ["HARNESS_PROBE_BASE"]
        insecure = os.environ.get("HARNESS_PROBE_INSECURE") == "1"
        await connect_expect_close(
            base,
            ticket="invalid",
            session_id=None,
            insecure=insecure,
            expect_code=4401,
        )
        client = ProbeClient(base, insecure=insecure)
        try:
            await client.login()
            await client.create_session()
            await client.connect()
            await l0.run_unknown_event(client)
            await l0.run_cancel_empty(client)
            await l0.run_stress_and_cancel_confirm(client)
        finally:
            await client.close()

    asyncio.run(_run())
