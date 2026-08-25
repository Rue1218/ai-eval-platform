"""MCP 工具中心（只读）：展示平台 allowlist 内部短工具目录。

对应 API.md §3.6.1：只读展示内部 MCP Host 目录（catalog），不展示任何
Server 连接命令、环境变量、工作目录或凭据，也不暴露内部 handler 细节。
"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..harness.execution import ToolCatalog, build_default_registry
from ..harness.execution.mcp import get_default_metrics
from ..models import User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_catalog: ToolCatalog | None = None


def _get_default_catalog() -> ToolCatalog:
    """模块级惰性目录：默认注册表的内部 MCP 目录（只读，进程内缓存）。"""
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


@router.get("/tools", summary="MCP 工具注册清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """平台 allowlist 内部短工具目录（只读）。"""
    _ = user
    items = [_project(descriptor) for descriptor in _get_default_catalog().all_descriptors()]
    return {"items": items, "total": len(items)}


@router.get("/metrics", summary="MCP 工具度量与熔断状态（只读）")
def tool_metrics(user: User = Depends(get_current_user)):
    """内部 MCP Host 调用度量与服务器熔断状态（P4-2，进程内快照）。

    按 ``tool_id`` 的调用计数/耗时与按 ``server_id`` 的熔断状态，只读展示，
    不含任何请求参数、工具结果原文或凭据。
    """
    _ = user
    return get_default_metrics().snapshot()
