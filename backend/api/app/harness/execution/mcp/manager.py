"""内部 MCP Client Manager（阶段 D，P3）。

``MCPClientManager`` 是 Agent 图与短工具执行之间的**唯一内部边界**：
``refresh_catalog``（tools/list）→ 门禁后的 ``call_tool``（tools/call）→
``ToolResult``（与 Observation 分离，§5.4）。同步 handler 经
``asyncio.to_thread`` 线程池执行（防 15s bash 阻塞 api 事件循环）；超时
cancel + TIMEOUT；``/stop`` 取消经 ``CancelledError`` 穿透给图运行；
``cancel_call`` 支持按 call_id 取消在飞调用。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace

from app.harness.contracts import ToolDescriptor, ToolResult

from ..registry import ToolDef, ToolRegistry
from .catalog import ToolCatalog
from .metrics import ToolMetrics, get_default_metrics
from .provider import InProcessProvider


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """MCP 工具调用上下文（仅运行时，不入 GraphState / 检查点）。

    ``sandbox_dir``/``owned_file_ids`` 等由平台注入，模型参数中不得携带。
    """

    session_id: str = ""
    user_id: str = ""
    thread_id: str = ""
    sandbox_dir: str | None = None
    owned_file_ids: frozenset[str] = frozenset()
    call_id: str = ""


class MCPClientManager:
    """内部 MCP Host：目录发现 + 工具调用 + 超时/取消/错误归一 + 熔断/度量。"""

    def __init__(self, metrics: ToolMetrics | None = None) -> None:
        self._catalog = ToolCatalog()
        self._providers: dict[str, InProcessProvider] = {}
        self._registry: ToolRegistry | None = None
        self._inflight: dict[str, asyncio.Future] = {}
        self._closed = False
        # 熔断与工具度量（P4-2）：缺省用进程级收集器，测试可注入独立实例。
        self._metrics = metrics if metrics is not None else get_default_metrics()

    @classmethod
    def build_from_registry(
        cls,
        registry: ToolRegistry,
        *,
        metrics: ToolMetrics | None = None,
    ) -> MCPClientManager:
        """按 server 分组构建 in-process provider，并建立目录索引。"""
        manager = cls(metrics=metrics)
        manager._registry = registry
        manager._rebuild(registry)
        return manager

    def _rebuild(self, registry: ToolRegistry) -> None:
        """从注册表重建目录与 provider 分组。"""
        catalog = ToolCatalog.build(registry)
        by_server: dict[str, dict[str, ToolDef]] = {}
        for descriptor in catalog.all_descriptors():
            definition = registry.find(descriptor.name)
            if definition is None:
                continue
            by_server.setdefault(descriptor.server_id, {})[descriptor.tool_id] = definition
        self._catalog = catalog
        self._providers = {
            server: InProcessProvider(server, defs) for server, defs in by_server.items()
        }

    async def refresh_catalog(self) -> list[ToolDescriptor]:
        """重建目录（注册表新增工具后反映）并返回全部描述符。"""
        if self._registry is not None:
            self._rebuild(self._registry)
        return list(self._catalog.all_descriptors())

    async def call_tool(
        self,
        tool_id: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """调用内部工具；未知/超时/失败均返回 ToolResult（不抛）。

        取消（``/stop`` 或 ``cancel_call``）以 ``CancelledError`` 穿透给图
        运行；超时经 ``asyncio.wait_for`` cancel 在飞 future 并返回 TIMEOUT。
        """
        if self._closed:
            return ToolResult(
                name=tool_id,
                ok=False,
                error={"code": "INTERNAL", "message": "工具目录已关闭"},
                call_id=context.call_id,
            )
        descriptor = self._catalog.get(tool_id)
        if descriptor is None:
            return ToolResult(
                name=tool_id,
                ok=False,
                error={"code": "VALIDATION", "message": f"工具未注册：{tool_id}"},
                call_id=context.call_id,
            )
        provider = self._providers.get(descriptor.server_id)
        if provider is None:
            return ToolResult(
                name=tool_id,
                ok=False,
                error={"code": "INTERNAL", "message": "工具执行器不可用"},
                call_id=context.call_id,
            )
        # P4-2 熔断：服务器 open 期间快速拒绝，不进入 handler。
        if self._metrics.is_open(descriptor.server_id):
            self._metrics.record_call(
                tool_id, descriptor.server_id, ok=False, error_code="CIRCUIT_OPEN"
            )
            return ToolResult(
                name=descriptor.name,
                ok=False,
                error={"code": "VALIDATION", "message": "服务器工具暂时不可用（熔断），请稍后重试"},
                call_id=context.call_id,
            )
        started = time.perf_counter()
        future = asyncio.ensure_future(
            asyncio.to_thread(
                provider.invoke,
                tool_id,
                dict(arguments),
                context,
                context.call_id,
            )
        )
        key = context.call_id or tool_id
        self._inflight[key] = future
        try:
            result = await asyncio.wait_for(
                future,
                timeout=max(0.001, float(descriptor.timeout_s)),
            )
        except TimeoutError:
            future.cancel()
            self._metrics.record_call(
                tool_id,
                descriptor.server_id,
                ok=False,
                timeout=True,
                error_code="TIMEOUT",
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
            return ToolResult(
                name=descriptor.name,
                ok=False,
                error={"code": "TIMEOUT", "message": "操作失败（TIMEOUT）"},
                call_id=context.call_id,
            )
        except asyncio.CancelledError:
            future.cancel()
            raise
        finally:
            self._inflight.pop(key, None)
        if not result.call_id:
            result = replace(result, call_id=context.call_id)
        latency_ms = round((time.perf_counter() - started) * 1000)
        if result.ok:
            self._metrics.record_call(tool_id, descriptor.server_id, ok=True, latency_ms=latency_ms)
        else:
            code = str((result.error or {}).get("code") or "INTERNAL")
            self._metrics.record_call(
                tool_id,
                descriptor.server_id,
                ok=False,
                timeout=(code == "TIMEOUT"),
                error_code=code,
                latency_ms=latency_ms,
            )
        return result

    def cancel_call(self, call_id: str) -> bool:
        """取消指定在飞调用；找到并取消返回 True。"""
        future = self._inflight.pop(call_id, None)
        if future is None or future.done():
            return False
        future.cancel()
        return True

    async def close(self) -> None:
        """取消全部在飞调用并关闭目录（幂等）。"""
        self._closed = True
        for future in list(self._inflight.values()):
            future.cancel()
        self._inflight.clear()
