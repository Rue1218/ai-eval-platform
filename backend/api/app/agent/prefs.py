"""跨会话下单偏好（HAR-PLAN-06 / 开发说明书 §8.2）。

存储键 ``agent_prefs:{user_id}``；只读于规划，仅 ack 成功且任务入队后写入。
不得用偏好覆盖人设或绕过白名单。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting
from .log import agent_trace

_PREFS_KEYS = (
    "last_kind",
    "last_profile_ids",
    "last_dataset_id",
    "last_kb_id",
    "last_gold_qa_id",
    "last_with_stress",
    "updated_at",
)


def prefs_key(user_id: str) -> str:
    """settings 表中的偏好键。"""
    return f"agent_prefs:{user_id}"


def empty_prefs() -> dict[str, Any]:
    """无记录时的只读空偏好。"""
    return {
        "last_kind": None,
        "last_profile_ids": None,
        "last_dataset_id": None,
        "last_kb_id": None,
        "last_gold_qa_id": None,
        "last_with_stress": None,
        "updated_at": None,
    }


def load_prefs(db: Session, user_id: str) -> dict[str, Any]:
    """读取当前成员偏好；无记录时各字段为 null。"""
    row = db.query(Setting).filter(Setting.key == prefs_key(user_id)).first()
    if not row or not isinstance(row.value, dict):
        return empty_prefs()
    out = empty_prefs()
    for key in _PREFS_KEYS:
        if key in row.value:
            out[key] = row.value.get(key)
    return out


def save_prefs_from_spec(db: Session, user_id: str, spec: dict[str, Any]) -> None:
    """ack 成功入队后写入偏好。取消确认、闲聊、compact 不得调用。"""
    try:
        kind = spec.get("kind")
        if kind not in {"benchmark", "rag", "testcase"}:
            return
        payload = {
            "last_kind": kind,
            "last_profile_ids": list(spec.get("profile_ids") or []) or None,
            "last_dataset_id": spec.get("dataset_id"),
            "last_kb_id": spec.get("kb_id"),
            "last_gold_qa_id": spec.get("gold_qa_id"),
            "last_with_stress": bool(spec.get("with_stress")),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        key = prefs_key(user_id)
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = payload
            row.updated_by = user_id
        else:
            db.add(Setting(key=key, value=payload, updated_by=user_id))
        db.commit()
        agent_trace(f"已写入偏好 user={user_id[:8]} kind={kind}")
    except Exception as exc:  # noqa: BLE001 — 偏好失败不得阻断入队
        agent_trace(f"写入偏好内部异常 type={type(exc).__name__}")
        db.rollback()
