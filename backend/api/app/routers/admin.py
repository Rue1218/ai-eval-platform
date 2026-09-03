"""全员同权的运行时配置、压测白名单治理与审计查询接口。"""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from ..agent.log import agent_trace
from ..agent_prompt_settings import (
    MAX_AGENT_PROMPT_OVERLAY_LENGTH,
    get_agent_prompt_overlay,
    update_agent_prompt_overlay,
)
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..harness.context import skill_hint_lines
from ..harness.prompts import DEFAULT_PROJECT_INSTRUCTIONS, SystemVars, build_system_prompt
from ..harness.skills.storage import (
    list_skill_metadata,
    read_skill_document,
    restore_skill_document,
    update_skill_document,
)
from ..models import AuditLog, ProtocolProfile, Setting, User
from ..profile_env import (
    ProfileEnvSnapshot,
    read_global_rag_env,
    restore_snapshot,
    write_global_rag_env,
    write_profile_env,
)
from ..schemas import ApiModel
from .profiles import _profile_connection
from .users import _parse_bound

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RagCheckIn(ApiModel):
    target: Literal["embedding", "reranker"]
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class RagModelsIn(ApiModel):
    """全局唯一的 Embedding 与 Reranker 模型配置输入。"""

    embedding_base_url: str | None = Field(default=None, max_length=1024)
    embedding_model: str | None = Field(default=None, max_length=256)
    embedding_api_key: str | None = Field(default=None, max_length=4096)
    reranker_base_url: str | None = Field(default=None, max_length=1024)
    reranker_model: str | None = Field(default=None, max_length=256)
    reranker_api_key: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="before")
    @classmethod
    def clean_empty(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for k in (
                "embedding_base_url",
                "embedding_model",
                "embedding_api_key",
                "reranker_base_url",
                "reranker_model",
                "reranker_api_key",
            ):
                if k in data and isinstance(data[k], str) and not data[k].strip():
                    data[k] = None
        return data


class AgentSkillUpdateIn(ApiModel):
    """管理端更新统一 SKILL.md 文件的请求体。"""

    content: str = Field(min_length=1, max_length=30_000)
    expected_revision: str = Field(min_length=16, max_length=16)


class AgentPromptUpdateIn(ApiModel):
    """管理端更新单个 Agent 协议档补充提示词的请求体。"""

    overlay: str = Field(default="", max_length=MAX_AGENT_PROMPT_OVERLAY_LENGTH)

DEFAULT_SETTINGS: dict[str, Any] = {
    "agent_profile_id": None,
    # Agent 模型推理控制：只允许展示上游返回的 reasoning summary，不暴露隐藏思维链。
    "agent_reasoning": {"enabled": True, "effort": "medium"},
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


def _require_agent_profile(db: Session, profile_id: str) -> ProtocolProfile:
    """校验 Prompt 管理目标存在且已启用 Agent 用途。"""
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "Agent 协议档不存在")
    if "agent" not in (profile.usages or []):
        raise AppError(ErrorCode.VALIDATION, "所选协议档未启用 agent 用途")
    return profile


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
    if "agent_reasoning" in body:
        reasoning = body["agent_reasoning"]
        if not isinstance(reasoning, dict):
            raise AppError(ErrorCode.VALIDATION, "agent_reasoning 必须为对象")
        if not isinstance(reasoning.get("enabled"), bool):
            raise AppError(ErrorCode.VALIDATION, "agent_reasoning.enabled 必须为布尔值")
        if reasoning.get("effort") not in {"low", "medium", "high", "xhigh", "max"}:
            raise AppError(ErrorCode.VALIDATION, "agent_reasoning.effort 不受支持")
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
    """保存允许的设置字段，并同步 Agent 模型的全局 LLM 环境别名。"""
    _validate_settings(body, db)
    env_snapshot: ProfileEnvSnapshot | None = None
    try:
        if body.get("agent_profile_id"):
            profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == body["agent_profile_id"]).first()
            base_url, model, api_key = _profile_connection(profile, allow_global_alias=True)
            env_snapshot = write_profile_env(
                profile.id,
                base_url=base_url,
                model=model,
                api_key=api_key,
                protocol=profile.protocol,
                write_global_aliases=True,
                remove_global_api_key=not bool(api_key),
            )
        # 批量加载已存在的设置行，避免逐 key 查询造成 N+1
        existing_settings = {
            row.key: row for row in db.query(Setting).filter(Setting.key.in_(list(body))).all()
        }
        for key, value in body.items():
            row = existing_settings.get(key)
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
    except AppError:
        db.rollback()
        if env_snapshot:
            restore_snapshot(env_snapshot)
        raise
    except Exception as exc:
        db.rollback()
        if env_snapshot:
            restore_snapshot(env_snapshot)
        raise AppError(ErrorCode.INTERNAL, "运行时配置写入失败") from exc
    return _load(db)


@router.get("/skills")
def list_agent_skills(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回技能文件的轻量目录，只读取 SKILL.md 头部。"""
    return {
        "items": [
            {
                "id": metadata.skill_id,
                "name": metadata.name,
                "kind": metadata.kind,
                "version": metadata.version,
                "enabled": metadata.enabled,
                "summary": metadata.summary,
            }
            for metadata in list_skill_metadata()
        ]
    }


@router.get("/skills/{skill_id}")
def get_agent_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预览单个技能完整文件；读取前由存储层验证 SKILL.md 存在。"""
    document = read_skill_document(skill_id)
    return {
        "id": document.metadata.skill_id,
        "content": document.content,
        "revision": document.revision,
        "metadata": {
            "id": document.metadata.skill_id,
            "name": document.metadata.name,
            "kind": document.metadata.kind,
            "version": document.metadata.version,
            "enabled": document.metadata.enabled,
            "summary": document.metadata.summary,
        },
    }


@router.put("/skills/{skill_id}")
def put_agent_skill(
    skill_id: str,
    body: AgentSkillUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """以修订指纹保护技能编辑，并记录不含正文的最小审计。"""
    previous = read_skill_document(skill_id)
    document = update_skill_document(skill_id, body.content, body.expected_revision)
    db.add(
        AuditLog(
            user_id=user.id,
            action="agent_skill_update",
            target_type="agent_skill",
            target_id=document.metadata.skill_id,
            detail={"revision": document.revision, "content_length": len(document.content)},
            ip=request.client.host if request.client else None,
        )
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            restore_skill_document(skill_id, previous.content, document.revision)
        except AppError as restore_error:
            agent_trace(
                "agent skill audit rollback failed "
                f"skill_id={skill_id} code={restore_error.code.value}"
            )
            raise AppError(ErrorCode.INTERNAL, "技能文件审计写入失败，请联系平台维护者") from restore_error
        raise AppError(ErrorCode.INTERNAL, "技能文件审计写入失败，已恢复原内容") from exc
    return {
        "id": document.metadata.skill_id,
        "content": document.content,
        "revision": document.revision,
        "metadata": {
            "id": document.metadata.skill_id,
            "name": document.metadata.name,
            "kind": document.metadata.kind,
            "version": document.metadata.version,
            "enabled": document.metadata.enabled,
            "summary": document.metadata.summary,
        },
    }


@router.get("/agent-prompts/{profile_id}")
def get_agent_prompt(
    profile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回指定 Agent 协议档的只读核心策略与可编辑补充提示词。"""
    profile = _require_agent_profile(db, profile_id)
    return {
        "profile_id": profile.id,
        "base_prompt": build_system_prompt(
            SystemVars(
                skill_hints=tuple(skill_hint_lines()),
                project_instructions=DEFAULT_PROJECT_INSTRUCTIONS,
            )
        ),
        "overlay": get_agent_prompt_overlay(db, profile.id),
    }


@router.put("/agent-prompts/{profile_id}")
def put_agent_prompt(
    profile_id: str,
    body: AgentPromptUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存协议档补充提示词；核心系统策略不提供写入通道。"""
    profile = _require_agent_profile(db, profile_id)
    overlay = update_agent_prompt_overlay(db, profile.id, body.overlay, updated_by=user.id)
    db.add(
        AuditLog(
            user_id=user.id,
            action="agent_prompt_update",
            target_type="agent_prompt",
            target_id=profile.id,
            detail={"overlay_length": len(overlay)},
            ip=request.client.host if request.client else None,
        )
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise AppError(ErrorCode.INTERNAL, "提示词配置写入失败") from exc
    return {
        "profile_id": profile.id,
        "base_prompt": build_system_prompt(
            SystemVars(
                skill_hints=tuple(skill_hint_lines()),
                project_instructions=DEFAULT_PROJECT_INSTRUCTIONS,
            )
        ),
        "overlay": overlay,
    }


@router.get("/rag-models")
def get_rag_models(
    user: User = Depends(get_current_user),
):
    """读取全局唯一的 Embedding 与 Reranker 模型配置（绝不回显密钥）。"""
    values = read_global_rag_env()
    return {
        "embedding_base_url": values.embedding_base_url or "",
        "embedding_model": values.embedding_model or "",
        "has_embedding_api_key": bool(values.embedding_api_key),
        "reranker_base_url": values.reranker_base_url or "",
        "reranker_model": values.reranker_model or "",
        "has_reranker_api_key": bool(values.reranker_api_key),
    }


@router.put("/rag-models")
def put_rag_models(
    body: RagModelsIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新系统全局唯一的 Embedding 与 Reranker 模型配置。"""
    env_snapshot: ProfileEnvSnapshot | None = None
    try:
        env_snapshot = write_global_rag_env(
            embedding_base_url=body.embedding_base_url,
            embedding_model=body.embedding_model,
            embedding_api_key=body.embedding_api_key,
            reranker_base_url=body.reranker_base_url,
            reranker_model=body.reranker_model,
            reranker_api_key=body.reranker_api_key,
        )
        db.add(
            AuditLog(
                user_id=user.id,
                action="rag_models_update",
                target_type="rag_models",
                detail={
                    "embedding_model": body.embedding_model,
                    "reranker_model": body.reranker_model,
                    "has_embedding_api_key": bool(body.embedding_api_key),
                    "has_reranker_api_key": bool(body.reranker_api_key),
                },
                ip=request.client.host if request.client else None,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if env_snapshot:
            restore_snapshot(env_snapshot)
        raise AppError(ErrorCode.INTERNAL, "全局 RAG 模型配置保存失败") from exc
    return get_rag_models(user=user)


@router.post("/rag-models/check")
def check_rag_model(
    body: RagCheckIn,
    user: User = Depends(get_current_user),
):
    """向指定的 Embedding 或 Reranker 模型端点发送轻量探活请求并返回延迟和状态。"""
    import time

    import httpx

    values = read_global_rag_env()
    if body.target == "embedding":
        base_url = (body.base_url or values.embedding_base_url or "").rstrip("/")
        model = body.model or values.embedding_model or ""
        api_key = body.api_key or values.embedding_api_key or ""
        if not base_url or not model:
            raise AppError(ErrorCode.VALIDATION, "Embedding 端点或模型名称未指定")
        url = f"{base_url}/embeddings" if not base_url.endswith("/embeddings") else base_url
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"input": "ping", "model": model}
    else:
        base_url = (body.base_url or values.reranker_base_url or "").rstrip("/")
        model = body.model or values.reranker_model or ""
        api_key = body.api_key or values.reranker_api_key or ""
        if not base_url or not model:
            raise AppError(ErrorCode.VALIDATION, "Reranker 端点或模型名称未指定")
        url = f"{base_url}/rerank" if not base_url.endswith("/rerank") else base_url
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"query": "ping", "documents": ["ping"], "model": model}

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code < 400:
                return {"ok": True, "latency_ms": latency_ms, "model": model, "target": body.target}
            else:
                return {
                    "ok": False,
                    "latency_ms": latency_ms,
                    "code": resp.status_code,
                    "message": f"HTTP {resp.status_code}: {resp.text[:120]}",
                }
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时（超过 8 秒未响应）"}
    except Exception as exc:
        return {"ok": False, "message": f"网络连通失败: {type(exc).__name__}"}


def _normalize_whitelist(items: list[Any]) -> list[dict[str, Any]]:
    """白名单条目归一化为契约对象；兼容早期纯字符串 host 写法。"""
    normalized: list[dict[str, Any]] = []
    for entry in items:
        if isinstance(entry, str):
            normalized.append(
                {"id": f"wl-{uuid4().hex[:8]}", "host": entry, "scope": "test", "creator": None, "created_at": None, "status": "active"}
            )
        elif isinstance(entry, dict) and entry.get("host"):
            normalized.append({**entry, "status": entry.get("status") or "active"})
    return normalized


def _save_stress_settings(db: Session, stress: dict[str, Any], user_id: str) -> None:
    """整体回写 stress 设置块（白名单与阈值同处一个 JSONB 值）。"""
    row = db.query(Setting).filter(Setting.key == "stress").first()
    if row:
        row.value = stress
        row.updated_by = user_id
    else:
        db.add(Setting(key="stress", value=stress, updated_by=user_id))


@router.get("/stress/whitelist", status_code=200)
def get_whitelist(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取发压 Host 白名单（存储于 settings.stress.host_whitelist）。"""
    items = _normalize_whitelist(_load(db)["stress"].get("host_whitelist") or [])
    return {"items": items, "total": len(items)}


@router.post("/stress/whitelist", status_code=201)
def add_whitelist(
    body: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新增白名单条目：host 必填且去重，scope 为 test/staging/prod 环境范围。"""
    host = str((body or {}).get("host") or "").strip()
    if not host:
        raise AppError(ErrorCode.VALIDATION, "host 不能为空")
    scope = str((body or {}).get("scope") or "test").strip() or "test"
    stress = _load(db)["stress"]
    items = _normalize_whitelist(stress.get("host_whitelist") or [])
    if any(entry["host"] == host for entry in items):
        raise AppError(ErrorCode.VALIDATION, "该 Host 已在白名单中")
    item = {
        "id": f"wl-{uuid4().hex[:8]}",
        "host": host,
        "scope": scope,
        "creator": user.username,
        "created_at": datetime.now(UTC).date().isoformat(),
        "status": "active",
    }
    items.append(item)
    stress["host_whitelist"] = items
    _save_stress_settings(db, stress, user.id)
    db.add(
        AuditLog(
            user_id=user.id,
            action="whitelist_change",
            target_type="stress_whitelist",
            target_id=item["id"],
            detail={"op": "add", "host": host, "scope": scope},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    return item


@router.delete("/stress/whitelist/{entry_id}")
def delete_whitelist(
    entry_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按条目 ID 移除白名单；不存在时按 NOT_FOUND 处理。"""
    stress = _load(db)["stress"]
    items = _normalize_whitelist(stress.get("host_whitelist") or [])
    target = next((entry for entry in items if entry["id"] == entry_id), None)
    if not target:
        raise AppError(ErrorCode.NOT_FOUND, "白名单条目不存在")
    stress["host_whitelist"] = [entry for entry in items if entry["id"] != entry_id]
    _save_stress_settings(db, stress, user.id)
    db.add(
        AuditLog(
            user_id=user.id,
            action="whitelist_change",
            target_type="stress_whitelist",
            target_id=entry_id,
            detail={"op": "remove", "host": target["host"]},
            ip=request.client.host if request.client else None,
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/audit-logs")
def get_audit_logs(
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按 API §3.12 契约过滤并分页返回合规审计事件（from/to 为 ISO 8601 时间）。"""
    to_bound = _parse_bound(to_ts, "to", None)
    from_bound = _parse_bound(from_ts, "from", None)
    query = db.query(AuditLog)
    if from_bound is not None:
        query = query.filter(AuditLog.ts >= from_bound)
    if to_bound is not None:
        query = query.filter(AuditLog.ts < to_bound)
    total = query.count()
    rows = query.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()
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
        "total": total,
    }
