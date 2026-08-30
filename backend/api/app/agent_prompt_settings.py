"""Agent 专属补充提示词的受控持久化。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .errors import AppError, ErrorCode
from .harness.prompts.system import assert_no_secret_leak
from .models import Setting

AGENT_PROMPT_OVERLAYS_KEY = "agent_prompt_overlays"
MAX_AGENT_PROMPT_OVERLAY_LENGTH = 12_000


def _read_prompt_overlays(db: Session) -> dict[str, str]:
    """读取协议档维度的补充提示词映射，并隔离损坏配置。"""
    row = db.query(Setting).filter(Setting.key == AGENT_PROMPT_OVERLAYS_KEY).first()
    if not row or not row.value:
        return {}
    try:
        payload = json.loads(row.value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(profile_id): str(overlay) for profile_id, overlay in payload.items() if isinstance(overlay, str)}


def get_agent_prompt_overlay(db: Session, profile_id: str | None) -> str:
    """读取当前 Agent 协议档补充提示词，不允许旧设置替换核心策略。"""
    overlays = _read_prompt_overlays(db)
    if profile_id is not None and str(profile_id) in overlays:
        return overlays[str(profile_id)]
    return ""


def update_agent_prompt_overlay(db: Session, profile_id: str, overlay: str, *, updated_by: str) -> str:
    """保存协议档专属补充提示词，核心系统提示词不在此处可写。"""
    normalized = overlay.replace("\r\n", "\n").strip()
    if len(normalized) > MAX_AGENT_PROMPT_OVERLAY_LENGTH:
        raise AppError(ErrorCode.VALIDATION, f"补充提示词不能超过 {MAX_AGENT_PROMPT_OVERLAY_LENGTH} 个字符")
    assert_no_secret_leak(normalized)

    overlays = _read_prompt_overlays(db)
    if normalized:
        overlays[str(profile_id)] = normalized
    else:
        overlays.pop(str(profile_id), None)

    serialized = json.dumps(overlays, ensure_ascii=False, separators=(",", ":"))
    row = db.query(Setting).filter(Setting.key == AGENT_PROMPT_OVERLAYS_KEY).first()
    if row:
        row.value = serialized
        row.updated_by = updated_by
    else:
        db.add(Setting(key=AGENT_PROMPT_OVERLAYS_KEY, value=serialized, updated_by=updated_by))
    return normalized
