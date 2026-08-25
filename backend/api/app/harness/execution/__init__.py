"""Harness 执行层（M5）：工具注册表与统一执行入口。"""

from .binding import bind_attachments
from .dispatch import (
    BASH_BLOCKLIST,
    ReadResult,
    edit_file_safe,
    execute,
    read_file_safe,
    run_bash,
    web_fetch,
    web_search,
    write_file_safe,
)

# 内部 MCP Host（阶段 D，P3）：依赖 dispatch/registry，须在其之后导入。
from .mcp import InProcessProvider, MCPClientManager, ToolCatalog, ToolExecutionContext
from .native_results import NativeToolResultStore, runtime_thread_id
from .registry import (
    ToolDef,
    ToolRegistry,
    build_default_registry,
    required_parameter_names,
    validate_tool_arguments,
    validate_tool_schema,
)
from .session_guard import assert_no_orm_leak, with_managed_session
from .toolnode import build_tool_node
from .worker_bridge import LONG_TOOLS, TASK_KINDS, enqueue_long_task
from .workspace import (
    ensure_session_workspace,
    get_workspace_root,
    session_workspace_dir,
)

__all__ = [
    "BASH_BLOCKLIST",
    "InProcessProvider",
    "LONG_TOOLS",
    "MCPClientManager",
    "NativeToolResultStore",
    "ReadResult",
    "TASK_KINDS",
    "ToolCatalog",
    "ToolDef",
    "ToolExecutionContext",
    "ToolRegistry",
    "bind_attachments",
    "build_default_registry",
    "required_parameter_names",
    "build_tool_node",
    "edit_file_safe",
    "enqueue_long_task",
    "ensure_session_workspace",
    "execute",
    "get_workspace_root",
    "read_file_safe",
    "run_bash",
    "runtime_thread_id",
    "assert_no_orm_leak",
    "session_workspace_dir",
    "with_managed_session",
    "web_fetch",
    "web_search",
    "validate_tool_arguments",
    "validate_tool_schema",
    "write_file_safe",
]
