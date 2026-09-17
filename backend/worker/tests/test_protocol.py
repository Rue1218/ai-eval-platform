"""Worker 两类协议调用器的协议地址规范化回归测试。"""

import pytest

from app import protocol


def test_responses_worker_wire_usage_and_failure(monkeypatch):
    """评测发送 Responses 字段，记录真实用量，拒绝 HTTP 200 的截断输出。"""
    captured = []
    payload = {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "完成"}]}],
        "usage": {"input_tokens": 12, "output_tokens": 8,
                  "output_tokens_details": {"reasoning_tokens": 3}}}

    def post(url, body, headers, timeout_s):
        """替换外部网络，保留协议请求和响应解析。"""
        captured.append((url, body, headers))
        return payload

    monkeypatch.setattr(protocol, "_post_json", post)
    args = dict(protocol="openai_responses", base_url="https://unit.invalid/v1/responses",
                model="gpt-5.4", api_key="unit", system="简短回答", messages=[{"role": "user", "content": "问"}])
    result = protocol.call_protocol(**args)
    assert result.text == "完成" and result.usage["total_tokens"] == 20
    assert result.usage["reasoning_tokens"] == 3
    url, body, headers = captured[0]
    assert url == args["base_url"]
    assert body["input"] == args["messages"] and body["instructions"] == args["system"]
    assert body["max_output_tokens"] == 1024 and body["store"] is False
    assert "temperature" not in body and "messages" not in body
    assert headers["Authorization"] == "Bearer unit"
    payload["status"] = "incomplete"
    with pytest.raises(protocol.ProtocolCallError, match="UPSTREAM"):
        protocol.call_protocol(**args)


@pytest.mark.parametrize("kind", ["openai_chat", "anthropic_messages"])
def test_full_endpoint_is_used_unchanged(monkeypatch, kind):
    """Worker 完整 URL 与 API 行为一致，不追加资源后缀。"""
    from app import protocol

    captured = []

    def post(url, body, headers, timeout_s):
        """记录最终 URL，使用固定协议响应。"""
        captured.append(url)
        return {"choices": [{"message": {"content": "ok"}}],
                "content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(protocol, "_post_json", post)
    url = "https://unit.invalid/run/?region=cn"
    protocol.call_protocol(protocol=kind, base_url=url, full_url=True,
                           model="unit", api_key="unit", messages=[])
    assert captured == [url]


@pytest.mark.parametrize(
    "protocol_name,payload,endpoint",
    [
        ("openai_chat", {"choices": [{"message": {"content": "ok"}}]}, "/v1/chat/completions"),
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


def test_worker_protocol_disables_thinking_on_aliyun_maas(monkeypatch):
    """阿里云 MaaS 网关的推理模型默认输出 thinking 块，小预算下正文为空；
    与 xiaomimimo 一致，显式关闭思考保证评测与裁判能拿到 text 正文。"""
    seen: dict = {}

    def fake_post(url, body, headers, timeout_s):
        seen["body"] = body
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(protocol, "_post_json", fake_post)
    protocol.call_protocol(
        protocol="anthropic_messages",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic",
        model="glm-5.2",
        api_key="sk-test",
        messages=[{"role": "user", "content": "ping"}],
    )
    assert seen["body"]["thinking"] == {"type": "disabled"}
