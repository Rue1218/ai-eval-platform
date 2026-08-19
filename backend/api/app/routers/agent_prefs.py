"""跨会话下单偏好只读接口（API.md §3.4 / 开发说明书 §16.5）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..agent.prefs import load_prefs
from ..db import get_db
from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/prefs", summary="读取当前成员的跨会话下单偏好")
def get_agent_prefs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """只读；无 PUT。写入仅发生在 confirm_ack 成功入队之后。"""
    return load_prefs(db, user.id)
