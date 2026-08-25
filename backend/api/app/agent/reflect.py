"""reflect 节点（M4 / P2 Reflexion）。

确定性门禁先行 → 可选 M6 ``review``（只允许 ``pass→clarify`` 降级）。
有计划的成功/拒绝路径由本节点发出 ``response.completed``；``clarify`` 挂
interrupt，``retry`` 回规划（``allows_replan`` 且重规划次数 < 2）。
"""

from __future__ import annotations

from typing import Literal

from app.harness.contracts import Observation, PlanArtifact, from_dict, make_event
from app.harness.feedback.review import review
from app.harness.memory import GraphState

ReflectVerdict = Literal["pass", "clarify", "reject", "retry"]
MAX_REPLANS = 2


def _completed(finish_reason: str) -> dict:
    """整轮结束事件：成功/拒绝路径只允许本节点发出。"""
    return make_event(
        "response.completed",
        {"finish_reason": finish_reason, "role": "assistant"},
    )


def _latest_observation(state: GraphState) -> Observation:
    """取最近一条真实工具观察做 L2；无则用规划占位（确定性门禁已先行）。"""
    for raw in reversed(list(state.get("observations") or [])):
        if isinstance(raw, dict):
            tool = str(raw.get("tool") or "")
            if tool in ("", "__parse__"):
                continue
            try:
                return from_dict(Observation, dict(raw))
            except ValueError:
                continue
        tool = str(getattr(raw, "tool", "") or "")
        if tool in ("", "__parse__"):
            continue
        if isinstance(raw, Observation):
            return raw
    return Observation(tool="plan", text="规划产物", ok=True)


def reflect_route(state: GraphState) -> str:
    """复核分流：clarify → 澄清卡；retry → 重规划；否则结束。"""
    verdict = str(state.get("verdict") or "")
    if verdict == "clarify":
        return "clarify"
    if verdict == "retry":
        return "plan_solve"
    return "end"


def reflect_node(state: GraphState) -> dict:
    """反射门禁：确定性校验 + 可选重规划 / 澄清，不把 Observation 写入正文。"""
    plan_data = state.get("plan")
    if plan_data is None:
        return {
            "verdict": "pass",
            "pending_events": [_completed("stop")],
        }
    try:
        plan = (
            from_dict(PlanArtifact, dict(plan_data))
            if isinstance(plan_data, dict)
            else None
        )
    except ValueError:
        plan = None
    if plan is None:
        return {
            "verdict": "reject",
            "pending_events": [
                make_event("error", {"code": "VALIDATION", "message": "规划产物非法"}),
                _completed("error"),
            ],
        }
    observation = _latest_observation(state)
    replan_count = int(state.get("replan_count") or 0)
    if plan.delivery == "confirm" and not plan.tools_needed:
        verdict: ReflectVerdict = "reject"
    else:
        verdict = "pass"
    if verdict == "pass":
        verdict = review(plan, observation, model_call=None)
    tool_failed = (
        not observation.ok and observation.tool not in {"plan", "__parse__"}
    )
    if tool_failed and plan.allows_replan and replan_count < MAX_REPLANS:
        return {
            "verdict": "retry",
            "replan_count": replan_count + 1,
            "force_replan": True,
            "pending_events": [
                make_event(
                    "thought",
                    {
                        "stage": "reflect",
                        "text": f"复核未通过，第 {replan_count + 1} 次有界重规划",
                    },
                )
            ],
        }
    if tool_failed and replan_count >= MAX_REPLANS:
        verdict = "reject"
    events = [
        make_event("thought", {"stage": "reflect", "text": f"复核完成：{verdict}"}),
    ]
    if verdict == "clarify":
        return {"verdict": verdict, "pending_events": events}
    if verdict == "reject":
        events.append(
            make_event("error", {"code": "VALIDATION", "message": "规划复核未通过"})
        )
        events.append(_completed("error"))
        return {"verdict": verdict, "pending_events": events}
    events.append(_completed("stop"))
    return {"verdict": "pass", "pending_events": events}
