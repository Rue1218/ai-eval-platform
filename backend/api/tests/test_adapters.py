"""三协议适配器夹具单测（后端开发计划 M1 W3）。

覆盖每种协议的「成功 + 4xx」夹具，并验证 TIMEOUT / UPSTREAM 可区分、
usage 归一、SDK 客户端参数与 API Key 不泄漏。非流式调用通过替换 SDK
客户端工厂注入夹具，不依赖真实上游与数据库。
"""

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from app import adapters
from app.adapters import AdapterStreamEvent, call_protocol, stream_protocol
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

# 真实 SDK 的 Pydantic 反序列化要求完整的协议必要字段；这些夹具只用于
# MockTransport 级测试，不会向外发起网络请求。
SDK_OPENAI_CHAT_OK = {
    "id": "chatcmpl_test",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok", "refusal": None},
            "finish_reason": "stop",
            "logprobs": None,
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
}
SDK_OPENAI_RESPONSES_OK = {
    "id": "resp_test",
    "object": "response",
    "created_at": 0,
    "status": "completed",
    "model": "test-model",
    "output": [
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
        }
    ],
    "parallel_tool_calls": True,
    "tools": [],
    "error": None,
    "incomplete_details": None,
    "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
}
SDK_ANTHROPIC_OK = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "test-model",
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 2},
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


class _FakeSdkResponse:
    """提供 SDK Pydantic 响应所需的最小 model_dump 接口。"""

    def __init__(self, payload: object):
        self._payload = payload

    def model_dump(self, *, mode: str) -> object:
        """按 SDK 的 JSON 序列化入口返回测试夹具。"""
        assert mode == "json"
        return self._payload


class _FakeSdkClient:
    """同时覆盖三种资源入口的 SDK 客户端替身。"""

    def __init__(self, seen: dict, payload: object, error: Exception | None):
        self._seen = seen
        self._payload = payload
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))
        self.responses = SimpleNamespace(create=self._create_responses)
        self.messages = SimpleNamespace(create=self._create_messages)

    def _create_chat(self, **kwargs):
        """记录 Chat Completions SDK 参数。"""
        return self._record("openai_chat", kwargs)

    def _create_responses(self, **kwargs):
        """记录 Responses SDK 参数。"""
        return self._record("openai_responses", kwargs)

    def _create_messages(self, **kwargs):
        """记录 Anthropic Messages SDK 参数。"""
        return self._record("anthropic_messages", kwargs)

    def _record(self, operation: str, kwargs: dict) -> _FakeSdkResponse:
        """保存调用参数后按夹具返回响应或抛出预期异常。"""
        self._seen["operation"] = operation
        self._seen["body"] = dict(kwargs)
        if self._error is not None:
            raise self._error
        return _FakeSdkResponse(self._payload)

    def close(self) -> None:
        """模拟 SDK 资源释放，供适配器 finally 调用。"""
        self._seen["closed"] = True


def _capture(monkeypatch, payload=None, *, error: Exception | None = None) -> dict:
    """替换 SDK 客户端工厂：记录参数并返回固定响应或异常。"""
    seen: dict = {}
    client = _FakeSdkClient(seen, payload, error)

    def fake_openai_client(**kwargs):
        seen["client"] = dict(kwargs)
        return client

    def fake_anthropic_client(**kwargs):
        seen["client"] = dict(kwargs)
        return client

    monkeypatch.setattr(adapters, "_openai_client", fake_openai_client)
    monkeypatch.setattr(adapters, "_anthropic_client", fake_anthropic_client)
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


def test_sdk_clients_use_normalized_base_url_and_disable_retries():
    """SDK 客户端必须保留 /v1 规则，并避免隐式重试改变模型调用次数。"""
    openai_client = adapters._openai_client(
        base_url=BASE,
        api_key=API_KEY,
        timeout_s=12.0,
    )
    anthropic_client = adapters._anthropic_client(
        base_url=BASE,
        api_key=API_KEY,
        timeout_s=12.0,
    )
    try:
        assert str(openai_client.base_url) == f"{BASE}/v1/"
        assert openai_client.max_retries == 0
        assert str(anthropic_client.base_url) == BASE
        assert anthropic_client.max_retries == 0
    finally:
        openai_client.close()
        anthropic_client.close()


@pytest.mark.parametrize(
    "protocol,payload,path",
    [
        ("openai_chat", SDK_OPENAI_CHAT_OK, "/v1/chat/completions"),
        ("openai_responses", SDK_OPENAI_RESPONSES_OK, "/v1/responses"),
        ("anthropic_messages", SDK_ANTHROPIC_OK, "/v1/messages"),
    ],
)
def test_nonstream_sdk_wire_contract(monkeypatch, protocol, payload, path):
    """真实 SDK 经 MockTransport 发送正确路径、鉴权和请求体，不依赖外网。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """记录 SDK 的实际 HTTP 请求并回送完整协议响应。"""
        seen.append(request)
        return httpx.Response(200, request=request, json=payload)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    if protocol == "anthropic_messages":
        client = adapters.Anthropic(
            api_key=API_KEY,
            base_url=BASE,
            max_retries=0,
            http_client=http_client,
        )
        monkeypatch.setattr(adapters, "_anthropic_client", lambda **_kwargs: client)
    else:
        client = adapters.OpenAI(
            api_key=API_KEY,
            base_url=f"{BASE}/v1",
            max_retries=0,
            http_client=http_client,
        )
        monkeypatch.setattr(adapters, "_openai_client", lambda **_kwargs: client)

    try:
        result = call_protocol(**_kwargs(protocol))
        request = seen[0]
        assert request.url.path == path
        assert json.loads(request.content)["model"] == "test-model"
        if protocol == "anthropic_messages":
            assert request.headers["x-api-key"] == API_KEY
            assert request.headers["anthropic-version"] == "2023-06-01"
        else:
            assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert result.text == "ok"
    finally:
        # call_protocol 已关闭 SDK 客户端；单独 close 传输保证异常分支也释放资源。
        http_client.close()


def test_anthropic_deepseek_subpath_wire_contract(monkeypatch):
    """DeepSeek 官方 Anthropic 端点（…/anthropic）须原样透传并 POST /anthropic/v1/messages。"""
    seen_requests: list[httpx.Request] = []
    seen_client_kwargs: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, request=request, json=SDK_ANTHROPIC_OK)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = adapters.Anthropic(
        api_key=API_KEY,
        base_url="https://api.deepseek.com/anthropic",
        max_retries=0,
        http_client=http_client,
    )

    def fake_anthropic_client(**kwargs):
        seen_client_kwargs.update(kwargs)
        return client

    monkeypatch.setattr(adapters, "_anthropic_client", fake_anthropic_client)
    try:
        kwargs = _kwargs("anthropic_messages")
        kwargs["base_url"] = "https://api.deepseek.com/anthropic"
        result = call_protocol(**kwargs)
        # 服务根地址不得被子路径剥离逻辑改写；真实请求落在官方端点上
        assert seen_client_kwargs["base_url"] == "https://api.deepseek.com/anthropic"
        assert seen_requests[0].url.path == "/anthropic/v1/messages"
        assert seen_requests[0].headers["x-api-key"] == API_KEY
        assert result.text == "ok"
    finally:
        http_client.close()


@pytest.mark.parametrize("protocol,payload,want_text,want_usage", SUCCESS_CASES)
def test_protocol_success_fixture(monkeypatch, protocol, payload, want_text, want_usage):
    """成功夹具：文本提取、usage 归一、原始响应与延迟均符合统一契约。"""
    seen = _capture(monkeypatch, payload)
    result = call_protocol(**_kwargs(protocol))

    assert result.text == want_text
    assert result.usage == want_usage
    assert result.raw == payload
    assert result.latency_ms >= 0
    # SDK 工厂接收规范化地址与超时，API Key 不得混入地址。
    assert seen["client"]["timeout_s"] == adapters.DEFAULT_TIMEOUT_S
    assert API_KEY not in seen["client"]["base_url"]
    assert seen["closed"] is True


def test_openai_chat_request_shape(monkeypatch):
    """openai_chat：system 进入 messages、Bearer 鉴权头、采样参数入 body。"""
    seen = _capture(monkeypatch, OPENAI_CHAT_OK)
    call_protocol(**_kwargs("openai_chat"), temperature=0.3)

    assert seen["client"] == {"base_url": BASE, "api_key": API_KEY, "timeout_s": adapters.DEFAULT_TIMEOUT_S}
    assert seen["operation"] == "openai_chat"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "你是裁判"}
    assert seen["body"]["messages"][1] == {"role": "user", "content": "ping"}
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["max_tokens"] == 16


def test_openai_responses_request_shape(monkeypatch):
    """openai_responses：system 走 instructions、input 承载 messages、Bearer 鉴权。"""
    seen = _capture(monkeypatch, OPENAI_RESPONSES_OK)
    call_protocol(**_kwargs("openai_responses"))

    assert seen["client"] == {"base_url": BASE, "api_key": API_KEY, "timeout_s": adapters.DEFAULT_TIMEOUT_S}
    assert seen["operation"] == "openai_responses"
    assert seen["body"]["instructions"] == "你是裁判"
    assert seen["body"]["input"] == [{"role": "user", "content": "ping"}]
    assert seen["body"]["max_output_tokens"] == 16


def test_openai_responses_reasoning_settings(monkeypatch):
    """Responses API 的思考强度与摘要开关映射到标准 reasoning 对象。"""
    seen = _capture(monkeypatch, OPENAI_RESPONSES_OK)
    call_protocol(
        **(_kwargs("openai_responses") | {"model": "gpt-5.2"}),
        reasoning_enabled=True,
        reasoning_effort="high",
    )

    assert seen["body"]["reasoning"] == {"effort": "high", "summary": "auto"}


def test_cursorapi_model_spec_keeps_request_fields_in_model_name(monkeypatch):
    """CursorAPI 参数在模型名中传递，不能再附加 OpenAI reasoning_effort。"""
    seen = _capture(monkeypatch, OPENAI_CHAT_OK)
    call_protocol(
        **(
            _kwargs("openai_chat")
            | {"model": "gpt-5.3-codex[reasoning=medium,fast=false]"}
        ),
        reasoning_enabled=True,
        reasoning_effort="high",
    )

    assert seen["body"]["model"] == "gpt-5.3-codex[reasoning=medium,fast=false]"
    assert "reasoning_effort" not in seen["body"]


def test_anthropic_request_shape(monkeypatch):
    """anthropic_messages：system 独立字段、x-api-key + anthropic-version 鉴权头。"""
    seen = _capture(monkeypatch, ANTHROPIC_OK)
    call_protocol(**_kwargs("anthropic_messages"), anthropic_version="2023-06-01")

    assert seen["client"] == {"base_url": BASE, "api_key": API_KEY, "timeout_s": adapters.DEFAULT_TIMEOUT_S}
    assert seen["operation"] == "anthropic_messages"
    assert seen["body"].pop("extra_headers") == {"anthropic-version": "2023-06-01"}
    assert seen["body"]["system"] == "你是裁判"
    assert seen["body"]["messages"] == [{"role": "user", "content": "ping"}]
    assert seen["body"]["max_tokens"] == 16


@pytest.mark.parametrize(
    "protocol,payload",
    [
        ("openai_chat", OPENAI_CHAT_OK),
        ("openai_responses", OPENAI_RESPONSES_OK),
        ("anthropic_messages", ANTHROPIC_OK),
    ],
)
@pytest.mark.parametrize("suffix", ["/v1", "/v1/"])
def test_protocol_url_accepts_optional_v1_suffix(monkeypatch, protocol, payload, suffix):
    """三协议均接受带 ``/v1`` 的协议档地址，传给 SDK 的服务根地址不重复版本段。"""
    seen = _capture(monkeypatch, payload)
    call_protocol(**(_kwargs(protocol) | {"base_url": f"{BASE}{suffix}"}))

    assert seen["client"]["base_url"] == BASE


@pytest.mark.parametrize("protocol", [case[0] for case in SUCCESS_CASES])
def test_protocol_4xx_maps_to_upstream(monkeypatch, protocol):
    """4xx 夹具：统一归一为 UPSTREAM，消息仅含状态码且不泄漏 Key。"""
    request = httpx.Request("POST", "https://upstream.example.com/v1/messages")
    response = httpx.Response(401, request=request)
    _capture(monkeypatch, error=openai.APIStatusError("Unauthorized", response=response, body=None))
    with pytest.raises(AppError) as exc:
        call_protocol(**_kwargs(protocol))

    assert exc.value.code == ErrorCode.UPSTREAM
    assert "401" in exc.value.message
    assert API_KEY not in exc.value.message


@pytest.mark.parametrize("protocol", [case[0] for case in SUCCESS_CASES])
def test_protocol_timeout_maps_to_timeout(monkeypatch, protocol):
    """超时夹具：统一归一为 TIMEOUT，与 UPSTREAM 可区分。"""
    _capture(monkeypatch, error=openai.APITimeoutError(httpx.Request("POST", "https://upstream.example.com")))
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


def test_openai_responses_usage_accepts_official_field_names(monkeypatch):
    """官方 Responses usage 的 input/output_tokens 也必须归一为平台字段。"""
    _capture(
        monkeypatch,
        {
            "output": [{"content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        },
    )

    result = call_protocol(**_kwargs("openai_responses"))

    assert result.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def test_usage_preserves_upstream_prompt_cache_counters(monkeypatch):
    """H0 缓存观测：仅透传上游已声明的读/创建 token，不凭空推断命中。"""
    _capture(
        monkeypatch,
        {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 5,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 12,
            },
        },
    )

    result = call_protocol(**_kwargs("anthropic_messages"))

    assert result.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 5,
        "total_tokens": 105,
        "cache_read_input_tokens": 80,
        "cache_creation_input_tokens": 12,
    }


@pytest.mark.parametrize(
    "protocol,payload,expected_tool",
    [
        (
            "openai_chat",
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "chat_read_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read",
                                        "arguments": '{"path":"a.txt"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "读取文件",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            },
        ),
        (
            "openai_responses",
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "responses_read_1",
                        "name": "read",
                        "arguments": '{"path":"a.txt"}',
                    }
                ]
            },
            {
                "type": "function",
                "name": "read",
                "description": "读取文件",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        ),
        (
            "anthropic_messages",
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "anthropic_read_1",
                        "name": "read",
                        "input": {"path": "a.txt"},
                    }
                ]
            },
            {
                "name": "read",
                "description": "读取文件",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        ),
    ],
)
def test_native_tool_call_roundtrip(monkeypatch, protocol, payload, expected_tool):
    """P2：三协议均能发送内部 schema 并回收原生 ToolCall。"""
    seen = _capture(monkeypatch, payload)
    result = call_protocol(
        **_kwargs(protocol),
        tools=[
            {
                "name": "read",
                "description": "读取文件",
                "parameters_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ],
    )

    assert seen["body"]["tools"] == [expected_tool]
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read"
    assert result.tool_calls[0].arguments == {"path": "a.txt"}
    assert result.tool_calls[0].call_id.endswith("read_1")


@pytest.mark.parametrize("protocol,payload,_want_text,_want_usage", SUCCESS_CASES)
def test_native_tool_result_messages_follow_protocol(monkeypatch, protocol, payload, _want_text, _want_usage):
    """P2：下一轮 assistant ToolCall 与 tool_result 必须保留同一 call_id。"""
    seen = _capture(monkeypatch, payload)
    call_protocol(
        **(_kwargs(protocol) | {
            "messages": [
                {
                    "role": "assistant",
                    "content": "我先读取文件。",
                    "tool_calls": [
                        {"call_id": "call_read_1", "name": "read", "arguments": {"path": "a.txt"}}
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_read_1",
                    "name": "read",
                    "content": "文件正文",
                },
            ]
        }),
    )

    if protocol == "openai_chat":
        messages = seen["body"]["messages"]
        assert messages[1]["tool_calls"][0]["id"] == "call_read_1"
        assert messages[2] == {"role": "tool", "tool_call_id": "call_read_1", "content": "文件正文"}
    elif protocol == "openai_responses":
        assert seen["body"]["input"] == [
            {"role": "assistant", "content": "我先读取文件。"},
            {"type": "function_call", "call_id": "call_read_1", "name": "read", "arguments": '{"path": "a.txt"}'},
            {"type": "function_call_output", "call_id": "call_read_1", "output": "文件正文"},
        ]
    else:
        messages = seen["body"]["messages"]
        assert messages[0]["content"][1]["id"] == "call_read_1"
        assert messages[1] == {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_read_1", "content": "文件正文"}],
        }


def test_anthropic_multiple_tool_results_share_one_user_message(monkeypatch):
    """同一 assistant 的多个 tool_use 必须由一条 user 消息中的多个结果响应。"""
    seen = _capture(monkeypatch, ANTHROPIC_OK)
    call_protocol(
        **(_kwargs("anthropic_messages") | {
            "messages": [
                {
                    "role": "assistant",
                    "content": "并行读取两个文件。",
                    "tool_calls": [
                        {"call_id": "call_a", "name": "read", "arguments": {"path": "a.txt"}},
                        {"call_id": "call_b", "name": "read", "arguments": {"path": "b.txt"}},
                    ],
                },
                {"role": "tool", "tool_call_id": "call_a", "name": "read", "content": "A"},
                {"role": "tool", "tool_call_id": "call_b", "name": "read", "content": "B"},
            ]
        }),
    )

    messages = seen["body"]["messages"]
    assert len(messages) == 2
    assert [block["id"] for block in messages[0]["content"][1:]] == ["call_a", "call_b"]
    assert messages[1] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_a", "content": "A"},
            {"type": "tool_result", "tool_use_id": "call_b", "content": "B"},
        ],
    }


# ---------------------------------------------------------------------------
# stream_protocol：三协议 SSE 流式解析夹具
# ---------------------------------------------------------------------------


class _FakeSdkStream:
    """模拟 SDK 已解帧的事件迭代器，适配器测试不再依赖底层 SSE 读取实现。"""

    def __init__(self, seen: dict, lines: list[str]):
        self._seen = seen
        self._events: list[object] = []
        for line in lines:
            # 兼容既有夹具书写形式；这一步只在测试夹具中把已知 SSE data 转为 SDK 事件。
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                self._events.append(data)
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self):
        """逐个返回带 model_dump 的 SDK 事件替身。"""
        if self._index >= len(self._events):
            raise StopIteration
        event = self._events[self._index]
        self._index += 1
        if isinstance(event, Exception):
            raise event
        return _FakeSdkResponse(event)

    def close(self) -> None:
        """记录适配器在流结束或取消时释放了 SDK Stream。"""
        self._seen["stream_closed"] = True


class _FakeSdkStreamClient:
    """提供三种 SDK 资源入口并记录流式 create 调用的客户端替身。"""

    def __init__(self, seen: dict, stream: _FakeSdkStream, error: Exception | None = None):
        self._seen = seen
        self._stream = stream
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))
        self.responses = SimpleNamespace(create=self._create_responses)
        self.messages = SimpleNamespace(create=self._create_messages)

    def _create_chat(self, **kwargs):
        """记录 Chat Completions 的流式 SDK 参数。"""
        return self._record("openai_chat", kwargs)

    def _create_responses(self, **kwargs):
        """记录 Responses 的流式 SDK 参数。"""
        return self._record("openai_responses", kwargs)

    def _create_messages(self, **kwargs):
        """记录 Anthropic Messages 的流式 SDK 参数。"""
        return self._record("anthropic_messages", kwargs)

    def _record(self, operation: str, kwargs: dict) -> _FakeSdkStream:
        """保存 SDK 参数，并返回已解帧的事件迭代器或模拟创建失败。"""
        self._seen["operation"] = operation
        self._seen["body"] = dict(kwargs)
        if self._error is not None:
            raise self._error
        return self._stream

    def close(self) -> None:
        """模拟 SDK 客户端释放，并供断言验证资源生命周期。"""
        self._seen["closed"] = True


def _capture_stream(monkeypatch, lines: list[str], *, error: Exception | None = None) -> dict:
    """替换 SDK 客户端工厂，向流式适配器注入已经过 SDK 解码的事件夹具。"""
    seen: dict = {}
    stream = _FakeSdkStream(seen, lines)
    client = _FakeSdkStreamClient(seen, stream, error)

    def fake_openai_client(**kwargs):
        """记录 OpenAI SDK 工厂参数。"""
        seen["client"] = dict(kwargs)
        return client

    def fake_anthropic_client(**kwargs):
        """记录 Anthropic SDK 工厂参数。"""
        seen["client"] = dict(kwargs)
        return client

    monkeypatch.setattr(adapters, "_openai_client", fake_openai_client)
    monkeypatch.setattr(adapters, "_anthropic_client", fake_anthropic_client)
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
    assert seen["operation"] == "openai_chat"
    assert seen["closed"] is True


@pytest.mark.parametrize(
    "protocol,sse_body,path,expected",
    [
        (
            "openai_chat",
            b'data: {"id":"chatcmpl_test","object":"chat.completion.chunk","created":0,"model":"test-model","choices":[{"index":0,"delta":{"role":"assistant","content":"SDK"},"finish_reason":null,"logprobs":null}]}\n\ndata: [DONE]\n\n',
            "/v1/chat/completions",
            [("content", "SDK")],
        ),
        (
            "openai_responses",
            b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","sequence_number":1,"item_id":"item_1","output_index":0,"content_index":0,"delta":"SDK"}\n\n',
            "/v1/responses",
            [("content", "SDK")],
        ),
        (
            "anthropic_messages",
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"SDK"}}\n\n',
            "/v1/messages",
            [("content", "SDK")],
        ),
    ],
)
def test_stream_sdk_wire_contract(monkeypatch, protocol, sse_body, path, expected):
    """真实 SDK 经 MockTransport 解帧后，适配器仍输出既有流式事件契约。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """记录 SDK 实际发出的请求，并回送最小合法 SSE 响应。"""
        seen.append(request)
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=sse_body,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    if protocol == "anthropic_messages":
        client = adapters.Anthropic(
            api_key=API_KEY,
            base_url=BASE,
            max_retries=0,
            http_client=http_client,
        )
        monkeypatch.setattr(adapters, "_anthropic_client", lambda **_kwargs: client)
    else:
        client = adapters.OpenAI(
            api_key=API_KEY,
            base_url=f"{BASE}/v1",
            max_retries=0,
            http_client=http_client,
        )
        monkeypatch.setattr(adapters, "_openai_client", lambda **_kwargs: client)

    try:
        assert list(stream_protocol(**_kwargs(protocol))) == expected
        request = seen[0]
        assert request.url.path == path
        assert json.loads(request.content)["stream"] is True
        if protocol == "anthropic_messages":
            assert request.headers["x-api-key"] == API_KEY
            assert request.headers["anthropic-version"] == "2023-06-01"
        else:
            assert request.headers["authorization"] == f"Bearer {API_KEY}"
    finally:
        http_client.close()


def test_stream_non_sse_response_maps_to_upstream(monkeypatch):
    """网关忽略 stream 参数而返回完整 JSON 时，拒绝静默空流并归一为 UPSTREAM。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """模拟兼容网关错误地返回非流式 JSON 响应。"""
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/json"},
            json=SDK_OPENAI_CHAT_OK,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = adapters.OpenAI(
        api_key=API_KEY,
        base_url=f"{BASE}/v1",
        max_retries=0,
        http_client=http_client,
    )
    monkeypatch.setattr(adapters, "_openai_client", lambda **_kwargs: client)
    try:
        with pytest.raises(AppError) as exc:
            list(stream_protocol(**_kwargs("openai_chat")))
        assert exc.value.code == ErrorCode.UPSTREAM
        assert exc.value.message == "上游未返回流式响应"
        assert API_KEY not in exc.value.message
    finally:
        http_client.close()


@pytest.mark.parametrize(
    "protocol,lines,expected_tool",
    [
        (
            "openai_chat",
            [
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"chat_read_1","function":{"name":"read","arguments":"{\\"path\\":"}}]}}]}',
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"a.txt\\"}"}}]}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
                "data: [DONE]",
            ],
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "读取文件",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            },
        ),
        (
            "openai_responses",
            [
                'data: {"type":"response.output_item.added","item":{"id":"fc_1","type":"function_call","call_id":"responses_read_1","name":"read"}}',
                'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{\\"path\\":"}',
                'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"\\"a.txt\\"}"}',
                'data: {"type":"response.function_call_arguments.done","item_id":"fc_1","call_id":"responses_read_1","name":"read","arguments":"{\\"path\\":\\"a.txt\\"}"}',
            ],
            {
                "type": "function",
                "name": "read",
                "description": "读取文件",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        ),
        (
            "anthropic_messages",
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"anthropic_read_1","name":"read","input":{}}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"\\"a.txt\\"}"}}',
                'data: {"type":"content_block_stop","index":0}',
            ],
            {
                "name": "read",
                "description": "读取文件",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        ),
    ],
)
def test_stream_native_tool_calls_accumulate_until_complete(
    monkeypatch, protocol, lines, expected_tool
):
    """P2-B：三协议的工具参数增量必须完整后才交给模型网关。"""
    seen = _capture_stream(monkeypatch, lines)
    chunks = list(
        stream_protocol(
            **_kwargs(protocol),
            tools=[
                {
                    "name": "read",
                    "description": "读取文件",
                    "parameters_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ],
        )
    )

    assert seen["body"]["tools"] == [expected_tool]
    assert len(chunks) == 1
    assert isinstance(chunks[0], AdapterStreamEvent)
    assert chunks[0].kind == "tool_call"
    assert chunks[0].tool_call is not None
    assert chunks[0].tool_call.name == "read"
    assert chunks[0].tool_call.arguments == {"path": "a.txt"}


@pytest.mark.parametrize(
    "protocol,lines",
    [
        (
            "openai_chat",
            [
                'data: {"choices":[{"delta":{"content":"我先读配置"}}]}',
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"chat_read_1","function":{"name":"read","arguments":"{\\"path\\":\\"a.txt\\"}"}}]}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
                "data: [DONE]",
            ],
        ),
        (
            "openai_responses",
            [
                'data: {"type":"response.output_text.delta","delta":"我先读配置"}',
                'data: {"type":"response.output_item.added","item":{"id":"fc_1","type":"function_call","call_id":"responses_read_1","name":"read"}}',
                'data: {"type":"response.function_call_arguments.done","item_id":"fc_1","call_id":"responses_read_1","name":"read","arguments":"{\\"path\\":\\"a.txt\\"}"}',
            ],
        ),
        (
            "anthropic_messages",
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"我先读配置"}}',
                'data: {"type":"content_block_stop","index":0}',
                'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"anthropic_read_1","name":"read","input":{}}}',
                'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"a.txt\\"}"}}',
                'data: {"type":"content_block_stop","index":1}',
            ],
        ),
    ],
)
def test_stream_text_then_complete_tool_call(monkeypatch, protocol, lines):
    """P1：三协议交错块必须先交出正文增量，参数完整后才产生 ToolCall。"""
    _capture_stream(monkeypatch, lines)
    chunks = list(stream_protocol(**_kwargs(protocol)))

    assert chunks[0] == ("content", "我先读配置")
    assert isinstance(chunks[1], AdapterStreamEvent)
    assert chunks[1].kind == "tool_call"
    assert chunks[1].tool_call is not None
    assert chunks[1].tool_call.name == "read"
    assert chunks[1].tool_call.arguments == {"path": "a.txt"}
    assert len(chunks) == 2


def test_stream_rejects_incomplete_tool_arguments(monkeypatch):
    """P2-B：完成帧上的不完整工具 JSON 必须失败，绝不能猜测执行参数。"""
    _capture_stream(
        monkeypatch,
        [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"chat_read_1","function":{"name":"read","arguments":"{\\"path\\":"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        ],
    )

    with pytest.raises(AppError) as error:
        list(stream_protocol(**_kwargs("openai_chat")))

    assert error.value.code == ErrorCode.UPSTREAM
    assert error.value.message == "上游工具调用参数结构异常"


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


def test_stream_mimo_keeps_thinking_enabled(monkeypatch):
    """对话/ReAct 流式请求不得关闭 mimo 思考，否则前端收不到 reasoning_content。"""
    seen = _capture_stream(monkeypatch, ['data: {"choices":[{"delta":{"content":"ok"}}]}'])
    kwargs = _kwargs("openai_chat") | {"base_url": "https://xiaomimimo.example.com"}
    list(stream_protocol(**kwargs))

    assert seen["body"]["extra_body"] == {"thinking": {"type": "enabled"}}


def test_stream_gemini_includes_thought_summaries(monkeypatch):
    """Gemini OpenAI 兼容流式请求开启 Google thought summary 与强度。"""
    seen = _capture_stream(monkeypatch, ['data: {"choices":[{"delta":{"content":"ok"}}]}'])
    kwargs = _kwargs("openai_chat") | {
        "model": "gemini-3.5-flash-lite",
        "reasoning_effort": "high",
    }
    list(stream_protocol(**kwargs))

    assert seen["body"]["extra_body"] == {
        "extra_body": {
            "google": {
                "thinking_config": {
                    "thinking_level": "high",
                    "include_thoughts": True,
                }
            }
        }
    }


def test_stream_gemini_thinking_delta_is_reasoning(monkeypatch):
    """Gemini 兼容网关返回 thinking 增量时归一为 reasoning。"""
    _capture_stream(
        monkeypatch,
        [
            'data: {"choices":[{"delta":{"thinking":"先分析"}}]}',
            'data: {"choices":[{"delta":{"content":"答案"}}]}',
        ],
    )
    kwargs = _kwargs("openai_chat") | {"model": "gemini-3.5-flash-lite"}

    assert list(stream_protocol(**kwargs)) == [
        ("reasoning", "先分析"),
        ("content", "答案"),
    ]


def test_stream_mimo_can_disable_thinking(monkeypatch):
    """关闭思考设置时，Mimo 流式请求明确发送 disabled。"""
    seen = _capture_stream(monkeypatch, ['data: {"choices":[{"delta":{"content":"ok"}}]}'])
    kwargs = _kwargs("openai_chat") | {
        "base_url": "https://xiaomimimo.example.com",
        "reasoning_enabled": False,
    }
    list(stream_protocol(**kwargs))

    assert seen["body"]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_call_mimo_still_disables_thinking(monkeypatch):
    """非流式 JSON 规划仍关闭思考，避免 reasoning 占满 max_tokens。"""
    seen = _capture(monkeypatch, OPENAI_CHAT_OK)
    kwargs = _kwargs("openai_chat") | {"base_url": "https://xiaomimimo.example.com"}
    call_protocol(**kwargs)

    assert seen["body"]["extra_body"] == {"thinking": {"type": "disabled"}}


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


def test_stream_ignores_unknown_sdk_events(monkeypatch):
    """非目标 SDK 事件不产生增量，也不阻断后续标准文本事件。"""
    _capture_stream(
        monkeypatch,
        [
            'data: {"type":"response.created"}',
            'data: {"type":"response.output_text.delta","delta":"ok"}',
        ],
    )
    assert list(stream_protocol(**_kwargs("openai_responses"))) == [("content", "ok")]


def test_stream_4xx_maps_to_upstream(monkeypatch):
    """建连即 4xx：归一为 UPSTREAM，消息仅含状态码。"""
    request = httpx.Request("POST", f"{BASE}/v1/chat/completions")
    _capture_stream(
        monkeypatch,
        [],
        error=openai.APIStatusError(
            "Too Many Requests",
            response=httpx.Response(429, request=request),
            body=None,
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


def test_stream_passes_timeout_to_sdk_client(monkeypatch):
    """流式调用把协议档超时原样传入 SDK，不再维护手写 urllib 建连超时。"""
    seen = _capture_stream(
        monkeypatch,
        ['data: {"choices":[{"delta":{"content":"ok"}}]}'],
    )
    list(stream_protocol(**_kwargs("openai_chat"), timeout_s=45.0))

    assert seen["client"]["timeout_s"] == 45.0


def test_stream_aborts_before_connect(monkeypatch):
    """令牌已取消时不得创建 SDK 客户端或发 HTTP 请求。"""
    called = {"n": 0}

    def fake_client(**_kwargs):
        called["n"] += 1
        raise AssertionError("已取消时不得创建客户端")

    monkeypatch.setattr(adapters, "_openai_client", fake_client)
    with pytest.raises(adapters.StreamAborted):
        list(stream_protocol(**_kwargs("openai_chat"), should_abort=lambda: True))

    assert called["n"] == 0


def test_stream_sdk_timeout_maps_to_timeout(monkeypatch):
    """SDK 流式建连或读事件超时仍统一归一为 TIMEOUT。"""
    _capture_stream(
        monkeypatch,
        [],
        error=openai.APITimeoutError(httpx.Request("POST", f"{BASE}/v1/chat/completions")),
    )
    with pytest.raises(AppError) as exc_info:
        list(stream_protocol(**_kwargs("openai_chat"), should_abort=lambda: False))
    assert exc_info.value.code == ErrorCode.TIMEOUT


def test_stream_sdk_connection_error_maps_to_upstream(monkeypatch):
    """SDK 流式连接失败归一为 UPSTREAM，避免暴露底层网络异常。"""
    _capture_stream(
        monkeypatch,
        [],
        error=openai.APIConnectionError(
            request=httpx.Request("POST", f"{BASE}/v1/chat/completions")
        ),
    )
    with pytest.raises(AppError) as exc_info:
        list(stream_protocol(**_kwargs("openai_chat"), should_abort=lambda: False))
    assert exc_info.value.code == ErrorCode.UPSTREAM
