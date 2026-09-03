"""基于 LangGraph 的模型调用网关。

图的职责被刻意收窄为：校验一次请求、调用统一协议适配器、输出统一响应，或
把协议适配器产生的正文/推理增量投影为 LangGraph custom stream。这里不放
Agent 循环、工具节点、确认卡、记忆和任务队列，避免模型层重新膨胀成 Harness。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator

from langgraph.config import get_config, get_stream_writer
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from ..adapters import (
    SUPPORTED_PROTOCOLS,
    AdapterResult,
    AdapterStreamEvent,
    StreamAborted,
    call_protocol,
    stream_protocol,
)
from ..errors import AppError, ErrorCode
from .contracts import (
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    NativeToolCall,
    StreamAbort,
)

logger = logging.getLogger("ai-eval.llm")

InvokeTransport = Callable[[ModelRequest], AdapterResult]
# 流式 transport：should_abort 回调经节点从 RunnableConfig 读取后传入（不入 State）
StreamTransport = Callable[
    [ModelRequest, StreamAbort | None],
    Iterator[tuple[str, str] | AdapterStreamEvent],
]


class _ModelCallState(TypedDict, total=False):
    """LangGraph 图内状态；不携带数据库会话和 Agent 运行时状态。"""

    request: ModelRequest
    response: ModelResponse


def _default_invoke_transport(request: ModelRequest) -> AdapterResult:
    """把模型层契约映射到现有三协议 HTTP 适配器。"""
    config = request.config
    return call_protocol(
        protocol=config.protocol,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        messages=[dict(message) for message in request.messages],
        system=request.system,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        anthropic_version=config.anthropic_version,
        timeout_s=config.timeout_s,
        reasoning_enabled=config.reasoning_enabled,
        reasoning_effort=config.reasoning_effort,
        tools=[dict(tool) for tool in request.tools],
        system_segments=request.system_segments,
    )


def _default_stream_transport(
    request: ModelRequest, should_abort: StreamAbort | None = None
) -> Iterator[tuple[str, str] | AdapterStreamEvent]:
    """把模型层契约映射到现有三协议 SSE 适配器。"""
    config = request.config
    yield from stream_protocol(
        protocol=config.protocol,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        messages=[dict(message) for message in request.messages],
        system=request.system,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        anthropic_version=config.anthropic_version,
        timeout_s=config.timeout_s,
        should_abort=should_abort,
        reasoning_enabled=config.reasoning_enabled,
        reasoning_effort=config.reasoning_effort,
        tools=[dict(tool) for tool in request.tools],
        system_segments=request.system_segments,
    )


class ModelGateway:
    """通过两个最小 LangGraph 图提供一次性与流式模型调用。"""

    def __init__(
        self,
        *,
        invoke_transport: InvokeTransport | None = None,
        stream_transport: StreamTransport | None = None,
    ) -> None:
        """创建网关；transport 可注入夹具，生产环境默认使用三协议适配器。"""
        self._invoke_transport = invoke_transport or _default_invoke_transport
        self._stream_transport = stream_transport or _default_stream_transport
        self._invoke_graph = self._build_invoke_graph()
        self._stream_graph = self._build_stream_graph()

    @property
    def invoke_graph(self):
        """返回已编译的一次性调用图，供 Harness 层组合而不复制节点。"""
        return self._invoke_graph

    @property
    def stream_graph(self):
        """返回已编译的流式调用图，供上层接入 SSE/WebSocket 投影。"""
        return self._stream_graph

    def invoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
        """执行一次非流式模型调用并返回统一响应。

        ``config``（RunnableConfig）可选透传：与 ``stream`` 签名一致，使上层
        Agent 图把含 ``configurable`` 的配置注入节点后再传入（O-12 迁移）。
        """
        result = self._invoke_graph.invoke({"request": request}, config=config or {})
        return self._response_from_state(result)

    async def ainvoke(self, request: ModelRequest, config: dict | None = None) -> ModelResponse:
        """异步执行一次模型调用；LangGraph 负责调度同步适配器节点。"""
        result = await self._invoke_graph.ainvoke({"request": request}, config=config or {})
        return self._response_from_state(result)

    def stream(
        self,
        request: ModelRequest,
        config: dict | None = None,
    ) -> Iterator[ModelStreamEvent]:
        """消费 LangGraph custom stream，最后发出一个 completed 事件。

        ``config``（RunnableConfig）可选透传：上层 Agent 图把含
        ``configurable.abort.should_abort`` 的配置注入到节点后，再透传给内部
        图，使取消回调在模型层生效（O-12 迁移）。
        """
        final_response: ModelResponse | None = None
        for mode, chunk in self._stream_graph.stream(
            {"request": request},
            config=config or {},
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                if chunk["kind"] == "tool_call":
                    tool_call = chunk.get("tool_call")
                    if not isinstance(tool_call, NativeToolCall):
                        raise AppError(ErrorCode.INTERNAL, "模型流式工具调用无效")
                    yield ModelStreamEvent(kind="tool_call", tool_call=tool_call)
                    continue
                yield ModelStreamEvent(kind=chunk["kind"], text=chunk["text"])
                continue
            response = self._response_from_update(chunk)
            if response is not None:
                final_response = response
        if final_response is not None:
            yield ModelStreamEvent(kind="completed", response=final_response)

    async def astream(
        self,
        request: ModelRequest,
        config: dict | None = None,
    ) -> AsyncIterator[ModelStreamEvent]:
        """异步消费 LangGraph custom stream，保持与同步 stream 相同的事件契约。"""
        final_response: ModelResponse | None = None
        async for mode, chunk in self._stream_graph.astream(
            {"request": request},
            config=config or {},
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                if chunk["kind"] == "tool_call":
                    tool_call = chunk.get("tool_call")
                    if not isinstance(tool_call, NativeToolCall):
                        raise AppError(ErrorCode.INTERNAL, "模型流式工具调用无效")
                    yield ModelStreamEvent(kind="tool_call", tool_call=tool_call)
                    continue
                yield ModelStreamEvent(kind=chunk["kind"], text=chunk["text"])
                continue
            response = self._response_from_update(chunk)
            if response is not None:
                final_response = response
        if final_response is not None:
            yield ModelStreamEvent(kind="completed", response=final_response)

    def _build_invoke_graph(self):
        """构建单节点调用图；后续 Agent/Harness 不应把节点逻辑复制出去。"""
        graph = StateGraph(_ModelCallState)
        graph.add_node("invoke_model", self._invoke_node)
        graph.add_edge(START, "invoke_model")
        graph.add_edge("invoke_model", END)
        return graph.compile()

    def _build_stream_graph(self):
        """构建通过 custom stream 投影正文与推理增量的单节点图。"""
        graph = StateGraph(_ModelCallState)
        graph.add_node("stream_model", self._stream_node)
        graph.add_edge(START, "stream_model")
        graph.add_edge("stream_model", END)
        return graph.compile()

    def _invoke_node(self, state: _ModelCallState) -> dict[str, ModelResponse]:
        """调用注入的同步 transport，并归一化意外异常。"""
        request = self._validated_request(state)
        started = time.perf_counter()
        try:
            adapter_result = self._invoke_transport(request)
        except AppError:
            raise
        except Exception as exc:
            logger.error(
                "模型调用内部异常 protocol=%s model=%s type=%s",
                request.config.protocol,
                request.config.model,
                type(exc).__name__,
            )
            raise AppError(ErrorCode.INTERNAL, "模型调用失败") from exc
        response = ModelResponse(
            text=adapter_result.text,
            usage=adapter_result.usage,
            raw=adapter_result.raw,
            latency_ms=adapter_result.latency_ms or round((time.perf_counter() - started) * 1000),
            tool_calls=tuple(
                NativeToolCall(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=dict(tool_call.arguments),
                )
                for tool_call in adapter_result.tool_calls
            ),
        )
        return {"response": response}

    def _stream_node(self, state: _ModelCallState) -> dict[str, ModelResponse]:
        """将协议适配器的增量写入 LangGraph custom stream。

        ``should_abort`` 从 ``RunnableConfig.configurable`` 读取（O-12 迁移：
        回调不入 State、不进 Checkpointer 检查点）。
        """
        request = self._validated_request(state)
        configurable = (get_config() or {}).get("configurable") or {}
        should_abort = configurable.get("abort", {}).get("should_abort")
        writer = get_stream_writer()
        content: list[str] = []
        tool_calls: list[NativeToolCall] = []
        started = time.perf_counter()
        try:
            for chunk in self._stream_transport(request, should_abort):
                if isinstance(chunk, AdapterStreamEvent):
                    if chunk.kind != "tool_call" or chunk.tool_call is None:
                        raise AppError(ErrorCode.UPSTREAM, "上游流式工具调用结构异常")
                    tool_call = NativeToolCall(
                        call_id=chunk.tool_call.call_id,
                        name=chunk.tool_call.name,
                        arguments=dict(chunk.tool_call.arguments),
                    )
                    tool_calls.append(tool_call)
                    writer({"kind": "tool_call", "tool_call": tool_call})
                    continue
                kind, delta = chunk
                if not delta:
                    continue
                # 关闭思考摘要时，即使上游仍返回 reasoning_content，也不得投影到 WS。
                if kind == "reasoning" and not request.config.reasoning_enabled:
                    continue
                if kind != "reasoning":
                    kind = "content"
                    content.append(delta)
                writer({"kind": kind, "text": delta})
        except StreamAborted:
            # 本地取消是受控流程，不应被归一成内部错误或继续向上游重试。
            raise
        except AppError:
            raise
        except Exception as exc:
            logger.error(
                "模型流式调用内部异常 protocol=%s model=%s type=%s",
                request.config.protocol,
                request.config.model,
                type(exc).__name__,
            )
            raise AppError(ErrorCode.INTERNAL, "模型流式调用失败") from exc
        return {
            "response": ModelResponse(
                text="".join(content),
                usage={},
                raw={},
                latency_ms=round((time.perf_counter() - started) * 1000),
                tool_calls=tuple(tool_calls),
            )
        }

    @staticmethod
    def _validated_request(state: _ModelCallState) -> ModelRequest:
        """校验图入口，避免把不完整配置发送到上游。"""
        request = state.get("request")
        if request is None:
            raise AppError(ErrorCode.VALIDATION, "模型调用请求不能为空")
        config = request.config
        if config.protocol not in SUPPORTED_PROTOCOLS:
            raise AppError(ErrorCode.VALIDATION, f"协议不受支持：{config.protocol}")
        if not config.base_url.strip() or not config.model.strip():
            raise AppError(ErrorCode.VALIDATION, "模型调用配置不完整")
        return request

    @staticmethod
    def _response_from_state(state: dict) -> ModelResponse:
        """从图终态提取响应，防止调用方依赖 LangGraph 内部状态结构。"""
        response = state.get("response")
        if not isinstance(response, ModelResponse):
            raise AppError(ErrorCode.INTERNAL, "模型调用未产生有效响应")
        return response

    @staticmethod
    def _response_from_update(update: dict) -> ModelResponse | None:
        """从 LangGraph updates 事件中提取节点收尾响应。"""
        for value in update.values():
            if isinstance(value, dict) and isinstance(value.get("response"), ModelResponse):
                return value["response"]
        return None
