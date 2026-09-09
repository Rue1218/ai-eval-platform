"""原生基础工具执行器。

模型通过两类协议 Function Calling 生成 ToolCall 后，read/write/edit/bash/web_search/
web_fetch/task 等基础工具在本进程直接调用既有受控 handler。这里仅承担异步
隔离、超时与取消；不会经过 MCP 目录、provider 或 transport。权限、Schema、
附件与长任务门禁仍固定在 ToolNode 之前执行。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from app.harness.contracts import ToolCall, ToolResult

from .context import ToolExecutionContext
from .dispatch import execute_raw
from .registry import ToolDef
from .workspace_guard import guarded_call


class NativeToolExecutor:
    """原生短工具的直连执行器，避免基础能力额外经过 MCP Host。"""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[ToolResult]] = {}

    async def call(
        self,
        definition: ToolDef,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """在线程池内执行同步 handler，并归一超时与取消语义。

        bash 自身仍由 bwrap 负责整棵子进程树清理；此处的协程取消不会降级为
        裸进程，也不会阻塞 API 事件循环。
        """
        call = ToolCall(
            name=definition.name,
            arguments=dict(arguments),
            call_id=context.call_id,
        )
        def execute_guarded() -> ToolResult:
            """真实工作线程持有隔离记录，主协程取消不会清除远端未知执行。"""
            try:
                return guarded_call(definition, context, lambda: execute_raw(
                    call, timeout_s=definition.timeout_s, permission=definition.permission,
                    sandbox_dir=context.sandbox_dir, handler=definition.handler,
                    context=context if definition.contextual else None,
                    recovery_policy=definition.recovery_policy,
                    output_schema=dict(definition.output_schema) if definition.output_schema else None,
                ))
            except Exception as exc:
                from app.errors import AppError

                code = exc.code.value if isinstance(exc, AppError) else "INTERNAL"
                return ToolResult(name=definition.name, ok=False, call_id=context.call_id,
                                  error={"code": code, "message": "工作区执行未获完成确认"})

        future = asyncio.ensure_future(
            asyncio.to_thread(
                execute_guarded,
            )
        )
        key = context.call_id or definition.name
        self._inflight[key] = future
        try:
            return await asyncio.wait_for(
                future,
                timeout=max(0.001, float(definition.timeout_s)),
            )
        except TimeoutError:
            future.cancel()
            return ToolResult(
                name=definition.name,
                ok=False,
                error={
                    "code": "TIMEOUT",
                    "message": "操作失败（TIMEOUT）",
                    "recovery": definition.recovery_policy.to_payload("TIMEOUT"),
                },
                call_id=context.call_id,
            )
        except asyncio.CancelledError:
            future.cancel()
            raise
        finally:
            self._inflight.pop(key, None)

    def cancel_call(self, call_id: str) -> bool:
        """取消指定原生调用；实际 bash 清理由沙箱的墙钟超时继续兜底。"""
        future = self._inflight.pop(call_id, None)
        if future is None or future.done():
            return False
        future.cancel()
        return True

    async def close(self) -> None:
        """取消在飞原生工具调用（幂等）。"""
        for future in list(self._inflight.values()):
            future.cancel()
        self._inflight.clear()
