"""阶段 3：批次解析、并行门禁、trace 归并与流式收尾回归。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.agent.plan import PlanArtifact
from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.errors import ErrorClass, TraceMismatch
from app.harness.contracts.tool_call import (
    ExecutionOutcome,
    OutcomeStatus,
    ToolCall,
    ToolCallBatch,
)
from app.harness.contracts.trace import TraceContext
from app.harness.contracts.turn import TurnStatus
from app.harness.feedback.normalizer import merge_batch
from app.harness.feedback.publisher import InMemoryPublisher, publisher, reset_publisher
from app.harness.orchestration.parallel_facade import (
    PreparedBatchCall,
    decide_parallel,
    execute_parallel,
)
from app.harness.orchestration.parser import McpStep, parse_model_payload, validate_react_output
from app.harness.orchestration.react_loop import _run_mcp_react_loop


class _Db:
    """无真实数据库依赖的 ReAct 循环测试桩。"""


@dataclass(frozen=True)
class _ToolMeta:
    """并行策略测试用的最小工具元数据。"""

    parallel_safe: bool
    permission: str


def _batch(trace: TraceContext) -> ToolCallBatch:
    """构造两个独立的只读测试调用。"""
    return ToolCallBatch(
        turn_id=trace.turn_id,
        thought="并行查询",
        tool_calls=[
            ToolCall(call_id="call-a", tool="test.first", arguments={}),
            ToolCall(call_id="call-b", tool="test.second", arguments={}),
        ],
    )


def test_batch_schema_accepts_no_top_level_tool_and_rejects_item_trace():
    """批次分支不要求顶层 tool；模型仍不能伪造每项 trace。"""
    trace = TraceContext.for_turn()
    payload = {
        "thought": "同时读取两个独立资源",
        "tool_calls": [
            {"tool": "image.generate", "arguments": {}},
            {"tool": "audio.speech_synthesis", "arguments": {}},
        ],
        "done": False,
    }
    decision = parse_model_payload(payload, trace=trace)
    assert isinstance(decision, ToolCallBatch)
    assert [call.batch_index for call in decision.tool_calls] == [0, 1]
    assert {call.trace_id for call in decision.tool_calls} == {trace.trace_id}

    with pytest.raises(ValueError, match="禁止字段"):
        validate_react_output(
            {
                "thought": "伪造链路",
                "tool_calls": [{"tool": "image.generate", "arguments": {}, "trace_id": "T-forged"}],
                "done": False,
            }
        )


def test_parallel_policy_has_only_frozen_three_branches():
    """开关关闭串行；开启后必须全只读安全，否则整批违规而非暗中串行。"""
    trace = TraceContext.for_turn()
    batch = _batch(trace)
    def safe(_name: str) -> _ToolMeta:
        """返回允许并行的只读测试工具。"""
        return _ToolMeta(parallel_safe=True, permission="read")

    def unsafe(_name: str) -> _ToolMeta:
        """返回禁止并行的写测试工具。"""
        return _ToolMeta(parallel_safe=False, permission="write")

    disabled = decide_parallel(batch, enabled=False, max_calls=4, lookup=safe)
    assert disabled.execute_in_parallel is False
    assert disabled.violation_reason is None
    assert decide_parallel(batch, enabled=True, max_calls=4, lookup=safe).execute_in_parallel is True
    rejected = decide_parallel(batch, enabled=True, max_calls=4, lookup=unsafe)
    assert rejected.execute_in_parallel is False
    assert rejected.violation_reason


def test_parallel_facade_preserves_success_when_one_call_fails():
    """gather 的局部失败不得取消同批成功项，返回顺序必须保持 batch 顺序。"""

    async def _body() -> None:
        root = TraceContext.for_turn()
        batch_span = root.child("execution.batch")
        calls = _batch(root).tool_calls
        prepared: list[PreparedBatchCall] = []
        for call in calls:
            execution_span = batch_span.child("execution.facade")
            prepared.append(
                PreparedBatchCall(
                    call=call.model_copy(
                        update={"trace_id": root.trace_id, "span_id": execution_span.span_id}
                    ),
                    trace=execution_span,
                )
            )

        async def _run(item: PreparedBatchCall) -> ExecutionOutcome:
            if item.call.call_id == "call-b":
                raise RuntimeError("模拟单项失败")
            return ExecutionOutcome.ok(
                item.call,
                {"id": item.call.call_id},
                trace_id=item.trace.trace_id,
                span_id=item.trace.span_id,
                parent_span_id=item.trace.parent_span_id,
                latency_ms=1,
            )

        outcomes = await execute_parallel(
            prepared,
            cancel=CancellationToken(turn_id=root.turn_id),
            run_call=_run,
            max_calls=4,
        )
        assert [outcome.call_id for outcome in outcomes] == ["call-a", "call-b"]
        assert [outcome.status for outcome in outcomes] == [OutcomeStatus.OK, OutcomeStatus.ERROR]
        assert outcomes[1].error and outcomes[1].error.class_ is ErrorClass.TOOL_INTERNAL_ERROR

    asyncio.run(_body())


def test_merge_batch_sorts_by_batch_index_and_rejects_wrong_parent():
    """反馈按 batch_index 归并；任一 Outcome 未挂在批次 span 下必须熔断。"""
    root = TraceContext.for_turn()
    batch = _batch(root)
    batch_span = root.child("execution.batch")
    first_span = batch_span.child("execution.facade")
    second_span = batch_span.child("execution.facade")
    first = ExecutionOutcome.ok(
        batch.tool_calls[0],
        {"id": "a"},
        trace_id=root.trace_id,
        span_id=first_span.span_id,
        parent_span_id=batch_span.span_id,
        latency_ms=3,
    )
    second = ExecutionOutcome.ok(
        batch.tool_calls[1],
        {"id": "b"},
        trace_id=root.trace_id,
        span_id=second_span.span_id,
        parent_span_id=batch_span.span_id,
        latency_ms=1,
    )
    result = merge_batch(
        batch,
        [second, first],
        batch_execution_span=batch_span,
        trace=root.child("feedback.merge_batch"),
    )
    assert [item.call_id for item in result.ordered_results] == ["call-a", "call-b"]
    assert result.results_by_call_id["call-b"].data == {"id": "b"}

    invalid = first.model_copy(update={"parent_span_id": root.span_id})
    with pytest.raises(TraceMismatch):
        merge_batch(
            batch,
            [invalid, second],
            batch_execution_span=batch_span,
            trace=root.child("feedback.merge_batch"),
        )


def test_default_batch_path_stays_serial_and_final_reply_enters_finalizing_stream(monkeypatch):
    """默认关闭并行时按原顺序调用；done 回复先写 FINALIZING_STREAM，再由总控结束。"""

    async def _body() -> None:
        trace = TraceContext.for_turn()
        cancel = CancellationToken(turn_id=trace.turn_id)
        store = reset_publisher(store=InMemoryPublisher())
        store.start_turn(trace, session_id="session-stage3")
        calls: list[str] = []
        decisions = [
            ToolCallBatch(
                turn_id=trace.turn_id,
                thought="依次执行媒体工具",
                tool_calls=[
                    ToolCall(tool="image.generate", arguments={}),
                    ToolCall(tool="audio.speech_synthesis", arguments={}),
                ],
            ),
            McpStep(thought="结果已足够", tool=None, arguments={}, done=True, reply="已完成"),
        ]

        async def _step(**_kwargs):
            return decisions.pop(0)

        async def _serial(_db, _react, *, name, **_kwargs):
            calls.append(name)
            return True

        monkeypatch.setattr("app.harness.orchestration.react_loop.PARALLEL_READONLY_TOOLS", False)
        monkeypatch.setattr("app.harness.orchestration.react_loop.emit_and_run_tool", _serial)
        plan = PlanArtifact(
            intent="chat",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=[],
            delivery="text",
            budget={"max_tool_rounds": 4},
            notes="测试",
            source="l0",
        )
        react = SimpleNamespace(
            observations=[],
            known_ids=[],
            rounds_used=0,
            thinking_text="",
            reply_text="",
            used_llm=False,
            proposed_spec=None,
        )

        async def _emit(_event: str, _payload: dict, **_kwargs) -> int:
            return 1

        await _run_mcp_react_loop(
            _Db(),
            plan,
            react,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            text="测试",
            attachments=[],
            stop=cancel.stop,
            history=[],
            compact_summary=None,
            rounds_limit=4,
            stream_mcp_step=_step,
            execute_short_tool=lambda *_args, **_kwargs: (True, {}, None, 0),
            execute_isolated=lambda *_args, **_kwargs: (True, {}, None, 0),
            trace=trace,
            cancel=cancel,
        )
        assert calls == ["image.generate", "audio.speech_synthesis"]
        assert react.reply_text == "已完成"
        assert store.turns[0]["status"] == TurnStatus.FINALIZING_STREAM
        publisher().finish_turn(trace, status=TurnStatus.FINISHED)
        assert store.turns[0]["status"] == TurnStatus.FINISHED
        reset_publisher()

    asyncio.run(_body())


def test_done_tool_conflict_and_missing_tool_never_execute(monkeypatch):
    """模型完成冲突或空动作只回填内部 observation，绝不能发出工具调用。"""

    async def _body() -> None:
        trace = TraceContext.for_turn()
        cancel = CancellationToken(turn_id=trace.turn_id)
        decisions = [
            McpStep(thought="冲突", tool="image.generate", arguments={}, done=True, reply=""),
            McpStep(thought="缺工具", tool=None, arguments={}, done=False, reply="", missing_tool=True),
            McpStep(thought="结束", tool=None, arguments={}, done=True, reply="完成"),
        ]

        async def _step(**_kwargs):
            return decisions.pop(0)

        async def _unexpected_execution(*_args, **_kwargs):
            raise AssertionError("冲突和空工具不应进入执行层")

        monkeypatch.setattr("app.harness.orchestration.react_loop.emit_and_run_tool", _unexpected_execution)
        plan = PlanArtifact(
            intent="chat",
            skill_id=None,
            slots={"filled": {}, "missing": []},
            tools_needed=[],
            delivery="text",
            budget={"max_tool_rounds": 4},
            notes="测试",
            source="l0",
        )
        react = SimpleNamespace(
            observations=[],
            known_ids=[],
            rounds_used=0,
            thinking_text="",
            reply_text="",
            used_llm=False,
            proposed_spec=None,
        )
        events: list[str] = []

        async def _emit(event: str, _payload: dict, **_kwargs) -> int:
            events.append(event)
            return len(events)

        await _run_mcp_react_loop(
            _Db(),
            plan,
            react,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            text="测试",
            attachments=[],
            stop=cancel.stop,
            history=[],
            compact_summary=None,
            rounds_limit=4,
            stream_mcp_step=_step,
            execute_short_tool=lambda *_args, **_kwargs: (True, {}, None, 0),
            execute_isolated=lambda *_args, **_kwargs: (True, {}, None, 0),
            trace=trace,
            cancel=cancel,
        )
        assert not {"tool_call", "tool_result"} & set(events)
        assert len(react.observations) == 2
        assert react.reply_text == "完成"

    asyncio.run(_body())
