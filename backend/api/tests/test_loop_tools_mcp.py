"""新循环显式开启 MCP 线程 join，覆盖取消、超时、关闭及实际副作用。"""

import asyncio
import threading

import pytest

from app.harness.execution.context import ToolExecutionContext
from app.harness.execution.mcp.manager import MCPClientManager
from app.harness.execution.mcp.metrics import ToolMetrics
from app.harness.execution.registry import ToolDef, ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["task_cancel", "cancel_call", "timeout", "close"])
async def test_mcp_join_preserves_actual_result_and_metrics(tmp_path, mode):
    """到达超时/取消边界后仍等待真实线程，且不重复记调用次数。"""
    entered, release = threading.Event(), threading.Event()

    def handler(args, root):
        """阻塞后写真实临时文件，证明不能把 future.cancel 当作线程终止。"""
        entered.set()
        assert release.wait(5)
        (tmp_path / "effect.txt").write_text("persisted")
        return "written"

    registry = ToolRegistry()
    definition = ToolDef(name="controlled", description="线程测试", parameters_schema={"type": "object", "properties": {}},
                         permission="test.controlled", timeout_s=0.02 if mode == "timeout" else 2,
                         handler=handler, output_schema={}, server_id="platform.test", transport="mcp")
    registry.register(definition)
    metrics = ToolMetrics()
    manager = MCPClientManager.build_from_registry(registry, metrics=metrics, join_on_cancel=True)
    context = ToolExecutionContext(session_id="s", user_id="u", call_id="c")
    task = asyncio.create_task(manager.call_tool(definition.tool_id, {}, context))
    closing = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        if mode == "task_cancel":
            task.cancel()
        elif mode == "cancel_call":
            assert manager.cancel_call("c")
        elif mode == "close":
            closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0.05)
        assert not task.done()
        assert manager._inflight
        assert not (tmp_path / "effect.txt").exists()
        # drain 中再次取消仍不能丢失底层结果。
        if mode == "task_cancel":
            task.cancel()
    finally:
        release.set()
    result = await task
    if closing is not None:
        await closing
    assert result.ok and result.call_id == "c"
    assert (tmp_path / "effect.txt").read_text() == "persisted"
    assert not manager._inflight
    stat = metrics.snapshot()["tools"][0]
    assert stat["total"] == 1 and stat["success"] == 1
    assert stat["timeout"] == (1 if mode == "timeout" else 0)
    await manager.close()
