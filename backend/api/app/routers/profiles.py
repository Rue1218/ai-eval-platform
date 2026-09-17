"""两类协议档的安全 CRUD 和真实连通性检查接口。"""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi import Request as FastApiRequest
from shared.model_urls import same_origin
from sqlalchemy.orm import Session

from ..adapters import DEFAULT_TIMEOUT_S, fetch_remote_models
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..llm.contracts import ModelConfig
from ..llm.loop_contracts import LlmRequestError
from ..llm.providers.catalog import detect_provider
from ..llm.providers.common import normalize_base_url
from ..llm.providers.reasoning_templates import (
    ensure_template_compatible,
    get_template,
    list_templates,
)
from ..models import AuditLog, ProtocolProfile, Setting, User
from ..profile_check import check_model_connection
from ..profile_env import (
    ProfileEnvSnapshot,
    read_global_llm_env,
    read_profile_env,
    remove_profile_env,
    resolve_env_api_key_for_url,
    resolve_env_base_url,
    restore_snapshot,
    write_profile_env,
)
from ..profile_probe import probe_reasoning_template
from ..profile_reasoning import profile_reasoning
from ..schemas import (
    FetchModelsIn,
    ProfileCreate,
    ProfileOut,
    ProfileProbeCreate,
    ProfileProbeOut,
    ProfileProbeUpdate,
    ProfileUpdate,
)
from ..security import decrypt_secret
from ._common import client_ip

router = APIRouter(prefix="/api/profiles", tags=["profiles"])
logger = logging.getLogger("ai-eval.profiles")

# 页面探活会触发一次真实模型推理，必须与协议调用共用 30 秒上限，避免冷启动被误判为不可用。
PROFILE_CHECK_TIMEOUT_S = DEFAULT_TIMEOUT_S


def _reuse_api_key(current_url: str | None, next_url: str | None, current_key: str | None,
                  explicit_key: str | None) -> str | None:
    """跨源编辑必须重新提供凭据，在探测、获取模型和保存前统一拒绝隐式转发。"""
    if explicit_key:
        return explicit_key
    if current_key and not same_origin(current_url, next_url):
        raise AppError(ErrorCode.VALIDATION, "服务地址的协议、主机或端口已变更，请重新填写 API Key")
    return current_key


def _validate_profile_url(url: str, protocol: str, full_url: bool) -> None:
    """保存前验证 URL，不向上游发送请求或要求模型支持思考。"""
    try:
        normalize_base_url(url, protocol, full_url=full_url)
    except LlmRequestError as exc:
        raise AppError(ErrorCode.VALIDATION, "请填写合法的模型服务地址") from exc


def _legacy_api_key(profile: ProtocolProfile) -> str | None:
    """兼容迁移前的历史密文；新建和更新协议档不会再写入该列。"""
    if not profile.encrypted_key:
        return None
    try:
        return decrypt_secret(profile.encrypted_key)
    except AppError:
        raise
    except Exception as exc:
        logger.warning("协议档历史密文解密失败 type=%s", type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "协议档凭据读取失败") from exc


def _profile_connection(
    profile: ProtocolProfile,
    *,
    allow_global_alias: bool = False,
) -> tuple[str, str, str | None]:
    """读取环境文件中的 URL、模型 ID、Key，历史密文仅作一次性回退。"""
    try:
        env_values = read_profile_env(profile.id)
        global_values = read_global_llm_env()
        profile_env_configured = any((env_values.base_url, env_values.model, env_values.api_key))
        global_base_url = (
            global_values.anthropic_base_url
            if profile.protocol == "anthropic_messages"
            else global_values.openai_base_url
        )
        return (
            env_values.base_url
            or (global_base_url if allow_global_alias and not profile_env_configured else None)
            or profile.base_url,
            env_values.model
            or (global_values.model if allow_global_alias and not profile_env_configured else None)
            or profile.model,
            env_values.api_key
            or (global_values.api_key if allow_global_alias and not profile_env_configured and global_base_url else None)
            or _legacy_api_key(profile),
        )
    except AppError:
        raise
    except Exception as exc:
        logger.warning("协议档环境配置读取失败 type=%s", type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置读取失败") from exc


def _migrate_profile_to_env(profile: ProtocolProfile) -> ProfileEnvSnapshot | None:
    """把历史数据库字段迁移到环境文件并清空历史密文列。"""
    env_values = read_profile_env(profile.id)
    global_values = read_global_llm_env()
    global_base_url = (
        global_values.anthropic_base_url
        if profile.protocol == "anthropic_messages"
        else global_values.openai_base_url
    )
    legacy_key = (
        _legacy_api_key(profile)
        if not env_values.api_key and not global_values.api_key
        else None
    )
    updates: dict[str, str] = {}
    if not env_values.base_url and not global_base_url and profile.base_url:
        updates["base_url"] = profile.base_url
    if not env_values.model and not global_values.model and profile.model:
        updates["model"] = profile.model
    if not env_values.api_key and not global_values.api_key and legacy_key:
        updates["api_key"] = legacy_key
    snapshot = None
    if updates:
        snapshot = write_profile_env(profile.id, **updates)
    if profile.encrypted_key:
        profile.encrypted_key = None
    return snapshot


def _profile_out(profile: ProtocolProfile, connection: tuple[str, str, str | None] | None = None) -> ProfileOut:
    """构造永不回显 Key 的协议档响应，连接参数以环境文件为准。"""
    try:
        base_url, model, api_key = connection or _profile_connection(profile)
        env_values = read_profile_env(profile.id)
    except AppError:
        raise
    except Exception as exc:
        logger.warning("协议档响应环境读取失败 type=%s", type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置读取失败") from exc
    reasoning = profile_reasoning(
        profile.protocol,
        base_url,
        model,
        getattr(profile, "max_output_tokens", 8192) or 8192,
        full_url=env_values.full_url,
        reasoning_template_id=getattr(profile, "reasoning_template_id", None),
        reasoning_probe=getattr(profile, "reasoning_probe", None),
    )
    template_id = getattr(profile, "reasoning_template_id", None)
    try:
        template_name = get_template(template_id).name if template_id else None
    except LlmRequestError:
        template_name = None
    probe = getattr(profile, "reasoning_probe", None)
    probe_status = (
        str(probe.get("status"))
        if isinstance(probe, dict) and probe.get("status") in {"passed", "partial", "failed"}
        else "unverified" if template_id else "legacy"
    )
    if template_id and probe_status in {"passed", "partial"} and not reasoning["allowed_efforts"]:
        probe_status = "unverified"
    tool_probe = probe.get("tool_probe", {}) if isinstance(probe, dict) else {}
    tool_status = tool_probe.get("status") if isinstance(tool_probe, dict) else None
    if probe_status not in {"passed", "partial"} or tool_status not in {"passed", "failed", "skipped"}:
        tool_status = "unverified"
    elif tool_status in {"passed", "failed"} and tool_probe.get("effort") not in reasoning["allowed_efforts"]:
        tool_status = "unverified"
    return ProfileOut(
        **reasoning,
        full_url=env_values.full_url,
        id=profile.id,
        name=profile.name,
        protocol=profile.protocol,
        base_url=base_url,
        model=model,
        usages=profile.usages or [],
        anthropic_version=profile.anthropic_version,
        has_api_key=bool(api_key),
        embedding_base_url=env_values.embedding_base_url,
        embedding_model=env_values.embedding_model,
        has_embedding_api_key=bool(env_values.embedding_api_key),
        reranker_base_url=env_values.reranker_base_url,
        reranker_model=env_values.reranker_model,
        has_reranker_api_key=bool(env_values.reranker_api_key),
        context_window=getattr(profile, "context_window", 200000) or 200000,
        max_output_tokens=getattr(profile, "max_output_tokens", 8192) or 8192,
        reasoning_template_id=template_id,
        reasoning_template_name=template_name,
        reasoning_probe_status=probe_status,
        tool_probe_status=tool_status,
        tool_call_mode=getattr(profile, "tool_call_mode", "native") or "native",
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("")
def list_profiles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出协议档，并将旧数据库参数一次性迁移到环境文件。"""
    rows = db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.desc()).all()
    snapshots: list[ProfileEnvSnapshot] = []
    db_changed = False
    try:
        for row in rows:
            had_legacy_key = bool(row.encrypted_key)
            snapshot = _migrate_profile_to_env(row)
            if snapshot:
                snapshots.append(snapshot)
            db_changed = db_changed or had_legacy_key or bool(snapshot)
        if db_changed:
            db.commit()
    except Exception as exc:
        db.rollback()
        for snapshot in reversed(snapshots):
            restore_snapshot(snapshot)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置读写失败") from exc
    return {
        "items": [_profile_out(row).model_dump(mode="json") for row in rows],
        "total": len(rows),
    }


@router.get("/reasoning-templates")
def get_reasoning_templates(
    provider: str,
    protocol: str,
    model: str = Query(min_length=1, max_length=256),
    user: User = Depends(get_current_user),
):
    """返回当前供应商、协议和模型可选择的受控思考模板，不返回可执行请求体。"""
    if protocol not in {"openai_chat", "openai_responses", "anthropic_messages"}:
        raise AppError(ErrorCode.VALIDATION, "协议类型不支持")
    normalized_provider = provider.strip().lower()
    if not normalized_provider or len(normalized_provider) > 64:
        raise AppError(ErrorCode.VALIDATION, "供应商标识不合法")
    items = [template.summary() for template in list_templates(normalized_provider, protocol, model)]
    return {"items": items, "total": len(items)}


def _probe_model_config(
    body: ProfileProbeCreate,
    *,
    api_key: str | None,
) -> dict[str, object]:
    """用待保存配置执行真实模板探测；返回内容仅含安全状态与通过档位。"""
    _validate_profile_url(body.base_url, body.protocol, body.full_url)
    provider = detect_provider(str(body.base_url).strip(), body.model, body.protocol)
    try:
        template = ensure_template_compatible(
            body.reasoning_template_id, provider, body.protocol, body.model,
        )
    except LlmRequestError as exc:
        raise AppError(ErrorCode.VALIDATION, "所选思考模板与供应商或协议不兼容") from exc
    if not api_key or not api_key.strip():
        raise AppError(ErrorCode.VALIDATION, "测试并添加需要当前模型的 API Key")
    config = ModelConfig(
        protocol=body.protocol,
        base_url=str(body.base_url).strip(),
        model=body.model,
        api_key=api_key,
        anthropic_version=body.anthropic_version,
        max_tokens=body.max_output_tokens,
        timeout_s=PROFILE_CHECK_TIMEOUT_S,
        reasoning_enabled=template.default_effort != "off",
        reasoning_effort=(template.default_effort if template.default_effort != "off" else "medium"),
        tool_call_mode=body.tool_call_mode,
        full_url=body.full_url,
        reasoning_template_id=template.id,
    )
    try:
        return probe_reasoning_template(config, check_tools="agent" in body.usages)
    except LlmRequestError as exc:
        raise AppError(ErrorCode.VALIDATION, "模型思考模板配置无效") from exc


def _probe_message(probe: dict[str, object]) -> str:
    """把非敏感探测结果转换为配置页可读提示，不泄露上游正文。"""
    supported = probe.get("supported_efforts")
    count = len(supported) if isinstance(supported, list) else 0
    if probe.get("status") in {"passed", "partial"}:
        label = "验证通过" if probe["status"] == "passed" else "部分通过"
        message = f"模型模板{label}，已确认 {count} 个思考档位"
        tool_status = (probe.get("tool_probe") or {}).get("status")
        if tool_status == "passed":
            return message + "；原生工具调用及结果回填已通过"
        if tool_status == "failed":
            return message + "；原生工具往返未通过，已保存但用于 Agent 前请检查模型或通道配置"
        return message + "；原生工具未验证"
    # 仅解释平台安全分类，不展示上游正文；便于用户选其他方言或重试。
    labels = {
        "NO_REASONING_EVIDENCE": "本次未观察到思考证据",
        "THINKING_NOT_DISABLED": "关闭后仍返回思考内容",
        "EMPTY_RESPONSE": "未返回正文",
        "TIMEOUT": "验证超时",
        "UPSTREAM": "上游拒绝请求或未正常完成",
        "VALIDATION": "所选参数不兼容",
        "AUTH_FAILED": "模型服务鉴权失败，请检查 API Key、令牌分组及模型访问权限",
        "MODEL_OR_ENDPOINT_UNAVAILABLE": "模型或接口不可用，请核对模型 ID、Base URL 和通道支持的协议",
        "RATE_LIMITED": "模型服务限流，请检查令牌并发限制或稍后重试",
        "UPSTREAM_UNAVAILABLE": "网关或上游通道暂时不可用，请检查通道状态",
        "CONNECTION_FAILED": "无法连接模型服务，请检查服务器到 Base URL 的网络与证书",
        "PARAMETERS_REJECTED": "请求参数或协议被拒绝，请核对通道是否支持当前协议及思考模板",
        "INVALID_RESPONSE": "返回格式与所选协议不匹配，请核对接口地址、协议和流式支持",
        "INCOMPLETE_RESPONSE": "模型响应未正常结束，请检查输出上限或流式连接",
        "BUDGET_EXCEEDED": "模型服务额度不足，请检查令牌余额及上游通道额度",
    }
    reasons = list(dict.fromkeys(
        labels.get(item.get("error_code"), "所选参数未通过验证")
        for item in probe.get("attempts", []) if isinstance(item, dict) and not item.get("ok")
    ))
    detail = "；".join(reasons) or "所选模板未通过验证"
    return f"{detail}，未保存协议档；可选择其他模板或重试"


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
    snapshot = None
    had_legacy_key = bool(profile.encrypted_key)
    try:
        snapshot = _migrate_profile_to_env(profile)
        if snapshot or had_legacy_key:
            db.commit()
    except Exception as exc:
        db.rollback()
        if snapshot:
            restore_snapshot(snapshot)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置读写失败") from exc
    return _profile_out(profile)


def _create_profile(
    body: ProfileCreate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    *,
    reasoning_probe: dict[str, object] | None = None,
):
    """创建协议档并把 URL、模型 ID、API Key 写入受控环境文件。"""
    _validate_profile_url(body.base_url, body.protocol, body.full_url)
    profile = ProtocolProfile(
        name=body.name,
        protocol=body.protocol,
        base_url=str(body.base_url).strip(),
        model=body.model,
        usages=body.usages,
        anthropic_version=body.anthropic_version,
        # API Key 严禁写入数据库；这里只保留数据库模型兼容列的空值。
        encrypted_key=None,
        context_window=body.context_window,
        max_output_tokens=body.max_output_tokens,
        tool_call_mode=body.tool_call_mode,
        reasoning_template_id=body.reasoning_template_id,
        reasoning_probe=reasoning_probe,
        reasoning_config_version=1,
        created_by=user.id,
    )
    db.add(profile)
    snapshot: ProfileEnvSnapshot | None = None
    try:
        db.flush()
        snapshot = write_profile_env(
            profile.id,
            base_url=str(body.base_url).strip(),
            model=body.model,
            full_url=body.full_url,
            api_key=body.api_key or None,
            embedding_base_url=(
                str(body.embedding_base_url).rstrip("/") if body.embedding_base_url else None
            ),
            embedding_model=body.embedding_model,
            embedding_api_key=body.embedding_api_key or None,
            reranker_base_url=(
                str(body.reranker_base_url).rstrip("/") if body.reranker_base_url else None
            ),
            reranker_model=body.reranker_model,
            reranker_api_key=body.reranker_api_key or None,
            protocol=body.protocol,
            write_global_aliases=True,
        )
        db.add(
            AuditLog(
                user_id=user.id,
                action=(
                    "key_change"
                    if body.api_key or body.embedding_api_key or body.reranker_api_key
                    else "profile_create"
                ),
                target_type="profile",
                target_id=profile.id,
                detail={
                    "name": profile.name,
                    "has_api_key": bool(body.api_key),
                    "has_embedding_api_key": bool(body.embedding_api_key),
                    "has_reranker_api_key": bool(body.reranker_api_key),
                    "reasoning_template_id": body.reasoning_template_id,
                    "reasoning_probe_status": reasoning_probe.get("status") if reasoning_probe else None,
                },
                ip=client_ip(request),
            )
        )
        db.commit()
        db.refresh(profile)
    except Exception as exc:
        db.rollback()
        if snapshot:
            restore_snapshot(snapshot)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置写入失败") from exc
    return _profile_out(profile)


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileCreate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保留旧协议档创建入口；带模板的新模型必须改走真实探测接口。"""
    if body.reasoning_template_id:
        raise AppError(ErrorCode.VALIDATION, "使用思考模板的新模型请先测试并添加")
    return _create_profile(body, request, db, user)


@router.post("/probe-create", response_model=ProfileProbeOut)
def probe_create_profile(
    body: ProfileProbeCreate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """逐档真实验证供应商模板；成功后才创建协议档与受控环境配置。"""
    probe = _probe_model_config(body, api_key=body.api_key)
    message = _probe_message(probe)
    if probe.get("status") == "failed":
        return ProfileProbeOut(ok=False, profile=None, probe=probe, message=message)
    profile = _create_profile(body, request, db, user, reasoning_probe=probe)
    return ProfileProbeOut(ok=True, profile=profile, probe=probe, message=message)


def _update_profile(
    profile_id: str,
    body: ProfileUpdate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    *,
    reasoning_probe: dict[str, object] | None = None,
):
    """更新协议档并安全刷新环境文件中的 URL、模型 ID、API Key。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    values = body.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    embedding_api_key = values.pop("embedding_api_key", None)
    reranker_api_key = values.pop("reranker_api_key", None)
    changed_reasoning_inputs = bool(
        {"protocol", "base_url", "full_url", "model", "max_output_tokens", "reasoning_template_id", "anthropic_version"}
        & set(values)
    ) or bool(api_key)  # 新凭据可能路由到不同通道，不能复用旧验证结果。
    current_env = read_profile_env(profile.id)
    full_url = values.pop("full_url", None)
    full_url = current_env.full_url if full_url is None else full_url
    # 编辑旧单模型环境配置时允许从全局别名读取一次，随后固化为本 profile 变量。
    current_base_url, current_model, current_api_key = _profile_connection(profile, allow_global_alias=True)
    next_base_url = current_base_url
    next_model = current_model
    if values.get("base_url") is not None:
        next_base_url = str(values["base_url"]).strip()
    if values.get("model") is not None:
        next_model = values["model"]
    _validate_profile_url(next_base_url, values.get("protocol") or profile.protocol, full_url)
    next_api_key = _reuse_api_key(current_base_url, next_base_url, current_api_key, api_key)
    next_embedding_base_url = current_env.embedding_base_url
    next_embedding_model = current_env.embedding_model
    next_reranker_base_url = current_env.reranker_base_url
    next_reranker_model = current_env.reranker_model
    if "embedding_base_url" in values:
        raw_val = values.pop("embedding_base_url")
        next_embedding_base_url = str(raw_val).rstrip("/") if raw_val and str(raw_val).strip() else None
    if "embedding_model" in values:
        raw_model = values.pop("embedding_model")
        next_embedding_model = str(raw_model).strip() if raw_model and str(raw_model).strip() else None
    if "reranker_base_url" in values:
        raw_val = values.pop("reranker_base_url")
        next_reranker_base_url = str(raw_val).rstrip("/") if raw_val and str(raw_val).strip() else None
    if "reranker_model" in values:
        raw_model = values.pop("reranker_model")
        next_reranker_model = str(raw_model).strip() if raw_model and str(raw_model).strip() else None
    next_embedding_api_key = _reuse_api_key(
        current_env.embedding_base_url or current_base_url, next_embedding_base_url or next_base_url,
        current_env.embedding_api_key, embedding_api_key,
    )
    next_reranker_api_key = _reuse_api_key(
        current_env.reranker_base_url or current_base_url, next_reranker_base_url or next_base_url,
        current_env.reranker_api_key, reranker_api_key,
    )
    key_changed = bool(api_key or embedding_api_key or reranker_api_key)
    snapshot: ProfileEnvSnapshot | None = None
    for field, value in values.items():
        if field == "base_url" and value is not None:
            value = str(value).strip()
        setattr(profile, field, value)
    if reasoning_probe is not None:
        profile.reasoning_probe = reasoning_probe
        profile.reasoning_config_version = int(getattr(profile, "reasoning_config_version", 0) or 0) + 1
    elif changed_reasoning_inputs:
        # 兼容旧 API 编辑时不偷偷沿用已验证的结果；必须重新走测试并更新。
        profile.reasoning_probe = None
        profile.reasoning_config_version = int(getattr(profile, "reasoning_config_version", 0) or 0) + 1
    profile.encrypted_key = None
    try:
        snapshot = write_profile_env(
            profile.id,
            base_url=next_base_url,
            full_url=full_url,
            model=next_model,
            # 编辑其它字段时保留现有 Key，并把旧全局/历史密文 Key 固化到本 profile 变量。
            api_key=next_api_key,
            embedding_base_url=next_embedding_base_url,
            embedding_model=next_embedding_model,
            embedding_api_key=next_embedding_api_key,
            reranker_base_url=next_reranker_base_url,
            reranker_model=next_reranker_model,
            reranker_api_key=next_reranker_api_key,
            protocol=profile.protocol,
            write_global_aliases=True,
        )
        db.add(
            AuditLog(
                user_id=user.id,
                action="key_change" if key_changed else "profile_update",
                target_type="profile",
                target_id=profile.id,
                detail={
                    "name": profile.name,
                    "has_api_key": bool(next_api_key),
                    "has_embedding_api_key": bool(next_embedding_api_key),
                    "has_reranker_api_key": bool(next_reranker_api_key),
                    "reasoning_template_id": getattr(profile, "reasoning_template_id", None),
                    "reasoning_probe_status": reasoning_probe.get("status") if reasoning_probe else None,
                },
                ip=client_ip(request),
            )
        )
        db.commit()
        db.refresh(profile)
    except Exception as exc:
        db.rollback()
        if snapshot:
            restore_snapshot(snapshot)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置写入失败") from exc
    return _profile_out(profile)


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保留 legacy 编辑入口；模板模型的连接变更必须先重新验证。"""
    if body.reasoning_template_id:
        raise AppError(ErrorCode.VALIDATION, "使用思考模板的模型请先测试并更新")
    return _update_profile(profile_id, body, request, db, user)


@router.post("/{profile_id}/probe-update", response_model=ProfileProbeOut)
def probe_update_profile(
    profile_id: str,
    body: ProfileProbeUpdate,
    request: FastApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """用完整的拟更新配置验证模板，失败时不改动已保存的协议档。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    current_base_url, _model, current_api_key = _profile_connection(profile, allow_global_alias=True)
    api_key = _reuse_api_key(current_base_url, body.base_url, current_api_key, body.api_key)
    probe = _probe_model_config(body, api_key=api_key)
    message = _probe_message(probe)
    if probe.get("status") == "failed":
        return ProfileProbeOut(ok=False, profile=None, probe=probe, message=message)
    updated = _update_profile(profile_id, body, request, db, user, reasoning_probe=probe)
    return ProfileProbeOut(ok=True, profile=updated, probe=probe, message=message)


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
    snapshot: ProfileEnvSnapshot | None = None
    try:
        snapshot = remove_profile_env(profile_id)
        db.delete(profile)
        db.add(
            AuditLog(
                user_id=user.id,
                action="profile_delete",
                target_type="profile",
                target_id=profile_id,
                detail={"name": profile.name},
                ip=client_ip(request),
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if snapshot:
            restore_snapshot(snapshot)
        raise AppError(ErrorCode.INTERNAL, "协议档环境配置删除失败") from exc
    return {"ok": True}


@router.get("/{profile_id}/models")
def get_profile_models(
    profile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """根据已有协议档 ID 直接获取该目标端点可用模型列表。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    if read_profile_env(profile.id).full_url:
        raise AppError(ErrorCode.VALIDATION, "完整 URL 模式请手动填写模型标识")
    env_base_url, _model, env_api_key = _profile_connection(profile, allow_global_alias=True)
    base_url = env_base_url or resolve_env_base_url(profile.protocol)
    if not base_url:
        raise AppError(ErrorCode.VALIDATION, "该协议档未配置目标服务的 Base URL")
    api_key = env_api_key or resolve_env_api_key_for_url(base_url, protocol=profile.protocol)
    models = fetch_remote_models(
        protocol=profile.protocol,
        base_url=base_url,
        api_key=api_key,
        anthropic_version=profile.anthropic_version,
    )
    return {"ok": True, "models": models, "total": len(models)}


@router.post("/models")
@router.post("/fetch-models")
def fetch_models(
    body: FetchModelsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从目标服务 Base URL 获取可用的模型标识列表 (/models)，支持从 .env 自动匹配凭据。"""
    if body.full_url:
        raise AppError(ErrorCode.VALIDATION, "完整 URL 模式请手动填写模型标识")
    api_key = body.api_key
    protocol = body.protocol
    base_url = body.base_url
    anthropic_version = body.anthropic_version

    if body.profile_id:
        profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == body.profile_id).first()
        if not profile:
            raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
        if body.full_url is None and read_profile_env(profile.id).full_url:
            raise AppError(ErrorCode.VALIDATION, "完整 URL 模式请手动填写模型标识")
        protocol = profile.protocol
        # 兼容旧单模型环境；若该 profile 已有任一独立变量，则不会串用全局 Key。
        env_base_url, _model, env_api_key = _profile_connection(profile, allow_global_alias=True)
        if not base_url:
            base_url = env_base_url
        anthropic_version = profile.anthropic_version
        api_key = _reuse_api_key(env_base_url, base_url, env_api_key, api_key)

    # 若未提供 Base URL，尝试从 .env 获取默认 Base URL
    if not base_url:
        base_url = resolve_env_base_url(protocol)
    if not base_url:
        raise AppError(ErrorCode.VALIDATION, "请提供目标服务的 Base URL")

    # 若未显式传入 api_key，从 .env 环境配置中自动解析
    if not api_key:
        api_key = resolve_env_api_key_for_url(base_url, protocol=protocol)

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
    """以已保存模板及默认档位执行流式探活，参数与实际对话同源。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    # 旧单模型部署可直接用服务器 LLM_* 别名探活；已配置 profile 变量时优先 profile。
    base_url, model, api_key = _profile_connection(profile, allow_global_alias=True)
    if not api_key:
        raise AppError(ErrorCode.VALIDATION, "协议档未配置 API Key")
    full_url = read_profile_env(profile.id).full_url
    max_tokens = getattr(profile, "max_output_tokens", 8192) or 8192
    template_id = getattr(profile, "reasoning_template_id", None)
    reasoning = profile_reasoning(profile.protocol, base_url, model, max_tokens, full_url=full_url,
                                  reasoning_template_id=template_id,
                                  reasoning_probe=getattr(profile, "reasoning_probe", None))
    if template_id and not reasoning["allowed_efforts"]:
        return {"ok": False, "code": "VALIDATION", "message": "思考模板尚未验证或已失效，请编辑协议档重新测试并保存"}
    effort = reasoning["reasoning_effort"]
    return check_model_connection(ModelConfig(
        protocol=profile.protocol, base_url=base_url, model=model, api_key=api_key,
        full_url=full_url, max_tokens=max_tokens, anthropic_version=profile.anthropic_version,
        timeout_s=PROFILE_CHECK_TIMEOUT_S, reasoning_template_id=template_id,
        reasoning_enabled=effort != "off", reasoning_effort=effort if effort != "off" else "medium",
        reasoning_allowed_efforts=tuple(reasoning["allowed_efforts"]) if template_id else None,
    ))
