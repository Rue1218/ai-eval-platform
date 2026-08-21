"""阶段 1：execute(..., *, trace) 与 normalize 回填必须走活路径。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.tool_call import ExecutionOutcome, OutcomeStatus, ToolCall
from app.harness.contracts.trace import TraceContext
from app.harness.execution.facade import execute
from app.harness.orchestration.react_loop import emit_and_run_tool


class _Db:
    def close(self) -> None:
        return None


def test_execute_keeps_caller_trace(monkeypatch):
    """生产路径不得自行 for_turn，必须沿用编排绑定的 span。"""

    monkeypatch.setattr("app.db.SessionLocal", lambda: _Db())
    monkeypatch.setattr(
        "app.harness.execution.facade.execute_registered_tool",
        lambda db, name, arguments, *, user_id: {"file_id": "f1"},
    )

    parent = TraceContext.for_turn(component="orchestration.react")
    exec_span = parent.child("execution.facade")
    call = ToolCall(
        tool="image.generate",
        arguments={"prompt": "x"},
        trace_id=exec_span.trace_id,
        span_id=exec_span.span_id,
    )
    outcome = asyncio.run(
        execute(
            call,
            trace=exec_span,
            db=_Db(),
            user_id="u1",
            cancel=CancellationToken(turn_id=parent.turn_id),
        )
    )
    assert outcome.status is OutcomeStatus.OK
    assert outcome.trace_id == exec_span.trace_id
    assert outcome.span_id == exec_span.span_id
    assert outcome.data["file_id"] == "f1"


def test_emit_and_run_uses_normalized_tool_result(monkeypatch):
    """WS / observations 必须来自 normalize 后的 ToolResult，密钥须脱敏。"""

    async def _fake_execute(call, *, trace, db, user_id, cancel=None, **_kwargs):
        return ExecutionOutcome.ok(
            call,
            {"id": "asset-1", "api_key": "should-hide"},
            trace_id=trace.trace_id,
            span_id=trace.span_id,
            latency_ms=9,
        )

    monkeypatch.setattr("app.harness.orchestration.react_loop.execute_tool", _fake_execute)
    monkeypatch.setattr(
        "app.harness.orchestration.react_loop.bind_arguments",
        lambda *_args, **_kwargs: {"prompt": "hi"},
    )

    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return len(events)

    react = SimpleNamespace(observations=[], known_ids=[])
    ok = asyncio.run(
        emit_and_run_tool(
            _Db(),
            react,
            name="image.generate",
            arguments={"prompt": "hi"},
            user_id="u1",
            emit=_emit,
            text="hi",
            attachments=[],
            execute_short_tool=lambda *_a, **_k: (True, {}, None, 0),
            execute_isolated=lambda *_a, **_k: (True, {}, None, 0),
            trace=TraceContext.for_turn(),
            cancel=CancellationToken(turn_id="turn-test"),
        )
    )
    assert ok is True
    assert react.known_ids == ["asset-1"]
    tool_result = next(payload for event, payload in events if event == "tool_result")
    assert tool_result["ok"] is True
    assert tool_result["data"]["api_key"] == "***"
    assert react.observations[0]["ok"] is True
    assert react.observations[0]["data_summary"]["ids"] == ["asset-1"]
