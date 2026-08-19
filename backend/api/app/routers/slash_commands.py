"""自定义斜杠命令 M1 桩（API.md §3.4：未启用返回 VALIDATION 400）。"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import User

router = APIRouter(prefix="/api/slash-commands", tags=["slash-commands"])

_DISABLED = "自定义命令未启用"


@router.get("")
def list_slash_commands(user: User = Depends(get_current_user)):
    """M1 桩：禁止 200 空列表冒充已启用。"""
    raise AppError(ErrorCode.VALIDATION, _DISABLED)


@router.post("", status_code=201)
def create_slash_command(user: User = Depends(get_current_user)):
    """M1 桩：完整 CRUD 在 AGT-M2-04。"""
    raise AppError(ErrorCode.VALIDATION, _DISABLED)


@router.delete("/{command_id}")
def delete_slash_command(command_id: str, user: User = Depends(get_current_user)):
    """M1 桩：完整 CRUD 在 AGT-M2-04。"""
    _ = command_id
    raise AppError(ErrorCode.VALIDATION, _DISABLED)
