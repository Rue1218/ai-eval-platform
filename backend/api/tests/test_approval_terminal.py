"""审批终态单测（dsh 改进 #3，API.md §4.3 V1.73：approval_terminal）。

覆盖：TTL 幂等判龄（不依赖扫描进程存活性）、过期 ack 拒绝且不 resume、
/stop 放弃悬挂审批卡 → cancelled、后台扫描清过期卡幂等不重复广播。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.errors import AppError, ErrorCode
from app.routers import ws

_EMIT = "_emit_persistent"


class _Row:
    def __init__(self, session_id: str = "s-1") -> None:
        self.id = session_id
        self.user_id = "u-1"
        self.pending_confirm: dict | None = None
        self.pending_confirm_author_id: str | None = None
        self.compact_summary = None


class _FakeDb:
    """与 test_hybrid_h5_hitl 同构的卡行锁桩。"""

    def __init__(self, rows: list[_Row] | None = None) -> None:
        self.rows = rows or [_Row()]
        self.committed = 0
        self.rolled_back = 0
        self._all_calls = 0

    def query(self, _model=None):
        return self

    def filter(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.rows[0]

    def all(self):
        self._all_calls += 1
        return self.rows

    def execute(self, statement, params=None):
        sql = str(getattr(statement, "text", statement))
        if sql.startswith("UPDATE sessions SET pending_confirm = NULL"):
            self.rows[0].pending_confirm = None
            self.rows[0].pending_confirm_author_id = None
        return self

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        pass


def _card(confirm_type: str = "tool_approval", *, created_at: datetime, approval_id: str = "call-1") -> dict:
    return {
        "id": approval_id,
        "call_id": approval_id,
        "name": "bash",
        "command": "rm -rf /tmp/x",
        "meta": {
            "schema_version": 2,
            "confirm_type": confirm_type,
            "thread_id": "t-1",
            "owner_id": "u-1",
            "resume_nonce": "nonce-1",
            "created_at": created_at.isoformat(),
        },
    }


def _now() -> datetime:
    return datetime.now(UTC)


def test_approval_overdue_uses_card_created_at_idempotently(monkeypatch) -> None:
    """幂等判龄：同一张卡在任何进程/时刻得出同一过期结论；无时间戳/TTL 关闭不判龄。"""
    monkeypatch.setattr(settings, "agent_approval_ttl_seconds", 3600)
    fresh = _card(created_at=_now())
    assert ws._approval_overdue(fresh) is False
    stale = _card(created_at=_now() - timedelta(seconds=3601))
    assert ws._approval_overdue(stale) is True
    # 恰好未到 TTL 不算过期
    edge = _card(created_at=_now() - timedelta(seconds=3599))
    assert ws._approval_overdue(edge) is False
    # 缺失 created_at（旧卡）不判龄（不误杀）
    no_ts = _card(created_at=_now())
    del no_ts["meta"]["created_at"]
    assert ws._approval_overdue(no_ts) is False
    # TTL ≤ 0 表示不启用过期
    monkeypatch.setattr(settings, "agent_approval_ttl_seconds", 0)
    assert ws._approval_overdue(stale) is False


@pytest.mark.asyncio
async def test_approval_ack_expired_clears_card_no_resume(monkeypatch) -> None:
    """过期卡 ack：清卡 + approval_terminal(expired) + VALIDATION；绝不 resume。"""
    started: list = []
    monkeypatch.setattr(ws, "_start_approval_resume", lambda *_a, **_k: started.append(1) or object())
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, _EMIT, fake_emit)
    db = _FakeDb()
    db.rows[0].pending_confirm = _card(created_at=_now() - timedelta(seconds=7200))
    db.rows[0].pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        await ws._handle_approval_ack(
            db, object(), ws._ConnectionState(), "s-1", "u-1",
            {"action": "approve", "id": "call-1"},
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.rows[0].pending_confirm is None  # 过期卡已清，ack 消费失败
    assert started == []  # 不 resume
    terminal = [e for e in emitted if e[0] == "approval_terminal"]
    assert terminal and terminal[-1][1] == {
        "approval_id": "call-1",
        "outcome": "expired",
        "reason": "审批超时已失效",
    }


@pytest.mark.asyncio
async def test_stop_cancels_hanging_approval_and_completes(monkeypatch) -> None:
    """/stop 无活跃回合且悬挂本成员审批卡 → cancelled 终态 + completed cancelled。"""
    emitted: list[tuple[str, dict]] = []
    completed: list[tuple[str, str]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    async def fake_completed(_db, _ws, _st, _sid, **kw):
        completed.append((kw.get("finish_reason") or "", kw.get("turn_id") or ""))
        return None

    monkeypatch.setattr(ws, _EMIT, fake_emit)
    monkeypatch.setattr(ws, "_emit_turn_completed", fake_completed)
    monkeypatch.setattr(ws, "_SESSION_TURNS", {})  # 无活跃回合
    db = _FakeDb()
    db.rows[0].pending_confirm = _card(created_at=_now())
    db.rows[0].pending_confirm_author_id = "u-1"
    await ws._handle_stop(db, object(), ws._ConnectionState(), "s-1", None, user_id="u-1")
    assert db.rows[0].pending_confirm is None
    terminal = [e for e in emitted if e[0] == "approval_terminal"]
    assert terminal and terminal[-1][1]["outcome"] == "cancelled"
    assert completed and completed[-1][0] == "cancelled"


@pytest.mark.asyncio
async def test_stop_keeps_others_or_non_approval_cards(monkeypatch) -> None:
    """/stop 不越权清他人审批卡、不动 confirm/clarify 卡。"""

    async def fake_completed(*_a, **_k):
        return None

    monkeypatch.setattr(ws, "_emit_turn_completed", fake_completed)

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        return True

    monkeypatch.setattr(ws, _EMIT, fake_emit)
    # 他人审批卡
    db = _FakeDb()
    db.rows[0].pending_confirm = _card(created_at=_now())
    db.rows[0].pending_confirm_author_id = "u-2"
    await ws._handle_stop(db, object(), ws._ConnectionState(), "s-1", None, user_id="u-1")
    assert db.rows[0].pending_confirm is not None
    # 任务确认卡（不属审批 TTL 范围）
    db2 = _FakeDb()
    db2.rows[0].pending_confirm = _card(
        confirm_type="task_confirm", created_at=_now(), approval_id="spec-1"
    )
    db2.rows[0].pending_confirm_author_id = "u-1"
    await ws._handle_stop(db2, object(), ws._ConnectionState(), "s-1", None, user_id="u-1")
    assert db2.rows[0].pending_confirm is not None


@pytest.mark.asyncio
async def test_stop_terminal_emit_failure_still_completes(monkeypatch) -> None:
    """/stop 的终态广播失败（DB/网络瞬时故障）时 completed 仍必发（每轮恰一终态铁律）。"""
    completed: list[str] = []

    async def fake_completed(_db, _ws, _st, _sid, **kw):
        completed.append(kw.get("finish_reason") or "")
        return None

    async def fake_emit_boom(*_a, **_k):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit_boom)
    monkeypatch.setattr(ws, "_emit_turn_completed", fake_completed)
    monkeypatch.setattr(ws, "_SESSION_TURNS", {})
    db = _FakeDb()
    db.rows[0].pending_confirm = _card(created_at=_now())
    db.rows[0].pending_confirm_author_id = "u-1"
    # 不应抛出：终态广播失败被吞掉，/stop 正常收尾
    await ws._handle_stop(db, object(), ws._ConnectionState(), "s-1", None, user_id="u-1")
    assert db.rows[0].pending_confirm is None  # 卡已清（清卡先行）
    assert completed == ["cancelled"]


@pytest.mark.asyncio
async def test_expiry_scan_clears_only_overdue_and_is_idempotent(monkeypatch) -> None:
    """后台扫描：只清过期审批卡并广播 expired；新鲜/非审批卡不动；重复扫描幂等。"""
    expired_row = _Row("s-overdue")
    expired_row.pending_confirm = _card(created_at=_now() - timedelta(seconds=7200))
    expired_row.pending_confirm_author_id = "u-1"
    fresh_row = _Row("s-fresh")
    fresh_row.pending_confirm = _card(approval_id="call-fresh", created_at=_now())
    fresh_row.pending_confirm_author_id = "u-1"
    clarify_row = _Row("s-clarify")
    clarify_row.pending_confirm = _card(
        confirm_type="clarify", created_at=_now() - timedelta(days=7), approval_id="call-c"
    )
    clarify_row.pending_confirm_author_id = "u-1"
    db = _FakeDb([expired_row, fresh_row, clarify_row])
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, _EMIT, fake_emit)
    monkeypatch.setattr(ws, "SessionLocal", lambda: db)
    # _expire 内锁内二次查询 first() 需返回对应行；_FakeDb.first 固定 rows[0]，
    # 故只验证 s-overdue 在 rows 首位时的单轮语义
    assert db.rows[0] is expired_row
    expired_count = await ws._expire_overdue_approvals_once()
    assert expired_count == 1
    assert expired_row.pending_confirm is None
    assert fresh_row.pending_confirm is not None
    assert clarify_row.pending_confirm is not None  # 审批 TTL 不约束澄清卡
    terminal = [e for e in emitted if e[0] == "approval_terminal"]
    assert len(terminal) == 1
    assert terminal[0][1] == {"approval_id": "call-1", "outcome": "expired", "reason": "审批超时已失效"}
    # 幂等：再次扫描无过期卡，不重复广播
    db.committed = 0
    again = await ws._expire_overdue_approvals_once()
    assert again == 0
    assert [e for e in emitted if e[0] == "approval_terminal"] == terminal


@pytest.mark.asyncio
async def test_approval_ack_voided_when_checkpoint_missing(monkeypatch) -> None:
    """F5/G6（M-R3-7）：恢复预检失败（检查点缺失）→ 行锁内清卡 + voided 终态 +
    error；绝不 resume（防静默丢卡/悬挂续跑）。"""
    started: list = []
    monkeypatch.setattr(ws, "_start_approval_resume", lambda *_a, **_k: started.append(1) or object())
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    async def probe_false(_thread_id: str) -> bool:
        return False

    monkeypatch.setattr(ws, _EMIT, fake_emit)
    monkeypatch.setattr(ws, "_approval_resume_probe", probe_false)
    db = _FakeDb()
    db.rows[0].pending_confirm = _card(created_at=_now())
    db.rows[0].pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        await ws._handle_approval_ack(
            db, object(), ws._ConnectionState(), "s-1", "u-1",
            {"action": "approve", "id": "call-1"},
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.rows[0].pending_confirm is None  # 卡已清（作废不留残留）
    assert started == []  # 不 resume
    terminal = [e for e in emitted if e[0] == "approval_terminal"]
    assert terminal and terminal[-1][1]["outcome"] == "voided"
    assert terminal[-1][1]["approval_id"] == "call-1"
    assert "检查点" in terminal[-1][1]["reason"]


@pytest.mark.asyncio
async def test_approval_ack_resumable_probe_passes(monkeypatch) -> None:
    """F5/G6：预检通过（检查点存在）→ 正常清卡 + resume（既有语义不回归）。"""
    started: list = []
    monkeypatch.setattr(ws, "_start_approval_resume", lambda *_a, **_k: started.append(1) or object())
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    async def probe_true(_thread_id: str) -> bool:
        return True

    monkeypatch.setattr(ws, _EMIT, fake_emit)
    monkeypatch.setattr(ws, "_approval_resume_probe", probe_true)
    db = _FakeDb()
    db.rows[0].pending_confirm = _card(created_at=_now())
    db.rows[0].pending_confirm_author_id = "u-1"
    await ws._handle_approval_ack(
        db, object(), ws._ConnectionState(), "s-1", "u-1",
        {"action": "approve", "id": "call-1"},
    )
    assert db.rows[0].pending_confirm is None
    assert started == [1]  # 预检通过 → resume 照常
    assert not [e for e in emitted if e[0] == "approval_terminal"]
