from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import TOKEN_TYPE_ACCESS, decode_token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="登录已过期")
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise HTTPException(status_code=401, detail="无效令牌")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or user.disabled:
        raise HTTPException(status_code=401, detail="用户不可用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
