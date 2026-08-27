"""MCP 扩展工具中心（只读）。

对应 API.md §3.6.1：只读展示显式 ``transport=mcp`` 的评测/RAG 扩展目录，
不展示任何 Server 连接命令、环境变量、工作目录或凭据，也不暴露 handler
细节。read/write/edit/bash/web_search/web_fetch 与对话拆解 task 属于原生基础
工具；评测任务桥 task.create/status/cancel 属于 platform.tasks MCP 扩展。
"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..harness.execution import ToolCatalog, build_default_registry
from ..harness.execution.mcp import get_default_metrics
from ..models import User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_catalog: ToolCatalog | None = None


def _get_default_catalog() -> ToolCatalog:
    """模块级惰性目录：默认注册表的 MCP 扩展目录（只读，进程内缓存）。"""
    global _catalog
    if _catalog is None:
        _catalog = ToolCatalog.build(build_default_registry())
    return _catalog


def _project(item: object) -> dict[str, object]:
    """把 ToolDescriptor 投影为 API.md §3.6.1 契约（不含命令/凭据）。"""
    tool_id = item.tool_id
    risk = item.risk_level
    return {
        "name": tool_id,
        "desc": item.description,
        "permission": "read" if risk in ("read", "network") else "write",
        "enabled": True,
        "source": "builtin",
        "tool_id": tool_id,
        "server_id": item.server_id,
        "short_name": item.name,
        "display_name": item.display_name,
        "risk_level": risk,
        "execution_mode": item.execution_mode,
        "timeout_s": item.timeout_s,
        "requires_confirmation": item.requires_confirmation,
        "supports_streaming": item.supports_streaming,
    }


def _project_native(def_: object) -> dict[str, object]:
    """把原生 ToolDef 投影为前端展示用契约（transport=native，不含 handler）。"""
    risk = def_.risk_level
    return {
        "name": def_.name,
        "desc": def_.description,
        "permission": "read" if risk in ("read", "network") else "write",
        "enabled": True,
        "source": "builtin",
        "tool_id": def_.name,
        "server_id": "platform.native",
        "short_name": def_.name,
        "display_name": def_.display_name or def_.name,
        "risk_level": risk,
        "execution_mode": def_.execution_mode,
        "timeout_s": float(def_.timeout_s),
        "requires_confirmation": def_.requires_confirmation,
        "supports_streaming": def_.supports_streaming,
        "transport": "native",
    }


@router.get("/tools", summary="MCP 工具注册清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """平台 allowlist 的 MCP 扩展目录（只读；无扩展时返回真实空清单）。"""
    _ = user
    items = [_project(descriptor) for descriptor in _get_default_catalog().all_descriptors()]
    return {"items": items, "total": len(items)}


@router.get("/all-tools", summary="全量工具清单（原生 ToolCall + MCP 扩展，只读）")
def list_all_tools(user: User = Depends(get_current_user)):
    """返回平台所有已注册工具（含 transport=native 与 transport=mcp），前端分组展示用。

    - ``transport=native``：原生基础工具（read/write/edit/bash/web_search/web_fetch/task），
      由 NativeToolExecutor 直连 handler，不经外部 MCP 协议。
    - ``transport=mcp``：内部 MCP 扩展工具（platform.tasks.task.create/status/cancel），
      由 MCPClientManager 通过受控目录调用，对应平台评测任务队列。
    不含 handler、凭据、环境变量等内部实现细节。
    """
    _ = user
    registry = build_default_registry()
    native_items = [
        {**_project_native(def_), "transport": "native"}
        for def_ in registry.iter_defs(transport="native")
    ]
    mcp_items = [
        {**_project(descriptor), "transport": "mcp"}
        for descriptor in _get_default_catalog().all_descriptors()
    ]
    items = native_items + mcp_items
    return {"items": items, "total": len(items)}


@router.get("/metrics", summary="MCP 工具度量与熔断状态（只读）")
def tool_metrics(user: User = Depends(get_current_user)):
    """内部 MCP Host 调用度量与服务器熔断状态（P4-2，进程内快照）。

    按 ``tool_id`` 的调用计数/耗时与按 ``server_id`` 的熔断状态，只读展示，
    不含任何请求参数、工具结果原文或凭据。
    """
    _ = user
    return get_default_metrics().snapshot()
