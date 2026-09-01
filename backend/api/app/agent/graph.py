"""基于 LangGraph 的 Harness Agent 图（阶段 4：Chat + Direct + ReAct + Plan-Solve）。

图拓扑：``START → routing → (direct | chat_stream | react_agent | plan_solve)``；
ReAct 循环：``react_agent → (tools | reflect | END)``，
``tools → (tools | react_agent | reflect | END)``（队列未空继续、确认卡已齐
直达门禁、预算耗尽结束）；
Plan-Solve：``plan_solve → tools | react_agent``（失败则 END）；有 ``plan`` 的
收尾进入 ``reflect``，由 reflect 发出 ``response.completed``；工具失败阶梯：
``reflect → react_agent``（repair 首档）/ ``reflect → plan_solve``（retry 重规划）。
节点只返回纯数据（mode / pending_events / pending_tool / pending_tool_batch / response 投影），
WebSocket、数据库与平台任务队列由路由层（ws.py）负责，节点内不持有外部资源
（§2.5 事件桥接契约）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ..errors import AppError, ErrorCode
from ..harness.execution import (
    MCPClientManager,
    NativeToolExecutor,
    NativeToolResultStore,
    ToolRegistry,
    build_default_registry,
    build_tool_node,
    runtime_thread_id,
)
from ..harness.memory import GraphState, SerializableRequest
from ..llm import ModelGateway, ModelResponse
from .clarify import clarify_node
from .plan_solve import build_plan_solve_subgraph, plan_solve_route
from .react import build_react_nodes, react_route, tools_route
from .reflect import reflect_node, reflect_route
from .routing import chat_stream_node, direct_node, route, routing_node

# 条件边分流映射：复杂任务进 plan_solve，成功后再进 react / reflect
_ROUTE_TARGETS: dict[str, str] = {
    "chat": "chat_stream",
    "direct": "direct",
    "react": "react_agent",
    "plan_solve": "plan_solve",
}


class LangGraphAgent:
    """Harness Agent 图；后续 Plan-Solve 只能扩展该公开入口。"""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        registry: ToolRegistry | None = None,
        *,
        db_factory: object | None = None,
        sandbox_dir: str | None = None,
        user_id: str = "",
        checkpointer: object | None = None,
    ) -> None:
        """创建 Agent 图；网关/注册表/检查点可注入测试夹具或不同模型路由。"""
        self._gateway = gateway or ModelGateway()
        self._registry = registry or build_default_registry()
        self._db_factory = db_factory
        self._sandbox_dir = sandbox_dir
        self._user_id = user_id
        self._checkpointer = checkpointer
        # 完整原生工具结果仅在本 Agent 实例的一轮图运行中存在，禁止进入 Config/State。
        self._native_tool_results = NativeToolResultStore()
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建完整 Harness 图：路由 → Direct/Chat/ReAct/Plan-Solve。"""
        # 基础工具为原生 ToolCall 直连；只有显式 MCP 扩展才创建 Host，避免每个
        # Agent 图为 read/write/bash/web/task 额外构建 catalog/provider 路径。
        manager = (
            MCPClientManager.build_from_registry(self._registry)
            if self._registry.has_transport("mcp")
            else None
        )
        tool_node = build_tool_node(
            self._registry,
            manager=manager,
            native_executor=NativeToolExecutor(),
            db_factory=self._db_factory,
            sandbox_dir=self._sandbox_dir,
            user_id=self._user_id,
            native_tool_results=self._native_tool_results,
        )
        react_nodes = build_react_nodes(
            self._gateway,
            self._registry,
            native_tool_results=self._native_tool_results,
        )
        plan_solve_nodes = build_plan_solve_subgraph(self._gateway)
        graph = StateGraph(GraphState)
        graph.add_node("routing", routing_node)
        graph.add_node("direct", direct_node)
        graph.add_node("chat_stream", self._make_chat_node())
        graph.add_node("react_agent", react_nodes["react_agent"])
        graph.add_node("tools", tool_node)
        graph.add_node("plan_solve", plan_solve_nodes["plan_solve"])
        graph.add_node("reflect", reflect_node)
        graph.add_node("clarify", clarify_node)
        graph.add_edge(START, "routing")
        graph.add_conditional_edges("routing", route, _ROUTE_TARGETS)
        # ReAct 循环：pending_tool 存在 → tools；repeat_retry → 回环 react_agent
        # （OR-4 首次重复纠正后重试）；否则图结束
        graph.add_conditional_edges(
            "react_agent",
            react_route,
            {
                "tools": "tools",
                "end": END,
                "react_agent": "react_agent",
                "reflect": "reflect",
            },
        )
        # 原生 ToolCall 同轮可返回多个调用；ToolNode 按批次保序，默认一次一项，
        # 全部完成后才回到模型。预算耗尽必须 END，避免第 13 次模型调用撞 recursion_limit。
        graph.add_conditional_edges(
            "tools",
            tools_route,
            {
                "tools": "tools",
                "react_agent": "react_agent",
                "reflect": "reflect",
                "end": END,
            },
        )
        graph.add_edge("direct", END)
        graph.add_edge("chat_stream", END)
        graph.add_conditional_edges(
            "plan_solve",
            plan_solve_route,
            {"tools": "tools", "react_agent": "react_agent", "end": END},
        )
        graph.add_conditional_edges(
            "reflect",
            reflect_route,
            {
                "executor": "react_agent",  # 失败阶梯首档：修复观察后再给 Executor 一次
                "clarify": "clarify",
                "plan_solve": "plan_solve",
                "end": END,
            },
        )
        # 澄清恢复后强制重规划，把用户补充并入 PlanArtifact
        graph.add_edge("clarify", "plan_solve")
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
        """执行一轮非流式 Agent 调用（兼容 Plan 直接进入异步 ToolNode）。"""
        run_config, thread_id = self._prepare_run_config(config)
        try:
            # ToolNode 本身是异步节点。Plan 现可直接调 task，非流式入口也必须沿用
            # 同一张图，避免同步 invoke 在到达 tools 节点时抛出运行时错误。
            state = asyncio.run(self._graph.ainvoke({"request": request}, config=run_config))
            if state.get("mode") not in ("chat", "react", "plan_solve"):
                raise AppError(ErrorCode.VALIDATION, "Direct 路径不产生模型响应")
            return self._response_from_state(state)
        finally:
            self._native_tool_results.clear(thread_id)

    async def astream(
        self,
        request: SerializableRequest,
        config: dict | None = None,
        *,
        resume: object | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        """执行一轮流式 Agent 调用。

        产出 ``(mode, chunk)`` 二元组：
        - ``mode="custom"``：模型正文/推理增量（瞬态帧，Chat 路径）；
        - ``mode="updates"``：节点增量（含 pending_events，收包循环统一 emit），
          澄清卡中断时含 ``__interrupt__`` 键（收包循环翻译为 clarify 事件）。

        ``resume`` 非 None 时以 ``Command(resume=...)`` 恢复被澄清卡中断的图
        （thread_id 必须与中断时一致，M9 §3.5.1）。
        """
        from langgraph.types import Command

        graph_input: object
        if resume is not None:
            graph_input = Command(resume=resume)
        else:
            graph_input = {"request": request}
        run_config, thread_id = self._prepare_run_config(config)
        interrupted = False
        try:
            async for mode, chunk in self._graph.astream(
                graph_input,
                config=run_config,
                stream_mode=["custom", "updates"],
            ):
                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                    # HITL 暂停后同一 thread 还会 resume；先清掉会丢掉本轮已成功的
                    # read/write 原文，恢复后模型只能看到「结果不可用」。
                    interrupted = True
                yield mode, chunk
        finally:
            if not interrupted:
                self._native_tool_results.clear(thread_id)

    async def ahas_pending_interrupt(self, thread_id: str) -> bool:
        """判断 thread 是否仍停在待恢复的人工中断处。

        HITL 确认卡在 api 重启后从持久化事件重建注册项，恢复前必须确认
        检查点里该 thread 确实处于中断暂停（memory 引擎随进程丢失、或已被
        其他连接消费时会返回 False），避免对已完成图线程误发 resume。
        """
        config = {"configurable": {"thread_id": str(thread_id)}}
        try:
            snapshot = await self._graph.aget_state(config)
        except Exception:  # noqa: BLE001 —— 引擎不可用一律视为不可恢复（fail-closed）
            return False
        return bool(snapshot is not None and snapshot.next)

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
        # 默认 12/12 预算约 2n+1 步，再加上 routing / reflect / clarify；
        # LangGraph 默认 25 会在预算耗尽前先抛 GraphRecursionError。
        run_config.setdefault("recursion_limit", 80)
        return run_config, thread_id

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
