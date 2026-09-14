"""路由层共享小工具：客户端 IP、审计写入与目录校验的唯一实现。

收敛前 ``_request_ip``/``_client_ip`` 在 7 个 router 内各自重复定义，
目录校验（cases/datasets）与审计写入（dataset_catalog/user_workspaces）
各存两份；本模块为上述工具的单一事实源。
"""

from typing import Any, TypeVar

from fastapi import Request
from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from ..models import AuditLog, User

FolderT = TypeVar("FolderT")


def client_ip(request: Request) -> str | None:
    """提取本次请求的直连地址，供安全审计使用。"""
    return request.client.host if request.client else None


def write_audit(
    db: Session,
    request: Request,
    user: User,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """写入不含凭据、上游正文或制品内容的通用审计记录（调用方负责 commit）。"""
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
            ip=client_ip(request),
        )
    )


def get_folder_or_404(db: Session, model: type[FolderT], folder_id: str) -> FolderT:
    """读取目录或抛出 NOT_FOUND。"""
    folder = db.query(model).filter(model.id == folder_id).first()
    if not folder:
        raise AppError(ErrorCode.NOT_FOUND, "目录不存在")
    return folder


def assert_folder_exists(db: Session, model: type[FolderT], folder_id: str) -> None:
    """校验挂载目标目录存在，不存在按入参错误 VALIDATION 处理。"""
    if not db.query(model).filter(model.id == folder_id).first():
        raise AppError(ErrorCode.VALIDATION, "目标目录不存在")
