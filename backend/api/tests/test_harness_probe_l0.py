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
from harness_ws_probe.protocol import FORBIDDEN_DOWNLINK, is_transient  # noqa: E402
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


def test_tool_stream_events_are_transient() -> None:
    """V1.44：tool_progress / tool_output_delta 为瞬态帧，不落库、不占 event_id。"""
    for event in ("tool_progress", "tool_output_delta"):
        assert is_transient({"event": event, "payload": {}}) is True
    # 工具终态 tool_result 为持久事件，不得误判为瞬态
    assert is_transient({"event": "tool_result", "payload": {}}) is False


def test_tool_call_start_is_forbidden() -> None:
    """API.md §4.3 明确禁止旧事件名 tool_call_start。"""
    assert "tool_call_start" in FORBIDDEN_DOWNLINK
    trace = TraceRecorder()
    trace.record_down(
        {
            "event": "tool_call_start",
            "session_id": "s",
            "task_id": None,
            "event_id": 1,
            "ts": "t",
            "payload": {},
        }
    )
    with pytest.raises(ProbeAssertion, match="禁止的旧事件名"):
        ExpectMatcher(trace).event_whitelist()


def test_tool_approval_events_are_whitelisted() -> None:
    """危险 bash 的确认卡与回执必须纳入服务端下行事件白名单。"""
    trace = TraceRecorder()
    base = {"session_id": "s", "task_id": None, "ts": "t", "payload": {}}
    trace.record_down({**base, "event": "tool_approval", "event_id": 1})
    trace.record_down({**base, "event": "tool_approval_ack", "event_id": 2})
    ExpectMatcher(trace).event_whitelist()


def test_tool_stream_events_whitelisted_and_skipped_by_event_id() -> None:
    """tool_progress / tool_output_delta 属白名单事件，且不参与 event_id 单调性检查。"""
    trace = TraceRecorder()
    base = {"session_id": "s", "task_id": None, "ts": "t", "payload": {}}
    trace.record_down({**base, "event": "tool_progress", "event_id": None})
    trace.record_down({**base, "event": "tool_output_delta", "event_id": None})
    trace.record_down({**base, "event": "tool_result", "event_id": 5})
    matcher = ExpectMatcher(trace)
    matcher.event_whitelist()
    # 瞬态帧没有 event_id 也不得报「缺少 event_id」；持久 tool_result 照常校验
    matcher.event_ids_monotonic()


def test_monotonic_event_id() -> None:
    trace = TraceRecorder()
    base = {"session_id": "s", "task_id": None, "ts": "t", "payload": {}}
    trace.record_down({**base, "event": "error", "event_id": 2})
    trace.record_down({**base, "event": "error", "event_id": 1})
    with pytest.raises(ProbeAssertion, match="严格递增"):
        ExpectMatcher(trace).event_ids_monotonic()


def test_client_rejects_unknown_uplink() -> None:
    async def _run() -> None:
        client = ProbeClient("http://127.0.0.1:9")
        client._ws = object()
        with pytest.raises(Exception, match="未登记"):
            await client._send({"event": "slash", "payload": {}})

    asyncio.run(_run())


def test_client_accepts_tool_approval_ack_uplink() -> None:
    """危险工具确认回执是 API.md §4.4 的合法第五类上行。"""

    class _Ws:
        async def send(self, _raw: str) -> None:
            return None

    async def _run() -> None:
        client = ProbeClient("http://127.0.0.1:9")
        client._ws = _Ws()
        await client.send_tool_approval_ack("call-1", "reject")
        assert client.trace.uplink()[-1].event == "tool_approval_ack"

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
