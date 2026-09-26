"""当前成员主动保存、编辑和撤回个人长期记忆。"""

from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError, ErrorCode
from app.harness.memory import personal
from app.models import User
from app.schemas import ApiModel

router = APIRouter(prefix="/api/agent/memories", tags=["agent"])


class MemoryCreate(ApiModel):
    """用户手动输入的记忆；禁止客户端指定来源、ACL 或所属成员。"""

    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=2000)
    category: Literal["preference", "fact"] = "fact"
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_text(cls, value):
        """先去首尾空白，纯空白记忆不能绕过长度校验。"""
        return value.strip() if isinstance(value, str) else value


class MemoryUpdate(MemoryCreate):
    """编辑必须携带页面读取到的正整数版本，防止覆盖他端修改。"""

    version: int = Field(gt=0, strict=True)


class MemoryOut(ApiModel):
    """可管理记忆的公开字段；来源仅表示当前用户手动保存。"""

    id: str
    title: str
    content: str
    category: Literal["preference", "fact"]
    workspace_id: str | None
    workspace_name: str | None
    version: int
    source_id: str
    created_at: str
    updated_at: str


class MemoryList(ApiModel):
    """经过本人范围与安全过滤后的分页结果。"""

    items: list[MemoryOut]
    total: int


@contextmanager
def _database_guard(db: Session):
    """数据库失败不向全局异常日志传递可能包含记忆正文的 SQL 参数。"""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        raise AppError(ErrorCode.INTERNAL, "记忆操作失败，请重试") from None


@router.get("", response_model=MemoryList)
def list_memories(q: str = Query(default="", max_length=200),
                  workspace_id: str | None = Query(default=None, max_length=128),
                  limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """搜索本人记忆，工作区参数省略表示全部、空串表示全局。"""
    with _database_guard(db):
        return personal.list_personal_memories(db, user.id, q=q.strip(), workspace_id=workspace_id,
                                               limit=limit, offset=offset)


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(body: MemoryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """主动保存记忆及无正文审计；不会从对话自动提取。"""
    with _database_guard(db):
        result = personal.create_personal_memory(db, user.id, **body.model_dump())
        db.commit()
        return result


@router.put("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, body: MemoryUpdate,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """版本一致时替换记忆，不改变所属成员和手动来源标识。"""
    with _database_guard(db):
        result = personal.update_personal_memory(db, user.id, memory_id, **body.model_dump())
        db.commit()
        return result


@router.delete("/{memory_id}", status_code=204)
def revoke_memory(memory_id: str, version: int = Query(gt=0),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """撤回只阻止未来召回，不追溯改写已有会话历史。"""
    with _database_guard(db):
        personal.revoke_personal_memory(db, user.id, memory_id, version)
        db.commit()
    return Response(status_code=204)
