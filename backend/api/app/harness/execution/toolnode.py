"""Harness 执行层：ToolNode 包装（M5 阶段 3，EX-1）。

``build_tool_node`` 返回 LangGraph 异步节点函数：消费 ``GraphState.pending_tool``
（ToolCall 投影），经门禁 → 绑定 → **原生执行器或内部 MCP Host** → 归一为 ``Observation``，
写回 ``observations`` + ``tool_call/tool_result`` 事件意图；不直接 emit（事件
桥接契约）。``pending_tool`` 图外不持久化，回合结束随工作记忆清除（MEM-1）。

会话上下文（session_id/user_id/附件归属/沙箱目录）经
``RunnableConfig.configurable`` 注入（M4-Q2 命名空间约定），不入 GraphState。
基础工具经 ``NativeToolExecutor`` 直连受控 handler；只有评测/RAG 等显式 MCP
扩展才经 ``MCPClientManager``。两条路径均经线程池执行同步工具，避免 15s bash
沙箱调用阻塞 api 事件循环（影响其他 WS 连接心跳）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from uuid import uuid4

from langgraph.config import get_config

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall, make_event
from app.harness.feedback.observation import normalize, normalize_exception
from app.harness.feedback.rules import GateContext, check_gates
from app.harness.memory import GraphState
from app.harness.orchestration.budget import from_dict, is_budget_exhausted

# 会话级占槽门禁（OR-7）：task.create/task.cancel 前查询会话活动任务
from app.harness.orchestration.gates import check_session_active_task

from .binding import bind_attachments
from .context import ToolExecutionContext
from .mcp import MCPClientManager
from .native import NativeToolExecutor
from .native_results import NativeToolResultStore, runtime_thread_id
from .registry import ToolRegistry, required_parameter_names, validate_tool_arguments


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
        call_id = str(pending.get("call_id") or f"toolcall_{uuid4().hex}")
        is_native = bool(pending.get("native"))
        call = ToolCall(
            name=str(pending.get("name") or ""),
            arguments=dict(pending.get("arguments") or {}),
            call_id=call_id,
        )
        # 会话上下文：优先 configurable，回退构造参数
        configurable = (get_config() or {}).get("configurable") or {}
        thread_id = runtime_thread_id(configurable)
        session_id = str(configurable.get("session", {}).get("id") or "")
        current_user = str(configurable.get("credentials", {}).get("user_id") or user_id)
        owned_file_ids = frozenset(configurable.get("assets", {}).get("file_ids") or ())
        sandbox_box = configurable.get("sandbox") or {}
        sandbox = str(sandbox_box.get("dir") or sandbox_dir or "")
        events = [
            make_event(
                "tool_call",
                {"call_id": call.call_id, "name": call.name, "arguments": call.arguments},
            )
        ]
        remaining = [dict(item) for item in (state.get("pending_tools") or [])]
        next_pending = remaining.pop(0) if remaining else None

        def rejected(code: str, message: str) -> dict:
            """所有拒绝路径均补齐同 call_id 的结果，供模型与 ToolCard 收敛。"""
            failed_events = list(events)
            failed_events.extend(
                [
                    make_event(
                        "tool_result",
                        {
                            "call_id": call.call_id,
                            "name": call.name,
                            "ok": False,
                            "error": message,
                            "latency_ms": 0,
                            "truncated": False,
                            "redacted": True,
                        },
                    ),
                    make_event("error", {"code": code, "message": message}),
                ]
            )
            result: dict[str, object] = {
                "pending_tool": next_pending,
                "pending_tools": remaining,
                "pending_events": failed_events,
            }
            if is_native:
                if native_tool_results is not None:
                    native_tool_results.put(thread_id, call.call_id, message)
                result["native_messages"] = [
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        # 完整内容仅存单回合临时上下文，检查点保留关联 ID。
                        "content": "",
                    }
                ]
            return result

        if is_native and (native_tool_results is None or not thread_id):
            return seal_budget_if_exhausted(
                rejected("INTERNAL", "工具临时上下文不可用"),
                state,
            )
        definition = registry.find(call.name)
        if definition is None:
            return seal_budget_if_exhausted(
                rejected("VALIDATION", f"工具未注册：{call.name}"),
                state,
            )
        schema_error = validate_tool_arguments(definition.parameters_schema, call.arguments)
        if schema_error:
            return seal_budget_if_exhausted(rejected("VALIDATION", schema_error), state)
        # 1. 门禁（FB-2）：长工具/白名单/资产溯源/占槽等
        # 占槽门禁（OR-7）需要 DB 事实：task.create/task.cancel 时查询会话活动任务；
        # 无 db_factory（测试/纯内存路径）时保持 False，handler 内仍有兜底校验。
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
            return seal_budget_if_exhausted(
                rejected(gate.failed_code or "VALIDATION", gate.failed_message or "门禁未通过"),
                state,
            )
        # 2. 绑定（EX-2）：附件归属校验（db_factory 提供会话）
        db = db_factory() if db_factory else None
        try:
            safe_args = bind_attachments(call.arguments, db, current_user)
        except AppError as exc:
            if db is not None:
                db.rollback()
            return seal_budget_if_exhausted(rejected(exc.code.value, exc.message), state)
        except Exception as exc:
            if db is not None:
                db.rollback()
            from app.agent.log import agent_trace

            agent_trace(f"工具附件绑定异常 type={type(exc).__name__}")
            return seal_budget_if_exhausted(rejected("INTERNAL", "附件绑定失败"), state)
        finally:
            if db is not None:
                db.close()
        # 3. 执行（EX-3）：基础工具直连原生执行器；未来 MCP 扩展才经 Host。
        # 两条路径均在工作线程执行同步 handler，不阻塞 API 事件循环。
        started = time.perf_counter()
        context = ToolExecutionContext(
            session_id=session_id,
            user_id=current_user,
            thread_id=thread_id,
            sandbox_dir=sandbox,
            owned_file_ids=owned_file_ids,
            call_id=call.call_id,
        )
        try:
            if definition.transport == "native":
                raw = await executor.call(definition, safe_args, context)
            elif manager is None:
                raw = None
                raise AppError(ErrorCode.INTERNAL, "MCP 工具执行器不可用")
            else:
                raw = await manager.call_tool(definition.tool_id, safe_args, context)
        except asyncio.CancelledError:
            # /stop 等上游取消：穿透给图运行，不吞掉取消。
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
        from app.agent.log import agent_trace

        agent_trace(
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
            # 前端 ToolCard 只接收受控展示投影；完整 read 正文保留在 Observation，
            # 仅供下一轮模型使用，禁止进入 ws_events。
            result_payload["data"] = dict(observation.display_data)
        else:
            result_payload["error"] = observation.text
        events.append(
            make_event("tool_result", result_payload)
        )
        checkpoint_observation = observation
        if is_native:
            # 模型可见正文已按 MODEL_TOOL_RESULT_MAX_CHARS 收口；完整观察只供
            # 当前图运行期的下一模型回合使用，不能与 native_messages 一起持久化。
            if native_tool_results is None or not native_tool_results.put(
                thread_id, call.call_id, observation.text
            ):
                from app.agent.log import agent_trace

                agent_trace("原生工具结果临时存储失败")
                return seal_budget_if_exhausted(
                    rejected("INTERNAL", "工具临时上下文不可用"),
                    state,
                )
            checkpoint_observation = replace(
                observation,
                text=f"工具 {call.name} 已执行；完整结果仅在当前回合供模型使用。",
            )
        result = {
            "pending_tool": next_pending,
            "pending_tools": remaining,
            "observations": [checkpoint_observation],
            "pending_events": events,
        }
        if is_native:
            result["native_messages"] = [
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "name": call.name,
                    "content": "",
                }
            ]
        return seal_budget_if_exhausted(result, state)

    return tool_node
