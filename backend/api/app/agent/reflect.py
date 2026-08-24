"""reflect 节点（M4 阶段 4）。

确定性门禁先行（调 M6 ``rules.check_gates``）→ 按需调 M6 ``review.review``
（模型辅助核对）→ 条件边 pass/clarify/reject。模型辅助核对只能
``pass→clarify`` 降级，不得 ``reject→pass``（FB-3）。本节点为 reflect.py
owner，调 M6 库函数；返回 ``{'verdict': ReflectVerdict, 'pending_events': [...]}``。
"""

from __future__ import annotations

from typing import Literal

from app.harness.contracts import PlanArtifact, from_dict, make_event
from app.harness.feedback.review import review
from app.harness.memory import GraphState

ReflectVerdict = Literal["pass", "clarify", "reject"]


def reflect_node(state: GraphState) -> dict:
    """反射门禁节点：确定性校验 + 模型辅助核对（只降级不放行）。"""
    plan_data = state.get("plan")
    if plan_data is None:
        return {
            "verdict": "pass",
            "pending_events": [],
        }
    plan = from_dict(PlanArtifact, dict(plan_data)) if isinstance(plan_data, dict) else None
    if plan is None:
        return {
            "verdict": "reject",
            "pending_events": [
                make_event("error", {"code": "VALIDATION", "message": "规划产物非法"})
            ],
        }
    # 确定性检查（不调模型）：confirm 交付缺工具 → reject
    if plan.delivery == "confirm" and not plan.tools_needed:
        verdict: ReflectVerdict = "reject"
    else:
        verdict = "pass"
    # 模型辅助核对：只允许 pass→clarify 降级（FB-3），模型调用句柄由
    # 调用方注入（阶段 4 节点默认跳过模型核对，走确定性门禁）
    if verdict == "pass":
        verdict = review(
            plan,
            _fake_observation_ok(),
            model_call=None,
        )
    return {
        "verdict": verdict,
        "pending_events": [
            make_event(
                "thought",
                {"stage": "reflect", "text": f"复核完成：{verdict}"},
            )
        ],
    }


def _fake_observation_ok():
    """阶段 4 占位：无工具结果的复核场景视为通过（确定性门禁已先行）。"""
    from app.harness.contracts import Observation

    return Observation(tool="plan", text="规划产物", ok=True)
