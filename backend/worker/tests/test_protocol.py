"""Worker 三协议调用器的协议地址规范化回归测试。"""

import pytest

from app import protocol


@pytest.mark.parametrize(
    "protocol_name,payload,endpoint",
    [
        ("openai_chat", {"choices": [{"message": {"content": "ok"}}]}, "/v1/chat/completions"),
        (
            "openai_responses",
            {"output": [{"content": [{"type": "output_text", "text": "ok"}]}]},
            "/v1/responses",
        ),
        (
            "anthropic_messages",
            {"content": [{"type": "text", "text": "ok"}]},
            "/v1/messages",
        ),
    ],
)
@pytest.mark.parametrize("suffix", ["/v1", "/v1/"])
def test_worker_protocol_url_accepts_optional_v1_suffix(monkeypatch, protocol_name, payload, endpoint, suffix):
    """真实评测调用与 API 侧一致，不会将 ``/v1`` 重复拼接。"""
    seen: dict[str, str] = {}

    def fake_post(url, body, headers, timeout_s):
        seen["url"] = url
        return payload

    monkeypatch.setattr(protocol, "_post_json", fake_post)
    protocol.call_protocol(
        protocol=protocol_name,
        base_url=f"https://upstream.example.com{suffix}",
        model="test-model",
        api_key="sk-test",
        messages=[{"role": "user", "content": "ping"}],
    )

    assert seen["url"] == f"https://upstream.example.com{endpoint}"
