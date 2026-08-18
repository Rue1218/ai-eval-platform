"""全员同权的运行时配置与审计查询接口。"""

from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, ProtocolProfile, Setting, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEFAULT_SETTINGS: dict[str, Any] = {
    "agent_profile_id": None,
    "max_running_tasks": 3,
    "max_inflight_model_calls": 8,
    "default_max_usd": 5,
    "stress": {
        "host_whitelist": [],
        "max_qps": 500,
        "max_duration_s": 1800,
        "price_per_1k_tokens": 0.002,
    },
    "notify": {"wecom": False, "email": False, "webhook": False},
    "prod_approvers": [],
    # Agent 运行时治理（协议档页运行时 Tab）：WS 心跳/超时与会话占槽互斥
    "runtime": {"ws_ping_s": 15, "ws_timeout_s": 45, "strict_session_slot": True},
}
ALLOWED_KEYS = set(DEFAULT_SETTINGS)


def _load(db: Session) -> dict[str, Any]:
    """合并数据库覆盖项与不含敏感值的配置默认值。"""
    merged = deepcopy(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        if row.key in ALLOWED_KEYS:
            merged[row.key] = row.value
    return merged


def _validate_settings(body: dict[str, Any], db: Session) -> None:
    """校验 M1 已需读取的并发、预算和 Agent 协议档引用。"""
    unknown = set(body) - ALLOWED_KEYS
    if unknown:
        raise AppError(ErrorCode.VALIDATION, "存在未定义的设置字段")
    if "agent_profile_id" in body and body["agent_profile_id"] is not None:
        profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == body["agent_profile_id"]).first()
        if not profile:
            raise AppError(ErrorCode.NOT_FOUND, "Agent 协议档不存在")
        if "agent" not in (profile.usages or []):
            raise AppError(ErrorCode.VALIDATION, "所选协议档未启用 agent 用途")
    for key in ("max_running_tasks", "max_inflight_model_calls"):
        if key in body and (not isinstance(body[key], int) or body[key] < 1):
            raise AppError(ErrorCode.VALIDATION, f"{key} 必须为正整数")
    if "default_max_usd" in body and (not isinstance(body["default_max_usd"], int | float) or body["default_max_usd"] <= 0):
        raise AppError(ErrorCode.VALIDATION, "default_max_usd 必须大于 0")
    if "runtime" in body:
        runtime = body["runtime"]
        if not isinstance(runtime, dict):
            raise AppError(ErrorCode.VALIDATION, "runtime 必须为对象")
        for key in ("ws_ping_s", "ws_timeout_s"):
            if key in runtime and (not isinstance(runtime[key], int) or not 5 <= runtime[key] <= 300):
                raise AppError(ErrorCode.VALIDATION, f"runtime.{key} 必须为 5–300 的整数秒")


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取前端工作台所需的受控配置，不回显通知凭据。"""
    return _load(db)


@router.put("/settings")
def put_settings(
    body: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存允许的设置字段，并为每次变更追加审计记录。"""
    _validate_settings(body, db)
    for key, value in body.items():
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
            row.updated_by = user.id
        else:
            db.add(Setting(key=key, value=value, updated_by=user.id))
    db.add(
        AuditLog(
            user_id=user.id,
            action="settings_update",
            target_type="settings",
            detail={"keys": sorted(body)},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    return _load(db)


@router.get("/audit-logs")
def get_audit_logs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """以只读方式返回近期合规审计事件。"""
    rows = db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(200).all()
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
