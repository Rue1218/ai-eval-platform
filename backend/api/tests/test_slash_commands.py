"""自定义斜杠 M2 CRUD（API.md §3.4）。"""

from unittest.mock import MagicMock

import pytest

from app.errors import AppError, ErrorCode
from app.harness.memory.slash_store import create_command, delete_command, list_commands


def _db_with_items(items: list[dict] | None = None, *, existing: bool = True) -> MagicMock:
    db = MagicMock()
    if existing:
        row = MagicMock()
        row.value = {"items": list(items or [])}
        db.query.return_value.filter.return_value.first.return_value = row
    else:
        db.query.return_value.filter.return_value.first.return_value = None
    return db


def test_create_and_list_custom_command() -> None:
    """合法命令可保存，列表按当前用户返回。"""
    db = _db_with_items(existing=False)
    created = create_command(
        db,
        "u1",
        {"name": "smoke", "hint": "冒烟评测", "template": "帮我下一单基准评测，抽样 20 条"},
    )
    assert created["name"] == "smoke"
    assert created["created_by"] == "u1"
    db.add.assert_called_once()
    db.commit.assert_called_once()
    listed = list_commands(_db_with_items([created]), "u1")
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "smoke"


def test_create_rejects_system_name_and_bypass_template() -> None:
    """系统命令名与绕过确认的模板必须拒绝。"""
    db = _db_with_items([])
    with pytest.raises(AppError) as error:
        create_command(db, "u1", {"name": "help", "hint": "", "template": "查看帮助"})
    assert error.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError) as error:
        create_command(db, "u1", {"name": "smoke", "hint": "", "template": "/bypass"})
    assert error.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError) as error:
        create_command(db, "u1", {"name": "中文", "hint": "", "template": "评测"})
    assert error.value.code == ErrorCode.VALIDATION


def test_create_rejects_duplicate_name() -> None:
    db = _db_with_items(
        [{"id": "1", "name": "smoke", "hint": "", "template": "x", "created_by": "u1"}]
    )
    with pytest.raises(AppError) as error:
        create_command(db, "u1", {"name": "Smoke", "hint": "", "template": "再来一单"})
    assert error.value.code == ErrorCode.VALIDATION


def test_delete_own_command() -> None:
    db = _db_with_items(
        [{"id": "cmd-1", "name": "smoke", "hint": "", "template": "x", "created_by": "u1"}]
    )
    delete_command(db, "u1", "cmd-1")
    db.commit.assert_called()
    row = db.query.return_value.filter.return_value.first.return_value
    assert row.value["items"] == []


def test_delete_missing_is_not_found() -> None:
    db = _db_with_items([])
    with pytest.raises(AppError) as error:
        delete_command(db, "u1", "missing")
    assert error.value.code == ErrorCode.NOT_FOUND
