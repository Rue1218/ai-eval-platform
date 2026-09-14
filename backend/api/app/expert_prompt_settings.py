"""Agent 专家提示词的受控持久化与乐观并发保护。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .agent.experts import EXPERTS, ExpertDef, get_expert
from .errors import AppError, ErrorCode
from .harness.prompts.system import assert_no_secret_leak, assert_no_takeover
from .models import Setting

EXPERT_PROMPT_OVERRIDES_KEY = "agent_expert_prompt_overrides"
MAX_EXPERT_PROMPT_LENGTH = 30_000


@dataclass(frozen=True, slots=True)
class ExpertPromptDocument:
    """管理页展示的专家有效提示词与内置基线。"""

    expert: ExpertDef
    content: str
    builtin_content: str
    revision: str
    overridden: bool


def _read_prompt_overrides(db: Session) -> dict[str, str]:
    """读取专家覆盖层，损坏时拒绝运行，避免静默切换人格或覆盖数据。"""
    row = db.query(Setting).filter(Setting.key == EXPERT_PROMPT_OVERRIDES_KEY).first()
    return _decode_prompt_overrides(row.value) if row is not None else {}


def _decode_prompt_overrides(value: object) -> dict[str, str]:
    """兼容历史 JSON 字符串与原生 JSONB 对象，禁止静默丢弃损坏条目。"""
    try:
        payload = json.loads(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise AppError(ErrorCode.INTERNAL, "专家提示词配置损坏，请联系平台维护者") from exc
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) or not isinstance(text, str) or not text.strip()
        for key, text in payload.items()
    ):
        raise AppError(ErrorCode.INTERNAL, "专家提示词配置损坏，请联系平台维护者")
    return dict(payload)


def _require_prompt_expert(expert_id: object) -> ExpertDef:
    """校验目标专家拥有可管理的专属提示词。"""
    expert = get_expert(expert_id)
    if not expert.prompt_file:
        raise AppError(ErrorCode.VALIDATION, "该专家没有专属提示词，无需配置")
    return expert


def _revision(content: str) -> str:
    """生成与技能文件一致的短修订指纹，供前端并发保护。"""
    return sha256(content.encode("utf-8")).hexdigest()[:16]


def _normalize_content(content: str) -> str:
    """规范化可写提示词并执行安全与长度门禁。"""
    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        raise AppError(ErrorCode.VALIDATION, "专家提示词不能为空")
    if len(normalized) > MAX_EXPERT_PROMPT_LENGTH:
        raise AppError(ErrorCode.VALIDATION, f"专家提示词不能超过 {MAX_EXPERT_PROMPT_LENGTH} 个字符")
    assert_no_secret_leak(normalized)
    assert_no_takeover(normalized)
    return normalized


def read_expert_prompt_document(db: Session, expert_id: object) -> ExpertPromptDocument:
    """读取专家有效提示词；未覆盖时回落随代码分发的内置基线。"""
    expert = _require_prompt_expert(expert_id)
    return _prompt_document(expert, _read_prompt_overrides(db))


def _prompt_document(expert: ExpertDef, overrides: dict[str, str]) -> ExpertPromptDocument:
    """从单次读取的覆盖层快照生成响应，避免关闭 autoflush 时读回旧值。"""
    builtin_content = expert.system_prompt
    if not builtin_content:
        # 启动期已经校验，这里仍 fail-closed，避免运行中删文件后发空人格请求。
        raise AppError(ErrorCode.INTERNAL, "专家内置提示词不可用")
    override = overrides.get(expert.expert_id)
    # 数据库可能被人工误改或由旧版本写入；读取运行时覆盖层时也必须 fail-closed。
    content = _normalize_content(override) if override else builtin_content
    return ExpertPromptDocument(
        expert=expert,
        content=content,
        builtin_content=builtin_content,
        revision=_revision(content),
        overridden=bool(override),
    )


def get_effective_expert_prompt(db: Session, expert: ExpertDef) -> str:
    """供运行时装配专家段；无覆盖时使用内置提示词。"""
    if not expert.prompt_file:
        return ""
    return read_expert_prompt_document(db, expert.expert_id).content


def list_expert_prompt_metadata(db: Session) -> list[dict[str, object]]:
    """返回技能页所需专家目录，不在列表接口返回提示词正文。"""
    overrides = _read_prompt_overrides(db)
    return [
        {
            "id": expert.expert_id,
            "name": expert.name,
            "description": expert.description,
            "badge": expert.badge,
            "prompt_available": bool(expert.prompt_file),
            "overridden": expert.expert_id in overrides,
        }
        for expert in EXPERTS
    ]


def update_expert_prompt_document(
    db: Session,
    expert_id: object,
    content: str,
    expected_revision: str,
    *,
    updated_by: str,
) -> ExpertPromptDocument:
    """保存专家覆盖层；相同于内置基线时自动清除覆盖并恢复发布版本。"""
    expert = _require_prompt_expert(expert_id)
    normalized = _normalize_content(content)
    # 不存在的行无法加锁：先幂等创建，再锁住整张专家映射至调用者提交/回滚。
    # 并发首次写入会等待唯一键冲突解决；不同专家的更新也不会丢失彼此的条目。
    db.execute(
        insert(Setting).values(key=EXPERT_PROMPT_OVERRIDES_KEY, value={})
        .on_conflict_do_nothing(index_elements=[Setting.key])
    )
    row = (
        db.query(Setting).filter(Setting.key == EXPERT_PROMPT_OVERRIDES_KEY)
        .populate_existing().with_for_update().one()
    )
    overrides = _decode_prompt_overrides(row.value)
    current = _prompt_document(expert, overrides)
    if expected_revision != current.revision:
        raise AppError(ErrorCode.CONCURRENCY, "专家提示词已被其他修改覆盖，请刷新后再保存")
    if normalized == current.builtin_content:
        overrides.pop(current.expert.expert_id, None)
    else:
        overrides[current.expert.expert_id] = normalized
    row.value = overrides
    row.updated_by = updated_by
    db.flush()
    return _prompt_document(expert, overrides)
