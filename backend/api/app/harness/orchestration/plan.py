"""Harness 编排层：规划解析（M4 阶段 4，OR-2/OR-3）。

``build_plan`` 严格 JSON 解析为 ``PlanArtifact``（调 M1 ``parse_plan_protocol``
做协议校验）；失败重试一次，仍失败走 L0 规则降级；降级产物必须经 reflect
复核（FB-2）。预算由 ``budget_for_plan`` 按 plan 派生（count-only）。
"""

from __future__ import annotations

from app.errors import AppError, ErrorCode
from app.harness.contracts import PlanArtifact, validate_plan_artifact
from app.harness.orchestration.budget import Budget, from_dict
from app.harness.prompts import parse_plan_protocol

# L0 规则降级关键词 → 意图（build_plan 失败降级用）
_L0_INTENT_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("评测", "运行基准评测"),
    ("测试", "运行基准评测"),
    ("压测", "运行压测"),
    ("用例", "生成测试用例"),
    ("知识库", "知识库评测"),
)


def _l0_fallback(raw: str) -> PlanArtifact | None:
    """L0 规则降级：按关键词构造最小 PlanArtifact（须经 reflect 复核）。"""
    for keyword, intent in _L0_INTENT_KEYWORDS:
        if keyword in raw:
            return PlanArtifact(
                intent=intent,
                skill_id=None,
                slots={},
                tools_needed=(),
                delivery="chat",
                budget={"model_calls": 2, "tool_turns": 1},
                allows_replan=False,
                notes="L0 规则降级产物，需复核",
            )
    return None


def build_plan(raw: str) -> PlanArtifact:
    """严格 JSON 解析为 PlanArtifact；失败重试一次，仍失败走 L0 降级。

    降级产物必须经 reflect 复核（FB-2）；无法降级时抛
    AppError(VALIDATION, "无法识别任务意图")。
    """
    parse_errors: list[str] = []
    for _ in range(2):  # 重试一次
        try:
            result = parse_plan_protocol(raw)
            return validate_plan_artifact(dict(result["fields"]))
        except AppError as exc:
            parse_errors.append(exc.message)
    fallback = _l0_fallback(raw)
    if fallback is not None:
        return fallback
    raise AppError(ErrorCode.VALIDATION, "无法识别任务意图")


def budget_for_plan(plan: PlanArtifact, base: Budget | None = None) -> Budget:
    """按 plan.budget 派生预算（count-only，OR-5）；缺省回退默认预算。"""
    plan_budget = plan.budget or {}
    base_budget = base or from_dict({})
    return Budget(
        model_calls=int(plan_budget.get("model_calls", base_budget.model_calls)),
        tool_turns=int(plan_budget.get("tool_turns", base_budget.tool_turns)),
    )
