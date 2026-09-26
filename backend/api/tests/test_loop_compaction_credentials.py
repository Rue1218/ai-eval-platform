"""压缩派生证据的凭据边界；测试值均为虚构，不改写原始会话事实。"""

import json
from copy import deepcopy

import pytest

from app.agent.compaction import EVIDENCE_BOUNDARY, ContextCompactor, _digest, _user_evidence
from app.agent.loop_wiring import _prompt_tokens
from app.errors import AppError, ErrorCode
from app.llm.loop_contracts import Done, TextDelta
from tests.test_loop_compaction import capacity, conversation, request_factory, store_messages
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter


@pytest.mark.parametrize("credential", [
    "sk-fictional123456", "Bearer fictional123456", "api_key=fictional-value",
    'password: "fictional value"', "-----BEGIN RSA PRIVATE KEY-----",
])
def test_sensitive_evidence_stops_before_older_constraints(credential):
    """不能略过包含敏感值的新更正，再把更旧要求当作优先证据。"""
    source = [{"role": "user", "content": "旧约束"},
              {"role": "user", "content": f"更正约束，同时提供 {credential}"},
              {"role": "user", "content": "后来补充的安全说明"}]
    assert _user_evidence(source, 2, 6000) == []
    assert _user_evidence(source, 3, 6000) == [{"source_id": "m:2", "content": source[2]["content"]}]


def test_security_words_without_credentials_remain_verbatim_evidence():
    """普通 token 预算和密码保护说明不能因关键词本身被丢弃。"""
    content = "token 预算为2048，password 字段不要放入日志。"
    assert _user_evidence([{"role": "user", "content": content}], 1, 6000) == [
        {"source_id": "m:0", "content": content},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
async def test_clean_summary_does_not_reintroduce_credential_through_evidence(protocol):
    """真实摘要与恢复路径不把含凭据的旧用户原文提升到系统资料段。"""
    credential = "sk-fictional123456"
    messages, log, build = conversation(), MemoryLog(), request_factory(protocol)
    messages[0]["content"] = f"只修改目标文件，临时凭据 {credential}"
    store_messages(log, messages)
    original = deepcopy(log.events)
    adapter = ScriptedAdapter([TextDelta("目标约束：只修改目标文件 [m:0]。"), Done("stop")])
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, capacity(build, messages))
    result = await compact.prepare(messages)
    saved = log.events[-1]
    assert saved["type"] == "context/compacted" and saved["data"]["user_evidence"] == []
    assert credential not in result.system and credential not in json.dumps(saved)
    assert log.events[:len(original)] == original
    restarted = ContextCompactor(log, ScriptedAdapter(), build, _prompt_tokens, compact.context_window)
    assert await restarted.prepare(messages) == result


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered", [False, True])
async def test_existing_evidence_is_verified_before_filtering_unsafe_prefix(tampered):
    """旧事实先验真再过滤；合法历史可继续使用，篡改不能借敏感过滤逃过验证。"""
    credential = "sk-fictional123456"
    messages = [{"role": "user", "content": "旧约束"},
                {"role": "assistant", "content": "已读取"},
                {"role": "user", "content": f"更正约束，临时凭据 {credential}"},
                {"role": "assistant", "content": "已处理"},
                {"role": "user", "content": "最新安全约束"},
                {"role": "assistant", "content": "已确认"},
                {"role": "user", "content": "继续"}]
    evidence = [{"source_id": f"m:{index}", "content": messages[index]["content"]} for index in (0, 2, 4)]
    if tampered:
        evidence[1]["content"] += "并非原文"
    log, build = MemoryLog(), request_factory()
    store_messages(log, messages)
    log.append("context/compacted", {
        "version": 1, "summary": "按最新约束执行 [m:4]。", "covered_messages": 6,
        "source_fingerprint": _digest(messages[:6]), "source_ids": ["m:4"],
        "user_evidence": evidence,
    })
    original = deepcopy(log.events)
    compact = ContextCompactor(log, ScriptedAdapter(), build, _prompt_tokens, 32768)
    if tampered:
        with pytest.raises(AppError) as caught:
            compact.preflight(messages)
        assert caught.value.code == ErrorCode.VALIDATION
    else:
        result = compact.preflight(messages)
        assert credential not in result.system
        assert json.loads(result.system.split(EVIDENCE_BOUNDARY)[1]) == [evidence[-1]]
        assert await compact.prepare(messages) == result
    assert log.events == original


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow", [False, True])
async def test_summary_credential_is_rejected_without_saving_candidate(overflow):
    """供应商输出已知凭据时沿用失败回退和用量记录，不持久化候选正文。"""
    credential = "sk-fictional123456"
    messages, log, build = conversation(), MemoryLog(), request_factory()
    store_messages(log, messages)
    adapter = ScriptedAdapter([TextDelta(f"读取配置，凭据 {credential} [m:1]"),
                               Done("stop", usage={"total_tokens": 42})])
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, capacity(build, messages, overflow=overflow))
    if overflow:
        with pytest.raises(AppError) as caught:
            await compact.prepare(messages)
        assert caught.value.code == ErrorCode.BUDGET_EXCEEDED
    else:
        assert (await compact.prepare(messages)).messages == messages
    saved = log.events[-1]
    assert saved["type"] == "context/compaction_failed" and saved["data"]["usage"]["total_tokens"] == 42
    assert credential not in json.dumps(log.events)
