"""按任务复杂度选择本轮范式（HAR-FLOW）。

ReAct 与 Plan-and-Solve 是同一根轴：一两步、下一步依赖观察 → ReAct；
多步且结构清楚 → Plan-and-Solve。Reflection 是外层，只在有可验证信号
（确认卡门禁）时启用，不是每回合必跑的第三段。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from .imagegen import looks_like_image_generation
from .plan import classify_intent_l0, is_smalltalk, looks_like_inspect_query
from .slash import SlashParse
from .voiceclone import looks_like_voiceclone


class TurnMode(str, Enum):
    """本轮编排模式。"""

    DIRECT = "direct"
    CHAT = "chat"
    REACT_ONLY = "react_only"
    PLAN_SOLVE = "plan_solve"
    INTENT = "intent"


_EVAL_INTENTS = frozenset({"benchmark", "rag", "testcase"})
_DIRECT_SLASH = frozenset({"help", "new", "status", "stop", "compact", "cancel"})
_PLAN_SOLVE_SLASH = frozenset({"benchmark", "testcase", "stress", "rerun", "rag"})
_REACT_SLASH = frozenset({"profiles", "datasets", "kb", "report"})


def select_turn_mode(text: str, parsed: SlashParse) -> TurnMode:
    """入口路由：只根据原文和斜杠，不调模型。"""
    command = parsed.command
    if parsed.is_slash:
        if command in _PLAN_SOLVE_SLASH:
            return TurnMode.PLAN_SOLVE
        if command in _REACT_SLASH:
            return TurnMode.REACT_ONLY
        return TurnMode.DIRECT

    if looks_like_image_generation(text):
        return TurnMode.REACT_ONLY
    if looks_like_voiceclone(text):
        return TurnMode.REACT_ONLY
    if is_smalltalk(text):
        return TurnMode.CHAT
    if looks_like_inspect_query(text):
        return TurnMode.REACT_ONLY

    intent, _stress = classify_intent_l0(text)
    if intent in _EVAL_INTENTS:
        return TurnMode.PLAN_SOLVE
    return TurnMode.INTENT


def refine_turn_mode(mode: TurnMode, *, intent: str, tools_needed: list[str], delivery: str) -> TurnMode:
    """规划完成后收束 INTENT：评测下单走 Plan-and-Solve，有短工具走 ReAct，否则闲聊。"""
    if mode != TurnMode.INTENT:
        return mode
    if intent in _EVAL_INTENTS and delivery in {"confirm", "clarify"}:
        return TurnMode.PLAN_SOLVE
    if tools_needed:
        return TurnMode.REACT_ONLY
    return TurnMode.CHAT


def turn_mode_from_loop(loop: str) -> TurnMode | None:
    """把模型 JSON 的 loop 收成 TurnMode。"""
    mapping = {
        "chat": TurnMode.CHAT,
        "react": TurnMode.REACT_ONLY,
        "plan_solve": TurnMode.PLAN_SOLVE,
        "direct": TurnMode.DIRECT,
    }
    return mapping.get((loop or "").strip().lower())


def resolve_turn_mode(*, text: str, parsed: SlashParse, plan: Any) -> TurnMode:
    """斜杠由产品绑定；自然语言优先用模型判定的 loop，再兜底启发式。"""
    if parsed.is_slash:
        return select_turn_mode(text, parsed)
    mode = turn_mode_from_loop(getattr(plan, "loop", "") or "")
    if mode is None:
        mode = select_turn_mode(text, parsed)
        if mode is TurnMode.INTENT:
            mode = refine_turn_mode(
                mode,
                intent=plan.intent,
                tools_needed=list(plan.tools_needed or []),
                delivery=plan.delivery,
            )
    tools = list(plan.tools_needed or [])
    if "image.generate" in tools or "audio.voiceclone" in tools:
        return TurnMode.REACT_ONLY
    return mode


def uses_react_llm(mode: TurnMode, *, command: str | None, slash_fill_first: bool) -> bool:
    """是否跑 Think-Act-Observe 决策模型。斜杠填槽只执行规划队列。"""
    if mode in {TurnMode.DIRECT, TurnMode.CHAT}:
        return False
    if mode == TurnMode.REACT_ONLY:
        return command not in _REACT_SLASH and command not in _DIRECT_SLASH
    if mode == TurnMode.PLAN_SOLVE:
        if slash_fill_first:
            return False
        return command not in _DIRECT_SLASH
    return False


def allows_replan(mode: TurnMode) -> bool:
    """仅评测下单允许 1 次补规划。"""
    return mode == TurnMode.PLAN_SOLVE


def allows_model_check(mode: TurnMode) -> bool:
    """仅 Plan-and-Solve 出确认卡前做可选核对。maybe_model_check 仍要求 delivery=confirm。"""
    return mode == TurnMode.PLAN_SOLVE


def emits_stage_thoughts(mode: TurnMode) -> bool:
    """规划/复核思考卡只在 Plan-and-Solve 出现，避免生图/闲聊套「技能 · 基准对比」。"""
    return mode == TurnMode.PLAN_SOLVE
