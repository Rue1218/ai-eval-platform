"""基于 LangGraph 的最小单轮 Agent 图。

Agent 图只负责把一次用户消息交给 ``ModelGateway``，并将模型层流事件向上
投影。WebSocket、数据库和平台任务队列由路由层负责，避免图节点持有外部资源。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from ..errors import AppError, ErrorCode
from ..llm import ModelGateway, ModelRequest, ModelResponse, ModelStreamEvent


class _AgentState(TypedDict, total=False):
    """单轮 Agent 图状态；不包含会话、数据库或工具执行状态。"""

    request: ModelRequest
    response: ModelResponse


class LangGraphAgent:
    """单轮模型 Agent；后续 Harness 只能组合该公开入口。"""

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        """创建 Agent 图；网关可注入测试夹具或不同模型路由。"""
        self._gateway = gateway or ModelGateway()
        self._invoke_graph = self._build_invoke_graph()
        self._stream_graph = self._build_stream_graph()

    def invoke(self, request: ModelRequest) -> ModelResponse:
        """执行一轮非流式 Agent 调用。"""
        state = self._invoke_graph.invoke({"request": request})
        return self._response_from_state(state)

    async def astream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """执行一轮流式 Agent 调用并投影模型正文/推理事件。"""
        final_response: ModelResponse | None = None
        async for mode, chunk in self._stream_graph.astream(
            {"request": request}, stream_mode=["custom", "updates"]
        ):
            if mode == "custom":
                yield ModelStreamEvent(kind=chunk["kind"], text=chunk["text"])
                continue
            response = self._response_from_update(chunk)
            if response is not None:
                final_response = response
        if final_response is None:
            raise AppError(ErrorCode.INTERNAL, "Agent 未产生有效响应")
        yield ModelStreamEvent(kind="completed", response=final_response)

    def _build_invoke_graph(self):
        """构建单轮调用图：入口 → 模型节点 → 结束。"""
        graph = StateGraph(_AgentState)
        graph.add_node("call_model", self._call_model_node)
        graph.add_edge(START, "call_model")
        graph.add_edge("call_model", END)
        return graph.compile()

    def _build_stream_graph(self):
        """构建把 ModelGateway 事件转成 Agent custom stream 的图。"""
        graph = StateGraph(_AgentState)
        graph.add_node("stream_model", self._stream_model_node)
        graph.add_edge(START, "stream_model")
        graph.add_edge("stream_model", END)
        return graph.compile()

    def _call_model_node(self, state: _AgentState) -> dict[str, ModelResponse]:
        """Agent 非流式节点；模型协议细节由 ModelGateway 隔离。"""
        request = self._request_from_state(state)
        return {"response": self._gateway.invoke(request)}

    def _stream_model_node(self, state: _AgentState) -> dict[str, ModelResponse]:
        """Agent 流式节点；只转发模型层事件，不解释模型内容。"""
        request = self._request_from_state(state)
        writer = get_stream_writer()
        final_response: ModelResponse | None = None
        for event in self._gateway.stream(request):
            if event.kind == "completed":
                final_response = event.response
                continue
            writer({"kind": event.kind, "text": event.text})
        if final_response is None:
            raise AppError(ErrorCode.INTERNAL, "模型层未产生完整响应")
        return {"response": final_response}

    @staticmethod
    def _request_from_state(state: _AgentState) -> ModelRequest:
        """校验 Agent 图入口状态。"""
        request = state.get("request")
        if request is None:
            raise AppError(ErrorCode.VALIDATION, "Agent 请求不能为空")
        return request

    @staticmethod
    def _response_from_state(state: dict) -> ModelResponse:
        """从图终态提取模型响应。"""
        response = state.get("response")
        if not isinstance(response, ModelResponse):
            raise AppError(ErrorCode.INTERNAL, "Agent 未产生有效响应")
        return response

    @staticmethod
    def _response_from_update(update: dict) -> ModelResponse | None:
        """从 LangGraph updates 事件提取 Agent 收尾响应。"""
        for value in update.values():
            if isinstance(value, dict) and isinstance(value.get("response"), ModelResponse):
                return value["response"]
        return None
