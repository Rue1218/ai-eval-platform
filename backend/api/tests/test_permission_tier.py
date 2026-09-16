"""三档权限裁决矩阵测试。"""

from __future__ import annotations

import pytest

from app.harness.security import permission_tier as pt


def test_normalize_falls_back_to_default() -> None:
    assert pt.normalize("tier2") == "tier2"
    assert pt.normalize("TIER3") == "tier3"
    assert pt.normalize("bogus") == pt.DEFAULT_TIER
    assert pt.normalize(None) == pt.DEFAULT_TIER


def test_sandbox_mode_per_tier() -> None:
    assert pt.sandbox_mode_for("tier1") == "isolated"
    assert pt.sandbox_mode_for("tier2") == "isolated"
    assert pt.sandbox_mode_for("tier3") == "network"


@pytest.mark.parametrize("tier", ["tier1", "tier2", "tier3"])
def test_read_and_interaction_always_auto(tier: str) -> None:
    assert pt.decide("read", {}, tier) == "auto"
    assert pt.decide("read_image", {}, tier) == "auto"
    assert pt.decide("glob", {}, tier) == "auto"
    assert pt.decide("grep", {}, tier) == "auto"
    assert pt.decide("ask_user_question", {}, tier) == "auto"
    assert pt.decide("task.create", {}, tier) == "auto"
    assert pt.decide("agent.spawn", {}, tier) == "auto"
    assert pt.decide("agent.cancel", {}, tier) == "auto"


@pytest.mark.parametrize("tool", ["write", "edit", "web_search", "web_fetch"])
def test_side_effect_tools_tier1_only(tool: str) -> None:
    assert pt.decide(tool, {}, "tier1") == "approval"
    assert pt.decide(tool, {}, "tier2") == "auto"
    assert pt.decide(tool, {}, "tier3") == "auto"


def test_bash_normal_per_tier() -> None:
    args = {"command": "echo hi"}
    assert pt.decide("bash", args, "tier1") == "approval"
    assert pt.decide("bash", args, "tier2") == "auto"
    assert pt.decide("bash", args, "tier3") == "auto"


@pytest.mark.parametrize("tier", ["tier1", "tier2", "tier3"])
def test_bash_destructive_always_approval(tier: str) -> None:
    assert pt.decide("bash", {"command": "rm -rf /tmp/x"}, tier) == "approval"


@pytest.mark.parametrize("tier", ["tier1", "tier2", "tier3"])
def test_bash_disaster_always_deny(tier: str) -> None:
    assert pt.decide("bash", {"command": "rm -rf /"}, tier) == "deny"
    assert pt.decide("bash", {"command": "mkfs.ext4 /dev/sda"}, tier) == "deny"
