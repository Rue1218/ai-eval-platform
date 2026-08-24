"""M5 执行层单测（X-A4/X-A7/EX-5 等）；不依赖 DB。"""

import asyncio
import json
import tempfile
import time

import pytest
from sqlalchemy.orm import Session

import app.harness.execution.toolnode as toolnode_mod
from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall
from app.harness.execution import (
    BASH_BLOCKLIST,
    ToolDef,
    ToolRegistry,
    build_default_registry,
    build_tool_node,
    edit_file_safe,
    execute,
    read_file_safe,
    run_bash,
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
    names = {definition["name"] for definition in registry.all_defs()}
    assert names == {"read", "write", "edit", "web_search", "web_fetch", "bash"}


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
        assert read_file_safe("a.txt", root) == "hello"
        edit_file_safe("a.txt", "hello", "hello world", root)
        assert read_file_safe("a.txt", root) == "hello world"
        with pytest.raises(AppError) as error:
            edit_file_safe("a.txt", "不存在", "x", root)
        assert error.value.code == ErrorCode.VALIDATION
        with pytest.raises(AppError):
            write_file_safe("a.txt", "x", root)


def test_read_file_safe_supports_offset_and_limit() -> None:
    """read 工具 offset/limit 分段读取长文本，未读完带截断标记。"""
    with tempfile.TemporaryDirectory() as root:
        write_file_safe("long.txt", "0123456789", root)
        assert read_file_safe("long.txt", root) == "0123456789"
        assert read_file_safe("long.txt", root, offset=4) == "456789"
        assert read_file_safe("long.txt", root, offset=100) == ""
        # 未读完：内容 + 截断标记，标记含下一段 offset 提示
        first = read_file_safe("long.txt", root, limit=3)
        assert first.startswith("012")
        assert "offset=3" in first
        second = read_file_safe("long.txt", root, offset=2, limit=3)
        assert second.startswith("234")
        assert "offset=5" in second
        # 恰好读到末尾：无标记
        tail = read_file_safe("long.txt", root, offset=7)
        assert tail == "789"


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
