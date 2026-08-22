"""MCP 工具中心占位；新 Agent 工具模型确定前不暴露旧注册表。"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools", summary="MCP 工具注册清单（只读）")
def list_tools(user: User = Depends(get_current_user)):
    """旧工具注册表已移除；新工具契约确定前返回空清单。"""
    _ = user
    return {"items": [], "total": 0}
