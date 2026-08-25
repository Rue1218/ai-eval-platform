"""reflect 节点（M4 阶段 4 / 后续架构收尾）。

确定性门禁先行（confirm 交付必须带短工具清单）→ 按需调 M6 ``review.review``
（模型辅助核对，只允许 ``pass→clarify`` 降级）。有计划的回合由本节点发出
唯一的 ``response.completed``；澄清卡 interrupt 与有界重规划仍属 P2。
"""

from __future__ import annotations

from typing import Literal

from app.harness.contracts import Observation, PlanArtifact, from_dict, make_event
from app.harness.feedback.review import review
from app.harness.memory import GraphState

ReflectVerdict = Literal["pass", "clarify", "reject"]


def _completed(finish_reason: str) -> dict:
    """整轮结束事件：有计划的路径只允许本节点发出。"""
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


def reflect_node(state: GraphState) -> dict:
    """反射门禁节点：确定性校验 + 模型辅助核对（只降级不放行）。"""
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
    # 确定性检查（不调模型）：confirm 交付缺工具 → reject
    if plan.delivery == "confirm" and not plan.tools_needed:
        verdict: ReflectVerdict = "reject"
    else:
        verdict = "pass"
    # 模型辅助核对：只允许 pass→clarify 降级（FB-3）；默认不注入模型句柄
    if verdict == "pass":
        verdict = review(plan, _latest_observation(state), model_call=None)
    events = [
        make_event("thought", {"stage": "reflect", "text": f"复核完成：{verdict}"}),
    ]
    if verdict == "reject":
        events.append(
            make_event("error", {"code": "VALIDATION", "message": "规划复核未通过"})
        )
        events.append(_completed("error"))
    else:
        events.append(_completed("stop"))
    return {"verdict": verdict, "pending_events": events}
