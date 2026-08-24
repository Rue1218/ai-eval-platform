"""Harness 反馈层：失败反馈预算（M6 阶段 4，FB-4）。

与 M4 ``orchestration/budget.py``（模型/工具轮次预算）区分：本层管**失败
反馈**预算——超熔断阈值不再重试，转 ``NodeEvent(error)``，禁止无限重试。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.errors import AppError, ErrorCode


@dataclass(frozen=True, slots=True)
class FeedbackBudget:
    """失败反馈预算（FB-4）。"""

    failures: int = 0
    max_failures: int = 3  # 熔断阈值


def consume_failure(budget: FeedbackBudget) -> FeedbackBudget:
    """失败 +1；超 max_failures 熔断（抛 AppError(BUDGET_EXCEEDED)）。"""
    if budget.failures >= budget.max_failures:
        raise AppError(ErrorCode.BUDGET_EXCEEDED, "失败反馈次数已达上限，已停止重试")
    return FeedbackBudget(budget.failures + 1, budget.max_failures)


def is_exhausted(budget: FeedbackBudget) -> bool:
    """是否已熔断（禁止再重试）。"""
    return budget.failures >= budget.max_failures
