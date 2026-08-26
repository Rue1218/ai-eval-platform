"""Harness WS 探针 L1：入队必须显式允许，且强制 sample_size=1。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROBE_ROOT = Path(__file__).resolve().parents[3] / "tools" / "harness-ws-probe"
sys.path.insert(0, str(PROBE_ROOT))

from harness_ws_probe.errors import ProbeError  # noqa: E402
from harness_ws_probe.scenarios.l1 import enqueue_patch, run_confirm_enqueue  # noqa: E402
from harness_ws_probe.scripted import ScriptedProbe  # noqa: E402


def test_enqueue_patch_is_safe() -> None:
    patch = enqueue_patch()
    assert patch["run"]["sample_size"] == 1
    assert patch["with_stress"] is False


def test_l1_requires_allow_enqueue() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        with pytest.raises(ProbeError, match="allow-enqueue"):
            await run_confirm_enqueue(peer, allow_enqueue=False)

    asyncio.run(_run())


def test_l1_enqueue_returns_task_id() -> None:
    async def _run() -> None:
        peer = ScriptedProbe()
        await peer.connect()
        matcher = await run_confirm_enqueue(peer, allow_enqueue=True)
        assert matcher.confirm_enqueued()

    asyncio.run(_run())
