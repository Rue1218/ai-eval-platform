"""MCP 扩展工具中心（只读）。

对应 API.md §3.6.1：只读展示显式 ``transport=mcp`` 的评测/RAG 扩展目录，
不展示任何 Server 连接命令、环境变量、工作目录或凭据，也不暴露 handler
细节。read/write/edit/bash/web_search/web_fetch/task 属于原生基础工具，绝不
出现在此接口。
"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..harness.execution import ToolCatalog, build_default_registry
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


@router.get("/tools", summary="MCP 工具注册清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """平台 allowlist 的 MCP 扩展目录（只读；无扩展时返回真实空清单）。"""
    _ = user
    items = [_project(descriptor) for descriptor in _get_default_catalog().all_descriptors()]
    return {"items": items, "total": len(items)}
