"""执行门面：公开 execute(..., *, trace, cancel) 只返回 ExecutionOutcome。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agent.log import agent_exception, agent_trace
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.errors import ErrorClass
from app.harness.contracts.tool_call import ExecutionOutcome, OutcomeStatus, ToolCall
from app.harness.contracts.trace import TraceContext, current_trace, using_trace
from app.harness.execution.jobs import assert_short_tool
from app.harness.execution.tool_registry import (
    REGISTERED_TOOLS,
    bind_tool_arguments,
    execute_registered_tool,
    get_tool_definition,
)
from app.harness.feedback.diagnostics import record_diagnostic
from app.harness.feedback.publisher import publisher
from app.harness.feedback.redaction import truncate_tool_data

# 已注册短工具均在独立会话线程执行，避免与 Harness 会话争用。
_ISOLATED_TOOLS = frozenset(tool.name for tool in REGISTERED_TOOLS)


def _map_app_error(exc: AppError) -> ErrorClass:
    """把对外 ErrorCode 收成 observation 级枚举。"""
    if exc.code is ErrorCode.TIMEOUT:
        return ErrorClass.UPSTREAM_TIMEOUT
    if exc.code is ErrorCode.UPSTREAM:
        return ErrorClass.UPSTREAM_ERROR
    if exc.code is ErrorCode.NEED_APPROVAL:
        return ErrorClass.NEED_APPROVAL
    return ErrorClass.ARGUMENT_VALIDATION_ERROR


def bind_arguments(
    db: Session,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    text: str,
    attachments: list[str],
) -> dict[str, Any]:
    """编排只经门面绑定入参，禁止直接 import 注册表。"""
    return bind_tool_arguments(db, name, arguments, text=text, attachments=attachments)


def execute_sync(
    call: ToolCall,
    *,
    trace: TraceContext,
    db: Session,
    user_id: str,
) -> ExecutionOutcome:
    """同步分派已绑定 trace 的 ToolCall，捕获工具异常为 Outcome。"""
    started = time.perf_counter()
    name = (call.tool or "").strip()
    args = call.arguments if isinstance(call.arguments, dict) else {}
    try:
        assert_short_tool(name)
        tool = get_tool_definition(name)
        if tool is None:
            raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")
        data = execute_registered_tool(db, tool.name, args, user_id=user_id)
        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_trace(f"ToolCall 完成 name={name} ok=true latency={latency_ms}ms")
        return ExecutionOutcome.ok(
            call,
            truncate_tool_data(data),
            trace_id=trace.trace_id,
            span_id=trace.span_id,
            latency_ms=latency_ms,
            parent_span_id=trace.parent_span_id,
        )
    except AppError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_trace(
            f"ToolCall 失败 name={name} code={exc.code.value} latency={latency_ms}ms error={exc.message}"
        )
        status = OutcomeStatus.TIMEOUT if exc.code is ErrorCode.TIMEOUT else OutcomeStatus.ERROR
        return ExecutionOutcome.failed(
            call,
            _map_app_error(exc),
            exc.message,
            trace_id=trace.trace_id,
            span_id=trace.span_id,
            status=status,
            latency_ms=latency_ms,
            parent_span_id=trace.parent_span_id,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        agent_exception(f"ToolCall 内部异常 name={name}", exc)
        diagnostic = record_diagnostic(exc, trace=trace)
        return ExecutionOutcome.failed(
            call,
            ErrorClass.TOOL_INTERNAL_ERROR,
            "操作失败",
            trace_id=trace.trace_id,
            span_id=trace.span_id,
            diagnostic_id=diagnostic.diagnostic_id,
            latency_ms=latency_ms,
            parent_span_id=trace.parent_span_id,
        )


def _execute_sync_isolated(call: ToolCall, trace: TraceContext, user_id: str) -> ExecutionOutcome:
    """独立会话执行，避免阻塞事件循环时共用 Harness 会话。"""
    from app.db import SessionLocal

    isolated = SessionLocal()
    try:
        return execute_sync(call, trace=trace, db=isolated, user_id=user_id)
    finally:
        isolated.close()


def _outcome_from_runner_tuple(
    call: ToolCall,
    *,
    trace: TraceContext,
    ok: bool,
    data: Any,
    error: str | None,
    latency_ms: int,
) -> ExecutionOutcome:
    """测试 monkeypatch 只返回 tuple 时，用调用方 span 收成 Outcome。"""
    if ok:
        return ExecutionOutcome.ok(
            call,
            data,
            trace_id=trace.trace_id,
            span_id=trace.span_id,
            latency_ms=latency_ms,
            parent_span_id=trace.parent_span_id,
        )
    timeout = bool(error) and "超时" in error
    if timeout:
        error_class = ErrorClass.UPSTREAM_TIMEOUT
        status = OutcomeStatus.TIMEOUT
    elif error and error.startswith("ToolCall 执行失败"):
        error_class = ErrorClass.TOOL_INTERNAL_ERROR
        status = OutcomeStatus.ERROR
    else:
        error_class = ErrorClass.ARGUMENT_VALIDATION_ERROR
        status = OutcomeStatus.ERROR
    return ExecutionOutcome.failed(
        call,
        error_class,
        error or "该能力未启用",
        trace_id=trace.trace_id,
        span_id=trace.span_id,
        status=status,
        latency_ms=latency_ms,
        parent_span_id=trace.parent_span_id,
    )


def _cancelled_outcome(call: ToolCall, *, trace: TraceContext, requested: bool) -> ExecutionOutcome:
    """本地已停记 cancelled；无法确认远端/线程已停则记 cancel_requested。"""
    return ExecutionOutcome.cancelled(
        call,
        trace_id=trace.trace_id,
        span_id=trace.span_id,
        parent_span_id=trace.parent_span_id,
        requested=requested,
    )


async def execute(
    call: ToolCall,
    *,
    trace: TraceContext,
    db: Session,
    user_id: str,
    cancel: CancellationToken,
    run_tuple: Callable[..., tuple[bool, Any, str | None, int]] | None = None,
    run_isolated: Callable[..., tuple[bool, Any, str | None, int]] | None = None,
) -> ExecutionOutcome:
    """编排层唯一执行入口；普通工具错收敛为 Outcome，不得打崩进程。

    ``run_tuple`` / ``run_isolated`` 仅服务现网 monkeypatch 锚点；未 patch 时走
    ``execute_sync``，保证调用方 ``trace`` 进入真实分派。
    """
    started = time.perf_counter()
    name = (call.tool or "").strip()
    args = call.arguments if isinstance(call.arguments, dict) else {}
    definition = get_tool_definition(name)
    timeout_sec = definition.timeout_s if definition else 30
    tuple_patched = run_tuple is not None and run_tuple is not execute_short_tool
    isolated_patched = run_isolated is not None and not getattr(run_isolated, "_harness_native", False)

    def _finish(outcome: ExecutionOutcome) -> ExecutionOutcome:
        publisher().record_span(
            trace, latency_ms=int((time.perf_counter() - started) * 1000)
        )
        return outcome

    _span_cm = using_trace(trace)
    _span_cm.__enter__()
    try:
        try:
            cancel.raise_if_cancelled()
            if isolated_patched or (
                tuple_patched and run_isolated is not None and name in _ISOLATED_TOOLS
            ):
                ok, data, error, latency_ms = await asyncio.wait_for(
                    asyncio.to_thread(run_isolated, name, args, user_id),
                    timeout=timeout_sec,
                )
                if cancel.is_cancelled():
                    return _finish(_cancelled_outcome(call, trace=trace, requested=False))
                return _finish(
                    _outcome_from_runner_tuple(
                        call,
                        trace=trace,
                        ok=ok,
                        data=data,
                        error=error,
                        latency_ms=latency_ms,
                    )
                )
            if tuple_patched:
                ok, data, error, latency_ms = run_tuple(
                    db, name, args, user_id=user_id, allow_create=False
                )
                if cancel.is_cancelled():
                    return _finish(_cancelled_outcome(call, trace=trace, requested=False))
                return _finish(
                    _outcome_from_runner_tuple(
                        call,
                        trace=trace,
                        ok=ok,
                        data=data,
                        error=error,
                        latency_ms=latency_ms,
                    )
                )
            outcome = await asyncio.wait_for(
                asyncio.to_thread(_execute_sync_isolated, call, trace, user_id),
                timeout=timeout_sec,
            )
            if cancel.is_cancelled():
                return _finish(_cancelled_outcome(call, trace=trace, requested=False))
            return _finish(outcome)
        except TurnCancelled:
            return _finish(_cancelled_outcome(call, trace=trace, requested=False))
        except asyncio.CancelledError:
            # to_thread 无法确认工作线程已停，且无 MCP 客户端，不得伪报 cancelled。
            return _finish(_cancelled_outcome(call, trace=trace, requested=True))
        except TimeoutError:
            agent_trace(f"ToolCall 超时 name={name} timeout={timeout_sec}s")
            return _finish(
                ExecutionOutcome.failed(
                    call,
                    ErrorClass.UPSTREAM_TIMEOUT,
                    f"工具执行超时（{timeout_sec}s）",
                    trace_id=trace.trace_id,
                    span_id=trace.span_id,
                    status=OutcomeStatus.TIMEOUT,
                    latency_ms=timeout_sec * 1000,
                    parent_span_id=trace.parent_span_id,
                )
            )
        except AppError as exc:
            agent_trace(f"ToolCall AppError name={name} code={exc.code.value} error={exc.message}")
            status = OutcomeStatus.TIMEOUT if exc.code is ErrorCode.TIMEOUT else OutcomeStatus.ERROR
            return _finish(
                ExecutionOutcome.failed(
                    call,
                    _map_app_error(exc),
                    exc.message,
                    trace_id=trace.trace_id,
                    span_id=trace.span_id,
                    status=status,
                    parent_span_id=trace.parent_span_id,
                )
            )
        except Exception as exc:
            agent_exception(f"ToolCall 未捕获异常 name={name}", exc)
            diagnostic = record_diagnostic(exc, trace=trace)
            return _finish(
                ExecutionOutcome.failed(
                    call,
                    ErrorClass.TOOL_INTERNAL_ERROR,
                    "操作失败",
                    trace_id=trace.trace_id,
                    span_id=trace.span_id,
                    diagnostic_id=diagnostic.diagnostic_id,
                    parent_span_id=trace.parent_span_id,
                )
            )
    finally:
        _span_cm.__exit__(None, None, None)


def execute_short_tool(
    db: Session,
    name: str,
    arguments: dict | None,
    *,
    user_id: str,
    allow_create: bool = False,
    trace: TraceContext | None = None,
) -> tuple[bool, Any, str | None, int]:
    """测试兼容的 tuple 签名；内部只走 ``execute_sync``。

    直接调用且未传 ``trace`` 时沿用当前任务绑定的 span，否则才 ``for_turn()``。
    活路径应走 ``execute(..., *, trace)``。
    """
    _ = allow_create
    exec_span = trace or current_trace() or TraceContext.for_turn(
        component="execution.facade"
    ).child("execution.dispatch")
    call = ToolCall(
        tool=name,
        arguments=arguments if isinstance(arguments, dict) else {},
        thought="",
        done=False,
        reply="",
        trace_id=exec_span.trace_id,
        span_id=exec_span.span_id,
    )
    outcome = execute_sync(call, trace=exec_span, db=db, user_id=user_id)
    ok = outcome.status is OutcomeStatus.OK
    error = outcome.error.message if outcome.error else None
    return ok, outcome.data if ok else None, error, outcome.latency_ms


def tool_title(name: str) -> str:
    """工具卡中文名。"""
    tool = get_tool_definition(name)
    return tool.title if tool else name
