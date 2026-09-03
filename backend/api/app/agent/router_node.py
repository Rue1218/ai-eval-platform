"""混合引擎 H1：顶层 Router 节点（四路分流骨架与审计）。

设计依据《AI测试与评估平台-混合驱动引擎架构.md》ADR-1：

- **L0 确定性特征**：纯函数 ``route_l0``，零模型调用、同输入 100% 可复现，
  产出 ``(engine, router_confidence, router_reason)`` 三元组；
- **L1 CoT 短调用**：仅当 L0 置信度低于 ``hybrid_router_confidence_threshold``
  （默认 0.7）且 ``hybrid_router_cot_enabled`` 开启时执行一次 ``router.v1``
  JSON 短调用（复用会话协议档、限制 max_tokens、计入 ``budget.model_calls``）；
  格式错误、上游异常、超时或预算耗尽**一律回落 L0**，L0 无结论回落 ``chat``；
- **执行边界**：``workflow`` 与 ``agent`` 均由图中对应子图执行；L1 不能
  越过固定流程的执行动作门禁，避免概念问答误发确认卡；
- **direct 语义**：H1 仅承认收包循环既有 ``/stop``（ws.py 拦截，不进图）；
  图内其余斜杠为防御性拒绝（零模型调用，``finish_reason="error"``）。

Router 只做分流：不创建任务、不加载工具、不执行长任务。``engine`` 由本节点
唯一写入，本轮不可变（其余节点不得覆写）。``router_reason`` 为脱敏短文本，
随 ``response.completed`` 落 ``ws_events``，是 O2 分流判错信号的唯一采集载体。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import NamedTuple

from langgraph.config import get_config

from app.agent.log import agent_trace
from app.config import settings
from app.errors import AppError
from app.harness.contracts import make_event
from app.harness.memory import GraphState, SerializableRequest, rebuild_model_config
from app.harness.memory.state import EngineKind
from app.harness.orchestration.budget import consume_model_call, from_dict

# 私有元组仅为避免在节点壳内复制技能关键词知识（ADR-9 冻结库文件，不改其内容）；
# 若未来技能目录调整，此处随 router.py 同步。
from app.harness.orchestration.router import (
    _SKILL_GROUPS,
    TOOL_INTENT_KEYWORDS,
    detect_plan_intent,
    has_quality_then_stress_intent,
    has_workflow_execution_intent,
    short_tool_names,
)
from app.harness.prompts.protocols import parse_router
from app.harness.skills import assert_skill_enabled
from app.llm import ModelRequest

# L0 置信度常量（离散特征 → 浮点；低于阈值的两个档位是 L1 的触发场景）
_CONF_DIRECT = 1.0  # 斜杠前缀，确定性
_CONF_PLAN_INTENT = 0.9  # 多槽/多技能/多短工具/确认卡（detect_plan_intent）
_CONF_WORKFLOW = 0.8  # 单技能组 + 执行动作
_CONF_TOOL_INTENT = 0.75  # 排查意图 / 单一具体短工具 / 强工具关键词
_CONF_SKILL_AMBIGUOUS = 0.6  # 命中技能词但无执行动作（低于默认阈值 0.7）
_CONF_WEAK = 0.5  # 仅弱元词「工具/命令」（低于默认阈值 0.7）
_CONF_CHAT = 0.95  # 无任何工具与技能意图

# 仅弱元词：单独出现不足以判定真实工具意图（如「你有哪些工具」）
_WEAK_INTENT_KEYWORDS: frozenset[str] = frozenset({"工具", "命令"})
_STRONG_INTENT_KEYWORDS: tuple[str, ...] = tuple(
    keyword for keyword in TOOL_INTENT_KEYWORDS if keyword not in _WEAK_INTENT_KEYWORDS
)

# 探索排查意图（S2 典型：目标导向、步数未知，需读文件/查报告交叉验证）
_DIAGNOSE_PATTERN = re.compile(r"排查|诊断|定位|分析一下|查一下原因|为什么|原因|掉了|失败|异常")

# 「rag/知识库评测」复合词折叠：通用「评测」是名词中心语，不构成第二个技能组
# （否则「跑 rag 评测」被误判为多技能 → agent，而期望是 workflow → skill-rag
# fail-closed）。仅当无其他技能组共现时折叠为单一「知识库评测」意图。
_RAG_EVAL_COMPOUND = re.compile(
    r"(?:rag|知识库)\s*(?:质量)?\s*评测|评测\s*(?:质量)?\s*(?:rag|知识库)"
)

# 用户先要求读取/分析资产再下单时，必须交由 Agent TAOR 完成只读准备；不能因
# 末尾带「先评后压」而跳过前置观察直接生成确认卡。
_WORKFLOW_PREPARATION_PATTERN = re.compile(
    r"(?:读取|读(?:取)?(?:数据集|文件)|查询|搜索|查看|分析).{0,32}(?:然后|再)",
    re.IGNORECASE,
)

# router_reason 落 ws_events，超长截断并清理控制字符（脱敏短文本）
_REASON_MAX_CHARS = 120

# L1 短调用约束：小输出、低温、关推理、短超时（决策门：复用会话协议档并限制 max_tokens）
_L1_MAX_TOKENS = 256
_L1_TEMPERATURE = 0.0
_L1_TIMEOUT_S = 15.0

# L1 CoT 系统指令：只允许输出 router.v1 JSON（ADR-1 裁决：JSON，不接受 XML 标签）
_ROUTER_L1_SYSTEM = (
    "你是评测平台对话引擎的路由器。只输出一个 JSON 对象，不要输出任何其他文字。\n"
    '格式：{"engine":"direct|chat|workflow|agent","skill_id":null或技能ID,'
    '"confidence":0到1的小数,"reason":"不超过40字的理由","slots":{},'
    '"protocol":"router","version":"router.v1"}\n'
    "engine 判据：\n"
    "- direct：斜杠命令（零模型动作）。\n"
    "- chat：概念问答、闲聊，不需要读写文件或检索。\n"
    "- workflow：要求执行基准评测、用例生成、压测等固定流程任务。\n"
    "- agent：探索排查、多步分析、需要读取文件/报告或联网检索。\n"
    "skill_id 仅在 engine=workflow 且明确对应 skill-benchmark/skill-testcase/skill-stress "
    "时给出，否则为 null。"
)

# direct 防御性拒绝文案（H1 仅承认 /stop，其余斜杠零模型收尾）
_DIRECT_REJECT_TEXT = "暂不支持该命令：当前仅支持 /stop 中止当前回合。"


class RouteDecision(NamedTuple):
    """L0 纯函数判定结果。"""

    engine: EngineKind
    confidence: float
    reason: str


def _skill_group_hits(text: str) -> tuple[str, ...]:
    """返回命中的技能组标签（复用 orchestration/router.py 的关键词组）。"""
    hits: list[str] = []
    for group in _SKILL_GROUPS:
        if any(keyword in text for keyword in group):
            hits.append(group[0])
    return tuple(hits)


def _rag_eval_single_intent(text: str) -> bool:
    """「rag/知识库评测」复合词命中且无其他技能组共现（折叠为单一意图）。"""
    if not _RAG_EVAL_COMPOUND.search(text):
        return False
    others = set(_skill_group_hits(text)) - {"评测", "知识库"}
    return not others


def route_l0(text: str) -> RouteDecision:
    """L0 确定性分流（纯函数，零模型调用，同输入 100% 可复现）。

    打分规则（优先级自上而下，全部为确定性特征）：

    | 特征                                   | engine   | confidence |
    | :------------------------------------- | :------- | :--------- |
    | 空输入                                 | chat     | 1.0        |
    | ``/`` 前缀（收包循环 /stop 之外）      | direct   | 1.0        |
    | 「rag/知识库评测」复合词（单一意图）   | workflow / chat | 0.8 / 0.6 |
    | 多技能/确认卡/≥2 短工具/技能+清单      | agent    | 0.9        |
    | 探索排查词                             | agent    | 0.75       |
    | 单技能组 + 执行动作                    | workflow | 0.8        |
    | 单一具体短工具 / 强工具关键词          | agent    | 0.75       |
    | 单技能组但无执行动作（疑似概念问答）   | chat     | 0.6        |
    | 仅弱元词（工具/命令）                  | agent    | 0.5        |
    | 无任何意图特征                         | chat     | 0.95       |

    0.6 / 0.5 两档低于默认阈值 0.7，是 L1 CoT 的触发场景；其余档位不触发。
    """
    stripped = text.strip()
    if not stripped:
        return RouteDecision("chat", _CONF_DIRECT, "空输入按对话处理")
    if stripped.startswith("/"):
        return RouteDecision("direct", _CONF_DIRECT, "斜杠命令（L0）")
    if _rag_eval_single_intent(stripped):
        # 复合词折叠：知识库评测是单一技能意图，先于多技能判定
        if has_workflow_execution_intent(stripped):
            return RouteDecision("workflow", _CONF_WORKFLOW, "命中技能组「知识库评测」且含执行动作（L0）")
        return RouteDecision("chat", _CONF_SKILL_AMBIGUOUS, "命中技能词「知识库评测」但无执行动作，疑似概念问答（L0）")
    if has_quality_then_stress_intent(stripped) and not _WORKFLOW_PREPARATION_PATTERN.search(stripped):
        # PRD：先评后压是质量任务成功后的 Worker 派生链，而不是 Agent 的多工具计划。
        return RouteDecision("workflow", _CONF_WORKFLOW, "命中质量评测后派生压测意图（L0）")
    if detect_plan_intent(stripped):
        return RouteDecision("agent", _CONF_PLAN_INTENT, "多槽/多技能/多短工具/确认卡意图（L0）")
    if _DIAGNOSE_PATTERN.search(stripped):
        return RouteDecision("agent", _CONF_TOOL_INTENT, "探索排查意图（L0）")
    groups = _skill_group_hits(stripped)
    if len(groups) == 1 and has_workflow_execution_intent(stripped):
        return RouteDecision("workflow", _CONF_WORKFLOW, f"命中技能组「{groups[0]}」且含执行动作（L0）")
    tools = short_tool_names(stripped)
    if tools:
        return RouteDecision("agent", _CONF_TOOL_INTENT, f"点名短工具：{'、'.join(tools)}（L0）")
    if any(keyword in stripped for keyword in _STRONG_INTENT_KEYWORDS):
        return RouteDecision("agent", _CONF_TOOL_INTENT, "工具意图关键词（L0）")
    if len(groups) == 1:
        return RouteDecision("chat", _CONF_SKILL_AMBIGUOUS, f"命中技能词「{groups[0]}」但无执行动作，疑似概念问答（L0）")
    if any(keyword in stripped for keyword in _WEAK_INTENT_KEYWORDS):
        return RouteDecision("agent", _CONF_WEAK, "仅弱工具线索，置信度不足（L0）")
    return RouteDecision("chat", _CONF_CHAT, "无工具与技能意图（L0）")


def _latest_user_text(serializable: SerializableRequest) -> str:
    """提取本轮最后一条用户消息文本（附件已在图外内联进 content）。"""
    for message in reversed(list(serializable.get("messages") or ())):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _sanitize_reason(reason: str) -> str:
    """清理并截断分流理由：去除控制字符与首尾空白，最长 120 字符。"""
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", str(reason)).strip()
    return cleaned[:_REASON_MAX_CHARS]


def _clamp_confidence(value: object) -> float:
    """把 L1 返回的置信度归一到 [0, 1]；非法值按 0 处理（触发保守回落）。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def router_node(state: GraphState, gateway: object) -> dict:
    """顶层 Router 节点：L0 判定 → （低置信且开启时）L1 CoT → 全量回落链。

    返回更新仅包含分流字段（engine / router_confidence / router_reason，L1
    实际发生时附带 budget）；不产出 WS 事件意图——审计随 ``response.completed``
    由各收尾节点携带。``engine`` 写入后本轮不可变。
    """
    serializable: SerializableRequest = state["request"]
    text = _latest_user_text(serializable)
    decision = route_l0(text)
    update: dict = {
        "engine": decision.engine,
        "router_confidence": decision.confidence,
        "router_reason": decision.reason,
    }
    agent_trace(
        f"router l0 engine={decision.engine} confidence={decision.confidence:.2f}"
    )
    threshold = settings.hybrid_router_confidence_threshold
    if decision.confidence >= threshold or not settings.hybrid_router_cot_enabled:
        return _finalize(update)
    update.update(_route_l1(state, serializable, text, decision, gateway))
    return _finalize(update)


def _route_l1(
    state: GraphState,
    serializable: SerializableRequest,
    text: str,
    l0: RouteDecision,
    gateway: object,
) -> dict:
    """L1 CoT 短调用；任何 AppError 一律回落 L0 结果（含降级标注前）。"""
    run_config = get_config()
    configurable = (run_config or {}).get("configurable") or {}
    api_key = str(configurable.get("credentials", {}).get("api_key") or "")
    budget_data: dict[str, int] | None = None
    try:
        budget = consume_model_call(from_dict(dict(state.get("budget") or {})))
        budget_data = budget.to_dict()
        model_config = replace(
            rebuild_model_config(serializable, api_key=api_key),
            max_tokens=_L1_MAX_TOKENS,
            temperature=_L1_TEMPERATURE,
            timeout_s=_L1_TIMEOUT_S,
            reasoning_enabled=False,
        )
        request = ModelRequest(
            config=model_config,  # type: ignore[arg-type]
            messages=({"role": "user", "content": text},),
            system=_ROUTER_L1_SYSTEM,
        )
        response = gateway.invoke(request, config=run_config)  # type: ignore[attr-defined]
        fields = parse_router(response.text)["fields"]
        engine = fields["engine"]
        confidence = _clamp_confidence(fields.get("confidence"))
        reason = _sanitize_reason(fields.get("reason"))
        # L1 只在低置信度时辅助判断，不能越过确定性的副作用门禁：普通
        # 概念问答即便模型误报 workflow，也必须保留 L0 的 chat/agent 结论。
        if engine == "workflow" and not has_workflow_execution_intent(text):
            return {
                "engine": l0.engine,
                "router_confidence": l0.confidence,
                "router_reason": f"{l0.reason}；L1 workflow 因缺少执行动作回落 L0",
                "budget": budget_data,
            }
        # direct 只承认 WS 收包循环的 /stop；L1 绝不能把普通文本升级为命令。
        if engine == "direct" and not text.strip().startswith("/"):
            return {
                "engine": l0.engine,
                "router_confidence": l0.confidence,
                "router_reason": f"{l0.reason}；L1 direct 因非斜杠输入回落 L0",
                "budget": budget_data,
            }
        skill_id = fields.get("skill_id")
        selected_skill_id: str | None = None
        if skill_id:
            skill_text = str(skill_id)
            if engine != "workflow":
                reason = f"{reason}（skill_id={skill_text} 非 Workflow 已忽略）"
            else:
                try:
                    # 仅把已注册且启用的 L1 建议写入 State；W0 将优先采用它，
                    # 避免第二段路由重新以关键词覆盖 Router 的明确选择。
                    assert_skill_enabled(skill_text)
                    selected_skill_id = skill_text
                    reason = f"{reason}（skill={skill_text}）"
                except AppError:
                    reason = f"{reason}（skill_id={skill_text} 不可用已忽略）"
        agent_trace(
            f"router l1 engine={engine} confidence={confidence:.2f} skill={skill_id or '-'}"
        )
        result = {
            "engine": engine,
            "router_confidence": confidence,
            "router_reason": f"L1 CoT：{reason}",
            "budget": budget_data,
        }
        if selected_skill_id is not None:
            result["skill_id"] = selected_skill_id
        return result
    except AppError as exc:
        # 格式错误 / 上游 5xx / 超时 / 预算耗尽：回落 L0；已消费的预算如实记账。
        agent_trace(f"router l1 fallback code={exc.code.value}")
        fallback: dict = {"router_reason": f"{l0.reason}；L1 失败回落（{exc.code.value}）"}
        if budget_data is not None:
            fallback["budget"] = budget_data
        return fallback


def _finalize(update: dict) -> dict:
    """收敛 Router 输出，保留真实引擎结论供图条件边和审计共同消费。

    H2/H3 已分别接通 Workflow DAG 与 Agent TAOR；不得再把 ``agent`` 篡改为
    “降级 chat”的审计文案，否则事件事实会与实际图路径不一致。
    """
    return update


def direct_node(state: GraphState) -> dict:
    """direct 防御节点：零模型调用收尾（H1 仅承认收包循环拦截的 /stop）。

    图内到达本节点的均为 ``/stop`` 之外的斜杠文本：产出一条防御性
    assistant_message 与 ``finish_reason="error"`` 的 completed（对齐 API.md
    V1.42 的历史 Direct 防御语义），审计字段取自 Router 写入的分流结论。
    """
    completed: dict[str, object] = {"finish_reason": "error", "role": "assistant"}
    if state.get("engine"):
        completed.update(
            engine=state.get("engine"),
            router_confidence=float(state.get("router_confidence") or 0.0),
            router_reason=str(state.get("router_reason") or ""),
        )
    return {
        "pending_events": [
            make_event(
                "assistant_message",
                {"text": _DIRECT_REJECT_TEXT, "role": "assistant", "latency_ms": 0},
            ),
            make_event("response.completed", completed),
        ],
        "response": {"text": _DIRECT_REJECT_TEXT, "usage": {}, "latency_ms": 0},
    }
