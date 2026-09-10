"""Harness 记忆层 GraphState 主体（M3 阶段 1）。

GraphState 是 LangGraph 图的状态容器，全部字段 JSON 可序列化（PG 检查点
兼容）；``should_abort`` 等回调不入 State，走 ``RunnableConfig.configurable``
（M4-Q2 命名空间 ``configurable["abort"]["should_abort"]``）。``api_key``
不入 ``SerializableRequest.config``——节点从 RunnableConfig 或 DB 取协议档时
即时注入 ModelGateway。

``pending_events`` 使用 append reducer 在图内累积，由 ws.py 收包循环按节点
边界消费后图外清空（M4-Q3 裁决）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Literal, TypedDict

from app.harness.contracts import NodeEvent

# 路由模式（等价 M4 AgentMode；条件边消费）
AgentMode = Literal["chat", "direct", "react", "plan_solve"]

# 混合引擎顶层分流结果（H1 RootState；与 AgentMode 正交——mode 为 Agent 子图内
# 细分且 H0–H6 不驱动任何条件边，engine 由 router 节点一次性写入、本轮不可变）
EngineKind = Literal["direct", "chat", "workflow", "agent"]

# 复核结论（等价 M4 ReflectVerdict；阶段 4 reflect 节点写；H4 五档已与
# feedback.review.Review 判决、REFLECT_SCHEMA.verdict 枚举三者对齐）
# - pass：候选答复可直接给出；
# - clarify：信息不足，收尾提问（不调用工具）；
# - reject：不可用且无法自动修复，可读原因收尾（reject 不得被判为 pass）；
# - repair：失败阶梯首档，注入 repair_hint 观察后回 Executor 再试一次；
# - retry：失败阶梯次档，回 Planner 有界重规划（replan_count 硬上限 2）。
ReflectVerdict = Literal["pass", "clarify", "reject", "retry", "repair"]

# ModelConfig 投影允许保留的键（api_key 密钥保护，不入 State）
_CONFIG_KEYS: tuple[str, ...] = (
    "protocol",
    "base_url",
    "model",
    "anthropic_version",
    "temperature",
    "max_tokens",
    "timeout_s",
    "reasoning_enabled",
    "reasoning_effort",
    "tool_call_mode",
    "full_url",  # 完整端点模式须随无密钥配置恢复。
)


class SerializableRequest(TypedDict, total=False):
    """ModelRequest 移除 should_abort 后的可序列化投影（M3 定义）。

    ``config`` 不含 api_key；``tools`` 承接 M2 ``assemble`` 产出的工具定义
    （CX-5，阶段 2 起注入）。
    """

    config: Mapping[str, object]
    messages: tuple[Mapping[str, object], ...]
    system: str | None
    # 缓存开启时的受控提示词来源投影（L1/L2/S2/L3 均为无密钥文本），供
    # chat 节点重建真实 S1→S7 分段；关闭缓存仍使用 system 单字符串兼容路径。
    system_context: Mapping[str, object]
    tools: tuple[Mapping[str, object], ...]


def to_serializable_request(
    req: object,
    *,
    system_context: Mapping[str, object] | None = None,
) -> SerializableRequest:
    """把含回调的请求转为可序列化投影（剔除 should_abort 与 api_key）。

    ``system_context`` 仅可由 WS 受控层传入，保存缓存开启时所需的静态/动态
    提示词来源；禁止在其中放入用户输入、模型凭据或任意数据库对象。
    """
    config = getattr(req, "config")
    projected_config = {key: getattr(config, key) for key in _CONFIG_KEYS if hasattr(config, key)}
    request: SerializableRequest = {
        "config": projected_config,
        "messages": tuple(dict(message) for message in getattr(req, "messages", ())),
    }
    system = getattr(req, "system", None)
    if system:
        request["system"] = system
    if system_context:
        request["system_context"] = dict(system_context)
    tools = getattr(req, "tools", None)
    if tools:
        request["tools"] = tuple(dict(tool) for tool in tools)
    return request


def _append_events(left: list[NodeEvent] | None, right: list[NodeEvent] | None) -> list[NodeEvent]:
    """LangGraph reducer：追加新事件，不覆盖（M4-Q3 append reducer）。"""
    return list(left or []) + list(right or [])


def _append_observations(left: list[object] | None, right: list[object] | None) -> list[object]:
    """LangGraph reducer：累积工具观察（OR-4 防重复需统计全部历史相同调用，
    此前仅保留最近一条导致相同 read 循环无法被守卫识别）。"""
    return list(left or []) + list(right or [])


def _append_native_messages(
    left: list[Mapping[str, object]] | None,
    right: list[Mapping[str, object]] | None,
) -> list[Mapping[str, object]]:
    """LangGraph reducer：追加原生 ToolCall 往返消息，保持调用与结果顺序。"""
    return list(left or []) + list(right or [])


class GraphState(TypedDict, total=False):
    """LangGraph 图状态容器；全部字段 JSON 可序列化，主体归本层。

    字段按需出现：阶段 1 使用 request/mode/pending_events/response；
    阶段 2 增加 observations/stop_flag/budget；阶段 4 增加 plan/verdict。
    """

    request: SerializableRequest  # 路由节点读文本，chat 节点重建 ModelRequest
    mode: AgentMode  # 路由节点写，条件边读
    pending_events: Annotated[list[NodeEvent], _append_events]  # 节点 append，ws.py 图外消费清空
    plan: object | None  # PlanArtifact 投影（H3 plan 节点写：intent/skill_id/slots/tools_needed/delivery/budget/allows_replan/notes）
    plan_step_index: int  # H3：计划步执行游标（0 基）；plan 置 0，Replan（H4）后重置，越界即 turn_failed
    observations: Annotated[list[object], _append_observations]  # 工具观察（Observation 投影）；只作模型输入
    pending_tool: Mapping[str, object] | None  # 阶段 2：当前 ToolCall 投影（react 条件边分流）
    pending_tools: list[Mapping[str, object]]  # 兼容队列：批次内尚未执行的后续项
    native_tool_round: Mapping[str, object] | None  # P2：原生 tool_use 轮缓冲
    # （assistant 段 + 该轮 tool_calls；orchestrator Act 写，tools 执行完回 orchestrator
    #  消费合成回填后置 None；仅含调用元数据与文本段，无工具正文——正文只经
    #  NativeToolResultStore，持久化契约见方案 V0.2 D3）
    pending_tool_batch: Mapping[str, object] | None  # P2：同轮 ToolBatch（batch_id/items/block_index/status）
    native_messages: Annotated[list[Mapping[str, object]], _append_native_messages]  # 原生 assistant/tool 往返消息
    stop_flag: bool  # 节点写，条件边读（阶段 2）
    repeat_retry: bool  # 阶段 2：OR-4 首次重复纠正后置位，react 条件边回环重试
    turn_failed: bool  # 有 plan 时 ReAct 硬错误：禁止再进 reflect，避免 completed(stop)
    replan_count: int  # P2：有界重规划已用次数，上限 2
    force_replan: bool  # P2：reflect 打回规划时强制重建 PlanArtifact
    step_fail_count: int  # 失败阶梯：同一步连续工具失败次数（成功即归零；用于判定「当前存在未解决失败」）
    repair_count: int  # 失败阶梯：本回合已用修复次数（**回合级**硬上限 MAX_REPAIRS=1，成功不重置）

    replan_reason: str | None  # 失败阶梯：最近一次失败原因，重规划时注入规划输入
    parse_retries: int  # 阶段 2：ReAct 协议解析失败纠正重试计数（有界，防死循环）
    budget: Mapping[str, int]  # 阶段 2：Budget count-only 投影
    clarify_answer: str | None  # 阶段 3：澄清卡 interrupt() 恢复后写（M4 clarify.py）
    clarify_id: str | None  # 阶段 3：澄清唯一标识（匹配前端 clarify_reply.id）
    verdict: ReflectVerdict | None  # 阶段 4：reflect 节点写（H4 五档判决，每次进入只出一个）
    final_text: str | None  # H4：orchestrator 收尾候选答复；由 reflect 判决后统一收尾发出
    turn_usage: dict  # F0/P1：回合累计模型 token usage（plan/orchestrator/reflect L3
    # 各次 invoke 合并，节点链式覆盖）；随 assistant_message.turn_stats 审计落库
    # （对齐 chat 路径 routing.py 的 usage 口径）。仅含计数，无正文，可入检查点。
    task_state: Mapping[str, object] | None  # 结构化任务状态机（TaskSessionState 投影）
    task_state_observation_count: int  # 已被状态机消费的 Observation 数，防 append reducer 重放旧观察
    session_tasks: list  # 会话内 TaskCreate 看板，不写 PG tasks 表
    response: Mapping[str, object]  # ModelResponse 投影（text/usage/latency_ms）
    # ── 混合引擎 RootState 扩展（H1）：engine 由 router 节点唯一写入，本轮不可变 ──
    engine: EngineKind  # 顶层分流结论（direct/chat/workflow/agent），顶层条件边读
    router_confidence: float  # L0 置信度（0–1）；低于阈值且开关开启才触发 L1 CoT
    router_reason: str  # 脱敏分流理由（含 H1 降级标注），随 response.completed 审计落库
    agent_id: str | None  # AgentRegistry.discover 选中的 Worker（H3 discover 节点写；H1 恒空）
    allowed_tools: tuple[str, ...]  # 收窄后的工具视野（H3 写；H1 恒空，且必须 ⊆ ToolRegistry）
    workflow_step: str | None  # Workflow DAG 当前节点名（H2 写；H1 恒空，仅供观测与恢复定位）
    # ── Workflow DAG（H2）：engine=workflow 时由 W0–W7 节点链写入，全部 JSON 可序列化 ──
    skill_id: str | None  # W0 select_skill：二段路由选定的技能（skill-<id>）
    skill_candidates: tuple[str, ...]  # W0：并列候选；命中多个时业务歧义 → clarify 就地收尾，禁止猜测
    slots: Mapping[str, object]  # W1 prepare_slots：抽取槽位（H2 确定性映射；LLM 抽取随 H3 工具批）
    slots_missing: tuple[str, ...]  # W1：缺失必填槽清单（确认卡兜底展示，由用户补齐）
    gate_report: Mapping[str, object]  # W3 validate_gates：门禁结果投影（passed/failed_code/message）
    task_spec: Mapping[str, object]  # W4 build_task_spec：TaskSpec（defaults.py 预填 + slots 覆盖）
    confirm_id: str | None  # W5 await_confirm：确认卡唯一标识（H2 WS 直连，图内不 interrupt）
    enqueued_task_id: str | None  # W6 enqueue：内部 MCP 长任务桥入队结果（task_id）
    workflow_failed: bool  # 失败就地收尾标记：W0/W3/W5 失败后短路后续节点并结束回合


def assert_serializable(state: GraphState) -> None:
    """断言 GraphState 全字段 json.dumps 安全（E-A1/E-A2 反射断言）。"""
    json.dumps(state)


def rebuild_model_config(
    serializable: SerializableRequest,
    *,
    api_key: str = "",
) -> object:
    """从 SerializableRequest.config 投影重建 ModelConfig（api_key 即时注入）。"""
    from app.llm import ModelConfig

    config = serializable.get("config") or {}
    return ModelConfig(
        protocol=config.get("protocol") or "openai_chat",  # type: ignore[arg-type]
        base_url=str(config.get("base_url") or ""),
        full_url=bool(config.get("full_url", False)),
        model=str(config.get("model") or ""),
        api_key=api_key,
        anthropic_version=config.get("anthropic_version"),  # type: ignore[arg-type]
        temperature=float(config.get("temperature", 0.2)),
        max_tokens=int(config.get("max_tokens", 8192)),
        timeout_s=float(config.get("timeout_s", 60.0)),
        reasoning_enabled=bool(config.get("reasoning_enabled", True)),
        reasoning_effort=config.get("reasoning_effort", "medium"),  # type: ignore[arg-type]
        tool_call_mode=config.get("tool_call_mode", "native"),  # type: ignore[arg-type]
    )
