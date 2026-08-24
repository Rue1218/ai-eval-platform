"""Harness 编排层：预算（M4 阶段 2，OR-4/OR-5）。

预算为**计数型**（count-only）：model_calls / tool_turns 整数，不含 token
预算（V0.4.2 裁决）。消费在 M4 节点内调用；耗尽时返回
``is_budget_exhausted`` 供条件边短路；超限结果记入 ``Observations``
（OR-4 重复调用/长路径抑制语义）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.errors import AppError, ErrorCode

# 阶段 2 默认预算（LLM 往返 / 工具轮次上限）
DEFAULT_BUDGET = {"model_calls": 4, "tool_turns": 4}


@dataclass(frozen=True, slots=True)
class Budget:
    """计数型预算（count-only，OR-5）。"""

    model_calls: int = 4
    tool_turns: int = 4

    def to_dict(self) -> dict[str, int]:
        """投影为纯 dict（入 GraphState.budget）。"""
        return {"model_calls": self.model_calls, "tool_turns": self.tool_turns}


def from_dict(data: dict) -> Budget:
    """从 GraphState.budget 投影重建（缺省回退默认预算）。"""
    return Budget(
        model_calls=int(data.get("model_calls", DEFAULT_BUDGET["model_calls"])),
        tool_turns=int(data.get("tool_turns", DEFAULT_BUDGET["tool_turns"])),
    )


def consume_model_call(budget: Budget) -> Budget:
    """消费一次模型调用；超限抛 AppError(BUDGET_EXCEEDED, 409)。"""
    if budget.model_calls <= 0:
        raise AppError(ErrorCode.BUDGET_EXCEEDED, "模型调用次数预算耗尽")
    return Budget(budget.model_calls - 1, budget.tool_turns)


def consume_tool_turn(budget: Budget) -> Budget:
    """消费一次工具轮次；超限抛 AppError(BUDGET_EXCEEDED, 409)。"""
    if budget.tool_turns <= 0:
        raise AppError(ErrorCode.BUDGET_EXCEEDED, "工具轮次预算耗尽")
    return Budget(budget.model_calls, budget.tool_turns - 1)


def is_budget_exhausted(budget: Budget) -> bool:
    """任一计数为 0 即视为耗尽（条件边短路用）。"""
    return budget.model_calls <= 0 or budget.tool_turns <= 0
