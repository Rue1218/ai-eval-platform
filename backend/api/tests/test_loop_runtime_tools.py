"""七节点图接真实 ToolScheduler、审批 broker 和临时文件工具的联调。"""

import asyncio
import json

import pytest

from app.agent.loop import build_agent
from app.agent.loop_settings import LoopSettings
from app.agent.runtime import AgentRuntime
from app.harness.execution.approval import ApprovalBroker
from app.harness.execution.scheduler import ToolScheduler
from app.harness.memory.agent_messages import derive_messages
from app.llm.loop_contracts import Done, TextDelta, ToolCallDelta, ToolCallStart
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter

pytestmark = pytest.mark.asyncio


class FileTool:
    """只读或修改测试临时文件；不引入源 builtin 工具。"""

    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    description = "测试临时文件"

    def __init__(self, name, path, *, approval=False):
        self.name, self.path = name, path
        self.metadata = {
            "dsh_access": "read" if name == "read" else "write",
            "dsh_execution_mode": "parallel" if name == "read" else "exclusive",
            "dsh_requires_approval": approval,
        }
        self.invocations = 0

    async def ainvoke(self, args):
        self.invocations += 1
        if self.name == "edit":
            self.path.write_text("after", encoding="utf-8")
            return "changed"
        return self.path.read_text(encoding="utf-8")


def calls(*names, raw="{}"):
    """为一条助手消息声明多个按模型顺序排列的调用。"""
    chunks = []
    for index, name in enumerate(names):
        chunks += [ToolCallStart(index, f"{name}-{index}", name), ToolCallDelta(index, raw)]
    return [*chunks, Done("tool_calls")]


async def test_real_scheduler_read_edit_read_full_loop(tmp_path):
    """四次模型请求真实读取、修改、复读并核对持久历史回填。"""
    path = tmp_path / "sample.txt"
    path.write_text("before", encoding="utf-8")
    tools = [FileTool("read", path), FileTool("edit", path)]
    adapter = ScriptedAdapter(calls("read"), calls("edit"), calls("read"),
                              [TextDelta("完成"), Done("stop")])
    graph = await build_agent(LoopSettings(dsh_model="test"), adapter=adapter, tools=tools)
    runtime = AgentRuntime(MemoryLog(), graph)
    await runtime.start_turn("检查并修改")
    await runtime.wait()
    assert path.read_text(encoding="utf-8") == "after"
    assert [r.messages[-1]["content"] for r in adapter.requests[1:]] == [
        "before", "changed", "after",
    ]
    assert [t.name for t in adapter.requests[0].tools] == ["read", "edit"]
    assert derive_messages(runtime.log.read())[-1]["content"] == "完成"
    assert runtime.log.read()[-1]["data"]["reason"] == "completed"
    await runtime.close()


@pytest.mark.parametrize("decision", ["allow", "deny", "always"])
async def test_real_approval_result_matches_tool_body_and_next_request(tmp_path, decision):
    """允许、拒绝及持续授权都形成一致的审批事实和 tool 回填。"""
    path = tmp_path / "sample.txt"
    path.write_text("before", encoding="utf-8")
    tool = FileTool("edit", path, approval=True)
    broker = ApprovalBroker()
    settings = LoopSettings(dsh_model="test")
    scheduler = ToolScheduler(settings, [tool], approval_broker=broker)
    adapter = ScriptedAdapter(calls("edit"), [TextDelta("结算"), Done("stop")])
    graph = await build_agent(settings, adapter=adapter, tools=[tool], scheduler=scheduler)
    runtime = AgentRuntime(MemoryLog(), graph, approval_broker=broker)

    async def approve(call):
        return decision

    runtime.set_approval_gate(approve)
    await runtime.start_turn("修改")
    await runtime.wait()
    assert tool.invocations == (0 if decision == "deny" else 1)
    assert adapter.requests[1].messages[-1]["is_error"] == (decision == "deny")
    decided = [e for e in runtime.log.read() if e["type"] == "approval/decided"]
    assert len(decided) == 1
    assert decided[0]["data"]["outcome"] == decision
    await runtime.close()
    assert broker.gate_for(runtime.session_id) is None


async def test_cancel_waiting_approval_settles_all_calls_without_starting(tmp_path):
    """审批等待中取消，不执行当前或后续工具，历史配对完整。"""
    path = tmp_path / "sample.txt"
    path.write_text("before", encoding="utf-8")
    tool = FileTool("edit", path, approval=True)
    broker = ApprovalBroker()
    settings = LoopSettings(dsh_model="test")
    scheduler = ToolScheduler(settings, [tool], approval_broker=broker)
    graph = await build_agent(settings, adapter=ScriptedAdapter(calls("edit", "edit")),
                              tools=[tool], scheduler=scheduler)
    runtime = AgentRuntime(MemoryLog(), graph, approval_broker=broker)
    entered = asyncio.Event()

    async def approve(call):
        entered.set()
        await asyncio.Event().wait()

    runtime.set_approval_gate(approve)
    await runtime.start_turn("修改")
    await asyncio.wait_for(entered.wait(), 2)
    await runtime.cancel()
    await runtime.wait()
    assert tool.invocations == 0
    results = [e["data"] for e in runtime.log.read() if e["type"] == "tool/result"]
    assert [r["status"] for r in results] == ["not_started", "not_started"]
    assert len([m for m in derive_messages(runtime.log.read()) if m["role"] == "tool"]) == 2
    assert runtime.log.read()[-1]["data"]["reason"] == "cancelled"
    await runtime.close()


async def test_invalid_json_and_unknown_tool_do_not_stop_valid_sibling(tmp_path):
    """坏参数和未知工具独立失败，后续有效调用仍执行且模型能继续。"""
    path = tmp_path / "sample.txt"
    path.write_text("valid", encoding="utf-8")
    tool = FileTool("read", path)
    chunks = [
        ToolCallStart(0, "bad", "read"), ToolCallDelta(0, '{"broken":'),
        ToolCallStart(1, "unknown", "unknown"), ToolCallDelta(1, "{}"),
        ToolCallStart(2, "good", "read"), ToolCallDelta(2, json.dumps({})), Done("tool_calls"),
    ]
    adapter = ScriptedAdapter(chunks, [TextDelta("已结算"), Done("stop")])
    graph = await build_agent(LoopSettings(dsh_model="test"), adapter=adapter, tools=[tool])
    runtime = AgentRuntime(MemoryLog(), graph)
    await runtime.start_turn("请求")
    await runtime.wait()
    results = [e["data"] for e in runtime.log.read() if e["type"] == "tool/result"]
    assert [r["status"] for r in results] == ["failed", "failed", "succeeded"]
    assert [r["call_id"] for r in results] == ["bad", "unknown", "good"]
    assert tool.invocations == 1
    assert len(adapter.requests) == 2
    assert adapter.requests[1].messages[-1]["content"] == "valid"
    await runtime.close()


async def test_cancel_dispatched_tool_drains_before_releasing_runtime():
    """已派发但无可信取消契约的工具，在清理后以 outcome_unknown 结算。"""
    entered, drained = asyncio.Event(), asyncio.Event()

    class WaitingTool:
        name = "wait"
        description = "等待外部执行"
        schema = {"type": "object", "properties": {}}
        metadata = {"dsh_access": "read", "dsh_execution_mode": "parallel"}

        async def ainvoke(self, args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                drained.set()

    graph = await build_agent(LoopSettings(dsh_model="test"),
                              adapter=ScriptedAdapter(calls("wait")), tools=[WaitingTool()])
    runtime = AgentRuntime(MemoryLog(), graph)
    await runtime.start_turn("请求")
    await asyncio.wait_for(entered.wait(), 2)
    await runtime.cancel()
    await runtime.wait()
    assert drained.is_set() and not runtime.running
    result = next(e for e in runtime.log.read() if e["type"] == "tool/result")
    assert result["data"]["status"] == "outcome_unknown"
    assert derive_messages(runtime.log.read())[-1]["is_error"]
    await runtime.close()
