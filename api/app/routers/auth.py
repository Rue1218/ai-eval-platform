from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import AuditLog, User
from ..schemas import LoginRequest, UserOut
from ..security import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_WS,
    create_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        db.add(AuditLog(action="login_failed", detail={"username": body.username}))
        db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.disabled:
        raise HTTPException(status_code=403, detail="账号已停用")

    token = create_token(
        user.id, user.role, TOKEN_TYPE_ACCESS, settings.access_token_expire_minutes
    )
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    db.add(AuditLog(action="login", detail={"user_id": user.id}))
    db.commit()
    return UserOut.model_validate(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/ws-ticket")
def ws_ticket(user: User = Depends(get_current_user)):
    ticket = create_token(
        user.id, user.role, TOKEN_TYPE_WS, settings.ws_ticket_expire_minutes
    )
    return {"ticket": ticket, "expires_in": settings.ws_ticket_expire_minutes * 60}
