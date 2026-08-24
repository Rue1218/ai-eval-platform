"""Harness 反馈层（M6）：规则门禁、归一、模型核对、失败预算与事件隔离。"""

from .budget import FeedbackBudget, consume_failure, is_exhausted
from .isolation import WORKER_EVENTS, assert_not_in_messages, isolate_worker_event
from .observation import normalize, normalize_exception
from .review import ReflectVerdict, review
from .rules import (
    BASH_BLOCK_PREFIXES,
    CONFIRM_KINDS,
    GateContext,
    GateResult,
    assert_gates,
    check_gates,
)

__all__ = [
    "BASH_BLOCK_PREFIXES",
    "CONFIRM_KINDS",
    "FeedbackBudget",
    "GateContext",
    "GateResult",
    "ReflectVerdict",
    "WORKER_EVENTS",
    "assert_gates",
    "assert_not_in_messages",
    "check_gates",
    "consume_failure",
    "is_exhausted",
    "isolate_worker_event",
    "normalize",
    "normalize_exception",
    "review",
]
