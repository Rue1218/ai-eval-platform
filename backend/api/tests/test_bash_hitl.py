"""bash 工具直通执行回归（F2/G4：静态裁决与词表删除后）。

原 HITL 语义（危险/变更命令由 ``bash_approval_reason`` 静态判定触发
``tool_approval`` 卡）自 F2/G4 起不存在——命令文本不再产生任何审批卡，
一律进入受控沙箱按档位执行（档位准入 + 拒写升档卡语义随 F5/read-only 档
接入，见《工作区与沙箱设计方案》§6.3/§6.4）。本文件回归锁定：
bash 调用（含原「危险」命令）直通执行一次、无中断、tool_result 可见；
bash 独占波次不变量保持。
"""

from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.harness.execution import (
    NativeToolResultStore,
    ToolDef,
    ToolRegistry,
    build_tool_node,
)
from app.harness.memory import GraphState, InMemoryCheckpointer, SerializableRequest


def _request() -> SerializableRequest:
    """构造 ToolNode 最小可序列化请求。"""
    return SerializableRequest(config={"protocol": "openai_chat", "model": "test"}, messages=())


def _build_graph(executed: list[str]):
    """构造仅含 bash ToolNode 的检查点图：首次执行即直通（无 interrupt）。"""
    registry = ToolRegistry()

    def handler(arguments: dict, _sandbox_dir: str | None = None) -> dict[str, str]:
        """测试 handler：记录命令，不触碰真实沙箱。"""
        executed.append(str(arguments["command"]))
        return {"summary": "命令已在测试执行器中运行"}

    registry.register(
        ToolDef(
            name="bash",
            description="测试 bash",
            parameters_schema={
                "type": "object",
                "properties": {"command": {"type": "string", "minLength": 1}},
                "required": ["command"],
                "additionalProperties": False,
            },
            permission="sandbox.bash",
            timeout_s=2.0,
            handler=handler,
            transport="native",
            risk_level="code",
            output_schema={},
        )
    )
    graph = StateGraph(GraphState)
    graph.add_node("tools", build_tool_node(registry, native_tool_results=NativeToolResultStore()))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile(checkpointer=InMemoryCheckpointer())


async def _collect(compiled, graph_input: object, config: dict) -> list[dict]:
    """收集更新帧，包含 LangGraph 的 ``__interrupt__`` 中断载荷。"""
    frames: list[dict] = []
    async for frame in compiled.astream(graph_input, config=config, stream_mode="updates"):
        frames.append(frame)
    return frames


def _initial_state() -> GraphState:
    """准备一条原「危险/变更」类命令的原生 ToolCall（词表删除前的卡触发样本）。"""
    return {
        "request": _request(),
        "pending_tool": {
            "name": "bash",
            "arguments": {"command": "rm -f result.md"},
            "call_id": "call-delete",
            "native": True,
        },
    }


def _tool_result_payloads(frames: list[dict]) -> list[dict]:
    """从更新帧提取持久 tool_result 载荷。"""
    payloads: list[dict] = []
    for frame in frames:
        for update in frame.values():
            if isinstance(update, dict):
                for event in update.get("pending_events", []):
                    if event["kind"] == "tool_result":
                        payloads.append(event["payload"])
    return payloads


def test_bash_dangerous_command_executes_directly_without_interrupt() -> None:
    """F2/G4：删除类命令首轮即执行，不再产生任何 tool_approval 中断。"""
    executed: list[str] = []
    graph = _build_graph(executed)
    config = {"configurable": {"thread_id": "bash-passthrough-1", "session": {"id": "s-1"}}}

    frames = asyncio.run(_collect(graph, _initial_state(), config))

    interrupts = [frame["__interrupt__"][0].value for frame in frames if "__interrupt__" in frame]
    assert interrupts == []
    assert executed == ["rm -f result.md"]
    payloads = _tool_result_payloads(frames)
    assert payloads and payloads[0]["ok"] is True


def test_bash_passthrough_reports_tool_result_via_updates() -> None:
    """直通执行的 bash 向模型/ToolCard 回传成功 tool_result（custom+updates 流）。"""
    executed: list[str] = []
    graph = _build_graph(executed)
    config = {"configurable": {"thread_id": "bash-passthrough-stream", "session": {"id": "s-1"}}}

    async def collect(graph_input: object) -> list[tuple[str, dict]]:
        frames: list[tuple[str, dict]] = []
        async for mode, frame in graph.astream(
            graph_input, config=config, stream_mode=["custom", "updates"]
        ):
            frames.append((mode, frame))
        return frames

    frames = asyncio.run(collect(_initial_state()))
    assert executed == ["rm -f result.md"]
    payloads = [
        event["payload"]
        for mode, frame in frames
        if mode == "updates"
        for update in frame.values()
        if isinstance(update, dict)
        for event in update.get("pending_events", [])
        if event["kind"] == "tool_result"
    ]
    assert payloads and payloads[0]["ok"] is True
    # 首轮即完成：不存在等待审批的 paused 中断路径
    assert all("__interrupt__" not in frame for _, frame in frames if isinstance(frame, dict))


def test_resume_after_passthrough_is_noop_observation() -> None:
    """直通后携带原 call_id 的 resume 属陈旧决策——无卡可批、命令不重放。"""
    executed: list[str] = []
    graph = _build_graph(executed)
    config = {"configurable": {"thread_id": "bash-passthrough-2", "session": {"id": "s-1"}}}
    asyncio.run(_collect(graph, _initial_state(), config))
    assert executed == ["rm -f result.md"]

    # 图已走完（无挂起 interrupt）→ 陈旧 resume 不重放、无新执行副作用
    frames = asyncio.run(
        _collect(
            graph,
            Command(resume={"id": "call-delete", "action": "approve"}),
            config,
        )
    )
    assert executed == ["rm -f result.md"]
    assert not any(
        event["kind"] == "tool_result"
        for frame in frames
        for update in frame.values()
        if isinstance(update, dict)
        for event in update.get("pending_events", [])
    )


def test_bash_never_shares_parallel_wave() -> None:
    """并行不变量：bash 恒独占波次。

    若 bash 与兄弟工具同波并行，TaskGroup 会把 interrupt() 包装进
    ExceptionGroup（中断语义丢失），且兄弟工具会在恢复后重复执行。
    该不变量由 PARALLEL_ELIGIBLE_NAMES 白名单 + exclusive 并发类共同保证。
    """
    from app.harness.execution.batch import is_parallel_eligible, select_execution_wave

    assert is_parallel_eligible("bash", "exclusive") is False

    class_of = {"bash": "exclusive", "read": "path_scoped"}
    # bash 打头：波次到 bash 为止，绝不带入后续工具
    wave = select_execution_wave(
        [
            {"name": "bash", "arguments": {"command": "rm x"}},
            {"name": "read", "arguments": {"path": "a.txt"}},
        ],
        class_of=class_of,
        enabled=True,
        max_parallel=3,
    )
    assert [item["name"] for item in wave] == ["bash"]
    # bash 在后：前面的可并行工具成波，bash 不加入
    wave = select_execution_wave(
        [
            {"name": "read", "arguments": {"path": "a.txt"}},
            {"name": "bash", "arguments": {"command": "rm x"}},
        ],
        class_of=class_of,
        enabled=True,
        max_parallel=3,
    )
    assert [item["name"] for item in wave] == ["read"]
