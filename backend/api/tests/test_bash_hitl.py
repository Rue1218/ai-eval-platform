"""危险 bash 的 LangGraph 人工确认中断测试。"""

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
from app.harness.execution.dispatch import bash_block_reason
from app.harness.memory import GraphState, InMemoryCheckpointer, SerializableRequest


def _request() -> SerializableRequest:
    """构造 ToolNode 最小可序列化请求。"""
    return SerializableRequest(config={"protocol": "openai_chat", "model": "test"}, messages=())


def _build_graph(executed: list[str]):
    """构造仅含 bash ToolNode 的检查点图，验证 interrupt/resume 的真实语义。"""
    registry = ToolRegistry()

    def handler(arguments: dict, _sandbox_dir: str | None = None) -> dict[str, str]:
        """测试 handler：仅在确认恢复后记录命令，不触碰真实沙箱。"""
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
    """准备一条会删除工作区文件的原生 ToolCall。"""
    return {
        "request": _request(),
        "pending_tool": {
            "name": "bash",
            "arguments": {"command": "rm -f result.md"},
            "call_id": "call-delete",
            "native": True,
        },
    }


def test_dangerous_bash_interrupts_before_handler_execution() -> None:
    """删除命令先产生确认载荷；handler 在用户确认前绝不能执行。"""
    executed: list[str] = []
    graph = _build_graph(executed)
    config = {"configurable": {"thread_id": "bash-hitl-1", "session": {"id": "s-1"}}}

    frames = asyncio.run(_collect(graph, _initial_state(), config))

    interrupts = [frame["__interrupt__"][0].value for frame in frames if "__interrupt__" in frame]
    assert len(interrupts) == 1
    assert interrupts[0]["type"] == "tool_approval"
    assert interrupts[0]["id"] == "call-delete"
    assert interrupts[0]["allowed_decisions"] == ["approve", "reject"]
    assert executed == []


def test_approved_bash_resumes_same_toolnode_and_executes() -> None:
    """确认后 Command(resume) 回到同一 ToolNode，才允许测试 handler 执行。"""
    executed: list[str] = []
    graph = _build_graph(executed)
    config = {"configurable": {"thread_id": "bash-hitl-2", "session": {"id": "s-1"}}}
    asyncio.run(_collect(graph, _initial_state(), config))

    frames = asyncio.run(
        _collect(
            graph,
            Command(resume={"id": "call-delete", "action": "approve"}),
            config,
        )
    )

    assert executed == ["rm -f result.md"]
    payloads = [
        event["payload"]
        for frame in frames
        for update in frame.values()
        if isinstance(update, dict)
        for event in update.get("pending_events", [])
        if event["kind"] == "tool_result"
    ]
    assert payloads and payloads[0]["ok"] is True


def test_rejected_bash_never_executes_and_returns_rejected_result() -> None:
    """拒绝不会执行 handler，并向模型和 ToolCard 返回可识别的 rejected 终态。"""
    executed: list[str] = []
    graph = _build_graph(executed)
    config = {"configurable": {"thread_id": "bash-hitl-3", "session": {"id": "s-1"}}}
    asyncio.run(_collect(graph, _initial_state(), config))

    frames = asyncio.run(
        _collect(
            graph,
            Command(resume={"id": "call-delete", "action": "reject"}),
            config,
        )
    )

    assert executed == []
    payloads = [
        event["payload"]
        for frame in frames
        for update in frame.values()
        if isinstance(update, dict)
        for event in update.get("pending_events", [])
        if event["kind"] == "tool_result"
    ]
    assert payloads and payloads[0]["status"] == "rejected"


def test_nested_hard_blacklist_command_cannot_downgrade_to_approval() -> None:
    """嵌套 shell 中的 sudo 仍硬拒绝，不能借确认卡绕过安全边界。"""
    assert bash_block_reason("bash -c 'sudo id'") == "bash 命令命中黑名单：sudo"


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
