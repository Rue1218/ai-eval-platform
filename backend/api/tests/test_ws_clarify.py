"""澄清卡中断翻译与恢复链路测试（M4 §3.9.6 / M9 §3.5.1）。"""

import asyncio

import pytest

from app.errors import AppError, ErrorCode
from app.models import Session as AgentSession
from app.routers import ws


class _MessageDb:
    """最小数据库桩（澄清链路不落库业务行）。"""

    def __init__(self) -> None:
        self.row = None

    def add(self, row) -> None:
        self.row = row

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return None

    def flush(self) -> None:
        self.row.id = "m-1"

    def commit(self) -> None:
        pass


def _session() -> AgentSession:
    return AgentSession(id="s-1", user_id="u-1", title="测试会话", visibility="private")


@pytest.mark.asyncio
async def test_clarify_interrupt_registers_and_emits(monkeypatch):
    """中断帧翻译：注册待恢复状态并持久化 clarify 事件。"""
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _websocket, _state, _session_id, event, payload):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_SESSION_CLARIFY", {})

    await ws._handle_clarify_interrupt(
        _MessageDb(),
        object(),
        ws._ConnectionState(),
        "s-1",
        "s-1:turn-9",
        {"type": "clarify", "id": "c-1", "question": "请补充数据集", "options": None},
    )
    assert ws._SESSION_CLARIFY["s-1"] == {"id": "c-1", "thread_id": "s-1:turn-9"}
    assert emitted[0][0] == "clarify"
    assert emitted[0][1]["id"] == "c-1"
    assert emitted[0][1]["question"] == "请补充数据集"


@pytest.mark.asyncio
async def test_clarify_reply_without_pending_rejected(monkeypatch):
    """无待回复澄清卡时回复被拒（VALIDATION）。"""
    monkeypatch.setattr(ws, "_SESSION_CLARIFY", {})
    with pytest.raises(AppError) as error:
        await ws._handle_clarify_reply(
            _MessageDb(),
            object(),
            ws._ConnectionState(),
            _session(),
            {"id": "c-1", "answer": "mmlu"},
            None,
        )
    assert error.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_clarify_reply_id_mismatch_rejected(monkeypatch):
    """id 不匹配（已失效/过期澄清卡）拒绝。"""
    monkeypatch.setattr(ws, "_SESSION_CLARIFY", {"s-1": {"id": "c-2", "thread_id": "t"}})
    with pytest.raises(AppError) as error:
        await ws._handle_clarify_reply(
            _MessageDb(),
            object(),
            ws._ConnectionState(),
            _session(),
            {"id": "c-1", "answer": "mmlu"},
            None,
        )
    assert error.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_clarify_reply_empty_answer_rejected(monkeypatch):
    """空回复拒绝。"""
    monkeypatch.setattr(ws, "_SESSION_CLARIFY", {"s-1": {"id": "c-1", "thread_id": "t"}})
    with pytest.raises(AppError) as error:
        await ws._handle_clarify_reply(
            _MessageDb(),
            object(),
            ws._ConnectionState(),
            _session(),
            {"id": "c-1", "answer": "   "},
            None,
        )
    assert error.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_clarify_reply_resumes_same_thread(monkeypatch):
    """合法回复：弹出待恢复状态并以 Command(resume) 恢复同一 thread。"""
    captured: dict = {}

    async def fake_run_turn(*_args, **_kwargs):
        captured.update(**_kwargs)
        return None

    monkeypatch.setattr(ws, "_run_turn", fake_run_turn)
    monkeypatch.setattr(ws, "_SESSION_CLARIFY", {"s-1": {"id": "c-1", "thread_id": "s-1:turn-9"}})

    task = await ws._handle_clarify_reply(
        _MessageDb(),
        object(),
        ws._ConnectionState(),
        _session(),
        {"id": "c-1", "answer": "数据集用 mmlu"},
        None,
    )
    await task
    # 恢复模式以 resume 参数传递（thread_id 复用 + answer 透传）
    assert captured["resume"] == {"thread_id": "s-1:turn-9", "answer": "数据集用 mmlu"}
    assert "s-1" not in ws._SESSION_CLARIFY


@pytest.mark.asyncio
async def test_clarify_reply_concurrent_turn_rejected(monkeypatch):
    """上一轮仍在生成时回复被拒（CONCURRENCY）。"""
    monkeypatch.setattr(ws, "_SESSION_CLARIFY", {"s-1": {"id": "c-1", "thread_id": "t"}})

    async def never_done():
        await asyncio.Event().wait()

    busy = asyncio.create_task(never_done())
    try:
        with pytest.raises(AppError) as error:
            await ws._handle_clarify_reply(
                _MessageDb(),
                object(),
                ws._ConnectionState(),
                _session(),
                {"id": "c-1", "answer": "mmlu"},
                busy,
            )
        assert error.value.code == ErrorCode.CONCURRENCY
    finally:
        busy.cancel()
