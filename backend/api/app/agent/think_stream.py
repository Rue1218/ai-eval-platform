"""思考链瞬态帧合并 + 可展示摘要。

上游按字增量时，WS 不应一帧一字。生产探针还发现部分协议档会把英文隐藏
CoT（``Here's a thinking process`` / ``Analyze User Input``）整段推给前端，
违反 API.md「不暴露隐藏思维链、只展示 reasoning summary」。本模块：

- ``ThinkStreamCoalescer``：首帧立即，之后按间隔与字数合并；
- ``sanitize_reasoning`` / ``ReasoningDisplayFilter``：把隐藏 CoT 收成可展示
  摘要；中文思考原文保留。完整快照由调用方对累计原文再 ``sanitize_reasoning``
  后发 ``think_final``。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Literal

# 可展示摘要（隐藏 CoT 的替代文案；不暴露逐步分析稿）
DISPLAY_REASONING_SUMMARY = "正在分析问题并组织回复。"

# 隐藏 CoT 包装头（大小写不敏感）
_WRAPPER_PREFIXES: tuple[str, ...] = (
    "here's a thinking process:",
    "here's my thinking process:",
    "here's the thinking process:",
    "thinking process:",
    "let me think step by step",
    "let me think through this",
)

# 英文隐藏 CoT 章节标题 / 元分析套话
_HIDDEN_MARKERS: tuple[str, ...] = (
    "analyze user input",
    "identify key points",
    "consider the user's",
    "the user asked",
    "the user wants",
    "break down the request",
    "step-by-step reasoning",
    "hidden chain",
    "chain of thought",
    "here's a thinking process",
)

_WRAPPER_START_RE = re.compile(
    r"^\s*(here'?s\b|let me think\b|thinking process\b|analyze user\b)",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

ClassifyMode = Literal["unknown", "hidden", "visible"]


def _cjk_ratio(text: str) -> float:
    """汉字占比；用于判断思考是否已是可展示中文，而不是英文隐藏稿。"""
    if not text:
        return 0.0
    return len(_CJK_RE.findall(text)) / len(text)


def strip_reasoning_wrappers(text: str) -> str:
    """去掉英文隐藏 CoT 包装头，保留其后正文。"""
    body = text.strip()
    lowered = body.lower()
    for prefix in _WRAPPER_PREFIXES:
        if lowered.startswith(prefix):
            body = body[len(prefix) :].lstrip(" \n\t:-")
            lowered = body.lower()
    return body.strip()


def is_hidden_chain_of_thought(text: str) -> bool:
    """累计思考是否为不可展示的隐藏 CoT（英文元分析稿）。"""
    body = strip_reasoning_wrappers(text)
    blob = f"{text}\n{body}".lower()
    if not any(marker in blob for marker in _HIDDEN_MARKERS) and not any(
        blob.lstrip().startswith(prefix) for prefix in _WRAPPER_PREFIXES
    ):
        return False
    # 包装头后若已是中文思考，只剥头、不当隐藏链整段替换
    return _cjk_ratio(body) < 0.25


def classify_reasoning(text: str) -> ClassifyMode:
    """对累计思考做三分：仍太短 / 隐藏 CoT / 可展示。"""
    stripped = text.strip()
    if not stripped:
        return "unknown"
    if is_hidden_chain_of_thought(stripped):
        return "hidden"
    body = strip_reasoning_wrappers(stripped)
    if _cjk_ratio(body) >= 0.25 and len(body) >= 2:
        return "visible"
    if _WRAPPER_START_RE.match(stripped) and len(stripped) < 80:
        return "unknown"
    if len(stripped) >= 24:
        return "visible"
    return "unknown"


def sanitize_reasoning(text: str) -> str:
    """把上游 reasoning 收成可展示摘要（API.md：不暴露隐藏思维链）。

    中文思考保留（可剥包装头）；英文隐藏 CoT 替换为短摘要；空输入返回空串。
    """
    stripped = text.strip()
    if not stripped:
        return ""
    if is_hidden_chain_of_thought(stripped):
        return DISPLAY_REASONING_SUMMARY
    return strip_reasoning_wrappers(stripped) or DISPLAY_REASONING_SUMMARY


class ReasoningDisplayFilter:
    """流式思考分类器：隐藏 CoT 只下发一次摘要，可展示原文按增量放出。

    ``unknown`` 时暂扣增量，避免把 ``Here's a th`` 这类包装头首字立即推给前端。
    """

    def __init__(self) -> None:
        self._acc: list[str] = []
        self._mode: ClassifyMode = "unknown"

    def feed(self, chunk: str) -> list[str]:
        """吃进一段上游 reasoning；返回本轮应进入合并器的可见文本。"""
        if not chunk:
            return []
        if self._mode == "hidden":
            return []
        if self._mode == "visible":
            return [chunk]
        self._acc.append(chunk)
        acc = "".join(self._acc)
        decision = classify_reasoning(acc)
        if decision == "unknown":
            return []
        if decision == "hidden":
            self._mode = "hidden"
            return [DISPLAY_REASONING_SUMMARY]
        self._mode = "visible"
        body = strip_reasoning_wrappers(acc)
        return [body] if body else []


class ThinkStreamCoalescer:
    """合并 reasoning 增量。首帧立即发出，之后按间隔与字数节流。"""

    def __init__(
        self,
        *,
        min_interval_s: float = 0.08,
        min_chars: int = 16,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.min_chars = min_chars
        self._clock = clock
        self._buf: list[str] = []
        self._last_flush = 0.0
        self._emitted = False

    def push(self, text: str) -> str | None:
        """吃进一段增量；若应立刻下发则返回合并文本，否则返回 None。"""
        if not text:
            return None
        self._buf.append(text)
        if not self._emitted:
            return self.flush()
        chars = sum(len(part) for part in self._buf)
        elapsed = self._clock() - self._last_flush
        if chars >= self.min_chars and elapsed >= self.min_interval_s:
            return self.flush()
        return None

    def flush(self) -> str | None:
        """强制打出缓冲区（正文开始前、think_final 前必须调用）。"""
        if not self._buf:
            return None
        text = "".join(self._buf)
        self._buf.clear()
        self._last_flush = self._clock()
        self._emitted = True
        return text
