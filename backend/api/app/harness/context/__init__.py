"""Harness 上下文工程层（M2）：窗口/装配/observation 摘要/compact 摘要/meter。"""

from .assembly import (
    assemble,
    compact_summary_from_configurable,
    select_tool_defs,
    skill_hint_lines,
)
from .compact import (
    COMPACT_SCHEMA,
    COMPACT_VERSION,
    CompactProtocolResult,
    parse_compact,
    summarize,
)
from .meter import ContextMeter, compute_meter, estimate_tokens, project_meter
from .observation import (
    DEFAULT_MAX_CHARS,
    MODEL_TOOL_RESULT_MAX_CHARS,
    to_observation,
    truncate_with_marker,
)
from .window import WindowMessage, is_window_eligible, recent_window

__all__ = [
    "COMPACT_SCHEMA",
    "COMPACT_VERSION",
    "CompactProtocolResult",
    "ContextMeter",
    "DEFAULT_MAX_CHARS",
    "MODEL_TOOL_RESULT_MAX_CHARS",
    "WindowMessage",
    "assemble",
    "compact_summary_from_configurable",
    "compute_meter",
    "estimate_tokens",
    "is_window_eligible",
    "parse_compact",
    "project_meter",
    "recent_window",
    "select_tool_defs",
    "skill_hint_lines",
    "summarize",
    "to_observation",
    "truncate_with_marker",
]
