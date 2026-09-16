"""三档权限等级：按档位 + 工具 + 命令风险裁决「自动 / 审批 / 拒绝」。

档位语义（全局默认 + 会话可覆盖）：
- ``tier1`` 请求批准：非只读工具一律审批（含 web_*），bash 普通命令也审批；
- ``tier2`` 帮我批准：工作区内写、联网、bash 普通命令自动；bash 破坏级命令审批；
- ``tier3`` 完全访问：全部自动，**但 bash 破坏级命令仍审批、灾难级仍拒绝**。

``decide`` 是唯一裁决入口，被 ``PlatformLoopTool.approval_decision`` 消费；
``disaster`` 直接 ``deny``（不进审批），在 ``check_permission`` 抛 DENIED。
"""

from __future__ import annotations

from .command_risk import classify

TIER1 = "tier1"
TIER2 = "tier2"
TIER3 = "tier3"
TIERS: tuple[str, ...] = (TIER1, TIER2, TIER3)
DEFAULT_TIER = TIER1

# 恒自动（只读 + 交互/业务确认，后者走各自卡片，不叠加审批）。
_ALWAYS_AUTO = frozenset(
    {
        "read", "read_image", "glob", "grep",
        "ask_user_question", "task.create", "task.status", "task.cancel", "task",
        "agent.list", "agent.spawn", "agent.status", "agent.wait", "agent.result", "agent.cancel",
    }
)


def normalize(value: str | None) -> str:
    """归一档位；非法/空回落默认档（fail-safe，不放大权限）。"""
    tier = str(value or "").strip().lower()
    return tier if tier in TIERS else DEFAULT_TIER


def sandbox_mode_for(tier: str | None) -> str:
    """档位 → 网络模式：档3 保留网络，档1/2 断网（isolated）。"""
    return "network" if normalize(tier) == TIER3 else "isolated"


def decide(tool_name: str, args: dict, tier: str | None) -> str:
    """返回 ``"auto" | "approval" | "deny"``。"""
    normalized = normalize(tier)
    if tool_name == "bash":
        risk = classify(str((args or {}).get("command") or ""))
        if risk == "disaster":
            return "deny"
        if risk == "destructive":
            return "approval"  # 三档都审批（含档3）
        return "approval" if normalized == TIER1 else "auto"
    if tool_name in _ALWAYS_AUTO:
        return "auto"
    # write / edit / web_search / web_fetch / 其余副作用工具
    return "approval" if normalized == TIER1 else "auto"
