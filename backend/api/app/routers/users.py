"""成员账号与审计查询接口。"""

import re

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, User
from ..schemas import ResetPasswordRequest, UserCreate, UserOut, UserStatusUpdate, UserUpdate
from ..security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def _validate_password(password: str) -> None:
    """执行 PRD 规定的至少八位且包含字母和数字的密码校验。"""
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AppError(ErrorCode.VALIDATION, "密码至少 8 位且包含字母和数字")


def _client_ip(request: Request) -> str | None:
    """提取本次请求的直连地址，供安全审计使用。"""
    return request.client.host if request.client else None


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出成员账号，统一返回分页外层。"""
    rows = db.query(User).order_by(User.created_at.desc()).all()
    return {"items": [UserOut.model_validate(row).model_dump(mode="json") for row in rows], "total": len(rows)}


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建同权成员账号，并记录不含密码的审计事件。"""
    _validate_password(body.password)
    member = User(
        username=body.username.strip(),
        display_name=body.display_name.strip() if body.display_name else None,
        email=body.email.strip().lower() if body.email else None,
        password_hash=hash_password(body.password),
        role="member",
        must_change_password=body.must_change_password,
    )
    db.add(member)
    db.add(
        AuditLog(
            user_id=user.id,
            action="user_create",
            target_type="user",
            target_id=member.id,
            detail={"username": member.username},
            ip=_client_ip(request),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(ErrorCode.VALIDATION, "用户名或邮箱已存在") from None
    db.refresh(member)
    return member


@router.get("/activity-summary")
def activity_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回成员页所需的真实基础 KPI，详细区间聚合留给后续统计批次。"""
    total = db.query(User).count()
    disabled = db.query(User).filter(User.disabled.is_(True)).count()
    login_count = db.query(AuditLog).filter(AuditLog.action == "login").count()
    return {
        "kpis": {
            "active_members": total - disabled,
            "new_members": total,
            "login_count": login_count,
            "disabled_members": disabled,
        },
        "login_buckets": [],
    }


@router.get("/{user_id}/audit-logs")
def user_audit_logs(
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取指定成员作为行为人的近期审计记录。"""
    if not db.query(User).filter(User.id == user_id).first():
        raise AppError(ErrorCode.NOT_FOUND, "成员不存在")
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user_id)
        .order_by(AuditLog.ts.desc())
        .limit(100)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "at": row.ts,
                "actor_id": row.user_id,
                "action": row.action,
                "target": {"type": row.target_type, "id": row.target_id},
                "detail": row.detail,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新成员展示资料，不提供角色修改入口。"""
    member = db.query(User).filter(User.id == user_id).first()
    if not member:
        raise AppError(ErrorCode.NOT_FOUND, "成员不存在")
    if body.display_name is not None:
        member.display_name = body.display_name.strip() or None
    if body.email is not None:
        member.email = body.email.strip().lower() or None
    db.add(
        AuditLog(
            user_id=user.id,
            action="user_update",
            target_type="user",
            target_id=member.id,
            detail={},
            ip=_client_ip(request),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(ErrorCode.VALIDATION, "邮箱已存在") from None
    db.refresh(member)
    return member


@router.put("/{user_id}/status", response_model=UserOut)
def update_user_status(
    user_id: str,
    body: UserStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启停成员，确保系统始终保留至少一个正常账号。"""
    member = db.query(User).filter(User.id == user_id).first()
    if not member:
        raise AppError(ErrorCode.NOT_FOUND, "成员不存在")
    if body.disabled and not member.disabled:
        active_count = db.query(User).filter(User.disabled.is_(False)).count()
        if active_count <= 1:
            raise AppError(ErrorCode.VALIDATION, "不可停用系统中最后一名正常账号")
        member.auth_version += 1
    member.disabled = body.disabled
    db.add(
        AuditLog(
            user_id=user.id,
            action="user_status_change",
            target_type="user",
            target_id=member.id,
            detail={"disabled": body.disabled},
            ip=_client_ip(request),
        )
    )
    db.commit()
    db.refresh(member)
    return member


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重置成员密码并失效该成员所有既有浏览器会话。"""
    _validate_password(body.password)
    member = db.query(User).filter(User.id == user_id).first()
    if not member:
        raise AppError(ErrorCode.NOT_FOUND, "成员不存在")
    member.password_hash = hash_password(body.password)
    member.must_change_password = True
    member.auth_version += 1
    db.add(
        AuditLog(
            user_id=user.id,
            action="password_reset",
            target_type="user",
            target_id=member.id,
            detail={},
            ip=_client_ip(request),
        )
    )
    db.commit()
    return {"ok": True}
