"""Harness 反馈层：工具结果归一为 observation（M6 阶段 2，FB-1）。

``normalize`` 把 M5 dispatch 执行产物（ToolResult 或异常）归一为
``Observation``：正常 → ok=True；异常 → ok=False（**不裸抛**，不导致 Agent
崩溃）。本层是归一逻辑 owner（M6-D1）；递归脱敏由 M2 注入上下文前调 M8 完成，
本层只标 ``redacted=True``。
"""

from __future__ import annotations

from app.harness.contracts import Observation, ToolResult


def _error_text(exc: Exception) -> str:
    """把异常归一为脱敏的错误码描述（不对外暴露异常原文，§5.2.1）。"""
    code = getattr(exc, "code", None)
    if code is not None:
        return f"操作失败（{code}）"  # ErrorCode 为 StrEnum，str() 即错误码名
    return "操作失败（INTERNAL）"


def normalize(
    raw: ToolResult | None,
    exc: Exception | None,
    *,
    tool: str,
    source: str | None = None,
) -> Observation:
    """工具结果归一为 Observation（FB-1）：

    - 正常：raw → Observation(ok=True, text=摘要, source=...)
    - 异常：exc → Observation(ok=False, text=归一错误码描述, redacted=True)

    异常不裸抛、不导致 Agent 崩溃；对外只暴露 10 大 ErrorCode 语义。
    """
    if exc is not None:
        return Observation(
            tool=tool,
            text=_error_text(exc),
            ok=False,
            redacted=True,
            source=source,
        )
    if raw is None:
        return Observation(
            tool=tool,
            text="操作未返回结果",
            ok=False,
            redacted=True,
            source=source,
        )
    data = raw.data or {}
    text = str(data.get("summary") or data.get("text") or "执行成功")
    error = raw.error if isinstance(raw.error, dict) else {}
    return Observation(
        tool=tool,
        text=text,
        ok=raw.ok,
        truncated=bool(data.get("truncated", False)),
        source=source or error.get("source"),
        redacted=True,
    )


def normalize_exception(exc: Exception, *, tool: str) -> Observation:
    """异常专归一：返回 ok=False observation，不抛出（F-A1）。"""
    return normalize(None, exc, tool=tool)
