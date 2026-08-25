"""Plan-and-Solve 规划节点（M4 / 后续架构）。

产出完整 ``PlanArtifact`` 事件后把控制权交给 ReAct 执行短工具；
``response.completed`` 由 ``reflect`` 在整轮结束后发出。规划失败则就地
收尾，不再进入执行层。
"""

from __future__ import annotations

from app.agent.routing import user_text_from_state
from app.errors import AppError
from app.harness.contracts import PlanArtifact, from_dict, make_event, to_dict
from app.harness.memory import GraphState
from app.harness.orchestration import budget_for_plan, build_plan


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


def build_plan_solve_subgraph() -> dict:
    """构造 Plan-Solve 节点：``{'plan_solve': <node>}``。"""

    def plan_solve_node(state: GraphState) -> dict:
        force_replan = bool(state.get("force_replan"))
        plan_data = None if force_replan else state.get("plan")
        extra = str(state.get("clarify_answer") or "").strip()
        raw = user_text_from_state(state)
        if extra:
            raw = f"{raw}\n用户补充：{extra}"
        if isinstance(plan_data, dict):
            try:
                plan = from_dict(PlanArtifact, dict(plan_data))
            except ValueError:
                return _failed("VALIDATION", "规划产物非法")
        else:
            try:
                plan = build_plan(raw)
            except AppError as exc:
                return _failed(exc.code.value, exc.message)
        payload = to_dict(plan)
        return {
            "plan": payload,
            "budget": budget_for_plan(plan).to_dict(),
            "force_replan": False,
            "pending_events": [
                make_event("thought", {"stage": "plan", "text": _plan_summary(plan)}),
                make_event("plan", payload),
            ],
        }

    return {"plan_solve": plan_solve_node}
