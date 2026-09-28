"""两类遗留协议适配器的请求形状与拒绝边界回归测试。"""

from types import SimpleNamespace

import pytest

from app import adapters
from app.adapters import call_protocol
from app.errors import AppError, ErrorCode


class _Response:
    """提供 SDK 响应对象的最小 ``model_dump`` 接口。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self, **_kwargs) -> dict:
        """返回测试预置的上游 JSON。"""
        return self._payload


@pytest.mark.parametrize(
    "protocol,payload,want_text",
    [
        ("openai_chat", {"choices": [{"message": {"content": "chat"}}]}, "chat"),
        ("anthropic_messages", {"content": [{"type": "text", "text": "anthropic"}]}, "anthropic"),
    ],
)
def test_remaining_protocols_call_their_native_adapters(monkeypatch, protocol, payload, want_text):
    """OpenAI Chat 与 Anthropic Messages 都生成各自原生请求，并可解析文本。"""
    seen: dict[str, object] = {}

    def create_chat(**body):
        """记录 Chat 请求。"""
        seen["body"] = body
        return _Response(payload)

    def create_messages(**body):
        """记录 Messages 请求。"""
        seen["body"] = body
        return _Response(payload)

    monkeypatch.setattr(
        adapters,
        "_openai_client",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create_chat)), close=lambda: None
        ),
    )
    monkeypatch.setattr(
        adapters,
        "_anthropic_client",
        lambda **kwargs: SimpleNamespace(
            messages=SimpleNamespace(create=create_messages), close=lambda: None
        ),
    )

    result = call_protocol(
        protocol=protocol,
        base_url="https://unit.invalid/v1",
        model="unit-model",
        api_key="unit-key",
        messages=[{"role": "user", "content": "ping"}],
        reasoning_enabled=False,
    )

    assert result.text == want_text
    assert "model" in seen["body"]
    if protocol == "openai_chat":
        assert seen["body"]["messages"] == [{"role": "user", "content": "ping"}]
    else:
        assert seen["body"]["messages"] == [{"role": "user", "content": "ping"}]


def test_unknown_protocol_is_rejected_before_network_call():
    """未知协议必须在触网前按统一 VALIDATION 契约拒绝。"""
    with pytest.raises(AppError) as caught:
        call_protocol(
            protocol="unknown_protocol",
            base_url="https://unit.invalid/v1",
            model="unit-model",
            api_key="unit-key",
            messages=[{"role": "user", "content": "ping"}],
        )

    assert caught.value.code == ErrorCode.VALIDATION


@pytest.mark.parametrize("kind", ["openai_chat", "anthropic_messages"])
def test_deepseek_case_generation_disables_default_thinking(monkeypatch, kind):
    """页面生成经 SDK 发送真实关闭参数，默认思考不能吃掉正文预算。"""
    def create(**body):
        thinking = body.get("extra_body", {}).get("thinking") if kind == "openai_chat" else body.get("thinking")
        assert thinking == {"type": "disabled"}
        return _Response({"choices": [{"message": {"content": "ok"}}],
                          "content": [{"type": "text", "text": "ok"}]})

    monkeypatch.setattr(adapters, "_openai_client", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None))
    monkeypatch.setattr(adapters, "_anthropic_client", lambda **kwargs: SimpleNamespace(
        messages=SimpleNamespace(create=create), close=lambda: None))
    result = call_protocol(protocol=kind, base_url="https://unit.invalid", model="deepseek-flash",
                           api_key="unit", messages=[], reasoning_enabled=False)
    assert result.text == "ok"


def test_deepseek_explicit_thinking_is_preserved():
    """显式开启思考的对话请求仍遵循调用方选择。"""
    body = {}
    adapters._apply_compatible_thinking(body, "https://unit.invalid", "deepseek-flash", True, "high")
    assert body["thinking"] == {"type": "enabled"}


def test_deepseek_responses_generation_disables_thinking():
    """Responses 生成使用原生 none 参数，未知型号不发送该参数。"""
    from app.responses_adapter import _body

    args = dict(messages=[], system="", temperature=0.2, max_tokens=8192,
                reasoning_enabled=False, reasoning_effort="high", tools=None)
    assert _body(model="deepseek-flash", **args)["reasoning"] == {"effort": "none"}
    assert "reasoning" not in _body(model="unit", **args)
