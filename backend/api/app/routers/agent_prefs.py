"""Agent 偏好兼容占位；新 Agent 范式确定前不读取旧存储。"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import User

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/prefs", summary="读取当前成员的跨会话下单偏好")
def get_agent_prefs(user: User = Depends(get_current_user)):
    """旧偏好模型已移除，等待新 Agent 设计。"""
    _ = user
    raise AppError(ErrorCode.VALIDATION, "Agent 偏好能力正在重建设计")
