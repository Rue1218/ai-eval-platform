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
