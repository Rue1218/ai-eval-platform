"""受控 MCP Client Manager（阶段 D，P3）。

``MCPClientManager`` 是 Agent 图与短工具执行之间的**唯一内部边界**：
``refresh_catalog``（tools/list）→ 门禁后的 ``call_tool``（tools/call）→
``ToolResult``（与 Observation 分离，§5.4）。进程内同步 handler 经
``asyncio.to_thread`` 线程池执行（防 15s bash 阻塞 api 事件循环）；超时
cancel + TIMEOUT；``/stop`` 取消经 ``CancelledError`` 穿透给图运行；
``cancel_call`` 支持按 call_id 取消在飞调用。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import replace

from app.harness.contracts import ToolDescriptor, ToolResult

from ..context import ToolExecutionContext
from ..registry import ToolDef, ToolRegistry
from .catalog import ToolCatalog
from .media_archive import archive_media_results
from .metrics import ToolMetrics, get_default_metrics
from .provider import InProcessProvider
from .streamable_provider import StreamableHttpProvider

# 需要平台侧归档产物的远程 MCP server（沙箱无公网出口，临时链接无法自行取回）。
_ARCHIVED_SERVER_IDS = frozenset({"media.generation"})


class MCPClientManager:
    """受控 MCP 扩展 Host：目录发现、调用、取消、熔断与度量。"""

    def __init__(self, metrics: ToolMetrics | None = None, *, join_on_cancel: bool = False) -> None:
        self._catalog = ToolCatalog()
        self._providers: dict[str, InProcessProvider | StreamableHttpProvider] = {}
        # 远程 provider 只能由启动配置构造，不能由模型参数或浏览器请求新增。
        self._remote_providers: dict[str, StreamableHttpProvider] = {}
        self._registry: ToolRegistry | None = None
        self._inflight: dict[str, asyncio.Future] = {}
        # 新循环显式选择等待线程真实结束；旧调用方保持原超时/取消行为。
        self._join_on_cancel = join_on_cancel
        self._call_tasks: dict[str, asyncio.Task] = {}
        self._closed = False
        # 熔断与工具度量（P4-2）：缺省用进程级收集器，测试可注入独立实例。
        self._metrics = metrics if metrics is not None else get_default_metrics()

    @classmethod
    def build_from_registry(
        cls,
        registry: ToolRegistry,
        *,
        metrics: ToolMetrics | None = None,
        join_on_cancel: bool = False,
        remote_providers: Mapping[str, StreamableHttpProvider] | None = None,
    ) -> MCPClientManager:
        """按 server 构建受控 provider，并建立目录索引。"""
        manager = cls(metrics=metrics, join_on_cancel=join_on_cancel)
        manager._registry = registry
        manager._remote_providers = dict(remote_providers or {})
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
            server: self._remote_providers.get(server, InProcessProvider(server, defs))
            for server, defs in by_server.items()
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
        is_remote = isinstance(provider, StreamableHttpProvider)
        if is_remote:
            future = asyncio.ensure_future(
                provider.invoke(
                    tool_id=tool_id,
                    tool_name=descriptor.name,
                    arguments=arguments,
                    output_schema=descriptor.output_schema,
                    call_id=context.call_id,
                )
            )
        else:
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
        timed_out = False
        if self._join_on_cancel:
            self._call_tasks[key] = asyncio.current_task()
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future) if self._join_on_cancel else future,
                timeout=max(0.001, float(descriptor.timeout_s)),
            )
        except TimeoutError:
            if self._join_on_cancel and not is_remote:
                timed_out = True
                result = await self._wait_joined(future)
            else:
                future.cancel()
                self._metrics.record_call(
                    tool_id, descriptor.server_id, ok=False, timeout=True, error_code="TIMEOUT",
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
                return ToolResult(name=descriptor.name, ok=False,
                                  error={"code": "TIMEOUT", "message": "操作失败（TIMEOUT）"},
                                  call_id=context.call_id)
        except asyncio.CancelledError:
            if self._join_on_cancel and not is_remote:
                result = await self._wait_joined(future)
            else:
                future.cancel()
                raise
        finally:
            self._inflight.pop(key, None)
            self._call_tasks.pop(key, None)
        if not result.call_id:
            result = replace(result, call_id=context.call_id)
        # 媒体产物（图片/视频）在 api 侧归档进会话工作区（失败不改写原结果），
        # 使模型与后续工具能在无出网沙箱内使用文件本体。
        if result.ok and descriptor.server_id in _ARCHIVED_SERVER_IDS:
            result = await archive_media_results(result, context.sandbox_dir)
        latency_ms = round((time.perf_counter() - started) * 1000)
        if result.ok:
            self._metrics.record_call(tool_id, descriptor.server_id, ok=True, timeout=timed_out, latency_ms=latency_ms)
        else:
            code = str((result.error or {}).get("code") or "INTERNAL")
            self._metrics.record_call(
                tool_id,
                descriptor.server_id,
                ok=False,
                timeout=timed_out or code == "TIMEOUT",
                error_code=code,
                latency_ms=latency_ms,
            )
        return result

    def cancel_call(self, call_id: str) -> bool:
        """取消指定在飞调用；找到并取消返回 True。"""
        if self._join_on_cancel:
            task = self._call_tasks.get(call_id)
            if task is None or task.done():
                return False
            task.cancel()
            return True
        future = self._inflight.pop(call_id, None)
        if future is None or future.done():
            return False
        future.cancel()
        return True

    async def close(self) -> None:
        """取消全部在飞调用并关闭目录（幂等）。"""
        self._closed = True
        if self._join_on_cancel:
            tasks = list(self._call_tasks.values())
            for task in tasks:
                task.cancel()
            await self._wait_joined(asyncio.gather(*tasks, return_exceptions=True))
            return
        for future in list(self._inflight.values()):
            future.cancel()
        self._inflight.clear()

    @staticmethod
    async def _wait_joined(future: asyncio.Future):
        """线程不能被 Task.cancel 杀死；重复取消时也必须等到真实结果。"""
        while True:
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                if future.done():
                    return future.result()
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
