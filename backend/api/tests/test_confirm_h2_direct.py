"""H2 批次 2：确认卡 WS 直连事务测试（发卡行锁 + 回执全路径）。

覆盖：open_pending_confirm（发卡：行锁写 pending_confirm + author_id；已有卡
CONCURRENCY；stress/未知 kind fail-closed）、handle_confirm_ack（确认入队
同一事务清卡；重复确认 CONCURRENCY；拒绝不入队清卡；非 owner 拒绝；
uq 命中语义由 enqueue 桥 IntegrityError 捕获链路覆盖）。全部为桩 DB，
不依赖真实 PG（行锁 SQL 由 lock_pending_confirm 执行并分发断言）。
"""

from __future__ import annotations

import json

import pytest

from app.errors import AppError, ErrorCode
from app.harness.orchestration.confirm import handle_confirm_ack, open_pending_confirm


class _Result:
    """模拟 db.execute(...).first() 的查询结果。"""

    def __init__(self, row: object | None = None) -> None:
        self._row = row

    def first(self):
        return self._row


class _Row:
    def __init__(self, pending, author_id) -> None:
        self.pending_confirm = pending
        self.pending_confirm_author_id = author_id


class _FakeDb:
    """行锁事务桩：按 SQL 分发 execute，记录 commit/rollback。"""

    def __init__(self, pending=None, author_id=None) -> None:
        self.pending = pending
        self.author_id = author_id
        self.executed: list[tuple[str, dict]] = []
        self.committed = 0
        self.rolled_back = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, dict(params or {})))
        if sql.startswith("SELECT"):
            return _Result(_Row(self.pending, self.author_id))
        return _Result()

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def _benchmark_spec(**overrides) -> dict:
    spec = {
        "kind": "benchmark",
        "profile_ids": [],
        "dataset_id": "d-1",
        "with_stress": False,
        "run": {"sample_size": 10},
    }
    spec.update(overrides)
    return spec


# ─── 1. 发卡（open_pending_confirm）───


def test_open_pending_confirm_writes_card_under_row_lock() -> None:
    db = _FakeDb(pending=None, author_id=None)
    card = open_pending_confirm(db, "s-1", "u-1", _benchmark_spec())
    assert card["kind"] == "benchmark"
    assert card["confirm_id"]
    assert card["profile_ids"] == []  # 平铺 TaskSpec + confirm_id（handle 基座兼容）
    # 行锁 SELECT 后同一事务写卡
    selects = [sql for sql, _ in db.executed if sql.startswith("SELECT")]
    updates = [params for sql, params in db.executed if "pending_confirm = :card" in sql]
    assert selects and updates
    written = json.loads(updates[-1]["card"])
    assert written["confirm_id"] == card["confirm_id"]
    assert written["kind"] == "benchmark"
    assert updates[-1]["user_id"] == "u-1"
    assert db.committed == 1


def test_open_pending_confirm_rejects_existing_card() -> None:
    db = _FakeDb(pending={"confirm_id": "c-1", "kind": "benchmark"}, author_id="u-1")
    with pytest.raises(AppError) as exc:
        open_pending_confirm(db, "s-1", "u-2", _benchmark_spec())
    assert exc.value.code == ErrorCode.CONCURRENCY
    assert db.committed == 0


def test_open_pending_confirm_rejects_stress_and_unknown_kind() -> None:
    db = _FakeDb(pending=None, author_id=None)
    with pytest.raises(AppError) as exc:
        open_pending_confirm(db, "s-1", "u-1", {"kind": "stress"})
    assert exc.value.code == ErrorCode.VALIDATION
    with pytest.raises(AppError) as exc:
        open_pending_confirm(db, "s-1", "u-1", {"kind": "no-such-kind"})
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.committed == 0


def test_open_pending_confirm_drops_stale_assets() -> None:
    """发卡前过滤已删除资产引用（profile_ids 残留不落卡）。"""

    class _QueryDb(_FakeDb):
        def __init__(self) -> None:
            super().__init__(pending=None, author_id=None)
            self._existing = set()

        def query(self, _model):
            return self

        def filter(self, _expr):
            return self

        def all(self):
            return [(_id,) for _id in self._existing]

    db = _QueryDb()
    db._existing = {"p-1"}
    card = open_pending_confirm(
        db, "s-1", "u-1", _benchmark_spec(profile_ids=["p-1", "p-deleted"])
    )
    assert card["profile_ids"] == ["p-1"]  # 平铺卡：stale 引用已滤


# ─── 2. 回执（handle_confirm_ack）───


def _ack_db(card: dict | None = None) -> _FakeDb:
    return _FakeDb(pending=card, author_id="u-1")


def test_ack_ok_enqueues_and_clears_card_in_one_transaction(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_enqueue(db, session_id, user_id, kind, spec, *, parent_task_id=None, commit=True):
        calls.append((session_id, user_id, kind, spec, commit))
        return "task-9"

    monkeypatch.setattr("app.harness.orchestration.confirm.enqueue_long_task", fake_enqueue)
    monkeypatch.setattr("app.harness.orchestration.confirm.write_prefs", lambda *_a, **_k: None)
    card = {**_benchmark_spec(profile_ids=["p-1"]), "confirm_id": "c-1"}
    db = _ack_db(card)
    result = handle_confirm_ack(db, "s-1", "u-1", {"ok": True, "patch": {}})
    assert result.ok is True
    assert result.task_id == "task-9"
    expected_spec = {
        key: value
        for key, value in _benchmark_spec(profile_ids=["p-1"]).items()
        if key != "kind"
    }
    assert calls and calls[0][:4] == ("s-1", "u-1", "benchmark", expected_spec)
    assert calls[0][4] is False  # 入队 commit=False，与清卡同一次 commit
    assert db.committed >= 1
    assert not db.rolled_back


def test_ack_reject_clears_card_without_enqueue(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_enqueue(*_args, **_kwargs):
        calls.append(1)
        return "task-x"

    monkeypatch.setattr("app.harness.orchestration.confirm.enqueue_long_task", fake_enqueue)
    card = {**_benchmark_spec(), "confirm_id": "c-2"}
    db = _ack_db(card)
    result = handle_confirm_ack(db, "s-1", "u-1", {"ok": False})
    assert result.ok is False
    assert result.task_id is None
    assert calls == []  # 拒绝绝不入队
    assert db.committed >= 1


def test_ack_repeated_after_card_consumed_rejected() -> None:
    """卡已消费（重复确认）→ 拒绝（无待确认卡），绝不重复入队。"""
    db = _FakeDb(pending=None, author_id=None)  # 行锁读到无卡
    with pytest.raises(AppError) as exc:
        handle_confirm_ack(db, "s-1", "u-1", {"ok": True, "patch": {}})
    assert exc.value.code == ErrorCode.VALIDATION
    assert "无待确认卡" in exc.value.message


def test_ack_non_owner_rejected() -> None:
    card = {**_benchmark_spec(), "confirm_id": "c-3"}
    db = _ack_db(card)
    with pytest.raises(AppError) as exc:
        handle_confirm_ack(db, "s-1", "u-2", {"ok": True, "patch": {}})
    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_ack_confirmed_missing_profile_rejected(monkeypatch) -> None:
    """确认卡必填资产缺失（profile_ids 空）→ VALIDATION，不入队不绕过门禁。"""
    calls: list[tuple] = []

    def fake_enqueue(*_args, **_kwargs):
        calls.append(1)
        return "task-x"

    monkeypatch.setattr("app.harness.orchestration.confirm.enqueue_long_task", fake_enqueue)
    card = {**_benchmark_spec(profile_ids=[]), "confirm_id": "c-4"}
    db = _ack_db(card)
    with pytest.raises(AppError) as exc:
        handle_confirm_ack(db, "s-1", "u-1", {"ok": True, "patch": {}})
    assert exc.value.code == ErrorCode.VALIDATION
    assert calls == []
    assert db.rolled_back >= 1
