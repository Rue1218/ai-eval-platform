"""M2 上下文工程层单测（X-A1~X-A7）；不依赖 DB。"""

import pytest

from app.errors import AppError
from app.harness.context import (
    COMPACT_VERSION,
    WindowMessage,
    assemble,
    is_window_eligible,
    parse_compact,
    project_meter,
    recent_window,
    summarize,
    to_observation,
)
from app.harness.contracts import Observation


def _messages(count: int) -> list[WindowMessage]:
    """构造 count 条 user/assistant 交替消息（source_id 自增）。"""
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"消息-{index}",
            "source_id": f"message:{index}",
        }
        for index in range(count)
    ]


def test_recent_window_default_20_tail() -> None:
    """X-A1：recent_window 默认取末尾 20 条。"""
    window = recent_window(_messages(50))
    assert len(window) == 20
    assert window[0]["content"] == "消息-30"
    assert window[-1]["content"] == "消息-49"


def test_recent_window_compact_keep_from_truncates() -> None:
    """X-A1：compact_keep_from 指定保留起点时截断更早消息。"""
    window = recent_window(_messages(50), keep_from="message:35")
    assert window[0]["content"] == "消息-35"
    assert len(window) == 15


def test_recent_window_keep_from_missing_ignored() -> None:
    """X-A1：keep_from 未命中时忽略，回退末尾 limit。"""
    window = recent_window(_messages(10), keep_from="message:999")
    assert len(window) == 10


def test_window_filters_non_user_assistant() -> None:
    """X-A2：窗口只含 user/assistant，事件（thought/tool/confirm）被过滤。"""
    assert is_window_eligible("user") is True
    assert is_window_eligible("assistant") is True
    assert is_window_eligible("thought") is False
    assert is_window_eligible("tool_call") is False
    assert is_window_eligible("confirm") is False
    assert is_window_eligible("progress") is False


def test_assemble_order_persona_skill_summary_stage_messages() -> None:
    """X-A4：装配顺序 Persona → Skill Hint → 摘要 → 阶段输入 → 消息。"""
    result = assemble(
        system="【Persona】评测助手",
        skill_hints=("技能A：基准评测",),
        summary="已评测 mmlu",
        stage_input="请输出规划 JSON",
        messages=[{"role": "user", "content": "你好"}],
    )
    system = result["system"]
    persona_index = system.index("【Persona】")
    skill_index = system.index("技能A")
    summary_index = system.index("已评测 mmlu")
    stage_index = system.index("请输出规划 JSON")
    assert persona_index < skill_index < summary_index < stage_index
    assert result["messages"] == [{"role": "user", "content": "你好"}]
    assert result["tools"] == []


def test_assemble_omits_empty_sections() -> None:
    """X-A4：空的可选段不占位。"""
    result = assemble(system="【Persona】", messages=[{"role": "user", "content": "hi"}])
    assert result["system"] == "【Persona】"


def test_assemble_injects_tool_defs() -> None:
    """X-4：按本轮最小注入工具定义（tools 透传）。"""
    result = assemble(
        system="【Persona】",
        messages=[{"role": "user", "content": "hi"}],
        tool_defs=[{"name": "web_search", "description": "搜索"}],
    )
    assert result["tools"] == [{"name": "web_search", "description": "搜索"}]


def test_to_observation_redacts_and_truncates_with_source() -> None:
    """X-A3：observation 摘要先脱敏再截断，带 truncated 与 source 溯源。"""
    observation = Observation(
        tool="web_fetch",
        text="http://example.com " + "x" * 3000,
        ok=True,
        truncated=False,
        source="message:abc",
    )
    line = to_observation(observation, max_chars=100)
    assert "[截断]" in line
    assert "来源：message:abc" in line
    assert len(line) < 200


def test_to_observation_marks_ok_and_failed() -> None:
    """observation 摘要携带 ok 标记。"""
    ok = to_observation(Observation(tool="read", text="内容", ok=True))
    failed = to_observation(Observation(tool="read", text="失败", ok=False))
    assert ok.startswith("✅")
    assert failed.startswith("⚠️")
    assert "[read]" in ok


def test_compact_summarize_keeps_recent_six() -> None:
    """X-A6：/compact 保留最近 6 条、摘要 ≤2000 字符、原始记录保留。"""
    messages = _messages(20)
    summary, kept_ids = summarize(messages)
    assert len(kept_ids) == 6
    assert kept_ids == [f"message:{index}" for index in range(14, 20)]
    assert len(summary) <= 2000
    # 原始记录不删除
    assert len(messages) == 20


def test_compact_summarize_truncates_overlong() -> None:
    """X-A6：超长摘要截断带标记。"""
    messages = [{"role": "user", "content": "x" * 300, "source_id": "m1"}] * 10
    summary, _ = summarize(messages, max_summary_chars=100)
    assert len(summary) <= 105
    assert "截断" in summary


def test_parse_compact_strict_schema() -> None:
    """X-A6：CompactProtocol 严格校验（缺字段/多字段/版本拒绝）。"""
    raw = (
        '{"protocol": "compact", "version": "compact.v1", '
        '"summary": "摘要", "kept_ids": ["m1"], "token_count": 10}'
    )
    result = parse_compact(raw)
    assert result["version"] == COMPACT_VERSION
    assert result["fields"]["summary"] == "摘要"
    with pytest.raises(AppError):
        parse_compact('{"protocol": "compact", "version": "compact.v1", "summary": "摘要"}')
    with pytest.raises(AppError):
        parse_compact(raw.replace('"version": "compact.v1"', '"version": "compact.v0"'))


def test_project_meter_matches_context_meter() -> None:
    """X-A7：ContextMeter 投影字段与 context_meter 一致。"""
    meter = project_meter(
        {"token_used": 3000, "token_limit": 8192, "window_ratio": 0.37, "compacted": True}
    )
    assert meter == {
        "token_used": 3000,
        "token_limit": 8192,
        "window_ratio": 0.37,
        "compacted": True,
    }
    # null 不渲染
    assert project_meter(None) is None
    assert project_meter({}) is None
