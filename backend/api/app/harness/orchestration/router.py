"""Harness 编排层：模式路由判定（M4 阶段 1，OR-1）。

阶段 1 仅按 ``text`` 前缀判定：斜杠 → Direct（不调模型），否则 → Chat。
阶段 2+ 扩展 hybrid 策略（规则启发式 + 轻量模型确认）与 Plan-and-Solve。
"""

from __future__ import annotations

from typing import Literal

# 路由模式（写入 GraphState.mode，条件边消费）
AgentMode = Literal["chat", "direct", "react", "plan_solve"]

# 已知斜杠（Direct 节点 L0 路由匹配）
KnownSlash = Literal["/help", "/compact", "/cancel", "/stress", "/stop"]

# 工具意图启发式关键词（OR-1 规则启发式，M4-Q1 hybrid 第一阶段）
TOOL_INTENT_KEYWORDS: tuple[str, ...] = (
    "搜索",
    "查一下",
    "查一查",
    "查询",
    "读取",
    "读一下",
    "文件",
    "抓取",
    "网页",
    "fetch",
    "read",
    "search",
)


def decide_mode(
    text: str,
    *,
    has_tool_intent: bool = False,
    has_multi_slots: bool = False,
) -> AgentMode:
    """模式路由判定（OR-1）。

    阶段 2：hybrid 策略第一阶段——斜杠 → direct；规则启发式（关键词匹配）
    判工具意图 → react；否则 → chat。第二阶段（轻量模型确认）与
    has_multi_slots → plan_solve 留阶段 4（OR-1 演进）。
    """
    if text.strip().startswith("/"):
        return "direct"
    if has_tool_intent or any(keyword in text for keyword in TOOL_INTENT_KEYWORDS):
        return "react"
    return "chat"
