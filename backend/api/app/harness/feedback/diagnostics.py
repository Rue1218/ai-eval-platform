"""原始 traceback 仅服务端审计；缺 trace_id/span_id 直接拒绝记录。"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field

from app.harness.contracts.errors import DiagnosticRef, MissingTraceContext
from app.harness.contracts.trace import TraceContext

# 阶段 2 迁 PG 前的进程内上限，防止 traceback 无限堆积。
MAX_AUDIT_ITEMS = 256


@dataclass
class InMemoryAuditStore:
    """单测与无库时的诊断存储；可注入、可清空。"""

    items: list[dict[str, str]] = field(default_factory=list)
    max_items: int = MAX_AUDIT_ITEMS

    def append(self, *, trace_id: str, span_id: str, traceback_text: str) -> DiagnosticRef:
        diagnostic_id = f"diag-{uuid.uuid4().hex[:12]}"
        self.items.append(
            {
                "diagnostic_id": diagnostic_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "traceback": traceback_text,
            }
        )
        overflow = len(self.items) - self.max_items
        if overflow > 0:
            del self.items[:overflow]
        return DiagnosticRef(diagnostic_id=diagnostic_id, trace_id=trace_id, span_id=span_id)

    def clear(self) -> None:
        """清空当前进程内诊断，供测试隔离。"""
        self.items.clear()


_STORE = InMemoryAuditStore()


def audit_store() -> InMemoryAuditStore:
    """当前诊断库。测试应通过 reset_audit_store 注入，避免依赖隐式全局。"""
    return _STORE


def reset_audit_store(*, store: InMemoryAuditStore | None = None) -> InMemoryAuditStore:
    """替换或重建进程内诊断库。"""
    global _STORE
    _STORE = store if store is not None else InMemoryAuditStore()
    return _STORE


def record_diagnostic(exc: Exception, *, trace: TraceContext) -> DiagnosticRef:
    """Fail-fast：没有 trace 上下文不得写入诊断库。"""
    if not str(trace.trace_id).strip() or not str(trace.span_id).strip():
        raise MissingTraceContext("diagnostics 拒绝记录未携带 trace_id/span_id 的 Outcome")
    traceback_text = "".join(traceback.format_exception(exc))
    return _STORE.append(
        trace_id=trace.trace_id,
        span_id=trace.span_id,
        traceback_text=traceback_text,
    )
