"""会话工作区单测（M5 会话级沙箱目录）；不依赖 DB。"""

import os

import pytest

from app.errors import AppError, ErrorCode
from app.harness.execution import (
    ToolDef,
    ToolRegistry,
    build_tool_node,
    ensure_session_workspace,
    session_workspace_dir,
)
from app.harness.execution.registry import _read_handler, _write_handler
from app.harness.execution.workspace import get_workspace_root

SID = "834a68f1-a4fd-4261-8677-6f51830c895d"
SID2 = "ef459f86-112c-4b13-9b0f-cab7f26f7a05"


@pytest.fixture()
def tmp_root(monkeypatch, tmp_path):
    """把工作区根指向临时目录。"""
    root = tmp_path / "workspaces"
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(root))
    return root


def test_ensure_creates_session_dir(tmp_root) -> None:
    """会话工作区创建：{root}/{session_id} 存在且独立。"""
    directory = ensure_session_workspace(SID)
    assert directory == str(tmp_root / SID)
    assert os.path.isdir(directory)


def test_two_sessions_isolated_dirs(tmp_root) -> None:
    """不同会话工作区互相隔离（目录不同）。"""
    d1 = ensure_session_workspace(SID)
    d2 = ensure_session_workspace(SID2)
    assert d1 != d2
    assert os.path.commonpath([d1, d2]) == str(tmp_root)


def test_invalid_session_id_rejected(tmp_root) -> None:
    """非法会话标识拒绝（路径穿越/空/超长/非安全字符）。"""
    for bad in ("", "../evil", "a/b", "s-1", "x" * 65, "会话"):
        with pytest.raises(AppError) as error:
            session_workspace_dir(bad)
        assert error.value.code == ErrorCode.VALIDATION


def test_workspace_root_fallback() -> None:
    """根目录解析：env 优先，容器 /data 回退，本地 data/workspaces。"""
    assert get_workspace_root()


def test_sandbox_injected_via_configurable(tmp_root) -> None:
    """toolnode 集成：configurable['sandbox']['dir'] 生效且防目录穿越。"""
    from app.harness.memory import GraphState

    registry = ToolRegistry()
    registry.register(
        ToolDef(
            name="read",
            description="read",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            permission="sandbox.read",
            timeout_s=10.0,
            handler=_read_handler,
            transport="native",
        )
    )
    registry.register(
        ToolDef(
            name="write",
            description="write",
            parameters_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            permission="sandbox.write",
            timeout_s=10.0,
            handler=_write_handler,
            transport="native",
        )
    )
    node = build_tool_node(registry)
    workspace = ensure_session_workspace(SID)

    state: GraphState = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {
            "name": "write",
            "arguments": {"path": "hello.txt", "content": "内容"},
        },
    }
    out = _run_node(node, state, {"sandbox": {"dir": workspace}})
    events = [e for e in out["pending_events"] if e["kind"] == "tool_result"]
    assert events and events[0]["payload"]["ok"] is True
    assert os.path.isfile(os.path.join(workspace, "hello.txt"))

    # read 的完整正文仅供下一模型回合使用；持久化 ToolCard 事件只保留受控预览。
    state_read: GraphState = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "read", "arguments": {"path": "hello.txt"}},
    }
    out_read = _run_node(node, state_read, {"sandbox": {"dir": workspace}})
    read_event = next(e for e in out_read["pending_events"] if e["kind"] == "tool_result")
    read_data = read_event["payload"]["data"]
    assert "model_text" not in read_data
    assert read_data["read"]["preview"] == "内容"
    assert read_data["read"]["total_lines"] == 1

    # 跨工作区读取被拒（会话隔离 + 防目录穿越）
    state2: GraphState = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "read", "arguments": {"path": "../../other/hello.txt"}},
    }
    out2 = _run_node(node, state2, {"sandbox": {"dir": workspace}})
    ev2 = [e for e in out2["pending_events"] if e["kind"] == "tool_result"]
    assert ev2 and ev2[0]["payload"]["ok"] is False


def _run_node(node, state: dict, configurable: dict) -> dict:
    """在 mock configurable 下执行 tool_node（toolnode 经 get_config 读取；节点为 async）。"""
    import asyncio

    import app.harness.execution.toolnode as toolnode_mod

    class _FakeConfig:
        def __init__(self, value: dict) -> None:
            self._value = value

        def get(self, _key: str, default=None):
            return self._value.get(_key, default)

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: _FakeConfig({"configurable": configurable})
    try:
        return asyncio.run(node(state))
    finally:
        toolnode_mod.get_config = original
