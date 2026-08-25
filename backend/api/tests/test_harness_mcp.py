"""内部 MCP Host（阶段 D，P3）测试。

覆盖：catalog（tools/list / refresh / 名称冲突）、manager（tools/call 成功/
失败/未知/超时/取消/close）、/api/mcp/tools 只读目录、ToolNode 经 manager
执行的事件 payload 与显式/自建 manager 等价。不依赖数据库连接。
"""

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Mapping

import pytest

import app.harness.execution.toolnode as toolnode_mod
from app.errors import AppError, ErrorCode
from app.harness.execution import (
    MCPClientManager,
    ToolCatalog,
    ToolDef,
    ToolRegistry,
    build_default_registry,
    build_tool_node,
)
from app.harness.execution.mcp import ToolExecutionContext
from app.harness.memory import GraphState


def _def(
    name: str,
    *,
    server_id: str = "platform.files",
    handler=None,
    timeout_s: float = 5.0,
    risk_level: str = "read",
) -> ToolDef:
    return ToolDef(
        name=name,
        description=f"{name} 描述",
        parameters_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "additionalProperties": False,
        },
        permission="test.read",
        timeout_s=timeout_s,
        handler=handler or (lambda args, sandbox_dir=None: f"ok:{name}"),
        server_id=server_id,
        display_name=name,
        risk_level=risk_level,  # type: ignore[arg-type]
    )


def _run_toolnode(node, state: GraphState, configurable: Mapping[str, object]) -> dict:
    """在受控 configurable 下运行 ToolNode 节点（不依赖真实 LangGraph 上下文）。"""

    class _FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            return {"configurable": configurable}.get(key, default)

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: _FakeConfig()
    try:
        return asyncio.run(node(state))
    finally:
        toolnode_mod.get_config = original


def _tool_result_event(out: dict) -> dict:
    return next(event for event in out["pending_events"] if event["kind"] == "tool_result")


# —— catalog ——


def test_catalog_builds_default_6_tools_3_servers() -> None:
    catalog = ToolCatalog.build(build_default_registry())
    descriptors = catalog.all_descriptors()
    assert len(descriptors) == 6
    assert set(catalog.servers()) == {"platform.files", "platform.web", "platform.sandbox"}
    assert catalog.get("platform.files.read") is not None
    assert catalog.get("platform.files.read").name == "read"
    assert catalog.resolve_name("read") == "platform.files.read"
    assert catalog.resolve_name("bash") == "platform.sandbox.bash"
    assert catalog.get("nope") is None


def test_catalog_refresh_reflects_newly_registered_tool() -> None:
    registry = ToolRegistry()
    registry.register(_def("a"))
    catalog = ToolCatalog.build(registry)
    assert catalog.get("platform.files.a") is not None
    assert catalog.get("platform.files.b") is None
    registry.register(_def("b"))
    catalog.refresh(registry)
    assert catalog.get("platform.files.b") is not None
    assert len(catalog.all_descriptors()) == 2


def test_catalog_rejects_duplicate_tool_id() -> None:
    catalog = ToolCatalog()
    descriptor = _def("a").to_descriptor()
    catalog.add(descriptor)
    with pytest.raises(AppError) as error:
        catalog.add(descriptor)
    assert error.value.code == ErrorCode.VALIDATION
    assert "重复" in error.value.message


def test_catalog_rejects_short_name_conflict_across_servers() -> None:
    catalog = ToolCatalog()
    catalog.add(_def("dup", server_id="platform.files").to_descriptor())
    with pytest.raises(AppError) as error:
        catalog.add(_def("dup", server_id="platform.web").to_descriptor())
    assert error.value.code == ErrorCode.VALIDATION
    assert "冲突" in error.value.message


def test_catalog_infers_server_for_unscoped_tool() -> None:
    catalog = ToolCatalog()
    catalog.add(_def("read").to_descriptor())  # server_id 缺省时按名称推断
    descriptor = catalog.get("platform.files.read")
    assert descriptor is not None
    assert descriptor.server_id == "platform.files"


# —— manager ——


def test_manager_call_success_returns_tool_result() -> None:
    async def run() -> None:
        manager = MCPClientManager.build_from_registry(build_default_registry())
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8") as handle:
                handle.write("hello world")
            result = await manager.call_tool(
                "platform.files.read",
                {"path": "a.txt"},
                ToolExecutionContext(sandbox_dir=tmp, call_id="c1"),
            )
            assert result.ok is True
            assert result.call_id == "c1"
            assert "hello world" in result.data["model_text"]
        await manager.close()

    asyncio.run(run())


def test_manager_call_app_error_normalized_not_found() -> None:
    async def run() -> None:
        manager = MCPClientManager.build_from_registry(build_default_registry())
        with tempfile.TemporaryDirectory() as tmp:
            result = await manager.call_tool(
                "platform.files.read",
                {"path": "missing.txt"},
                ToolExecutionContext(sandbox_dir=tmp, call_id="c2"),
            )
            assert result.ok is False
            assert result.error["code"] == "NOT_FOUND"
            assert result.call_id == "c2"
        await manager.close()

    asyncio.run(run())


def test_manager_unknown_tool_returns_validation_without_raise() -> None:
    async def run() -> None:
        manager = MCPClientManager.build_from_registry(build_default_registry())
        result = await manager.call_tool(
            "platform.nope.x",
            {},
            ToolExecutionContext(call_id="c3"),
        )
        assert result.ok is False
        assert result.error["code"] == "VALIDATION"
        assert "未注册" in result.error["message"]
        await manager.close()

    asyncio.run(run())


def test_manager_runtime_error_normalized_internal() -> None:
    def boom(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        raise RuntimeError("secret detail")

    registry = ToolRegistry()
    registry.register(_def("boom", server_id="platform.custom", handler=boom))

    async def run() -> None:
        manager = MCPClientManager.build_from_registry(registry)
        result = await manager.call_tool(
            "platform.custom.boom",
            {},
            ToolExecutionContext(call_id="c4"),
        )
        assert result.ok is False
        assert result.error["code"] == "INTERNAL"
        assert "secret" not in result.error["message"]
        await manager.close()

    asyncio.run(run())


def test_manager_timeout_returns_timeout_result() -> None:
    def slow(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        time.sleep(0.05)
        return "late"

    registry = ToolRegistry()
    registry.register(_def("slow", server_id="platform.custom", handler=slow, timeout_s=0.01))

    async def run() -> None:
        manager = MCPClientManager.build_from_registry(registry)
        result = await manager.call_tool(
            "platform.custom.slow",
            {},
            ToolExecutionContext(call_id="c5"),
        )
        assert result.ok is False
        assert result.error["code"] == "TIMEOUT"
        await manager.close()

    asyncio.run(run())


def test_manager_cancel_call_propagates_cancelled_error() -> None:
    def slow(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        time.sleep(1.0)
        return "never returned"

    registry = ToolRegistry()
    registry.register(_def("slow", server_id="platform.custom", handler=slow, timeout_s=10.0))

    async def run() -> None:
        manager = MCPClientManager.build_from_registry(registry)
        task = asyncio.create_task(
            manager.call_tool(
                "platform.custom.slow",
                {},
                ToolExecutionContext(call_id="cancel-me"),
            )
        )
        await asyncio.sleep(0.02)
        assert manager.cancel_call("cancel-me") is True
        assert manager.cancel_call("cancel-me") is False  # 已弹出
        with pytest.raises(asyncio.CancelledError):
            await task
        await manager.close()

    asyncio.run(run())


def test_manager_close_is_idempotent_and_rejects_new_calls() -> None:
    async def run() -> None:
        manager = MCPClientManager.build_from_registry(build_default_registry())
        await manager.close()
        await manager.close()  # 幂等
        result = await manager.call_tool(
            "platform.files.read",
            {"path": "a.txt"},
            ToolExecutionContext(call_id="c6"),
        )
        assert result.ok is False
        assert result.error["code"] == "INTERNAL"

    asyncio.run(run())


# —— /api/mcp/tools 只读目录 ——


def test_mcp_tools_router_lists_internal_catalog() -> None:
    from app.routers.mcp import list_tools

    payload = list_tools(user=None)
    assert payload["total"] == 6
    items = payload["items"]
    names = {item["name"] for item in items}
    assert names == {
        "platform.files.read",
        "platform.files.write",
        "platform.files.edit",
        "platform.web.web_search",
        "platform.web.web_fetch",
        "platform.sandbox.bash",
    }
    read_item = next(item for item in items if item["name"] == "platform.files.read")
    assert read_item["permission"] == "read"
    assert read_item["source"] == "builtin"
    assert read_item["enabled"] is True
    assert read_item["risk_level"] == "read"
    assert read_item["execution_mode"] == "short"
    bash_item = next(item for item in items if item["name"] == "platform.sandbox.bash")
    assert bash_item["permission"] == "write"
    # 只读目录：不含连接命令/凭据/内部 handler 细节
    serialized = json.dumps(items)
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert "command" not in serialized
    assert "handler" not in serialized
    for item in items:
        assert set(item) == {
            "name",
            "desc",
            "permission",
            "enabled",
            "source",
            "tool_id",
            "server_id",
            "short_name",
            "display_name",
            "risk_level",
            "execution_mode",
            "timeout_s",
            "requires_confirmation",
            "supports_streaming",
        }


# —— ToolNode 经 manager 执行 ——


def test_toolnode_explicit_manager_equals_self_built() -> None:
    """显式传入 manager 与自建 manager 的成功路径事件 payload 一致。"""
    registry = build_default_registry()
    explicit = build_tool_node(registry, manager=MCPClientManager.build_from_registry(registry))
    builtin = build_tool_node(registry)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8") as handle:
            handle.write("data1")
        state: GraphState = {
            "request": {"config": {}, "messages": ()},
            "pending_tool": {"name": "read", "arguments": {"path": "a.txt"}},
        }
        configurable = {"sandbox": {"dir": tmp}, "session": {"id": "s1"}, "thread_id": "t1"}
        out_explicit = _run_toolnode(explicit, state, configurable)
        out_builtin = _run_toolnode(builtin, state, configurable)
    payload_explicit = _tool_result_event(out_explicit)["payload"]
    payload_builtin = _tool_result_event(out_builtin)["payload"]
    # call_id 每次运行随机生成，latency_ms 也受线程调度影响；比较其余业务字段
    # 是否一致，验证两条执行路径的目录、分派与受控展示投影等价。
    ignored_keys = {"call_id", "latency_ms"}
    assert {key: value for key, value in payload_explicit.items() if key not in ignored_keys} == {
        key: value for key, value in payload_builtin.items() if key not in ignored_keys
    }
    assert payload_explicit["ok"] is True
    assert payload_explicit["name"] == "read"


def test_toolnode_failure_via_manager_keeps_error_payload() -> None:
    """工具失败（文件不存在）经 manager 仍产出关联 call_id 的 ok=False 事件。"""
    registry = build_default_registry()
    node = build_tool_node(registry)
    with tempfile.TemporaryDirectory() as tmp:
        state: GraphState = {
            "request": {"config": {}, "messages": ()},
            "pending_tool": {"name": "read", "arguments": {"path": "missing.txt"}},
        }
        configurable = {"sandbox": {"dir": tmp}, "session": {"id": "s2"}, "thread_id": "t2"}
        out = _run_toolnode(node, state, configurable)
    payload = _tool_result_event(out)["payload"]
    assert payload["ok"] is False
    assert payload["error"] == "操作失败（NOT_FOUND）"
    assert payload["redacted"] is True
    assert payload["call_id"].startswith("toolcall_")
