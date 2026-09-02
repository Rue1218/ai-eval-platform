"""基于 LangGraph 的 Harness Agent 图（骨架版：纯对话）。

图拓扑：``START → chat_stream → END``。用户消息经上下文装配（assemble）后
直接调用 ModelGateway 流式生成回复，产出 ``assistant_message`` 与
``response.completed`` 事件；不包含多范式路由（direct/chat/react/plan_solve）、
ReAct 思考链、规划与反思门禁、工具调用、确认卡与澄清卡（骨架化改造）。

节点只返回纯数据（pending_events / response 投影），WebSocket、数据库与
平台任务队列由路由层（ws.py）负责，节点内不持有外部资源（§2.5 事件桥接契约）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ..errors import AppError, ErrorCode
from ..harness.execution import runtime_thread_id
from ..harness.memory import GraphState, SerializableRequest
from ..llm import ModelGateway, ModelResponse
from .routing import chat_stream_node


class LangGraphAgent:
    """Harness Agent 图（骨架版）；对外入口与既有 ws.py 调用契约保持一致。"""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        registry: object | None = None,
        *,
        db_factory: object | None = None,
        sandbox_dir: str | None = None,
        user_id: str = "",
        checkpointer: object | None = None,
    ) -> None:
        """创建 Agent 图；网关/检查点可注入测试夹具或不同模型路由。

        骨架版不构建工具节点，``registry`` / ``db_factory`` / ``sandbox_dir``
        参数仅为兼容既有调用方保留，实际不参与图构建。
        """
        self._gateway = gateway or ModelGateway()
        self._checkpointer = checkpointer
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建骨架图：路由 → 纯对话流式节点 → 结束。"""
        graph = StateGraph(GraphState)
        graph.add_node("chat_stream", self._make_chat_node())
        graph.add_edge(START, "chat_stream")
        graph.add_edge("chat_stream", END)
        # 阶段 3：Checkpointer 按 thread_id 隔离回合（M3-D4 恢复语义）
        if self._checkpointer is not None:
            return graph.compile(checkpointer=self._checkpointer)
        return graph.compile()

    def _make_chat_node(self):
        """闭包绑定网关的 Chat 流式节点（节点签名只接收 state）。"""
        gateway = self._gateway

        def node(state: GraphState) -> dict:
            return chat_stream_node(state, gateway)

        return node

    def invoke(self, request: SerializableRequest, config: dict | None = None) -> ModelResponse:
        """执行一轮非流式 Agent 调用（纯对话路径产生模型响应）。"""
        run_config, thread_id = self._prepare_run_config(config)
        try:
            state = self._graph.invoke({"request": request}, config=run_config)
            return self._response_from_state(state)
        finally:
            self._discard_thread(thread_id)

    async def astream(
        self,
        request: SerializableRequest,
        config: dict | None = None,
        *,
        resume: object | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        """执行一轮流式 Agent 调用。

        产出 ``(mode, chunk)`` 二元组：
        - ``mode="custom"``：模型正文增量（瞬态帧）；
        - ``mode="updates"``：节点增量（含 pending_events，收包循环统一 emit）。
        """
        from langgraph.types import Command

        graph_input: object
        if resume is not None:
            graph_input = Command(resume=resume)
        else:
            graph_input = {"request": request}
        run_config, thread_id = self._prepare_run_config(config)
        try:
            async for mode, chunk in self._graph.astream(
                graph_input,
                config=run_config,
                stream_mode=["custom", "updates"],
            ):
                yield mode, chunk
        finally:
            self._discard_thread(thread_id)

    async def ahas_pending_interrupt(self, thread_id: str) -> bool:
        """判断 thread 是否仍停在待恢复的人工中断处（骨架版恒为 False）。"""
        return False

    @staticmethod
    def _prepare_run_config(config: dict | None) -> tuple[dict, str]:
        """复制运行配置并保证每一轮都有不可冲突的临时存储键。"""
        run_config = dict(config or {})
        configurable = dict(run_config.get("configurable") or {})
        thread_id = runtime_thread_id(configurable)
        if not thread_id:
            thread_id = f"agent:{uuid4().hex}"
            configurable["thread_id"] = thread_id
        run_config["configurable"] = configurable
        run_config.setdefault("recursion_limit", 32)
        return run_config, thread_id

    @staticmethod
    def _discard_thread(thread_id: str) -> None:
        """骨架版无原生工具结果存储，保留占位以对齐既有 finally 语义。"""

    @staticmethod
    def _response_from_state(state: dict) -> ModelResponse:
        """从图终态提取模型响应（state.response 为可序列化投影）。"""
        response = state.get("response")
        if not isinstance(response, dict):
            raise AppError(ErrorCode.INTERNAL, "Agent 未产生有效响应")
        return ModelResponse(
            text=str(response.get("text", "")),
            usage=response.get("usage") or {},
            latency_ms=int(response.get("latency_ms", 0)),
        )


def iter_pending_events(update: dict) -> Iterator[dict]:
    """从 LangGraph updates 增量中提取节点产出的 pending_events（图外消费）。"""
    for value in update.values():
        if isinstance(value, dict):
            events = value.get("pending_events")
            if isinstance(events, list):
                yield from events
