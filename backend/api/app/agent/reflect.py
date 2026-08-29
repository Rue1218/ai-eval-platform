"""reflect 节点（M4 / P2 Reflexion，§4.3 失败阶梯）。

确定性门禁先行 → 可选 M6 ``review``（只允许 ``pass→clarify`` 降级）。
工具失败按阶梯处置：首次失败注入修复观察回 Executor 再试一次（``repair``）；
再失败且 ``allows_replan`` 则有界重规划（``retry``，携带 ``replan_reason``）；
重规划满 2 次或禁止重规划时收尾。有计划的成功/拒绝路径由本节点发出
``response.completed``；``delivery=confirm`` 且复核通过时先发 ``confirm``
（TaskSpec，``kind`` 不得为 stress）。``clarify`` 挂 interrupt，``retry`` 回规划。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.harness.contracts import Observation, PlanArtifact, TaskSessionState, from_dict, make_event
from app.harness.feedback.review import review
from app.harness.memory import GraphState
from app.harness.orchestration.confirm_spec import build_confirm_payload

ReflectVerdict = Literal["pass", "clarify", "reject", "retry", "repair"]
MAX_REPLANS = 2
# 失败阶梯首档容量：同一步连续失败达到该次数前只注入修复观察回 Executor（§4.3，禁魔法数散落）
MAX_REPAIRS = 1


def _completed(finish_reason: str) -> dict:
    """整轮结束事件：成功/拒绝路径只允许本节点发出。"""
    return make_event(
        "response.completed",
        {"finish_reason": finish_reason, "role": "assistant"},
    )


def _draft_assistant_message(state: GraphState) -> dict | None:
    """读取 ReAct 暂存的最终正文，仅在 Reflect 放行后转为对外事件。"""
    draft = state.get("response")
    if not isinstance(draft, Mapping):
        return None
    text = str(draft.get("text") or "").strip()
    if not text:
        return None
    payload: dict[str, object] = {
        "text": text,
        "role": "assistant",
        "latency_ms": int(draft.get("latency_ms") or 0),
    }
    if isinstance(draft.get("turn_stats"), Mapping):
        payload["turn_stats"] = dict(draft["turn_stats"])
    return make_event("assistant_message", payload)


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
    """复核分流：repair 回 Executor；clarify → 澄清卡；retry → 重规划；否则结束。"""
    verdict = str(state.get("verdict") or "")
    if verdict == "repair":
        return "executor"
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
    fail_count = int(state.get("step_fail_count") or 0)
    if plan.delivery == "confirm" and not plan.tools_needed:
        verdict: ReflectVerdict = "reject"
    else:
        verdict = "pass"
    if verdict == "pass":
        verdict = review(plan, observation, model_call=None)

    task_state_data = state.get("task_state")
    if verdict == "pass" and isinstance(task_state_data, dict):
        task_state = TaskSessionState.from_dict(task_state_data)
        has_tool_obs = any(
            str(getattr(obs, "tool", "") or "") not in ("", "__parse__", "__reflect__", "plan")
            for obs in (state.get("observations") or [])
        )
        if plan.delivery == "chat" and has_tool_obs and not task_state.can_deliver and task_state.missing_info:
            missing_preview = "、".join(task_state.missing_info[:3])
            if fail_count < MAX_REPAIRS:
                repair_text = (
                    f"【任务状态门禁拦截】：任务关键信息尚未闭环（尚缺：{missing_preview}），"
                    "当前禁止提前交付最终结论！请继续调用工具探查以补齐信息缺口。"
                )
                return {
                    "verdict": "repair",
                    "step_fail_count": fail_count + 1,
                    "observations": [
                        Observation(
                            tool="__reflect__",
                            text=repair_text,
                            ok=False,
                            redacted=True,
                        )
                    ],
                    "pending_events": [
                        make_event(
                            "thought",
                            {"stage": "reflect", "text": "任务信息缺口未闭环，驳回提前收尾"},
                        )
                    ],
                }
            return {
                "verdict": "reject",
                "step_fail_count": fail_count,
                "pending_events": [
                    make_event("thought", {"stage": "reflect", "text": "任务信息缺口未闭环，终止提前交付"}),
                    make_event("error", {"code": "VALIDATION", "message": "任务关键信息未闭环，无法交付最终结论"}),
                    _completed("error"),
                ],
            }
    tool_failed = (
        not observation.ok and observation.tool not in {"plan", "__parse__"}
    )
    hint = str(getattr(observation, "repair_hint", "") or "").strip()
    if tool_failed and fail_count < MAX_REPAIRS:
        # 阶梯首档：不直接重规划，先注入修复观察给 Executor 一次换参/换路机会（§4.3）
        text = (
            f"系统提示：工具 {observation.tool} 执行失败：{observation.text[:200]}。"
            "请根据失败原因调整参数或换用其他方式继续；若已有信息足够，请直接收尾。"
        )
        if hint:
            text += f"修复建议：{hint}"
        return {
            "verdict": "repair",
            "step_fail_count": fail_count + 1,
            "observations": [
                Observation(
                    tool=observation.tool,
                    text=text,
                    ok=False,
                    redacted=True,
                    arguments=observation.arguments,
                    repair_hint=hint,
                )
            ],
            "pending_events": [
                make_event(
                    "thought",
                    {"stage": "reflect", "text": "复核未通过，注入修复建议后再试一次"},
                )
            ],
        }
    if tool_failed and plan.allows_replan and replan_count < MAX_REPLANS:
        reason = f"工具 {observation.tool} 执行失败：{observation.text[:200]}"
        if hint:
            reason += f"；修复建议：{hint}"
        return {
            "verdict": "retry",
            "replan_count": replan_count + 1,
            "force_replan": True,
            "step_fail_count": 0,
            "replan_reason": reason,
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
        return {"verdict": verdict, "step_fail_count": 0, "pending_events": events}
    if verdict == "reject":
        events.append(
            make_event("error", {"code": "VALIDATION", "message": "规划复核未通过"})
        )
        events.append(_completed("error"))
        return {"verdict": verdict, "step_fail_count": 0, "pending_events": events}
    if plan.delivery == "confirm":
        payload = build_confirm_payload(plan, state.get("observations"))
        if payload is None:
            # 规划要确认卡但拼不出质量任务 kind：收窄为澄清，避免发一张必失败的卡。
            return {
                "verdict": "clarify",
                "step_fail_count": 0,
                "pending_events": events,
            }
        events.append(make_event("confirm", payload))
    if plan.delivery == "chat":
        draft_message = _draft_assistant_message(state)
        if draft_message is not None:
            events.append(draft_message)
    events.append(_completed("stop"))
    return {"verdict": "pass", "step_fail_count": 0, "pending_events": events}
