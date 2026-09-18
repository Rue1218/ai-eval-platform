"""兼容网关遗漏终态 output 时，用真实 SDK 验证已完成工具项的往返与拒绝边界。"""

import asyncio
import json

import httpx
import pytest
from shared.responses import ResponsesStream

from app import profile_tool_probe
from app.llm.contracts import ModelConfig
from tests.test_loop_llm_sdk import install_transport
from tests.test_responses_protocol import completed, wire


def tool_item(index=0):
    """生成有独立身份、完整参数的无副作用测试调用。"""
    return {"id": f"fc_{index}", "type": "function_call", "call_id": f"call_{index}",
            "name": "profile_probe_echo", "arguments": '{"token":"request-token"}', "status": "completed"}


def done_items(items):
    """完成事件携带原始项，终态刻意模拟网关空数组。"""
    return [{"type": "response.output_item.done", "output_index": index, "item": item}
            for index, item in enumerate(items)] + [{"type": "response.completed", "response": completed([])}]


@pytest.mark.parametrize("reasoning", [False, True])
def test_gateway_tool_probe_roundtrip_with_empty_terminal(monkeypatch, reasoning):
    """工具调用和回填后文本都缺失终态 output 时，仍须完整往返才算通过。"""
    sent = []
    monkeypatch.setattr(profile_tool_probe.secrets, "token_hex", lambda size: "request-token" if size == 8 else "result-token")
    thought = {"type": "reasoning", "id": "rs_probe", "summary": [], "encrypted_content": "opaque"}
    items = ([thought] if reasoning else []) + [tool_item()]

    def handler(request):
        """验证实际 SDK 请求原样回放工具身份与加密项，不模拟模型自称支持。"""
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) == 1:
            assert body["tools"][0]["name"] == "profile_probe_echo"
            content = wire(done_items(items))
        else:
            assert body["input"][1:-1] == items
            assert body["input"][-1] == {"type": "function_call_output", "call_id": "call_0", "output": "result-token"}
            message = {"type": "message", "id": "msg_answer", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "result-token", "annotations": []}]}
            content = wire([{"type": "response.output_text.done", "output_index": int(reasoning),
                              "content_index": 0, "item_id": "msg_answer", "text": "result-token"}]
                           + done_items(([thought] if reasoning else []) + [message]))
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    install_transport(monkeypatch, "openai", handler)
    config = ModelConfig("openai_responses", "https://unit.invalid/v1", "unit", api_key="fake",
                         reasoning_enabled=False, reasoning_template_id="newapi-responses-effort-v1")
    assert asyncio.run(profile_tool_probe.probe_tool_roundtrip(config))["status"] == "passed"
    assert len(sent) == 2


def test_gateway_interleaved_completed_tools_keep_exact_arguments():
    """多个交错调用的参数完成事件与输出项一致，终态不重复发射参数。"""
    stream = ResponsesStream()
    items = [tool_item(i) for i in range(2)]
    events = []
    for i, item in enumerate(items):
        events += stream.feed({"type": "response.output_item.added", "output_index": i,
                               "item": {**item, "status": "in_progress", "arguments": ""}})
    for i in (1, 0):
        item = items[i]
        events += stream.feed({"type": "response.function_call_arguments.delta", "output_index": i, "delta": item["arguments"][:5]})
        events += stream.feed({"type": "response.function_call_arguments.done", "output_index": i,
                               "item_id": item["id"], "arguments": item["arguments"]})
        events += stream.feed({"type": "response.output_item.done", "output_index": i, "item": item})
    events += stream.feed({"type": "response.completed", "response": completed([])})
    assert stream.response["output"] == items
    for i, item in enumerate(items):
        assert "".join(event[2] for event in events if event[:2] == ("tool_delta", i)) == item["arguments"]


@pytest.mark.parametrize("failure", [
    "missing_done", "gap", "incomplete_item", "bad_json", "non_object", "missing_id",
    "missing_call_id", "duplicate_call_id", "missing_reasoning", "unreplayable_reasoning",
    "unknown_item", "args_done_conflict", "duplicate_args_done", "late_args", "nonempty_conflict",
])
def test_gateway_incomplete_or_conflicting_tools_never_complete(failure):
    """身份、参数或完成证据任一缺失时不生成成功终态，拒绝不完整工具回放。"""
    item = tool_item()
    events = []
    terminal = {"type": "response.completed", "response": completed([])}
    if failure in {"missing_done", "args_done_conflict", "duplicate_args_done", "late_args"}:
        events.append({"type": "response.output_item.added", "output_index": 0,
                       "item": {**item, "arguments": "", "status": "in_progress"}})
        events.append({"type": "response.function_call_arguments.done", "output_index": 0,
                       "item_id": item["id"], "arguments": item["arguments"]})
        if failure == "args_done_conflict":
            events.append({"type": "response.output_item.done", "output_index": 0, "item": {**item, "arguments": '{}'}})
        elif failure == "duplicate_args_done":
            events.append({**events[-1], "arguments": '{}'})
        elif failure == "late_args":
            events.append({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": ' '})
    else:
        if failure == "incomplete_item":
            item["status"] = "in_progress"
        elif failure in {"bad_json", "non_object"}:
            item["arguments"] = '{' if failure == "bad_json" else '[]'
        elif failure in {"missing_id", "missing_call_id"}:
            item.pop("id" if failure == "missing_id" else "call_id")
        events.append({"type": "response.output_item.done", "output_index": 1 if failure == "gap" else 0, "item": item})
        if failure == "duplicate_call_id":
            events.append({"type": "response.output_item.done", "output_index": 1, "item": {**item, "id": "fc_other"}})
        elif failure in {"missing_reasoning", "unreplayable_reasoning", "unknown_item"}:
            events.append({"type": "response.output_item.added" if failure == "missing_reasoning" else "response.output_item.done",
                           "output_index": 1, "item": {"type": "web_search_call" if failure == "unknown_item" else "reasoning",
                                                       "id": "rs_missing", "summary": []}})
        elif failure == "nonempty_conflict":
            terminal["response"]["output"] = [{**item, "arguments": '{}'}]
    stream = ResponsesStream()
    with pytest.raises(ValueError):
        for event in [*events, terminal]:
            stream.feed(event)
    assert stream.response is None
