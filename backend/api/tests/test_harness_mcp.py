"""内部 MCP Host（阶段 D，P3）测试。

覆盖：MCP 扩展 catalog（tools/list / refresh / 名称冲突）、manager（tools/call
成功/失败/未知/超时/取消/close）、/api/mcp/tools 的真实空目录，以及原生基础
工具不经过 manager 的隔离边界。不依赖数据库连接。
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
    transport: str = "mcp",
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
        output_schema={},  # 显式空：无结构化展示投影
        transport=transport,  # type: ignore[arg-type]
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


def test_catalog_only_exposes_platform_task_mcp_extensions() -> None:
    catalog = ToolCatalog.build(build_default_registry())
    descriptors = catalog.all_descriptors()
    assert {descriptor.tool_id for descriptor in descriptors} == {
        "platform.tasks.task.create",
        "platform.tasks.task.status",
        "platform.tasks.task.cancel",
    }
    assert catalog.servers() == ("platform.tasks",)
    assert catalog.resolve_name("task.create") == "platform.tasks.task.create"
    assert catalog.resolve_name("read") is None
    assert catalog.resolve_name("bash") is None
    assert catalog.get("nope") is None


def test_catalog_exposes_media_mcp_only_when_enabled(monkeypatch) -> None:
    """媒体目录受总开关控制，关闭时不把未接通工具暴露给模型或管理端。"""
    from app.harness.execution import registry as registry_module

    monkeypatch.setattr(registry_module.settings, "media_mcp_enabled", True)
    catalog = ToolCatalog.build(build_default_registry())
    assert {
        descriptor.tool_id for descriptor in catalog.all_descriptors()
        if descriptor.server_id == "media.generation"
    } == {
        "media.generation.image.generate",
        "media.generation.video.create",
        "media.generation.video.status",
    }


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


def test_catalog_ignores_native_definition_with_server_metadata() -> None:
    """MCP 目录按 transport 过滤，不能因 server_id 误暴露基础工具。"""
    registry = ToolRegistry()
    registry.register(_def("native", transport="native"))
    assert ToolCatalog.build(registry).all_descriptors() == ()


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
    registry = ToolRegistry()
    registry.register(_def("ping", server_id="platform.test", handler=lambda *_args: "hello world"))

    async def run() -> None:
        manager = MCPClientManager.build_from_registry(registry)
        result = await manager.call_tool(
            "platform.test.ping",
            {},
            ToolExecutionContext(call_id="c1"),
        )
        assert result.ok is True
        assert result.call_id == "c1"
        assert result.data["summary"] == "hello world"
        await manager.close()

    asyncio.run(run())


def test_manager_call_app_error_normalized_not_found() -> None:
    def missing(*_args: object) -> str:
        raise AppError(ErrorCode.NOT_FOUND, "不存在")

    registry = ToolRegistry()
    registry.register(_def("lookup", server_id="platform.test", handler=missing))

    async def run() -> None:
        manager = MCPClientManager.build_from_registry(registry)
        result = await manager.call_tool(
            "platform.test.lookup",
            {},
            ToolExecutionContext(call_id="c2"),
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
            "platform.tasks.task.status",
            {"task_id": "task-1"},
            ToolExecutionContext(call_id="c6"),
        )
        assert result.ok is False
        assert result.error["code"] == "INTERNAL"

    asyncio.run(run())


# —— /api/mcp/tools 只读目录 ——


def test_mcp_tools_router_lists_internal_catalog() -> None:
    from app.routers.mcp import list_tools

    payload = list_tools(user=None)
    assert payload["total"] == 3
    items = payload["items"]
    names = {item["name"] for item in items}
    assert names == {
        "platform.tasks.task.create",
        "platform.tasks.task.status",
        "platform.tasks.task.cancel",
    }
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


def test_toolnode_native_tool_ignores_mcp_manager() -> None:
    """基础 read 走直连执行器，传入空 MCP manager 也不会改变执行结果。"""
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
    # call_id 每次运行随机生成；latency_ms 为实测耗时（毫秒取整），两次独立执行
    # 必然存在亚毫秒抖动（CI 上曾出现 0 vs 1）。其余 payload 必须一致
    # （证明两条执行路径等价）。
    excluded = {"call_id", "latency_ms"}
    assert {key: value for key, value in payload_explicit.items() if key not in excluded} == {
        key: value for key, value in payload_builtin.items() if key not in excluded
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
