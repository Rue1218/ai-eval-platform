"""Harness 编排层：模式路由判定（M4 阶段 1，OR-1）。

阶段 1 仅按 ``text`` 前缀判定：斜杠 → Direct（不调模型），否则 → Chat。
阶段 2+ 扩展 hybrid 策略（规则启发式 + 轻量模型确认）与 Plan-and-Solve。
"""

from __future__ import annotations

import re
from typing import Literal

# 路由模式（写入 GraphState.mode，条件边消费）
AgentMode = Literal["chat", "direct", "react", "plan_solve"]

# 已知斜杠（Direct 节点 L0 路由匹配）
KnownSlash = Literal["/help", "/compact", "/cancel", "/stress", "/stop"]

# 工具意图启发式关键词（OR-1 规则启发式，M4-Q1 hybrid 第一阶段）。
# 覆盖读写编辑/bash/网络全组短工具：缺词会把"用 write 工具改文件"误路由到
# chat（无工具注入 → 模型只能口头声称已执行 → 幻觉）。
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
    "写入",
    "创建文件",
    "编辑",
    "修改",
    "覆盖",
    "删除",
    "工具",
    "命令",
    "运行",
    "执行",
    "fetch",
    "read",
    "write",
    "edit",
    "bash",
    "search",
    "web_search",
    "web_fetch",
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

# 短工具链也属于需要规划的复杂任务。仅命中一个工具时仍走 ReAct，避免把普通
# 读取或单条诊断命令过度升级；两个及以上不同工具才进入 Plan-and-Solve。
_SHORT_TOOL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("read", re.compile(r"读取|读文件|\bread\b", re.IGNORECASE)),
    ("write", re.compile(r"写入|创建文件|\bwrite\b", re.IGNORECASE)),
    ("edit", re.compile(r"编辑|修改文件|\bedit\b", re.IGNORECASE)),
    ("bash", re.compile(r"shell|终端命令|命令行|\bbash\b", re.IGNORECASE)),
    ("web_search", re.compile(r"网页搜索|\bweb[ _-]?search\b", re.IGNORECASE)),
    ("web_fetch", re.compile(r"网页抓取|抓取网页|\bweb[ _-]?fetch\b", re.IGNORECASE)),
)


def short_tool_names(text: str) -> tuple[str, ...]:
    """提取用户任务中点名的不同短工具，供路由与 L0 规划使用。"""
    return tuple(name for name, pattern in _SHORT_TOOL_PATTERNS if pattern.search(text))


def detect_plan_intent(text: str) -> bool:
    """确定性多槽/多技能/多短工具链/确认卡意图（P0）。

    单技能或单短工具闲聊（如「评测一下」「读取文件」）不升级为 plan_solve，
    避免把简单问题拆成 3–7 步。「测试」过宽，不单独成组，避免「测试一下搜索」
    误入规划。
    """
    stripped = text.strip()
    if not stripped:
        return False
    if any(phrase in stripped for phrase in _CONFIRM_PHRASES):
        return True
    if len(short_tool_names(stripped)) >= 2:
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
