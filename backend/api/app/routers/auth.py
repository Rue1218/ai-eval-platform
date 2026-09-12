"""Cookie 鉴权、改密和 WebSocket 短票接口。"""

import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, User
from ..schemas import ChangePasswordRequest, LoginRequest, UserOut
from ..security import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_WS,
    create_token,
    hash_password,
    verify_password,
)
from ._common import client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE_NAME = "aieval_session"


def _validate_password(password: str) -> None:
    """执行密码长度、字母和数字组成的统一校验。"""
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AppError(ErrorCode.VALIDATION, "密码至少 8 位且包含字母和数字")


def _set_access_cookie(response: Response, user: User) -> None:
    """签发 12 小时 HttpOnly 登录 Cookie，浏览器脚本无法读取其内容。"""
    token = create_token(
        user.id,
        user.auth_version,
        TOKEN_TYPE_ACCESS,
        settings.access_token_expire_minutes,
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """验证账号后写入登录审计，并返回受 Cookie 保护的成员信息。"""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or user.disabled or not verify_password(body.password, user.password_hash):
        db.add(
            AuditLog(
                action="login_failed",
                detail={"username": body.username},
                ip=client_ip(request),
            )
        )
        db.commit()
        raise AppError(ErrorCode.UNAUTHORIZED, "用户名或密码错误", status_code=401)

    user.last_login_at = datetime.now(UTC)
    user.last_login_ip = client_ip(request)
    db.add(
        AuditLog(
            user_id=user.id,
            action="login",
            target_type="user",
            target_id=user.id,
            detail={},
            ip=user.last_login_ip,
        )
    )
    db.commit()
    db.refresh(user)
    _set_access_cookie(response, user)
    return user


@router.post("/logout")
def logout(response: Response):
    """清除浏览器 Cookie，不干预已经排队或运行的任务。"""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """供 SPA 刷新后恢复身份的当前成员接口。"""
    return user


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """校验旧密码后更新哈希并令旧登录 Cookie 立即失效。"""
    _validate_password(body.new_password)
    if not body.old_password or not verify_password(body.old_password, user.password_hash):
        raise AppError(ErrorCode.VALIDATION, "旧密码不正确", fields={"old_password": "旧密码不正确"})
    user.password_hash = hash_password(body.new_password)
    user.auth_version += 1
    db.add(
        AuditLog(
            user_id=user.id,
            action="password_change",
            target_type="user",
            target_id=user.id,
            detail={},
            ip=client_ip(request),
        )
    )
    db.commit()
    db.refresh(user)
    _set_access_cookie(response, user)
    return {"ok": True}


@router.post("/ws-ticket")
def ws_ticket(user: User = Depends(get_current_user)):
    """签发五分钟单次短票，长期浏览器 Cookie 不进入 WS query。

    每张票携带唯一 ``jti``，WebSocket 建连时消费一次即作废，
    防止同一票据在有效期内被重复用于建立多个连接。
    """
    ticket = create_token(
        user.id,
        user.auth_version,
        TOKEN_TYPE_WS,
        settings.ws_ticket_expire_minutes,
        jti=uuid4().hex,
    )
    return {"ticket": ticket, "expires_in": settings.ws_ticket_expire_minutes * 60}
