"""Harness 工作记忆（M3 阶段 1，MEM-1）。

本轮 Plan、observations、停止标志为回合内暂态：回合结束**不持久化为系统
事实**；下一回合 GraphState 重置（阶段 0/1 由进程内会话注册表承载，阶段 3
起由 Checkpointer 按 thread_id 隔离回合）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def new_working() -> dict[str, Any]:
    """构造空工作记忆字段（observations=[], stop_flag=False）。"""
    return {
        "observations": [],
        "stop_flag": False,
    }


def reset_working(state: dict) -> dict[str, Any]:
    """回合清理：清零 observations/stop_flag；plan 按 allows_replan 决定保留。

    返回更新 patch（供图外/节点间清理使用）。``allows_replan=True`` 时保留
    plan 供补规划；否则一并清除（MEM-1：工作记忆回合结束不持久化）。
    """
    patch: dict[str, Any] = {"observations": [], "stop_flag": False}
    plan = state.get("plan")
    if plan is not None:
        allows_replan = bool(
            isinstance(plan, Mapping) and plan.get("allows_replan", False)
        )
        if not allows_replan:
            patch["plan"] = None
    return patch
