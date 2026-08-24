"""Harness 执行层（M5）：工具注册表与统一执行入口。"""

from .binding import bind_attachments
from .dispatch import (
    BASH_BLOCKLIST,
    edit_file_safe,
    execute,
    read_file_safe,
    run_bash,
    web_fetch,
    web_search,
    write_file_safe,
)
from .registry import ToolDef, ToolRegistry, build_default_registry
from .toolnode import build_tool_node
from .worker_bridge import LONG_TOOLS, TASK_KINDS, enqueue_long_task
from .workspace import (
    ensure_session_workspace,
    get_workspace_root,
    session_workspace_dir,
)

__all__ = [
    "BASH_BLOCKLIST",
    "LONG_TOOLS",
    "TASK_KINDS",
    "ToolDef",
    "ToolRegistry",
    "bind_attachments",
    "build_default_registry",
    "build_tool_node",
    "edit_file_safe",
    "enqueue_long_task",
    "ensure_session_workspace",
    "execute",
    "get_workspace_root",
    "read_file_safe",
    "run_bash",
    "session_workspace_dir",
    "web_fetch",
    "web_search",
    "write_file_safe",
]
