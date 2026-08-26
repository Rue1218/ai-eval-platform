"""自定义斜杠命令 CRUD（API.md §3.4 M2）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..harness.memory.slash_store import create_command, delete_command, list_commands
from ..models import User
from ..schemas import SlashCommandCreate

router = APIRouter(prefix="/api/slash-commands", tags=["slash-commands"])


@router.get("")
def list_slash_commands(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """列出当前用户的自定义命令（系统 15 条不在此接口）。"""
    return list_commands(db, user.id)


@router.post("", status_code=201)
def create_slash_command(
    body: SlashCommandCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """创建自定义命令；模板只预填输入框，不当 system。"""
    return create_command(db, user.id, body.model_dump())


@router.delete("/{command_id}")
def delete_slash_command(
    command_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除本人创建的命令。"""
    delete_command(db, user.id, command_id)
    return {"ok": True}
