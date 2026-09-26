"""Harness 偏好记忆（M3 阶段 3，MEM-4）。

偏好只作确认卡空槽预填与规划建议，**不可绕过 ID 溯源门禁**（MEM-4）。
写入时机：确认且任务已入队后写，表示上次确认配置，不表示评测成功。
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
    """确认入队后写偏好；同成员首次写入串行，避免辅助记录使任务回滚。"""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import Setting, User

    payload = {key: prefs.get(key) for key in _PREF_KEYS}
    # 沿用 session→user 顺序；NO KEY UPDATE 串行同成员写入，同时兼容任务外键的 KEY SHARE。
    db.query(User.id).filter(User.id == user_id).with_for_update(key_share=True).first()
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


def has_personal_context(db: Session, session_id: str) -> bool:
    """判断会话是否已使用个人记忆；标记不包含偏好或模型正文。"""
    from app.models import AuditLog

    return db.query(AuditLog.id).filter(
        AuditLog.action == "session_personal_context_used",
        AuditLog.target_type == "session",
        AuditLog.target_id == session_id,
    ).first() is not None


def _lock_private_session(db: Session, session_id: str, user_id: str):
    """与共享切换持有同一会话行锁，锁内复验本人、私有范围及成员状态。"""
    from app.models import Session as ChatSession
    from app.models import User

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.deleted_at.is_(None),
    ).populate_existing().with_for_update().first()
    if session is None or session.visibility != "private" or session.user_id != user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.disabled:
        return None
    return session


def _mark_personal_context_used(db: Session, session_id: str, user_id: str, source: str) -> None:
    """调用方持有会话锁；同事务尚未 flush 的标记也要去重，不记录个人正文。"""
    from app.models import AuditLog

    if any(isinstance(row, AuditLog) and row.action == "session_personal_context_used"
           and row.target_type == "session" and row.target_id == session_id for row in db.new):
        return
    if not has_personal_context(db, session_id):
        db.add(AuditLog(user_id=user_id, action="session_personal_context_used", target_type="session",
                        target_id=session_id, detail={"source": source}))


def prepare_private_memories(db: Session, session_id: str, user_id: str, query: str) -> list[dict]:
    """逐请求召回本人及当前工作区资料；使用标记提交成功后调用方才可注入模型。"""
    from .personal import recall_personal_memories

    session = _lock_private_session(db, session_id, user_id)
    if session is None:
        return []
    memories = recall_personal_memories(db, user_id, session.workspace_id, query)
    if memories:
        _mark_personal_context_used(db, session_id, user_id, "personal_memories")
    return memories


def prepare_private_prefs(db: Session, session_id: str, user_id: str) -> dict:
    """逐请求复验本人私有偏好并登记使用标记；调用者必须先提交再注入。

    与共享切换持有相同会话行锁，避免请求头、回复或后续摘要随共享泄露。
    取消或模型失败也保留标记，因为请求可能已发给模型。不得用于子运行。
    """
    from app.models import Dataset, GoldQa, KnowledgeBase, ProtocolProfile

    if _lock_private_session(db, session_id, user_id) is None:
        return {}
    raw = read_prefs(db, user_id)
    prefs = {}
    kind = raw.get("last_kind")
    if isinstance(kind, str) and kind in {"benchmark", "rag", "testcase", "stress"}:
        prefs["last_kind"] = kind
    if isinstance(raw.get("last_with_stress"), bool):
        prefs["last_with_stress"] = raw["last_with_stress"]
    # 这些资产沿用平台全员同权目录；created_by 是审计字段，不是使用 ACL。
    profile_ids = raw.get("last_profile_ids")
    if isinstance(profile_ids, list):
        # 评测最多选择五个模型；脏历史不放大查询数，过长 ID 不进入提示词。
        ids = list(dict.fromkeys(
            item for item in profile_ids[:5]
            if isinstance(item, str) and 0 < len(item) <= 128 and db.get(ProtocolProfile, item) is not None
        ))
        if ids:
            prefs["last_profile_ids"] = ids
    for key, model in (("last_dataset_id", Dataset), ("last_kb_id", KnowledgeBase)):
        value = raw.get(key)
        if isinstance(value, str) and 0 < len(value) <= 128 and db.get(model, value) is not None:
            prefs[key] = value
    gold_id = raw.get("last_gold_qa_id")
    if isinstance(gold_id, str) and 0 < len(gold_id) <= 128 and "last_kb_id" in prefs:
        gold = db.get(GoldQa, gold_id)
        if gold is not None and gold.kb_id == prefs["last_kb_id"]:
            prefs["last_gold_qa_id"] = gold_id
    if prefs:
        _mark_personal_context_used(db, session_id, user_id, "confirmed_task_preferences")
    return prefs
