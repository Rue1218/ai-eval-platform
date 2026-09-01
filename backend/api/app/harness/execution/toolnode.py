"""Harness 执行层：ToolNode 包装（M5 阶段 3，EX-1）。

``build_tool_node`` 返回 LangGraph 异步节点函数：消费 ``GraphState.pending_tool``
（当前 ToolCall 投影），经门禁 → 绑定 → **原生执行器或内部 MCP Host** → 归一为
``Observation``，写回 ``observations`` + ``tool_result`` 事件意图；不直接 emit。
同轮多个原生调用以 ``pending_tool_batch`` 保序，全部终态后才一次性组装
``native_messages`` 的 tool 回填。P3/P4 在 feature flag、协议档白名单与脚踢线
均允许时，只读波次可并行；写/bash/任务屏障仍串行。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from uuid import uuid4

from langgraph.config import get_config, get_stream_writer
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall, ToolResult, make_event
from app.harness.feedback.observation import normalize, normalize_exception
from app.harness.feedback.rules import GateContext, check_gates
from app.harness.memory import GraphState
from app.harness.orchestration.budget import from_dict, is_budget_exhausted

# 会话级占槽门禁（OR-7）：task.create/task.cancel 前查询会话活动任务
from app.harness.orchestration.gates import check_session_active_task

from .aliases import enforce_tool_argument_policy, normalize_tool_arguments
from .ask_user import answers_from_reply, first_option_labels, validate_questions
from .batch import (
    BatchItemStatus,
    batch_is_complete,
    batch_item_to_pending,
    mark_batch_items,
    native_result_messages,
    pending_batch_items,
    select_execution_wave,
)
from .binding import bind_attachments
from .context import ToolExecutionContext
from .dispatch import bash_approval_reason, bash_block_reason
from .mcp import MCPClientManager
from .native import NativeToolExecutor
from .native_results import NativeToolResultStore, runtime_thread_id
from .policy import DEFAULT_RECOVERY_POLICY, TOOL_STREAM_CHUNK_CHARS, stream_max_chars
from .registry import ToolRegistry, required_parameter_names, validate_tool_arguments
from .stream_metrics import get_default_stream_metrics
from .stream_policy import parallel_batch_allowed, profile_id_from_configurable


def _trace(message: str) -> None:
    """延迟导入追踪，避免 toolnode → agent 包初始化 → graph 的循环依赖。"""
    from app.agent.log import agent_trace

    agent_trace(message)


def seal_budget_if_exhausted(result: dict, state: GraphState) -> dict:
    """工具队列清空后若预算耗尽，补发 BUDGET_EXCEEDED 并结束回合。

    消费发生在 ``react_agent``；本函数只负责在回边 END 前补齐 error 事件，
    避免调用方看到「图静默结束」或再撞 ``GraphRecursionError``。
    拒绝路径若已有 error，只置 ``turn_failed``，不叠第二条。
    """
    if result.get("pending_tool"):
        return result
    budget = from_dict(state.get("budget") or {})
    if not is_budget_exhausted(budget):
        return result
    events = list(result.get("pending_events") or [])
    if not any(event.get("kind") == "error" for event in events):
        message = (
            "模型调用次数预算耗尽"
            if budget.model_calls <= 0
            else "工具轮次预算耗尽"
        )
        events.append(
            make_event("error", {"code": "BUDGET_EXCEEDED", "message": message})
        )
        result["pending_events"] = events
    result["turn_failed"] = True
    return result


def build_tool_node(
    registry: ToolRegistry,
    *,
    db_factory: Callable[[], object] | None = None,
    sandbox_dir: str | None = None,
    user_id: str = "",
    native_tool_results: NativeToolResultStore | None = None,
    native_executor: NativeToolExecutor | None = None,
    manager: MCPClientManager | None = None,
) -> Callable[[GraphState], Awaitable[dict]]:
    """构造 ToolNode 异步节点函数（EX-1）。

    ``db_factory`` 延迟提供 DB Session（节点内按需获取，避免跨 Session 传
    ORM 对象）；``sandbox_dir``/``user_id`` 为平台注入的默认值（模型不可传），
    优先读 ``RunnableConfig.configurable``（session/credentials/sandbox 命名空间）。
    ``native_tool_results`` 是不参与序列化的单回合原文存储；``native_executor``
    负责默认基础工具直连；``manager`` 只负责显式 MCP 扩展。缺少 MCP manager
    时基础工具不受影响，且不会隐式构建空 MCP Host。
    """

    executor = native_executor or NativeToolExecutor()

    async def tool_node(state: GraphState) -> dict:
        pending = state.get("pending_tool")
        if not pending:
            return {"pending_events": []}
        configurable = (get_config() or {}).get("configurable") or {}
        thread_id = runtime_thread_id(configurable)
        session_id = str(configurable.get("session", {}).get("id") or "")
        current_user = str(configurable.get("credentials", {}).get("user_id") or user_id)
        owned_file_ids = frozenset(configurable.get("assets", {}).get("file_ids") or ())
        sandbox_box = configurable.get("sandbox") or {}
        sandbox = str(sandbox_box.get("dir") or sandbox_dir or "")
        session_board = [
            dict(item)
            for item in (state.get("session_tasks") or [])
            if isinstance(item, Mapping)
        ]
        try:
            writer = get_stream_writer()
        except Exception:  # noqa: BLE001 —— 图外单测/同步调用没有 LangGraph writer
            writer = None
        loop = asyncio.get_running_loop()

        async def execute_one(pending_item: Mapping[str, object]) -> dict[str, object]:
            """执行单项：业务失败不抛出，以便并行波次隔离。"""
            try:
                return await execute_one_unguarded(pending_item)
            except asyncio.CancelledError:
                raise
            except GraphInterrupt:
                # ``interrupt()`` 不是工具错误：必须冒泡给 LangGraph 写检查点并暂停。
                # 吞掉它会导致确认卡已经展示、图却继续或返回失败的严重错位。
                raise
            except Exception as exc:
                _trace(f"工具执行隔离异常 type={type(exc).__name__}")
                call_id = str(pending_item.get("call_id") or "")
                name = str(pending_item.get("name") or "")
                return {
                    "call_id": call_id,
                    "name": name,
                    "native": bool(pending_item.get("native")),
                    "status": "failed",
                    "events": [
                        make_event(
                            "tool_result",
                            {
                                "call_id": call_id,
                                "name": name,
                                "ok": False,
                                "error": "工具执行失败",
                                "latency_ms": 0,
                                "truncated": False,
                                "redacted": True,
                            },
                        ),
                        make_event("error", {"code": "INTERNAL", "message": "工具执行失败"}),
                    ],
                    "observation": None,
                }

        async def execute_one_unguarded(pending_item: Mapping[str, object]) -> dict[str, object]:
            """单项执行本体；异常由外层隔离，避免 TaskGroup 取消同波次。"""
            call_id = str(pending_item.get("call_id") or f"toolcall_{uuid4().hex}")
            is_native = bool(pending_item.get("native"))
            call = ToolCall(
                name=str(pending_item.get("name") or ""),
                arguments=dict(pending_item.get("arguments") or {}),
                call_id=call_id,
            )
            events: list[dict] = []
            stream_chars = 0
            stream_seq = 0
            stream_line = 1
            recovery_policy = DEFAULT_RECOVERY_POLICY

            def emit_stream(frame: dict[str, object]) -> None:
                """在线程安全地投影 LangGraph custom 帧；缺少 writer 时静默降级。"""
                if writer is None:
                    return
                loop.call_soon_threadsafe(writer, frame)

            def emit_progress(stage: str, message: str) -> None:
                """发送不落库的工具阶段状态，前端仅原地更新已有 ToolCard。"""
                emit_stream(
                    {
                        "kind": "tool_progress",
                        "call_id": call.call_id,
                        "name": call.name,
                        "stage": stage,
                        "message": message[:160],
                    }
                )

            def emit_output(channel: str, text: str, start_line: int | None = None) -> None:
                """按块发送受控输出；总量受 stream_max_chars 限制，完整
                Observation 不进入浏览器。"""
                nonlocal stream_chars, stream_seq, stream_line
                remaining = stream_max_chars() - stream_chars
                if remaining <= 0 or not text:
                    return
                visible = text[:remaining]
                if len(visible) < len(text) and "\n" in visible:
                    visible = visible[: visible.rfind("\n") + 1]
                if not visible:
                    return
                line = start_line if start_line is not None else stream_line
                for index in range(0, len(visible), TOOL_STREAM_CHUNK_CHARS):
                    chunk = visible[index : index + TOOL_STREAM_CHUNK_CHARS]
                    if not chunk:
                        continue
                    stream_seq += 1
                    emit_stream(
                        {
                            "kind": "tool_output_delta",
                            "call_id": call.call_id,
                            "name": call.name,
                            "seq": stream_seq,
                            "channel": channel,
                            "text": chunk,
                            "start_line": line,
                        }
                    )
                    line += chunk.count("\n")
                    stream_chars += len(chunk)
                stream_line = line

            def display_preview(data: object) -> tuple[str, str, int | None]:
                """提取已经过 handler 投影的预览，供不支持原生回调的工具补发一次。"""
                if not isinstance(data, dict):
                    return "", "result", None
                for key, channel in (
                    ("read", "document"),
                    ("write", "document"),
                    ("bash", "stdout"),
                    ("web", "document"),
                ):
                    section = data.get(key)
                    if isinstance(section, dict) and isinstance(section.get("preview"), str):
                        raw_start = section.get("start_line")
                        return (
                            str(section["preview"]),
                            channel,
                            int(raw_start) + 1 if isinstance(raw_start, int) else 1,
                        )
                return "", "result", None

            def failed(
                code: str,
                message: str,
                *,
                status: str = "failed",
                emit_error: bool = True,
            ) -> dict[str, object]:
                """拒绝路径：同 call_id 的结果 + error，不推进批次（由外层合并）。"""
                if is_native and native_tool_results is not None:
                    native_tool_results.put(thread_id, call.call_id, message)
                result_event = make_event(
                    "tool_result",
                    {
                        "call_id": call.call_id,
                        "name": call.name,
                        "ok": False,
                        "status": status,
                        "error": message,
                        "latency_ms": 0,
                        "truncated": False,
                        "redacted": True,
                        "recovery": recovery_policy.to_payload(code, message),
                    },
                )
                return {
                    "call_id": call.call_id,
                    "name": call.name,
                    "native": is_native,
                    "status": status,
                    "events": [
                        *events,
                        result_event,
                        *(
                            [make_event("error", {"code": code, "message": message})]
                            if emit_error
                            else []
                        ),
                    ],
                    "observation": None,
                }

            if is_native and (native_tool_results is None or not thread_id):
                return failed("INTERNAL", "工具临时上下文不可用")
            definition = registry.find(call.name)
            if definition is None:
                return failed("VALIDATION", f"工具未注册：{call.name}")
            recovery_policy = definition.recovery_policy
            try:
                call = replace(
                    call,
                    arguments=normalize_tool_arguments(
                        call.name, call.arguments, definition.parameters_schema
                    ),
                )
                enforce_tool_argument_policy(call.name, call.arguments)
            except AppError as exc:
                return failed(exc.code.value, exc.message)
            schema_error = validate_tool_arguments(definition.parameters_schema, call.arguments)
            if schema_error:
                return failed("VALIDATION", schema_error)
            has_active_task = False
            if call.name in {"task.create", "task.cancel"} and db_factory is not None:
                gate_db = db_factory()
                try:
                    has_active_task = check_session_active_task(gate_db, session_id)
                finally:
                    gate_db.close()
            context = GateContext(
                session_id=session_id,
                user_id=current_user,
                has_active_task=has_active_task,
                owned_file_ids=owned_file_ids,
                registered_names=frozenset(registry.names()),
                required_slots={call.name: required_parameter_names(definition.parameters_schema)},
            )
            gate = check_gates(call, context)
            if not gate.passed:
                return failed(gate.failed_code or "VALIDATION", gate.failed_message or "门禁未通过")
            db = db_factory() if db_factory else None
            try:
                safe_args = bind_attachments(call.arguments, db, current_user)
            except AppError as exc:
                if db is not None:
                    db.rollback()
                return failed(exc.code.value, exc.message)
            except Exception as exc:
                if db is not None:
                    db.rollback()
                _trace(f"工具附件绑定异常 type={type(exc).__name__}")
                return failed("INTERNAL", "附件绑定失败")
            finally:
                if db is not None:
                    db.close()
            # LangGraph HITL：所有无法静态证明只读的 bash 命令必须在副作用前暂停。
            # call_id 同时是确认卡 ID，图从检查点恢复时会重进本节点并拿到 decision。
            if call.name == "bash":
                command = str(safe_args.get("command") or "")
                if blocked := bash_block_reason(command):
                    return failed("VALIDATION", blocked)
                reason = bash_approval_reason(command)
                if reason:
                    decision = interrupt(
                        {
                            "type": "tool_approval",
                            "id": call.call_id,
                            "call_id": call.call_id,
                            "name": call.name,
                            "command": command,
                            "reason": reason,
                            "risk_level": "high",
                            "sandbox_scope": "仅当前会话工作区可写；网络关闭、系统目录只读且资源受限。",
                            "allowed_decisions": ["approve", "reject"],
                        }
                    )
                    action = decision.get("action") if isinstance(decision, Mapping) else None
                    approval_id = decision.get("id") if isinstance(decision, Mapping) else None
                    if approval_id != call.call_id or action not in {"approve", "reject"}:
                        return failed("VALIDATION", "确认结果无效，命令未执行")
                    if action == "reject":
                        return failed(
                            "VALIDATION",
                            "用户拒绝执行此 bash 命令",
                            status="rejected",
                            emit_error=False,
                        )
                    emit_progress("approved", "已获用户确认，正在进入受控沙箱执行")
            ask_user_raw = None
            if call.name == "ask_user_question":
                try:
                    questions = validate_questions(safe_args)
                except AppError as exc:
                    return failed(exc.code.value, exc.message)
                first = questions[0]
                reply = interrupt(
                    {
                        "type": "clarify",
                        "id": call.call_id,
                        "question": str(first.get("question") or ""),
                        "options": first_option_labels(first),
                        "questions": questions,
                    }
                )
                answers = answers_from_reply(questions, reply)
                ask_user_raw = ToolResult(
                    name=call.name,
                    ok=True,
                    data={
                        "summary": "用户已回复提问",
                        "model_text": "用户已回复提问",
                        "display": {"status": "success", "answers": answers},
                    },
                    call_id=call.call_id,
                )
            emit_progress("validating", "正在校验工具参数与权限边界")
            emit_progress("executing", "工具正在受控执行")
            started = time.perf_counter()
            exec_context = ToolExecutionContext(
                session_id=session_id,
                user_id=current_user,
                thread_id=thread_id,
                sandbox_dir=sandbox,
                owned_file_ids=owned_file_ids,
                call_id=call.call_id,
                report_progress=emit_progress,
                report_output=emit_output,
                session_tasks=session_board,
            )
            try:
                if ask_user_raw is not None:
                    raw = ask_user_raw
                elif definition.transport == "native":
                    raw = await executor.call(definition, safe_args, exec_context)
                elif manager is None:
                    raise AppError(ErrorCode.INTERNAL, "MCP 工具执行器不可用")
                else:
                    raw = await manager.call_tool(definition.tool_id, safe_args, exec_context)
            except asyncio.CancelledError:
                raise
            except Exception:
                observation = normalize_exception(
                    AppError(ErrorCode.INTERNAL, "工具执行失败"),
                    tool=call.name,
                    arguments=dict(call.arguments or {}),
                )
            else:
                observation = normalize(
                    raw,
                    None,
                    tool=call.name,
                    arguments=dict(call.arguments or {}),
                )
            latency_ms = round((time.perf_counter() - started) * 1000)
            emit_progress("finalizing", "正在整理安全输出")
            _trace(
                f"tool done name={call.name} latency_ms={latency_ms} "
                f"model_chars={len(observation.text)} ok={observation.ok}"
            )
            result_payload: dict[str, object] = {
                "call_id": call.call_id,
                "name": call.name,
                "ok": observation.ok,
                "latency_ms": latency_ms,
                "truncated": observation.truncated,
                "redacted": observation.redacted,
            }
            if observation.source:
                result_payload["source"] = observation.source
            if observation.ok:
                result_payload["data"] = dict(observation.display_data)
                if stream_chars == 0 and definition.supports_streaming:
                    preview, channel, start_line = display_preview(observation.display_data)
                    emit_output(channel, preview, start_line)
            else:
                result_payload["error"] = observation.text
                result_payload["recovery"] = dict(observation.recovery) or recovery_policy.to_payload(
                    observation.error_code or "INTERNAL", observation.repair_hint
                )
            events.append(make_event("tool_result", result_payload))
            checkpoint_observation = observation
            if is_native:
                if native_tool_results is None or not native_tool_results.put(
                    thread_id, call.call_id, observation.text
                ):
                    _trace("原生工具结果临时存储失败")
                    return failed("INTERNAL", "工具临时上下文不可用")
                checkpoint_observation = replace(
                    observation,
                    text=f"工具 {call.name} 已执行；完整结果仅在当前回合供模型使用。",
                )
            return {
                "call_id": call.call_id,
                "name": call.name,
                "native": is_native,
                "status": "succeeded" if observation.ok else "failed",
                "events": events,
                "observation": checkpoint_observation,
            }

        raw_batch = state.get("pending_tool_batch")
        batch = dict(raw_batch) if isinstance(raw_batch, Mapping) else None
        queue = (
            pending_batch_items(batch)
            if batch and batch.get("items")
            else [dict(pending), *[dict(item) for item in (state.get("pending_tools") or [])]]
        )
        class_of = {
            definition.name: definition.concurrency_class for definition in registry.iter_defs()
        }
        prior_of = {
            definition.name: definition.requires_prior_result for definition in registry.iter_defs()
        }
        # 无显式 ToolBatch 时保持 P2 一次一项，避免隐式队列并行后回填顺序漂移。
        profile_id = profile_id_from_configurable(configurable)
        enabled = parallel_batch_allowed(profile_id, has_batch=bool(batch))
        max_parallel = int(settings.max_parallel_tool_calls or 1)
        wave_started = time.perf_counter()
        wave = select_execution_wave(
            queue,
            class_of=class_of,
            prior_of=prior_of,
            enabled=enabled,
            max_parallel=max_parallel,
            sandbox_dir=sandbox,
        ) or [dict(pending)]
        _trace(
            f"tool_batch wave={len(wave)} parallel={enabled and len(wave) > 1} "
            f"names={','.join(str(item.get('name') or '') for item in wave)}"
        )
        if len(wave) == 1:
            outcomes = [await execute_one(wave[0])]
        else:
            try:
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(execute_one(item)) for item in wave]
                outcomes = [task.result() for task in tasks]
            except* GraphInterrupt as group_exc:
                # TaskGroup 会把子任务的 GraphInterrupt 包装进 ExceptionGroup，
                # 裸 except 与 LangGraph 运行时都无法识别 → 中断语义丢失（节点
                # 报错而非暂停）。当前并行波次仅只读工具、bash 恒独占波次，不会
                # 走到这里；此解包是对未来并行面扩大的纵深防御。
                raise group_exc.exceptions[0] from None
        get_default_stream_metrics().record_batch(
            duration_ms=round((time.perf_counter() - wave_started) * 1000),
            wave_size=len(wave),
            parallel=enabled and len(wave) > 1,
        )

        events: list[dict] = []
        observations: list[object] = []
        updates: list[tuple[str, BatchItemStatus]] = []
        any_native = False
        for outcome in outcomes:
            events.extend(list(outcome.get("events") or []))
            observation = outcome.get("observation")
            if observation is not None:
                observations.append(observation)
            status: BatchItemStatus = (
                "succeeded" if str(outcome.get("status") or "") == "succeeded" else "failed"
            )
            updates.append((str(outcome.get("call_id") or ""), status))
            any_native = any_native or bool(outcome.get("native"))

        updated_batch = mark_batch_items(batch, updates) if batch else None
        if updated_batch is not None:
            waiting = pending_batch_items(updated_batch)
            next_pending = batch_item_to_pending(waiting[0]) if waiting else None
            remaining = [batch_item_to_pending(item) for item in waiting[1:]]
            should_flush = batch_is_complete(updated_batch)
        else:
            leftover = [dict(item) for item in (state.get("pending_tools") or [])]
            next_pending = leftover.pop(0) if leftover else None
            remaining = leftover
            should_flush = True

        result: dict[str, object] = {
            "pending_tool": next_pending,
            "pending_tools": remaining,
            "pending_events": events,
            "session_tasks": session_board,
        }
        if observations:
            result["observations"] = observations
        if updated_batch is not None:
            result["pending_tool_batch"] = updated_batch
        if any_native and should_flush:
            result["native_messages"] = (
                native_result_messages(updated_batch)
                if updated_batch is not None
                else [
                    {
                        "role": "tool",
                        "tool_call_id": str(outcomes[0].get("call_id") or ""),
                        "name": str(outcomes[0].get("name") or ""),
                        "content": "",
                    }
                ]
            )
        return seal_budget_if_exhausted(result, state)

    return tool_node
