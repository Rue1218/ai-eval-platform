from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .db import get_db
from .errors import AppError, ErrorCode
from .models import User
from .security import TOKEN_TYPE_ACCESS, decode_token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """从 HttpOnly Cookie 解析当前正常成员。"""
    token = request.cookies.get("aieval_session")
    if not token:
        raise AppError(ErrorCode.UNAUTHORIZED, "没有权限做这件事", status_code=401)
    try:
        payload = decode_token(token)
    except Exception:
        raise AppError(ErrorCode.UNAUTHORIZED, "登录已过期", status_code=401)
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise AppError(ErrorCode.UNAUTHORIZED, "无效令牌", status_code=401)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or user.disabled or payload.get("av") != user.auth_version:
        raise AppError(ErrorCode.UNAUTHORIZED, "用户不可用", status_code=401)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """兼容旧 router 依赖；V1.0 单一成员角色下不再区分管理员。"""
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """可选鉴权：无 Cookie 或令牌无效时返回 None，由路由按 share 等免登通道自行裁决。"""
    token = request.cookies.get("aieval_session")
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:
        return None
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        return None
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or user.disabled or payload.get("av") != user.auth_version:
        return None
    return user
