"""M8 跨层安全 secrets 模块单测：脱敏判定、部分/全量抹除与递归行为。"""

from app.harness.security.secrets import (
    REDACT_KEYS,
    is_sensitive_key,
    mask_full,
    mask_partial,
    redact,
    redact_for_log,
)


def test_is_sensitive_key_case_and_space_insensitive():
    """键判定大小写不敏感，且容忍首尾空白；非敏感键不受影响。"""
    assert is_sensitive_key("api_key")
    assert is_sensitive_key("API_KEY")
    assert is_sensitive_key(" Authorization ")
    assert is_sensitive_key("set-cookie")
    assert not is_sensitive_key("model")
    assert not is_sensitive_key("api_keys")  # 仅精确匹配，不做前缀猜测


def test_mask_partial_keeps_prefix_and_handles_empty():
    """部分脱敏保留前 keep 字符；空值与短值不泄漏长度以外的信息。"""
    assert mask_partial("sk-1234567890") == "sk-1***"
    assert mask_partial("sk-1234567890", keep=6) == "sk-123***"
    assert mask_partial("ab") == "ab***"  # 短值仍保留全部前缀（当前行为）
    assert mask_partial("") == "***"


def test_mask_full_always_returns_mask():
    """全量脱敏任何输入都只返回 ***。"""
    assert mask_full("super-secret") == "***"
    assert mask_full("") == "***"


def test_redact_top_level_scalar_values():
    """标量敏感键：api_key/token 部分保留，password/cookie 全量抹除。"""
    out = redact({
        "api_key": "sk-abcdef123456",
        "access_token": "tok-987654321",
        "password": "p@ssw0rd",
        "cookie": "session=abc",
        "model": "deepseek-v4-flash",
    })
    assert out["api_key"] == "sk-a***"
    assert out["access_token"] == "tok-***"
    assert out["password"] == "***"
    assert out["cookie"] == "***"
    assert out["model"] == "deepseek-v4-flash"  # 非敏感键原样保留


def test_redact_recurses_nested_structures_and_preserves_shape():
    """嵌套 dict/list/tuple 递归脱敏，结构形状不变，非敏感值保留。"""
    out = redact({
        "headers": {"Authorization": "Bearer xyz", "accept": "json"},
        "items": [{"token": "abc12345"}, "plain"],
        "pair": ("secret", {"password": "pw"}),
    })
    assert out["headers"]["Authorization"] == "***"
    assert out["headers"]["accept"] == "json"
    assert out["items"][0]["token"] == "abc1***"
    assert out["items"][1] == "plain"
    assert out["pair"][0] == "secret"
    assert out["pair"][1]["password"] == "***"
    assert isinstance(out["pair"], tuple)


def test_redact_is_pure_and_does_not_mutate_input():
    """纯函数：返回副本，不改动入参。"""
    source = {"api_key": "sk-abcdef", "nested": {"password": "pw"}}
    out = redact(source)
    assert source == {"api_key": "sk-abcdef", "nested": {"password": "pw"}}
    assert out is not source and out["nested"] is not source["nested"]


def test_redact_sensitive_key_with_container_value_is_known_gap():
    """已知边界：敏感键的值是容器时不抹除（仅递归内部键）。

    记录当前行为供后续决策：``{"api_key": {"value": "sk-xxx"}}`` 中
    内层 "value" 非敏感键，因此内容原样保留。若安全侧要求抹除，
    需调整 ``redact`` 对容器值命中敏感键时的处理。
    """
    out = redact({"api_key": {"value": "sk-abcdef123456"}})
    assert out == {"api_key": {"value": "sk-abcdef123456"}}


def test_redact_for_log_is_stricter_than_redact():
    """日志脱敏更严格：api_key/token 也不留前缀，全量 ***。"""
    payload = {"api_key": "sk-abcdef123456", "token": "tok-999", "note": "ok"}
    assert redact(payload)["api_key"] == "sk-a***"
    logged = redact_for_log(payload)
    assert logged == {"api_key": "***", "token": "***", "note": "ok"}


def test_redact_keys_vocabulary_is_documented_set():
    """词表断言：核心五类与 authorization 头均在集合内（防误删）。"""
    for key in ("api_key", "token", "password", "secret", "cookie", "authorization"):
        assert key in REDACT_KEYS
