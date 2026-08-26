"""思考链瞬态帧合并：上游按字增量，WS 不应一帧一字。

生产探针（「用一句话介绍你自己」）曾在约 7.5s 内打出 400+ 条
``thought.stream=think``，首字节思考仍合理，但帧密度会拖垮前端 ThoughtCard
与连接。本模块把增量合并后再交给 ``ws.py`` 发送；完整快照仍由调用方用
``"".join(thinking)`` 发 ``think_final``。
"""

from __future__ import annotations

import time
from collections.abc import Callable


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
