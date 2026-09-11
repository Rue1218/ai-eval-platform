"""M2 上下文工程层 compact 模块单测：CompactProtocol 严格解析与可控摘要。"""

import json

import pytest

from app.errors import AppError, ErrorCode
from app.harness.context.compact import (
    COMPACT_VERSION,
    DEFAULT_KEEP_RECENT,
    DEFAULT_MAX_SUMMARY_CHARS,
    parse_compact,
    summarize,
)


def _payload(**overrides) -> str:
    """构造合法 compact 协议 JSON；overrides 覆盖字段。"""
    base = {
        "protocol": "compact",
        "version": COMPACT_VERSION,
        "summary": "历史摘要",
        "kept_ids": ["m1", "m2"],
        "token_count": 128,
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


def test_parse_compact_accepts_valid_payload_and_fenced_json():
    """合法载荷（含 ```json 围栏）解析出 protocol/version/fields。"""
    result = parse_compact(_payload())
    assert result["protocol"] == "compact"
    assert result["version"] == COMPACT_VERSION
    assert result["fields"]["summary"] == "历史摘要"
    assert result["fields"]["kept_ids"] == ["m1", "m2"]
    assert result["fields"]["token_count"] == 128

    fenced = parse_compact(f"```json\n{_payload()}\n```")
    assert fenced["fields"]["summary"] == "历史摘要"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("not-json", "非 JSON"),
        ("[1,2,3]", "JSON 数组不是对象"),
        (_payload(protocol="react"), "协议声明不匹配"),
        (_payload(extra_field=1), "多余字段"),
        ('{"protocol":"compact"}', "缺必填字段"),
        (_payload(summary="x" * (DEFAULT_MAX_SUMMARY_CHARS + 1)), "摘要超长"),
        (_payload(summary=123), "摘要类型非法"),
        (_payload(kept_ids="m1"), "kept_ids 非数组"),
        (_payload(kept_ids=[1, 2]), "kept_ids 元素非字符串"),
        (_payload(token_count="128"), "token_count 非整数"),
        (_payload(token_count=True), "token_count 布尔值拒绝"),
        (_payload(version="compact.v0"), "版本不兼容"),
        (_payload(version=""), "版本缺失"),
    ],
)
def test_parse_compact_rejects_invalid_payloads(raw: str, reason: str):
    """所有协议违规路径统一抛 VALIDATION，不泄漏内部异常。"""
    with pytest.raises(AppError) as exc:
        parse_compact(raw)
    assert exc.value.code == ErrorCode.VALIDATION, reason


def test_summarize_empty_messages_returns_empty():
    """空消息列表返回空摘要与空 kept_ids。"""
    assert summarize([]) == ("", [])


def test_summarize_keeps_recent_and_summarizes_history():
    """最近 keep_recent 条原样保留（kept_ids），更早消息进摘要且不删除原记录。"""
    messages = [
        {"source_id": f"m{i}", "role": "user", "content": f"内容{i}"}
        for i in range(1, 9)
    ]
    summary, kept_ids = summarize(messages, keep_recent=6)
    assert kept_ids == ["m3", "m4", "m5", "m6", "m7", "m8"]
    assert "内容1" in summary and "内容2" in summary
    assert "内容3" not in summary  # 最近 6 条不进入摘要正文
    assert len(messages) == 8  # 不删除原始记录（CX-6/MEM-3）


def test_summarize_keep_recent_zero_summarizes_all():
    """keep_recent=0 时全部消息进入摘要，kept_ids 为空。"""
    messages = [
        {"source_id": f"m{i}", "role": "assistant", "content": f"内容{i}"}
        for i in range(1, 4)
    ]
    summary, kept_ids = summarize(messages, keep_recent=0)
    assert kept_ids == []
    assert "内容1" in summary and "内容3" in summary


def test_summarize_truncates_overlong_body_with_marker():
    """摘要正文超限截断并带 …[截断] 标记。"""
    messages = [
        {"source_id": "m1", "role": "user", "content": "长内容" * 50},
        {"source_id": "m2", "role": "user", "content": "最近"},
    ]
    summary, _ = summarize(messages, keep_recent=1, max_summary_chars=20)
    assert summary.endswith("…[截断]")
    assert len(summary) == 20 + len("…[截断]")


def test_summarize_falls_back_to_index_ids_when_source_missing():
    """缺 source_id 时 kept_ids 回落 idx:{index} 占位。"""
    summary, kept_ids = summarize([{"role": "user", "content": "x"}], keep_recent=1)
    assert kept_ids == ["idx:0"]
    assert summary  # 非空摘要（无历史时为占位文案）


def test_summarize_default_keep_recent_matches_constant():
    """默认保留条数与文档常量一致（防漂移）。"""
    messages = [
        {"source_id": f"m{i}", "role": "user", "content": f"内容{i}"}
        for i in range(1, DEFAULT_KEEP_RECENT + 3)
    ]
    _, kept_ids = summarize(messages)
    assert kept_ids == [f"m{i}" for i in range(3, DEFAULT_KEEP_RECENT + 3)]
