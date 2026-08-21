"""强制链路追踪：trace_id 标识整个用户 Turn，span_id 标识单次跨层操作。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


def new_trace_id() -> str:
    """生成全 Turn 唯一的 trace_id。"""
    return f"T-{uuid.uuid4().hex[:16]}"


def new_span_id() -> str:
    """生成当前操作唯一的 span_id。"""
    return f"S-{uuid.uuid4().hex[:16]}"


def new_turn_id() -> str:
    """生成与产品回合对应的 turn_id。"""
    return f"turn-{uuid.uuid4().hex[:16]}"


def new_call_id() -> str:
    """生成 Turn 内唯一的工具调用 call_id。"""
    return f"call-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class TraceContext:
    """不可选的请求链路上下文；禁止缓存到无状态服务的 ``__init__``。"""

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
        """派生同 trace_id 的子 span；parent 指向当前 span。"""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            parent_span_id=self.span_id,
            turn_id=self.turn_id,
            component=component,
        )

    @classmethod
    def for_turn(cls, *, turn_id: str | None = None, component: str = "turn") -> TraceContext:
        """进入 Harness 时创建根 TraceContext。"""
        return cls(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            turn_id=turn_id or new_turn_id(),
            parent_span_id=None,
            component=component,
        )
