"""思考链瞬态帧合并单测：不触碰 WS / 真实模型。"""

from __future__ import annotations

from app.agent.think_stream import ThinkStreamCoalescer


class _Clock:
    """可控时钟，避免用真实 sleep 测节流。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_first_token_flushes_immediately() -> None:
    """首帧立即下发，保证思考卡尽快出现。"""
    clock = _Clock()
    coalescer = ThinkStreamCoalescer(clock=clock)
    assert coalescer.push("先") == "先"
    assert coalescer.flush() is None


def test_subsequent_tokens_coalesce_by_interval_and_chars() -> None:
    """后续增量按 16 字 + 80ms 合并，而不是一字一帧。"""
    clock = _Clock()
    coalescer = ThinkStreamCoalescer(min_interval_s=0.08, min_chars=16, clock=clock)
    assert coalescer.push("A") == "A"
    for _ in range(15):
        assert coalescer.push("x") is None
    clock.now = 0.08
    assert coalescer.push("y") == "xxxxxxxxxxxxxxx" + "y"
    assert coalescer.flush() is None


def test_flush_emits_remainder_before_content() -> None:
    """正文开始前必须打出剩余缓冲，避免思考尾字丢失。"""
    clock = _Clock()
    coalescer = ThinkStreamCoalescer(clock=clock)
    assert coalescer.push("开") == "开"
    assert coalescer.push("始") is None
    assert coalescer.flush() == "始"
