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


def test_removed_responses_protocol_is_rejected_before_network_call():
    """已删除协议必须在触网前按统一 VALIDATION 契约拒绝。"""
    with pytest.raises(AppError) as caught:
        call_protocol(
            protocol="openai_responses",
            base_url="https://unit.invalid/v1",
            model="unit-model",
            api_key="unit-key",
            messages=[{"role": "user", "content": "ping"}],
        )

    assert caught.value.code == ErrorCode.VALIDATION
