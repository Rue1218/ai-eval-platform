"""真实隔离 PG 的摘要恢复与会话边界回归；仅使用显式测试数据库。"""

from __future__ import annotations

import json
from copy import deepcopy

from sqlalchemy import select

from app.agent.compaction import SUMMARY_BOUNDARY, ContextCompactor, _digest
from app.agent.events import trace_frame
from app.agent.loop_wiring import _prompt_tokens
from app.harness.memory.agent_events import SessionLog
from app.harness.memory.agent_messages import derive_messages
from app.llm.contracts import SystemSegment
from app.llm.loop_contracts import LlmRequest
from app.models import Message
from tests import test_loop_store_pg as store_fixtures
from tests.test_loop_runtime import ScriptedAdapter

pg_case = store_fixtures.pg_case


def _request(messages, summary):
    """按真实 Chat 序列化估算，摘要仅放入不可缓存的系统补充段。"""
    segments = (SystemSegment("平台系统提示"),)
    if summary:
        segments += (SystemSegment(SUMMARY_BOUNDARY + summary, cacheable=False),)
    return LlmRequest(
        model="test-model", messages=deepcopy(messages),
        system="\n\n".join(segment.text for segment in segments), system_segments=segments,
        tools=[], max_tokens=128, provider="openai", protocol="openai_chat",
        reasoning_effort="off",
    )


def _seed_history(log):
    """写入两轮原始消息，摘要仅覆盖首个已完成回合。"""
    log.append("user/message", {"turn": 1, "content": "首轮原始要求：保留全部明细。"})
    log.append("assistant/message", {
        "turn": 1, "step": 1, "attempt_id": "first-answer",
        "message": {"role": "assistant", "content": "首轮原始结果：明细已经核对。"},
    })
    log.append("user/message", {"turn": 2, "content": "请继续完成剩余事项。"})
    return derive_messages(log.read())


def _save_summary(log, messages, summary):
    """通过真实 SessionLog 事务保存摘要事实及对应公开通知。"""
    return log.append("context/compacted", {
        "version": 1, "reason": "summary", "summary": summary,
        "covered_messages": 2, "source_fingerprint": _digest(messages[:2]),
        "previous_summary_seq": None, "history_upto_seq": log.read()[-1]["seq"],
        "dropped": 2, "kept": 1, "in_scope_total": 3, "limit": 100000,
        "input_tokens_before": 1000, "input_tokens_after": 100,
        "model": "test-model", "profile_id": None,
        "usage": {"prompt_tokens": 900, "completion_tokens": 50},
    })


def test_pg_compaction_restores_after_reopen_without_rewriting_or_exposing_summary(pg_case):
    """新日志句柄恢复真实摘要；事实/REST 原文不变，公开流与轨迹不泄露摘要。"""
    session_id = pg_case.session()
    summary = "private-summary-marker：保留明细，首轮核对已完成，剩余事项待处理。"
    with pg_case.log(session_id) as log:
        messages = _seed_history(log)
        originals = log.read()
        saved = _save_summary(log, messages, summary)

    reopened = SessionLog(session_id, pg_case.factory, actor_id=pg_case.user_id)
    try:
        facts = reopened.read()
        assert facts[:len(originals)] == originals
        assert facts[-1] == saved
        assert derive_messages(facts) == messages
        adapter = ScriptedAdapter()
        compactor = ContextCompactor(reopened, adapter, _request, _prompt_tokens, 100000)
        request = compactor.preflight(derive_messages(facts))
        assert request.messages == messages[2:]
        assert request.system_segments[-1] == SystemSegment(
            SUMMARY_BOUNDARY + summary, cacheable=False,
        )
        assert adapter.requests == [] and reopened.read() == facts

        with pg_case.factory() as db:
            rows = db.scalars(select(Message).where(Message.session_id == session_id)).all()
            assert sorted(row.content for row in rows) == sorted(item["content"] for item in messages)
        frames = reopened.stream()
        notices = [frame for frame in frames if frame["type"] == "context.trimmed"]
        assert len(notices) == 1
        assert notices[0]["data"] == {
            "reason": "summary", "dropped": 2, "kept": 1,
            "in_scope_total": 3, "limit": 100000,
        }
        assert summary not in json.dumps(frames, ensure_ascii=False)
        trace = trace_frame(saved, session_id, source="history")
        assert "summary" not in trace["data"]["event"]["data"]
        assert summary not in json.dumps(trace, ensure_ascii=False)
    finally:
        reopened.close()


def test_pg_compaction_does_not_cross_session_even_when_source_history_matches(pg_case):
    """相同成员和相同原文也不能使一个会话读取另一个会话的摘要。"""
    first_id, second_id = pg_case.session(), pg_case.session()
    summary = "仅属于第一个会话的摘要。"
    with pg_case.log(first_id) as first:
        first_messages = _seed_history(first)
        _save_summary(first, first_messages, summary)
    with pg_case.log(second_id) as second:
        second_messages = _seed_history(second)
    assert first_messages == second_messages

    first = SessionLog(first_id, pg_case.factory, actor_id=pg_case.user_id)
    second = SessionLog(second_id, pg_case.factory, actor_id=pg_case.user_id)
    try:
        first_request = ContextCompactor(
            first, ScriptedAdapter(), _request, _prompt_tokens, 100000,
        ).preflight(derive_messages(first.read()))
        second_request = ContextCompactor(
            second, ScriptedAdapter(), _request, _prompt_tokens, 100000,
        ).preflight(derive_messages(second.read()))
        assert summary in first_request.system and first_request.messages == first_messages[2:]
        assert second_request.messages == second_messages
        assert second_request.system_segments == (SystemSegment("平台系统提示"),)
        assert not any(event["type"] == "context/compacted" for event in second.read())
        assert not any(frame["type"] == "context.trimmed" for frame in second.stream())
    finally:
        first.close()
        second.close()
