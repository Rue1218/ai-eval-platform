"""Plan-and-Solve 规划节点（M4 / 后续架构，§2.1 Planner）。

产出完整 ``PlanArtifact`` 事件后把控制权交给 ReAct 执行短工具；
``response.completed`` 由 ``reflect`` 在整轮结束后发出。规划失败则就地
收尾，不再进入执行层。

复杂任务走**一次短模型调用**生成 ``plan.v1`` JSON（Q3：LLM Planner）；
上游异常 / 产物解析失败均降级 L0 关键词规则，不另起第二条规划循环。
重规划时把上一轮 ``replan_reason`` 注入规划输入，避免重复产出相同计划。
"""

from __future__ import annotations

from collections.abc import Mapping

from langgraph.config import get_config

from app.agent.log import agent_trace
from app.agent.routing import user_text_from_state
from app.errors import AppError
from app.harness.contracts import PlanArtifact, from_dict, make_event, to_dict
from app.harness.memory import GraphState, rebuild_model_config
from app.harness.orchestration import (
    Budget,
    budget_for_plan,
    build_plan,
    consume_model_call,
    is_budget_exhausted,
    task_state_from_plan,
)
from app.harness.orchestration import from_dict as budget_from_dict
from app.harness.skills import assert_skill_enabled
from app.llm import ModelRequest

# 规划阶段输入（§2.1：仅复杂任务调 LLM，一次短调用出 plan.v1 JSON）
PLAN_STAGE_INPUT = """\
【当前阶段：任务规划】
请把用户任务拆解为 3–7 步计划，只输出 plan.v1 协议 JSON（禁止代码块外的说明）：
{"protocol": "plan", "version": "plan.v1", "intent": "意图", "skill_id": "技能或null", \
"slots": {"steps": ["步骤1", "步骤2"]}, "tools_needed": ["task"], \
"delivery": "chat或confirm", "budget": {"model_calls": 整数, "tool_turns": 整数}, \
"allows_replan": true或false, "notes": "补充说明"}
约束：
- tools_needed 只允许对话内短工具（如 task）；评测/用例/知识库/压测等长任务不写入，\
只能经确认卡入队；
- delivery=confirm 时 tools_needed 不得为空；
- 未接入能力（如知识库评测）必须在 notes 中如实说明，禁止伪装成功；
- 对话路径不得直接发起压测确认卡（先评后压）。"""


def _plan_summary(plan: PlanArtifact) -> str:
    """生成阶段思考摘要（不是 Observation 原文，也不是最终助手正文）。"""
    steps = plan.slots.get("steps") if isinstance(plan.slots, dict) else None
    if isinstance(steps, list) and steps:
        preview = " → ".join(str(item) for item in steps[:3])
        return f"已规划：{plan.intent}（{len(steps)} 步）。{preview}"
    tools = "、".join(plan.tools_needed) if plan.tools_needed else "待确认槽位"
    return f"已规划：{plan.intent}。交付={plan.delivery}，涉及工具：{tools}。"


def _failed(code: str, message: str) -> dict:
    """规划失败：清空 plan，带 completed，条件边走向 END。"""
    return {
        "plan": None,
        "pending_events": [
            make_event("error", {"code": code, "message": message}),
            make_event(
                "response.completed",
                {"finish_reason": "error", "role": "assistant"},
            ),
        ],
    }


def plan_solve_route(state: GraphState) -> str:
    """规划成功 → ReAct 执行；失败（无 plan）→ 结束。"""
    return "react_agent" if isinstance(state.get("plan"), dict) else "end"


def _plan_gateway_config(run_config: object) -> dict[str, object]:
    """仅向规划模型调用传递取消回调，隔离会话凭据与工具原文（同 ReAct）。"""
    configurable = (run_config or {}).get("configurable") if isinstance(run_config, dict) else None
    abort = configurable.get("abort") if isinstance(configurable, Mapping) else None
    return (
        {"configurable": {"abort": dict(abort)}}
        if isinstance(abort, Mapping)
        else {"configurable": {}}
    )


def _generate_plan(
    state: GraphState,
    raw: str,
    fail_reason: str,
    gateway: object | None,
) -> tuple[PlanArtifact, bool]:
    """生成 PlanArtifact：复杂任务一次短模型调用，失败全部降级 L0 规则。

    返回 ``(plan, used_llm)``；``used_llm=True`` 表示已消费一次模型调用预算。
    预算耗尽 / 无网关 / 上游异常 / 产物非法时均回退 ``build_plan`` 规则路径，
    规划阶段不得把异常裸抛给整轮收尾。
    """
    run_config = get_config()
    configurable = (run_config or {}).get("configurable") or {}
    api_key = str(configurable.get("credentials", {}).get("api_key") or "")
    budget = budget_from_dict(state.get("budget") or {})
    invoke = getattr(gateway, "invoke", None)
    if gateway is None or not callable(invoke) or is_budget_exhausted(budget):
        return build_plan(raw, fail_reason=fail_reason), False
    prompt = PLAN_STAGE_INPUT + f"\n\n用户任务：{raw}"
    if fail_reason:
        prompt += f"\n上一轮执行失败原因（请在计划中规避）：{fail_reason[:200]}"
    request = ModelRequest(
        config=rebuild_model_config(state["request"], api_key=api_key),  # type: ignore[arg-type]
        messages=({"role": "user", "content": prompt},),
        system=None,
        tools=(),
    )
    try:
        budget = consume_model_call(budget)
    except AppError:
        # 预算已尽：不再发起规划模型调用，直接走规则降级
        return build_plan(raw, fail_reason=fail_reason), False
    try:
        response = invoke(request, config=_plan_gateway_config(run_config))
        agent_trace("planner LLM 调用成功")
    except AppError as exc:
        agent_trace(f"planner LLM 调用失败 code={exc.code.value}，降级 L0")
        return build_plan(raw, fail_reason=fail_reason), True
    except Exception as exc:  # 内部异常归一，禁止裸抛给浏览器（§5.2.1）
        agent_trace(f"planner LLM 内部异常 type={type(exc).__name__}，降级 L0")
        return build_plan(raw, fail_reason=fail_reason), True
    text = str(getattr(response, "text", "") or "")
    try:
        return build_plan(text, fail_reason=fail_reason), True
    except AppError:
        # 模型产物解析失败：回到用户原文做规则降级，保住可交付的计划
        agent_trace("planner 产物解析失败，降级用户原文 L0")
        return build_plan(raw, fail_reason=fail_reason), True


def build_plan_solve_subgraph(gateway: object | None = None) -> dict:
    """构造 Plan-Solve 节点：``{'plan_solve': <node>}``。

    ``gateway`` 为可选模型网关：注入后复杂任务走一次短模型调用生成计划
    （§2.1 LLM Planner）；缺省（如旧测试夹具）保持纯规则路径。
    """

    def plan_solve_node(state: GraphState) -> dict:
        force_replan = bool(state.get("force_replan"))
        plan_data = None if force_replan else state.get("plan")
        extra = str(state.get("clarify_answer") or "").strip()
        raw = user_text_from_state(state)
        if extra:
            raw = f"{raw}\n用户补充：{extra}"
        fail_reason = str(state.get("replan_reason") or "").strip()
        used_llm = False
        if isinstance(plan_data, dict):
            try:
                plan = from_dict(PlanArtifact, dict(plan_data))
            except ValueError:
                return _failed("VALIDATION", "规划产物非法")
        else:
            try:
                plan, used_llm = _generate_plan(state, raw, fail_reason, gateway)
            except AppError as exc:
                return _failed(exc.code.value, exc.message)
        if plan.skill_id:
            # SK-4：未接入 skill 不得产出规划/确认卡，禁止 mock succeeded。
            try:
                assert_skill_enabled(plan.skill_id)
            except AppError as exc:
                return _failed(exc.code.value, exc.message)
        budget = budget_for_plan(plan)
        if used_llm:
            # 规划模型调用已消费一次：派生预算同步扣减，保持计数口径一致
            budget = Budget(max(0, budget.model_calls - 1), budget.tool_turns)
        task_state = task_state_from_plan(plan)
        payload = to_dict(plan)
        slots_dict = dict(payload.get("slots") or {})
        slots_dict["task_state"] = task_state.to_dict()
        payload["slots"] = slots_dict
        return {
            "plan": payload,
            "task_state": task_state.to_dict(),
            "budget": budget.to_dict(),
            "force_replan": False,
            "replan_reason": None,
            "pending_events": [
                make_event("thought", {"stage": "plan", "text": _plan_summary(plan)}),
                make_event("plan", payload),
            ],
        }

    return {"plan_solve": plan_solve_node}
