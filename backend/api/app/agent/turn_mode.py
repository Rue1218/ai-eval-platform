"""最小 Agent 内核的回合路由：仅 chat、ReAct 与会话控制。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from .imagegen import looks_like_image_generation
from .plan import is_smalltalk
from .slash import SlashParse
from .voiceclone import looks_like_voiceclone


class TurnMode(str, Enum):
    """本轮编排模式。"""

    DIRECT = "direct"
    CHAT = "chat"
    REACT_ONLY = "react_only"
    PLAN_SOLVE = "plan_solve"
    INTENT = "intent"


_DIRECT_SLASH = frozenset({"stop", "compact"})


def select_turn_mode(text: str, parsed: SlashParse) -> TurnMode:
    """入口路由：只根据原文和斜杠，不调模型。"""
    if parsed.is_slash:
        return TurnMode.DIRECT

    if looks_like_image_generation(text):
        return TurnMode.REACT_ONLY
    if looks_like_voiceclone(text):
        return TurnMode.REACT_ONLY
    if is_smalltalk(text):
        return TurnMode.CHAT
    return TurnMode.INTENT


def refine_turn_mode(mode: TurnMode, *, intent: str, tools_needed: list[str], delivery: str) -> TurnMode:
    """规划完成后收束：有已注册短工具走 ReAct，否则走闲聊。"""
    if mode != TurnMode.INTENT:
        return mode
    if tools_needed:
        return TurnMode.REACT_ONLY
    return TurnMode.CHAT


def turn_mode_from_loop(loop: str) -> TurnMode | None:
    """把模型 JSON 的 loop 收成 TurnMode。"""
    mapping = {
        "chat": TurnMode.CHAT,
        "react": TurnMode.REACT_ONLY,
        "direct": TurnMode.DIRECT,
    }
    return mapping.get((loop or "").strip().lower())


def resolve_turn_mode(*, text: str, parsed: SlashParse, plan: Any) -> TurnMode:
    """会话控制命令直达；自然语言优先使用模型判定的 chat/react 循环。"""
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
    """是否运行 Think-Act-Observe 决策模型。"""
    if mode in {TurnMode.DIRECT, TurnMode.CHAT}:
        return False
    if mode == TurnMode.REACT_ONLY:
        return command not in _DIRECT_SLASH
    return False


def allows_replan(mode: TurnMode) -> bool:
    """业务 Workflow 未注册前不允许补规划。"""
    return False


def allows_model_check(mode: TurnMode) -> bool:
    """业务 Workflow 未注册前不执行确认卡核对。"""
    return False


def emits_stage_thoughts(mode: TurnMode) -> bool:
    """规划/复核思考卡只在 Plan-and-Solve 出现，避免生图/闲聊套「技能 · 基准对比」。"""
    return mode == TurnMode.PLAN_SOLVE
