"""Harness 跨层安全（M8）：递归脱敏与确认卡行锁。"""

from .auth import (
    PendingConfirm,
    assert_confirm_owner,
    assert_no_concurrent_confirm,
    lock_pending_confirm,
)
from .secrets import (
    REDACT_KEYS,
    is_sensitive_key,
    mask_full,
    mask_partial,
    redact,
    redact_for_log,
)

__all__ = [
    "PendingConfirm",
    "REDACT_KEYS",
    "assert_confirm_owner",
    "assert_no_concurrent_confirm",
    "is_sensitive_key",
    "lock_pending_confirm",
    "mask_full",
    "mask_partial",
    "redact",
    "redact_for_log",
]
