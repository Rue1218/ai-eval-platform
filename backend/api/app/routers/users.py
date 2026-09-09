"""成员账号与审计查询接口。"""

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, Task, User
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
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按 API §1.1 统一分页约定列出成员账号（offset 默认 0，limit 默认 50）。"""
    query = db.query(User)
    total = query.count()
    rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [UserOut.model_validate(row).model_dump(mode="json") for row in rows], "total": total}


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
        # V1.83 起机制废除：忽略请求字段，开户一律不强制首次改密。
        must_change_password=False,
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


def _parse_bound(value: str | None, name: str, default: datetime | None) -> datetime | None:
    """解析 ISO 8601 时间边界，非法输入按 VALIDATION 拒绝并补 UTC 时区；缺省返回 default。"""
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AppError(ErrorCode.VALIDATION, f"{name} 不是合法的 ISO 8601 时间") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@router.get("/activity-summary")
def activity_summary(
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按 [from, to) 区间聚合成员活跃 KPI 与逐小时登录桶（API §3.3）。

    缺省区间为最近 24 小时；登录事件来自 auth 登录打点的审计日志；
    shared_reports 待 M2 报告分享域（share_links）落地后接入，当前如实返回 0。
    """
    to_bound = _parse_bound(to_ts, "to", datetime.now(UTC))
    from_bound = _parse_bound(from_ts, "from", to_bound - timedelta(hours=24))
    if from_bound >= to_bound:
        raise AppError(ErrorCode.VALIDATION, "from 必须早于 to")

    login_rows = (
        db.query(AuditLog.user_id, AuditLog.ts)
        .filter(
            AuditLog.action == "login",
            AuditLog.ts >= from_bound,
            AuditLog.ts < to_bound,
        )
        .all()
    )
    active_members = len({uid for uid, _ in login_rows if uid})

    # 逐小时登录桶：以区间起点对齐整点切分，桶键形如 2026-08-19T10:00
    buckets: dict[str, int] = {}
    cursor = from_bound.replace(minute=0, second=0, microsecond=0)
    while cursor < to_bound:
        buckets[cursor.strftime("%Y-%m-%dT%H:00")] = 0
        cursor += timedelta(hours=1)
    for _, ts in login_rows:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        key = ts.strftime("%Y-%m-%dT%H:00")
        if key in buckets:
            buckets[key] += 1

    new_members = (
        db.query(func.count(User.id))
        .filter(User.created_at >= from_bound, User.created_at < to_bound)
        .scalar()
        or 0
    )
    total_tasks = (
        db.query(func.count(Task.id))
        .filter(Task.created_at >= from_bound, Task.created_at < to_bound)
        .scalar()
        or 0
    )
    login_count = len(login_rows)
    disabled = db.query(User).filter(User.disabled.is_(True)).count()
    total = db.query(User).count()

    return {
        "range": {"from": from_bound.isoformat(), "to": to_bound.isoformat()},
        "kpis": {
            "active_members": active_members,
            "total_tasks": total_tasks,
            "new_members": new_members,
            # M2 前无 share_links 表：分享数为契约占位 0，不做假聚合
            "shared_reports": 0,
            "login_count": login_count,
            "disabled_members": disabled,
            "total_members": total,
        },
        "login_buckets": [{"h": key, "count": count} for key, count in buckets.items()],
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
