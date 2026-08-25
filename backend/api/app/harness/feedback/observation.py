"""Harness 反馈层：工具结果归一为 observation（M6 阶段 2，FB-1）。

``normalize`` 把 M5 dispatch 执行产物（ToolResult 或异常）归一为
``Observation``：正常 → ok=True；异常 → ok=False（**不裸抛**，不导致 Agent
崩溃）。本层是归一逻辑 owner（M6-D1）；递归脱敏由 M2 注入上下文前调 M8 完成，
本层只标 ``redacted=True``。
"""

from __future__ import annotations

from collections.abc import Mapping

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
    arguments: Mapping[str, object] | None = None,
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
            arguments=arguments,
            repair_hint=_repair_hint_from_error(None, exc),
        )
    if raw is None:
        return Observation(
            tool=tool,
            text="操作未返回结果",
            ok=False,
            redacted=True,
            source=source,
            arguments=arguments,
        )
    data = raw.data or {}
    error = raw.error if isinstance(raw.error, dict) else {}
    error_message = str(error.get("message") or "") if error else ""
    # ``model_text`` 仅在服务端进入 Observation，不能透传到 ToolCard。read 以此
    # 保留按行读取的完整片段，``display`` 则是浏览器可见的短预览和元数据。
    text = str(
        data.get("model_text")
        or data.get("summary")
        or data.get("text")
        or error_message
        or "执行成功"
    )
    display = data.get("display")
    if not isinstance(display, Mapping):
        display = {
            "summary": str(
                data.get("summary") or data.get("text") or error_message or "执行成功"
            )
        }
    data_source = data.get("source")
    return Observation(
        tool=tool,
        text=text,
        ok=raw.ok,
        truncated=bool(data.get("truncated", False)),
        source=source or (str(data_source) if data_source else None) or error.get("source"),
        redacted=True,
        arguments=arguments,
        display_data=dict(display),
        repair_hint="" if raw.ok else _repair_hint_from_error(error, None),
    )


def _repair_hint_from_error(
    error: Mapping[str, object] | None,
    exc: Exception | None,
) -> str:
    """提取模型可见的修复建议；缺省为空，不把内部栈写进去。"""
    if error and error.get("repair_hint"):
        return str(error.get("repair_hint") or "")[:500]
    fields = getattr(exc, "fields", None)
    if isinstance(fields, Mapping) and fields.get("repair_hint"):
        return str(fields.get("repair_hint") or "")[:500]
    message = str(getattr(exc, "message", "") or "")
    if message and message not in {"操作失败", "操作失败（INTERNAL）"}:
        return message[:500]
    return ""


def normalize_exception(
    exc: Exception, *, tool: str, arguments: Mapping[str, object] | None = None
) -> Observation:
    """异常专归一：返回 ok=False observation，不抛出（F-A1）。"""
    return normalize(None, exc, tool=tool, arguments=arguments)
