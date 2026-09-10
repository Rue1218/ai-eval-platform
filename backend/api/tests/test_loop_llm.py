"""新异步模型层的契约、原始增量、取消和协议往返回归。"""

import asyncio
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.llm.contracts import ModelConfig, SystemSegment
from app.llm.loop_contracts import (
    Done,
    LlmRequest,
    LlmRequestError,
    MissingApiKeyError,
    ProviderItemEnd,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    ToolSpec,
    UnsupportedReasoningEffortError,
    classify_provider_error,
    header_fingerprint,
)
from app.llm.providers.anthropic import AnthropicAdapter, to_anthropic_messages
from app.llm.providers.common import compatibility_key, normalize_base_url
from app.llm.providers.openai import OpenAiAdapter, to_openai_messages
from app.llm.resolver import (
    AuthorizedProfileSnapshot,
    build_adapter,
    close_adapter,
    resolve_request,
)


class FakeStream:
    """确定性异步流，可停在首 token 前以验证真实取消传播。"""

    def __init__(self, events=(), *, block=False):
        self.events = list(events)
        self.block = block
        self.started = asyncio.Event()
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        """等待由测试取消，禁止同步阻塞事件循环。"""
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event

    async def close(self):
        """记录适配器是否释放响应。"""
        self.closed = True


class FakeClient:
    """三种 SDK 资源共用的测试替身，记录真实请求参数。"""

    def __init__(self):
        self.stream = FakeStream()
        self.requests = []
        self.closed = False
        self.chat = SimpleNamespace(completions=self)
        self.messages = self

    async def create(self, **kwargs):
        """每次调用记录一次，不提供隐式重试。"""
        self.requests.append(kwargs)
        return self.stream

    async def close(self):
        """记录资源拥有者的关闭调用。"""
        self.closed = True


@pytest.fixture
def clients(monkeypatch):
    """替换构造入口，任何测试都不触达真实模型或读取凭据。"""
    created = []

    def factory(**kwargs):
        """保留 SDK 初始化选项以验证重试、URL、超时。"""
        client = FakeClient()
        client.options = kwargs
        created.append(client)
        return client

    monkeypatch.setattr("openai.AsyncOpenAI", factory)
    monkeypatch.setattr("anthropic.AsyncAnthropic", factory)
    return created


def request(**kwargs):
    """源五个必填参数即可构建请求。"""
    return LlmRequest(
        **{
            "model": "plain-model",
            "messages": [],
            "system": "规则",
            "tools": [],
            "max_tokens": 4096,
            **kwargs,
        }
    )


async def collect(adapter, req):
    """模拟图的一次消费，不把 Done 当回合完成。"""
    return [chunk async for chunk in adapter.stream(req)]


def chat(delta=None, finish=None, usage=None):
    """Chat SSE 内容在 SDK 解码后的结构。"""
    return {
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
        "usage": usage,
    }


def anthropic_events(*, signature=True, broken_args=False):
    """思考签名、工具调用和尾部用量的最小完整消息。"""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "usage": {
                    "input_tokens": 5,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 2,
                },
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "分析"},
        },
    ]
    if signature:
        events.append(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "opaque-signature"},
            }
        )
    events += [
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "call_1", "name": "read", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        },
    ]
    if not broken_args:
        events.append(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '"a"}'},
            }
        )
    events += [
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 9},
        },
        {"type": "message_stop"},
    ]
    return events


def test_source_header_and_constructor_compatibility():
    """没有平台扩展时源 header 和指纹完全不变。"""
    tool = ToolSpec("read", "读文件", {"type": "object"})
    req = LlmRequest("m", [], "规则", [tool], 42, "deepseek", "medium", True)
    expected = {
        "model": "m",
        "system": "规则",
        "tools": [asdict(tool)],
        "max_tokens": 42,
        "provider": "deepseek",
        "reasoning_effort": "medium",
        "thinking": True,
    }
    assert req.header() == expected
    assert req.fingerprint() == header_fingerprint(expected)
    assert Done("stop", {"prompt_tokens": 2}).protocol_state is None


def test_resolver_freezes_and_excludes_credentials(clients):
    """配置、schema 与消息修改不影响请求快照；密钥仅进 SDK。"""
    config = ModelConfig(
        "openai_chat",
        "https://unit.invalid/v1/chat/completions",
        "deepseek-chat",
        api_key="secret-test-key",
    )
    profile = AuthorizedProfileSnapshot(config, "p1", 3, "deepseek")
    messages = [{"role": "user", "content": "你好"}]
    tools = [{"name": "read", "parameters_schema": {"type": "object"}}]
    req = resolve_request(profile, messages=messages, tools=tools)
    messages[0]["content"] = "改变"
    tools[0]["parameters_schema"]["type"] = "array"
    adapter, model = build_adapter(profile)
    assert model == "deepseek-chat"
    assert req.messages[0]["content"] == "你好"
    assert req.tools[0].parameters["type"] == "object"
    assert req.profile_version == 3
    assert "secret-test-key" not in json.dumps(asdict(req))
    assert "secret-test-key" not in repr(profile)
    assert clients[-1].options["max_retries"] == 0
    assert clients[-1].options["base_url"] == "https://unit.invalid/v1"
    clients[-1].stream = FakeStream([chat(finish="stop")])
    asyncio.run(collect(adapter, req))
    wire = clients[-1].requests[-1]
    assert wire["extra_body"]["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in wire  # 旧 DeepSeek 仅发送思考开关。
    asyncio.run(close_adapter(adapter))
    assert clients[-1].closed


@pytest.mark.parametrize(
    "protocol,adapter_type",
    [
        ("openai_chat", OpenAiAdapter),
        ("anthropic_messages", AnthropicAdapter),
    ],
)
def test_build_each_protocol(clients, protocol, adapter_type):
    """协议决定 codec，不以供应商名替代协议路由。"""
    config = ModelConfig(
        protocol, "https://unit.invalid/v1", "m", api_key="unit", reasoning_enabled=False
    )
    adapter, model = build_adapter(config)
    assert isinstance(adapter, adapter_type)
    assert model == "m"
    assert clients[-1].options["max_retries"] == 0


@pytest.mark.parametrize(
    "suffix", ["", "/v1", "/v1/chat/completions", "/v1/messages"]
)
def test_url_single_version(suffix):
    """平台根地址和源版本地址都只附加一个 v1。"""
    assert (
        normalize_base_url("https://unit.invalid" + suffix, "openai_chat")
        == "https://unit.invalid/v1"
    )
    assert (
        normalize_base_url("https://unit.invalid" + suffix, "anthropic_messages")
        == "https://unit.invalid"
    )


def test_resolver_rejects_conflicts_and_missing_key(clients):
    """能力和矛盾配置在网络请求前失败，不静默降级。"""
    config = ModelConfig("openai_chat", "https://unit.invalid", "plain", reasoning_enabled=False)
    with pytest.raises(MissingApiKeyError):
        build_adapter(config)
    with pytest.raises(LlmRequestError):
        resolve_request(config, messages=[], system="不同", system_segments=[SystemSegment("分段")])
    with pytest.raises(LlmRequestError):
        resolve_request({"config": config}, messages=[])
    with pytest.raises(UnsupportedReasoningEffortError):
        resolve_request(replace(config, reasoning_enabled=True), messages=[])
    with pytest.raises(LlmRequestError):
        resolve_request(replace(config, base_url="https://secret@unit.invalid"), messages=[])
    adapter = OpenAiAdapter(api_key="unit")
    with pytest.raises(LlmRequestError):
        asyncio.run(collect(adapter, request(reasoning_effort="off", thinking=True)))
    assert clients[-1].requests == []


def test_chat_raw_arguments_usage_and_reasoning(clients):
    """坏 JSON 不丢弃；usage-only 尾块进入唯一 Done。"""
    adapter = OpenAiAdapter(api_key="unit", provider="deepseek")
    clients[-1].stream = FakeStream(
        [
            chat({"reasoning_content": "想", "content": "读"}),
            chat(
                {
                    "tool_calls": [
                        {
                            "index": 2,
                            "id": "call_1",
                            "function": {"name": "read", "arguments": '{"path":'},
                        }
                    ]
                }
            ),
            chat(finish="tool_calls"),
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 4},
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            },
        ]
    )
    chunks = asyncio.run(collect(adapter, request()))
    assert chunks[:2] == [ReasoningDelta("想"), TextDelta("读")]
    assert ToolCallStart(2, "call_1", "read") in chunks
    assert ToolCallDelta(2, '{"path":') in chunks
    assert chunks[-1] == Done(
        "tool_calls",
        {"prompt_tokens": 12, "completion_tokens": 5, "cached_tokens": 4, "reasoning_tokens": 3},
    )
    assert clients[-1].stream.closed


def test_chat_source_messages_preserve_raw_and_error_results():
    """源 args 不再经旧 arguments codec 丢成空对象。"""
    messages = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "想",
            "tool_calls": [
                {"id": "c", "name": "read", "args": {"path": "a"}, "arguments_raw": '{"path":"a"}'}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c",
            "name": "read",
            "content": "不存在",
            "is_error": True,
        },
    ]
    wire = to_openai_messages(messages, "", include_reasoning_content=True)
    assert wire[0]["tool_calls"][0]["function"]["arguments"] == '{"path":"a"}'
    assert wire[0]["reasoning_content"] == "想"
    assert wire[1] == {"role": "tool", "tool_call_id": "c", "content": "不存在"}


def test_image_tool_result_converts_for_openai_and_anthropic():
    """read_image 的当前回合图文结果应进入 provider 请求，且不要求持久事件保留字节。"""
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "image-call", "name": "read_image", "args": {"file_path": "a.png"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "image-call",
            "name": "read_image",
            "content": [
                {"type": "text", "text": "已读取图片"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
            ],
            "is_error": False,
        },
    ]
    openai_wire = to_openai_messages(messages, "")
    assert openai_wire[1]["content"][1]["image_url"]["url"].endswith("YQ==")
    anthropic_wire = to_anthropic_messages(messages)
    assert anthropic_wire[1]["content"][0]["content"][1]["source"]["data"] == "YQ=="


@pytest.mark.parametrize("adapter_type", [OpenAiAdapter, AnthropicAdapter])
def test_eof_does_not_fabricate_done(clients, adapter_type):
    """自然 EOF 不等同于模型完成。"""
    adapter = adapter_type(api_key="unit")
    assert asyncio.run(collect(adapter, request())) == []
    assert clients[-1].stream.closed


@pytest.mark.parametrize("adapter_type", [OpenAiAdapter, AnthropicAdapter])
def test_cancel_before_first_token_closes_stream(clients, adapter_type):
    """等待首 token 时取消必须直接打断并关闭响应，不产生 Done。"""

    async def scenario():
        adapter = adapter_type(api_key="unit")
        stream = clients[-1].stream = FakeStream(block=True)
        task = asyncio.create_task(collect(adapter, request()))
        await asyncio.wait_for(stream.started.wait(), 0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.5)
        assert stream.closed
        await close_adapter(adapter)
        assert clients[-1].closed

    asyncio.run(scenario())


@pytest.mark.parametrize("status,retryable", [(401, False), (400, False), (429, True), (500, True)])
def test_error_classification_redacts_upstream(status, retryable):
    """上游错误中的密钥正文不进入规范异常。"""
    error = RuntimeError("Authorization: super-secret")
    error.status_code = status
    result = classify_provider_error(error)
    assert result.retryable is retryable
    assert result.status_code == status
    assert "super-secret" not in str(result)


def test_anthropic_signature_tool_roundtrip_and_cache(clients):
    """签名完整回传一次，工具结果合并且保留错误标记及缓存边界。"""
    config = ModelConfig(
        "anthropic_messages", "https://unit.invalid/v1", "claude-sonnet-4", api_key="unit"
    )
    profile = AuthorizedProfileSnapshot(config, "p", 2, "anthropic", True)
    req = resolve_request(
        profile, messages=[], system_segments=[SystemSegment("静态", True), SystemSegment("动态")]
    )
    adapter, _ = build_adapter(profile)
    client = clients[-1]
    client.stream = FakeStream(anthropic_events())
    chunks = asyncio.run(collect(adapter, req))
    done = chunks[-1]
    assert done.finish_reason == "tool_calls"
    assert done.usage["cached_tokens"] == 3
    assert done.usage["cache_creation_input_tokens"] == 2
    assert done.usage["completion_tokens"] == 9
    assert done.usage["input_tokens"] == 5
    assert done.usage["prompt_tokens"] == 10
    assert done.usage["total_tokens"] == 19
    assert done.protocol_state.items[0]["signature"] == "opaque-signature"
    assert len([chunk for chunk in chunks if isinstance(chunk, ProviderItemEnd)]) == 2
    assert client.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in client.requests[0]["system"][1]
    assert "temperature" not in client.requests[0]
    assert client.requests[0]["thinking"]["budget_tokens"] >= 1024
    messages = [
        {
            "role": "assistant",
            "content": "",
            "protocol_state": asdict(done.protocol_state),
            "tool_calls": [{"id": "call_1", "name": "read", "args": {"path": "a"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "失败", "is_error": True},
    ]
    client.stream = FakeStream()
    asyncio.run(collect(adapter, replace(req, messages=messages)))
    wire = client.requests[-1]["messages"]
    assert len(wire) == 2
    assert wire[0]["content"] == done.protocol_state.items
    assert wire[1]["content"][0]["is_error"] is True
    assert len(wire[1]["content"]) == 1


def test_anthropic_bad_json_preserves_fragments(clients):
    """坏参数仍形成源 ToolCallDelta，不能由 codec 整项丢弃。"""
    adapter = AnthropicAdapter(api_key="unit")
    clients[-1].stream = FakeStream(anthropic_events(broken_args=True))
    chunks = asyncio.run(collect(adapter, request()))
    assert ToolCallDelta(1, '{"path":') in chunks
    assert chunks[-1].finish_reason == "tool_calls"
    wire = to_anthropic_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c", "name": "read", "arguments_raw": "{", "parse_error": "invalid_json"}
                ],
            },
            {"role": "tool", "tool_call_id": "c", "content": "参数错误", "is_error": True},
        ]
    )
    assert wire[0]["content"][0]["input"] == {}


def test_anthropic_rejects_missing_signature(clients):
    """签名残缺不能提交为成功历史。"""
    adapter = AnthropicAdapter(api_key="unit")
    clients[-1].stream = FakeStream(anthropic_events(signature=False))
    with pytest.raises(LlmRequestError, match="签名"):
        asyncio.run(collect(adapter, request()))
    assert clients[-1].stream.closed


@pytest.mark.parametrize("model", ["deepseek-v4-flash-0731", "qwen3.6-flash"])
def test_compatible_anthropic_unsigned_thinking_tool_roundtrip(clients, model):
    """兼容流空签名可回填工具结果，且不会越过 Claude 的跨模型边界。"""
    profile = AuthorizedProfileSnapshot(
        ModelConfig(
            "anthropic_messages",
            "https://unit.invalid/apps/anthropic",
            model,
            api_key="unit",
            reasoning_enabled=False,
        )
    )
    req = resolve_request(profile, messages=[])
    adapter, _ = build_adapter(profile)
    client = clients[-1]
    client.stream = FakeStream(anthropic_events(signature=False))
    chunks = asyncio.run(collect(adapter, req))
    done = chunks[-1]
    assert done.finish_reason == "tool_calls"
    assert done.protocol_state.items[0] == {
        "type": "thinking",
        "thinking": "分析",
        "signature": "",
    }
    assert client.requests[0]["thinking"] == {"type": "disabled"}
    messages = [
        {
            "role": "assistant",
            "content": "",
            "protocol_state": asdict(done.protocol_state),
            "tool_calls": [{"id": "call_1", "name": "read", "args": {"path": "a"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "文件内容"},
    ]
    client.stream = FakeStream()
    asyncio.run(collect(adapter, replace(req, messages=messages)))
    assert client.requests[-1]["messages"][0]["content"] == done.protocol_state.items
    assert client.requests[-1]["messages"][1]["content"][0]["tool_use_id"] == "call_1"
    with pytest.raises(LlmRequestError, match="不兼容"):
        to_anthropic_messages(messages, request=replace(req, model="claude-sonnet-4"))


@pytest.mark.parametrize(
    "adapter_type,wire_key",
    [(OpenAiAdapter, "messages"), (AnthropicAdapter, "messages")],
)
def test_platform_multimodal_content(clients, adapter_type, wire_key):
    """平台图文块正确转换，图片与文字均不可丢失。"""
    adapter = adapter_type(api_key="unit")
    req = request(
        system="",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,YQ==", "detail": "high"},
                    },
                ],
            }
        ],
    )
    asyncio.run(collect(adapter, req))
    parts = clients[-1].requests[-1][wire_key][0]["content"]
    assert len(parts) == 2
    assert parts[0]["text"] == "识图"
    assert "YQ==" in json.dumps(parts[1])


def test_protocol_state_compatibility_key_is_stable():
    """键包含供应商、协议及模型，不包含凭据。"""
    assert compatibility_key("a", "b", "c") == compatibility_key("a", "b", "c")
    assert compatibility_key("a", "b", "c") != compatibility_key("a", "b", "d")


@pytest.mark.parametrize(
    "options",
    [
        {"api_key": "secret"},
        {"extra_headers": {"authorization": "secret"}},
        {"thinking": {"type": "enabled", "api_key": "secret"}},
        {"output_config": {"effort": "high", "api_key": "secret"}},
        {"output_config": {"effort": {"api_key": "secret"}}},
    ],
)
def test_request_rejects_credentials_before_header(options):
    """不能先把凭据写入 header 再等 SDK 请求时校验。"""
    with pytest.raises(LlmRequestError):
        request(provider_options=options)


@pytest.mark.parametrize("model,effort,max_tokens", [
    ("qwen3-coder-plus", "high", 4096),
    ("qwen3.6-flash-unknown", "high", 4096),
    ("qwen3.6-flash", "high", 1024),
])
def test_compatible_reasoning_does_not_invent_model_or_budget_capabilities(model, effort, max_tokens):
    """近似型号、供应商别名档位和不足的预算不得被 UI 当成可用能力。"""
    with pytest.raises(UnsupportedReasoningEffortError):
        resolve_request(ModelConfig(
            "anthropic_messages", "https://unit.invalid", model, api_key="test-only",
            max_tokens=max_tokens, reasoning_effort=effort,
        ), messages=[])


@pytest.mark.parametrize(
    "adapter_type,events",
    [
        (AnthropicAdapter, anthropic_events),
    ],
)
def test_provider_chunks_feed_real_attempt_and_next_request(clients, adapter_type, events):
    """与并行迁入的 Attempt 实际联调，工具结果回填后可发下一模型请求。"""
    from app.agent.stream import AssistantAttempt

    async def scenario():
        adapter = adapter_type(api_key="unit")
        client = clients[-1]
        client.stream = FakeStream(events())
        attempt = AssistantAttempt()
        async for chunk in adapter.stream(request()):
            attempt.push(chunk)
        assert not attempt.identity_errors()
        assert not attempt.protocol_errors()
        message = attempt.message()
        assert len(message["tool_calls"]) == 1
        assert message["tool_calls"][0]["args"] == {"path": "a"}
        assert message["reasoning_content"] == "分析"
        client.stream = FakeStream()
        await collect(
            adapter,
            request(
                messages=[
                    message,
                    {"role": "tool", "tool_call_id": "call_1", "content": "文件内容"},
                ]
            ),
        )
        assert len(client.requests) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("adapter_type", [OpenAiAdapter, AnthropicAdapter])
@pytest.mark.parametrize("malformed", [False, True])
def test_attempt_fact_projection_preserves_source_arguments(clients, adapter_type, malformed):
    """真实 Attempt 与事实投影联调，验证正常/坏 JSON 的 args/raw 及状态往返。"""
    from app.agent.stream import AssistantAttempt
    from app.harness.memory.agent_messages import derive_messages

    raw = '{"path":' if malformed else '{"path":"a"}'
    if adapter_type is OpenAiAdapter:
        events = [
            chat(
                {
                    "tool_calls": [
                        {"index": 0, "id": "call_1", "function": {"name": "read", "arguments": raw}}
                    ]
                }
            ),
            chat(finish="tool_calls"),
        ]
    elif adapter_type is AnthropicAdapter:
        events = anthropic_events(broken_args=malformed)
    async def scenario():
        adapter = adapter_type(api_key="unit")
        client = clients[-1]
        client.stream = FakeStream(events)
        attempt = AssistantAttempt()
        chunks = await collect(adapter, request())
        for chunk in chunks:
            attempt.push(chunk)
        assert not attempt.identity_errors()
        assert not attempt.protocol_errors()
        message = attempt.message()
        call = message["tool_calls"][0]
        assert call["arguments_raw"] == raw
        if malformed:
            assert "parse_error" in call
            assert "args" not in call
        else:
            assert call["args"] == {"path": "a"}
            assert "parse_error" not in call
        if adapter_type is not OpenAiAdapter:
            expected = [chunk.item for chunk in chunks if isinstance(chunk, ProviderItemEnd)]
            assert message["protocol_state"]["items"] == expected
            assert asdict(chunks[-1].protocol_state)["items"] == expected
        facts = [
            {"seq": 1, "type": "user/message", "data": {"content": "读文件"}},
            {"seq": 2, "type": "assistant/message", "data": {"message": message}},
            {
                "seq": 3,
                "type": "tool/result",
                "data": {
                    "call_id": "call_1",
                    "name": "read",
                    "status": "failed" if malformed else "succeeded",
                    "content": "参数错误" if malformed else "文件内容",
                },
            },
        ]
        projected = derive_messages(facts)
        assert projected[1] == message
        assert projected[1] is not message
        assert projected[2]["is_error"] is malformed
        client.stream = FakeStream()
        await collect(adapter, request(messages=projected))
        wire = client.requests[-1]
        if adapter_type is OpenAiAdapter:
            assert wire["messages"][2]["tool_calls"][0]["function"]["arguments"] == raw
        elif adapter_type is AnthropicAdapter:
            tool = [
                block for block in wire["messages"][1]["content"] if block["type"] == "tool_use"
            ]
            assert len(tool) == 1
            assert tool[0]["input"] == ({} if malformed else {"path": "a"})
            if malformed:
                assert wire["messages"][2]["content"][0]["is_error"]
    asyncio.run(scenario())


@pytest.mark.parametrize(
    "adapter_type,events",
    [(AnthropicAdapter, anthropic_events)],
)
def test_attempt_rejects_done_state_different_from_item_end(clients, adapter_type, events):
    """Done 和 ItemEnd 是同一完成事实，二者被篡改成不同快照时必须拒绝。"""
    from app.agent.stream import AssistantAttempt

    adapter = adapter_type(api_key="unit")
    clients[-1].stream = FakeStream(events())
    chunks = asyncio.run(collect(adapter, request()))
    done = chunks[-1]
    broken = replace(done, protocol_state=replace(done.protocol_state, items=[]))
    attempt = AssistantAttempt()
    for chunk in [*chunks[:-1], broken]:
        attempt.push(chunk)
    assert attempt.protocol_errors()


@pytest.mark.parametrize("adapter_type", [OpenAiAdapter, AnthropicAdapter])
@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "unknown", "content": "不能变成用户消息"}],
        [{"role": "user", "tool_calls": [{"id": "c", "name": "read", "args": {}}]}],
        [{"role": "user", "content": "x", "protocol_state": {"items": []}}],
        [{"role": "assistant", "tool_calls": [{"id": "c", "name": "read", "args": {}}]}],
        [{"role": "tool", "tool_call_id": "unknown", "content": "没有配对"}],
        [
            {"role": "assistant", "tool_calls": [{"id": "c", "name": "read", "args": {}}]},
            {"role": "user", "content": "不能切开调用组"},
            {"role": "tool", "tool_call_id": "c", "content": "x"},
        ],
    ],
)
def test_codecs_reject_unknown_or_incomplete_history(clients, adapter_type, messages):
    """畸形历史在发请求前明确失败，不能靠空对象或丢字段让它继续执行。"""
    adapter = adapter_type(api_key="unit")
    with pytest.raises(LlmRequestError):
        asyncio.run(collect(adapter, request(messages=messages)))
    assert not clients[-1].requests


def test_anthropic_merges_only_paired_results():
    """合并连续的合法 tool_result，不放过未知或重复的调用 ID。"""
    history = [
        {
            "role": "assistant",
            "tool_calls": [{"id": name, "name": "read", "args": {}} for name in ("a", "b")],
        },
        {"role": "tool", "tool_call_id": "a", "content": "a"},
        {"role": "tool", "tool_call_id": "b", "content": "b"},
    ]
    wire = to_anthropic_messages(history)
    assert len(wire) == 2
    assert [part["tool_use_id"] for part in wire[1]["content"]] == ["a", "b"]


def test_direct_helpers_do_not_discard_opaque_state_without_request():
    """未提供兼容性上下文时 helper 不能静默抹掉协议状态。"""
    message = {
        "role": "assistant",
        "content": "正文",
        "protocol_state": {"items": [{"type": "thinking", "signature": "sig"}]},
    }
    with pytest.raises(LlmRequestError):
        to_anthropic_messages([message])
    with pytest.raises(LlmRequestError):
        to_openai_messages([message], "")
