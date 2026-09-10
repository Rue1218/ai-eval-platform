"""M5 执行层单测（X-A4/X-A7/EX-5 等）；不依赖 DB。"""

import asyncio
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy.orm import Session

import app.harness.execution.toolnode as toolnode_mod
from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall
from app.harness.execution import (
    NativeToolResultStore,
    ToolDef,
    ToolRegistry,
    build_default_registry,
    build_tool_node,
    edit_file_safe,
    execute,
    read_file_safe,
    run_bash,
    validate_tool_arguments,
    validate_tool_output,
    validate_tool_schema,
    write_file_safe,
)
from app.harness.execution.session_guard import assert_no_orm_leak
from app.harness.execution.worker_bridge import LONG_TOOLS, TASK_KINDS
from app.harness.memory import GraphState


def _handler_factory(name: str):
    """构造可注入 handler。"""

    def handler(arguments: dict, sandbox_dir: str | None = None) -> str:
        return f"{name}:{arguments.get('key', '')}"

    return handler


def test_registry_rejects_duplicate_register() -> None:
    """EX-5：重名登记拒绝（防止分派漂移）。"""
    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="dup",
            description="d",
            parameters_schema={},
            permission="p",
            timeout_s=1.0,
            handler=_handler_factory("dup"),
            output_schema={},
        )
    )
    with pytest.raises(AppError) as error:
        registry.register(
            ToolDef(
                name="dup",
                description="d2",
                parameters_schema={},
                permission="p",
                timeout_s=1.0,
                handler=_handler_factory("dup2"),
                output_schema={},
            )
        )
    assert error.value.code == ErrorCode.VALIDATION

def test_registry_get_unregistered_rejected() -> None:
    """未注册工具调用一律拒绝。"""
    registry = build_default_registry()
    with pytest.raises(AppError) as error:
        registry.get("nope")
    assert error.value.code == ErrorCode.VALIDATION


def test_default_registry_includes_bash() -> None:
    """阶段 3 开放通用 bash（bwrap 沙箱）：默认注册表含 bash。"""
    registry = build_default_registry()
    assert registry.is_registered("bash") is True
    bash_def = registry.get_def("bash")
    assert bash_def is not None
    assert bash_def["permission"] == "sandbox.bash"
    assert bash_def["output_schema"]["type"] == "object"
    assert bash_def["permission_policy"]["workspace"] == "write"
    assert bash_def["recovery_policy"]["suggested_action"] == "reduce_command_scope"
    names = {definition["name"] for definition in registry.all_defs()}
    assert names == {
        "read",
        "read_image",
        "glob",
        "grep",
        "write",
        "edit",
        "web_search",
        "web_fetch",
        "bash",
        "task",
        "TaskCreate",
        "TaskGet",
        "TaskUpdate",
        "TaskList",
        "ask_user_question",
        "task.create",
        "task.status",
        "task.cancel",
    }


def test_tool_schema_validation_rejects_invalid_and_extra_arguments() -> None:
    """ToolNode 前的 schema 校验拒绝类型错误、缺字段和未声明参数。"""
    read_schema = build_default_registry().get("read").parameters_schema
    assert validate_tool_arguments(read_schema, {"file_path": 1}) == "参数 file_path 类型无效，应为 string"
    assert validate_tool_arguments(read_schema, {"offset": 0}) == "缺少必填参数：file_path"
    assert validate_tool_arguments(read_schema, {"file_path": "a.txt", "unsafe": True}) == "包含未允许的参数：unsafe"


def test_array_max_items_enforced_at_runtime() -> None:
    """minItems/maxItems 运行期校验：超长/欠长数组被 VALIDATION 拒绝。"""
    registry = build_default_registry()
    # TaskUpdate.addBlocks/addBlockedBy 上限 20
    update_schema = registry.get("TaskUpdate").parameters_schema
    over = {"taskId": "t1", "status": "pending", "addBlocks": [f"x{i}" for i in range(21)]}
    assert "不能多于 20" in (validate_tool_arguments(update_schema, over) or "")
    ok = {"taskId": "t1", "status": "pending", "addBlocks": ["a", "b"]}
    assert validate_tool_arguments(update_schema, ok) is None
    # ask_user_question.questions 下限 1 / 上限 5
    ask_schema = registry.get("ask_user_question").parameters_schema
    assert "不能少于 1" in (validate_tool_arguments(ask_schema, {"questions": []}) or "")
    too_many = {"questions": [{"id": f"q{i}", "question": "x", "options": []} for i in range(6)]}
    assert "不能多于 5" in (validate_tool_arguments(ask_schema, too_many) or "")


def test_registry_rejects_unsupported_tool_schema_keywords() -> None:
    """未知 JSON Schema 关键字必须在注册期失败，不能运行时静默放行。"""
    assert validate_tool_schema({"type": "object", "$ref": "#/defs/input"})
    registry = ToolRegistry()
    with pytest.raises(AppError) as error:
        registry.register(
            ToolDef(
                name="invalid-schema",
                description="不支持的 Schema",
                parameters_schema={"type": "object", "oneOf": []},
                permission="test.read",
                timeout_s=1.0,
                handler=_handler_factory("invalid-schema"),
                output_schema={},
            )
        )
    assert error.value.code == ErrorCode.VALIDATION

    with pytest.raises(AppError) as output_error:
        registry.register(
            ToolDef(
                name="bad_output",
                description="d",
                parameters_schema={},
                output_schema={"$ref": "#/defs/output"},
                permission="p",
                timeout_s=1.0,
                handler=_handler_factory("bad_output"),
            )
        )
    assert output_error.value.code == ErrorCode.VALIDATION
    assert "输出 Schema" in output_error.value.message
    assert "oneOf" in error.value.message


def test_tool_schema_required_fields_must_be_declared() -> None:
    """注册期拒绝 required 指向不存在 properties 的无效 JSON Schema。"""
    schema = {
        "type": "object",
        "properties": {"known": {"type": "string"}},
        "required": ["missing"],
    }
    assert validate_tool_schema(schema) == "arguments.required 包含未声明字段：missing"

    registry = ToolRegistry()
    with pytest.raises(AppError) as error:
        registry.register(
            ToolDef(
                name="invalid-required-output",
                description="无效输出字段",
                parameters_schema={},
                output_schema=schema,
                permission="test.read",
                timeout_s=1.0,
                handler=_handler_factory("invalid-required-output"),
            )
        )
    assert error.value.code == ErrorCode.VALIDATION


def test_read_image_output_schema_checks_display_projection() -> None:
    """图片工具校验对外 display，而非含模型图文块的内部包装。"""
    output_schema = build_default_registry().get("read_image").output_schema

    class _ImageResult:
        """模拟含内部模型字段的图片结果，展示投影保持对外契约。"""

        def to_tool_data(self) -> dict[str, object]:
            return {
                "summary": "已读取图片 sample.png",
                "model_text": "已读取图片 sample.png",
                "model_content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
                "display": {
                    "summary": "已读取图片 sample.png",
                    "status": "success",
                    "read_image": {
                        "path": "sample.png",
                        "media_type": "image/png",
                        "size_bytes": 1,
                        "width": 1,
                        "height": 1,
                    },
                },
            }

    def image_handler(_arguments: dict, _sandbox_dir: str | None = None) -> _ImageResult:
        """返回模拟图片结果，供执行器验证投影层级。"""
        return _ImageResult()

    observation = execute(
        ToolCall(name="read_image", arguments={"file_path": "sample.png"}),
        timeout_s=1.0,
        permission="sandbox.read",
        handler=image_handler,
        output_schema=output_schema,
    )
    assert observation.ok is True
    output_error = validate_tool_output(
        output_schema,
        {
            "summary": "已读取图片 sample.png",
            "status": "success",
            "read_image": {
                "path": "sample.png",
                "media_type": "image/png",
                "size_bytes": 1,
                "width": 1,
                "height": 1,
                "unexpected": True,
            },
        },
    )
    assert output_error is not None
    assert "unexpected" in output_error


def test_seal_budget_if_exhausted_appends_error_once() -> None:
    """工具队列清空且预算耗尽时补一条 BUDGET_EXCEEDED，已有 error 不叠第二条。"""
    from app.harness.execution.toolnode import seal_budget_if_exhausted

    empty = seal_budget_if_exhausted(
        {"pending_tool": None, "pending_events": [{"kind": "tool_result"}]},
        {"budget": {"model_calls": 0, "tool_turns": 1}},
    )
    kinds = [event["kind"] for event in empty["pending_events"]]
    assert kinds.count("error") == 1
    assert empty["pending_events"][-1]["payload"]["code"] == "BUDGET_EXCEEDED"
    assert empty["turn_failed"] is True

    queued = seal_budget_if_exhausted(
        {"pending_tool": {"name": "read"}, "pending_events": []},
        {"budget": {"model_calls": 0, "tool_turns": 0}},
    )
    assert queued.get("turn_failed") is None
    assert queued["pending_events"] == []

    already = seal_budget_if_exhausted(
        {
            "pending_tool": None,
            "pending_events": [{"kind": "error", "payload": {"code": "VALIDATION"}}],
        },
        {"budget": {"model_calls": 0, "tool_turns": 0}},
    )
    assert [event["kind"] for event in already["pending_events"]] == ["error"]
    assert already["turn_failed"] is True


def test_toolnode_rejection_keeps_native_call_id_and_skips_dispatch() -> None:
    """未知工具与 schema 拒绝均产出关联的 ToolCard 结果，不进入执行器。"""
    registry = build_default_registry()
    result_store = NativeToolResultStore()
    node = build_tool_node(registry, native_tool_results=result_store)
    configurable = {"thread_id": "toolnode-native-test"}

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {"configurable": configurable}
    try:
        unknown = asyncio.run(
            node(
                {
                    "request": {"config": {}, "messages": ()},
                    "pending_tool": {
                        "call_id": "unknown_call",
                        "name": "not_registered",
                        "arguments": {},
                        "native": True,
                    },
                }
            )
        )
        invalid = asyncio.run(
            node(
                {
                    "request": {"config": {}, "messages": ()},
                    "pending_tool": {
                        "call_id": "invalid_call",
                        "name": "read",
                        "arguments": {"path": 1},
                        "native": True,
                    },
                }
            )
        )
    finally:
        toolnode_mod.get_config = original

    for out, call_id in ((unknown, "unknown_call"), (invalid, "invalid_call")):
        events = out["pending_events"]
        # ToolCall 已由 ReAct 在进入 ToolNode 前持久化，避免瞬态工具输出先于
        # 卡片到达；ToolNode 拒绝路径只补齐关联结果与错误。
        assert [event["kind"] for event in events] == ["tool_result", "error"]
        assert events[0]["payload"]["call_id"] == call_id
        assert events[0]["payload"]["ok"] is False
        assert events[1]["payload"]["code"] == "VALIDATION"
        assert out["native_messages"][0]["content"] == ""
    assert result_store.get("toolnode-native-test", "unknown_call") == "工具未注册：not_registered"
    assert "类型无效" in str(result_store.get("toolnode-native-test", "invalid_call"))


def test_tool_batch_refill_keeps_original_block_order() -> None:
    """P2：即使后完成的项先标记终态，回填仍按原始 block_index。"""
    from app.harness.execution.batch import (
        batch_is_complete,
        build_tool_batch,
        mark_batch_item,
        native_result_messages,
    )

    batch = build_tool_batch(
        [
            {"call_id": "call_read", "name": "read", "arguments": {"path": "a.txt"}, "native": True},
            {
                "call_id": "call_write",
                "name": "write",
                "arguments": {"path": "b.txt", "content": "x"},
                "native": True,
            },
        ],
        batch_id="batch_order",
    )
    # 模拟乱序完成：write 先成功、read 后失败，回填仍必须是 read → write。
    updated = mark_batch_item(batch, "call_write", "succeeded")
    updated = mark_batch_item(updated, "call_read", "failed")
    assert batch_is_complete(updated)
    assert [message["tool_call_id"] for message in native_result_messages(updated)] == [
        "call_read",
        "call_write",
    ]


def test_toolnode_batch_flushes_native_messages_once_in_original_order() -> None:
    """P2：失败+成功同批时，中间项不回填，全部终态后按原 call_id 组装。"""
    registry = build_default_registry()
    result_store = NativeToolResultStore()
    from app.harness.execution.batch import build_tool_batch

    unknown = {
        "call_id": "call_unknown",
        "name": "not_registered",
        "arguments": {},
        "native": True,
    }
    read_call = {
        "call_id": "call_read",
        "name": "read",
        "arguments": {"path": "a.txt"},
        "native": True,
    }
    batch = build_tool_batch([unknown, read_call], batch_id="batch_fail_ok")
    configurable = {"thread_id": "toolnode-batch-test"}
    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {"configurable": configurable}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8") as handle:
                handle.write("batch-ok")
            node = build_tool_node(
                registry, native_tool_results=result_store, sandbox_dir=tmp
            )
            first = asyncio.run(
                node(
                    {
                        "request": {"config": {}, "messages": ()},
                        "pending_tool": unknown,
                        "pending_tools": [read_call],
                        "pending_tool_batch": batch,
                    }
                )
            )
            assert "native_messages" not in first
            assert first["pending_tool"]["call_id"] == "call_read"
            second = asyncio.run(
                node(
                    {
                        "request": {"config": {}, "messages": ()},
                        "pending_tool": first["pending_tool"],
                        "pending_tools": first["pending_tools"],
                        "pending_tool_batch": first["pending_tool_batch"],
                    }
                )
            )
    finally:
        toolnode_mod.get_config = original

    assert second["pending_tool"] is None
    assert [message["tool_call_id"] for message in second["native_messages"]] == [
        "call_unknown",
        "call_read",
    ]
    assert result_store.get("toolnode-batch-test", "call_unknown") == "工具未注册：not_registered"
    assert "batch-ok" in str(result_store.get("toolnode-batch-test", "call_read"))


def test_select_execution_wave_serial_when_flag_off() -> None:
    """开关关闭时即使两个独立 read 也只切出一项。"""
    from app.harness.execution.batch import select_execution_wave

    items = [
        {"call_id": "a", "name": "read", "arguments": {"path": "a.txt"}},
        {"call_id": "b", "name": "read", "arguments": {"path": "b.txt"}},
    ]
    wave = select_execution_wave(
        items, class_of={"read": "path_scoped"}, enabled=False, max_parallel=3
    )
    assert [item["call_id"] for item in wave] == ["a"]


def test_select_execution_wave_parallel_reads_and_barriers() -> None:
    """P3：独立 read/web 可并行；同路径写、bash、task.create 做屏障。"""
    from app.harness.execution.batch import (
        normalize_workspace_path,
        select_execution_wave,
    )

    class_of = {
        "read": "path_scoped",
        "web_search": "read_only",
        "web_fetch": "read_only",
        "write": "path_scoped",
        "bash": "exclusive",
        "task.create": "session_exclusive",
    }
    reads = [
        {"call_id": "r1", "name": "read", "arguments": {"path": "a.txt"}},
        {"call_id": "r2", "name": "read", "arguments": {"path": "./a.txt"}},
        {"call_id": "w1", "name": "web_search", "arguments": {"query": "x"}},
        {"call_id": "w2", "name": "write", "arguments": {"path": "b.txt", "content": "x"}},
    ]
    wave = select_execution_wave(reads, class_of=class_of, enabled=True, max_parallel=3)
    assert [item["call_id"] for item in wave] == ["r1", "r2", "w1"]
    assert normalize_workspace_path("a.txt") == normalize_workspace_path("./a.txt")
    assert normalize_workspace_path("foo/../a.txt") == normalize_workspace_path("a.txt")

    mixed = [
        {"call_id": "r1", "name": "read", "arguments": {"path": "a.txt"}},
        {"call_id": "wr", "name": "write", "arguments": {"path": "a.txt", "content": "x"}},
    ]
    assert [item["call_id"] for item in select_execution_wave(
        mixed, class_of=class_of, enabled=True, max_parallel=3
    )] == ["r1"]

    bash_first = [
        {"call_id": "b1", "name": "bash", "arguments": {"command": "ls"}},
        {"call_id": "r1", "name": "read", "arguments": {"path": "a.txt"}},
    ]
    assert [item["call_id"] for item in select_execution_wave(
        bash_first, class_of=class_of, enabled=True, max_parallel=3
    )] == ["b1"]

    create_first = [
        {"call_id": "c1", "name": "task.create", "arguments": {"kind": "benchmark"}},
        {"call_id": "r1", "name": "read", "arguments": {"path": "a.txt"}},
    ]
    assert [item["call_id"] for item in select_execution_wave(
        create_first, class_of=class_of, enabled=True, max_parallel=3
    )] == ["c1"]

    four_reads = [
        {"call_id": f"r{i}", "name": "read", "arguments": {"path": f"{i}.txt"}}
        for i in range(4)
    ]
    assert len(select_execution_wave(
        four_reads, class_of=class_of, enabled=True, max_parallel=3
    )) == 3

    class_of["task.status"] = "read_only"
    status_after_read = [
        {"call_id": "r1", "name": "read", "arguments": {"path": "a.txt"}},
        {"call_id": "s1", "name": "task.status", "arguments": {"task_id": "t1"}},
    ]
    assert [item["call_id"] for item in select_execution_wave(
        status_after_read, class_of=class_of, enabled=True, max_parallel=3
    )] == ["r1"]


def test_toolnode_flag_off_still_one_call_per_visit() -> None:
    """默认关闭并行时，一次 ToolNode 访问只执行批次头一项。"""
    registry = build_default_registry()
    result_store = NativeToolResultStore()
    from app.harness.execution.batch import build_tool_batch

    first = {
        "call_id": "call_a",
        "name": "read",
        "arguments": {"path": "a.txt"},
        "native": True,
    }
    second = {
        "call_id": "call_b",
        "name": "read",
        "arguments": {"path": "b.txt"},
        "native": True,
    }
    batch = build_tool_batch([first, second], batch_id="batch_serial")
    configurable = {"thread_id": "toolnode-serial-wave"}
    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {"configurable": configurable}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in (("a.txt", "A"), ("b.txt", "B")):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                    handle.write(text)
            node = build_tool_node(
                registry, native_tool_results=result_store, sandbox_dir=tmp
            )
            out = asyncio.run(
                node(
                    {
                        "request": {"config": {}, "messages": ()},
                        "pending_tool": first,
                        "pending_tools": [second],
                        "pending_tool_batch": batch,
                    }
                )
            )
    finally:
        toolnode_mod.get_config = original

    results = [event for event in out["pending_events"] if event["kind"] == "tool_result"]
    assert [event["payload"]["call_id"] for event in results] == ["call_a"]
    assert out["pending_tool"]["call_id"] == "call_b"
    assert "native_messages" not in out


def test_toolnode_parallel_reads_one_visit(monkeypatch) -> None:
    """打开并行后，两个独立 read 在一次访问内完成，且真正重叠执行。"""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", True)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    from app.harness.execution.stream_metrics import get_default_stream_metrics

    get_default_stream_metrics().reset()
    barrier = threading.Barrier(2, timeout=2)

    def overlapping_read(arguments, sandbox_dir, context) -> str:
        barrier.wait()
        path = os.path.join(sandbox_dir or "", str(arguments.get("path") or ""))
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="read",
            description="并行读",
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            permission="sandbox.read",
            timeout_s=3.0,
            handler=overlapping_read,
            transport="native",
            contextual=True,
            concurrency_class="path_scoped",
            output_schema={},
        )
    )
    result_store = NativeToolResultStore()
    from app.harness.execution.batch import build_tool_batch

    first = {
        "call_id": "call_a",
        "name": "read",
        "arguments": {"path": "a.txt"},
        "native": True,
    }
    second = {
        "call_id": "call_b",
        "name": "read",
        "arguments": {"path": "b.txt"},
        "native": True,
    }
    batch = build_tool_batch([first, second], batch_id="batch_parallel")
    configurable = {"thread_id": "toolnode-parallel-wave"}
    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {"configurable": configurable}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in (("a.txt", "A"), ("b.txt", "B")):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                    handle.write(text)
            node = build_tool_node(
                registry, native_tool_results=result_store, sandbox_dir=tmp
            )
            out = asyncio.run(
                node(
                    {
                        "request": {"config": {}, "messages": ()},
                        "pending_tool": first,
                        "pending_tools": [second],
                        "pending_tool_batch": batch,
                    }
                )
            )
    finally:
        toolnode_mod.get_config = original

    results = [event for event in out["pending_events"] if event["kind"] == "tool_result"]
    assert [event["payload"]["call_id"] for event in results] == ["call_a", "call_b"]
    assert all(event["payload"]["ok"] is True for event in results)
    assert out["pending_tool"] is None
    assert [message["tool_call_id"] for message in out["native_messages"]] == [
        "call_a",
        "call_b",
    ]
    assert result_store.get("toolnode-parallel-wave", "call_a") == "A"
    assert result_store.get("toolnode-parallel-wave", "call_b") == "B"


def test_toolnode_parallel_failure_does_not_cancel_sibling(monkeypatch) -> None:
    """并行组内单项失败不取消同组其他只读调用。"""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", True)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    from app.harness.execution.stream_metrics import get_default_stream_metrics

    get_default_stream_metrics().reset()

    def boom(_arguments, _sandbox_dir=None, _context=None) -> str:
        raise RuntimeError("boom")

    def ok(_arguments, _sandbox_dir=None, _context=None) -> str:
        return "ok"

    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="read",
            description="会失败的读",
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            permission="sandbox.read",
            timeout_s=2.0,
            handler=boom,
            transport="native",
            contextual=True,
            concurrency_class="path_scoped",
            output_schema={},
        )
    )
    registry.register(
        ToolDef(
            name="web_fetch",
            description="独立抓取",
            parameters_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
            permission="web.fetch",
            timeout_s=2.0,
            handler=ok,
            transport="native",
            concurrency_class="read_only",
            output_schema={},
        )
    )
    result_store = NativeToolResultStore()
    from app.harness.execution.batch import build_tool_batch

    first = {
        "call_id": "call_read",
        "name": "read",
        "arguments": {"path": "a.txt"},
        "native": True,
    }
    second = {
        "call_id": "call_web",
        "name": "web_fetch",
        "arguments": {"url": "https://example.com"},
        "native": True,
    }
    batch = build_tool_batch([first, second], batch_id="batch_isolate")
    configurable = {"thread_id": "toolnode-parallel-isolate"}
    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: {"configurable": configurable}
    try:
        node = build_tool_node(registry, native_tool_results=result_store, sandbox_dir=".")
        out = asyncio.run(
            node(
                {
                    "request": {"config": {}, "messages": ()},
                    "pending_tool": first,
                    "pending_tools": [second],
                    "pending_tool_batch": batch,
                }
            )
        )
    finally:
        toolnode_mod.get_config = original

    results = [event for event in out["pending_events"] if event["kind"] == "tool_result"]
    by_id = {event["payload"]["call_id"]: event["payload"] for event in results}
    assert by_id["call_read"]["ok"] is False
    assert by_id["call_web"]["ok"] is True
    assert [message["tool_call_id"] for message in out["native_messages"]] == [
        "call_read",
        "call_web",
    ]


def test_default_registry_concurrency_classes_not_in_all_defs() -> None:
    """并发类只留在运行时 ToolDef，不投影给模型或目录。"""
    registry = build_default_registry()
    assert registry.get("read").concurrency_class == "path_scoped"
    assert registry.get("web_search").concurrency_class == "read_only"
    assert registry.get("bash").concurrency_class == "exclusive"
    assert registry.get("task.create").concurrency_class == "session_exclusive"
    assert registry.get("task.status").concurrency_class == "read_only"
    assert all("concurrency_class" not in item for item in registry.all_defs())
    assert not hasattr(registry.get("read").to_descriptor(), "concurrency_class")


def test_toolnode_streams_scoped_progress_and_output(monkeypatch) -> None:
    """工具流只经 custom 通道输出受控块，持久终态仍保持 tool_result。"""
    registry = ToolRegistry()

    def stream_handler(_arguments, _sandbox_dir, context) -> str:
        assert context.report_progress is not None
        assert context.report_output is not None
        context.report_progress("executing", "正在生成测试输出")
        context.report_output("stdout", "第一行\n第二行\n", None)
        return "完成"

    registry.register(
        ToolDef(
            name="stream_test",
            description="流式测试工具",
            parameters_schema={"type": "object", "additionalProperties": False},
            permission="test.read",
            timeout_s=1.0,
            handler=stream_handler,
            transport="native",
            supports_streaming=True,
            contextual=True,
            output_schema={},
        )
    )
    frames: list[dict] = []
    monkeypatch.setattr(
        toolnode_mod,
        "get_config",
        lambda: {"configurable": {"thread_id": "stream-test"}},
    )
    monkeypatch.setattr(toolnode_mod, "get_stream_writer", lambda: frames.append)
    out = asyncio.run(
        build_tool_node(registry, native_tool_results=NativeToolResultStore())(
            {
                "request": {"config": {}, "messages": ()},
                "pending_tool": {
                    "call_id": "stream-call",
                    "name": "stream_test",
                    "arguments": {},
                    "native": True,
                },
            }
        )
    )

    assert [event["kind"] for event in out["pending_events"]] == ["tool_result"]
    assert any(frame["kind"] == "tool_progress" and frame["call_id"] == "stream-call" for frame in frames)
    output = next(frame for frame in frames if frame["kind"] == "tool_output_delta")
    assert output["text"] == "第一行\n第二行\n"
    assert output["seq"] == 1
    assert output["start_line"] == 1


def test_all_defs_serializable_without_handler() -> None:
    """all_defs 可序列化投影（不含 handler）。"""
    definitions = build_default_registry().all_defs()
    assert all("handler" not in definition for definition in definitions)
    json.dumps(definitions)


def test_bash_no_blocklist_static_adjudication(monkeypatch) -> None:
    """F2/G4：词表与静态裁决删除（§6.3）——提权/网络/破坏命令不再字符串拦截。"""
    import app.harness.execution.dispatch as dispatch

    captured: dict[str, object] = {}

    def fake_run_sandboxed(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["mode"] = kwargs["mode"]
        return "沙箱输出"

    monkeypatch.setattr(dispatch, "run_sandboxed", fake_run_sandboxed)
    for command in ("sudo whoami", "curl http://x", "wget http://x", "rm -f result.md"):
        run_bash(command, sandbox_dir="/tmp/ws", mode="workspace-write", timeout_s=15.0)
    # 全部命令直通沙箱（未拦截），档位原样透传
    assert captured["cmd"] == "rm -f result.md"
    assert captured["mode"] == "workspace-write"


def test_run_bash_delegates_to_sandbox(monkeypatch) -> None:
    """EX-6：bash 执行走 bwrap 沙箱内核，而非裸 subprocess。"""
    import app.harness.execution.dispatch as dispatch

    captured: dict[str, object] = {}

    def fake_run_sandboxed(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["sandbox_dir"] = kwargs["sandbox_dir"]
        captured["mode"] = kwargs["mode"]
        captured["timeout_s"] = kwargs["timeout_s"]
        return "沙箱输出"

    monkeypatch.setattr(dispatch, "run_sandboxed", fake_run_sandboxed)
    result = run_bash("echo hi", sandbox_dir="/tmp/ws", timeout_s=15.0)
    assert result == "沙箱输出"
    assert captured["cmd"] == "echo hi"
    assert captured["sandbox_dir"] == "/tmp/ws"
    assert captured["mode"] == "workspace-write"
    assert captured["timeout_s"] == 15.0


def test_run_bash_fail_closed_when_sandbox_unavailable(monkeypatch) -> None:
    """EX-6：沙箱引擎不可用（bwrap 缺失/seccomp 拦截）时 fail-closed。"""
    import app.harness.execution.dispatch as dispatch

    def fake_run_sandboxed(*_args, **_kwargs):
        raise AppError(ErrorCode.VALIDATION, "沙箱引擎不可用")

    monkeypatch.setattr(dispatch, "run_sandboxed", fake_run_sandboxed)
    with pytest.raises(AppError) as error:
        run_bash("echo hi", sandbox_dir="/tmp/ws", timeout_s=15.0)
    assert error.value.code == ErrorCode.VALIDATION
    assert "沙箱引擎不可用" in error.value.message


def test_bash_handler_engine_off_rejected(monkeypatch) -> None:
    """EX-6：引擎开关为 off 时 bash 工具 fail-closed。"""
    from app.config import settings
    from app.harness.execution.registry import _bash_handler

    monkeypatch.setattr(settings, "sandbox_engine", "off")
    with pytest.raises(AppError) as error:
        _bash_handler({"command": "echo hi"}, "/tmp/ws")
    assert error.value.code == ErrorCode.VALIDATION
    assert "沙箱引擎未启用" in error.value.message


def test_read_write_edit_sandbox_escape_rejected() -> None:
    """受控目录防目录穿越：绝对路径/越界相对路径拒绝。"""
    with tempfile.TemporaryDirectory() as root:
        with pytest.raises(AppError):
            read_file_safe("/etc/passwd", root)
        with pytest.raises(AppError):
            read_file_safe("../../secret.txt", root)


def test_read_write_edit_roundtrip() -> None:
    """受控目录 read/write/edit 正常往返。"""
    with tempfile.TemporaryDirectory() as root:
        write_file_safe("a.txt", "hello", root)
        assert read_file_safe("a.txt", root).content == "hello"
        edit_file_safe("a.txt", "hello", "hello world", root)
        assert read_file_safe("a.txt", root).content == "hello world"
        with pytest.raises(AppError) as error:
            edit_file_safe("a.txt", "不存在", "x", root)
        assert error.value.code == ErrorCode.VALIDATION
        assert error.value.fields
        assert "行" in str(error.value.fields.get("repair_hint") or "")
        with pytest.raises(AppError):
            write_file_safe("a.txt", "x", root)


def test_edit_mismatch_observation_keeps_repair_hint() -> None:
    """edit 失败经 execute 归一后，repair_hint 含行号或邻近文本，且不进展示正文。"""
    from app.harness.execution.registry import _edit_handler

    with tempfile.TemporaryDirectory() as root:
        write_file_safe("note.txt", "alpha\nhello world\nomega\n", root)
        observation = execute(
            ToolCall(
                name="edit",
                arguments={"path": "note.txt", "old": "不存在的片段", "new": "x"},
            ),
            timeout_s=10.0,
            permission="sandbox.write",
            sandbox_dir=root,
            handler=_edit_handler,
        )
    assert observation.ok is False
    assert "行" in observation.repair_hint
    assert "hello" in observation.repair_hint
    assert observation.text == "操作失败（VALIDATION）"


def test_read_edit_task_descriptions_include_preconditions() -> None:
    """P0：read/edit/task 描述写清适用、不适用与前置条件。"""
    registry = build_default_registry()
    read_def = registry.find("read")
    edit_def = registry.find("edit")
    task_def = registry.find("task")
    assert read_def is not None and "适用" in read_def.description and "前置" in read_def.description
    assert edit_def is not None and "先 read" in edit_def.description
    assert task_def is not None and "不适用" in task_def.description


def test_read_file_safe_supports_offset_and_limit() -> None:
    """read 工具按行分页，未读完返回准确 next_offset。"""
    with tempfile.TemporaryDirectory() as root:
        write_file_safe("long.txt", "zero\none\ntwo\nthree\nfour", root)
        all_lines = read_file_safe("long.txt", root)
        assert all_lines.content == "zero\none\ntwo\nthree\nfour"
        assert all_lines.total_lines == 5
        assert all_lines.is_complete is True
        assert read_file_safe("long.txt", root, offset=4).content == "four"
        beyond = read_file_safe("long.txt", root, offset=100)
        assert beyond.content == ""
        assert beyond.is_complete is True
        # 未读完时只返回完整行，next_offset 指向下一行。
        first = read_file_safe("long.txt", root, limit=3)
        assert first.content == "zero\none\ntwo\n"
        assert first.start_line == 0
        assert first.end_line == 3
        assert first.next_offset == 3
        assert first.is_complete is False
        second = read_file_safe("long.txt", root, offset=2, limit=3)
        assert second.content == "two\nthree\nfour"
        assert second.next_offset is None


def test_read_file_safe_default_limit_returns_first_2000_lines() -> None:
    """read 默认返回前 2000 行，并用 next_offset 指向后续内容。"""
    with tempfile.TemporaryDirectory() as root:
        body = "\n".join("x" for _ in range(3000))
        write_file_safe("big.txt", body, root)
        result = read_file_safe("big.txt", root)
        assert result.total_lines == 3000
        assert result.lines_read == 2000
        assert result.start_line == 0
        assert result.end_line == 2000
        assert result.next_offset == 2000
        assert result.is_complete is False
        assert result.content.splitlines()[0] == "x"
        assert result.content.splitlines()[-1] == "x"
        assert "offset=2000" in result.to_tool_data()["model_text"]


def test_read_file_safe_accepts_the_agent_attachment_size_limit(tmp_path) -> None:
    """read 文件上限与 Agent 附件 20MB 契约一致，避免上传成功后再被拒绝。"""
    from app.harness.execution.dispatch import READ_MAX_BYTES

    assert READ_MAX_BYTES == 20 * 1024 * 1024


def test_read_file_safe_stops_on_character_budget_at_line_boundary() -> None:
    """字符预算触发时不截断半行，next_offset 与实际结束行一致。"""
    from app.harness.execution.dispatch import READ_MAX_CHARS

    with tempfile.TemporaryDirectory() as root:
        # 2000 行 × 400 字符 = 800k > 600k 预算，触发字符边界停止。
        write_file_safe("huge.txt", "\n".join("y" * 400 for _ in range(2000)), root)
        result = read_file_safe("huge.txt", root)
        assert result.lines_read < 2000
        assert result.total_lines == 2000
        assert result.end_line == result.lines_read
        assert result.next_offset == result.lines_read
        assert result.content.endswith("\n")
        assert result.content_truncated is True
        model_text = str(result.to_tool_data()["model_text"])
        assert len(model_text) <= READ_MAX_CHARS
        display = result.to_tool_data()["display"]["read"]
        preview = str(display["preview"])
        assert preview.endswith("\n") or preview == result.content


def test_read_file_safe_reads_1000_lines_with_long_lines_in_one_call() -> None:
    """1000 行、含超长行的文件一次读完：不触发字符预算，无截断标记。"""
    from app.harness.execution.dispatch import READ_MAX_CHARS

    with tempfile.TemporaryDirectory() as root:
        lines = []
        for i in range(1000):
            if i % 20 == 19:
                lines.append(f"LONG_LINE_{i + 1}:" + "x" * 8000)
            else:
                lines.append(f"LINE_{i + 1:04d}: normal content")
        write_file_safe("big_mix.txt", "\n".join(lines), root)
        result = read_file_safe("big_mix.txt", root)
        assert result.is_complete is True
        assert result.next_offset is None
        assert result.lines_read == 1000
        assert result.content_truncated is False
        assert len(result.content) < READ_MAX_CHARS
        model_text = str(result.to_tool_data()["model_text"])
        assert "…[未读完]" not in model_text
        # 元数据头：读取范围 + 总行数 + 已读完，随正文注入模型。
        first_line = model_text.split("\n", 1)[0]
        assert "已读完" in first_line and "共 1000 行" in first_line
        assert "LONG_LINE_1000:" in model_text
        assert model_text.rstrip().endswith("x")


def test_clip_at_line_boundary_keeps_full_lines() -> None:
    """预览截断停在换行处，不切开当前行。"""
    from app.harness.execution.dispatch import clip_at_line_boundary

    text = "alpha\nbeta-is-long\ngamma\n"
    clipped, truncated = clip_at_line_boundary(text, 12)
    assert truncated is True
    assert clipped == "alpha\n"
    assert not clipped.endswith("beta")


def test_read_handler_accepts_next_offset_alias() -> None:
    """模型把上次 next_offset 填回参数时，按 offset 继续读，不重读首页。"""
    from app.harness.execution.registry import _read_handler

    with tempfile.TemporaryDirectory() as root:
        write_file_safe("page.txt", "one\ntwo\nthree\nfour", root)
        first = _read_handler({"path": "page.txt", "limit": 2}, root)
        assert first.content == "one\ntwo\n"
        second = _read_handler({"path": "page.txt", "next_offset": first.next_offset, "limit": 2}, root)
        assert second.content == "three\nfour"


def test_read_file_safe_large_file_pages_without_line_scan_timeout() -> None:
    """大文档只解码当前窗口：总量仍准确，且不会因逐行扫完全文而超时。"""
    with tempfile.TemporaryDirectory() as root:
        line = "文档行内容0123456789\n"
        total = 80_000
        with open(os.path.join(root, "huge.md"), "w", encoding="utf-8") as handle:
            handle.writelines(line for _ in range(total))
        started = time.perf_counter()
        first = read_file_safe("huge.md", root, limit=8)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0
        assert first.lines_read == 8
        assert first.total_lines == total
        assert first.total_chars == len(line) * total
        assert first.is_complete is False
        assert first.next_offset == 8
        assert first.content == line * 8
        second = read_file_safe("huge.md", root, offset=79_995, limit=20)
        assert second.lines_read == 5
        assert second.total_lines == total
        assert second.is_complete is True
        assert second.next_offset is None


def test_read_file_safe_counts_final_line_without_newline() -> None:
    """无行尾换行的最后一行仍计入 total_lines，且分页 next_offset 正确。"""
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "tail.txt"), "w", encoding="utf-8") as handle:
            handle.write("alpha\nbeta\ngamma")
        first = read_file_safe("tail.txt", root, limit=1)
        assert first.content == "alpha\n"
        assert first.total_lines == 3
        assert first.next_offset == 1
        last = read_file_safe("tail.txt", root, offset=2)
        assert last.content == "gamma"
        assert last.total_lines == 3
        assert last.is_complete is True


def test_read_result_hides_full_content_from_display_data(monkeypatch) -> None:
    """完整正文只给 Observation；ToolCard 数据仅包含受控预览窗口。"""
    from app.config import settings

    # 预览上限可配置（TOOL_PREVIEW_MAX_CHARS）；用小上限验证截断语义与
    # preview_limit_chars 的下发，默认值对齐 read 模型窗口。
    monkeypatch.setattr(settings, "tool_preview_max_chars", 100)
    with tempfile.TemporaryDirectory() as root:
        write_file_safe("secret.txt", "机密内容" * 200, root)
        result = read_file_safe("secret.txt", root)
        data = result.to_tool_data()
        display = data["display"]
        assert isinstance(display, dict)
        assert "model_text" in data
        assert "model_text" not in display
        assert len(display["read"]["preview"]) <= 100
        assert display["read"]["preview_truncated"] is True
        assert display["read"]["preview_limit_chars"] == 100


def test_task_plan_is_transient_and_never_creates_platform_task() -> None:
    """task 原生工具只生成本回合清单，不产生数据库/Worker 副作用。"""
    from app.harness.execution import build_task_plan

    result = build_task_plan(
        {
            "goal": "审查工具链路",
            "steps": [
                {"title": "读取注册表", "status": "completed"},
                {"title": "总结风险", "status": "in_progress"},
            ],
        }
    )
    data = result.to_tool_data()
    assert "不创建评测任务" in data["summary"]
    assert data["display"]["task"]["steps"][1]["status"] == "in_progress"
    assert "Task(" not in data["model_text"]


def test_web_search_requires_server_side_service_configuration(monkeypatch) -> None:
    """未配置 Firecrawl Key 时明确拒绝，禁止用占位文本伪造搜索成功。"""
    from app.config import settings
    from app.harness.execution import dispatch

    monkeypatch.setattr(settings, "firecrawl_api_key", "")
    with pytest.raises(AppError) as error:
        dispatch.web_search("ReAct 原理", timeout_s=1.0)
    assert error.value.code == ErrorCode.VALIDATION


def test_web_search_projects_safe_structured_results(monkeypatch) -> None:
    """真实搜索适配器只把受控结果交给模型与 ToolCard，不泄露服务端密钥。"""
    from app.config import settings
    from app.harness.execution import dispatch

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return b'{"data":[{"title":"LangGraph","url":"https://example.com/a","description":"agent graph"}]}'

    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **_kwargs: object) -> _FakeResponse:
        captured["request"] = request
        return _FakeResponse()

    monkeypatch.setattr(settings, "firecrawl_api_key", "private-key")
    monkeypatch.setattr(dispatch, "urlopen", fake_urlopen)
    result = dispatch.web_search("LangGraph", limit=1, timeout_s=1.0)
    data = result.to_tool_data()
    assert result.results[0]["title"] == "LangGraph"
    assert data["display"]["search"]["results"][0]["url"] == "https://example.com/a"
    assert "private-key" not in json.dumps(data, ensure_ascii=False)
    assert captured["request"] is not None


def test_web_fetch_rejects_internal_targets(monkeypatch) -> None:
    """SSRF 防护：web_fetch 拒绝回环/内网/保留地址（IP 字面量、域名与非标准写法）。

    ``urlopen`` 被替换为必然失败的桩：若 SSRF 校验漏拦任一 URL，urlopen 被调用
    即触发 AssertionError，保证校验确实在发起请求前生效。
    """
    from app.harness.execution import dispatch

    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("SSRF 校验未拦截，urlopen 不应被调用")

    monkeypatch.setattr(dispatch, "urlopen", fake_urlopen)
    blocked_urls = (
        "http://127.0.0.1:8000/api/health",
        "http://localhost:8000/api/health",
        "http://[::1]:8000/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://172.31.255.254/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        # 非标准 IP 写法（十进制/十六进制/省略段），解析后仍命中回环
        "http://2130706433/",
        "http://0x7f000001/",
        "http://127.1/",
        # IPv4 映射 IPv6
        "http://[::ffff:127.0.0.1]:8000/",
    )
    for url in blocked_urls:
        with pytest.raises(AppError) as error:
            dispatch.web_fetch(url, timeout_s=1.0)
        assert error.value.code in (ErrorCode.VALIDATION, ErrorCode.UPSTREAM), url


def test_web_fetch_allows_public_target(monkeypatch) -> None:
    """SSRF 防护不误伤公网地址。"""
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/html"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return self._body

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/"

    class _FakeOpener:
        def open(self, _request: object, timeout: float) -> _FakeResponse:
            assert timeout == 1.0
            return _FakeResponse(b"<html>public</html>")

    monkeypatch.setattr(dispatch, "build_opener", lambda *_a, **_k: _FakeOpener())
    # 公网 IP 字面量：无需 DNS，直接放行
    assert "public" in dispatch.web_fetch("http://93.184.216.34/", timeout_s=1.0).content
    # 与 HTTP 一样固定 DNS 响应，避免本机代理/离线解析改变本例的公网前提。
    monkeypatch.setattr(dispatch.socket, "getaddrinfo", lambda *_a, **_k: [
        (dispatch.socket.AF_INET, dispatch.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
    ])
    result = dispatch.web_fetch("http://example.com/", timeout_s=1.0)
    assert "public" in result.content


def test_web_fetch_content_budget_and_card_preview(monkeypatch) -> None:
    """web_fetch 正文预算与卡片预览（2026-08-28 调整）：

    - 旧 8000 字符正文上限把知乎专栏等长文截掉大半，放宽为专属
      ``WEB_FETCH_MAX_CHARS`` 预算，超限仍带 ``truncated`` 诚实标记；
    - 卡片预览不再固定 500 字符，与 read 同源对齐 ``preview_char_limit()``，
      并下发 ``preview_limit_chars`` 供前端提示文案使用。
    """
    from app.config import settings
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/plain"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return self._body

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/long"

    class _FakeOpener:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def open(self, _request: object, timeout: float) -> _FakeResponse:
            _ = timeout
            return _FakeResponse(self._body)

    # 1) 介于旧 8000 与新 60000 预算之间的长文不再被截半
    monkeypatch.setattr(
        dispatch, "build_opener", lambda *_a, **_k: _FakeOpener(b"x" * 20_000)
    )
    mid = dispatch.web_fetch("http://93.184.216.34/long", format="text", timeout_s=1.0)
    assert len(mid.content) == 20_000
    assert mid.truncated is False

    # 2) 超出 60000 预算仍受控截断，并带诚实标记
    monkeypatch.setattr(
        dispatch, "build_opener", lambda *_a, **_k: _FakeOpener(b"y" * 61_000)
    )
    over = dispatch.web_fetch("http://93.184.216.34/long", format="text", timeout_s=1.0)
    assert len(over.content) == dispatch.WEB_FETCH_MAX_CHARS
    assert over.truncated is True

    # 3) 卡片预览与 preview_char_limit() 同源，上限随数据下发
    monkeypatch.setattr(settings, "tool_preview_max_chars", 100)
    data = over.to_tool_data()
    web = data["display"]["web"]
    assert isinstance(web, dict)
    assert web["preview_limit_chars"] == 100
    assert web["preview_truncated"] is True
    assert len(str(web["preview"])) <= 100


def test_web_fetch_streams_direct_plain_text_before_completion(monkeypatch) -> None:
    """直接抓取纯文本时，已接收片段应在 HTTP 响应结束前通过安全回调发出。"""
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/plain"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self._offset = 0

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(self._body):
                return b""
            stop = len(self._body) if size < 0 else min(len(self._body), self._offset + size)
            chunk = self._body[self._offset:stop]
            self._offset = stop
            return chunk

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/stream.txt"

    class _FakeOpener:
        def open(self, _request: object, timeout: float) -> _FakeResponse:
            assert timeout == 1.0
            return _FakeResponse(("第一行\\n第二行\\n" * 1_000).encode("utf-8"))

    monkeypatch.setattr(dispatch, "build_opener", lambda *_a, **_k: _FakeOpener())
    chunks: list[tuple[str, str, int | None]] = []
    stages: list[tuple[str, str]] = []
    result = dispatch.web_fetch(
        "http://93.184.216.34/stream.txt",
        format="text",
        timeout_s=1.0,
        on_output=lambda channel, text, start_line: chunks.append((channel, text, start_line)),
        on_progress=lambda stage, message: stages.append((stage, message)),
    )

    assert result.content.startswith("第一行")
    assert len(chunks) >= 2
    assert all(channel == "document" and start_line is None for channel, _text, start_line in chunks)
    assert "".join(text for _channel, text, _start_line in chunks) == result.content
    assert [stage for stage, _message in stages] == ["downloading", "extracting"]


_ARTICLE_HTML = """<!DOCTYPE html>
<html><head><title>Agent设计模式详解 - 技术专栏</title></head>
<body>
<nav><a href="/home">首页</a><a href="/tags">标签</a></nav>
<article>
<h1>Agent设计模式详解</h1>
<p>Agent设计模式是智能化系统开发的核心要点。本系列文章将详细介绍九种常见的Agent设计模式，
帮助开发者掌握每种模式的原理和具体应用场景，先从最基础的ReAct模式开始讲起，
它是所有模式的理论基石，也是工程实践中使用频率最高的一种范式。</p>
<h2>1、ReAct 模式</h2>
<p>ReAct 模式的核心思想是<a href="https://example.com/react-paper">推理与行动交错进行</a>，
模型在思考之后立即执行工具调用，并根据观察结果调整下一步计划。
这种循环结构既保证了推理的深度，又保证了行动的准确性。</p>
<img src="https://picx.zhimg.com/v2-853507087d2befc30a742018816a7d5f_1440w.jpg" alt="ReAct架构图"/>
<h2>2、Plan-and-Solve 模式</h2>
<p>Plan-and-Solve 模式强调先制定完整计划再逐步执行。规划阶段模型会把目标拆解为有序的子步骤，
执行阶段按顺序完成每个子步骤并根据反馈动态修正，适合流程固定的批量评测任务。</p>
</article>
<footer>版权声明：本文为原创文章，转载请保留出处与作者信息。</footer>
</body></html>"""


def _install_fake_html_fetch(monkeypatch, body: bytes) -> None:
    """给 web_fetch 直抓路径装上返回固定 HTML 的假 opener（测试辅助）。"""
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/html"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return body

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/article"

    class _FakeOpener:
        def open(self, _request: object, timeout: float) -> _FakeResponse:
            _ = timeout
            return _FakeResponse()

    monkeypatch.setattr(dispatch, "build_opener", lambda *_a, **_k: _FakeOpener())


def test_web_fetch_trafilatura_markdown_extraction(monkeypatch) -> None:
    """直抓路径接入 trafilatura（2026-08-28）：正文级 Markdown 提取且格式诚实声明。"""
    from types import SimpleNamespace

    from app.harness.execution import dispatch

    captured: dict[str, object] = {}

    def _fake_extract(decoded: str, **kwargs: object) -> str:
        captured["kwargs"] = kwargs
        assert "<article>" in decoded
        return "# Agent设计模式详解\n\n正文含 [ReAct 模式](https://example.com/react-paper)。"

    monkeypatch.setattr(
        dispatch, "_load_trafilatura", lambda: SimpleNamespace(extract=_fake_extract)
    )
    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "markdown"
    assert "[ReAct 模式](https://example.com/react-paper)" in result.content
    # <title> 仍由内置提取器提供
    assert "Agent设计模式详解" in result.title
    kwargs = captured["kwargs"]
    assert kwargs.get("include_links") is True
    assert kwargs.get("favor_recall") is True


def test_web_fetch_falls_back_without_trafilatura(monkeypatch) -> None:
    """未安装 trafilatura 时降级回 _TextExtractor，格式诚实保持 text。"""
    from app.harness.execution import dispatch

    monkeypatch.setattr(dispatch, "_load_trafilatura", lambda: None)
    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "text"
    assert "Agent设计模式" in result.content
    assert "Agent设计模式详解" in result.title


def test_web_fetch_falls_back_when_trafilatura_raises(monkeypatch) -> None:
    """trafilatura 提取抛异常时不中断抓取，降级为内置提取器。"""
    from types import SimpleNamespace

    from app.harness.execution import dispatch

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(
        dispatch, "_load_trafilatura", lambda: SimpleNamespace(extract=_boom)
    )
    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "text"
    assert "Agent设计模式" in result.content


def test_web_fetch_real_trafilatura_integration(monkeypatch) -> None:
    """集成：真实 trafilatura 对文章式 HTML 输出结构化 Markdown。"""
    pytest.importorskip("trafilatura")
    from app.harness.execution import dispatch

    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "markdown"
    assert "# Agent设计模式详解" in result.content
    assert "](https://example.com/react-paper)" in result.content
    assert "![" in result.content
    # 导航/页脚噪声被剔除
    assert "首页" not in result.content
    assert "版权声明" not in result.content


class _RecordingHandler(BaseHTTPRequestHandler):
    """回环集成测试用 HTTP handler：记录请求路径、返回固定内容、不刷日志。"""

    requests: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).requests.append(self.path)
        body = b"integration-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture()
def loopback_server() -> str:
    """启动一个真实可达的回环 HTTP 服务器（127.0.0.1 随机端口），返回其 URL。

    用作集成测试的"内部可达目标"：若 SSRF 校验缺失，web_fetch 必然能抓到它。
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _RecordingHandler.requests = []
    yield f"http://127.0.0.1:{server.server_address[1]}/health"
    server.shutdown()
    thread.join(timeout=5)


def test_web_fetch_integration_blocks_reachable_loopback(loopback_server) -> None:
    """集成：SSRF 校验先于网络请求——回环服务真实可达也拦截，且服务端未收到请求。"""
    from app.harness.execution import dispatch

    with pytest.raises(AppError) as error:
        dispatch.web_fetch(loopback_server, timeout_s=3.0)
    assert error.value.code == ErrorCode.VALIDATION
    assert _RecordingHandler.requests == []


def test_web_fetch_integration_execute_path_observation(loopback_server) -> None:
    """集成：经 execute 分派路径，SSRF 拦截归一为 ok=False observation。"""
    registry = build_default_registry()
    observation = execute(
        ToolCall(name="web_fetch", arguments={"url": loopback_server}),
        timeout_s=5.0,
        permission=registry.get("web_fetch").permission,
        handler=registry.get("web_fetch").handler,
    )
    assert observation.ok is False
    assert observation.text == "操作失败（VALIDATION）"
    assert _RecordingHandler.requests == []


def test_web_fetch_integration_toolnode_event(loopback_server) -> None:
    """集成：经 ToolNode 全链路（门禁→绑定→分派→归一），产出 ok=False tool_result 事件。"""
    registry = build_default_registry()
    node = build_tool_node(registry)
    state: GraphState = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "web_fetch", "arguments": {"url": loopback_server}},
    }

    class _FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            return {"configurable": {}}.get(key, default)

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: _FakeConfig()
    try:
        out = asyncio.run(node(state))
    finally:
        toolnode_mod.get_config = original

    result = next(event for event in out["pending_events"] if event["kind"] == "tool_result")
    payload = result["payload"]
    assert payload["ok"] is False
    assert payload["error"] == "操作失败（VALIDATION）"
    assert payload["latency_ms"] >= 0
    assert _RecordingHandler.requests == []


def test_web_fetch_integration_reachable_when_guard_disabled(loopback_server, monkeypatch) -> None:
    """集成对照：绕过 SSRF 校验后同一回环服务可正常抓取，证明拦截来自校验本身而非环境。"""
    from app.harness.execution import dispatch

    monkeypatch.setattr(dispatch, "_reject_internal_target", lambda _host: None)
    result = dispatch.web_fetch(loopback_server, timeout_s=3.0)
    assert "integration-ok" in result.content
    assert _RecordingHandler.requests == ["/health"]


def test_execute_normalizes_exception_to_observation() -> None:
    """分派异常不裸抛：归一为 ok=False observation（X-A4）。"""
    def boom(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        raise RuntimeError("secret")

    observation = execute(
        ToolCall(name="t", arguments={"key": "k"}),
        timeout_s=1.0,
        permission="p",
        handler=boom,
    )
    assert observation.ok is False
    assert "secret" not in observation.text


def test_execute_calls_handler_and_returns_ok() -> None:
    """正常分派返回 ok=True observation。"""
    observation = execute(
        ToolCall(name="t", arguments={"key": "v"}),
        timeout_s=1.0,
        permission="p",
        handler=_handler_factory("t"),
    )
    assert observation.ok is True
    assert observation.text == "t:v"


def test_execute_rejects_without_handler() -> None:
    """无 handler（未注册）返回 ok=False，不抛、不泄露内部细节。"""
    observation = execute(
        ToolCall(name="nope", arguments={}),
        timeout_s=1.0,
        permission="p",
    )
    assert observation.ok is False
    assert observation.text == "操作失败（VALIDATION）"


def test_toolnode_timeout_and_frontend_event_payload() -> None:
    """ToolNode 超时后仍返回 API.md 规定的前端 ToolCard 字段。"""
    registry = ToolRegistry()

    def slow_handler(_arguments: dict, _sandbox_dir: str | None = None) -> str:
        time.sleep(0.05)
        return "不应在超时后展示"

    registry.register(
        ToolDef(
            name="slow",
            description="慢工具",
            parameters_schema={},
            permission="test.read",
            timeout_s=0.01,
            handler=slow_handler,
            transport="native",
            output_schema={},
        )
    )
    node = build_tool_node(registry)
    state: GraphState = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "slow", "arguments": {}},
    }

    class _FakeConfig:
        def get(self, key: str, default=None):
            return {"configurable": {}}.get(key, default)

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: _FakeConfig()
    try:
        out = asyncio.run(node(state))
    finally:
        toolnode_mod.get_config = original

    result = next(event for event in out["pending_events"] if event["kind"] == "tool_result")
    payload = result["payload"]
    assert payload["ok"] is False
    assert payload["error"] == "操作失败（TIMEOUT）"
    assert isinstance(payload["latency_ms"], int)
    assert payload["redacted"] is True
    assert payload["truncated"] is False


def test_assert_no_orm_leak_rejects_bound_instance() -> None:
    """EX-6：已绑定 Session 的 ORM 对象不得跨执行器边界传递。"""
    from app.models import User

    db = Session()
    try:
        user = User(id="u-session-guard", username="guard", password_hash="hash")
        db.add(user)
        with pytest.raises(AppError) as error:
            assert_no_orm_leak({"user": user})
        assert error.value.code == ErrorCode.INTERNAL
    finally:
        db.close()


def test_worker_bridge_constants() -> None:
    """长工具/任务类型常量与契约一致。"""
    assert LONG_TOOLS == {"benchmark.run", "testcase.generate", "rag.evaluate", "stress.run"}
    assert TASK_KINDS == {"benchmark", "testcase", "rag", "stress"}
