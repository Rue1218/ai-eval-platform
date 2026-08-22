"""ReAct 单调用循环：每轮 0 或 1 个短工具；trace/cancel 由总控强制下传。"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agent.defaults import (
    MODEL_TIMEOUT_S,
    PARALLEL_READONLY_TOOLS,
    SHORT_TOOLS,
    STREAM_EMIT_WAIT_S,
    STREAM_TIMEOUT_S,
    TOOL_TITLES,
    is_long_tool,
)
from app.agent.log import agent_exception, agent_trace
from app.agent.persona import react_system, turn_system
from app.agent.plan import PlanArtifact, parse_json_object
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.errors import ErrorClass, MissingTraceContext, TraceMismatch
from app.harness.contracts.tool_call import (
    ExecutionOutcome,
    OutcomeStatus,
    ToolCall,
    ToolCallBatch,
    ToolResult,
)
from app.harness.contracts.trace import TraceContext, using_trace
from app.harness.contracts.turn import TurnStatus
from app.harness.execution.facade import bind_arguments
from app.harness.execution.facade import execute as execute_tool
from app.harness.execution.tool_registry import get_tool_definition
from app.harness.feedback.normalizer import merge_batch, normalize
from app.harness.feedback.observation import collect_ids, summarize_observation
from app.harness.feedback.publisher import publisher
from app.harness.feedback.redaction import redact_secrets
from app.harness.orchestration.budgets import (
    consecutive_retryable_error_cap,
    max_parallel_calls,
    rounds_cap,
    same_call_fingerprint_cap,
)
from app.harness.orchestration.parallel_facade import (
    PreparedBatchCall,
    decide_parallel,
    execute_parallel,
)
from app.harness.orchestration.parser import (
    McpStep,
    ReactDecision,
    parse_model_payload,
)
from app.harness.orchestration.state_machine import TurnStateMachine

EmitFn = Callable[..., Awaitable[int]]
AbortCheck = Callable[[], None]


def _executed_names(react: Any) -> set[str]:
    """本轮已发出的工具名（含失败），用于回退队列去重。"""
    return {str(obs.get("name") or "") for obs in react.observations if obs.get("name")}


def _trace_toolcall_args(arguments: dict[str, Any]) -> str:
    """控制台打印用的入参摘要；脱敏且截断。"""
    try:
        return json.dumps(redact_secrets(arguments or {}), ensure_ascii=False)[:800]
    except Exception:
        return "{}"


async def emit_and_run_tool(
    db: Session,
    react: Any,
    *,
    name: str,
    arguments: dict[str, Any],
    user_id: str,
    emit: EmitFn,
    text: str,
    attachments: list[str],
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    trace: TraceContext,
    cancel: CancellationToken,
) -> bool:
    """发出成对 tool_call / tool_result 并写入观察。返回工具是否成功。"""
    cancel.raise_if_cancelled()
    if is_long_tool(name):
        error = f"「{name}」是长任务，只能入队后由 Worker 执行"
        await emit("tool_call", {"name": name, "arguments": {}})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(
            summarize_observation(
                name,
                False,
                None,
                error,
                0,
                error_class=ErrorClass.TOOL_NOT_ALLOWED,
            )
        )
        agent_trace(f"ToolCall 拒绝长任务 name={name}")
        return False
    if name not in SHORT_TOOLS:
        error = f"未知短工具「{name}」"
        await emit("tool_call", {"name": name, "arguments": arguments})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(
            summarize_observation(
                name,
                False,
                None,
                error,
                0,
                error_class=ErrorClass.TOOL_NOT_ALLOWED,
            )
        )
        agent_trace(f"ToolCall 拒绝未知工具 name={name}")
        return False
    if name == "task.create":
        error = "task.create 只允许在确认卡 ack 之后执行"
        await emit("tool_call", {"name": name, "arguments": {}})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(
            summarize_observation(
                name,
                False,
                None,
                error,
                0,
                error_class=ErrorClass.TOOL_NOT_ALLOWED,
            )
        )
        agent_trace("ToolCall 拒绝 task.create（须 ack 后）")
        return False

    try:
        bound = bind_arguments(db, name, arguments, text=text, attachments=attachments)
    except AppError as exc:
        # 参数绑定失败时没有真正 ToolCall，不能孤立发送 tool_result；仅回填安全 observation。
        _append_internal_error(
            react,
            tool=name,
            error_class=ErrorClass.ARGUMENT_VALIDATION_ERROR,
            message=exc.message,
            trace=trace,
        )
        agent_trace(f"ToolCall 参数校验失败 name={name}")
        return False
    agent_trace(f"ToolCall 开始 name={name} arguments={_trace_toolcall_args(bound)}")
    await emit("tool_call", {"name": name, "arguments": bound})

    exec_span = trace.child("execution.facade")
    with using_trace(exec_span):
        call = ToolCall(
            tool=name,
            arguments=bound,
            thought="",
            done=False,
            reply="",
            trace_id=exec_span.trace_id,
            span_id=exec_span.span_id,
        )
        try:
            outcome = await execute_tool(
                call,
                trace=exec_span,
                db=db,
                user_id=user_id,
                cancel=cancel,
                run_tuple=execute_short_tool,
                run_isolated=execute_isolated,
            )
            feedback_span = exec_span.child("feedback.normalize")
            result = normalize(outcome, trace=feedback_span)
            publisher().record_span(feedback_span, latency_ms=result.latency_ms)
        except (MissingTraceContext, TraceMismatch) as exc:
            agent_trace(f"ReAct normalize Fail-fast type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "操作失败") from exc

        payload: dict[str, Any] = {"name": result.tool, "ok": result.ok, "latency_ms": result.latency_ms}
        if result.ok:
            payload["data"] = result.data
            react.known_ids.extend(collect_ids(result.data))
            agent_trace(f"ToolCall 结束 name={name} ok=true latency={result.latency_ms}ms")
        else:
            payload["error"] = result.error or "该能力未启用"
            agent_trace(
                f"ToolCall 结束 name={name} ok=false latency={result.latency_ms}ms error={payload['error']}"
            )
    await emit("tool_result", payload)
    react.observations.append(
        summarize_observation(
            result.tool,
            result.ok,
            result.data,
            result.error,
            result.latency_ms,
            error_class=result.error_class,
        )
    )
    if result.status in {OutcomeStatus.CANCELLED, OutcomeStatus.CANCEL_REQUESTED}:
        raise TurnCancelled(cancel.reason or "cancelled")
    cancel.raise_if_cancelled()
    return result.ok


def _append_internal_error(
    react: Any,
    *,
    tool: str,
    error_class: ErrorClass,
    message: str,
    trace: TraceContext,
) -> None:
    """把未执行的编排错误收成 observation，不发送孤立的 WS 工具事件。"""
    execution_span = trace.child("execution.validation")
    call = ToolCall(
        tool=tool,
        arguments={},
        thought="",
        done=False,
        reply="",
        trace_id=execution_span.trace_id,
        span_id=execution_span.span_id,
    )
    outcome = ExecutionOutcome.failed(
        call,
        error_class,
        message,
        trace_id=execution_span.trace_id,
        span_id=execution_span.span_id,
        parent_span_id=execution_span.parent_span_id,
    )
    feedback_span = execution_span.child("feedback.normalize")
    result = normalize(outcome, trace=feedback_span)
    publisher().record_span(execution_span)
    publisher().record_span(feedback_span)
    react.observations.append(
        summarize_observation(
            result.tool,
            result.ok,
            result.data,
            result.error,
            result.latency_ms,
            error_class=result.error_class,
        )
    )


def _tool_result_payload(result: ToolResult) -> dict[str, Any]:
    """把已脱敏的内部结果映射为既有 WS 工具结果事件，不扩展对外字段。"""
    payload: dict[str, Any] = {
        "name": result.tool,
        "ok": result.ok,
        "latency_ms": result.latency_ms,
    }
    if result.ok:
        payload["data"] = result.data
    else:
        payload["error"] = result.error or "该能力未启用"
    return payload


async def _emit_and_run_batch(
    db: Session,
    react: Any,
    *,
    batch: ToolCallBatch,
    user_id: str,
    emit: EmitFn,
    text: str,
    attachments: list[str],
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    trace: TraceContext,
    cancel: CancellationToken,
    max_calls: int,
    execute_in_parallel: bool,
) -> bool:
    """执行一批已过门禁调用；串行和并行都必须经过同一批次 span 与反馈归并。"""
    batch_execution_span = trace.child("execution.batch")
    prepared: list[PreparedBatchCall] = []
    outcomes_by_call_id: dict[str, ExecutionOutcome] = {}
    emitted_call_ids: set[str] = set()
    feedback_span = trace.child("feedback.merge_batch")

    for call in batch.tool_calls:
        execution_span = batch_execution_span.child("execution.facade")
        try:
            bound = bind_arguments(
                db,
                call.tool or "",
                call.arguments,
                text=text,
                attachments=attachments,
            )
        except AppError as exc:
            # 入参不合规不能启动工具，但必须作为同一批次的结构化 observation 回填。
            outcomes_by_call_id[call.call_id] = ExecutionOutcome.failed(
                call,
                ErrorClass.ARGUMENT_VALIDATION_ERROR,
                exc.message,
                trace_id=execution_span.trace_id,
                span_id=execution_span.span_id,
                parent_span_id=batch_execution_span.span_id,
            )
            # 没有进入执行门面也必须留下真实 child span，审计才能解释该项为何未执行。
            publisher().record_span(execution_span)
            continue
        bound_call = call.model_copy(
            update={
                "arguments": bound,
                "trace_id": execution_span.trace_id,
                "span_id": execution_span.span_id,
            }
        )
        prepared.append(PreparedBatchCall(call=bound_call, trace=execution_span))

    async def _run_one(prepared_call: PreparedBatchCall) -> ExecutionOutcome:
        return await execute_tool(
            prepared_call.call,
            trace=prepared_call.trace,
            db=db,
            user_id=user_id,
            cancel=cancel,
            run_tuple=execute_short_tool,
            run_isolated=execute_isolated,
        )

    if execute_in_parallel:
        for prepared_call in prepared:
            emitted_call_ids.add(prepared_call.call.call_id)
            await emit(
                "tool_call",
                {"name": prepared_call.call.tool, "arguments": prepared_call.call.arguments},
            )
        outcomes = await execute_parallel(
            prepared,
            cancel=cancel,
            run_call=_run_one,
            max_calls=max_calls,
        )
    else:
        outcomes = []
        for prepared_call in prepared:
            cancel.raise_if_cancelled()
            emitted_call_ids.add(prepared_call.call.call_id)
            await emit(
                "tool_call",
                {"name": prepared_call.call.tool, "arguments": prepared_call.call.arguments},
            )
            outcome = await _run_one(prepared_call)
            try:
                # 默认串行必须保持既有的一项调用紧跟一项结果事件，同时仍以批次父 span 校验。
                serial_result = normalize(
                    outcome,
                    trace=feedback_span,
                    batch_index=prepared_call.call.batch_index,
                    batch_execution_span=batch_execution_span,
                )
            except (MissingTraceContext, TraceMismatch) as exc:
                agent_trace(f"ReAct 串行批次 normalize Fail-fast type={type(exc).__name__}")
                raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
            await emit("tool_result", _tool_result_payload(serial_result))
            outcomes.append(outcome)
    outcomes_by_call_id.update({outcome.call_id: outcome for outcome in outcomes})
    ordered_outcomes = [outcomes_by_call_id[call.call_id] for call in batch.tool_calls]

    try:
        result_batch = merge_batch(
            batch,
            ordered_outcomes,
            batch_execution_span=batch_execution_span,
            trace=feedback_span,
        )
    except (MissingTraceContext, TraceMismatch) as exc:
        agent_trace(f"ReAct 批次 normalize Fail-fast type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
    publisher().record_span(batch_execution_span)
    publisher().record_span(feedback_span)

    all_ok = True
    cancelled = False
    for result in result_batch.ordered_results:
        if execute_in_parallel and result.call_id in emitted_call_ids:
            await emit("tool_result", _tool_result_payload(result))
        if result.ok:
            react.known_ids.extend(collect_ids(result.data))
        else:
            all_ok = False
        react.observations.append(
            summarize_observation(
                result.tool,
                result.ok,
                result.data,
                result.error,
                result.latency_ms,
                error_class=result.error_class,
            )
        )
        cancelled = cancelled or result.status in {
            OutcomeStatus.CANCELLED,
            OutcomeStatus.CANCEL_REQUESTED,
        }
    if cancelled:
        raise TurnCancelled(cancel.reason or "cancelled")
    cancel.raise_if_cancelled()
    return all_ok


def _call_mcp_step(
    db: Session,
    *,
    system: str,
    payload: dict,
    stop: threading.Event,
    cancel: CancellationToken,
    trace: TraceContext,
) -> ReactDecision:
    """同步调用模型，只要 JSON 决策，不走 function calling。

    经 ``app.llm`` 再导出以保留 monkeypatch 锚点；正文在 ``harness.llm.client``。
    """
    from app.llm import call_agent_model_detailed

    cancel.raise_if_cancelled()
    if stop.is_set():
        raise RuntimeError("aborted")
    result = call_agent_model_detailed(
        db,
        system,
        json.dumps(payload, ensure_ascii=False),
        temperature=0,
        max_tokens=1024,
        timeout_s=MODEL_TIMEOUT_S,
        cancel=cancel,
    )
    decision = parse_model_payload(parse_json_object(result.text), trace=trace)
    if isinstance(decision, McpStep):
        decision.latency_ms = result.latency_ms
    return decision


async def stream_mcp_step(
    *,
    system: str,
    payload: dict,
    stop: threading.Event,
    emit: EmitFn,
    trace: TraceContext,
    cancel: CancellationToken,
) -> ReactDecision:
    """流式跑一轮 MCP 决策：推理链走 thought.stream=think，正文只解析 JSON。

    ``trace`` / ``cancel`` 不可缺省。经 ``app.llm`` 再导出以保留 monkeypatch 锚点。
    """
    from app.db import SessionLocal
    from app.llm import stream_agent_model

    cancel.raise_if_cancelled()
    stop = cancel.stop
    loop = asyncio.get_running_loop()
    user_blob = json.dumps(payload, ensure_ascii=False)
    parse_span = trace.child("orchestration.parse")
    started = time.perf_counter()

    def _producer() -> tuple[str, str, int]:
        cancel.raise_if_cancelled()
        tdb = SessionLocal()
        content_parts: list[str] = []
        thought_parts: list[str] = []
        t0 = time.perf_counter()
        try:
            for kind, chunk in stream_agent_model(
                tdb,
                system,
                user_blob,
                trace=parse_span,
                cancel=cancel,
                temperature=0,
                max_tokens=2048,
                timeout_s=STREAM_TIMEOUT_S,
            ):
                cancel.raise_if_cancelled()
                if not chunk:
                    continue
                if kind == "reasoning":
                    thought_parts.append(chunk)
                    try:
                        asyncio.run_coroutine_threadsafe(
                            emit("thought", {"text": chunk, "stream": "think"}),
                            loop,
                        ).result(timeout=STREAM_EMIT_WAIT_S)
                    except Exception:
                        pass
                else:
                    content_parts.append(chunk)
            latency_ms = round((time.perf_counter() - t0) * 1000)
            return "".join(content_parts), "".join(thought_parts).strip()[:12000], latency_ms
        finally:
            tdb.close()

    with using_trace(parse_span):
        content, reasoning, latency_ms = await asyncio.to_thread(_producer)
        cancel.raise_if_cancelled()
        if reasoning:
            await emit("thought", {"text": reasoning, "stream": "think_final"})
        try:
            parsed = parse_json_object(content)
        except ValueError:
            agent_trace("ReAct 流式 JSON 解析失败，回退非流式决策")
            isolated = SessionLocal()
            try:
                decision = _call_mcp_step(
                    isolated,
                    system=system,
                    payload=payload,
                    stop=stop,
                    cancel=cancel,
                    trace=trace,
                )
            finally:
                isolated.close()
            if isinstance(decision, McpStep):
                decision.reasoning_text = reasoning
                if not decision.latency_ms:
                    decision.latency_ms = latency_ms
            publisher().record_span(
                parse_span, latency_ms=round((time.perf_counter() - started) * 1000)
            )
            return decision
        decision = parse_model_payload(parsed, trace=trace)
        if isinstance(decision, McpStep):
            decision.latency_ms = latency_ms
            decision.reasoning_text = reasoning
        publisher().record_span(
            parse_span, latency_ms=round((time.perf_counter() - started) * 1000)
        )
        return decision


async def _emit_react_thought(
    emit: EmitFn,
    text: str,
    *,
    skill_id: str | None,
    latency_ms: int | None = None,
) -> None:
    """每轮一张思考卡：stage=react，技能徽标走 skill_id。"""
    payload: dict[str, Any] = {"text": text, "stage": "react"}
    if skill_id:
        payload["skill_id"] = skill_id
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    await emit("thought", payload)


async def _run_mcp_react_loop(
    db: Session,
    plan: PlanArtifact,
    react: Any,
    *,
    user_id: str,
    emit: EmitFn,
    check_abort: AbortCheck,
    slash_fill_first: bool,
    text: str,
    attachments: list[str],
    stop: threading.Event,
    history: list[dict[str, str]],
    compact_summary: str | None,
    rounds_limit: int,
    stream_mcp_step: Callable[..., Awaitable[ReactDecision]],
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    trace: TraceContext,
    cancel: CancellationToken,
) -> None:
    """多轮 MCP ReAct：思考卡 → 一个短工具 → 观察 → 再思考。"""
    from app.harness.orchestration.react_adapter import (
        _missing_for_kind,
        _redirect_creative_tool,
        build_proposed_spec,
    )

    system = turn_system(
        react_system(),
        skill_id=plan.skill_id if plan.delivery == "confirm" else None,
        compact_summary=compact_summary,
    )
    executed_calls: dict[tuple[str, str], int] = {}
    consecutive_retryable = 0
    state = TurnStateMachine()

    while react.rounds_used < rounds_limit:
        check_abort()
        cancel.raise_if_cancelled()
        payload = {
            "text": text,
            "intent": plan.intent,
            "skill_id": plan.skill_id,
            "delivery": plan.delivery,
            "slots": plan.slots,
            "history": history[-6:],
            "observations": list(react.observations),
            "round": react.rounds_used + 1,
            "max_rounds": rounds_limit,
            "attachments": attachments,
            "suggested_tools": list(plan.tools_needed),
            "note": "suggested_tools 只是规划建议，不是必须执行的清单",
        }
        try:
            decision = await stream_mcp_step(
                system=system,
                payload=payload,
                stop=stop,
                emit=emit,
                trace=trace,
                cancel=cancel,
            )
        except TurnCancelled:
            raise
        except RuntimeError:
            cancel.raise_if_cancelled()
            check_abort()
            return
        except AppError as exc:
            agent_trace(f"ReAct 决策不可用 code={exc.code.value}，改走工具队列")
            return
        except Exception as exc:
            agent_exception("ReAct 决策内部异常，改走工具队列", exc)
            return

        state.transition(TurnStatus.PARSED)
        publisher().set_turn_status(trace, status=TurnStatus.PARSED)
        react.used_llm = True
        if decision.thought:
            react.thinking_text = (react.thinking_text + "\n" + decision.thought).strip()[-12000:]
        if isinstance(decision, McpStep) and decision.reasoning_text:
            react.thinking_text = (
                react.thinking_text + "\n" + decision.reasoning_text
            ).strip()[-12000:]
        elif decision.thought:
            await _emit_react_thought(
                emit,
                decision.thought,
                skill_id=plan.skill_id,
                latency_ms=decision.latency_ms if isinstance(decision, McpStep) else None,
            )
        if decision.reply:
            react.reply_text = decision.reply

        if isinstance(decision, ToolCallBatch):
            if decision.done:
                if decision.tool_calls:
                    react.rounds_used += 1
                    react.reply_text = ""
                    _append_internal_error(
                        react,
                        tool="batch",
                        error_class=ErrorClass.DONE_TOOL_CONFLICT,
                        message="模型已声明完成，不能同时请求批量工具调用",
                        trace=trace,
                    )
                    state.transition(TurnStatus.FEEDBACK_READY)
                    publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
                    continue
                break
            react.rounds_used += 1
            if not decision.tool_calls:
                _append_internal_error(
                    react,
                    tool="",
                    error_class=ErrorClass.MISSING_TOOL,
                    message="模型未提供可执行工具",
                    trace=trace,
                )
                state.transition(TurnStatus.FEEDBACK_READY)
                publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
                continue

            parallel = decide_parallel(
                decision,
                enabled=PARALLEL_READONLY_TOOLS,
                max_calls=max_parallel_calls(),
                lookup=get_tool_definition,
            )
            if not PARALLEL_READONLY_TOOLS:
                state.transition(TurnStatus.EXECUTING)
                publisher().set_turn_status(trace, status=TurnStatus.EXECUTING)
                await _emit_and_run_batch(
                    db,
                    react,
                    batch=decision,
                    user_id=user_id,
                    emit=emit,
                    text=text,
                    attachments=attachments,
                    execute_short_tool=execute_short_tool,
                    execute_isolated=execute_isolated,
                    trace=trace,
                    cancel=cancel,
                    max_calls=max_parallel_calls(),
                    execute_in_parallel=False,
                )
                state.transition(TurnStatus.FEEDBACK_READY)
                publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
                continue
            if not parallel.execute_in_parallel:
                _append_internal_error(
                    react,
                    tool="batch",
                    error_class=ErrorClass.PARALLEL_POLICY_VIOLATION,
                    message=parallel.violation_reason or "批量工具不满足并行策略",
                    trace=trace,
                )
                state.transition(TurnStatus.FEEDBACK_READY)
                publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
                continue

            state.transition(TurnStatus.PARALLEL_EXECUTING)
            publisher().set_turn_status(trace, status=TurnStatus.PARALLEL_EXECUTING)
            await _emit_and_run_batch(
                db,
                react,
                batch=decision,
                user_id=user_id,
                emit=emit,
                text=text,
                attachments=attachments,
                execute_short_tool=execute_short_tool,
                execute_isolated=execute_isolated,
                trace=trace,
                cancel=cancel,
                max_calls=max_parallel_calls(),
                execute_in_parallel=True,
            )
            state.transition(TurnStatus.FEEDBACK_READY)
            publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
            continue

        step = decision

        raw_tool = _redirect_creative_tool(plan, text, step.tool)
        if raw_tool and is_long_tool(raw_tool):
            await _emit_react_thought(
                emit,
                f"「{raw_tool}」是长任务，确认后由 Worker 入队执行，对话进程不跑完。",
                skill_id=plan.skill_id,
            )
            break
        if step.model_done and raw_tool:
            react.rounds_used += 1
            react.reply_text = ""
            _append_internal_error(
                react,
                tool=raw_tool,
                error_class=ErrorClass.DONE_TOOL_CONFLICT,
                message="模型已声明完成，不能同时请求工具调用",
                trace=trace,
            )
            state.transition(TurnStatus.FEEDBACK_READY)
            publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
            continue
        if step.missing_tool:
            react.rounds_used += 1
            _append_internal_error(
                react,
                tool="",
                error_class=ErrorClass.MISSING_TOOL,
                message="模型未提供可执行工具",
                trace=trace,
            )
            state.transition(TurnStatus.FEEDBACK_READY)
            publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
            continue
        if not raw_tool or step.done:
            break

        args_key = json.dumps(step.arguments, ensure_ascii=False, sort_keys=True)
        dedup_key = (raw_tool, args_key)
        seen = executed_calls.get(dedup_key, 0)
        fingerprint_cap = same_call_fingerprint_cap()
        effective_cap = fingerprint_cap if fingerprint_cap is not None else 1
        if seen >= effective_cap:
            if fingerprint_cap is not None:
                agent_trace(f"BUDGET_EXHAUSTED fingerprint name={raw_tool}")
            agent_trace(f"跳过重复 MCP 调用 name={raw_tool}")
            await _emit_react_thought(
                emit,
                f"「{raw_tool}」相同参数已调用过，停止重复。",
                skill_id=plan.skill_id,
            )
            break

        react.rounds_used += 1
        state.transition(TurnStatus.EXECUTING)
        publisher().set_turn_status(trace, status=TurnStatus.EXECUTING)
        ok = await emit_and_run_tool(
            db,
            react,
            name=raw_tool,
            arguments=step.arguments,
            user_id=user_id,
            emit=emit,
            text=text,
            attachments=attachments,
            execute_short_tool=execute_short_tool,
            execute_isolated=execute_isolated,
            trace=trace,
            cancel=cancel,
        )
        state.transition(TurnStatus.FEEDBACK_READY)
        publisher().set_turn_status(trace, status=TurnStatus.FEEDBACK_READY)
        executed_calls[dedup_key] = seen + 1
        if ok:
            consecutive_retryable = 0
        else:
            consecutive_retryable += 1
            retry_cap = consecutive_retryable_error_cap()
            if retry_cap is not None and consecutive_retryable >= retry_cap:
                agent_trace("BUDGET_EXHAUSTED consecutive_retryable")
                break
        spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        react.proposed_spec = spec
        if plan.delivery == "confirm" and spec and not _missing_for_kind(spec):
            break


async def _run_tool_queue(
    db: Session,
    plan: PlanArtifact,
    react: Any,
    *,
    queue: list[str],
    user_id: str,
    emit: EmitFn,
    check_abort: AbortCheck,
    slash_fill_first: bool,
    text: str,
    attachments: list[str],
    rounds_limit: int,
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    trace: TraceContext,
    cancel: CancellationToken,
) -> None:
    """按规划队列串行执行尚未跑过的短工具。"""
    from app.harness.orchestration.react_adapter import (
        _missing_for_kind,
        _redirect_creative_tool,
        build_proposed_spec,
    )

    executed = set(_executed_names(react))
    pending = [name for name in queue if name and name not in executed]
    while pending and react.rounds_used < rounds_limit:
        check_abort()
        cancel.raise_if_cancelled()
        original = pending.pop(0)
        name = _redirect_creative_tool(plan, text, original)
        if not name:
            continue
        if name != original and name in executed:
            continue
        if is_long_tool(name):
            await _emit_react_thought(
                emit,
                f"「{name}」是长任务，确认后由 Worker 入队执行，对话进程不跑完。",
                skill_id=plan.skill_id,
            )
            break
        if name not in SHORT_TOOLS:
            agent_trace(f"跳过未知工具 name={name}")
            continue
        await _emit_react_thought(
            emit,
            f"ToolCall「{TOOL_TITLES.get(name, name)}」",
            skill_id=plan.skill_id,
        )
        react.rounds_used += 1
        ok = await emit_and_run_tool(
            db,
            react,
            name=name,
            arguments={},
            user_id=user_id,
            emit=emit,
            text=text,
            attachments=attachments,
            execute_short_tool=execute_short_tool,
            execute_isolated=execute_isolated,
            trace=trace,
            cancel=cancel,
        )
        executed.add(name)
        if name == "task.create":
            continue
        spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        react.proposed_spec = spec
        if spec and not _missing_for_kind(spec):
            break
        if not ok:
            break
    if react.rounds_used >= rounds_limit and pending:
        agent_trace(f"工具轮次达到硬顶 rounds={react.rounds_used}")


async def run_react_loop(
    db: Session,
    plan: PlanArtifact,
    *,
    user_id: str,
    emit: EmitFn,
    check_abort: AbortCheck,
    slash_fill_first: bool,
    prior: Any | None = None,
    extra_tools: list[str] | None = None,
    text: str = "",
    attachments: list[str] | None = None,
    use_llm: bool = False,
    stop: threading.Event | None = None,
    history: list[dict[str, str]] | None = None,
    compact_summary: str | None = None,
    stream_mcp_step: Callable[..., Awaitable[ReactDecision]],
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    new_artifact: Callable[[], Any],
    trace: TraceContext,
    cancel: CancellationToken,
) -> Any:
    """ReAct 行动：优先 MCP JSON 多轮循环，失败则按 tools_needed 串行。"""
    from app.harness.orchestration.react_adapter import _missing_for_kind, build_proposed_spec

    react = prior or new_artifact()
    _ = PARALLEL_READONLY_TOOLS
    cap = rounds_cap(plan.budget.get("max_tool_rounds"))
    turn_attachments = list(attachments or [])
    orch = trace.child("orchestration.react")
    started = time.perf_counter()

    async def _body() -> Any:
        try:
            if use_llm:
                await _run_mcp_react_loop(
                    db,
                    plan,
                    react,
                    user_id=user_id,
                    emit=emit,
                    check_abort=check_abort,
                    slash_fill_first=slash_fill_first,
                    text=text,
                    attachments=turn_attachments,
                    stop=stop or cancel.stop,
                    history=list(history or []),
                    compact_summary=compact_summary,
                    rounds_limit=cap,
                    stream_mcp_step=stream_mcp_step,
                    execute_short_tool=execute_short_tool,
                    execute_isolated=execute_isolated,
                    trace=trace,
                    cancel=cancel,
                )
        except TurnCancelled:
            agent_trace("ReAct 已取消，停止继续调用模型")
            raise

        remaining = list(extra_tools) if extra_tools is not None else list(plan.tools_needed)
        if extra_tools is not None:
            need_queue = bool(remaining)
        elif not react.used_llm:
            need_queue = bool(remaining)
        elif slash_fill_first and plan.delivery == "confirm":
            spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
            react.proposed_spec = spec
            need_queue = bool(remaining) and bool(spec and _missing_for_kind(spec))
        elif (
            plan.intent in {"benchmark", "rag", "testcase"}
            and plan.delivery == "confirm"
            and bool(remaining)
            and not _executed_names(react)
            and not (react.reply_text or "").strip()
        ):
            need_queue = True
        else:
            need_queue = False

        try:
            if need_queue:
                await _run_tool_queue(
                    db,
                    plan,
                    react,
                    queue=remaining,
                    user_id=user_id,
                    emit=emit,
                    check_abort=check_abort,
                    slash_fill_first=slash_fill_first,
                    text=text,
                    attachments=turn_attachments,
                    rounds_limit=cap,
                    execute_short_tool=execute_short_tool,
                    execute_isolated=execute_isolated,
                    trace=trace,
                    cancel=cancel,
                )
            elif not remaining and not react.used_llm:
                react.proposed_spec = build_proposed_spec(
                    plan, react, slash_fill_first=slash_fill_first
                )
                return react
        except TurnCancelled:
            agent_trace("ReAct 已取消，停止继续调用模型")
            raise

        if react.proposed_spec is None:
            react.proposed_spec = build_proposed_spec(plan, react, slash_fill_first=slash_fill_first)
        return react

    with using_trace(orch):
        try:
            return await _body()
        finally:
            publisher().record_span(
                orch, latency_ms=round((time.perf_counter() - started) * 1000)
            )


def execute_short_tool_isolated(
    name: str,
    arguments: dict,
    user_id: str,
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
) -> tuple[bool, Any, str | None, int]:
    """耗时短工具用独立会话在线程里跑。"""
    from app.db import SessionLocal

    isolated = SessionLocal()
    try:
        return execute_short_tool(isolated, name, arguments, user_id=user_id, allow_create=False)
    finally:
        isolated.close()


execute_short_tool_isolated._harness_native = True  # type: ignore[attr-defined]
