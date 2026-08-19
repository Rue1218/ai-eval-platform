"""三协议适配器夹具单测（后端开发计划 M1 W3）。

覆盖每种协议的「成功 + 4xx」夹具，并验证 TIMEOUT / UPSTREAM 可区分、
usage 归一、鉴权头组装与 API Key 不泄漏。HTTP 层通过 monkeypatch
替换 ``adapters._post_json`` 注入夹具，不依赖真实上游与数据库。
"""

import json
from urllib.error import HTTPError

import pytest

from app import adapters
from app.adapters import call_protocol, stream_protocol
from app.errors import AppError, ErrorCode

API_KEY = "sk-secret-key-123"
BASE = "https://upstream.example.com"

# 三协议成功响应夹具
OPENAI_CHAT_OK = {
    "choices": [{"message": {"role": "assistant", "content": "你好"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}
OPENAI_RESPONSES_OK = {
    "output": [
        {"content": [{"type": "output_text", "text": "答案"}, {"type": "reasoning", "text": "略"}]},
    ],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
}
ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "回复"}, {"type": "tool_use", "id": "x"}],
    "usage": {"input_tokens": 8, "output_tokens": 4},
}

# 协议 -> (成功夹具, 期望提取文本, 期望归一 usage)
SUCCESS_CASES = [
    ("openai_chat", OPENAI_CHAT_OK, "你好", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    (
        "openai_responses",
        OPENAI_RESPONSES_OK,
        "答案",
        {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    ),
    (
        "anthropic_messages",
        ANTHROPIC_OK,
        "回复",
        {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    ),
]


def _capture(monkeypatch, payload=None, *, error: Exception | None = None) -> dict:
    """替换 HTTP 层为夹具：记录请求并返回固定 payload 或抛出固定异常。"""
    seen: dict = {}

    def fake_post(url, body, headers, timeout_s):
        seen["url"], seen["body"], seen["headers"], seen["timeout_s"] = url, body, headers, timeout_s
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(adapters, "_post_json", fake_post)
    return seen


def _kwargs(protocol: str) -> dict:
    """三协议统一的公共调用参数。"""
    return {
        "protocol": protocol,
        "base_url": BASE,
        "model": "test-model",
        "api_key": API_KEY,
        "messages": [{"role": "user", "content": "ping"}],
        "system": "你是裁判",
        "max_tokens": 16,
    }


@pytest.mark.parametrize("protocol,payload,want_text,want_usage", SUCCESS_CASES)
def test_protocol_success_fixture(monkeypatch, protocol, payload, want_text, want_usage):
    """成功夹具：文本提取、usage 归一、原始响应与延迟均符合统一契约。"""
    seen = _capture(monkeypatch, payload)
    result = call_protocol(**_kwargs(protocol))

    assert result.text == want_text
    assert result.usage == want_usage
    assert result.raw == payload
    assert result.latency_ms >= 0
    # 端点与超时按协议正确组装
    assert seen["timeout_s"] == adapters.DEFAULT_TIMEOUT_S
    assert API_KEY not in seen["url"]


def test_openai_chat_request_shape(monkeypatch):
    """openai_chat：system 进入 messages、Bearer 鉴权头、采样参数入 body。"""
    seen = _capture(monkeypatch, OPENAI_CHAT_OK)
    call_protocol(**_kwargs("openai_chat"), temperature=0.3)

    assert seen["url"] == f"{BASE}/v1/chat/completions"
    assert seen["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "你是裁判"}
    assert seen["body"]["messages"][1] == {"role": "user", "content": "ping"}
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["max_tokens"] == 16


def test_openai_responses_request_shape(monkeypatch):
    """openai_responses：system 走 instructions、input 承载 messages、Bearer 鉴权。"""
    seen = _capture(monkeypatch, OPENAI_RESPONSES_OK)
    call_protocol(**_kwargs("openai_responses"))

    assert seen["url"] == f"{BASE}/v1/responses"
    assert seen["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert seen["body"]["instructions"] == "你是裁判"
    assert seen["body"]["input"] == [{"role": "user", "content": "ping"}]
    assert seen["body"]["max_output_tokens"] == 16


def test_anthropic_request_shape(monkeypatch):
    """anthropic_messages：system 独立字段、x-api-key + anthropic-version 鉴权头。"""
    seen = _capture(monkeypatch, ANTHROPIC_OK)
    call_protocol(**_kwargs("anthropic_messages"), anthropic_version="2023-06-01")

    assert seen["url"] == f"{BASE}/v1/messages"
    assert seen["headers"]["x-api-key"] == API_KEY
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["headers"].get("Authorization") is None
    assert seen["body"]["system"] == "你是裁判"
    assert seen["body"]["messages"] == [{"role": "user", "content": "ping"}]
    assert seen["body"]["max_tokens"] == 16


@pytest.mark.parametrize(
    "protocol,payload,endpoint",
    [
        ("openai_chat", OPENAI_CHAT_OK, "/v1/chat/completions"),
        ("openai_responses", OPENAI_RESPONSES_OK, "/v1/responses"),
        ("anthropic_messages", ANTHROPIC_OK, "/v1/messages"),
    ],
)
@pytest.mark.parametrize("suffix", ["/v1", "/v1/"])
def test_protocol_url_accepts_optional_v1_suffix(monkeypatch, protocol, payload, endpoint, suffix):
    """三协议均接受带 ``/v1`` 的协议档地址，且请求端点不会重复版本段。"""
    seen = _capture(monkeypatch, payload)
    call_protocol(**(_kwargs(protocol) | {"base_url": f"{BASE}{suffix}"}))

    assert seen["url"] == f"{BASE}{endpoint}"


@pytest.mark.parametrize("protocol", [case[0] for case in SUCCESS_CASES])
def test_protocol_4xx_maps_to_upstream(monkeypatch, protocol):
    """4xx 夹具：统一归一为 UPSTREAM，消息仅含状态码且不泄漏 Key。"""
    _capture(monkeypatch, error=HTTPError("https://upstream", 401, "Unauthorized", None, None))
    with pytest.raises(AppError) as exc:
        call_protocol(**_kwargs(protocol))

    assert exc.value.code == ErrorCode.UPSTREAM
    assert "401" in exc.value.message
    assert API_KEY not in exc.value.message


@pytest.mark.parametrize("protocol", [case[0] for case in SUCCESS_CASES])
def test_protocol_timeout_maps_to_timeout(monkeypatch, protocol):
    """超时夹具：统一归一为 TIMEOUT，与 UPSTREAM 可区分。"""
    _capture(monkeypatch, error=TimeoutError("timed out"))
    with pytest.raises(AppError) as exc:
        call_protocol(**_kwargs(protocol))

    assert exc.value.code == ErrorCode.TIMEOUT


def test_malformed_response_maps_to_upstream(monkeypatch):
    """结构异常夹具：上游 200 但缺少协议字段时归一为 UPSTREAM。"""
    _capture(monkeypatch, {"unexpected": True})
    with pytest.raises(AppError) as exc:
        call_protocol(**_kwargs("openai_chat"))

    assert exc.value.code == ErrorCode.UPSTREAM
    assert "结构" in exc.value.message


def test_unsupported_protocol_rejected():
    """非契约协议在发请求前即拒绝，归一为 VALIDATION。"""
    with pytest.raises(AppError) as exc:
        call_protocol(**_kwargs("grpc"))

    assert exc.value.code == ErrorCode.VALIDATION


def test_missing_usage_counts_as_zero(monkeypatch):
    """上游缺失 usage 字段时按 0 计，不抛异常。"""
    _capture(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    result = call_protocol(**_kwargs("openai_chat"))

    assert result.usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# stream_protocol：三协议 SSE 流式解析夹具
# ---------------------------------------------------------------------------


class _FakeSSE:
    """把 SSE 文本行包装成可迭代的假响应对象（urlopen 返回值替身）。"""

    def __init__(self, lines: list[str]):
        self._lines = [f"{ln}\n".encode() for ln in lines]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._lines)


def _capture_stream(monkeypatch, lines: list[str]) -> dict:
    """替换 urlopen 为 SSE 夹具：记录请求并返回固定行序列。"""
    seen: dict = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        return _FakeSSE(lines)

    monkeypatch.setattr(adapters, "urlopen", fake_urlopen)
    return seen


def test_stream_openai_chat_chunks(monkeypatch):
    """openai_chat 流式：跳过 role 首帧与 [DONE]，仅 yield content 增量。"""
    seen = _capture_stream(
        monkeypatch,
        [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            '',
            'data: {"choices":[{"delta":{"content":"你"}}]}',
            'data: {"choices":[{"delta":{"content":"好"}}]}',
            'data: [DONE]',
        ],
    )
    chunks = list(stream_protocol(**_kwargs("openai_chat")))

    assert chunks == [("content", "你"), ("content", "好")]
    assert seen["body"]["stream"] is True
    assert seen["headers"]["authorization"] == f"Bearer {API_KEY}"


def test_stream_openai_chat_reasoning_chunks(monkeypatch):
    """openai_chat 思考模型流式：reasoning_content 增量归类为 reasoning。"""
    _capture_stream(
        monkeypatch,
        [
            'data: {"choices":[{"delta":{"reasoning_content":"思考第一段"}}]}',
            'data: {"choices":[{"delta":{"reasoning_content":"第二段"}}]}',
            'data: {"choices":[{"delta":{"content":"正文"}}]}',
            'data: [DONE]',
        ],
    )
    chunks = list(stream_protocol(**_kwargs("openai_chat")))

    assert chunks == [("reasoning", "思考第一段"), ("reasoning", "第二段"), ("content", "正文")]


def test_stream_mimo_disables_thinking(monkeypatch):
    """mimo 网关：流式请求同样显式关闭思考（对齐 call_protocol 提速策略）。"""
    seen = _capture_stream(monkeypatch, ['data: {"choices":[{"delta":{"content":"ok"}}]}'])
    kwargs = _kwargs("openai_chat") | {"base_url": "https://xiaomimimo.example.com"}
    list(stream_protocol(**kwargs))

    assert seen["body"].get("thinking") == {"type": "disabled"}


def test_stream_non_sse_fallback(monkeypatch):
    """网关忽略 stream 参数返回完整 JSON：兜底解析全文作为单块 content。"""
    _capture_stream(
        monkeypatch,
        [
            '{"choices": [{"message": {"role": "assistant", "content": "完整回复"}}],',
            ' "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}',
        ],
    )
    chunks = list(stream_protocol(**_kwargs("openai_chat")))

    assert chunks == [("content", "完整回复")]


def test_stream_openai_responses_chunks(monkeypatch):
    """openai_responses 流式：仅 output_text.delta 事件携带可见增量。"""
    _capture_stream(
        monkeypatch,
        [
            'data: {"type":"response.created"}',
            'data: {"type":"response.reasoning_summary_text.delta","delta":"先想想"}',
            'data: {"type":"response.output_text.delta","delta":"评"}',
            'data: {"type":"response.output_text.delta","delta":"测"}',
            'data: {"type":"response.completed","response":{}}',
        ],
    )
    chunks = list(stream_protocol(**_kwargs("openai_responses")))

    assert chunks == [("reasoning", "先想想"), ("content", "评"), ("content", "测")]


def test_stream_anthropic_chunks(monkeypatch):
    """anthropic_messages 流式：thinking_delta 与 text_delta 正确分类。"""
    _capture_stream(
        monkeypatch,
        [
            'data: {"type":"message_start","message":{}}',
            'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"先推理"}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"基"}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"准"}}',
            'data: {"type":"content_block_stop"}',
            'data: {"type":"message_stop"}',
        ],
    )
    chunks = list(stream_protocol(**_kwargs("anthropic_messages")))

    assert chunks == [("reasoning", "先推理"), ("content", "基"), ("content", "准")]


def test_stream_tolerates_bad_frames(monkeypatch):
    """坏帧（非 JSON / 非 data 行 / 空 data）不中断整条流。"""
    _capture_stream(
        monkeypatch,
        [
            'event: message',
            'data: not-json',
            'data: ',
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
        ],
    )
    assert list(stream_protocol(**_kwargs("openai_chat"))) == [("content", "ok")]


def test_stream_4xx_maps_to_upstream(monkeypatch):
    """建连即 4xx：归一为 UPSTREAM，消息仅含状态码。"""
    monkeypatch.setattr(
        adapters,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            HTTPError("https://upstream", 429, "Too Many Requests", None, None)
        ),
    )
    with pytest.raises(AppError) as exc:
        list(stream_protocol(**_kwargs("openai_chat")))

    assert exc.value.code == ErrorCode.UPSTREAM
    assert "429" in exc.value.message


def test_stream_unsupported_protocol_rejected():
    """非契约协议在发请求前即拒绝。"""
    with pytest.raises(AppError) as exc:
        list(stream_protocol(**_kwargs("grpc")))

    assert exc.value.code == ErrorCode.VALIDATION
