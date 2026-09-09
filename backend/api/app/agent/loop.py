"""以持久事实驱动的七节点 Agent 回合；WS 只提交命令和观察事实。

ReAct 主线（保持该顺序不变）：
``pre_step -> model -> tools -> close_step -> decide_next``。
模型提出工具调用后，工具结果会作为 ``role=tool`` 消息追加到历史，下一
个 Step 再把“模型调用 + 工具观察”一起交给模型。``retry_wait`` 只重试
同一个 Step 的模型 Attempt，不会额外消耗 Step；``finalize_turn`` 只负责
写本轮终态。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.agent.loop_settings import LoopSettings
from app.agent.stream import AssistantAttempt
from app.llm.loop_contracts import (
    LlmAdapter,
    LlmRequest,
    LlmRequestError,
    Message,
    ReasoningDelta,
    ReasoningEffort,
    TextDelta,
    ToolSpec,
    is_retryable_error,
)

if TYPE_CHECKING:
    from app.harness.execution.scheduler import ToolScheduler
    from app.harness.memory.agent_events import SessionLog

SYSTEM_PROMPT = "你是平台助手。按已提供的工具契约执行任务，如实报告工具结果。"

# 工厂接收当前事实历史和每回合思考覆盖，返回完整且固定的模型请求。
RequestFactory = Callable[[list[Message], ReasoningEffort | None], LlmRequest]


def _override_reasoning(request: LlmRequest, effort: ReasoningEffort) -> LlmRequest:
    """覆盖模板档位后重算协议派生选项，保留独立的缓存和协议版本配置。"""
    from app.llm.providers.options import resolve_options

    options = {key: value for key, value in request.provider_options.items()
               if key in {"prompt_cache", "anthropic_version"}}
    updated = replace(request, reasoning_effort=effort, thinking=effort != "off",
                      reasoning_enabled=effort != "off", provider_options=options)
    # 源五参数请求允许不声明协议，此时仍由注入的 adapter 解析 wire 参数。
    if updated.protocol is None:
        return updated
    provider = updated.provider or (
        "anthropic" if updated.protocol == "anthropic_messages" else "openai"
    )
    resolved = resolve_options(updated, provider, updated.protocol)
    return replace(updated, provider_options={**options, **resolved})


def _history_selection(messages: list[Message], selected: list[Message]) -> dict[str, Any]:
    """以有序索引追踪真实模型输入，不额外持久化一份历史正文。"""
    start = len(messages) - len(selected)
    if start >= 0 and messages[start:] == selected:
        indices = list(range(start, len(messages)))
    else:
        indices, position = [], 0
        for message in selected:
            while position < len(messages) and messages[position] != message:
                position += 1
            if position == len(messages):
                raise LlmRequestError("模型输入无法对应持久历史", code="history_selection")
            indices.append(position)
            position += 1
    return {
        "algorithm": "message_indices.v1", "indices": indices,
        "message_count": len(messages),
        "input_fingerprint": hashlib.sha256(
            json.dumps(selected, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


@dataclass(frozen=True)
class TurnDependencies:
    """每回合固定的模型、工具及请求配置，不进入图状态或跨会话模型缓存。"""

    adapter: LlmAdapter
    scheduler: ToolScheduler | None = None
    request: LlmRequest | None = None
    request_factory: RequestFactory | None = None
    # 平台配置的容量只用于真实请求展示，不改变核心循环窗口策略。
    context_window: int | None = None
    # 工具 wire 名到执行通道的本轮快照，仅用于上下文用量展示，不参与模型路由。
    tool_transports: dict[str, str] | None = None


FinishReason = Literal["completed", "error", "max_tokens", "max_steps"]


class AgentState(TypedDict, total=False):
    """可序列化的执行快照，持久事件始终是历史权威。"""

    # 本次图运行的身份与循环计数。Turn 是用户请求；Step 是一次模型响应及其工具处理。
    session_id: str
    turn: int
    step: int
    steps_used: int
    model_attempts: int
    phase: str

    # 下一次模型请求使用的完整有效历史。节点返回新列表，避免覆盖旧消息。
    messages: list[Message]

    # 最近一次模型请求头的可追溯信息；历史消息本身不在 fingerprint 中。
    request_fingerprint: str | None
    request_header_seq: int | None
    request_header_reason: str | None

    # 当前模型 Attempt 的结果，以及等待工具节点结算的调用。
    attempt_id: str
    pending_calls: list[dict[str, Any]]
    model_finish: str
    allow_tool_dispatch: bool

    # 路由和收尾使用的错误、重试与结束状态。
    model_error: str
    model_error_code: str
    retryable_error: bool
    step_open: bool
    continue_loop: bool
    stop_reason: FinishReason
    usage: dict[str, int]
    last_event_seq: int


@dataclass(frozen=True)
class GraphRunContext:
    """当前回合的活依赖，不写入可序列化图状态。"""

    session_id: str
    turn: int
    log: SessionLog
    dependencies: TurnDependencies | None = None


def _context(config: RunnableConfig) -> GraphRunContext:
    """读取配置内的回合依赖，拒绝缺少上下文的图调用。"""
    configurable = config.get("configurable", {})
    context = configurable.get("run_context")
    if not isinstance(context, GraphRunContext):
        raise RuntimeError("agent graph requires GraphRunContext in configurable.run_context")
    return context


def _reasoning_effort(config: RunnableConfig, settings: LoopSettings) -> ReasoningEffort:
    """读取已验证的每回合思考配置覆盖。"""
    configured = config.get("configurable", {}).get("reasoning_effort")
    if configured in ("off", "low", "medium", "high", "xhigh", "max"):
        return configured
    return settings.dsh_reasoning_effort


def _emit(kind: str, event: dict[str, Any], **data: Any) -> None:
    """通过图自定义流发布已提交事实；正文片段仅引用已提交身份。"""
    # 这里的 seq/ts 来自已经写入 SessionLog 的 event。文本和推理 delta 是
    # 例外：它们引用 attempt_start 的已提交身份，但自身不会逐片段落盘。
    get_stream_writer()(
        {
            "kind": kind,
            "seq": event["seq"],
            "event_ts": event["ts"],
            "record_type": event["type"],
            **data,
        }
    )


def _truncated(finish_reason: str) -> bool:
    """识别需要停止派发的 token 截断终态。"""
    return finish_reason in ("length", "max_tokens")


def _terminal_failure(finish_reason: str) -> bool:
    """识别供应商明确失败或未知的终态。"""
    return finish_reason not in ("stop", "tool_calls", "length", "max_tokens")


async def build_agent(
    settings: LoopSettings,
    *,
    adapter: LlmAdapter | None = None,
    model: str | None = None,
    tools: list[Any] | None = None,
    specs: list[ToolSpec] | None = None,
    scheduler: ToolScheduler | None = None,
    request: LlmRequest | None = None,
    request_factory: RequestFactory | None = None,
    system: str = SYSTEM_PROMPT,
):
    """构建七节点循环；工具和模型由调用者注入，不创建 SQLite 或源内置工具。

    应用共享图时仅设置运行限额，通过 GraphRunContext.dependencies 绑定每回合
    的模型及调度器。显式 adapter 等默认值用于单运行时装配和聚焦测试。
    """
    if specs is None and tools is not None:
        from app.harness.execution.loop_tools import tool_spec

        specs = [tool_spec(tool) for tool in tools]
    specs = list(specs or [])
    if scheduler is None and tools is not None:
        from app.harness.execution.scheduler import ToolScheduler

        scheduler = ToolScheduler(settings, tools)
    model = model or settings.dsh_model

    def dependencies(config: RunnableConfig) -> TurnDependencies:
        """优先读取回合依赖，拒绝缺少模型配置的执行。"""
        current = _context(config).dependencies
        if current is not None:
            return current
        if adapter is None:
            raise RuntimeError("agent loop requires a per-turn adapter")
        return TurnDependencies(adapter, scheduler, request, request_factory)

    async def pre_step(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """检查步数预算并持久开启下一步。"""
        context = _context(config)
        if state.get("steps_used", 0) >= settings.dsh_max_steps:
            # 没有预算时不要创建虚假的 step/start；路由会直接转到 finalize_turn。
            return {
                "phase": "finalizing",
                "stop_reason": "max_steps",
                "continue_loop": False,
            }

        # 一个新 Step 从持久 step/start 开始。先写日志、再发布实时事件，保证
        # 浏览器看到的 Step 都能在历史中找到对应事实。
        step = state.get("step", 0) + 1
        event = context.log.append("step/start", {"turn": context.turn, "step": step})
        _emit("step_start", event, turn=context.turn, step=step)
        return {
            "step": step,
            "steps_used": state.get("steps_used", 0) + 1,
            "model_attempts": 0,
            "phase": "model",
            "step_open": True,
            "pending_calls": [],
            "model_error": "",
            "retryable_error": False,
            "model_finish": "",
            "last_event_seq": event["seq"],
        }

    async def call_model(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """执行一次模型 Attempt，完成校验后才提交助手消息。"""
        context = _context(config)
        model_attempts = state.get("model_attempts", 0) + 1
        # 组装 Provider 无关的请求。Adapter 负责转换成具体 SDK 的 wire 格式；
        # 图节点不依赖 OpenAI/DeepSeek 的原始 chunk 结构。
        current = dependencies(config)
        effort = _reasoning_effort(config, settings)
        if current.request_factory is not None:
            request = current.request_factory(deepcopy(state["messages"]), effort)
        elif current.request is not None:
            request = replace(current.request, messages=deepcopy(state["messages"]))
            if config.get("configurable", {}).get("reasoning_effort") is not None:
                request = _override_reasoning(request, effort)
        else:
            if not model:
                raise ValueError("agent loop requires a model or request template")
            request = LlmRequest(
                provider=settings.dsh_provider,
                model=model,
                messages=deepcopy(state["messages"]),
                system=system,
                tools=specs,
                max_tokens=settings.dsh_max_tokens,
                reasoning_effort=effort,
            )
        selection = _history_selection(state["messages"], request.messages)
        # 请求头变化时单独记录，让历史回放能知道模型当时看到的模型、系统提示词
        # 和工具 schema。messages 是历史主体，不会被这个 fingerprint 覆盖。
        fingerprint = request.fingerprint()
        header_seq = state.get("request_header_seq")
        forced_header_reason = state.get("request_header_reason")
        if forced_header_reason or state.get("request_fingerprint") != fingerprint:
            header = context.log.append(
                "request/header",
                {
                    "turn": context.turn,
                    "step": state["step"],
                    "reason": forced_header_reason
                    or ("initial" if state.get("request_fingerprint") is None else "change"),
                    "fingerprint": fingerprint,
                    "header": request.header(),
                },
            )
            _emit(
                "request_header",
                header,
                turn=context.turn,
                step=state["step"],
                reason=header["data"]["reason"],
                fingerprint=fingerprint,
                header=request.header(),
            )
            header_seq = header["seq"]

        # Attempt 是“同一 Step 的一次具体模型请求”。网络重试会创建新的 Attempt，
        # 但不会重新创建 Step。
        attempt_id = f"a-{uuid.uuid4().hex[:12]}"
        from .loop_presentation import request_summary

        start = context.log.append(
            "assistant/attempt_start",
            {
                "turn": context.turn,
                "step": state["step"],
                "attempt_id": attempt_id,
                "header_seq": header_seq,
                "history_upto_seq": context.log.read()[-1]["seq"],
                "history_selection": selection,
                "request_summary": request_summary(
                    request, context_window=current.context_window,
                    history_upto_seq=context.log.read()[-1]["seq"],
                    input_fingerprint=selection["input_fingerprint"],
                    tool_transports=current.tool_transports,
                ),
                "fingerprint_algorithm": "dsh-json-v1",
            },
        )
        _emit(
            "assistant_attempt_start",
            start,
            attempt_id=attempt_id,
            turn=context.turn,
            step=state["step"],
            header_seq=header_seq,
            history_upto_seq=start["data"]["history_upto_seq"],
        )

        # 先缓存流片段，只有收到 Done 并通过校验后才形成正式 assistant/message。
        # 因此尚未完成的工具参数不会被提前执行。
        attempt = AssistantAttempt()
        # 仅统计本次模型流从建连到完成的耗时，不混入工具执行或整个回合等待时间。
        model_started_at = time.perf_counter()
        try:
            model_stream = current.adapter.stream(request)
            try:
                async for chunk in model_stream:
                    chunk_index = attempt.push(chunk)
                    if isinstance(chunk, TextDelta):
                        # 文本 delta 可实时显示，但不会逐片段写入 持久事件日志；最终消息才是
                        # 下一轮模型上下文和重连历史的权威来源。
                        _emit(
                            "text",
                            start,
                            content=chunk.text,
                            attempt_id=attempt_id,
                            turn=context.turn,
                            step=state["step"],
                            chunk_index=chunk_index,
                        )
                    elif isinstance(chunk, ReasoningDelta):
                        # 推理内容与用户可见正文分开推送、分开保存，避免混入最终回答文本。
                        _emit(
                            "reasoning",
                            start,
                            content=chunk.text,
                            attempt_id=attempt_id,
                            turn=context.turn,
                            step=state["step"],
                            chunk_index=chunk_index,
                        )
            finally:
                close_stream = getattr(model_stream, "aclose", None)
                if close_stream is not None:
                    await close_stream()
        except asyncio.CancelledError:
            # 已显示正文前缀可以安全地成为历史，但未完成的工具调用不能带入下一轮；
            # 这是取消时唯一允许写入模型可见历史的半成品。
            if attempt.text:
                prefix: Message = {"role": "assistant", "content": attempt.text}
                if attempt.reasoning_content:
                    prefix["reasoning_content"] = attempt.reasoning_content
                committed = context.log.append(
                    "assistant/message",
                    {
                        "turn": context.turn,
                        "step": state["step"],
                        "attempt_id": attempt_id,
                        "message": prefix,
                        "content": attempt.text,
                        "reasoning_content": attempt.reasoning_content,
                        "interrupted": True,
                    },
                )
                _emit(
                    "assistant_message",
                    committed,
                    attempt_id=attempt_id,
                    turn=context.turn,
                    step=state["step"],
                    content=attempt.text,
                    reasoning_content=attempt.reasoning_content,
                    tool_calls=[],
                    usage={},
                    finish_reason="cancelled",
                    interrupted=True,
                )
                _emit(
                    "assistant_end",
                    committed,
                    attempt_id=attempt_id,
                    turn=context.turn,
                    step=state["step"],
                    outcome="committed",
                    committed_seq=committed["seq"],
                    interrupted=True,
                )
            else:
                _emit(
                    "assistant_end",
                    start,
                    attempt_id=attempt_id,
                    turn=context.turn,
                    step=state["step"],
                    outcome="abandoned",
                    committed_seq=None,
                    interrupted=True,
                )
            raise
        except Exception as exc:
            error_message = str(exc) if isinstance(exc, LlmRequestError) else "模型请求失败"
            error_code = getattr(exc, "code", "provider_error")
            failed = context.log.append(
                "assistant/attempt",
                {
                    "turn": context.turn,
                    "step": state["step"],
                    "attempt_id": attempt_id,
                    "error": error_message,
                    "error_code": error_code,
                    "usage": attempt.done.usage if attempt.done else {},
                },
            )
            _emit(
                "assistant_end",
                failed,
                attempt_id=attempt_id,
                turn=context.turn,
                step=state["step"],
                outcome="failed",
                committed_seq=failed["seq"],
                error=error_message,
                error_code=error_code,
            )
            return {
                "attempt_id": attempt_id,
                "request_fingerprint": fingerprint,
                "request_header_seq": header_seq,
                "request_header_reason": None,
                "model_error": error_message,
                "model_error_code": error_code,
                "retryable_error": is_retryable_error(exc),
                "model_attempts": model_attempts,
                "model_finish": "error",
                "pending_calls": [],
                "allow_tool_dispatch": False,
                "last_event_seq": failed["seq"],
            }

        if attempt.done is None:
            failed = context.log.append(
                "assistant/attempt",
                {
                    "turn": context.turn,
                    "step": state["step"],
                    "attempt_id": attempt_id,
                    "error": "provider stream ended without a finish reason",
                    "error_code": "missing_finish",
                },
            )
            _emit(
                "assistant_end",
                failed,
                attempt_id=attempt_id,
                turn=context.turn,
                step=state["step"],
                outcome="failed",
                committed_seq=failed["seq"],
                error="provider stream ended without a finish reason",
                error_code="missing_finish",
            )
            return {
                "attempt_id": attempt_id,
                "request_fingerprint": fingerprint,
                "request_header_seq": header_seq,
                "request_header_reason": None,
                "model_error": "provider stream ended without a finish reason",
                "model_error_code": "missing_finish",
                "retryable_error": False,
                "model_attempts": model_attempts,
                "model_finish": "error",
                "pending_calls": [],
                "allow_tool_dispatch": False,
                "last_event_seq": failed["seq"],
            }

        # Done 到达后才解析缓冲的工具参数并检查身份。调用存在不代表允许执行：
        # 下面的 allow_tool_dispatch 还会拦截截断或终态错误响应。
        calls = attempt.tool_calls
        # 截断仍要配齐模型已声明的工具结果；不完整原始块只保留诊断、不回传。
        protocol_errors = attempt.protocol_errors(
            allow_incomplete=_truncated(attempt.done.finish_reason)
            or _terminal_failure(attempt.done.finish_reason)
        )
        invalid = [*attempt.identity_errors(), *protocol_errors]
        call_ids = [call.get("id") for call in calls]
        if len(call_ids) != len(set(call_ids)):
            invalid.append("provider returned duplicate tool call ids")
        if (
            attempt.done.finish_reason == "stop"
            and not attempt.text
            and not attempt.reasoning_content
            and not calls
        ):
            invalid.append("provider returned an empty completed response")
        if invalid:
            error_code = (
                "empty_response"
                if invalid == ["provider returned an empty completed response"]
                else ("invalid_protocol_state" if protocol_errors else "invalid_tool_call")
            )
            failed = context.log.append(
                "assistant/attempt",
                {
                    "turn": context.turn,
                    "step": state["step"],
                    "attempt_id": attempt_id,
                    "error": "; ".join(invalid),
                    "error_code": error_code,
                    "usage": attempt.done.usage,
                },
            )
            _emit(
                "assistant_end",
                failed,
                attempt_id=attempt_id,
                turn=context.turn,
                step=state["step"],
                outcome="failed",
                committed_seq=failed["seq"],
                error="; ".join(invalid),
                error_code=error_code,
            )
            return {
                "attempt_id": attempt_id,
                "request_fingerprint": fingerprint,
                "request_header_seq": header_seq,
                "request_header_reason": None,
                "model_error": "; ".join(invalid),
                "model_error_code": error_code,
                "retryable_error": False,
                "model_attempts": model_attempts,
                "model_finish": "error",
                "pending_calls": [],
                "allow_tool_dispatch": False,
                "last_event_seq": failed["seq"],
            }

        # 完整 assistant 消息先提交，再同时作为图状态中的下一轮历史。
        assistant = attempt.message()
        latency_ms = round((time.perf_counter() - model_started_at) * 1000)
        if attempt.done.usage:
            assistant["usage"] = attempt.done.usage
        assistant["latency_ms"] = latency_ms
        assistant["source"] = {"provider": request.provider, "model": request.model}
        committed = context.log.append(
            "assistant/message",
            {
                "turn": context.turn,
                "step": state["step"],
                "attempt_id": attempt_id,
                "message": assistant,
                "content": assistant["content"],
                "tool_calls": calls,
                "reasoning_content": assistant.get("reasoning_content"),
                "usage": attempt.done.usage,
                "latency_ms": latency_ms,
                "finish_reason": attempt.done.finish_reason,
            },
        )
        _emit(
            "assistant_message",
            committed,
            attempt_id=attempt_id,
            turn=context.turn,
            step=state["step"],
            content=assistant["content"],
            reasoning_content=assistant.get("reasoning_content", ""),
            tool_calls=calls,
            usage=attempt.done.usage,
            latency_ms=latency_ms,
            finish_reason=attempt.done.finish_reason,
            source=assistant.get("source"),
            interrupted=False,
        )
        _emit(
            "assistant_end",
            committed,
            attempt_id=attempt_id,
            turn=context.turn,
            step=state["step"],
            outcome="committed",
            committed_seq=committed["seq"],
            interrupted=False,
        )
        terminal_error = _terminal_failure(attempt.done.finish_reason)
        return {
            "messages": [*state["messages"], assistant],
            "request_fingerprint": fingerprint,
            "request_header_seq": header_seq,
            "request_header_reason": None,
            "attempt_id": attempt_id,
            "pending_calls": calls,
            "model_finish": attempt.done.finish_reason,
            "allow_tool_dispatch": not (
                _truncated(attempt.done.finish_reason) or terminal_error
            ),
            "model_attempts": model_attempts,
            "retryable_error": False,
            "model_error": (
                f"provider finished with {attempt.done.finish_reason}"
                if terminal_error
                else ""
            ),
            "model_error_code": attempt.done.finish_reason if terminal_error else "",
            "usage": attempt.done.usage,
            "last_event_seq": committed["seq"],
        }

    async def run_tools(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """通过唯一调度器结算工具调用并将结果追加到下一步历史。"""
        context = _context(config)
        writer = get_stream_writer()
        # Scheduler 负责调用登记、参数验证、审批、并发/独占与结果结算。无论真正
        # dispatch、拒绝还是禁止 dispatch，它都会返回与模型调用顺序配对的 tool 消息。
        tool_scheduler = dependencies(config).scheduler
        if tool_scheduler is None:
            raise RuntimeError("agent loop requires a scheduler for tool calls")
        results = await tool_scheduler.execute(
            session_id=context.session_id,
            log=context.log,
            turn=context.turn,
            step=state["step"],
            attempt_id=state["attempt_id"],
            calls=state.get("pending_calls", []),
            emit=writer,
            allow_dispatch=state.get("allow_tool_dispatch", False),
            dispatch_block_code=(
                "truncated_model_response"
                if _truncated(state.get("model_finish", ""))
                else "terminal_model_response"
            ),
        )
        last_seq = context.log.read()[-1]["seq"]
        return {
            # 下一 Step 会将 assistant 的工具调用和这些 role=tool 观察一起交给模型。
            "messages": [*state["messages"], *results],
            "last_event_seq": last_seq,
        }

    async def retry_wait(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """同一步内记录重试并等待，取消可直接打断等待。"""
        context = _context(config)
        event = context.log.append(
            "assistant/retry",
            {
                "turn": context.turn,
                "step": state["step"],
                "attempt_id": state.get("attempt_id"),
                "retry_index": state["model_attempts"],
                "error": state["model_error"],
                "error_code": state.get("model_error_code"),
            },
        )
        _emit(
            "retry_wait",
            event,
            turn=context.turn,
            step=state["step"],
            attempt_id=state.get("attempt_id"),
            retry_index=state["model_attempts"],
            error=state["model_error"],
            error_code=state.get("model_error_code"),
        )
        await asyncio.sleep(settings.dsh_model_retry_delay_seconds)
        return {
            "model_error": "",
            "model_error_code": "",
            "model_finish": "",
            "retryable_error": False,
            "last_event_seq": event["seq"],
        }

    async def close_step(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """关闭已开启的步骤，避免重复终态。"""
        context = _context(config)
        if not state.get("step_open"):
            return {}
        event = context.log.append(
            "step/end",
            {
                "turn": context.turn,
                "step": state["step"],
                "reason": state.get("model_finish") or state.get("model_error") or "completed",
            },
        )
        _emit(
            "step_end",
            event,
            turn=context.turn,
            step=state["step"],
            reason=event["data"]["reason"],
        )
        return {"step_open": False, "last_event_seq": event["seq"]}

    def decide_next(state: AgentState) -> dict[str, Any]:
        # 这一步只根据已经结算的模型/工具结果做路由，不再调用模型或工具。
        """仅依据已结算结果决定下一步或回合结束。"""
        has_model_error = bool(state.get("model_error"))
        has_pending_calls = bool(state.get("pending_calls"))
        may_dispatch_tools = bool(state.get("allow_tool_dispatch"))
        response_was_truncated = _truncated(state.get("model_finish", ""))

        if has_model_error:
            # 模型错误已经在 call_model 中记录；当前 Turn 交给 finalize_turn 收尾。
            return {"continue_loop": False, "stop_reason": "error", "phase": "finalizing"}
        if has_pending_calls and may_dispatch_tools:
            # 工具节点已经把观察追加到 messages；回到 pre_step 发起下一轮 ReAct。
            return {"continue_loop": True, "phase": "next_step"}
        if has_pending_calls:
            # 调用存在但不能执行通常表示模型响应被截断或是终态错误；不能遗漏
            # 工具结果配对，但也不能继续执行新的模型循环。
            return {"continue_loop": False, "stop_reason": "max_tokens", "phase": "finalizing"}
        if response_was_truncated:
            # 没有工具调用但回答不完整，同样以 max_tokens 结束本次 Turn。
            return {"continue_loop": False, "stop_reason": "max_tokens", "phase": "finalizing"}
        # 正常回答且没有待处理工具调用：ReAct 循环完成。
        return {"continue_loop": False, "stop_reason": "completed", "phase": "finalizing"}

    async def finalize_turn(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """提交本回合唯一正常终态。"""
        context = _context(config)
        reason = state.get("stop_reason", "completed")
        event = context.log.append("turn/end", {"turn": context.turn, "reason": reason})
        _emit("turn_end", event, turn=context.turn, reason=reason)
        return {"phase": "finished", "last_event_seq": event["seq"]}

    def route_after_pre(state: AgentState) -> str:
        # pre_step 可能因 Step 额度耗尽设置 stop_reason；否则才允许调用模型。
        """预算耗尽时直接收尾，否则请求模型。"""
        return "model" if not state.get("stop_reason") else "finalize_turn"

    def route_after_model(state: AgentState) -> str:
        """同一步内分类重试，或进入工具结算及步骤收尾。"""
        has_retryable_failure = bool(state.get("model_error")) and bool(
            state.get("retryable_error")
        )
        retry_budget_remaining = (
            state.get("model_attempts", 0) <= settings.dsh_model_max_retries
        )
        if has_retryable_failure and retry_budget_remaining:
            # 只等待并重试模型 Attempt；不会重新执行前一轮已结算工具。
            return "retry_wait"

        has_tool_calls = bool(state.get("pending_calls"))
        # 有调用就一定经过 tools 节点：即使不允许 dispatch，也要生成与调用配对的
        # 拒绝/未开始结果；无调用时即可关闭本 Step。
        return "tools" if has_tool_calls else "close_step"

    def route_after_decide(state: AgentState) -> str:
        # 唯一的循环回边：只有工具观察有效进入历史后才会回到 pre_step。
        """仅在需要工具观察后的模型请求时回到循环入口。"""
        return "pre_step" if state.get("continue_loop") else "finalize_turn"

    # LangGraph 节点图就是上面 ReAct 顺序的可持久化表达。各节点通过返回 AgentState
    # 更新通信，WebSocket 不参与任何路由决定。
    graph = StateGraph(AgentState)
    graph.add_node("pre_step", pre_step)
    graph.add_node("model", call_model)
    graph.add_node("retry_wait", retry_wait)
    graph.add_node("tools", run_tools)
    graph.add_node("close_step", close_step)
    graph.add_node("decide_next", decide_next)
    graph.add_node("finalize_turn", finalize_turn)
    graph.add_edge(START, "pre_step")
    graph.add_conditional_edges("pre_step", route_after_pre)
    graph.add_conditional_edges("model", route_after_model)
    graph.add_edge("retry_wait", "model")
    graph.add_edge("tools", "close_step")
    graph.add_edge("close_step", "decide_next")
    graph.add_conditional_edges("decide_next", route_after_decide)
    graph.add_edge("finalize_turn", END)

    compiled = graph.compile()
    # LangGraph 默认 25 次转换不足以覆盖源默认 16 步；限额由相同预算推导。
    compiled.loop_recursion_limit = max(
        25, settings.dsh_max_steps * (5 + 2 * settings.dsh_model_max_retries) + 2
    )
    return compiled
