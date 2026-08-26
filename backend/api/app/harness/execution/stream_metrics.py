"""原生流式与 ToolBatch 的进程内观测（P4）。

只记录延迟、计数和错误码类别，禁止写入正文、工具参数、密钥或完整
Observation。连续 ``UPSTREAM`` / 关联错乱达到阈值时暂时禁用并行，冷却后
自动恢复；不改写已落库的 WebSocket 事件。运维仍可用环境变量总开关回滚。
"""

from __future__ import annotations

import threading
import time
from typing import Any


def _avg(total: int, count: int) -> int:
    """整数毫秒均值；无样本时为 0。"""
    return round(total / count) if count else 0


class StreamMetrics:
    """线程安全的交错流/批次度量与并行脚踢线。"""

    def __init__(self, *, failure_threshold: int = 5, cooldown_s: float = 30.0) -> None:
        self._lock = threading.Lock()
        self._failure_threshold = max(1, int(failure_threshold))
        self._cooldown_s = max(0.0, float(cooldown_s))
        self.reset()

    def reset(self) -> None:
        """清空统计与脚踢状态（测试 / 运维重置）。"""
        with self._lock:
            self._stream_rounds = 0
            self._invoke_fallbacks = 0
            self._first_delta_total_ms = 0
            self._first_delta_count = 0
            self._tool_parse_total_ms = 0
            self._tool_parse_count = 0
            self._incomplete = 0
            self._cancelled = 0
            self._upstream = 0
            self._associate_errors = 0
            self._batch_count = 0
            self._batch_duration_total_ms = 0
            self._parallel_waves = 0
            self._wave_size_total = 0
            self._max_wave_size = 0
            self._consecutive_incidents = 0
            self._parallel_disabled = False
            self._disable_reason: str | None = None
            self._disabled_at: float | None = None

    def record_stream(
        self,
        *,
        first_delta_ms: int | None = None,
        tool_call_parse_ms: int | None = None,
        incomplete: bool = False,
        cancelled: bool = False,
        upstream: bool = False,
        associate_error: bool = False,
        invoke_fallback: bool = False,
    ) -> None:
        """记录一次模型回合的脱敏指标；调用方必须每回合只记一笔终态。

        不含文本或参数。成功回合会清零连续事故；``UPSTREAM`` / 关联错乱累计
        至阈值后暂时禁用并行。
        """
        with self._lock:
            self._stream_rounds += 1
            if invoke_fallback:
                self._invoke_fallbacks += 1
            if first_delta_ms is not None:
                self._first_delta_total_ms += max(0, int(first_delta_ms))
                self._first_delta_count += 1
            if tool_call_parse_ms is not None:
                self._tool_parse_total_ms += max(0, int(tool_call_parse_ms))
                self._tool_parse_count += 1
            if incomplete:
                self._incomplete += 1
            if cancelled:
                self._cancelled += 1
            if upstream:
                self._upstream += 1
            if associate_error:
                self._associate_errors += 1
            if cancelled:
                return
            if upstream or associate_error:
                self._consecutive_incidents += 1
                if (
                    self._consecutive_incidents >= self._failure_threshold
                    and not self._parallel_disabled
                ):
                    self._parallel_disabled = True
                    self._disable_reason = "associate" if associate_error else "UPSTREAM"
                    self._disabled_at = time.time()
            else:
                self._consecutive_incidents = 0

    def record_batch(self, *, duration_ms: int, wave_size: int, parallel: bool) -> None:
        """记录一波 ToolNode 执行的墙钟与并发规模。"""
        size = max(0, int(wave_size))
        with self._lock:
            self._batch_count += 1
            self._batch_duration_total_ms += max(0, int(duration_ms))
            self._wave_size_total += size
            if size > self._max_wave_size:
                self._max_wave_size = size
            if parallel and size > 1:
                self._parallel_waves += 1

    def is_parallel_disabled(self) -> bool:
        """并行是否被脚踢线暂时关闭（冷却结束自动恢复）。"""
        with self._lock:
            self._apply_cooldown_locked()
            return self._parallel_disabled

    def _apply_cooldown_locked(self) -> None:
        """open 且过冷却 → 恢复并行，连续事故清零。"""
        if (
            self._parallel_disabled
            and self._disabled_at is not None
            and time.time() - self._disabled_at >= self._cooldown_s
        ):
            self._parallel_disabled = False
            self._disable_reason = None
            self._disabled_at = None
            self._consecutive_incidents = 0

    def snapshot(self) -> dict[str, Any]:
        """可序列化快照；保证不含正文、参数或凭据。"""
        from app.config import settings

        with self._lock:
            self._apply_cooldown_locked()
            incomplete_ratio = (
                round(self._incomplete / self._stream_rounds, 4) if self._stream_rounds else 0.0
            )
            return {
                "stream": {
                    "rounds": self._stream_rounds,
                    "invoke_fallbacks": self._invoke_fallbacks,
                    "first_delta_avg_ms": _avg(self._first_delta_total_ms, self._first_delta_count),
                    "tool_call_parse_avg_ms": _avg(self._tool_parse_total_ms, self._tool_parse_count),
                    "incomplete": self._incomplete,
                    "incomplete_ratio": incomplete_ratio,
                    "cancelled": self._cancelled,
                    "upstream": self._upstream,
                    "associate_errors": self._associate_errors,
                },
                "batch": {
                    "count": self._batch_count,
                    "duration_avg_ms": _avg(self._batch_duration_total_ms, self._batch_count),
                    "parallel_waves": self._parallel_waves,
                    "wave_size_avg": _avg(self._wave_size_total, self._batch_count),
                    "max_wave_size": self._max_wave_size,
                },
                "rollout": {
                    "native_stream_enabled": bool(settings.agent_native_stream_enabled),
                    "parallel_enabled": bool(settings.agent_parallel_tool_batch_enabled),
                    "parallel_profile_allowlist": sorted(
                        part
                        for part in str(settings.agent_parallel_tool_batch_profile_ids or "").split(",")
                        if part.strip()
                    ),
                    "parallel_disabled": self._parallel_disabled,
                    "parallel_disable_reason": self._disable_reason,
                    "consecutive_incidents": self._consecutive_incidents,
                    "failure_threshold": self._failure_threshold,
                    "cooldown_s": self._cooldown_s,
                },
            }


_default_metrics: StreamMetrics | None = None
_default_metrics_lock = threading.Lock()


def get_default_stream_metrics() -> StreamMetrics:
    """进程级默认收集器（Agent 与 GET /api/agent/metrics 共享）。"""
    global _default_metrics
    with _default_metrics_lock:
        if _default_metrics is None:
            from app.config import settings

            _default_metrics = StreamMetrics(
                failure_threshold=settings.circuit_failure_threshold,
                cooldown_s=settings.circuit_cooldown_s,
            )
        return _default_metrics
