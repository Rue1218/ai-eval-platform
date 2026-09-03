"""基于 LangGraph 的 Harness Agent 图（H1：可选 Router 四路分流骨架）。

图拓扑由 ``hybrid_engine_enabled`` 在进程启动时决定：

- **关闭（默认）**：``START → chat_stream → END``，与骨架化纯对话完全一致
  （回归保证：事件序列与 payload 不因本文件引入而漂移）；
- **开启（H1）**：``START → router →（条件边）→ direct | chat_stream → END``。
  ``workflow`` / ``agent`` 引擎本阶段未实现，条件边统一降级到 ``chat_stream``
  执行，降级事实经 ``router_reason`` 标注（见 router_node.py）。

节点只返回纯数据（pending_events / response 投影），WebSocket、数据库与
平台任务队列由路由层（ws.py）负责，节点内不持有外部资源（§2.5 事件桥接契约）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ..config import settings
from ..errors import AppError, ErrorCode
from ..harness.execution import runtime_thread_id
from ..harness.memory import GraphState, SerializableRequest
from ..llm import ModelGateway, ModelResponse
from .router_node import direct_node, router_node
from .routing import chat_stream_node


def _route_by_engine(state: GraphState) -> str:
    """Router 之后的顶层条件边：direct 零模型收尾，其余引擎 H1 统一降级 chat。

    防御语义：Router 未产出 ``engine``（异常路径）时回落 chat，不猜测。
    """
    engine = state.get("engine")
    if engine == "direct":
        return "direct"
    return "chat_stream"


class LangGraphAgent:
    """Harness Agent 图；对外入口与既有 ws.py 调用契约保持一致。"""

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
        """构建图：主开关关闭保持纯对话；开启接入 Router 四路分流（H1 降级）。"""
        graph = StateGraph(GraphState)
        graph.add_node("chat_stream", self._make_chat_node())
        if not settings.hybrid_engine_enabled:
            graph.add_edge(START, "chat_stream")
            graph.add_edge("chat_stream", END)
        else:
            graph.add_node("router", self._make_router_node())
            graph.add_node("direct", self._make_direct_node())
            graph.add_edge(START, "router")
            # H1：workflow / agent 未实现，与 chat 一同降级到 chat_stream 执行
            graph.add_conditional_edges(
                "router",
                _route_by_engine,
                {"direct": "direct", "chat_stream": "chat_stream"},
            )
            graph.add_edge("direct", END)
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

    def _make_router_node(self):
        """闭包绑定网关的 Router 分流节点（L0 零调用；L1 仅低置信时短调用）。"""
        gateway = self._gateway

        def node(state: GraphState) -> dict:
            return router_node(state, gateway)

        return node

    @staticmethod
    def _make_direct_node():
        """direct 防御节点（纯函数，不绑定网关：零模型调用）。"""

        def node(state: GraphState) -> dict:
            return direct_node(state)

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


def router_audit_from_update(update: dict) -> dict | None:
    """从 updates 增量中提取 Router 审计三元组（engine 已写入时）。

    供 ws.py 在取消 / 异常收尾路径携带审计（O2 信号：如 agent 分支立即
    /stop）；正常路径的审计已由收尾节点写入 completed payload，无需重复。
    """
    for value in update.values():
        if isinstance(value, dict) and value.get("engine"):
            return {
                "engine": value.get("engine"),
                "router_confidence": float(value.get("router_confidence") or 0.0),
                "router_reason": str(value.get("router_reason") or ""),
            }
    return None
