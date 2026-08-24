"""M5 执行层单测（X-A4/X-A7/EX-5 等）；不依赖 DB。"""

import json
import tempfile

import pytest

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall
from app.harness.execution import (
    BASH_BLOCKLIST,
    ToolDef,
    ToolRegistry,
    build_default_registry,
    edit_file_safe,
    execute,
    read_file_safe,
    run_bash,
    write_file_safe,
)
from app.harness.execution.worker_bridge import LONG_TOOLS, TASK_KINDS


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


def test_default_registry_excludes_bash() -> None:
    """阶段 2 不开放通用 bash：默认注册表不含 bash。"""
    registry = build_default_registry()
    assert registry.is_registered("bash") is False
    names = {definition["name"] for definition in registry.all_defs()}
    assert names == {"read", "write", "edit", "web_search", "web_fetch"}


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


def test_worker_bridge_constants() -> None:
    """长工具/任务类型常量与契约一致。"""
    assert LONG_TOOLS == {"benchmark.run", "testcase.generate", "rag.evaluate", "stress.run"}
    assert TASK_KINDS == {"benchmark", "testcase", "rag", "stress"}
