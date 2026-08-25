"""Harness 上下文工程层：observation 摘要（M2 阶段 2，CX-3）。

``to_observation`` 把工具结果归一为注入模型的摘要文本：先调 M8 递归脱敏
（secret 脱敏发生在注入前，红色操作只在本层），再截断超长文本并带
``truncated`` 标记与 ``source`` 溯源（复用 messages 表 source_id 格式）。
"""

from __future__ import annotations

from app.harness.contracts import Observation
from app.harness.security.secrets import redact

# 注入模型的单条工具结果上限。超过会拖慢预填充、挤占上下文并触发 TIMEOUT。
# ToolCard 仍走各自 preview；磁盘/沙箱窗口与此对齐，避免模型只看到半页却拿到错误 next_offset。
MODEL_TOOL_RESULT_MAX_CHARS = 8_000
DEFAULT_MAX_CHARS = MODEL_TOOL_RESULT_MAX_CHARS

_TRUNCATE_MARKER = "…[截断]"


def truncate_with_marker(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    """超长截断，保留头尾并带标记（X-D2）；未超长原样返回。"""
    if max_chars <= 0:
        return _TRUNCATE_MARKER, True
    if len(text) <= max_chars:
        return text, False
    marker = _TRUNCATE_MARKER
    budget = max(0, max_chars - len(marker))
    if budget <= 1:
        return (text[:max_chars] + marker)[: max_chars + len(marker)], True
    head = max(1, budget // 2)
    tail = max(1, budget - head)
    return text[:head] + marker + text[-tail:], True


def to_observation(
    obs: Observation,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    source: str | None = None,
) -> str:
    """Observation → 注入模型的摘要文本（CX-3）。

    脱敏（M8 redact）发生在注入前；截断带标记；溯源复用 source_id 格式
    （如 ``file:uuid`` / ``message:uuid``）。
    """
    text = str(redact(obs.text) or "")
    text, truncated = truncate_with_marker(text, max_chars=max_chars)
    prefix = "✅" if obs.ok else "⚠️"
    line = f"{prefix} [{obs.tool}] {text}"
    hint = str(getattr(obs, "repair_hint", "") or "").strip()
    if hint:
        hint_text, _ = truncate_with_marker(str(redact(hint) or ""), max_chars=min(400, max_chars))
        line += f" 修复建议：{hint_text}"
    if truncated or obs.truncated:
        line += " [内容已截断]"
    origin = source or obs.source  # 溯源复用 source_id 格式（file:uuid / message:uuid）
    if origin:
        line += f"（来源：{origin}）"
    return line
