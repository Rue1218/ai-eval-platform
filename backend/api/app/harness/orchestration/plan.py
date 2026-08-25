"""Harness 编排层：规划解析（M4 / P0+）。

``build_plan`` 严格 JSON 解析为 ``PlanArtifact``；失败重试一次，仍失败走
L0 规则降级。降级时合并全部命中技能（不再先命中先返回），步骤控制在
3–7 步；长工具不写入 ``tools_needed``（对话内只允许短工具 ``task``）。
"""

from __future__ import annotations

from app.errors import AppError, ErrorCode
from app.harness.contracts import PlanArtifact, validate_plan_artifact
from app.harness.orchestration.budget import Budget, from_dict
from app.harness.prompts import parse_plan_protocol
from app.harness.skills import DISABLED_SKILLS

# L0 技能组：关键词 → 意图 / skill_id / 步骤标题。不含过宽的「测试」。
# 英文别名与 detect_plan_intent 技能组对齐，避免「benchmark + testcase」规划失败。
_L0_SKILLS: tuple[tuple[str, str, str, str], ...] = (
    ("评测", "运行基准评测", "skill-benchmark", "确认基准评测的数据集与协议档"),
    ("benchmark", "运行基准评测", "skill-benchmark", "确认基准评测的数据集与协议档"),
    ("用例", "生成测试用例", "skill-testcase", "确认用例生成范围与策略"),
    ("testcase", "生成测试用例", "skill-testcase", "确认用例生成范围与策略"),
    ("知识库", "知识库评测", "skill-rag", "确认知识库评测前置（未接入须如实拒绝）"),
    ("rag", "知识库评测", "skill-rag", "确认知识库评测前置（未接入须如实拒绝）"),
    ("压测", "运行压测", "skill-stress", "确认压测仅能在评测成功后经确认卡派生"),
    ("stress", "运行压测", "skill-stress", "确认压测仅能在评测成功后经确认卡派生"),
)
_STRESS_PHRASES: tuple[str, ...] = ("先评后压", "先评再压", "评完再压")


def _dedupe(items: tuple[str, ...]) -> tuple[str, ...]:
    """保持顺序去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _matched_skills(raw: str) -> list[tuple[str, str, str]]:
    """收集全部命中技能 ``(intent, skill_id, step)``。"""
    hits: list[tuple[str, str, str]] = []
    if any(phrase in raw for phrase in _STRESS_PHRASES):
        hits.append(("运行基准评测", "skill-benchmark", "确认基准评测的数据集与协议档"))
        hits.append(("运行压测", "skill-stress", "确认压测仅能在评测成功后经确认卡派生"))
    for keyword, intent, skill_id, step in _L0_SKILLS:
        if keyword in raw:
            hits.append((intent, skill_id, step))
    unique: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in hits:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    return unique


def _build_steps(skills: list[tuple[str, str, str]], raw: str) -> list[str]:
    """生成 3–7 步清单：先落 task，再按技能确认槽位，最后说明长任务入队。"""
    steps = ["用 task 列出本轮步骤"]
    steps.extend(item[2] for item in skills)
    if any(item[1] == "skill-stress" for item in skills) or any(
        phrase in raw for phrase in _STRESS_PHRASES
    ):
        if "先评后压" not in "".join(steps):
            steps.append("遵守先评后压：对话路径不得直接发起压测确认卡")
    if any(item[1] in DISABLED_SKILLS for item in skills):
        steps.append("知识库评测未接入，必须如实告知，禁止伪装成功")
    steps.append("向用户说明长任务须经确认卡入队，对话内只执行短工具")
    if len(steps) < 3:
        steps.append("根据已有信息汇总结论与下一步")
    return steps[:7]


def _l0_fallback(raw: str) -> PlanArtifact | None:
    """L0 规则降级：合并全部命中技能，产出 3–7 步 PlanArtifact（须经 reflect）。"""
    skills = _matched_skills(raw)
    if not skills:
        return None
    steps = _build_steps(skills, raw)
    intents = _dedupe(tuple(item[0] for item in skills))
    skill_ids = _dedupe(tuple(item[1] for item in skills))
    needs_confirm = any(
        skill_id in {"skill-benchmark", "skill-testcase", "skill-rag", "skill-stress"}
        for skill_id in skill_ids
    )
    return PlanArtifact(
        intent="，并".join(intents),
        skill_id=skill_ids[0] if len(skill_ids) == 1 else None,
        slots={"steps": steps},
        tools_needed=("task",),
        delivery="confirm" if needs_confirm else "chat",
        budget={
            "model_calls": min(12, max(4, 2 + len(steps))),
            "tool_turns": min(12, max(4, 2 + len(steps))),
        },
        allows_replan=True,
        notes="L0 规则降级产物，需复核；步骤："
        + " / ".join(f"{index}.{title}" for index, title in enumerate(steps, start=1)),
    )


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
