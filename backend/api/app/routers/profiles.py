"""三协议档的安全 CRUD 和真实连通性检查接口。"""

from fastapi import APIRouter, Depends
from fastapi import Request as FastApiRequest
from sqlalchemy.orm import Session

from ..adapters import call_protocol, fetch_remote_models
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, ProtocolProfile, Setting, User
from ..schemas import FetchModelsIn, ProfileCreate, ProfileOut, ProfileUpdate
from ..security import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _profile_out(profile: ProtocolProfile) -> ProfileOut:
    """构造永不回显 Key 的协议档响应。"""
    return ProfileOut(
        id=profile.id,
        name=profile.name,
        protocol=profile.protocol,
        base_url=profile.base_url,
        model=profile.model,
        usages=profile.usages or [],
        anthropic_version=profile.anthropic_version,
        has_api_key=bool(profile.encrypted_key),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _request_ip(request: FastApiRequest) -> str | None:
    """提取协议档变更的请求来源 IP。"""
    return request.client.host if request.client else None


@router.get("")
def list_profiles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出所有协议档的非敏感发现信息。"""
    rows = db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.desc()).all()
    return {"items": [_profile_out(row).model_dump(mode="json") for row in rows], "total": len(rows)}


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取单个协议档，仍不返回 API Key。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    return _profile_out(profile)


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileCreate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建协议档并将可选 API Key 加密后写入数据库。"""
    profile = ProtocolProfile(
        name=body.name,
        protocol=body.protocol,
        base_url=str(body.base_url).rstrip("/"),
        model=body.model,
        usages=body.usages,
        anthropic_version=body.anthropic_version,
        encrypted_key=encrypt_secret(body.api_key) if body.api_key else None,
        created_by=user.id,
    )
    db.add(profile)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="key_change" if body.api_key else "profile_create",
            target_type="profile",
            target_id=profile.id,
            detail={"name": profile.name, "has_api_key": bool(body.api_key)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新协议档公开字段，并在有新 Key 时替换密文。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    values = body.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    for field, value in values.items():
        if field == "base_url" and value is not None:
            value = str(value).rstrip("/")
        setattr(profile, field, value)
    if api_key:
        profile.encrypted_key = encrypt_secret(api_key)
    db.add(
        AuditLog(
            user_id=user.id,
            action="key_change" if api_key else "profile_update",
            target_type="profile",
            target_id=profile.id,
            detail={"name": profile.name, "has_api_key": bool(api_key)},
            ip=_request_ip(request),
        )
    )
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: str,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除未被 Agent 默认配置引用的协议档（API §3.6：被引用的协议档禁止删除）。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    # Agent 核心驱动档不允许直接删除：需先在系统设置中解除 agent_profile_id 引用
    setting_row = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    if setting_row and setting_row.value == profile_id:
        raise AppError(ErrorCode.VALIDATION, "该协议档正被 Agent 后端引用，请先在设置页解除引用后再删除")
    db.delete(profile)
    db.add(
        AuditLog(
            user_id=user.id,
            action="profile_delete",
            target_type="profile",
            target_id=profile_id,
            detail={"name": profile.name},
            ip=_request_ip(request),
        )
    )
    db.commit()
    return {"ok": True}


@router.post("/fetch-models")
def fetch_models(
    body: FetchModelsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从目标服务 Base URL 获取可用的模型标识列表 (/models)。"""
    api_key = body.api_key
    protocol = body.protocol
    base_url = body.base_url
    anthropic_version = body.anthropic_version

    if body.profile_id:
        profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == body.profile_id).first()
        if not profile:
            raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
        protocol = profile.protocol
        base_url = profile.base_url
        anthropic_version = profile.anthropic_version
        if not api_key and profile.encrypted_key:
            api_key = decrypt_secret(profile.encrypted_key)

    models = fetch_remote_models(
        protocol=protocol,
        base_url=base_url,
        api_key=api_key,
        anthropic_version=anthropic_version,
    )
    return {"ok": True, "models": models, "total": len(models)}


@router.post("/{profile_id}/check")
def check_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """向目标协议端点发送最小真实探活请求并返回脱敏结果。

    复用三协议统一适配器：上游 4xx/5xx → ``UPSTREAM``、超时 → ``TIMEOUT``、
    结构异常 → ``UPSTREAM``；探活仅验证连通与鉴权，不因空文本判定失败。
    """
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    if not profile.encrypted_key:
        raise AppError(ErrorCode.VALIDATION, "协议档未配置 API Key")
    try:
        result = call_protocol(
            protocol=profile.protocol,
            base_url=profile.base_url,
            model=profile.model,
            api_key=decrypt_secret(profile.encrypted_key),
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            anthropic_version=profile.anthropic_version,
            timeout_s=10,
        )
    except AppError as exc:
        return {"ok": False, "code": exc.code.value, "message": exc.message}
    return {"ok": True, "latency_ms": result.latency_ms, "model": profile.model}
