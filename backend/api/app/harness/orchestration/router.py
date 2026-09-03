"""Harness 编排层：模式路由判定（M4 阶段 1，OR-1）+ H1 引擎分流（ADR-1）。

阶段 1 仅按 ``text`` 前缀判定：斜杠 → Direct（不调模型），否则 → Chat。
H1 起新增 ``decide_engine_l0``：四路引擎（direct/chat/workflow/agent）的
确定性 L0 分流（纯函数、可复现 100%），低置信度时才由 Router 节点触发
一次 L1 CoT 短调用（失败必回落 L0）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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

# 网页抓取动作的窄匹配：仅在用户明确要求访问/提取链接内容时进入 ReAct，
# 避免普通聊天中仅提到一个 URL 就意外触发网络工具。
_WEB_FETCH_INTENT_PATTERN = re.compile(
    r"网页抓取|抓取网页|爬取|爬虫|"
    r"(?:访问|打开|读取|解析|提取).{0,8}(?:链接|网址)|"
    r"(?:链接|网址).{0,8}(?:内容|正文|网页)",
    re.IGNORECASE,
)

# 短工具链也属于需要规划的复杂任务。仅命中一个工具时仍走 ReAct，避免把普通
# 读取或单条诊断命令过度升级；两个及以上不同工具才进入 Plan-and-Solve。
_SHORT_TOOL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("read", re.compile(r"读取|读文件|\bread\b", re.IGNORECASE)),
    ("write", re.compile(r"写入|创建文件|\bwrite\b", re.IGNORECASE)),
    ("edit", re.compile(r"编辑|修改文件|\bedit\b", re.IGNORECASE)),
    ("bash", re.compile(r"shell|终端命令|命令行|\bbash\b", re.IGNORECASE)),
    ("task", re.compile(r"拆解任务|任务计划|\btask\b", re.IGNORECASE)),
    ("web_search", re.compile(r"网页搜索|\bweb[ _-]?search\b", re.IGNORECASE)),
    ("web_fetch", re.compile(
        rf"(?:{_WEB_FETCH_INTENT_PATTERN.pattern})|\bweb[ _-]?fetch\b",
        re.IGNORECASE,
    )),
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
    plan_solve；工具关键词或点名的短工具 → react；否则 chat。附件优先于规划，避免 P0
    规划节点尚未执行工具时丢掉附件读取。
    """
    if text.strip().startswith("/"):
        return "direct"
    if has_attachments:
        return "react"
    if has_multi_slots:
        return "plan_solve"
    if (
        has_tool_intent
        or short_tool_names(text)
        or any(keyword in text for keyword in TOOL_INTENT_KEYWORDS)
    ):
        return "react"
    return "chat"


# ─── H1 引擎分流（ADR-1：L0 确定性优先，低置信度才 L1）───

# 探索类弱信号：命中走 agent；强词高置信，弱词低置信（触发 L1 CoT 校准）
_EXPLORE_STRONG_KEYWORDS: tuple[str, ...] = (
    "为什么",
    "排查",
    "诊断",
    "定位原因",
    "分析原因",
    "复盘",
    "对比一下",
    "调查",
    "解读报告",
    "查看报告",
    "查一下任务",
    "追踪",
)
_EXPLORE_WEAK_KEYWORDS: tuple[str, ...] = (
    "看看",
    "什么情况",
    "怎么回事",
    "帮我查",
    "检查一下",
)


def _skill_group_hit(text: str) -> bool:
    """是否命中任一技能组关键词（benchmark/testcase/rag/stress 强流程意图）。"""
    return any(
        any(keyword in text for keyword in group) for group in _SKILL_GROUPS
    )


def _has_explore_signal(text: str) -> str:
    """探索信号强度：返回 'strong' / 'weak' / ''（未命中）。"""
    if any(keyword in text for keyword in _EXPLORE_STRONG_KEYWORDS):
        return "strong"
    if any(keyword in text for keyword in _EXPLORE_WEAK_KEYWORDS):
        return "weak"
    return ""


# 结果/诊断修饰词：技能词命中但用户在讨论「既有任务的产出」而非发起新评测时，
# 判定为探索（agent）而非入队流程（workflow）。如「统计压测结果」「上周
# benchmark 分数掉了」——发起评测与解读结果在引擎语义上必须区分。
_RESULT_MODIFIERS: tuple[str, ...] = (
    "为什么",
    "原因",
    "排查",
    "诊断",
    "复盘",
    "统计",
    "结果",
    "报告",
    "分数",
    "解读",
    "分析一下",
)


def decide_engine_l0(text: str, *, has_attachments: bool = False) -> RouteVerdict:
    """引擎分流 L0（确定性纯函数，ADR-1；同输入必同输出，可复现 100%）。

    规则按优先级裁决（首中即返），全部不调模型：
    1. ``/`` 前缀 → ``direct``（斜杠；H1 仅收包循环的 /stop 有效，其余未恢复）；
    2. 强探索词（为什么/排查/诊断…）→ ``agent``（诊断既有产出优先于发起新流程）；
    3. 技能组命中且**无**结果/诊断修饰词 → ``workflow``（发起评测/用例/压测入队）；
    4. 技能组命中但讨论既有结果（统计压测结果/分数掉了）→ ``agent``；
    5. 弱探索词 → ``agent`` 但置信度 0.62（低于配置阈值 0.7 → 触发 L1 校准）；
    6. 附件 → ``agent``（需工具读取）；
    7. 工具意图（read/write/edit/bash/web_* 关键词）→ ``agent``；
    8. 其余 → ``chat`` 高置信。

    ``confidence`` 取值语义：≥0.95 高置信规则；0.8–0.9 一般规则；<0.7
    表示该信号弱，Router 节点据此决定是否做一次 L1 CoT（若开关开启）。
    """
    stripped = text.strip()
    if not stripped:
        return RouteVerdict(engine="chat", confidence=0.95, reason="空消息按常规问答处理")
    if stripped.startswith("/"):
        # H1 决策门：仅承认收包循环已有的 /stop；其余斜杠未恢复，回退 chat 执行
        return RouteVerdict(
            engine="direct",
            confidence=1.0,
            reason="斜杠命令意图（H1 仅 /stop 有效，其余按 chat 降级执行）",
        )
    explore_signal = _has_explore_signal(stripped)
    if explore_signal == "strong":
        return RouteVerdict(
            engine="agent",
            confidence=0.85,
            reason="强探索意图（排查/诊断/复盘），走 Agent",
        )
    skill_hit = _skill_group_hit(stripped) or detect_plan_intent(stripped)
    result_modifier = any(modifier in stripped for modifier in _RESULT_MODIFIERS)
    if skill_hit:
        if not result_modifier:
            return RouteVerdict(
                engine="workflow",
                confidence=0.9,
                reason="命中评测/用例/压测等强流程技能意图，走 Workflow",
            )
        return RouteVerdict(
            engine="agent",
            confidence=0.8,
            reason="技能命中但讨论既有产出（结果/报告/原因），走 Agent 解读",
        )
    if explore_signal == "weak":
        return RouteVerdict(
            engine="agent",
            confidence=0.62,
            reason="弱探索信号，L0 低置信度建议 L1 复核",
        )
    if has_attachments:
        return RouteVerdict(
            engine="agent",
            confidence=0.8,
            reason="携带附件需工具读取，走 Agent",
        )
    if short_tool_names(stripped) or any(
        keyword in stripped for keyword in TOOL_INTENT_KEYWORDS
    ):
        return RouteVerdict(
            engine="agent",
            confidence=0.8,
            reason="工具意图（H1 未启用工具执行，按 chat 降级执行并保留审计）",
        )
    return RouteVerdict(engine="chat", confidence=0.95, reason="常规问答，走 Chat")


@dataclass(frozen=True, slots=True)
class RouteVerdict:
    """L0/L1 分流裁决：引擎 + 置信度 + 脱敏理由（写入 RootState 审计）。"""

    engine: Literal["direct", "chat", "workflow", "agent"]
    confidence: float
    reason: str  # 平台生成中文原因；不含用户原文，可直接进审计
