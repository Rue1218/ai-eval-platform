"""已完成长回合的分批摘要、完整工具组和持久恢复回归。"""

import json
from copy import deepcopy

import pytest

from app.agent.compaction import SUMMARY_BOUNDARY, ContextCompactor
from app.agent.loop import STEP_NOTICE_TOKEN_RESERVE, _history_selection
from app.agent.loop_wiring import _loop_system_segments, _prompt_tokens
from app.harness.memory.agent_messages import derive_messages
from app.llm.contracts import ModelConfig, SystemSegment
from app.llm.loop_contracts import Done, TextDelta, ToolSpec
from app.llm.providers.common import validate_messages
from app.llm.resolver import AuthorizedProfileSnapshot, resolve_request
from tests.test_loop_compaction import store_messages
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter


def _request_factory(protocol, max_tokens):
    """使用真实协议解析和平台系统提示，摘要与正式请求按相同 wire 估算。"""
    profile = AuthorizedProfileSnapshot(ModelConfig(
        protocol=protocol, base_url="https://example.test/v1",
        model="claude-sonnet-4-5" if protocol == "anthropic_messages" else "gpt-4o",
        api_key="test-only", max_tokens=max_tokens, reasoning_enabled=False,
    ))
    tools = [ToolSpec("read", "读取工作区文件", {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
    })]

    def build(messages, summary):
        """固定授权请求，仅把已提交摘要加入动态系统段。"""
        segments = _loop_system_segments("")
        if summary:
            segments += (SystemSegment(SUMMARY_BOUNDARY + summary, cacheable=False),)
        return resolve_request(profile, messages=messages, system_segments=segments, tools=tools)

    return build


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
async def test_long_final_report_can_be_compacted_in_batches_on_next_turn(protocol):
    """上一轮合法长回复使新轮超限时，分别摘要闭合工具组与报告后仍能继续。"""
    build, log = _request_factory(protocol, 12000), MemoryLog()
    messages = [
        {"role": "user", "content": "Read the file and write the report."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "read-a", "name": "read", "args": {"path": "a.txt"}},
        ]},
        {"role": "tool", "tool_call_id": "read-a", "name": "read",
         "content": "evidence " * 1500, "is_error": False},
        {"role": "assistant", "content": "report text " * 1900},
        {"role": "user", "content": "Continue."},
    ]
    original = deepcopy(messages)
    store_messages(log, messages)
    original_facts = log.read()
    budget = 20000 - 12000 - STEP_NOTICE_TOKEN_RESERVE
    assert _prompt_tokens(build(messages[:3], "")) < budget * .85
    assert _prompt_tokens(build(messages, "")) > budget
    adapter = ScriptedAdapter(
        [TextDelta("第一批：文件证据已经核实。"), Done("stop")],
        [TextDelta("完整记忆：证据已核实，报告已生成，等待继续。"), Done("stop")],
    )
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, 20000)

    result = await compact.prepare(messages)

    assert len(adapter.requests) == 2
    batches = [json.loads(request.messages[0]["content"]) for request in adapter.requests]
    assert [message for batch in batches for message in batch["new_history"]] == [
        {**message, "source_id": f"m:{index}"} for index, message in enumerate(original[:-1])
    ]
    assert batches[1]["previous_summary"] == "第一批：文件证据已经核实。"
    for batch in batches:
        validate_messages(batch["new_history"])
    assert result.messages == original[-1:]
    selection = _history_selection(original, result.messages)
    assert [original[index] for index in selection["indices"]] == result.messages
    assert _prompt_tokens(result) <= budget
    assert messages == original and derive_messages(log.read()) == original
    assert log.read()[:len(original_facts)] == original_facts
    saved = [event for event in log.read() if event["type"] == "context/compacted"]
    assert saved[1]["data"]["previous_summary_seq"] == saved[0]["seq"]
    assert saved[-1]["data"]["covered_messages"] == len(original) - 1
    replay_adapter = ScriptedAdapter()
    reopened = ContextCompactor(log, replay_adapter, build, _prompt_tokens, 20000)
    assert await reopened.prepare(derive_messages(log.read())) == result
    assert replay_adapter.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
async def test_smaller_window_batches_old_parallel_tool_groups_without_splitting_pairs(protocol):
    """较小窗口仍可分批处理旧回合；并行调用与结果整组保留且回放一致。"""
    build, log = _request_factory(protocol, 256), MemoryLog()
    messages = [{"role": "user", "content": "Read all four files and remember the facts."}]
    for group in range(2):
        calls = [{"id": f"{group}-{name}", "name": "read", "args": {"path": f"{group}-{name}.txt"}}
                 for name in ("a", "b")]
        messages.append({"role": "assistant", "content": "", "tool_calls": calls})
        messages.extend({"role": "tool", "tool_call_id": call["id"], "name": "read",
                         "content": "evidence " * 1200, "is_error": False} for call in calls)
    messages.append({"role": "assistant", "content": "All four files were read."})
    store_messages(log, messages)
    large_adapter = ScriptedAdapter()
    previous = ContextCompactor(log, large_adapter, build, _prompt_tokens, 20000)
    assert (await previous.prepare(messages)).messages == messages
    assert large_adapter.requests == []
    messages.append({"role": "user", "content": "Continue in the smaller model window."})
    store_messages(log, messages)
    original = deepcopy(messages)
    adapter = ScriptedAdapter([TextDelta("第一组两个文件已读取，继续处理剩余事实。"), Done("stop")])
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, 9000)

    result = await compact.prepare(messages)

    assert len(adapter.requests) == 1
    source = json.loads(adapter.requests[0].messages[0]["content"])["new_history"]
    assert [message["tool_call_id"] for message in source if message["role"] == "tool"] == ["0-a", "0-b"]
    assert [message["tool_call_id"] for message in result.messages if message["role"] == "tool"] == ["1-a", "1-b"]
    validate_messages(source)
    validate_messages(result.messages)
    assert result.messages[-1] == original[-1]
    selection = _history_selection(original, result.messages)
    assert [original[index] for index in selection["indices"]] == result.messages
    assert _prompt_tokens(result) <= 9000 - 256 - STEP_NOTICE_TOKEN_RESERVE
    assert messages == original and derive_messages(log.read()) == original
    replay_adapter = ScriptedAdapter()
    reopened = ContextCompactor(log, replay_adapter, build, _prompt_tokens, 9000)
    assert await reopened.prepare(derive_messages(log.read())) == result
    assert replay_adapter.requests == []
