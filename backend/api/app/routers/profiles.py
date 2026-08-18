"""三协议档的安全 CRUD 和真实连通性检查接口。"""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends
from fastapi import Request as FastApiRequest
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..models import AuditLog, ProtocolProfile, User
from ..schemas import ProfileCreate, ProfileOut, ProfileUpdate
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


def _endpoint_and_body(profile: ProtocolProfile) -> tuple[str, dict, dict[str, str]]:
    """按协议构造最小真实上游探活请求，不返回或记录认证头。"""
    base = profile.base_url.rstrip("/")
    api_key = decrypt_secret(profile.encrypted_key) if profile.encrypted_key else ""
    if not api_key:
        raise AppError(ErrorCode.VALIDATION, "协议档未配置 API Key")
    headers = {"Content-Type": "application/json"}
    if profile.protocol == "openai_chat":
        headers["Authorization"] = f"Bearer {api_key}"
        return (
            f"{base}/v1/chat/completions",
            {"model": profile.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
            headers,
        )
    if profile.protocol == "openai_responses":
        headers["Authorization"] = f"Bearer {api_key}"
        return f"{base}/v1/responses", {"model": profile.model, "input": "ping", "max_output_tokens": 1}, headers
    headers["x-api-key"] = api_key
    headers["anthropic-version"] = profile.anthropic_version or "2023-06-01"
    return (
        f"{base}/v1/messages",
        {"model": profile.model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]},
        headers,
    )


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
    """删除未被 Agent 默认配置引用的协议档。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
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


@router.post("/{profile_id}/check")
def check_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """向目标协议端点发送最小真实探活请求并返回脱敏结果。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    url, body, headers = _endpoint_and_body(profile)
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=10) as response:
            response.read(1)
        return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000), "model": profile.model}
    except HTTPError as exc:
        return {"ok": False, "code": "UPSTREAM", "message": f"{exc.code} from upstream"}
    except (URLError, TimeoutError):
        return {"ok": False, "code": "UPSTREAM", "message": "上游连接失败"}
