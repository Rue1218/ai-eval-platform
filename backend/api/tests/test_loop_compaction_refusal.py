"""真实 Responses SDK 拒绝响应不能推进会话摘要的持久覆盖边界。"""

from copy import deepcopy

import httpx
import pytest

from app.errors import AppError, ErrorCode
from app.harness.memory.agent_messages import derive_messages
from app.llm.providers.responses import ResponsesAdapter
from tests.test_loop_compaction import compactor, conversation, request_factory
from tests.test_loop_runtime import MemoryLog
from tests.test_responses_protocol import completed, transport, wire


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow", [False, True], ids=["fallback", "over-budget"])
@pytest.mark.parametrize("mixed", [False, True], ids=["refusal-only", "text-and-refusal"])
async def test_structured_refusal_never_advances_compaction_boundary(monkeypatch, overflow, mixed):
    """供应商明确拒绝时保留原始事实；可容纳则回退，超限则返回标准预算错误。"""
    refusal = "I cannot provide a summary of that content."
    content = [{"type": "output_text", "text": "Partial summary.", "annotations": []}] if mixed else []
    content.append({"type": "refusal", "refusal": refusal})
    response = completed([{
        "type": "message", "id": "msg_refusal", "role": "assistant", "status": "completed",
        "content": content,
    }])
    calls = []

    def handler(request):
        """只捕获无凭据的请求地址；SSE 仍经真实 SDK 与协议适配器解码。"""
        calls.append(str(request.url))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=wire([{"type": "response.completed", "response": response, "sequence_number": 1}]),
        )

    transport(monkeypatch, handler, asynchronous=True)
    adapter = ResponsesAdapter(api_key="test-only", base_url="https://example.test/v1")
    messages, log, build = conversation(), MemoryLog(), request_factory("openai_responses")
    original_messages = deepcopy(messages)
    compact = compactor(log, adapter, build, messages, overflow=overflow)
    original_events = log.read()
    try:
        if overflow:
            with pytest.raises(AppError) as error:
                await compact.prepare(messages)
            assert error.value.code == ErrorCode.BUDGET_EXCEEDED
        else:
            selected = await compact.prepare(messages)
            assert selected == build(original_messages, "")
            assert await compact.prepare(messages) == selected
    finally:
        await adapter.close()

    assert calls == ["https://example.test/v1/responses"]
    assert messages == original_messages
    assert derive_messages(log.read()) == original_messages
    assert log.read()[:len(original_events)] == original_events
    assert not any(event["type"] == "context/compacted" for event in log.read())
    failures = [event for event in log.read() if event["type"] == "context/compaction_failed"]
    assert len(failures) == 1
    assert failures[0]["data"]["usage"]["prompt_tokens"] == 10
    assert failures[0]["data"]["usage"]["completion_tokens"] == 5
    assert refusal not in str(failures)
