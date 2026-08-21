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
    TOOL_TITLES,
    is_long_tool,
)
from app.agent.log import agent_exception, agent_trace
from app.agent.persona import react_system, turn_system
from app.agent.plan import PlanArtifact, parse_json_object
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.errors import MissingTraceContext, TraceMismatch
from app.harness.contracts.tool_call import OutcomeStatus, ToolCall
from app.harness.contracts.trace import TraceContext, using_trace
from app.harness.execution.facade import bind_arguments
from app.harness.execution.facade import execute as execute_tool
from app.harness.feedback.normalizer import normalize
from app.harness.feedback.observation import collect_ids, summarize_observation
from app.harness.feedback.publisher import publisher
from app.harness.feedback.redaction import redact_secrets
from app.harness.orchestration.budgets import (
    consecutive_retryable_error_cap,
    rounds_cap,
    same_call_fingerprint_cap,
)
from app.harness.orchestration.parser import McpStep, parse_mcp_step, validate_react_output

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
        react.observations.append(summarize_observation(name, False, None, error, 0))
        agent_trace(f"ToolCall 拒绝长任务 name={name}")
        return False
    if name not in SHORT_TOOLS:
        error = f"未知短工具「{name}」"
        await emit("tool_call", {"name": name, "arguments": arguments})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(summarize_observation(name, False, None, error, 0))
        agent_trace(f"ToolCall 拒绝未知工具 name={name}")
        return False
    if name == "task.create":
        error = "task.create 只允许在确认卡 ack 之后执行"
        await emit("tool_call", {"name": name, "arguments": {}})
        await emit("tool_result", {"name": name, "ok": False, "error": error, "latency_ms": 0})
        react.observations.append(summarize_observation(name, False, None, error, 0))
        agent_trace("ToolCall 拒绝 task.create（须 ack 后）")
        return False

    bound = bind_arguments(db, name, arguments, text=text, attachments=attachments)
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
        summarize_observation(result.tool, result.ok, result.data, result.error, result.latency_ms)
    )
    if result.status in {OutcomeStatus.CANCELLED, OutcomeStatus.CANCEL_REQUESTED}:
        raise TurnCancelled(cancel.reason or "cancelled")
    cancel.raise_if_cancelled()
    return result.ok


def _call_mcp_step(
    db: Session,
    *,
    system: str,
    payload: dict,
    stop: threading.Event,
    cancel: CancellationToken,
) -> McpStep:
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
    parsed = validate_react_output(parse_json_object(result.text))
    step = parse_mcp_step(parsed)
    step.latency_ms = result.latency_ms
    return step


async def stream_mcp_step(
    *,
    system: str,
    payload: dict,
    stop: threading.Event,
    emit: EmitFn,
    trace: TraceContext,
    cancel: CancellationToken,
) -> McpStep:
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
                timeout_s=90,
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
                        ).result(timeout=30)
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
            parsed = validate_react_output(parse_json_object(content))
        except ValueError:
            agent_trace("ReAct 流式 JSON 解析失败，回退非流式决策")
            isolated = SessionLocal()
            try:
                step = _call_mcp_step(
                    isolated, system=system, payload=payload, stop=stop, cancel=cancel
                )
            finally:
                isolated.close()
            step.reasoning_text = reasoning
            if not step.latency_ms:
                step.latency_ms = latency_ms
            publisher().record_span(
                parse_span, latency_ms=round((time.perf_counter() - started) * 1000)
            )
            return step
        step = parse_mcp_step(parsed)
        step.latency_ms = latency_ms
        step.reasoning_text = reasoning
        publisher().record_span(
            parse_span, latency_ms=round((time.perf_counter() - started) * 1000)
        )
        return step


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
    stream_mcp_step: Callable[..., Awaitable[McpStep]],
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    trace: TraceContext,
    cancel: CancellationToken,
) -> None:
    """多轮 MCP ReAct：思考卡 → 一个短工具 → 观察 → 再思考。"""
    from app.agent.react import _missing_for_kind, _redirect_creative_tool, build_proposed_spec

    system = turn_system(
        react_system(),
        skill_id=plan.skill_id if plan.delivery == "confirm" else None,
        compact_summary=compact_summary,
    )
    executed_calls: dict[tuple[str, str], int] = {}
    consecutive_retryable = 0

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
            step = await stream_mcp_step(
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

        react.used_llm = True
        if step.thought:
            react.thinking_text = (react.thinking_text + "\n" + step.thought).strip()[-12000:]
        if step.reasoning_text:
            react.thinking_text = (react.thinking_text + "\n" + step.reasoning_text).strip()[-12000:]
        elif step.thought:
            await _emit_react_thought(
                emit,
                step.thought,
                skill_id=plan.skill_id,
                latency_ms=step.latency_ms or None,
            )
        if step.reply:
            react.reply_text = step.reply

        raw_tool = _redirect_creative_tool(plan, text, step.tool)
        if raw_tool and is_long_tool(raw_tool):
            await _emit_react_thought(
                emit,
                f"「{raw_tool}」是长任务，确认后由 Worker 入队执行，对话进程不跑完。",
                skill_id=plan.skill_id,
            )
            break
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
    from app.agent.react import _missing_for_kind, _redirect_creative_tool, build_proposed_spec

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
    stream_mcp_step: Callable[..., Awaitable[McpStep]],
    execute_short_tool: Callable[..., tuple[bool, Any, str | None, int]],
    execute_isolated: Callable[..., tuple[bool, Any, str | None, int]],
    new_artifact: Callable[[], Any],
    trace: TraceContext,
    cancel: CancellationToken,
) -> Any:
    """ReAct 行动：优先 MCP JSON 多轮循环，失败则按 tools_needed 串行。"""
    from app.agent.react import _missing_for_kind, build_proposed_spec

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
