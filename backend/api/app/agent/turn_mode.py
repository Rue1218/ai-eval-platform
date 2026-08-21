"""最小 Agent 内核的回合路由：会话控制直达，自然语言一律走思考链循环。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .slash import SlashParse


class TurnMode(StrEnum):
    """本轮编排模式。"""

    DIRECT = "direct"
    CHAT = "chat"
    REACT_ONLY = "react_only"
    PLAN_SOLVE = "plan_solve"
    INTENT = "intent"


_DIRECT_SLASH = frozenset({"stop", "compact"})


def select_turn_mode(text: str, parsed: SlashParse) -> TurnMode:
    """入口路由：斜杠会话控制直达；自然语言不拆闲聊，思考链即规划。"""
    if parsed.is_slash:
        return TurnMode.DIRECT
    return TurnMode.REACT_ONLY


def refine_turn_mode(mode: TurnMode, *, intent: str, tools_needed: list[str], delivery: str) -> TurnMode:
    """规划完成后收束：自然语言保持同一循环，不再降级闲聊二次生成。"""
    if mode in {TurnMode.DIRECT, TurnMode.REACT_ONLY}:
        return mode
    return TurnMode.REACT_ONLY


def turn_mode_from_loop(loop: str) -> TurnMode | None:
    """历史 loop=chat 并入思考链循环，避免再走二次闲聊生成。"""
    mapping = {
        "chat": TurnMode.REACT_ONLY,
        "react": TurnMode.REACT_ONLY,
        "direct": TurnMode.DIRECT,
    }
    return mapping.get((loop or "").strip().lower())


def resolve_turn_mode(*, text: str, parsed: SlashParse, plan: Any) -> TurnMode:
    """会话控制命令直达；其余一律 ReAct，思考链即规划。"""
    if parsed.is_slash:
        return TurnMode.DIRECT
    return TurnMode.REACT_ONLY


def uses_react_llm(mode: TurnMode, *, command: str | None, slash_fill_first: bool) -> bool:
    """是否运行思考链循环（流式 reasoning → 工具或回复）。"""
    if mode == TurnMode.DIRECT:
        return False
    return command not in _DIRECT_SLASH


def allows_replan(mode: TurnMode) -> bool:
    """业务 Workflow 未注册前不允许补规划。"""
    return False


def allows_model_check(mode: TurnMode) -> bool:
    """业务 Workflow 未注册前不执行确认卡核对。"""
    return False


def emits_stage_thoughts(mode: TurnMode) -> bool:
    """规划/复核阶段卡只在 Plan-and-Solve 出现；思考链走 thought.stream=think。"""
    return mode == TurnMode.PLAN_SOLVE
