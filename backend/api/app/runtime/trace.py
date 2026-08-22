"""跨层链路追踪契约：模型调用层不依赖 Harness 即可记录 trace。"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


def new_trace_id() -> str:
    """生成一个用户回合级 trace_id。"""
    return f"T-{uuid.uuid4().hex[:16]}"


def new_span_id() -> str:
    """生成一个操作级 span_id。"""
    return f"S-{uuid.uuid4().hex[:16]}"


def new_turn_id() -> str:
    """生成一个回合级 turn_id。"""
    return f"turn-{uuid.uuid4().hex[:16]}"


def new_call_id() -> str:
    """生成一个工具或模型调用级 call_id。"""
    return f"call-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class TraceContext:
    """不可为空的链路上下文；可按组件派生子 span。"""

    trace_id: str
    span_id: str
    turn_id: str
    parent_span_id: str | None = None
    component: str = ""

    def __post_init__(self) -> None:
        if not self.trace_id or not str(self.trace_id).strip():
            raise ValueError("trace_id 不可为空")
        if not self.span_id or not str(self.span_id).strip():
            raise ValueError("span_id 不可为空")
        if not self.turn_id or not str(self.turn_id).strip():
            raise ValueError("turn_id 不可为空")

    def child(self, component: str) -> TraceContext:
        """派生同一回合的子 span。"""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            parent_span_id=self.span_id,
            turn_id=self.turn_id,
            component=component,
        )

    @classmethod
    def for_turn(cls, *, turn_id: str | None = None, component: str = "turn") -> TraceContext:
        """创建一个新的用户回合根上下文。"""
        return cls(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            turn_id=turn_id or new_turn_id(),
            component=component,
        )


_CURRENT_TRACE: ContextVar[TraceContext | None] = ContextVar("current_trace", default=None)


def current_trace() -> TraceContext | None:
    """读取当前上下文绑定的 trace。"""
    return _CURRENT_TRACE.get()


def format_trace_prefix(trace: TraceContext, *, call_id: str | None = None) -> str:
    """构造不含敏感信息的日志前缀。"""
    parts = [
        f"trace_id={trace.trace_id}",
        f"span_id={trace.span_id}",
        f"turn_id={trace.turn_id}",
    ]
    if trace.component:
        parts.append(f"component={trace.component}")
    if call_id:
        parts.append(f"call_id={call_id}")
    return " ".join(parts)


@contextmanager
def using_trace(trace: TraceContext) -> Iterator[TraceContext]:
    """在当前执行上下文绑定 trace，结束后恢复旧值。"""
    token = _CURRENT_TRACE.set(trace)
    try:
        yield trace
    finally:
        _CURRENT_TRACE.reset(token)
