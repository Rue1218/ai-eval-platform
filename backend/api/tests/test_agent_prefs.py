"""跨会话下单偏好（API.md §3.4 / MEM-4）。"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.harness.memory.preference import (
    empty_prefs,
    prefs_from_task_spec,
    public_prefs,
    write_prefs,
)


def test_prefs_from_task_spec_keeps_allowed_fields_only() -> None:
    """入队成功只抽取契约允许的偏好字段。"""
    prefs = prefs_from_task_spec(
        {
            "kind": "rag",
            "profile_ids": ["p1", ""],
            "dataset_id": None,
            "kb_id": "kb-1",
            "gold_qa_id": "gold-1",
            "with_stress": True,
            "run": {"sample_size": 10},
        }
    )
    assert prefs == {
        "last_kind": "rag",
        "last_profile_ids": ["p1"],
        "last_dataset_id": None,
        "last_kb_id": "kb-1",
        "last_gold_qa_id": "gold-1",
        "last_with_stress": True,
    }


def test_public_prefs_empty_when_missing() -> None:
    """无记录时各字段为 null，不编造上次选择。"""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert public_prefs(db, "u1") == empty_prefs()


def test_public_prefs_projects_updated_at() -> None:
    """有记录时透出 settings.updated_at。"""
    row = MagicMock()
    row.value = {
        "last_kind": "benchmark",
        "last_profile_ids": ["p1"],
        "last_dataset_id": "d1",
        "last_with_stress": False,
    }
    row.updated_at = datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row
    payload = public_prefs(db, "u1")
    assert payload["last_kind"] == "benchmark"
    assert payload["last_profile_ids"] == ["p1"]
    assert payload["updated_at"] == "2026-08-26T01:02:03Z"


def test_write_prefs_can_skip_commit() -> None:
    """同事务写入时不得自行 commit。"""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    write_prefs(db, "u1", {"last_kind": "benchmark"}, commit=False)
    db.add.assert_called_once()
    db.commit.assert_not_called()
