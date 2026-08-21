"""MCP 工具中心路由（API V1.3 §3.6.1）。

V1.0 仅暴露内置受控短工具清单的只读视图；外部 MCP Server 的接入、
探活、解绑与动态发现均不在本期范围，浏览器侧对应按钮展示能力未启用。
"""

from fastapi import APIRouter, Depends

from ..agent.mcp_registry import REGISTERED_TOOLS
from ..deps import get_current_user
from ..models import User
from ..schemas import McpToolOut

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# 路由只负责转换响应模型；能力描述统一来自 Agent 注册表。
BUILTIN_TOOLS: list[McpToolOut] = [
    McpToolOut(name=tool.name, desc=tool.description, permission=tool.permission, enabled=True)
    for tool in REGISTERED_TOOLS
]

MCP_TOOL_REGISTRY: list[McpToolOut] = BUILTIN_TOOLS


@router.get("/tools", summary="MCP 工具注册清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """返回当前 Agent Host 已挂载的内置短工具及权限级别。"""
    return {"items": [t.model_dump(mode="json") for t in MCP_TOOL_REGISTRY], "total": len(MCP_TOOL_REGISTRY)}
