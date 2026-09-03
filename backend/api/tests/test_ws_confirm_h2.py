"""H2 批次 2：ws 直连确认卡桥接测试（图事件 → 行锁发卡 → 广播；失败降级）。

模拟 _run_turn 收包循环消费图产出 confirm 事件的翻译路径（_translate_event），
断言：confirm 意图经 open_pending_confirm 行锁发卡后广播带 confirm_id 的卡；
发卡失败（会话已有卡）降级 error 事件；非 confirm 事件不受影响。
"""

from __future__ import annotations

import pytest

from app.errors import AppError, ErrorCode
from app.routers import ws


def _make_state() -> ws._ConnectionState:
    return ws._ConnectionState()


class _Db:
    def __init__(self) -> None:
        self.pending: dict | None = None

    def execute(self, statement, params=None):
        sql = str(statement)
        if sql.startswith("SELECT"):
            class _Row:
                pass

            row = _Row()
            row.pending_confirm = self.pending
            row.pending_confirm_author_id = "u-1"
            return _Result(row)
        return _Result(None)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class _Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row


@pytest.mark.asyncio
async def test_translate_confirm_opens_card_and_broadcasts(monkeypatch) -> None:
    """图产 confirm 意图 → 行锁发卡 → 广播带 confirm_id 的卡（user_id 正确注入）。"""
    emitted: list[tuple[str, dict]] = []
    opened: dict = {}

    async def fake_emit(_db, _ws, _state, _sid, event, payload, **kwargs):
        emitted.append((event, payload))
        return True

    def fake_open(db, session_id, user_id, task_spec):
        opened["user_id"] = user_id
        return {**task_spec, "confirm_id": "c-new"}

    monkeypatch.setattr("app.routers.ws._emit_persistent", fake_emit)
    monkeypatch.setattr(
        "app.harness.orchestration.confirm.open_pending_confirm", fake_open
    )
    await ws._translate_event(
        _Db(),
        object(),
        _make_state(),
        "s-1",
        None,
        {
            "kind": "confirm",
            "payload": {
                "kind": "benchmark",
                "spec": {"kind": "benchmark", "profile_ids": []},
                "missing": ["profile_ids"],
            },
        },
        user_id="u-1",
    )
    assert opened["user_id"] == "u-1"
    assert emitted and emitted[-1][0] == "confirm"
    payload = emitted[-1][1]
    assert payload["confirm_id"] == "c-new"
    assert payload["kind"] == "benchmark"
    assert payload["missing"] == ["profile_ids"]
    assert payload["spec"]["kind"] == "benchmark"


@pytest.mark.asyncio
async def test_translate_confirm_open_failure_degrades_to_error(monkeypatch) -> None:
    """发卡失败（会话已有待确认卡）→ error 事件，不落 confirm 卡。"""
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _state, _sid, event, payload, **kwargs):
        emitted.append((event, payload))
        return True

    def fake_open(db, session_id, user_id, task_spec):
        raise AppError(ErrorCode.CONCURRENCY, "会话存在待确认任务，请先确认或取消")

    monkeypatch.setattr("app.routers.ws._emit_persistent", fake_emit)
    monkeypatch.setattr(
        "app.harness.orchestration.confirm.open_pending_confirm", fake_open
    )
    await ws._translate_event(
        _Db(),
        object(),
        _make_state(),
        "s-1",
        None,
        {"kind": "confirm", "payload": {"kind": "benchmark", "spec": {}, "missing": []}},
        user_id="u-1",
    )
    assert emitted and emitted[-1][0] == "error"
    assert emitted[-1][1]["code"] == "CONCURRENCY"
    assert not any(event == "confirm" for event, _ in emitted)


@pytest.mark.asyncio
async def test_translate_non_confirm_events_unaffected(monkeypatch) -> None:
    """非 confirm 事件（error/assistant_message 之外）仍走通用翻译（不改写）。"""
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _state, _sid, event, payload, **kwargs):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr("app.routers.ws._emit_persistent", fake_emit)
    await ws._translate_event(
        _Db(),
        object(),
        _make_state(),
        "s-1",
        None,
        {"kind": "tool_call", "payload": {"call_id": "c-1", "name": "read", "arguments": {}}},
        user_id="u-1",
    )
    assert emitted and emitted[-1][0] == "tool_call"
    assert emitted[-1][1] == {"call_id": "c-1", "name": "read", "arguments": {}}
