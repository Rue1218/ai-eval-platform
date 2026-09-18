"""真实官方 SDK 配合本地 HTTP 替身，验证解码、取消和零重试。"""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace

import anthropic
import httpx
import openai
import pytest

from app.llm.loop_contracts import Done, LlmRequest, LlmRequestError, TextDelta
from app.llm.providers.anthropic import AnthropicAdapter
from app.llm.providers.openai import OpenAiAdapter
from app.llm.providers.responses import ResponsesAdapter
from app.llm.resolver import close_adapter

PROTOCOLS = [
    (OpenAiAdapter, "openai", "/v1/chat/completions"),
    (AnthropicAdapter, "anthropic", "/v1/messages"),
    (ResponsesAdapter, "openai", "/v1/responses"),
]


@pytest.mark.parametrize("model", ["deepseek-v4-flash-0731", "qwen3.6-flash", "qwen3.8-flash"])
@pytest.mark.parametrize("effort", ["off", "high", "max"])
def test_compatible_messages_sdk_loop_and_next_turn(monkeypatch, model, effort):
    """真实 SDK 和七节点图验证空签名、工具回填、最终回复及下一轮历史。"""
    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from app.llm.contracts import ModelConfig
    from app.llm.loop_contracts import ToolSpec
    from app.llm.resolver import build_adapter, resolve_request
    from tests.test_loop_llm import anthropic_events
    from tests.test_loop_runtime import MemoryLog, RecordingScheduler

    requests = []
    config = ModelConfig("anthropic_messages", "https://unit.invalid/apps/anthropic", model,
                         api_key="unit", reasoning_enabled=False)
    specs = [ToolSpec("read", "读取", {"type":"object", "properties":{"path":{"type":"string"}}})]

    def handler(http_request):
        """只替换供应商 HTTP 响应；SDK、codec、Runtime 和图均保持真实实现。"""
        payload = json.loads(http_request.content)
        requests.append(payload)
        assert http_request.url.path == "/apps/anthropic/v1/messages"
        assert payload["model"] == model
        expected_effort = effort if len(requests) < 3 else "off"
        assert http_request.method == "POST"
        assert payload["stream"] is True
        if expected_effort == "off":
            assert payload["thinking"] == {"type":"disabled"}
            assert "output_config" not in payload
        else:
            assert payload["thinking"]["type"] == "enabled"
            assert "temperature" not in payload
            if model.startswith("deepseek"):
                assert payload["output_config"] == {"effort": expected_effort}
                assert "budget_tokens" not in payload["thinking"]
            else:
                ratio = 0.6 if expected_effort == "high" else 0.8
                budget = round(config.max_tokens * ratio)
                assert payload["thinking"]["budget_tokens"] == budget
                if model.startswith("qwen3.8"):
                    # 3.8 起 max_tokens 是总输出上限，思考预算必须小于它，不能额外扣除。
                    assert payload["max_tokens"] == config.max_tokens
                    assert budget < payload["max_tokens"]
                else:
                    assert payload["max_tokens"] + budget == config.max_tokens
        if len(requests) == 1:
            wire = b"".join(sse(event, named=True) for event in anthropic_events(signature=False))
        else:
            wire = successful_wire(AnthropicAdapter)
        return httpx.Response(200, content=wire, headers={"content-type":"text/event-stream"})

    install_transport(monkeypatch, "anthropic", handler)

    async def scenario():
        """工具节点完成后再次请求模型，下一轮继续携带原始工具和思考块。"""
        adapter, _ = build_adapter(config)
        scheduler = RecordingScheduler()
        graph = await build_agent(
            LoopSettings(), adapter=adapter, scheduler=scheduler,
            request_factory=lambda messages, selected: resolve_request(
                replace(config, reasoning_enabled=selected != "off", reasoning_effort=selected),
                messages=messages, tools=specs,
            ),
        )
        runtime = AgentRuntime(MemoryLog(), graph)
        try:
            await runtime.submit("读取文件", reasoning_effort=effort)
            await runtime.wait()
            assert runtime.log.read()[-1]["data"]["reason"] == "completed"
            assert len(requests) == 2
            assert len(scheduler.invocations) == 1
            blocks = requests[1]["messages"][1]["content"]
            assert blocks[0] == {"type":"thinking", "thinking":"分析", "signature":""}
            assert blocks[1]["type"] == "tool_use"
            assert requests[1]["messages"][2]["content"][0]["tool_use_id"] == "call_1"
            await runtime.submit("继续上一轮", reasoning_effort="off")
            await runtime.wait()
            assert runtime.log.read()[-1]["data"]["reason"] == "completed"
            assert len(requests) == 3
            assert requests[2]["messages"][1]["content"] == blocks
        finally:
            await runtime.close()
            await adapter.close()

    asyncio.run(scenario())


def install_transport(monkeypatch, sdk, handler):
    """仅替换 HTTP transport，保留 SDK 的真实 create、SSE 解码与关闭代码。"""
    module = openai if sdk == "openai" else anthropic
    name = "AsyncOpenAI" if sdk == "openai" else "AsyncAnthropic"
    original = getattr(module, name)

    def factory(**kwargs):
        """适配器的 max_retries 和超时参数原样进入官方 SDK。"""
        return original(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr(module, name, factory)


async def consume(adapter):
    """一次完整流消费。"""
    return [chunk async for chunk in adapter.stream(LlmRequest("test-model", [], "", [], 64))]


def sse(event, *, named=False):
    """按真实协议打包事件，Anthropic 使用命名 SSE。"""
    prefix = f"event: {event['type']}\n" if named else ""
    return (prefix + "data: " + json.dumps(event) + "\n\n").encode()


def successful_wire(adapter_type):
    """足够完整的供应商流，经过本机安装 SDK 的类型解码。"""
    if adapter_type is OpenAiAdapter:
        base = {
            "id": "chat_1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "test-model",
        }
        return b"".join(
            [
                sse(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "ok"},
                                "finish_reason": None,
                            }
                        ],
                    }
                ),
                sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                sse(
                    {
                        **base,
                        "choices": [],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
                    }
                ),
                b"data: [DONE]\n\n",
            ]
        )
    if adapter_type is AnthropicAdapter:
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "ok"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
            {"type": "message_stop"},
        ]
        return b"".join(sse(event, named=True) for event in events)
    item = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "ok", "annotations": []}],
    }
    events = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "status": "in_progress", "content": []},
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": "ok",
        },
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {
            "type": "response.completed",
            "response": {
                "id": "resp_1",
                "object": "response",
                "created_at": 1,
                "model": "test-model",
                "status": "completed",
                "output": [item],
                "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
            },
        },
    ]
    return b"".join(sse({**event, "sequence_number": i}) for i, event in enumerate(events))


@pytest.mark.parametrize("adapter_type,sdk,path", PROTOCOLS)
def test_real_sdk_decoding_and_resource_path(monkeypatch, adapter_type, sdk, path):
    """SDK 解码结果满足同一源契约，URL 不产生 v1/v1。"""
    requests = []

    async def handler(request):
        """返回本地 SSE，不访问任何网络。"""
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=successful_wire(adapter_type),
        )

    install_transport(monkeypatch, sdk, handler)

    async def scenario():
        adapter = adapter_type(api_key="unit-test", base_url="https://unit.invalid/v1")
        try:
            chunks = await consume(adapter)
            text_chunks = [chunk for chunk in chunks if isinstance(chunk, TextDelta)]
            assert "".join(chunk.text for chunk in text_chunks) == "ok"
            if adapter_type is ResponsesAdapter:
                assert text_chunks[-1].text_parts == [{"output_index": 0, "phase": None, "text": "ok"}]
            else:
                assert text_chunks == [TextDelta("ok")]
            assert chunks[-1].finish_reason == "stop"
            assert chunks[-1].usage["prompt_tokens"] == 3
            assert chunks[-1].usage["completion_tokens"] == 1
            assert len([chunk for chunk in chunks if isinstance(chunk, Done)]) == 1
        finally:
            await close_adapter(adapter)

    asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0].url.path == path


@pytest.mark.parametrize("adapter_type,sdk,path", PROTOCOLS)
def test_real_sdk_rate_limit_has_one_request(monkeypatch, adapter_type, sdk, path):
    """真实 SDK 遇 429 也只调用一次，重试交给 Agent Loop。"""
    requests = []

    async def handler(request):
        """错误体带假密钥，验证规范错误不泄漏原文。"""
        requests.append(request)
        return httpx.Response(
            429, json={"error": {"type": "rate_limit_error", "message": "private-unit-secret"}}
        )

    install_transport(monkeypatch, sdk, handler)

    async def scenario():
        adapter = adapter_type(api_key="unit-test", base_url="https://unit.invalid/v1")
        try:
            with pytest.raises(LlmRequestError) as caught:
                await consume(adapter)
            assert caught.value.retryable
            assert caught.value.status_code == 429
            assert "private-unit-secret" not in str(caught.value)
            assert caught.value.__suppress_context__
        finally:
            await close_adapter(adapter)

    asyncio.run(scenario())
    assert len(requests) == 1


@pytest.mark.parametrize("adapter_type,sdk,path", PROTOCOLS)
def test_real_sdk_cancel_waiting_headers(monkeypatch, adapter_type, sdk, path):
    """SDK 尚未取得响应头时取消仍打断底层 await，无首 token 才检查的延迟。"""

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def handler(request):
            """模拟模型建连后尚未回应，取消时留下证明。"""
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        install_transport(monkeypatch, sdk, handler)
        adapter = adapter_type(api_key="unit-test", base_url="https://unit.invalid")
        try:
            task = asyncio.create_task(consume(adapter))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            assert cancelled.is_set()
        finally:
            await close_adapter(adapter)

    asyncio.run(scenario())


@pytest.mark.parametrize("adapter_type,sdk,path", PROTOCOLS)
def test_real_sdk_cancel_body_closes_http_stream(monkeypatch, adapter_type, sdk, path):
    """已经取得响应、首 token 尚未出现时也必须释放真实 HTTP 流。"""

    async def scenario():
        entered = asyncio.Event()

        class Body(httpx.AsyncByteStream):
            """只有取消才能结束的异步响应体。"""

            closed = False

            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield b""

            async def aclose(self):
                """HTTPX 与 SDK 的关闭链最终必须抵达这里。"""
                self.closed = True

        body = Body()

        async def handler(request):
            """立即返回头部，正文挂起。"""
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

        install_transport(monkeypatch, sdk, handler)
        adapter = adapter_type(api_key="unit-test", base_url="https://unit.invalid")
        try:
            task = asyncio.create_task(consume(adapter))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            assert body.closed
        finally:
            await close_adapter(adapter)

    asyncio.run(scenario())


@pytest.mark.parametrize("adapter_type,sdk,path", PROTOCOLS)
@pytest.mark.parametrize("phase_at", ["added", "done", "stream"])
def test_runtime_cancel_prefix_next_request_has_no_opaque_or_partial_tools(
    monkeypatch,
    adapter_type,
    sdk,
    path,
    phase_at,
):
    """真实 Runtime 与 SDK：取消留下正文，下一轮经严格本地 HTTP 接收端校验。"""

    class MemoryLog:
        """隔离真实 Runtime 所需的日志接口，允许本文件单独运行。"""

        session_id = "sdk-cancel-prefix"
        actor_id = None

        def __init__(self):
            self.events = []
            self.command_context = {}

        @property
        def next_seq(self):
            return len(self.events)

        def append(self, kind, data):
            event = {
                "seq": self.next_seq,
                "ts": float(self.next_seq),
                "type": kind,
                "data": deepcopy(data),
            }
            self.events.append(event)
            return deepcopy(event)

        def read(self):
            return deepcopy(self.events)

        def close(self):
            pass

    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from app.harness.memory.agent_messages import derive_messages

    if adapter_type is OpenAiAdapter:
        prefix = sse(
            {
                "id": "chat_1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "安全前缀",
                            "reasoning_content": "思考",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "partial",
                                    "type": "function",
                                    "function": {"name": "read", "arguments": '{"path":'},
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            }
        )
    elif adapter_type is AnthropicAdapter:
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 0},
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
                "delta": {"type": "thinking_delta", "thinking": "思考"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "opaque-signature"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "安全前缀"},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {"type": "tool_use", "id": "partial", "name": "read", "input": {}},
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
            },
        ]
        prefix = b"".join(sse(event, named=True) for event in events)
    else:
        reasoning = {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [{"type": "summary_text", "text": "思考"}],
            "encrypted_content": "opaque-encrypted",
        }
        message = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "phase": "commentary",
            "status": "completed",
            "content": [{"type": "output_text", "text": "安全前缀", "annotations": []}],
        }
        events = [
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "reasoning", "id": "rs_1", "summary": []},
            },
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": "思考",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {**message, "status": "in_progress", "content": [],
                         "phase": "commentary" if phase_at != "done" else None},
            },
            {
                "type": "response.output_text.delta",
                "output_index": 1,
                "content_index": 0,
                "item_id": "msg_1",
                "delta": "安全前缀",
            },
            {"type": "response.output_item.done", "output_index": 1, "item": message},
            {
                "type": "response.output_item.added",
                "output_index": 2,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "partial",
                    "name": "read",
                    "arguments": "",
                    "status": "in_progress",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 2,
                "item_id": "fc_1",
                "delta": '{"path":',
            },
        ]
        if phase_at == "stream":
            # 正文项尚未完成就取消，验证阶段直接由定位增量保存，而非依赖完成快照。
            events = [event for event in events
                      if not (event["type"] == "response.output_item.done" and event["output_index"] == 1)]
        prefix = b"".join(sse({**event, "sequence_number": i}) for i, event in enumerate(events))

    async def scenario():
        entered = asyncio.Event()
        requests = []

        class Body(httpx.AsyncByteStream):
            """部分状态已经闭合，但没有供应商 Done 的响应。"""

            closed = False

            async def __aiter__(self):
                """消费者取完所有前缀再进入可取消等待。"""
                yield prefix
                entered.set()
                await asyncio.Event().wait()

            async def aclose(self):
                """记录 HTTP 流关闭。"""
                self.closed = True

        body = Body()

        async def handler(http_request):
            """校验真实 SDK 发出的下一轮 JSON，不把 fake 成功当作云端验收。"""
            payload = json.loads(http_request.content)
            requests.append(payload)
            if len(requests) == 1:
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=body
                )
            history = payload["input" if adapter_type is ResponsesAdapter else "messages"]
            assert len(history) == 3
            assert history[0]["role"] == history[-1]["role"] == "user"
            assert history[1]["role"] == "assistant"
            encoded = json.dumps(history, ensure_ascii=False)
            for forbidden in (
                "opaque-signature",
                "opaque-encrypted",
                "protocol_state",
                "partial",
                "tool_calls",
                "tool_use",
                "function_call",
            ):
                assert forbidden not in encoded
            assert "安全前缀" in encoded
            if adapter_type is not OpenAiAdapter:
                assert "思考" not in encoded
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=successful_wire(adapter_type),
            )

        install_transport(monkeypatch, sdk, handler)
        adapter = adapter_type(api_key="unit-test", base_url="https://unit.invalid")
        template = LlmRequest("test-model", [], "", [], 64)
        graph = await build_agent(LoopSettings(), adapter=adapter, request=template)
        runtime = AgentRuntime(MemoryLog(), graph)
        try:
            await runtime.start_turn("第一轮")
            await asyncio.wait_for(entered.wait(), 2)
            assert await runtime.cancel()
            await runtime.wait()
            assert body.closed
            history = derive_messages(runtime.log.read())
            assert history[-1] == {
                "role": "assistant",
                "content": "安全前缀",
                "reasoning_content": "思考",
            }
            from app.agent.events import project_fact

            fact = next(event for event in runtime.log.read() if event["type"] == "assistant/message")
            expected_parts = ([{"output_index": 1, "phase": "commentary", "text": "安全前缀"}]
                              if adapter_type is ResponsesAdapter else None)
            assert fact["data"]["text_parts"] == expected_parts
            projected = project_fact({**fact, "session_id": "s"})[0]["data"]
            assert projected["text_parts"] == expected_parts
            assert "opaque" not in str(projected)
            await runtime.start_turn("下一轮")
            await runtime.wait()
            assert len(requests) == 2
            assert derive_messages(runtime.log.read())[-1]["content"] == "ok"
        finally:
            await runtime.close()
            await close_adapter(adapter)

    asyncio.run(scenario())
