"""原始 traceback 仅服务端审计；缺 trace_id/span_id 直接拒绝记录。

生产写入 PostgreSQL；单测通过 reset_audit_store 注入 InMemoryAuditStore。
诊断保留天数见 budgets.diagnostics_retention_days；定时清理任务可后补。
"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.harness.contracts.errors import DiagnosticRef, MissingTraceContext
from app.harness.contracts.trace import TraceContext

# 进程内上限，防止 traceback 无限堆积；PG 路径不使用该上限。
MAX_AUDIT_ITEMS = 256


class AuditStore(Protocol):
    """诊断存储端口；测试注入内存实现，生产写入 PG。"""

    def append(self, *, trace_id: str, span_id: str, traceback_text: str) -> DiagnosticRef: ...


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


class PgAuditStore:
    """把诊断写入 harness_diagnostics。落库失败不得打断 Turn，只打控制台。"""

    def append(self, *, trace_id: str, span_id: str, traceback_text: str) -> DiagnosticRef:
        from app.agent.log import agent_trace
        from app.db import SessionLocal
        from app.models import HarnessDiagnostic

        diagnostic_id = f"diag-{uuid.uuid4().hex[:12]}"
        db = SessionLocal()
        try:
            db.add(
                HarnessDiagnostic(
                    diagnostic_id=diagnostic_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    traceback=traceback_text,
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            agent_trace(f"诊断落库失败 type={type(exc).__name__}")
        finally:
            db.close()
        return DiagnosticRef(diagnostic_id=diagnostic_id, trace_id=trace_id, span_id=span_id)


_STORE: AuditStore = InMemoryAuditStore()


def audit_store() -> AuditStore:
    """当前诊断库。测试应通过 reset_audit_store 注入，避免依赖隐式全局。"""
    return _STORE


def reset_audit_store(*, store: AuditStore | None = None) -> AuditStore:
    """替换或重建诊断库。"""
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
