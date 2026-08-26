"""Harness WS 探针 L2：闲聊思考链契约（API.md think_final 在 completed 之前）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROBE_ROOT = Path(__file__).resolve().parents[3] / "tools" / "harness-ws-probe"
sys.path.insert(0, str(PROBE_ROOT))

from harness_ws_probe.expect import ExpectMatcher, ProbeAssertion  # noqa: E402
from harness_ws_probe.recorder import TraceRecorder  # noqa: E402
from harness_ws_probe.scenarios.chat import run_chat_turn  # noqa: E402
from harness_ws_probe.scripted import ScriptedProbe  # noqa: E402


def _down(trace: TraceRecorder, event: str, event_id: int, payload: dict) -> None:
    trace.record_down(
        {
            "event": event,
            "session_id": "s",
            "task_id": None,
            "event_id": event_id,
            "ts": "t",
            "payload": payload,
        }
    )


def test_l2_scripted_chat_matches_contract() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        await run_chat_turn(peer, "用一句话介绍你自己")

    asyncio.run(_run())


def test_l2_rejects_completed_before_think_final() -> None:
    """现网缺陷：think_final 落在 completed 之后，必须被 matcher 拦住。"""
    trace = TraceRecorder()
    _down(trace, "user_message", 1, {"content": "hi", "role": "user"})
    _down(trace, "thought", 1, {"text": "a", "stream": "think"})
    _down(trace, "assistant_message", 2, {"text": "你好", "role": "assistant"})
    _down(trace, "response.completed", 3, {"finish_reason": "stop", "role": "assistant"})
    _down(trace, "thought", 4, {"text": "a", "stream": "think_final"})
    with pytest.raises(ProbeAssertion, match="response.completed"):
        ExpectMatcher(trace).chat_turn_contract()


def test_l2_rejects_one_char_think_frames() -> None:
    trace = TraceRecorder()
    _down(trace, "user_message", 1, {"content": "hi", "role": "user"})
    for _ in range(24):
        _down(trace, "thought", 1, {"text": "字", "stream": "think"})
    _down(trace, "assistant_message", 2, {"text": "ok", "role": "assistant"})
    _down(trace, "thought", 3, {"text": "字" * 24, "stream": "think_final"})
    _down(trace, "response.completed", 4, {"finish_reason": "stop", "role": "assistant"})
    with pytest.raises(ProbeAssertion, match="一字一帧"):
        ExpectMatcher(trace).chat_turn_contract()


def test_l2_rejects_hidden_chain_of_thought() -> None:
    """API.md：think_final 不得下发 Here's a thinking process 隐藏稿。"""
    trace = TraceRecorder()
    _down(trace, "user_message", 1, {"content": "hi", "role": "user"})
    _down(
        trace,
        "thought",
        1,
        {"text": "Here's a thinking process: Analyze User Input", "stream": "think"},
    )
    _down(trace, "assistant_message", 2, {"text": "ok", "role": "assistant"})
    _down(
        trace,
        "thought",
        3,
        {
            "text": "Here's a thinking process: Analyze User Input",
            "stream": "think_final",
        },
    )
    _down(trace, "response.completed", 4, {"finish_reason": "stop", "role": "assistant"})
    with pytest.raises(ProbeAssertion, match="隐藏思维链"):
        ExpectMatcher(trace).chat_turn_contract()
