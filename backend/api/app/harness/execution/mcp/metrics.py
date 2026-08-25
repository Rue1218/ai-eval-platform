"""内部 MCP 工具度量与失败熔断（P4-2）。

``ToolMetrics`` 按 ``tool_id`` 记录调用计数与耗时（§10.4「记录并可查询」），
按 ``server_id`` 维护失败熔断（§7.2「失败熔断」）。熔断**只统计基础设施错误码**
（``INTERNAL``/``TIMEOUT``/``UPSTREAM``）计入连续失败；业务性 ``VALIDATION``/
``NOT_FOUND`` 等是正常业务结果，不计入（避免 web_search「未接入」等误熔断）。
度量进程内瞬态收集，经 ``GET /api/mcp/metrics`` 只读查询，不落 DB。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

# 计入熔断连续失败的基础设施错误码；其余（VALIDATION/NOT_FOUND 等）为业务结果
CIRCUIT_FAILURE_CODES: frozenset[str] = frozenset({"INTERNAL", "TIMEOUT", "UPSTREAM"})


@dataclass(frozen=True, slots=True)
class ToolStat:
    """单工具调用统计（快照投影，不可变）。"""

    tool_id: str
    total: int = 0
    success: int = 0
    failure: int = 0
    timeout: int = 0
    total_latency_ms: int = 0
    last_latency_ms: int = 0
    last_error_code: str | None = None

    @property
    def avg_latency_ms(self) -> int:
        """平均耗时（毫秒，总调用为 0 时返回 0）。"""
        return round(self.total_latency_ms / self.total) if self.total else 0


@dataclass(frozen=True, slots=True)
class CircuitState:
    """单个 server 的熔断状态。"""

    server_id: str
    state: str = "closed"  # "closed" | "open"
    consecutive_failures: int = 0
    failure_threshold: int = 5
    cooldown_s: float = 30.0
    opened_at: float | None = None


class ToolMetrics:
    """线程安全的工具度量 + 服务器熔断收集器。"""

    def __init__(self, *, failure_threshold: int = 5, cooldown_s: float = 30.0) -> None:
        self._lock = threading.Lock()
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._tools: dict[str, ToolStat] = {}
        self._circuits: dict[str, CircuitState] = {}

    def record_call(
        self,
        tool_id: str,
        server_id: str,
        *,
        ok: bool,
        timeout: bool = False,
        error_code: str | None = None,
        latency_ms: int = 0,
    ) -> None:
        """记录一次工具调用并推进熔断状态。

        成功 → 重置电路连续失败；失败且错误码 ∈ ``CIRCUIT_FAILURE_CODES`` →
        连续失败 +1，达阈值置 open；其余失败（VALIDATION 等）不动电路。
        """
        with self._lock:
            stat = self._tools.get(tool_id)
            stat = ToolStat(
                tool_id=tool_id,
                total=(stat.total if stat else 0) + 1,
                success=(stat.success if stat else 0) + (1 if ok else 0),
                failure=(stat.failure if stat else 0) + (0 if ok else 1),
                timeout=(stat.timeout if stat else 0) + (1 if timeout else 0),
                total_latency_ms=(stat.total_latency_ms if stat else 0) + latency_ms,
                last_latency_ms=latency_ms,
                last_error_code=None if ok else (error_code or "INTERNAL"),
            )
            self._tools[tool_id] = stat

            circuit = self._circuits.get(server_id) or CircuitState(
                server_id=server_id,
                failure_threshold=self._failure_threshold,
                cooldown_s=self._cooldown_s,
            )
            if ok:
                circuit = replace(circuit, consecutive_failures=0, state="closed", opened_at=None)
            elif error_code in CIRCUIT_FAILURE_CODES:
                failures = circuit.consecutive_failures + 1
                if failures >= self._failure_threshold and circuit.state != "open":
                    circuit = replace(circuit, consecutive_failures=failures, state="open", opened_at=time.time())
                else:
                    circuit = replace(circuit, consecutive_failures=failures)
            self._circuits[server_id] = circuit

    def is_open(self, server_id: str) -> bool:
        """服务器熔断是否生效（open 且未过冷却期）；冷却结束自动恢复 closed。"""
        with self._lock:
            circuit = self._circuits.get(server_id)
            if circuit is None:
                return False
            circuit = self._apply_cooldown(circuit)
            self._circuits[server_id] = circuit
            return circuit.state == "open"

    def _apply_cooldown(self, circuit: CircuitState) -> CircuitState:
        """open 且冷却期已过 → 自动回 closed（连续失败清零）。"""
        if (
            circuit.state == "open"
            and circuit.opened_at is not None
            and time.time() - circuit.opened_at >= circuit.cooldown_s
        ):
            return replace(circuit, state="closed", consecutive_failures=0, opened_at=None)
        return circuit

    def snapshot(self) -> dict:
        """导出可序列化快照（工具统计 + 熔断状态 + 汇总）。"""
        with self._lock:
            for server_id, circuit in list(self._circuits.items()):
                self._circuits[server_id] = self._apply_cooldown(circuit)
            tools = [
                {
                    "tool_id": stat.tool_id,
                    "total": stat.total,
                    "success": stat.success,
                    "failure": stat.failure,
                    "timeout": stat.timeout,
                    "avg_latency_ms": stat.avg_latency_ms,
                    "last_latency_ms": stat.last_latency_ms,
                    "last_error_code": stat.last_error_code,
                }
                for stat in sorted(self._tools.values(), key=lambda item: item.tool_id)
            ]
            circuits = [
                {
                    "server_id": circuit.server_id,
                    "state": circuit.state,
                    "consecutive_failures": circuit.consecutive_failures,
                    "failure_threshold": circuit.failure_threshold,
                    "cooldown_s": circuit.cooldown_s,
                    "opened_at": circuit.opened_at,
                }
                for circuit in sorted(self._circuits.values(), key=lambda item: item.server_id)
            ]
            return {
                "tools": tools,
                "circuits": circuits,
                "summary": {
                    "total_calls": sum(item["total"] for item in tools),
                    "total_failures": sum(item["failure"] for item in tools),
                    "total_timeouts": sum(item["timeout"] for item in tools),
                    "open_servers": [item["server_id"] for item in circuits if item["state"] == "open"],
                },
            }

    def reset(self) -> None:
        """清空全部统计与熔断状态（测试 / 运维重置用）。"""
        with self._lock:
            self._tools.clear()
            self._circuits.clear()


_default_metrics: ToolMetrics | None = None
_default_metrics_lock = threading.Lock()


def get_default_metrics() -> ToolMetrics:
    """进程级默认收集器（生产 agent 与 /api/mcp/metrics 共享；读 Settings）。"""
    global _default_metrics
    with _default_metrics_lock:
        if _default_metrics is None:
            from app.config import settings

            _default_metrics = ToolMetrics(
                failure_threshold=settings.circuit_failure_threshold,
                cooldown_s=settings.circuit_cooldown_s,
            )
        return _default_metrics
