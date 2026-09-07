"""上下文压缩事件化单测（dsh 改进 #2 首期落地物，API.md V1.74）。

覆盖：超大 tool_result 先裁剪（NativeToolResultStore 限长 + 截断标注、
模型只见带标注的截断结果）；窗口裁剪元信息（window_trim_stats：reason/
dropped/kept 且不含被裁原文——观察纪律）。
"""

from __future__ import annotations

from app.harness.context import is_window_eligible, recent_window, window_trim_stats
from app.harness.execution.native_results import (
    TOOL_RESULT_STORE_MAX_CHARS,
    NativeToolResultStore,
    clip_for_store,
)


def _msg(role: str, content: str, source_id: str | None = None) -> dict:
    return {"role": role, "content": content, "source_id": source_id}


def test_clip_for_store_truncates_overlong_with_notice() -> None:
    """超长正文先裁剪并带截断标注；未超限原样返回不追加标注。"""
    short = "hello"
    stored, truncated = clip_for_store(short)
    assert stored == short
    assert truncated is False

    long_text = "x" * (TOOL_RESULT_STORE_MAX_CHARS + 100)
    stored, truncated = clip_for_store(long_text)
    assert truncated is True
    assert len(stored) < len(long_text)
    assert "已截断" in stored  # 模型可见标注，禁止假装全文在手
    assert stored.startswith("x" * TOOL_RESULT_STORE_MAX_CHARS)


def test_store_put_clips_and_tracks_truncation() -> None:
    """store.put 裁剪后存储；get 只见带标注截断结果；was_truncated 留痕可审计。"""
    store = NativeToolResultStore()
    assert store.put("t-1", "call-big", "y" * (TOOL_RESULT_STORE_MAX_CHARS + 50)) is True
    body = store.get("t-1", "call-big")
    assert body is not None
    assert "已截断" in body
    assert store.was_truncated("t-1", "call-big") is True

    # 小结果不受影响（行为默认不变）
    assert store.put("t-1", "call-small", "ok") is True
    assert store.get("t-1", "call-small") == "ok"
    assert store.was_truncated("t-1", "call-small") is False

    # 重复写入小结果清除截断留痕（幂等一致）
    store.put("t-1", "call-big", "small")
    assert store.was_truncated("t-1", "call-big") is False
    store.clear("t-1")
    assert store.get("t-1", "call-big") is None
    assert store.was_truncated("t-1", "call-big") is False


def _flat(items: list[dict]) -> list[dict]:
    """构造含 user/assistant 与噪声消息的列表。"""
    return list(items)


def test_window_trim_stats_tail_window_meta() -> None:
    """尾窗截断：dropped/kept 统计正确，元信息不含被裁原文。"""
    messages = [
        _msg("user", f"第 {i} 条", f"m-{i}")
        for i in range(25)
    ] + [_msg("tool", "噪声不进窗", "t-1")]
    windowed, meta = window_trim_stats(messages, limit=20)
    assert len(windowed) == 20
    assert windowed[0]["source_id"] == "m-5"  # 末 20 条
    assert meta["reason"] == "tail_window"
    assert meta["dropped"] == 5
    assert meta["kept"] == 20
    assert meta["in_scope_total"] == 25  # tool 噪声不计入
    assert meta["keep_from_id"] is None
    # 与 recent_window 行为一致（同源实现，仅多返回元信息）
    assert recent_window(messages, limit=20) == windowed


def test_window_trim_stats_compact_reason_and_no_trim() -> None:
    """compact（keep_from 命中）reason 区分；无裁剪时 dropped=0。"""
    messages = [_msg("user", f"第 {i} 条", f"m-{i}") for i in range(10)]
    windowed, meta = window_trim_stats(messages, limit=20, keep_from="m-3")
    assert len(windowed) == 7  # m-3 起 7 条
    assert meta["reason"] == "compact"
    assert meta["dropped"] == 3
    assert meta["keep_from_id"] == "m-3"

    small, no_trim = window_trim_stats(messages[:5], limit=20)
    assert no_trim["dropped"] == 0
    assert small == messages[:5]
    # keep_from 未命中时忽略（原始记录仍在 DB，不删除）
    _w, miss = window_trim_stats(messages, limit=20, keep_from="no-such-id")
    assert miss["reason"] == "tail_window"
    assert miss["dropped"] == 0
    assert len(_w) == 10


def test_is_window_eligible_only_user_assistant() -> None:
    """CX-2 纵深防御：仅 user/assistant 可入窗。"""
    assert is_window_eligible("user") and is_window_eligible("assistant")
    assert not is_window_eligible("tool")
    assert not is_window_eligible("thought")
