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
    BASH_BLOCKLIST,
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
        "write",
        "edit",
        "web_search",
        "web_fetch",
        "bash",
        "task",
        "task.create",
        "task.status",
        "task.cancel",
    }


def test_tool_schema_validation_rejects_invalid_and_extra_arguments() -> None:
    """ToolNode 前的 schema 校验拒绝类型错误、缺字段和未声明参数。"""
    read_schema = build_default_registry().get("read").parameters_schema
    assert validate_tool_arguments(read_schema, {"path": 1}) == "参数 path 类型无效，应为 string"
    assert validate_tool_arguments(read_schema, {"offset": 0}) == "缺少必填参数：path"
    assert validate_tool_arguments(read_schema, {"path": "a.txt", "unsafe": True}) == "包含未允许的参数：unsafe"


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


def test_bash_blocklist_rejects_dangerous_commands() -> None:
    """X-A7：bash 黑名单拒绝 rm/sudo/网络命令。"""
    for command in ("rm -rf /", "sudo whoami", "curl http://x", "wget http://x"):
        with pytest.raises(AppError) as error:
            run_bash(command, sandbox_dir=".", timeout_s=1.0)
        assert error.value.code == ErrorCode.VALIDATION
    assert "rm" in BASH_BLOCKLIST


def test_run_bash_delegates_to_sandbox(monkeypatch) -> None:
    """EX-6：bash 执行走 bwrap 沙箱内核，而非裸 subprocess。"""
    import app.harness.execution.dispatch as dispatch

    captured: dict[str, object] = {}

    def fake_run_sandboxed(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["sandbox_dir"] = kwargs["sandbox_dir"]
        captured["timeout_s"] = kwargs["timeout_s"]
        return "沙箱输出"

    monkeypatch.setattr(dispatch, "run_sandboxed", fake_run_sandboxed)
    result = run_bash("echo hi", sandbox_dir="/tmp/ws", timeout_s=15.0)
    assert result == "沙箱输出"
    assert captured["cmd"] == "echo hi"
    assert captured["sandbox_dir"] == "/tmp/ws"
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


def test_read_file_safe_stops_on_character_budget_at_line_boundary() -> None:
    """字符预算触发时不截断半行，next_offset 与实际结束行一致。"""
    with tempfile.TemporaryDirectory() as root:
        write_file_safe("huge.txt", "\n".join("y" * 100 for _ in range(2000)), root)
        result = read_file_safe("huge.txt", root)
        assert result.lines_read < 2000
        assert result.total_lines == 2000
        assert result.end_line == result.lines_read
        assert result.next_offset == result.lines_read
        assert result.content.endswith("\n")
        assert result.content_truncated is True
        model_text = str(result.to_tool_data()["model_text"])
        assert len(model_text) <= 8000
        display = result.to_tool_data()["display"]["read"]
        preview = str(display["preview"])
        assert preview.endswith("\n") or preview == result.content


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


def test_read_result_hides_full_content_from_display_data() -> None:
    """完整正文只给 Observation；ToolCard 数据仅包含受控预览。"""
    with tempfile.TemporaryDirectory() as root:
        write_file_safe("secret.txt", "机密内容" * 200, root)
        result = read_file_safe("secret.txt", root)
        data = result.to_tool_data()
        display = data["display"]
        assert isinstance(display, dict)
        assert "model_text" in data
        assert "model_text" not in display
        assert len(display["read"]["preview"]) <= 4000


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
    # 公网域名：SSRF 校验不应以 VALIDATION 拦截（无 DNS 环境的解析失败不算拦截）
    try:
        result = dispatch.web_fetch("http://example.com/", timeout_s=1.0)
        assert "public" in result.content
    except AppError as error:
        assert error.value.code != ErrorCode.VALIDATION


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
