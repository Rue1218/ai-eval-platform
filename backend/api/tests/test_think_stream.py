"""思考链瞬态帧合并单测：不触碰 WS / 真实模型。"""

from __future__ import annotations

from app.agent.think_stream import (
    DISPLAY_REASONING_SUMMARY,
    ReasoningDisplayFilter,
    ThinkStreamCoalescer,
    sanitize_reasoning,
)


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


def test_sanitize_hidden_english_cot_to_summary() -> None:
    """API.md：英文隐藏 CoT 不得原样下发，应收成可展示摘要。"""
    raw = (
        "Here's a thinking process:\n"
        "Analyze User Input: The user asked 用一句话介绍你自己.\n"
        "Identify Key Points: introduce the assistant."
    )
    assert sanitize_reasoning(raw) == DISPLAY_REASONING_SUMMARY
    assert "Analyze User Input" not in sanitize_reasoning(raw)


def test_sanitize_keeps_chinese_thought() -> None:
    """中文思考原文保留，只剥英文包装头。"""
    raw = "Here's a thinking process:\n用户在闲聊问好，用一句话介绍评测助手即可。"
    out = sanitize_reasoning(raw)
    assert "用户在闲聊问好" in out
    assert "Here's a thinking process" not in out


def test_display_filter_holds_wrapper_then_emits_summary_once() -> None:
    """流式：包装头暂扣；判定隐藏后只下发一次摘要，后续英文增量丢弃。"""
    filt = ReasoningDisplayFilter()
    assert filt.feed("Here's a th") == []
    visible = filt.feed("inking process:\nAnalyze User Input: hello")
    assert visible == [DISPLAY_REASONING_SUMMARY]
    assert filt.feed("Identify Key Points: more") == []


def test_display_filter_flushes_held_chinese() -> None:
    """流式：暂扣后一旦可判定为中文思考，整段放出。"""
    filt = ReasoningDisplayFilter()
    assert filt.feed("用") == []
    assert filt.feed("户想了解平台能力") == ["用户想了解平台能力"]
    assert filt.feed("，直接介绍。") == ["，直接介绍。"]
