"""Harness 编排层：规划解析（M4 / P0+）。

``build_plan`` 严格 JSON 解析为 ``PlanArtifact``；解析是纯函数，单次尝试，
失败即走 L0 规则降级。降级时合并全部命中技能（不再先命中先返回），步骤控制在
3–7 步；长工具不写入 ``tools_needed``（对话内只允许短工具 ``task``）。
"""

from __future__ import annotations

from dataclasses import replace

from app.errors import AppError, ErrorCode
from app.harness.contracts import PlanArtifact, TaskSessionState, validate_plan_artifact
from app.harness.orchestration.budget import Budget, from_dict
from app.harness.orchestration.router import short_tool_names
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

# 多短工具链的 L0 规划模板。规划模型不可用时仍可让内部图保留“先规划、再执行”
# 的边界，不把用户提供的 <PLAN> / ReAct 文本当作平台控制协议。
_SHORT_TOOL_STEPS: dict[str, str] = {
    "read": "使用 read 定位并读取所需文件或日志",
    "write": "使用 write 生成或更新交付文件",
    "edit": "使用 edit 修改目标文件并核对变更",
    "bash": "使用 bash 执行受控诊断或统计命令",
    "web_search": "使用 web_search 搜集所需公开信息",
    "web_fetch": "使用 web_fetch 抓取并核对目标网页",
}


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


def _build_steps(
    skills: list[tuple[str, str, str]], short_tools: tuple[str, ...], raw: str
) -> list[str]:
    """生成 3–7 步清单：先落 task，再按技能确认槽位，最后说明长任务入队。"""
    steps = ["用 task 列出本轮步骤"]
    steps.extend(_SHORT_TOOL_STEPS[name] for name in short_tools)
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
    short_tools = short_tool_names(raw)
    if not skills and len(short_tools) < 2:
        return None
    steps = _build_steps(skills, short_tools, raw)
    intents = _dedupe(
        (("执行多短工具链",) if short_tools else ()) + tuple(item[0] for item in skills)
    )
    skill_ids = _dedupe(tuple(item[1] for item in skills))
    needs_confirm = any(
        skill_id in {"skill-benchmark", "skill-testcase", "skill-rag", "skill-stress"}
        for skill_id in skill_ids
    )
    return PlanArtifact(
        intent="，并".join(intents),
        skill_id=skill_ids[0] if len(skill_ids) == 1 else None,
        slots={"steps": steps},
        tools_needed=_dedupe(("task",) + short_tools),
        delivery="confirm" if needs_confirm else "chat",
        budget={
            # native 模式每个工具步骤需 2 次模型调用（决策 + 回填后继续），
            # 加规划/路由/总结固定开销后，4 步任务实测 ≥12 次；公式按
            # 4 + steps*3 派生、上限 20（plan 任务本就多轮，防失控由上限保障）。
            "model_calls": min(20, max(6, 4 + len(steps) * 3)),
            "tool_turns": min(20, max(6, 4 + len(steps) * 3)),
        },
        allows_replan=True,
        notes="L0 规则降级产物，需复核；步骤："
        + " / ".join(f"{index}.{title}" for index, title in enumerate(steps, start=1)),
    )


def build_plan(raw: str, fail_reason: str = "") -> PlanArtifact:
    """严格 JSON 解析为 PlanArtifact；失败走 L0 降级。

    解析为纯函数（输入不变结果不变），单次尝试即降级，不做无效重试。
    降级产物必须经 reflect 复核（FB-2）；无法降级时抛
    AppError(VALIDATION, "无法识别任务意图")。

    ``fail_reason`` 为上一轮 Reflexion 打回的失败原因：只写入 notes（供模型 /
    复核消费），**不参与** L0 关键词匹配，避免失败文本里的词误命中技能。
    """
    try:
        result = parse_plan_protocol(raw)
        return validate_plan_artifact(dict(result["fields"]))
    except AppError:
        pass
    fallback = _l0_fallback(raw)
    if fallback is not None:
        if fail_reason:
            fallback = replace(
                fallback,
                notes=f"{fallback.notes}；上次执行失败：{fail_reason[:200]}",
            )
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


def task_state_from_plan(plan: PlanArtifact) -> TaskSessionState:
    """从 PlanArtifact 初始化结构化任务状态机（TaskSessionState）。

    优先读取 slots 中携带的 task_state 字典；缺省时根据 intent 与 steps 自动初始化，
    将尚未执行的步骤与信息缺口显式结构化，作为抗漂移与防提前总结的基准底座。
    """
    slots = plan.slots if isinstance(plan.slots, dict) else {}
    embedded = slots.get("task_state")
    if isinstance(embedded, dict):
        return TaskSessionState.from_dict(embedded)

    raw_steps = slots.get("steps")
    steps: list[str] = (
        [str(item).strip() for item in raw_steps if str(item).strip()]
        if isinstance(raw_steps, list | tuple)
        else []
    )
    current_step = steps[0] if steps else ""
    next_actions = tuple(steps[1:]) if len(steps) > 1 else ()

    # 初始关键信息缺口：仅把需要工具闭环的探查类步骤视为缺口；
    # 纯说明/总结/汇报类步骤由模型直接作答收尾（无工具调用），纳入缺口会
    # 永远无法消除，导致 can_deliver 恒 False（任务完成仍显示待执行）。
    missing_info = tuple(
        s
        for s in steps
        if not any(
            word in s
            for word in ("说明", "列出", "确认卡", "总结", "汇总", "报告", "介绍", "回答")
        )
    )

    return TaskSessionState(
        protocol="task_state",
        version="v1",
        goal=plan.intent or "完成用户指定任务",
        phase="exploring",
        completed_steps=(),
        current_step=current_step,
        next_actions=next_actions,
        failed_steps=(),
        current_hypothesis=str(slots.get("hypothesis") or ""),
        confirmed_facts=(),
        evidence=(),
        rejected_hypotheses=(),
        missing_info=missing_info,
        can_deliver=False,
        blocked_reason="",
        notes=plan.notes,
    )
