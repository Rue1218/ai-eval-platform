"""M8 跨层安全单测（X-A3 递归脱敏）；纯函数，不依赖 DB。"""

import json

from app.harness.security import (
    is_sensitive_key,
    mask_full,
    mask_partial,
    redact,
    redact_for_log,
)


def test_recursive_redact_nested_dict_list() -> None:
    """X-A3：递归脱敏覆盖嵌套 dict/list/tuple。"""
    payload = {
        "ok": True,
        "headers": {"authorization": "Bearer sk-123"},
        "config": {"api_key": "sk-secret", "model": "gpt-4o"},
        "logs": [{"token": "token-abc123", "text": "正常"}],
        "nested": {"deep": {"password": "p@ss"}},
        "user_input": "我的密码是 abc",
    }
    safe = redact(payload)
    assert "sk-secret" not in json.dumps(safe)
    assert "sk-123" not in json.dumps(safe)
    assert "token-abc123" not in json.dumps(safe)
    assert safe["logs"][0]["token"] == "toke***"
    assert "p@ss" not in json.dumps(safe)
    assert safe["headers"]["authorization"] == "***"
    assert safe["config"]["api_key"] == "sk-s***"
    assert safe["config"]["model"] == "gpt-4o"
    assert safe["logs"][0]["text"] == "正常"
    assert safe["nested"]["deep"]["password"] == "***"


def test_redact_is_pure_function() -> None:
    """脱敏为纯函数：不修改原始对象。"""
    payload = {"config": {"api_key": "sk-1"}}
    redact(payload)
    assert payload["config"]["api_key"] == "sk-1"


def test_mask_partial_keeps_prefix() -> None:
    """部分保留脱敏保留前 4 字符。"""
    assert mask_partial("sk-123456") == "sk-1***"
    assert mask_full("anything") == "***"


def test_is_sensitive_key_case_insensitive() -> None:
    """敏感键判定大小写不敏感。"""
    assert is_sensitive_key("API_KEY") is True
    assert is_sensitive_key("Password") is True
    assert is_sensitive_key("model") is False


def test_redact_for_log_masks_all() -> None:
    """日志专用脱敏更严格：疑似密钥全量 '***'。"""
    safe = redact_for_log({"api_key": "sk-123"})
    assert safe == {"api_key": "***"}


def test_redact_keeps_non_sensitive_values() -> None:
    """非敏感键原样保留，正文不被误伤。"""
    payload = {"text": "我的密码是 abc", "query": "如何评测"}
    safe = redact(payload)
    assert safe["text"] == "我的密码是 abc"
    assert safe["query"] == "如何评测"
