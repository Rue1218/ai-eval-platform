"""摘要来源、原文证据和局部缓存回归；脚本输出仅验证机制，不证明模型语义保真。"""

import json
from collections import Counter
from copy import deepcopy

import pytest

from app.agent.compaction import EVIDENCE_BOUNDARY, ContextCompactor, _digest, _user_evidence
from app.agent.loop_wiring import _prompt_tokens
from app.errors import AppError, ErrorCode
from app.harness.context.meter import estimate_payload_tokens
from app.harness.memory.agent_messages import derive_messages
from app.llm.loop_contracts import Done, TextDelta
from tests.test_loop_compaction import capacity, conversation, request_factory, store_messages
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter


class CountingLog(MemoryLog):
    """计数完整事实读取，确保优化覆盖真实 log.read 边界。"""

    def __init__(self):
        """保留真实内存日志语义，只增加观测计数。"""
        super().__init__()
        self.reads = 0

    def read(self):
        """每次调用仍返回独立副本，防止测试依赖共享可变事实。"""
        self.reads += 1
        return super().read()


@pytest.mark.asyncio
@pytest.mark.parametrize("rounds", [1, 3, 10])
async def test_repeated_compaction_and_recovery_preserves_bounded_originals_and_source_ids(rounds):
    """跨真实日志追加与恢复多次合并，逐字证据、来源边界和新日志可见性均稳定。"""
    messages, log, build = conversation(), CountingLog(), request_factory()
    window = capacity(build, messages)
    previous_seq, previous_covered = None, 0
    for turn in range(rounds):
        if turn:
            messages.extend([
                {"role": "assistant", "content": "new verified evidence " * 340},
                {"role": "user", "content": f"更正：预算上限为{turn}元；只修改 target.py。"},
            ])
        store_messages(log, messages)
        original = deepcopy(log.events)
        # 故意让脚本摘要仍包含旧约束：确定性保证来自独立原文，不冒充模型理解能力。
        summary = "目标与约束：预算100元 [m:0]\n已验证事实：已读取 [m:1]\n未完成与失败：待继续\n来源：[m:0]"
        adapter = ScriptedAdapter([TextDelta(summary), Done("stop")])
        compact = ContextCompactor(log, adapter, build, _prompt_tokens, window)
        log.reads = 0

        result = await compact.prepare(messages)

        assert log.reads == 1
        assert len(adapter.requests) == 1
        saved = log.events[-1]
        data = saved["data"]
        assert saved["type"] == "context/compacted"
        assert data["previous_summary_seq"] == previous_seq
        assert data["source_ids"] == ["m:0", "m:1"]
        assert data["covered_messages"] == len(messages) - 1
        payload = json.loads(adapter.requests[0].messages[0]["content"])
        assert [item["source_id"] for item in payload["new_history"]] == [
            f"m:{index}" for index in range(previous_covered, data["covered_messages"])
        ]
        expected = [{"source_id": f"m:{index}", "content": item["content"]}
                    for index, item in enumerate(messages[:data["covered_messages"]])
                    if item["role"] == "user"][-3:]
        assert data["user_evidence"] == expected
        assert json.loads(result.system.split(EVIDENCE_BOUNDARY)[1]) == expected
        assert "后来的明确更正优先" in result.system
        assert "未列入不代表其他历史约束失效" in result.system
        assert data["input_tokens_after"] == _prompt_tokens(result)
        assert data["input_tokens_after"] <= window - result.max_tokens - 256
        assert log.events[:len(original)] == original
        assert derive_messages(log.events) == messages

        restored_adapter = ScriptedAdapter()
        restored = ContextCompactor(log, restored_adapter, build, _prompt_tokens, window)
        log.reads = 0
        assert await restored.prepare(messages) == result
        assert log.reads == 1 and restored_adapter.requests == []
        previous_seq, previous_covered = saved["seq"], data["covered_messages"]


@pytest.mark.asyncio
async def test_one_prepare_reuses_candidate_estimates_and_next_prepare_reads_new_facts():
    """相同候选只序列化估算一次，缓存不能把下一次新增用户和工具历史隐藏掉。"""
    messages, log, build = conversation(), CountingLog(), request_factory()
    store_messages(log, messages)
    estimates = Counter()

    def count_tokens(request):
        """用真实 wire 估算，并按完整正文和系统段辨别相同候选。"""
        key = json.dumps({"messages": request.messages, "system": request.system}, sort_keys=True)
        estimates[key] += 1
        return _prompt_tokens(request)

    adapter = ScriptedAdapter([TextDelta("事实已核实 [m:1]。"), Done("stop")],
                              [TextDelta("新增事实已核实 [m:3]。"), Done("stop")])
    compact = ContextCompactor(log, adapter, build, count_tokens, capacity(build, messages))
    log.reads = 0
    await compact.prepare(messages)
    assert log.reads == 1 and max(estimates.values()) == 1
    messages.extend([{"role": "assistant", "content": "new evidence " * 650},
                     {"role": "user", "content": "后来追加的原文必须可见"}])
    store_messages(log, messages)
    estimates.clear()
    log.reads = 0
    result = await compact.prepare(messages)
    assert log.reads == 1 and max(estimates.values()) == 1
    assert result.messages[-1] == messages[-1]
    assert "new evidence" in adapter.requests[-1].messages[0]["content"]
    estimates.clear()
    log.reads = 0
    assert compact.preflight(messages) == result
    assert log.reads == 1 and max(estimates.values()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["[m:-1]", "[m:02]", "[m:2]", "[m:999]", "[m:invalid]"])
@pytest.mark.parametrize("overflow", [False, True])
async def test_invalid_summary_reference_never_commits(reference, overflow):
    """不存在、未覆盖和非规范来源无法提交；原文可容纳则回退，否则标准预算错误。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    store_messages(log, messages)
    original = deepcopy(log.events)
    adapter = ScriptedAdapter([TextDelta(f"已验证事实 {reference}"), Done("stop")])
    compact = ContextCompactor(log, adapter, build, _prompt_tokens,
                               capacity(build, messages, overflow=overflow))
    if overflow:
        with pytest.raises(AppError) as error:
            await compact.prepare(messages)
        assert error.value.code == ErrorCode.BUDGET_EXCEEDED
    else:
        assert (await compact.prepare(messages)).messages == messages
    assert log.events[:len(original)] == original
    assert log.events[-1]["type"] == "context/compaction_failed"
    assert not any(event["type"] == "context/compacted" for event in log.events)


@pytest.mark.asyncio
async def test_literal_path_is_not_reference_and_oversized_user_original_is_not_truncated():
    """仅方括号来源参与验证；过大原文整条跳过，不能变成似是而非的截断约束。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    messages[0]["content"] = "完整用户原文必须整体保留或整体略过。" * 70
    store_messages(log, messages)
    adapter = ScriptedAdapter([TextDelta("文件 /tmp/m:999 与 m:0 是普通文本。已读取 [m:1]。"), Done("stop")])
    compact = ContextCompactor(log, adapter, build, _prompt_tokens, capacity(build, messages))
    result = await compact.prepare(messages)
    data = log.events[-1]["data"]
    assert estimate_payload_tokens(messages[0]["content"]) > 512
    assert data["source_ids"] == ["m:1"] and data["user_evidence"] == []
    assert EVIDENCE_BOUNDARY not in result.system
    assert messages[0]["content"] in adapter.requests[0].messages[0]["content"]


@pytest.mark.parametrize("field,value", [
    ("source_ids", ["m:999"]),
    ("user_evidence", [{"source_id": "m:0", "content": "篡改后的约束"}]),
    ("user_evidence", [{"source_id": "m:1", "content": "助手不是用户原文"}]),
])
def test_recovery_rejects_tampered_references_or_evidence(field, value):
    """已持久化的元信息也必须对应原始历史，不能靠摘要指纹绕过原文验证。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    store_messages(log, messages)
    log.append("context/compacted", {
        "version": 1, "summary": "历史事实 [m:1]", "covered_messages": 2,
        "source_fingerprint": _digest(messages[:2]), "source_ids": ["m:1"], "user_evidence": [],
        field: value,
    })
    compact = ContextCompactor(log, ScriptedAdapter(), build, _prompt_tokens, capacity(build, messages))
    with pytest.raises(AppError) as error:
        compact.preflight(messages)
    assert error.value.code == ErrorCode.VALIDATION


def test_legacy_summary_without_new_metadata_still_recovers_verbatim():
    """旧摘要没有来源与原文字段时沿用旧语义，不能从新约束倒推为非法事实。"""
    messages, log, build = conversation(), MemoryLog(), request_factory()
    store_messages(log, messages)
    summary = "旧格式中的 [m:999] 当时并非来源契约。"
    log.append("context/compacted", {"version": 1, "summary": summary, "covered_messages": 2,
                                     "source_fingerprint": _digest(messages[:2])})
    compact = ContextCompactor(log, ScriptedAdapter(), build, _prompt_tokens, capacity(build, messages))
    assert compact.preflight(messages) == build(messages[2:], summary)


@pytest.mark.parametrize("correction", [
    "更正：此前预算100元现已作废，采用新限制。" * 100,
    [{"type": "text", "text": "更正：预算从100元改为200元。"},
     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
])
def test_evidence_does_not_skip_newer_unrepresentable_correction_to_keep_old_rule(correction):
    """容量或多模态边界必须阻止回头强调过期约束，较新的短原文仍完整保留。"""
    source = [
        {"role": "user", "content": "预算100元。"},
        {"role": "assistant", "content": "收到"},
        {"role": "user", "content": correction},
        {"role": "assistant", "content": "收到更正"},
        {"role": "user", "content": "继续完成剩余工作"},
    ]
    assert _user_evidence(source, 3, 6000) == []
    assert _user_evidence(source, 5, 6000) == [
        {"source_id": "m:4", "content": "继续完成剩余工作"},
    ]
