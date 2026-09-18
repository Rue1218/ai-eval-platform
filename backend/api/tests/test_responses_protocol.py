"""Responses 从真实 SDK 到工具回填的回归契约（HTTP transport 本地替身）。"""

import asyncio
import json
from dataclasses import asdict, replace

import httpx
import openai
import pytest
from shared.model_urls import model_request_url
from shared.responses import ResponsesStream

from app.adapters import StreamAborted, call_protocol, stream_protocol
from app.errors import AppError
from app.llm.contracts import ModelConfig
from app.llm.loop_contracts import (
    Done,
    LlmRequestError,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    ToolSpec,
)
from app.llm.providers.responses import to_responses_input
from app.llm.resolver import build_adapter, resolve_request
from app.schemas import ProfileCreate, ProfileUpdate


def completed(output=None, status="completed"):
    """生成合法的最小完成快照，usage 含推理与缓存计费。"""
    return {"id": "resp_unit", "object": "response", "created_at": 1, "model": "unit-model",
            "status": status, "output": output if output is not None else [
                {"type": "message", "id": "msg_unit", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": "你好", "annotations": []}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                      "input_tokens_details": {"cached_tokens": 2},
                      "output_tokens_details": {"reasoning_tokens": 3}}}


def wire(events):
    """实际 SSE 字节经过 SDK 解析，避免仅验证字典替身。"""
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()


def text_events():
    """标准正文增量与终态。"""
    return [{"type": "response.output_text.delta", "delta": "你好", "output_index": 0,
             "content_index": 0, "item_id": "msg_unit", "sequence_number": 1},
            {"type": "response.completed", "response": completed(), "sequence_number": 2}]


@pytest.mark.parametrize("prefix", ["", "你", "你好"])
def test_terminal_snapshot_completes_text_once(prefix):
    """只含快照、部分增量和完整增量均还原相同正文，不重复追加。"""
    stream = ResponsesStream()
    events = stream.feed({"type": "response.output_text.delta", "delta": prefix}) if prefix else []
    events += stream.feed({"type": "response.completed", "response": completed()})
    assert "".join(event[1] for event in events if event[0] == "text") == "你好"


@pytest.mark.parametrize("output,prefix", [
    ([], "你好"),
    ([{"type": "message", "content": [{"type": "output_text", "text": "不同正文"}]}], "你好"),
    ([{"type": "message", "content": [{"type": "output_text", "text": "你"}]}], "你好"),
])
def test_terminal_snapshot_rejects_missing_or_conflicting_text(output, prefix):
    """终态删除、篡改或缩短已发正文时不得宣布成功。"""
    stream = ResponsesStream()
    stream.feed({"type": "response.output_text.delta", "delta": prefix})
    with pytest.raises(ValueError, match="正文"):
        stream.feed({"type": "response.completed", "response": completed(output)})
    assert stream.response is None


def test_empty_terminal_snapshot_rebuilds_verified_single_text():
    """兼容网关遗漏 output 时，仅以完成正文事件重建单一助手文本。"""
    stream = ResponsesStream()
    assert stream.feed({"type": "response.output_text.delta", "delta": "你", "item_id": "msg_gateway"}) == [("text", "你")]
    assert stream.feed({"type": "response.output_text.done", "text": "你好", "item_id": "msg_gateway"}) == []
    assert stream.feed({"type": "response.completed", "response": completed([])}) == [("text", "好")]
    assert stream.response["output"] == [{
        "id": "msg_gateway", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "你好", "annotations": []}],
    }]


def test_empty_terminal_snapshot_without_verified_done_remains_invalid():
    """不能只凭增量伪造终态，缺少完成正文时继续拒绝兼容网关响应。"""
    stream = ResponsesStream()
    stream.feed({"type": "response.output_text.delta", "delta": "你好"})
    with pytest.raises(ValueError, match="正文"):
        stream.feed({"type": "response.completed", "response": completed([])})


def test_empty_terminal_snapshot_never_rebuilds_tool_state():
    """工具调用必须以完成快照回放，文本完成事件不能越权补建工具状态。"""
    stream = ResponsesStream()
    stream.feed({"type": "response.output_item.added", "output_index": 0,
                 "item": {"type": "function_call", "call_id": "call_gateway", "name": "lookup"}})
    with pytest.raises(ValueError, match="工具"):
        stream.feed({"type": "response.completed", "response": completed([])})


def test_text_reconciliation_uses_content_indexes_and_refusals():
    """按内容索引独立核对拒绝文本，不能把后一个分块的文本挪到前面。"""
    output = [{"type": "message", "content": [
        {"type": "output_text", "text": "说明"}, {"type": "refusal", "refusal": "无法执行"},
    ]}]
    stream = ResponsesStream()
    stream.feed({"type": "response.output_text.delta", "delta": "说明", "content_index": 0})
    stream.feed({"type": "response.refusal.delta", "delta": "无法", "content_index": 1})
    assert stream.feed({"type": "response.completed", "response": completed(output)}) == [("text", "执行")]
    wrong_order = ResponsesStream()
    wrong_order.feed({"type": "response.refusal.delta", "delta": "无法", "content_index": 1})
    with pytest.raises(ValueError, match="顺序"):
        wrong_order.feed({"type": "response.completed", "response": completed(output)})


@pytest.mark.asyncio
async def test_sdk_partial_stream_matches_persisted_snapshot(monkeypatch):
    """实际 SDK 流完成后用户正文必须与持久回放快照一致。"""
    from app.agent.stream import AssistantAttempt
    from app.llm.resolver import close_adapter

    def handler(request):
        """本地传输模拟网关遗漏末尾正文增量。"""
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire([
            {"type": "response.output_text.delta", "delta": "你", "output_index": 0, "content_index": 0},
            {"type": "response.completed", "response": completed()},
        ]))

    transport(monkeypatch, handler, asynchronous=True)
    config = ModelConfig("openai_responses", "https://unit.invalid", "unit", api_key="fake", reasoning_enabled=False)
    adapter, _ = build_adapter(config)
    attempt = AssistantAttempt()
    try:
        async for chunk in adapter.stream(resolve_request(config, messages=[])):
            attempt.push(chunk)
        assert attempt.done.finish_reason == "stop"
        assert attempt.text == attempt.protocol_state["items"][0]["content"][0]["text"] == "你好"
    finally:
        await close_adapter(adapter)


@pytest.mark.asyncio
async def test_sdk_empty_terminal_snapshot_replays_verified_done_text(monkeypatch):
    """真实 SDK 收到兼容网关的空终态时，持久状态仍保留已核验正文。"""
    from app.agent.stream import AssistantAttempt
    from app.llm.resolver import close_adapter

    def handler(request):
        """模拟 New API 的正文完成事件存在、response.completed.output 为空。"""
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire([
            {"type": "response.output_text.delta", "delta": "你", "item_id": "msg_gateway", "output_index": 0, "content_index": 0},
            {"type": "response.output_text.done", "text": "你好", "item_id": "msg_gateway", "output_index": 0, "content_index": 0},
            {"type": "response.completed", "response": completed([])},
        ]))

    transport(monkeypatch, handler, asynchronous=True)
    config = ModelConfig("openai_responses", "https://unit.invalid", "unit", api_key="fake", reasoning_enabled=False)
    adapter, _ = build_adapter(config)
    attempt = AssistantAttempt()
    try:
        async for chunk in adapter.stream(resolve_request(config, messages=[])):
            attempt.push(chunk)
        assert attempt.done.finish_reason == "stop"
        assert attempt.text == attempt.protocol_state["items"][0]["content"][0]["text"] == "你好"
    finally:
        await close_adapter(adapter)


def transport(monkeypatch, handler, asynchronous=False):
    """保留完整 SDK 生命周期与 URL hook，只替换网络传输。"""
    name = "AsyncClient" if asynchronous else "Client"
    base = getattr(httpx, name)

    class LocalClient(base):
        """隔离上游网络并保留真实 HTTPX 类型。"""

        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, name, LocalClient)
    sdk_name = "AsyncOpenAI" if asynchronous else "OpenAI"
    sdk = getattr(openai, sdk_name)

    def local_sdk(**kwargs):
        """默认 SDK 使用已导入的 HTTPX 子类，因此显式注入测试传输。"""
        if "http_client" not in kwargs:
            kwargs["http_client"] = LocalClient()
        return sdk(**kwargs)

    monkeypatch.setattr(openai, sdk_name, local_sdk)


@pytest.mark.parametrize("base,expected", [
    ("https://unit.invalid", "https://unit.invalid/v1/responses"),
    ("https://unit.invalid/v1", "https://unit.invalid/v1/responses"),
    ("https://unit.invalid/v1/responses", "https://unit.invalid/v1/responses"),
    ("https://unit.invalid/api/v3", "https://unit.invalid/api/v3/responses"),
])
def test_responses_urls_and_schema(base, expected):
    """根、版本和完整资源地址不重复拼接，创建更新均接受新枚举。"""
    assert model_request_url(base, "openai_responses") == expected
    assert ProfileCreate(name="Responses", protocol="openai_responses", base_url=base, model="unit").protocol == "openai_responses"
    assert ProfileUpdate(protocol="openai_responses").protocol == "openai_responses"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("full_url", [False, True])
def test_sdk_request_usage_and_exact_url(monkeypatch, asynchronous, full_url):
    """同步和异步入口发送正确 input、输出预算和完整 URL，且归一真实用量。"""
    seen = []
    endpoint = "https://unit.invalid/custom/run/?region=cn" if full_url else "https://unit.invalid/v1"

    def handler(request):
        """捕获请求，不记录认证头。"""
        seen.append((str(request.url), json.loads(request.content)))
        if asynchronous:
            return httpx.Response(200, content=wire(text_events()), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=completed())

    transport(monkeypatch, handler, asynchronous)
    messages = [{"role": "user", "content": "你好"}]
    if asynchronous:
        async def run():
            """通过正式 resolver 及异步 SDK 完成一次调用。"""
            config = ModelConfig("openai_responses", endpoint, "unit-model", api_key="unit",
                                 reasoning_enabled=False, max_tokens=256, full_url=full_url)
            adapter, _ = build_adapter(config)
            try:
                return [event async for event in adapter.stream(resolve_request(config, messages=messages, system="简短回答"))]
            finally:
                await adapter.close()
        events = asyncio.run(run())
        assert [event.text for event in events if isinstance(event, TextDelta)] == ["你好"]
        result = events[-1]
        assert isinstance(result, Done) and result.finish_reason == "stop"
    else:
        result = call_protocol(protocol="openai_responses", base_url=endpoint, full_url=full_url,
                               model="unit-model", api_key="unit", messages=messages, system="简短回答", max_tokens=256)
        assert result.text == "你好"
    assert result.usage["prompt_tokens"] == 10
    assert result.usage["cached_tokens"] == 2
    assert result.usage["reasoning_tokens"] == 3
    url, body = seen[0]
    assert url == (endpoint if full_url else endpoint + "/responses")
    assert body["input"] == messages
    assert body["instructions"] == "简短回答"
    assert body["max_output_tokens"] == 256 and body["store"] is False
    assert "messages" not in body and "max_tokens" not in body


def test_tool_stream_and_encrypted_reasoning_replay(monkeypatch):
    """item.id 与 call_id 不同，碎片仅累积一次，下一轮保留原始 reasoning 项。"""
    call = {"type": "function_call", "id": "fc_item", "call_id": "call_wire", "name": "lookup",
            "arguments": '{"q":"中文"}', "status": "completed"}
    reasoning = {"type": "reasoning", "id": "rs_unit", "summary": [], "encrypted_content": "opaque"}
    events = [
        {"type": "response.output_item.added", "output_index": 1, "item": {**call, "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "item_id": "fc_item", "delta": '{"q":'},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "item_id": "fc_item", "delta": '"中文"}'},
        {"type": "response.output_item.done", "output_index": 1, "item": call},
        {"type": "response.completed", "response": completed([reasoning, call])},
    ]
    sent = []

    def handler(request):
        """返回带工具参数碎片的真实 SSE。"""
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=wire(events), headers={"content-type": "text/event-stream"})

    transport(monkeypatch, handler, True)
    config = ModelConfig("openai_responses", "https://unit.invalid/v1", "gpt-5.4", api_key="unit",
                         reasoning_enabled=True, reasoning_template_id="responses-reasoning-effort-v1")
    request = resolve_request(config, messages=[{"role": "user", "content": "查询"}],
                              tools=[ToolSpec("lookup", "查找", {"type": "object", "properties": {}})])

    async def run():
        """收集原生流并关闭 SDK。"""
        adapter, _ = build_adapter(config)
        try:
            return [event async for event in adapter.stream(request)]
        finally:
            await adapter.close()

    chunks = asyncio.run(run())
    assert [event.id for event in chunks if isinstance(event, ToolCallStart)] == ["call_wire"]
    assert "".join(event.arguments_fragment for event in chunks if isinstance(event, ToolCallDelta)) == call["arguments"]
    done = chunks[-1]
    assert done.finish_reason == "tool_calls"
    assert sent[0]["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert sent[0]["tools"][0]["name"] == "lookup" and "function" not in sent[0]["tools"][0]
    history = request.messages + [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_wire", "name": "lookup", "args": {"q": "中文"}}],
         "protocol_state": asdict(done.protocol_state)},
        {"role": "tool", "tool_call_id": "call_wire", "content": "结果"},
    ]
    replay = to_responses_input(replace(request, messages=history))
    assert replay[1:3] == [reasoning, call]
    assert replay[3] == {"type": "function_call_output", "call_id": "call_wire", "output": "结果"}
    with pytest.raises(LlmRequestError):
        to_responses_input(replace(request, messages=history, model="different", compatibility_key=None))


@pytest.mark.parametrize("events", [text_events()[:1], [{"type": "response.failed", "response": {"error": {"message": "secret"}}}]])
def test_sync_stream_failure_never_executes_tools(monkeypatch, events):
    """EOF 和失败事件均转为脱敏错误，不能伪装完成。"""
    transport(monkeypatch, lambda request: httpx.Response(200, content=wire(events), headers={"content-type": "text/event-stream"}))
    with pytest.raises(AppError) as error:
        list(stream_protocol(protocol="openai_responses", base_url="https://unit.invalid", model="unit", api_key="unit",
                             messages=[], reasoning_enabled=False))
    assert "secret" not in error.value.message


def test_images_invalid_arguments_and_cancellation(monkeypatch):
    """图片保留真实 URL；乱序工具和调用前取消不会产生网络请求。"""
    config = ModelConfig("openai_responses", "https://unit.invalid", "unit", api_key="unit", reasoning_enabled=False)
    request = resolve_request(config, messages=[{"role": "user", "content": [
        {"type": "text", "text": "图片"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}]}])
    assert to_responses_input(request)[0]["content"][1]["type"] == "input_image"
    with pytest.raises(ValueError):
        ResponsesStream().feed({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": "{}"})
    with pytest.raises(StreamAborted):
        list(stream_protocol(protocol="openai_responses", base_url="https://unit.invalid", model="unit", api_key="unit",
                             messages=[], should_abort=lambda: True))


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_sync_non_success_is_rejected(monkeypatch, status):
    """评测不能把失败或截断的 HTTP 200 响应记录为成功。"""
    transport(monkeypatch, lambda request: httpx.Response(200, json=completed(status=status)))
    with pytest.raises(AppError):
        call_protocol(protocol="openai_responses", base_url="https://unit.invalid", model="unit", api_key="unit", messages=[])


@pytest.mark.parametrize("call_count", [1, 2])
def test_responses_agent_tool_roundtrip_and_next_turn(monkeypatch, call_count):
    """真实 Agent 图执行工具，后续请求正确回填并在下一轮继续携带协议状态。"""
    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from tests.test_loop_runtime import MemoryLog, RecordingScheduler

    sent = []
    call = {"type": "function_call", "id": "fc_roundtrip", "call_id": "call_roundtrip",
            "name": "read", "arguments": '{"path":"a.txt"}', "status": "completed"}
    reasoning = {"type": "reasoning", "id": "rs_roundtrip", "summary": [], "encrypted_content": "opaque"}
    calls = [{**call, "id": f"fc_{index}", "call_id": f"call_{index}"} for index in range(call_count)]

    def handler(request):
        """首轮输出工具，之后正常回答；每次请求经过真实 SDK。"""
        sent.append(json.loads(request.content))
        events = ([{"type": "response.completed", "response": completed([reasoning, *calls])}]
                  if len(sent) == 1 else text_events())
        return httpx.Response(200, content=wire(events), headers={"content-type": "text/event-stream"})

    transport(monkeypatch, handler, True)
    config = ModelConfig("openai_responses", "https://unit.invalid/v1", "unit", api_key="unit", reasoning_enabled=False)
    specs = [ToolSpec("read", "读取", {"type": "object", "properties": {"path": {"type": "string"}}})]

    async def run():
        """按生产图接口发起两轮，检查工具只执行一次。"""
        adapter, _ = build_adapter(config)
        scheduler = RecordingScheduler()
        graph = await build_agent(LoopSettings(), adapter=adapter, scheduler=scheduler,
                                  request_factory=lambda messages, effort: resolve_request(config, messages=messages, tools=specs))
        runtime = AgentRuntime(MemoryLog(), graph)
        try:
            await runtime.submit("读取文件", reasoning_effort="off")
            await runtime.wait()
            assert runtime.log.read()[-1]["data"]["reason"] == "completed"
            assert len(scheduler.invocations) == 1 and len(sent) == 2
            assert sent[1]["input"][1:2 + call_count] == [reasoning, *calls]
            outputs = sent[1]["input"][2 + call_count:]
            assert [item["call_id"] for item in outputs] == [item["call_id"] for item in calls]
            assert all(item["type"] == "function_call_output" for item in outputs)
            await runtime.submit("继续", reasoning_effort="off")
            await runtime.wait()
            assert runtime.log.read()[-1]["data"]["reason"] == "completed"
            assert len(sent) == 3 and len(scheduler.invocations) == 1
            assert sent[2]["input"][1:2 + call_count] == [reasoning, *calls]
        finally:
            await runtime.close()
            await adapter.close()

    asyncio.run(run())


def test_self_hosted_vendor_templates_match_runtime():
    """New API 按网关协议推荐；Ollama 任意地址仍可用显式兼容模板。"""
    from app.llm.providers.options import request_options
    from app.llm.providers.reasoning_templates import list_templates

    assert list_templates("newapi", "openai_chat", "gpt-5.4")[0].id == "newapi-chat-effort-v1"
    assert list_templates("newapi", "openai_chat", "qwen3.6-flash")[0].id == "newapi-chat-effort-v1"
    template = list_templates("ollama", "openai_chat", "qwen3:8b")[0]
    assert template.id == "ollama-reasoning-effort-v1"
    config = ModelConfig("openai_chat", "http://private.invalid:8080/v1", "qwen3:8b", api_key="ollama",
                         reasoning_enabled=True, reasoning_template_id=template.id)
    request = resolve_request(config, messages=[])
    options = request_options(request, request.provider, request.protocol)
    assert options["reasoning_effort"] == "medium"
    assert "extra_body" not in options and options["max_tokens"] == config.max_tokens


@pytest.mark.parametrize("protocol,template_id,model,effort,expected", [
    ("openai_responses", "responses-reasoning-effort-v1", "o3", "max", "high"),
    ("openai_responses", "responses-reasoning-effort-v1", "gpt-5", "max", "high"),
    ("openai_responses", "responses-reasoning-effort-v1", "gpt-5.1", "max", "high"),
    ("openai_responses", "responses-reasoning-effort-v1", "gpt-5.1-codex-max", "max", "xhigh"),
    ("openai_responses", "responses-reasoning-effort-v1", "gpt-5.4", "max", "xhigh"),
    ("openai_chat", "openai-reasoning-effort-v1", "gpt-5.1", "max", "high"),
    ("openai_responses", "ollama-responses-effort-v1", "qwen3:8b", "max", "max"),
    ("openai_responses", "ollama-responses-effort-v1", "qwen3:8b", "off", "none"),
    ("openai_chat", "ollama-reasoning-effort-v1", "gpt-oss:20b", "high", "high"),
    ("openai_chat", "ollama-reasoning-effort-v1", "qwen3:8b", "max", "max"),
])
def test_vendor_effort_sdk_wire(monkeypatch, protocol, template_id, model, effort, expected):
    """思考档位通过真实 SDK 序列化；自建地址不误套模型原厂方言。"""
    from app.llm.providers.options import request_options

    sent = []

    def handler(request):
        """捕获请求体并提供无外网的合法完成响应。"""
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=wire(text_events()), headers={"content-type": "text/event-stream"})

    transport(monkeypatch, handler, True)
    config = ModelConfig(protocol, "http://private.invalid:8080/v1", model, api_key="unit",
                         reasoning_enabled=effort != "off", reasoning_effort=effort,
                         reasoning_template_id=template_id)
    request = resolve_request(config, messages=[])
    options = request_options(request, request.provider, protocol)

    async def run():
        """直接使用 SDK 发送已解析参数，隔离测试响应的协议差异。"""
        client = openai.AsyncOpenAI(api_key="unit", base_url=config.base_url)
        try:
            if protocol == "openai_responses":
                stream = await client.responses.create(model=model, input=[], stream=True, **options)
            else:
                stream = await client.chat.completions.create(model=model, messages=[], stream=True, **options)
            await stream.close()
        finally:
            await client.close()

    asyncio.run(run())
    body = sent[0]
    if protocol == "openai_responses":
        assert body["reasoning"]["effort"] == expected
        assert "reasoning_effort" not in body and "max_tokens" not in body
    else:
        assert body["reasoning_effort"] == expected
    assert "enable_thinking" not in body and "thinking_budget" not in body


@pytest.mark.parametrize("model,expected", [("o3", "high"), ("gpt-5.1", "high"), ("gpt-5.4", "xhigh")])
def test_sync_responses_max_effort_uses_model_mapping(monkeypatch, model, expected):
    """同步网关的最高档不能把平台 max 直接发送给 OpenAI。"""
    sent = []

    def handler(request):
        """捕获同步 SDK 最终参数。"""
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=completed())

    transport(monkeypatch, handler)
    call_protocol(protocol="openai_responses", base_url="https://unit.invalid", model=model, api_key="unit",
                  messages=[], reasoning_enabled=True, reasoning_effort="max")
    assert sent[0]["reasoning"]["effort"] == expected


def test_responses_interleaved_tools_keep_arguments_separate():
    """两个交错增量不会串参，最终快照也不会重复追加参数。"""
    decoder = ResponsesStream()
    calls = [{"type": "function_call", "id": f"fc_{index}", "call_id": f"call_{index}",
              "name": "read", "arguments": f'{{"path":"{index}.txt"}}'} for index in range(2)]
    emitted = []
    for index, call in enumerate(calls):
        emitted += decoder.feed({"type": "response.output_item.added", "output_index": index,
                                 "item": {**call, "arguments": ""}})
    for fragment in range(2):
        for index in (1, 0):
            arguments = calls[index]["arguments"]
            emitted += decoder.feed({"type": "response.function_call_arguments.delta", "output_index": index,
                                     "delta": arguments[:8] if fragment == 0 else arguments[8:]})
    emitted += decoder.feed({"type": "response.completed", "response": completed(calls)})
    for index, call in enumerate(calls):
        assert "".join(item[2] for item in emitted if item[:2] == ("tool_delta", index)) == call["arguments"]
    assert len([item for item in emitted if item[0] == "tool_start"]) == 2


@pytest.mark.parametrize("failure", ["eof", "failed", "incomplete", "duplicate_ids"])
def test_agent_never_dispatches_tools_from_invalid_responses(monkeypatch, failure):
    """真实 Agent 图只结算异常工具，断流、失败、截断、重复身份均不可调度执行。"""
    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from tests.test_loop_runtime import MemoryLog, RecordingScheduler

    call = {"type": "function_call", "id": "fc_bad", "call_id": "call_bad", "name": "read",
            "arguments": '{"path":"a.txt"}', "status": "completed"}
    events = [{"type": "response.output_item.added", "output_index": 0, "item": {**call, "arguments": ""}},
              {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": call["arguments"]}]
    if failure == "incomplete":
        events.append({"type": "response.incomplete", "response": {
            **completed([call], status="incomplete"), "incomplete_details": {"reason": "max_output_tokens"}}})
    elif failure == "failed":
        events.append({"type": "response.failed", "response": completed(status="failed")})
    elif failure == "duplicate_ids":
        events.append({"type": "response.completed", "response": completed([call, {**call, "id": "fc_other"}])})
    transport(monkeypatch, lambda request: httpx.Response(200, content=wire(events),
              headers={"content-type": "text/event-stream"}), True)
    config = ModelConfig("openai_responses", "https://unit.invalid/v1", "unit", api_key="unit", reasoning_enabled=False)

    async def run():
        """运行到终态，允许生成拒绝执行的工具回执但不允许实际执行。"""
        adapter, _ = build_adapter(config)
        scheduler = RecordingScheduler()
        graph = await build_agent(LoopSettings(), adapter=adapter, scheduler=scheduler,
                                  request_factory=lambda messages, effort: resolve_request(config, messages=messages))
        runtime = AgentRuntime(MemoryLog(), graph)
        try:
            await runtime.submit("读取", reasoning_effort="off")
            await runtime.wait()
            assert all(not invocation["allow_dispatch"] for invocation in scheduler.invocations)
            assert runtime.log.read()[-1]["type"] == "turn/end"
        finally:
            await runtime.close()
            await adapter.close()

    asyncio.run(run())


def test_ollama_responses_template_and_openai_probe_version():
    """Ollama Responses 优先本服务模板；变更后的 OpenAI 模板要求重新验证。"""
    from app.llm.providers.reasoning_templates import list_templates
    from app.profile_reasoning import profile_reasoning

    assert list_templates("ollama", "openai_responses", "gpt-oss:20b")[0].id == "ollama-responses-effort-v1"
    result = profile_reasoning("openai_responses", "https://unit.invalid", "gpt-5.4", 8192,
        reasoning_template_id="responses-reasoning-effort-v1", reasoning_probe={
            "status": "passed", "template_id": "responses-reasoning-effort-v1",
            "template_version": 2, "supported_efforts": ["max"]})
    assert result["allowed_efforts"] == []
