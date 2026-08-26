"""跨会话下单偏好（API.md §3.4）与 Agent 流式度量（§3.4.1）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..harness.execution.stream_metrics import get_default_stream_metrics
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


@router.get("/metrics", summary="Agent 交错流与 ToolBatch 度量（只读）")
def get_agent_metrics(user: User = Depends(get_current_user)) -> dict:
    """进程内快照：首 delta / ToolCall 解析延迟、批次并发、取消与不完整流比例。

    不含正文、工具参数、Observation 或凭据。并行脚踢为进程内瞬态，不改历史事件。
    """
    _ = user
    return get_default_stream_metrics().snapshot()
