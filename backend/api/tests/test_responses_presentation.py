"""Responses 摘要补齐、阶段投影和真实 AgentLoop 回放回归。"""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest
from shared.responses import ResponsesStream

from app.agent.events import project_fact
from app.agent.loop_presentation import tool_display
from app.llm.loop_contracts import LlmRequest, LlmRequestError
from app.llm.providers.anthropic import to_anthropic_messages
from app.llm.providers.common import make_state
from app.llm.providers.openai import to_openai_messages
from app.llm.providers.responses import to_responses_input
from tests.test_responses_protocol import completed, transport, wire


@pytest.mark.parametrize("phase", ["commentary", "final_answer"])
@pytest.mark.parametrize("item_id", [None, "msg", "responses-fallback-0"])
@pytest.mark.parametrize("completion", ["text", "item", "terminal"])
def test_verified_phase_survives_gateway_repair_and_replay(phase, item_id, completion):
    """空终态、终态漏字段及旧版无身份消息均保留阶段，且不修改输入快照。"""
    decoder = ResponsesStream()
    message = {"type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "正文", "annotations": []}]}
    if item_id is not None:
        message["id"] = item_id
    decoder.feed({"type": "response.output_item.added", "output_index": 0,
                  "item": {**message, "phase": phase, "content": []}})
    decoder.feed({"type": "response.output_text.delta", "delta": "正", "item_id": item_id})
    decoder.feed({"type": "response.output_text.done", "text": "正文", "item_id": item_id})
    if completion == "item":
        decoder.feed({"type": "response.output_item.done", "output_index": 0, "item": message})
    terminal = completed([message] if completion == "terminal" else [])
    original = deepcopy(terminal)
    decoder.feed({"type": "response.completed", "response": terminal})
    assert terminal == original
    assert decoder.response["output"][0]["phase"] == phase
    assert decoder.response["output"][0].get("id") == item_id
    request = LlmRequest("unit", [], "", [], 64, provider="newapi", protocol="openai_responses")
    state = make_state(request, "newapi", "openai_responses", decoder.response["output"])
    history = [{"role": "assistant", "content": "正文", "protocol_state": state}]
    replay = to_responses_input(replace(request, messages=history))
    assert replay[0]["phase"] == phase
    assert replay[0].get("id") == (item_id if item_id == "msg" else None)


@pytest.mark.parametrize("completion", ["item", "terminal"])
def test_conflicting_phase_remains_invalid(completion):
    """兼容遗漏不等于接受冲突阶段，必须在形成可执行结果之前拒绝。"""
    decoder = ResponsesStream()
    item = {"type": "message", "id": "msg", "role": "assistant", "content": []}
    decoder.feed({"type": "response.output_item.added", "output_index": 0,
                  "item": {**item, "phase": "commentary"}})
    changed = {**item, "phase": "final_answer"}
    event = ({"type": "response.output_item.done", "output_index": 0, "item": changed}
             if completion == "item" else {"type": "response.completed", "response": completed([changed])})
    with pytest.raises(ValueError, match="阶段"):
        decoder.feed(event)
    assert decoder.response is None


def test_terminal_can_declare_previously_unknown_phase():
    """item.done 的显式空阶段不阻止终态首次声明阶段。"""
    decoder = ResponsesStream()
    item = {**completed()["output"][0], "phase": None}
    decoder.feed({"type": "response.output_item.done", "output_index": 0, "item": item})
    decoder.feed({"type": "response.completed", "response": completed([{**item, "phase": "commentary"}])})
    assert decoder.response["output"][0]["phase"] == "commentary"
    assert decoder.display_text_parts()[0]["phase"] == "commentary"


def protocol_wire(request):
    """使用三种生产编码器检查状态隔离，而不是复制适配逻辑。"""
    if request.protocol == "openai_chat":
        return to_openai_messages(request.messages, "", request=request)
    if request.protocol == "anthropic_messages":
        return to_anthropic_messages(request.messages, request=request)
    return to_responses_input(request)


PROTOCOL_NAMES = ["openai_chat", "openai_responses", "anthropic_messages"]


@pytest.mark.parametrize("source", PROTOCOL_NAMES)
@pytest.mark.parametrize("target", PROTOCOL_NAMES)
def test_protocol_history_isolation_matrix(source, target):
    """全部六种跨协议方向都拒绝原始状态串用，展示分段不进入其他协议线格式。"""
    request = LlmRequest("unit", [], "", [], 64, provider="newapi", protocol=target)
    message = {"role": "assistant", "content": "正文", "text_parts": [
        {"output_index": 0, "phase": "commentary", "text": "正文"}]}
    plain_wire = protocol_wire(replace(request, messages=[message]))
    assert "text_parts" not in str(plain_wire) and "phase" not in str(plain_wire)
    if source == target:
        return
    message["protocol_state"] = make_state(request, "newapi", source, [{"type": "reasoning"}])
    with pytest.raises(LlmRequestError) as caught:
        protocol_wire(replace(request, messages=[message]))
    assert caught.value.code == "protocol_state_incompatible"
    from app.agent.loop_wiring import _drop_incompatible_protocol_state

    # 用户切换协议时，生产迁移只移除不透明状态，保留完整工具往返和公开正文。
    message["tool_calls"] = [{"id": "call", "name": "read", "args": {"path": "a"}}]
    tool_result = {"role": "tool", "tool_call_id": "call", "name": "read", "content": "工具结果"}
    migrated, dropped = _drop_incompatible_protocol_state(replace(request, messages=[message, tool_result]))
    assert dropped == [0] and "protocol_state" in message
    encoded = json.dumps(protocol_wire(migrated), ensure_ascii=False)
    assert "工具结果" in encoded and "call" in encoded and "正文" in encoded
    assert "protocol_state" not in encoded and "text_parts" not in encoded and "phase" not in encoded


def reasoning_item(text="标题\n\n完整摘要"):
    """包含公开摘要和不得展示的原始加密状态。"""
    return {"type": "reasoning", "id": "rs", "summary": [{"type": "summary_text", "text": text}],
            "encrypted_content": "PRIVATE_ENCRYPTED_STATE"}


def reasoning_event(kind, **kwargs):
    """生成同一公开摘要项的标准流事件。"""
    return {"type": f"response.reasoning_summary_{kind}", "output_index": 0,
            "summary_index": 0, "item_id": "rs", **kwargs}


@pytest.mark.parametrize("completion", ["text.done", "part.done", "item", "terminal"])
def test_reasoning_completion_recovers_suffix_once(completion):
    """只有标题增量时从各类完成快照补齐，重复完成不重复展示。"""
    decoder = ResponsesStream()
    output = decoder.feed(reasoning_event("text.delta", delta="标题"))
    item = reasoning_item()
    if completion in {"text.done", "part.done"}:
        fields = {"text": "标题\n\n完整摘要"} if completion == "text.done" else {"part": item["summary"][0]}
        event = reasoning_event(completion, **fields)
        output += decoder.feed(event)
        output += decoder.feed(event)
    if completion == "item":
        output += decoder.feed({"type": "response.output_item.done", "output_index": 0, "item": item})
    output += decoder.feed({"type": "response.completed", "response": completed([item])})
    assert "".join(part[1] for part in output) == "标题\n\n完整摘要"
    assert "PRIVATE" not in str(output)


@pytest.mark.parametrize("failure", ["conflict", "late", "identity", "negative", "type", "missing"])
def test_reasoning_rejects_damaged_completion(failure):
    """损坏公开摘要不能在工具可执行之前被静默接受。"""
    decoder = ResponsesStream()
    decoder.feed(reasoning_event("text.delta", delta="标题"))
    decoder.feed(reasoning_event("text.done", text="标题"))
    event = {
        "conflict": reasoning_event("text.done", text="不同摘要"),
        "late": reasoning_event("text.delta", delta="后缀"),
        "identity": reasoning_event("text.done", text="标题", item_id="other"),
        "negative": reasoning_event("text.done", text="标题", summary_index=-1),
        "type": reasoning_event("text.done", text={}),
        "missing": {"type": "response.completed", "response": completed([{**reasoning_item(), "summary": []}])},
    }[failure]
    with pytest.raises(ValueError):
        decoder.feed(event)


def test_multiple_reasoning_parts_and_snapshot_only():
    """无增量与多段摘要可从终态恢复，段落之间保留边界。"""
    item = reasoning_item("第一段")
    item["summary"].append({"type": "summary_text", "text": "第二段"})
    output = ResponsesStream().feed({"type": "response.completed", "response": completed([item])})
    assert output == [("reasoning", "第一段\n\n第二段")]


def test_agent_roundtrip_preserves_presentation_and_wire_state(monkeypatch):
    """真实 SDK/Agent 图完成工具后保存独立阶段，投影不泄露协议状态。"""
    from app.agent.loop import build_agent
    from app.agent.loop_settings import LoopSettings
    from app.agent.runtime import AgentRuntime
    from app.llm.contracts import ModelConfig
    from app.llm.loop_contracts import ToolSpec
    from app.llm.resolver import build_adapter, resolve_request
    from tests.test_loop_runtime import MemoryLog, RecordingScheduler

    call = {"type": "function_call", "id": "fc", "call_id": "call", "name": "read", "arguments": '{"path":"a"}'}
    messages = [{"type": "message", "id": f"msg{i}", "role": "assistant", "phase": phase,
                 "content": [{"type": "output_text", "text": text}]}
                for i, (phase, text) in enumerate([("commentary", "已核对工具结果。"), ("final_answer", "最终答案。")])]
    sent = []

    def handler(request):
        """先发工具，再用省略增量的多阶段完成快照收尾。"""
        sent.append(json.loads(request.content))
        items = [reasoning_item(), call] if len(sent) == 1 else messages
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=wire([{"type": "response.completed", "response": completed(items)}]))

    transport(monkeypatch, handler, True)
    config = ModelConfig("openai_responses", "https://unit.invalid", "unit", api_key="unit", reasoning_enabled=False)

    async def run():
        """执行与重放使用生产实现，工具只调度一次。"""
        adapter, _ = build_adapter(config)
        scheduler = RecordingScheduler()
        graph = await build_agent(LoopSettings(), adapter=adapter, scheduler=scheduler,
                                  request_factory=lambda history, effort: resolve_request(
                                      config, messages=history, tools=[ToolSpec("read", "读取", {"type": "object"})]))
        runtime = AgentRuntime(MemoryLog(), graph)
        try:
            await runtime.submit("读取", reasoning_effort="off")
            await runtime.wait()
            events = [event for event in runtime.log.read() if event["type"] == "assistant/message"]
            assert len(events) == 2 and len(scheduler.invocations) == 1
            assert events[0]["data"]["reasoning_content"] == "标题\n\n完整摘要"
            projected = project_fact({**events[1], "session_id": "s"})[0]["data"]
            assert projected["text_parts"] == [
                {"output_index": 0, "phase": "commentary", "text": "已核对工具结果。"},
                {"output_index": 1, "phase": "final_answer", "text": "最终答案。"},
            ]
            assert "PRIVATE" not in str(projected)
            await runtime.submit("继续", reasoning_effort="off")
            await runtime.wait()
            assert all(item in sent[2]["input"] for item in messages)
        finally:
            await runtime.close()
            await adapter.close()

    asyncio.run(run())


@pytest.mark.parametrize("status,synthetic,expected", [("succeeded", False, True), ("failed", False, False), ("succeeded", True, False)])
def test_write_download_path_only_from_success(status, synthetic, expected):
    """文件入口不读取模型正文或失败/合成回执中的路径。"""
    from app.harness.execution.dispatch import WriteResult

    result = WriteResult("reports/计划.md", 1, 1, "x", False).to_tool_data()
    display = tool_display({"name": "write", "status": status, "synthetic": synthetic,
                            "content": result["summary"], "display": result["display"]}, result=True)
    assert (display.get("file_path") == "reports/计划.md") is expected
