"""跨会话下单偏好（API.md §3.4）：只读 GET，写入仅发生在确认入队后。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..harness.memory import public_prefs
from ..models import User

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/prefs", summary="读取当前成员的跨会话下单偏好")
def get_agent_prefs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """返回上次成功入队的下单偏好；无记录时各字段为 null。"""
    return public_prefs(db, user.id)
