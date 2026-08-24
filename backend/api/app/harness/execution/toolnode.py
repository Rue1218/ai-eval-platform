"""Harness 执行层：ToolNode 包装（M5 阶段 3，EX-1）。

``build_tool_node`` 返回 LangGraph 异步节点函数：消费 ``GraphState.pending_tool``
（ToolCall 投影），经门禁 → 绑定 → 分派 → 归一为 ``Observation``，写回
``observations`` + ``tool_call/tool_result`` 事件意图；不直接 emit（事件桥接
契约）。``pending_tool`` 图外不持久化，回合结束随工作记忆清除（MEM-1）。

会话上下文（session_id/user_id/附件归属/沙箱目录）经
``RunnableConfig.configurable`` 注入（M4-Q2 命名空间约定），不入 GraphState。
节点为异步：``execute`` 经 ``asyncio.to_thread`` 在线程池执行，避免 15s bash
沙箱调用阻塞 api 事件循环（影响其他 WS 连接心跳）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from langgraph.config import get_config

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall, make_event
from app.harness.feedback.observation import normalize_exception
from app.harness.feedback.rules import GateContext, check_gates
from app.harness.memory import GraphState

from .binding import bind_attachments
from .dispatch import execute
from .registry import ToolRegistry


def build_tool_node(
    registry: ToolRegistry,
    *,
    db_factory: Callable[[], object] | None = None,
    sandbox_dir: str | None = None,
    user_id: str = "",
) -> Callable[[GraphState], Awaitable[dict]]:
    """构造 ToolNode 异步节点函数（EX-1）。

    ``db_factory`` 延迟提供 DB Session（节点内按需获取，避免跨 Session 传
    ORM 对象）；``sandbox_dir``/``user_id`` 为平台注入的默认值（模型不可传），
    优先读 ``RunnableConfig.configurable``（session/credentials/sandbox 命名空间）。
    """

    async def tool_node(state: GraphState) -> dict:
        pending = state.get("pending_tool")
        if not pending:
            return {"pending_events": []}
        call = ToolCall(
            name=str(pending.get("name") or ""),
            arguments=dict(pending.get("arguments") or {}),
        )
        # 会话上下文：优先 configurable，回退构造参数
        configurable = (get_config() or {}).get("configurable") or {}
        session_id = str(configurable.get("session", {}).get("id") or "")
        current_user = str(configurable.get("credentials", {}).get("user_id") or user_id)
        owned_file_ids = frozenset(configurable.get("assets", {}).get("file_ids") or ())
        sandbox_box = configurable.get("sandbox") or {}
        sandbox = str(sandbox_box.get("dir") or sandbox_dir or "")
        definition = registry.get(call.name)  # 未注册抛 VALIDATION
        # 1. 门禁（FB-2）：长工具/白名单/资产溯源/占槽等
        context = GateContext(
            session_id=session_id,
            user_id=current_user,
            owned_file_ids=owned_file_ids,
            registered_names=frozenset(registry._defs.keys()),
            required_slots={},
        )
        gate = check_gates(call, context)
        events = [make_event("tool_call", {"name": call.name, "arguments": call.arguments})]
        if not gate.passed:
            events.append(
                make_event(
                    "error",
                    {
                        "code": gate.failed_code or "VALIDATION",
                        "message": gate.failed_message or "门禁未通过",
                    },
                )
            )
            return {
                "pending_tool": None,
                "pending_events": events,
            }
        # 2. 绑定（EX-2）：附件归属校验（db_factory 提供会话）
        db = db_factory() if db_factory else None
        try:
            safe_args = bind_attachments(call.arguments, db, current_user)
        except Exception:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()
        # 3. 分派（EX-3）：超时 + 脱敏日志 → 归一 Observation
        # 异步节点经 to_thread 执行：避免 bash 等同步工具阻塞事件循环
        started = time.perf_counter()
        try:
            observation = await asyncio.wait_for(
                asyncio.to_thread(
                    execute,
                    ToolCall(name=call.name, arguments=safe_args),
                    timeout_s=definition.timeout_s,
                    permission=definition.permission,
                    sandbox_dir=sandbox,
                    handler=definition.handler,
                ),
                timeout=max(0.001, float(definition.timeout_s)),
            )
        except TimeoutError:
            # 节点级超时兜底；bash/web_fetch 自身仍有进程/网络超时，避免
            # 通用工具忘记实现超时时把 WS 回合永久挂起。
            observation = normalize_exception(
                AppError(ErrorCode.TIMEOUT, "工具执行超时"),
                tool=call.name,
            )
        latency_ms = round((time.perf_counter() - started) * 1000)
        result_payload: dict[str, object] = {
            "name": call.name,
            "ok": observation.ok,
            "latency_ms": latency_ms,
            "truncated": observation.truncated,
            "redacted": observation.redacted,
        }
        if observation.source:
            result_payload["source"] = observation.source
        if observation.ok:
            # 前端 ToolCard 与 API.md §4.3 读取 data；摘要保持脱敏后的文本。
            result_payload["data"] = {"summary": observation.text}
        else:
            result_payload["error"] = observation.text
        events.append(
            make_event("tool_result", result_payload)
        )
        return {
            "pending_tool": None,
            "observations": [observation],
            "pending_events": events,
        }

    return tool_node
