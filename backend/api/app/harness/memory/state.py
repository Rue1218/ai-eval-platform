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

# 复核结论（等价 M4 ReflectVerdict；阶段 4 reflect 节点写）
ReflectVerdict = Literal["pass", "clarify", "reject"]

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
)


class SerializableRequest(TypedDict, total=False):
    """ModelRequest 移除 should_abort 后的可序列化投影（M3 定义）。

    ``config`` 不含 api_key；``tools`` 承接 M2 ``assemble`` 产出的工具定义
    （CX-5，阶段 2 起注入）。
    """

    config: Mapping[str, object]
    messages: tuple[Mapping[str, object], ...]
    system: str | None
    tools: tuple[Mapping[str, object], ...]


def to_serializable_request(req: object) -> SerializableRequest:
    """把含回调的请求转为可序列化投影（剔除 should_abort 与 api_key）。"""
    config = getattr(req, "config")
    projected_config = {key: getattr(config, key) for key in _CONFIG_KEYS if hasattr(config, key)}
    request: SerializableRequest = {
        "config": projected_config,
        "messages": tuple(dict(message) for message in getattr(req, "messages", ())),
    }
    system = getattr(req, "system", None)
    if system:
        request["system"] = system
    tools = getattr(req, "tools", None)
    if tools:
        request["tools"] = tuple(dict(tool) for tool in tools)
    return request


def _append_events(left: list[NodeEvent] | None, right: list[NodeEvent] | None) -> list[NodeEvent]:
    """LangGraph reducer：追加新事件，不覆盖（M4-Q3 append reducer）。"""
    return list(left or []) + list(right or [])


class GraphState(TypedDict, total=False):
    """LangGraph 图状态容器；全部字段 JSON 可序列化，主体归本层。

    字段按需出现：阶段 1 使用 request/mode/pending_events/response；
    阶段 2 增加 observations/stop_flag/budget；阶段 4 增加 plan/verdict。
    """

    request: SerializableRequest  # 路由节点读文本，chat 节点重建 ModelRequest
    mode: AgentMode  # 路由节点写，条件边读
    pending_events: Annotated[list[NodeEvent], _append_events]  # 节点 append，ws.py 图外消费清空
    plan: object | None  # 阶段 4：PlanArtifact（M7 晚波）投影
    observations: list[object]  # 阶段 2：Observation（M7 早波）
    pending_tool: Mapping[str, object] | None  # 阶段 2：ToolCall 投影（react 条件边分流）
    stop_flag: bool  # 节点写，条件边读（阶段 2）
    repeat_retry: bool  # 阶段 2：OR-4 首次重复纠正后置位，react 条件边回环重试
    budget: Mapping[str, int]  # 阶段 2：Budget count-only 投影
    clarify_answer: str | None  # 阶段 3：澄清卡 interrupt() 恢复后写（M4 clarify.py）
    clarify_id: str | None  # 阶段 3：澄清唯一标识（匹配前端 clarify_reply.id）
    verdict: ReflectVerdict | None  # 阶段 4：reflect 节点写
    response: Mapping[str, object]  # ModelResponse 投影（text/usage/latency_ms）


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
        model=str(config.get("model") or ""),
        api_key=api_key,
        anthropic_version=config.get("anthropic_version"),  # type: ignore[arg-type]
        temperature=float(config.get("temperature", 0.2)),
        max_tokens=int(config.get("max_tokens", 8192)),
        timeout_s=float(config.get("timeout_s", 60.0)),
        reasoning_enabled=bool(config.get("reasoning_enabled", True)),
        reasoning_effort=config.get("reasoning_effort", "medium"),  # type: ignore[arg-type]
    )
