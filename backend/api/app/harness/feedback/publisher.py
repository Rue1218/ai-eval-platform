"""回合 / span / 结构化追踪日志。审计只落 PostgreSQL，不进 Redis。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.agent.log import agent_trace
from app.harness.contracts.errors import MissingTraceContext
from app.harness.contracts.trace import TraceContext, format_trace_prefix, using_trace
from app.harness.contracts.turn import TurnStatus


class AuditPublisher(Protocol):
    """Turn / Span 持久化与带 trace 的结构化日志。"""

    def start_turn(self, trace: TraceContext, *, session_id: str, status: str = TurnStatus.INIT) -> None: ...

    def set_turn_status(self, trace: TraceContext, *, status: str, finished: bool = False) -> None: ...

    def finish_turn(self, trace: TraceContext, *, status: str) -> None: ...

    def record_span(self, trace: TraceContext, *, latency_ms: int = 0) -> None: ...

    def log(
        self,
        message: str,
        *,
        trace: TraceContext,
        call_id: str | None = None,
    ) -> None: ...


def _require_trace(trace: TraceContext) -> None:
    """结构化日志与审计写入均拒绝空 trace。"""
    if not str(trace.trace_id).strip() or not str(trace.span_id).strip():
        raise MissingTraceContext("publisher 拒绝未携带 trace_id/span_id 的记录")


def format_traced_message(
    message: str,
    *,
    trace: TraceContext,
    call_id: str | None = None,
) -> str:
    """自动拼接 trace_id/span_id/turn_id，禁止调用方手写拼接作为唯一来源。"""
    return f"{format_trace_prefix(trace, call_id=call_id)} {message}"


@dataclass
class InMemoryPublisher:
    """单测用的审计发布器。"""

    turns: list[dict[str, str]] = field(default_factory=list)
    spans: list[dict[str, str | int | None]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    def start_turn(
        self,
        trace: TraceContext,
        *,
        session_id: str,
        status: str = TurnStatus.INIT,
    ) -> None:
        _require_trace(trace)
        self.turns.append(
            {
                "trace_id": trace.trace_id,
                "turn_id": trace.turn_id,
                "session_id": session_id,
                "status": str(status),
            }
        )
        self.log(f"Turn 开始 session={session_id[:8]}", trace=trace)

    def set_turn_status(self, trace: TraceContext, *, status: str, finished: bool = False) -> None:
        _require_trace(trace)
        _ = finished
        for row in reversed(self.turns):
            if row.get("trace_id") == trace.trace_id:
                row["status"] = str(status)
                break
        self.log(f"Turn 状态 status={status}", trace=trace)

    def finish_turn(self, trace: TraceContext, *, status: str) -> None:
        self.set_turn_status(trace, status=status, finished=True)
        self.log(f"Turn 结束 status={status}", trace=trace)

    def record_span(self, trace: TraceContext, *, latency_ms: int = 0) -> None:
        _require_trace(trace)
        self.spans.append(
            {
                "trace_id": trace.trace_id,
                "span_id": trace.span_id,
                "parent_span_id": trace.parent_span_id,
                "component": trace.component,
                "latency_ms": latency_ms,
            }
        )

    def log(
        self,
        message: str,
        *,
        trace: TraceContext,
        call_id: str | None = None,
    ) -> None:
        _require_trace(trace)
        line = format_traced_message(message, trace=trace, call_id=call_id)
        self.logs.append(line)
        with using_trace(trace):
            agent_trace(message if not call_id else f"call_id={call_id} {message}")


class PgAuditPublisher:
    """把 Turn / Span 写入 PG；失败只打控制台，不得把 traceback 发给浏览器。"""

    def start_turn(
        self,
        trace: TraceContext,
        *,
        session_id: str,
        status: str = TurnStatus.INIT,
    ) -> None:
        from app.db import SessionLocal
        from app.models import HarnessTurn

        _require_trace(trace)
        db = SessionLocal()
        try:
            db.add(
                HarnessTurn(
                    trace_id=trace.trace_id,
                    turn_id=trace.turn_id,
                    session_id=session_id,
                    status=str(status),
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            agent_trace(f"Turn 审计落库失败 type={type(exc).__name__}")
        finally:
            db.close()
        self.log(f"Turn 开始 session={session_id[:8]}", trace=trace)

    def set_turn_status(self, trace: TraceContext, *, status: str, finished: bool = False) -> None:
        from app.db import SessionLocal
        from app.models import HarnessTurn

        _require_trace(trace)
        db = SessionLocal()
        try:
            row = db.query(HarnessTurn).filter(HarnessTurn.trace_id == trace.trace_id).first()
            if row is not None:
                row.status = str(status)
                if finished:
                    row.finished_at = datetime.now(UTC)
                db.commit()
        except Exception as exc:
            db.rollback()
            agent_trace(f"Turn 状态落库失败 type={type(exc).__name__}")
        finally:
            db.close()
        self.log(f"Turn 状态 status={status}", trace=trace)

    def finish_turn(self, trace: TraceContext, *, status: str) -> None:
        self.set_turn_status(trace, status=status, finished=True)
        self.log(f"Turn 结束 status={status}", trace=trace)

    def record_span(self, trace: TraceContext, *, latency_ms: int = 0) -> None:
        from app.db import SessionLocal
        from app.models import HarnessSpan

        _require_trace(trace)
        db = SessionLocal()
        try:
            existing = db.query(HarnessSpan).filter(HarnessSpan.span_id == trace.span_id).first()
            if existing is None:
                db.add(
                    HarnessSpan(
                        span_id=trace.span_id,
                        trace_id=trace.trace_id,
                        parent_span_id=trace.parent_span_id,
                        component=trace.component or "",
                        latency_ms=latency_ms,
                    )
                )
            else:
                existing.latency_ms = latency_ms
            db.commit()
        except Exception as exc:
            db.rollback()
            agent_trace(f"Span 审计落库失败 type={type(exc).__name__}")
        finally:
            db.close()

    def log(
        self,
        message: str,
        *,
        trace: TraceContext,
        call_id: str | None = None,
    ) -> None:
        _require_trace(trace)
        with using_trace(trace):
            agent_trace(message if not call_id else f"call_id={call_id} {message}")


_PUBLISHER: AuditPublisher = InMemoryPublisher()


def publisher() -> AuditPublisher:
    """当前审计发布器。"""
    return _PUBLISHER


def reset_publisher(*, store: AuditPublisher | None = None) -> AuditPublisher:
    """替换或重建发布器，供测试隔离。"""
    global _PUBLISHER
    _PUBLISHER = store if store is not None else InMemoryPublisher()
    return _PUBLISHER
