"""Harness 偏好记忆（M3 阶段 3，MEM-4）。

偏好只作确认卡空槽预填与规划建议，**不可绕过 ID 溯源门禁**（MEM-4）。
写入时机：仅 ``confirm_ack.ok=true`` 且任务已入队后写（API.md §3.4）。
存储：``settings`` 键 ``agent_prefs:{user_id}``（跨会话单偏好，只读对外，
无 PUT 端点）。闲聊、取消确认、``/compact`` 不写。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...time_utils import iso_utc

# API.md §3.4 允许写出的字段；其它键一律丢弃。
_PREF_KEYS = (
    "last_kind",
    "last_profile_ids",
    "last_dataset_id",
    "last_kb_id",
    "last_gold_qa_id",
    "last_with_stress",
)


def _prefs_key(user_id: str) -> str:
    """偏好存储键（settings 表）。"""
    return f"agent_prefs:{user_id}"


def empty_prefs() -> dict:
    """无记录时的对外投影（各字段 null）。"""
    return {
        "last_kind": None,
        "last_profile_ids": None,
        "last_dataset_id": None,
        "last_kb_id": None,
        "last_gold_qa_id": None,
        "last_with_stress": None,
        "updated_at": None,
    }


def prefs_from_task_spec(spec: dict) -> dict:
    """从已入队 TaskSpec 抽取允许写入的偏好字段。"""
    profile_ids = spec.get("profile_ids")
    if not isinstance(profile_ids, list):
        profile_ids = []
    kind = spec.get("kind")
    return {
        "last_kind": kind if isinstance(kind, str) and kind else None,
        "last_profile_ids": [str(item) for item in profile_ids if item],
        "last_dataset_id": spec.get("dataset_id") or None,
        "last_kb_id": spec.get("kb_id") or None,
        "last_gold_qa_id": spec.get("gold_qa_id") or None,
        "last_with_stress": bool(spec.get("with_stress")),
    }


def write_prefs(db: Session, user_id: str, prefs: dict, *, commit: bool = True) -> None:
    """写偏好（仅 confirm_ack.ok=true 入队后调用，MEM-4）。"""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import Setting

    payload = {key: prefs.get(key) for key in _PREF_KEYS}
    row = db.query(Setting).filter(Setting.key == _prefs_key(user_id)).first()
    if row is None:
        db.add(Setting(key=_prefs_key(user_id), value=payload))
    else:
        row.value = payload
        flag_modified(row, "value")
    if commit:
        db.commit()


def read_prefs(db: Session, user_id: str) -> dict:
    """读偏好原始 dict，供规划建议；不可绕过 ID 溯源门禁。"""
    from app.models import Setting

    row = db.query(Setting).filter(Setting.key == _prefs_key(user_id)).first()
    if row is None or not isinstance(row.value, dict):
        return {}
    return dict(row.value)


def public_prefs(db: Session, user_id: str) -> dict:
    """``GET /api/agent/prefs`` 对外投影（无记录时各字段 null）。"""
    from app.models import Setting

    payload = empty_prefs()
    row = db.query(Setting).filter(Setting.key == _prefs_key(user_id)).first()
    if row is None or not isinstance(row.value, dict):
        return payload
    raw = row.value
    kind = raw.get("last_kind")
    payload["last_kind"] = kind if isinstance(kind, str) and kind else None
    profile_ids = raw.get("last_profile_ids")
    if isinstance(profile_ids, list):
        payload["last_profile_ids"] = [str(item) for item in profile_ids if item]
    else:
        payload["last_profile_ids"] = None
    for key in ("last_dataset_id", "last_kb_id", "last_gold_qa_id"):
        value = raw.get(key)
        payload[key] = value if isinstance(value, str) and value else None
    if "last_with_stress" in raw:
        payload["last_with_stress"] = bool(raw.get("last_with_stress"))
    payload["updated_at"] = iso_utc(row.updated_at) if row.updated_at else None
    return payload
