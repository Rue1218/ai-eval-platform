"""自定义斜杠存储（API.md §3.4 M2 CRUD）。

系统命令不走本存储，只作重名拒绝。按用户写入 ``settings`` 键
``slash_commands:{user_id}``，避免新增表；改删仅创建者本人。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.errors import AppError, ErrorCode

# 与前端 slashRegistry + 路由控制斜杠对齐；禁止自定义命令抢占系统名。
SYSTEM_SLASH_NAMES: frozenset[str] = frozenset(
    {
        "help",
        "stop",
        "compact",
        "cancel",
        "stress",
        "benchmark",
        "testcase",
        "rag",
        "eval",
        "new",
        "share",
        "prefs",
        "datasets",
        "kb",
        "tasks",
    }
)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_FORBIDDEN_TEMPLATE = ("跳过确认", "改系统提示词")


def _store_key(user_id: str) -> str:
    """当前用户的自定义命令存储键。"""
    return f"slash_commands:{user_id}"


def _iso(value: datetime | None = None) -> str:
    """UTC ISO 字符串。"""
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _load_items(db: Session, user_id: str) -> tuple[object, list[dict]]:
    """读取用户命令列表；无记录时返回 (None, [])。"""
    from app.models import Setting

    row = db.query(Setting).filter(Setting.key == _store_key(user_id)).first()
    if row is None or not isinstance(row.value, dict):
        return row, []
    raw = row.value.get("items")
    if not isinstance(raw, list):
        return row, []
    return row, [dict(item) for item in raw if isinstance(item, dict)]


def _save_items(db: Session, user_id: str, row: object, items: list[dict]) -> None:
    """写回命令列表。"""
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import Setting

    payload = {"items": items}
    if row is None:
        db.add(Setting(key=_store_key(user_id), value=payload))
    else:
        row.value = payload
        flag_modified(row, "value")
    db.commit()


def list_commands(db: Session, user_id: str) -> dict:
    """列出当前用户的自定义命令。"""
    _, items = _load_items(db, user_id)
    return {"items": items, "total": len(items)}


def create_command(db: Session, user_id: str, body: dict) -> dict:
    """创建自定义命令；校验 name/template，禁止与系统命令重名。"""
    name = str(body.get("name") or "").strip()
    hint = str(body.get("hint") or "").strip()
    template = str(body.get("template") or "")
    if not _NAME_RE.match(name):
        raise AppError(ErrorCode.VALIDATION, "命令名须为字母开头的 1–32 位英文、数字、下划线或短横线")
    if name.lower() in {item.lower() for item in SYSTEM_SLASH_NAMES}:
        raise AppError(ErrorCode.VALIDATION, "不能与系统命令重名")
    stripped = template.strip()
    if not stripped or len(template) > 2000:
        raise AppError(ErrorCode.VALIDATION, "模板须为 1–2000 字符")
    if stripped == "/bypass" or any(token in template for token in _FORBIDDEN_TEMPLATE):
        raise AppError(ErrorCode.VALIDATION, "模板不能跳过确认或改写系统提示词")
    if len(hint) > 128:
        raise AppError(ErrorCode.VALIDATION, "说明过长")
    row, items = _load_items(db, user_id)
    if any(str(item.get("name") or "").lower() == name.lower() for item in items):
        raise AppError(ErrorCode.VALIDATION, "命令名已存在")
    created = {
        "id": uuid4().hex,
        "name": name,
        "hint": hint,
        "template": template,
        "created_by": user_id,
        "created_at": _iso(),
    }
    items.append(created)
    _save_items(db, user_id, row, items)
    return created


def delete_command(db: Session, user_id: str, command_id: str) -> None:
    """删除本人创建的命令；他人命令视为未找到，避免泄漏。"""
    row, items = _load_items(db, user_id)
    target = next((item for item in items if str(item.get("id") or "") == command_id), None)
    if target is None:
        raise AppError(ErrorCode.NOT_FOUND, "命令不存在")
    if str(target.get("created_by") or "") != user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "只能删除自己创建的命令", status_code=403)
    remain = [item for item in items if str(item.get("id") or "") != command_id]
    _save_items(db, user_id, row, remain)
