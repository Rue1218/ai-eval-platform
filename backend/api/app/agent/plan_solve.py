"""Plan-and-Solve 执行子图（M4 阶段 4，OR-2/OR-3）。

图内复用节点（无独立 LLM 循环、不编排 LLM 子代理）：按 PlanArtifact 顺序
复用 chat/react 节点执行。阶段 4 最小实现：``plan_solve_node`` 只产出
事件意图（plan/thought/tool_call），工具真正执行与 reflect 复核由后续
阶段接线；长工具经 ``worker_bridge`` 入队（不阻塞回合）。
"""

from __future__ import annotations

from app.harness.contracts import PlanArtifact, from_dict, make_event
from app.harness.memory import GraphState


def build_plan_solve_subgraph() -> dict:
    """构造 Plan-Solve 节点：``{'plan_solve': <node>}``（图内复用节点）。"""

    def plan_solve_node(state: GraphState) -> dict:
        plan_data = state.get("plan")
        if not isinstance(plan_data, dict):
            return {
                "pending_events": [
                    make_event("error", {"code": "VALIDATION", "message": "缺少规划产物"})
                ]
            }
        plan = from_dict(PlanArtifact, plan_data)
        events = [
            make_event("plan", {"intent": plan.intent, "delivery": plan.delivery}),
            make_event(
                "thought",
                {"stage": "plan_solve", "text": f"开始执行规划：{plan.intent}"},
            ),
        ]
        # 按 plan.tools_needed 依次产工具调用事件意图（执行由后续阶段接线）
        for tool_name in plan.tools_needed:
            events.append(
                make_event(
                    "tool_call",
                    {"name": tool_name, "arguments": {"via": "plan_solve"}},
                )
            )
        return {"pending_events": events}

    return {"plan_solve": plan_solve_node}
