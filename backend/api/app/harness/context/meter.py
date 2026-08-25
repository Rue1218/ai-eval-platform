"""Harness 上下文工程层：ContextMeter 计算与投影（M2 阶段 3，CX-7）。

服务端按**实际发往模型的消息窗口**估算 token，经
``GET /api/sessions/{id}/messages.context_meter`` 下发。前端只读该字段，
禁止按 messages 总条数自行估算（CX-7 / API.md §3.4）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypedDict

DEFAULT_MAX_TOKENS = 200_000
DEFAULT_WINDOW = 20
DEFAULT_MCP_TOOLS_MAX = 28
DEFAULT_MEMORY_FILES_MAX = 1


class ContextMeter(TypedDict, total=False):
    """ContextMeter 投影，对齐 API.md §3.4。"""

    messages: int
    skills: int
    summary: int
    headroom: int
    window: int
    total_tokens: int
    max_tokens: int
    messages_tokens: int
    skills_tokens: int
    free_tokens: int
    used_percent: float
    messages_percent: float
    skills_percent: float
    free_percent: float
    mcp_tools_count: int
    mcp_tools_max: int
    memory_files_count: int
    memory_files_max: int
    compacted: bool
    token_used: int
    token_limit: int
    window_ratio: float


def estimate_tokens(text: str) -> int:
    """确定性 token 估算：CJK 约 1.5 字/token，其余约 4 字符/token。"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
            cjk += 1
        else:
            other += 1
    return max(0, round(cjk / 1.5 + other / 4.0))


def _as_int(value: object, default: int = 0) -> int:
    """安全取整。"""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    """安全取浮点。"""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _percent(part: int, whole: int) -> float:
    """占比百分比，保留 1 位小数。"""
    if whole <= 0:
        return 0.0
    return round(min(100.0, max(0.0, part / whole * 100.0)), 1)


def compute_meter(
    messages: Sequence[Mapping[str, object]],
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    compact_summary: str | None = None,
    skills_text: str = "",
    mcp_tools_count: int = 0,
    mcp_tools_max: int = DEFAULT_MCP_TOOLS_MAX,
    memory_files_count: int = 0,
    memory_files_max: int = DEFAULT_MEMORY_FILES_MAX,
    window: int = DEFAULT_WINDOW,
) -> ContextMeter:
    """按窗口消息 + 摘要 + 技能 Hint 计算前端可读 meter（API.md §3.4）。"""
    limit = max(1, int(window or DEFAULT_WINDOW))
    token_limit = max(1, int(max_tokens or DEFAULT_MAX_TOKENS))
    message_count = min(len(messages), limit)
    body = "\n".join(str(item.get("content") or "") for item in messages)
    messages_tokens = estimate_tokens(body)
    skills_tokens = estimate_tokens(skills_text) if skills_text else 0
    summary_text = (compact_summary or "").strip()
    summary_tokens = estimate_tokens(summary_text) if summary_text else 0
    total_tokens = messages_tokens + skills_tokens + summary_tokens
    free_tokens = max(0, token_limit - total_tokens)
    compacted = bool(summary_text)
    skills_flag = 1 if skills_tokens > 0 else 0
    summary_flag = 1 if compacted else 0
    used_percent = _percent(total_tokens, token_limit)
    return ContextMeter(
        messages=message_count,
        skills=skills_flag,
        summary=summary_flag,
        headroom=max(0, limit - message_count),
        window=limit,
        total_tokens=total_tokens,
        max_tokens=token_limit,
        messages_tokens=messages_tokens,
        skills_tokens=skills_tokens,
        free_tokens=free_tokens,
        used_percent=used_percent,
        messages_percent=_percent(messages_tokens, token_limit),
        skills_percent=_percent(skills_tokens, token_limit),
        free_percent=_percent(free_tokens, token_limit),
        mcp_tools_count=max(0, int(mcp_tools_count)),
        mcp_tools_max=max(0, int(mcp_tools_max)),
        memory_files_count=max(0, int(memory_files_count)),
        memory_files_max=max(0, int(memory_files_max)),
        compacted=compacted,
        token_used=total_tokens,
        token_limit=token_limit,
        window_ratio=round(total_tokens / token_limit, 4),
    )


def project_meter(context_meter: Mapping[str, object] | None) -> ContextMeter | None:
    """把已有 context_meter 投影为前端可读字段。"""
    if not context_meter:
        return None
    token_limit = _as_int(
        context_meter.get("max_tokens") or context_meter.get("token_limit"),
        DEFAULT_MAX_TOKENS,
    )
    token_used = _as_int(
        context_meter.get("total_tokens") or context_meter.get("token_used"),
        0,
    )
    messages_tokens = _as_int(context_meter.get("messages_tokens"), token_used)
    skills_tokens = _as_int(context_meter.get("skills_tokens"), 0)
    free_tokens = _as_int(context_meter.get("free_tokens"), max(0, token_limit - token_used))
    window = _as_int(context_meter.get("window"), DEFAULT_WINDOW)
    message_count = _as_int(context_meter.get("messages"), 0)
    compacted = bool(context_meter.get("compacted", False))
    ratio = _as_float(context_meter.get("window_ratio"), 0.0)
    if token_limit > 0 and "window_ratio" not in context_meter:
        ratio = round(token_used / token_limit, 4)
    used_percent = _as_float(context_meter.get("used_percent"), _percent(token_used, token_limit))
    return ContextMeter(
        messages=message_count,
        skills=_as_int(context_meter.get("skills"), 1 if skills_tokens else 0),
        summary=_as_int(context_meter.get("summary"), 1 if compacted else 0),
        headroom=_as_int(context_meter.get("headroom"), max(0, window - message_count)),
        window=window,
        total_tokens=token_used,
        max_tokens=token_limit,
        messages_tokens=messages_tokens,
        skills_tokens=skills_tokens,
        free_tokens=free_tokens,
        used_percent=used_percent,
        messages_percent=_as_float(
            context_meter.get("messages_percent"),
            _percent(messages_tokens, token_limit),
        ),
        skills_percent=_as_float(
            context_meter.get("skills_percent"),
            _percent(skills_tokens, token_limit),
        ),
        free_percent=_as_float(
            context_meter.get("free_percent"),
            _percent(free_tokens, token_limit),
        ),
        mcp_tools_count=_as_int(context_meter.get("mcp_tools_count"), 0),
        mcp_tools_max=_as_int(context_meter.get("mcp_tools_max"), DEFAULT_MCP_TOOLS_MAX),
        memory_files_count=_as_int(context_meter.get("memory_files_count"), 0),
        memory_files_max=_as_int(context_meter.get("memory_files_max"), DEFAULT_MEMORY_FILES_MAX),
        compacted=compacted,
        token_used=token_used,
        token_limit=token_limit,
        window_ratio=ratio,
    )
