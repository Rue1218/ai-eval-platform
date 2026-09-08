"""验证 Attempt 的原始参数、供应商状态和完成边界。"""

from copy import deepcopy
from dataclasses import asdict

import pytest

from app.agent.stream import AssistantAttempt
from app.harness.memory.agent_messages import derive_messages
from app.llm.loop_contracts import (
    Done,
    ProtocolState,
    ProviderItemDelta,
    ProviderItemEnd,
    ProviderItemStart,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
)


def test_fragments_preserve_raw_arguments_and_model_order():
    """身份晚于参数、交错正文和思考时仍保持模型声明顺序。"""
    attempt = AssistantAttempt()
    chunks = [
        ReasoningDelta("想"), TextDelta("答"),
        ToolCallDelta(1, '{"n":'), ToolCallStart(1, "b", "read"),
        ToolCallStart(0, "a", "read"), ToolCallDelta(0, "{}"),
        ToolCallDelta(1, "2}"), Done("tool_calls", {"prompt_tokens": 3}),
    ]
    assert [attempt.push(chunk) for chunk in chunks] == list(range(len(chunks)))
    assert attempt.identity_errors() == []
    assert attempt.message() == {
        "role": "assistant", "content": "答", "reasoning_content": "想",
        "tool_calls": [
            {"id": "a", "name": "read", "arguments_raw": "{}", "args": {}},
            {"id": "b", "name": "read", "arguments_raw": '{"n":2}', "args": {"n": 2}},
        ],
    }


@pytest.mark.parametrize("raw", ['{"path":', "[]", "null", '"text"'])
def test_invalid_arguments_are_retained_not_made_executable(raw):
    """坏 JSON 以及非对象 JSON 都保留调用，不补成可执行空对象。"""
    attempt = AssistantAttempt()
    attempt.push(ToolCallStart(0, "a", "read"))
    attempt.push(ToolCallDelta(0, raw))
    attempt.push(Done("tool_calls"))
    call = attempt.tool_calls[0]
    assert call["arguments_raw"] == raw
    assert "args" not in call
    assert call["parse_error"]
    assert attempt.identity_errors() == []
    assert attempt.incomplete_call_errors()


def test_provider_state_roundtrip_is_lossless_and_detached():
    """状态块与工具语义不重复，持久投影完整保留签名且不共用可变对象。"""
    item = {"type": "thinking", "thinking": "秘密推理", "signature": "signed"}
    state = ProtocolState(
        provider="anthropic", protocol="anthropic_messages", model="model",
        compatibility_key="profile:1", items=[item],
    )
    attempt = AssistantAttempt()
    attempt.push(ProviderItemStart("p", 0, "thinking"))
    attempt.push(ProviderItemDelta("p", "signature", "sig"))
    attempt.push(ProviderItemDelta("p", "signature", "ned"))
    attempt.push(ProviderItemEnd("p", item))
    attempt.push(TextDelta("公开回答"))
    attempt.push(Done("stop", protocol_state=state))
    assert attempt.protocol_errors() == []
    message = attempt.message()
    assert message["protocol_state"] == asdict(state)
    assert "tool_calls" not in message
    events = [{"seq": 1, "type": "assistant/message", "data": {"message": message}}]
    before = deepcopy(events)
    projected = derive_messages(events)
    projected[0]["protocol_state"]["items"][0]["signature"] = "changed"
    assert events == before
    assert state.items[0]["signature"] == "signed"


@pytest.mark.parametrize("case", ["open", "mismatch", "missing", "delta_before_start", "duplicate"])
def test_invalid_provider_state_fails_closed(case):
    """不完整、重复或与 Done 不一致的状态不得进入下一轮模型历史。"""
    attempt = AssistantAttempt()
    item = {"type": "reasoning", "encrypted_content": "opaque"}
    if case == "delta_before_start":
        attempt.push(ProviderItemDelta("p", "text", "bad"))
    attempt.push(ProviderItemStart("p", 0, "reasoning"))
    if case == "duplicate":
        attempt.push(ProviderItemStart("q", 0, "reasoning"))
    if case != "open":
        attempt.push(ProviderItemEnd("p", item))
    state = None if case == "missing" else ProtocolState(
        items=[] if case == "mismatch" else [item]
    )
    attempt.push(Done("stop", protocol_state=state))
    assert attempt.protocol_errors()


def test_changed_tool_identity_and_chunk_after_done_are_rejected():
    """供应商不得把同一下标换成另一调用，终止后也不得继续产出片段。"""
    attempt = AssistantAttempt()
    attempt.push(ToolCallStart(0, "a", "read"))
    attempt.push(ToolCallStart(0, "b", "write"))
    assert attempt.identity_errors()
    attempt.push(Done("tool_calls"))
    with pytest.raises(ValueError, match="after Done"):
        attempt.push(TextDelta("late"))
