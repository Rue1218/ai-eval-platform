"""确认卡二次校验与回执事务回归测试。"""

from unittest.mock import MagicMock

import pytest

from app.errors import AppError, ErrorCode
from app.harness.orchestration.confirm import (
    _validate_confirmed,
    handle_confirm_ack,
)
from app.harness.security.auth import PendingConfirm


def _benchmark_spec(**overrides) -> dict:
    spec = {
        "kind": "benchmark",
        "profile_ids": ["p1"],
        "dataset_id": "d1",
        "run": {"sample_size": 100, "concurrency": 4, "timeout_s": 60},
        "with_stress": False,
    }
    spec.update(overrides)
    return spec


def test_validate_confirmed_accepts_dataset_id() -> None:
    """契约字段是 dataset_id，不得再读错误的 dataset。"""
    assert _validate_confirmed(_benchmark_spec()) == "benchmark"


def test_validate_confirmed_rejects_legacy_dataset_key() -> None:
    """只有 dataset 没有 dataset_id 的卡必须失败。"""
    spec = _benchmark_spec()
    spec.pop("dataset_id")
    spec["dataset"] = "d1"
    with pytest.raises(AppError) as error:
        _validate_confirmed(spec)
    assert error.value.code == ErrorCode.VALIDATION
    assert "数据集" in error.value.message


def test_validate_confirmed_rag_does_not_require_dataset() -> None:
    """rag 按 kb_id + gold_qa_id 校验，不得误杀为缺少数据集。"""
    assert (
        _validate_confirmed(
            {
                "kind": "rag",
                "kb_id": "kb-1",
                "gold_qa_id": "gold-1",
                "run": {"sample_size": 10, "k": 5},
            }
        )
        == "rag"
    )


def test_validate_confirmed_testcase_requires_case_source() -> None:
    with pytest.raises(AppError) as error:
        _validate_confirmed({"kind": "testcase"})
    assert error.value.code == ErrorCode.VALIDATION
    assert "用例" in error.value.message


def test_validate_confirmed_rejects_kind_stress() -> None:
    with pytest.raises(AppError) as error:
        _validate_confirmed(
            {
                "kind": "stress",
                "parent_task_id": "parent",
                "stress": {"env": "test", "qps": 10, "duration_s": 60},
            }
        )
    assert "先评后压" in error.value.message


def test_handle_confirm_ack_passes_commit_false(monkeypatch) -> None:
    """入队不得在清卡前进内部 commit，避免半提交。"""
    seen: dict = {}

    monkeypatch.setattr(
        "app.harness.orchestration.confirm.lock_pending_confirm",
        lambda db, session_id: PendingConfirm(pending=_benchmark_spec(), author_id="u1"),
    )

    def fake_enqueue(*_args, **kwargs):
        seen.update(kwargs)
        return "task-new"

    monkeypatch.setattr(
        "app.harness.orchestration.confirm.enqueue_long_task",
        fake_enqueue,
    )
    db = MagicMock()
    result = handle_confirm_ack(db, "s1", "u1", {"ok": True, "patch": {}})
    assert result.ok is True
    assert result.task_id == "task-new"
    assert seen.get("commit") is False
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_handle_confirm_ack_invalid_keeps_card(monkeypatch) -> None:
    """二次校验失败必须 rollback，不得清卡、不得入队。"""
    monkeypatch.setattr(
        "app.harness.orchestration.confirm.lock_pending_confirm",
        lambda db, session_id: PendingConfirm(
            pending={"kind": "benchmark", "dataset": "d1"},
            author_id="u1",
        ),
    )
    enqueue = MagicMock()
    monkeypatch.setattr(
        "app.harness.orchestration.confirm.enqueue_long_task",
        enqueue,
    )
    db = MagicMock()
    with pytest.raises(AppError) as error:
        handle_confirm_ack(db, "s1", "u1", {"ok": True})
    assert error.value.code == ErrorCode.VALIDATION
    enqueue.assert_not_called()
    db.rollback.assert_called()
    db.commit.assert_not_called()
