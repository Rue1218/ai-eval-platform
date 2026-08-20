"""MCP 工具中心路由（API V1.3 §3.6.1）。

V1.0 仅暴露内置受控短工具清单的只读视图；外部 MCP Server 的接入、
探活、解绑与动态发现均不在本期范围，浏览器侧对应按钮展示能力未启用。
``enabled`` 与 Agent Host 实际可执行的短工具同源，禁止把未落地工具标成已启用。
"""

from fastapi import APIRouter, Depends

from ..agent.defaults import (
    IMPLEMENTED_SHORT_TOOLS,
    MCP_TOOL_DESCRIPTIONS,
    MCP_TOOL_ORDER,
    TOOL_TITLES,
    WRITE_TOOLS,
)
from ..deps import get_current_user
from ..models import User
from ..schemas import McpToolOut

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def builtin_tools() -> list[McpToolOut]:
    """按冻结顺序生成内置短工具清单，enabled 与实现表一致。"""
    items: list[McpToolOut] = []
    for name in MCP_TOOL_ORDER:
        items.append(
            McpToolOut(
                name=name,
                desc=MCP_TOOL_DESCRIPTIONS.get(name, TOOL_TITLES.get(name, name)),
                permission="write" if name in WRITE_TOOLS else "read",
                enabled=name in IMPLEMENTED_SHORT_TOOLS,
            )
        )
    return items


@router.get("/tools", summary="内置 MCP 短工具清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """返回当前智能体环境受控的内置短工具及权限级别。"""
    items = builtin_tools()
    return {"items": [t.model_dump(mode="json") for t in items], "total": len(items)}
