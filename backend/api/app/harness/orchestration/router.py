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

# 多技能/确认卡/显式清单：命中则走 Plan-and-Execute（P0，代码主导，不调模型）
_SKILL_GROUPS: tuple[tuple[str, ...], ...] = (
    ("评测", "benchmark"),
    ("用例", "testcase"),
    ("知识库", "rag"),
    ("压测", "stress"),
)
_CONFIRM_PHRASES: tuple[str, ...] = ("确认卡", "先评后压", "先评再压", "评完再压")
_LIST_PHRASES: tuple[str, ...] = ("任务清单", "分步", "拆成步骤", "分几步")


def detect_plan_intent(text: str) -> bool:
    """确定性多槽/多技能/确认卡意图（P0）。

    单技能闲聊（如「评测一下」）不升级为 plan_solve，避免把简单问题拆成 3–7 步。
    「测试」过宽，不单独成组，避免「测试一下搜索」误入规划。
    """
    stripped = text.strip()
    if not stripped:
        return False
    if any(phrase in stripped for phrase in _CONFIRM_PHRASES):
        return True
    groups = sum(1 for group in _SKILL_GROUPS if any(keyword in stripped for keyword in group))
    if groups >= 2:
        return True
    if groups >= 1 and any(phrase in stripped for phrase in _LIST_PHRASES):
        return True
    return False


def decide_mode(
    text: str,
    *,
    has_tool_intent: bool = False,
    has_multi_slots: bool = False,
    has_attachments: bool = False,
) -> AgentMode:
    """模式路由判定（OR-1 / P0）。

    斜杠 → direct；带附件强制 react（模型需 read）；多槽/多技能/确认卡 →
    plan_solve；工具关键词 → react；否则 chat。附件优先于规划，避免 P0
    规划节点尚未执行工具时丢掉附件读取。
    """
    if text.strip().startswith("/"):
        return "direct"
    if has_attachments:
        return "react"
    if has_multi_slots:
        return "plan_solve"
    if has_tool_intent or any(keyword in text for keyword in TOOL_INTENT_KEYWORDS):
        return "react"
    return "chat"
