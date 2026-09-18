"""Responses 摘要补齐、阶段投影和真实 AgentLoop 回放回归。"""

import asyncio
import json

import httpx
import pytest
from shared.responses import ResponsesStream

from app.agent.events import project_fact
from app.agent.loop_presentation import tool_display
from tests.test_responses_protocol import completed, transport, wire


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
