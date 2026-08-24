"""Harness 偏好记忆（M3 阶段 3，MEM-4）。

偏好只作 M4 ``plan.py`` 规划建议，**不可绕过 ID 溯源门禁**（MEM-4）。
写入时机：仅 ``confirm_ack.ok=true`` 且任务已入队后写（API.md §3.4）。
存储：``settings`` 键 ``agent_prefs:{user_id}``（跨会话单偏好，只读对外，
无 PUT 端点）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def _prefs_key(user_id: str) -> str:
    """偏好存储键（settings 表）。"""
    return f"agent_prefs:{user_id}"


def write_prefs(db: Session, user_id: str, prefs: dict) -> None:
    """写偏好（仅 confirm_ack.ok=true 入队后调用，MEM-4）。"""
    from app.models import Setting

    row = db.query(Setting).filter(Setting.key == _prefs_key(user_id)).first()
    if row is None:
        db.add(Setting(key=_prefs_key(user_id), value=dict(prefs)))
    else:
        row.value = dict(prefs)
    db.commit()


def read_prefs(db: Session, user_id: str) -> dict:
    """读偏好，供 M4 plan.py 规划建议；不可绕过 ID 溯源门禁。"""
    from app.models import Setting

    row = db.query(Setting).filter(Setting.key == _prefs_key(user_id)).first()
    if row is None or not isinstance(row.value, dict):
        return {}
    return dict(row.value)
