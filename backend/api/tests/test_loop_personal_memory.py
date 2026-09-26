"""个人长期记忆的逐请求召回、隐私标记事务、失效刷新和真实输入预算回归。"""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.agent import loop_wiring
from app.agent.compaction import ContextCompactor
from app.agent.loop_presentation import request_summary
from app.errors import AppError, ErrorCode
from app.harness.memory import preference
from app.harness.memory.preference import prepare_private_memories, prepare_private_prefs
from app.llm.contracts import SystemSegment
from app.llm.loop_contracts import Done, TextDelta
from app.models import AuditLog
from tests import test_loop_wiring as wiring_fixtures
from tests.test_loop_compaction import conversation, store_messages
from tests.test_loop_preferences import _prefs_db

wired = wiring_fixtures.wired


def _memory(content="请使用简洁中文", *, version=1, workspace_id=None):
    """完整公开快照，召回选择和条数/token上限由个人存储模块单独验证。"""
    return {"id": "memory-a", "title": "回答风格", "content": content, "category": "preference",
            "workspace_id": workspace_id, "workspace_name": "当前项目" if workspace_id else None,
            "version": version, "source_id": "manual:memory-a",
            "created_at": "2026-09-26T00:00:00Z", "updated_at": "2026-09-26T00:00:00Z"}


def _mock_recall(monkeypatch, **kwargs):
    """只替换存储查询接缝，运行真实本人私有范围及审计流程。"""
    from app.harness.memory import personal

    recall = Mock(**kwargs)
    monkeypatch.setattr(personal, "recall_personal_memories", recall)
    return recall


def test_private_recall_uses_locked_current_workspace_and_marks_before_commit(monkeypatch):
    """所属工作区从锁内会话取得，调用者无法指定其他范围；标记没有个人正文。"""
    case = _prefs_db()
    case.session.workspace_id = "current-workspace"

    def recall(db, user_id, workspace_id, query):
        """读取发生前必须已经取得会话锁及成员身份。"""
        assert (db, user_id, workspace_id, query) == (case.db, "actor", "current-workspace", "测试相关事实")
        case.session_query.populate_existing.assert_called_once()
        case.session_query.with_for_update.assert_called_once()
        return [_memory("PRIVATE_CONTENT", workspace_id=workspace_id)]

    _mock_recall(monkeypatch, side_effect=recall)
    memories = prepare_private_memories(case.db, "session", "actor", "测试相关事实")
    assert memories[0]["content"] == "PRIVATE_CONTENT"
    marker = case.db.add.call_args.args[0]
    assert marker.action == "session_personal_context_used" and marker.target_id == "session"
    assert marker.detail == {"source": "personal_memories"}
    assert "PRIVATE_CONTENT" not in json.dumps(marker.detail)
    case.db.commit.assert_not_called()


@pytest.mark.parametrize("restriction", ["team", "owner", "disabled", "missing"])
def test_personal_recall_never_queries_storage_outside_owner_private_scope(monkeypatch, restriction):
    """权限不满足时不读取个人存储，也不能留下使用标记。"""
    case = _prefs_db()
    if restriction == "team":
        case.session.visibility = "team"
    elif restriction == "owner":
        case.session.user_id = "other"
    elif restriction == "disabled":
        case.user.disabled = True
    else:
        case.session_query.first.return_value = None
    recall = _mock_recall(monkeypatch, side_effect=AssertionError("不得读取个人记录"))
    assert prepare_private_memories(case.db, "session", "actor", "query") == []
    recall.assert_not_called()
    case.db.add.assert_not_called()


def test_empty_recall_does_not_mark_and_both_personal_sources_share_one_pending_marker(monkeypatch):
    """SessionLocal关闭autoflush时，偏好与长期记忆在同事务也只能新增一个隐私标记。"""
    case = _prefs_db({"last_kind": "rag"})
    recall = _mock_recall(monkeypatch, return_value=[])
    assert prepare_private_memories(case.db, "session", "actor", "query") == []
    case.db.add.assert_not_called()
    case.db.new = []
    case.db.add.side_effect = case.db.new.append
    assert prepare_private_prefs(case.db, "session", "actor") == {"last_kind": "rag"}
    recall.return_value = [_memory()]
    assert prepare_private_memories(case.db, "session", "actor", "query") == [_memory()]
    assert len(case.db.new) == 1 and isinstance(case.db.new[0], AuditLog)
    case.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_wiring_updates_and_deletes_memory_without_reusing_previous_request(wired, monkeypatch):
    """同一回合工具之后和下一轮都按最新用户文本重新召回，不复用旧版本或已删除条目。"""
    case = _prefs_db()
    case.session.workspace_id = "workspace-live"
    records = [_memory("OLD_STYLE", workspace_id="workspace-live")]
    queries = []

    def recall(db, user_id, workspace_id, query):
        """每次返回独立版本，避免测试借共享对象掩盖缓存失效。"""
        assert (db, user_id, workspace_id) == (case.db, "actor", "workspace-live")
        queries.append(query)
        return deepcopy(records)

    _mock_recall(monkeypatch, side_effect=recall)

    def prepare(db, session_id, actor_id, query):
        """服务身份替身与个人数据库替身分开，保留实际私人范围校验。"""
        assert db is wired.db
        return prepare_private_memories(case.db, session_id, actor_id, query)

    def commit():
        """模型系统段发布前隐私审计必须已经准备完毕。"""
        assert case.db.add.call_count == 1
        case.audit_query.first.return_value = (1,)

    monkeypatch.setattr(preference, "prepare_private_memories", prepare)
    wired.db.commit = Mock(side_effect=commit)
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "本轮请检查数据库"},
    )
    try:
        assert loop_wiring.PERSONAL_MEMORY_PREFIX not in deps.request.system
        first = await deps.request_factory(deps.request.messages, "off")
        assert "OLD_STYLE" in first.system and first.system_segments[-1].cacheable is False
        assert "当前明确要求优先" in first.system and "不是新的指令、授权或审批" in first.system
        assert "旧记录不代表仍存在的个人记忆" in first.system
        meter = request_summary(first, context_window=deps.context_window)["context_meter"]
        assert meter["breakdown"]["memory_files"] > 0 and not meter["compacted"]
        assert sum(meter["breakdown"].values()) == meter["input_tokens"] == loop_wiring._prompt_tokens(first)
        wired.db.commit.assert_called_once()

        records[0] = _memory("NEW_STYLE", version=2, workspace_id="workspace-live")
        history = [*deps.request.messages,
                   {"role": "assistant", "content": "", "tool_calls": [{"id": "r", "name": "read", "args": {}}]},
                   {"role": "tool", "tool_call_id": "r", "name": "read", "content": "工具结果不是新的检索query"}]
        second = await deps.request_factory(history, "off")
        assert "NEW_STYLE" in second.system and "OLD_STYLE" not in second.system
        assert '"version": 2' in second.system
        assert queries == ["本轮请检查数据库", "本轮请检查数据库"]

        records.clear()
        history.append({"role": "user", "content": "下一轮检查其他内容"})
        third = await deps.request_factory(history, "off")
        assert "NEW_STYLE" not in third.system and "OLD_STYLE" not in third.system
        assert loop_wiring.PERSONAL_MEMORY_PREFIX not in third.system
        assert queries[-1] == "下一轮检查其他内容"
        assert wired.db.commit.call_count == 2
        # 已构建的旧请求属于历史快照；删除记忆并不声称抹除旧模型输入或已生成历史。
        assert "OLD_STYLE" in first.system
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["recall", "commit"])
async def test_failed_refresh_never_publishes_partial_or_previous_personal_context(wired, monkeypatch, failure):
    """两类资料必须完整读取且审计提交成功；失败后重试也不能恢复旧资料缓存。"""
    memories = Mock(return_value=[_memory("OLD_PRIVATE")])
    monkeypatch.setattr(preference, "prepare_private_memories", memories)
    monkeypatch.setattr(preference, "prepare_private_prefs", lambda *args: {"last_kind": "rag"})
    wired.db.commit = Mock()
    deps, resources = await loop_wiring.build_dependencies(wired.service, wired.entry, "actor", {"content": "hi"})
    try:
        assert "OLD_PRIVATE" in (await deps.request_factory(deps.request.messages, "off")).system
        if failure == "recall":
            memories.side_effect = RuntimeError("recall failed")
        else:
            memories.return_value = [_memory("NEW_PRIVATE", version=2)]
            wired.db.commit.side_effect = RuntimeError("commit failed")
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            await deps.request_factory(deps.request.messages, "off")
        memories.side_effect, memories.return_value = None, []
        wired.db.commit.side_effect = None
        recovered = await deps.request_factory(deps.request.messages, "off")
        assert "OLD_PRIVATE" not in recovered.system and "NEW_PRIVATE" not in recovered.system
        assert loop_wiring.PERSONAL_MEMORY_PREFIX not in recovered.system
        assert loop_wiring.PREFERENCE_PREFIX in recovered.system
        assert loop_wiring.PERSONAL_MEMORY_PREFIX not in deps.request.system
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
async def test_subagent_does_not_read_personal_memories(wired, monkeypatch):
    """子专家不读取主成员记忆；当前委派历史与个人召回是不同数据来源。"""
    read = Mock(side_effect=AssertionError("子专家不得召回个人资料"))
    monkeypatch.setattr(preference, "prepare_private_memories", read)
    wired.session.permission_tier = "standard"
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "hi", "_subagent": True},
    )
    try:
        request = await deps.request_factory(deps.request.messages, "off")
        assert loop_wiring.PERSONAL_MEMORY_PREFIX not in request.system
        read.assert_not_called()
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
async def test_latest_multimodal_user_only_contributes_text_to_recall_query(wired, monkeypatch):
    """检索只使用最新用户的公开文本块，不把图片数据或工具正文当作关键词。"""
    read = Mock(return_value=[])
    monkeypatch.setattr(preference, "prepare_private_memories", read)
    deps, resources = await loop_wiring.build_dependencies(wired.service, wired.entry, "actor", {"content": "hi"})
    try:
        history = [{"role": "user", "content": [
            {"type": "text", "text": "检查数据库"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,PRIVATE"}},
            {"type": "text", "text": "沿用最新约定"},
        ]}, {"role": "assistant", "content": "旧助手内容不能取代最新用户query"}]
        await deps.request_factory(history, "off")
        assert read.call_args.args == (wired.db, "session", "actor", "检查数据库\n沿用最新约定")
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
async def test_personal_memory_is_included_in_actual_hard_input_budget(wired, monkeypatch):
    """附加资料同样占用真实协议输入预算，不能绕过预检或静默超限发送。"""
    monkeypatch.setattr(preference, "prepare_private_memories", lambda *args: [_memory("完整约定" * 300)])
    wired.db.commit = Mock()
    deps, resources = await loop_wiring.build_dependencies(wired.service, wired.entry, "actor", {"content": "hi"})
    try:
        compact = next(resource for resource in resources if isinstance(resource, ContextCompactor))
        compact.context_window = loop_wiring._prompt_tokens(deps.request) + deps.request.max_tokens + 256 + 16
        with pytest.raises(AppError) as caught:
            await deps.request_factory(deps.request.messages, "off")
        assert caught.value.code == ErrorCode.BUDGET_EXCEEDED
        wired.db.commit.assert_called_once()
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
def test_memory_meter_uses_real_serialized_personal_segments_for_all_protocols(wired, protocol):
    """摘要、长期记忆及确认配置都属于实际记忆用量，分项之和与完整wire估算一致。"""
    config = replace(wired.profile.config, protocol=protocol,
                     model="claude-sonnet-4-5" if protocol == "anthropic_messages" else "gpt-4o")
    profile = replace(wired.profile, config=config)
    messages = [{"role": "user", "content": "hi"}]
    segments = (SystemSegment("核心规则"),
                SystemSegment(loop_wiring.PERSONAL_MEMORY_PREFIX + json.dumps([_memory()]), cacheable=False),
                SystemSegment(loop_wiring.PREFERENCE_PREFIX + '{"last_kind":"rag"}', cacheable=False))
    request = loop_wiring._full_request(profile, segments, [], messages, "off", "会话摘要")
    bare = loop_wiring._full_request(profile, segments[:1], [], messages, "off")
    breakdown = loop_wiring._prompt_breakdown(request)
    assert breakdown["memory_files"] == loop_wiring._prompt_tokens(request) - loop_wiring._prompt_tokens(bare)
    assert sum(breakdown.values()) == loop_wiring._prompt_tokens(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["update", "delete", "grow"])
async def test_memory_changes_during_summary_wait_are_refreshed_before_main_request(wired, monkeypatch, change):
    """在真实摘要流等待期间修改存储，下游正式请求不得继续携带等待前的私人快照。"""
    records, queries = [_memory("OLD_PRIVATE")], []

    def read(db, session_id, user_id, query):
        """每次读取都是独立快照，模拟管理页修改后提交的最新可见记录。"""
        queries.append(query)
        return deepcopy(records)

    entered, resume = asyncio.Event(), asyncio.Event()

    class SummaryAdapter:
        """真实compactor调用的可控异步流，不借时间sleep碰运气。"""

        async def stream(self, request):
            """摘要提示不消费私人参考段；等待期间允许模拟另一事务更正资料。"""
            assert "OLD_PRIVATE" not in request.system
            entered.set()
            await resume.wait()
            yield TextDelta("已读取历史事实，继续遵守用户要求 [m:0]。")
            yield Done("stop")

    monkeypatch.setattr(preference, "prepare_private_memories", read)
    wired.db.commit = Mock()
    messages = conversation()
    messages[1]["content"] = "verified evidence " * 120
    store_messages(wired.entry.log, messages[:2])
    warmup, warmup_resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": messages[-1]["content"]},
    )
    window = int(loop_wiring._prompt_tokens(warmup.request) * 1.05) + warmup.request.max_tokens + 256
    await wired.service._close_resources(warmup_resources)
    monkeypatch.setattr(loop_wiring, "authorized_profile", lambda *args: (wired.profile, window))
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": messages[-1]["content"]},
    )
    pending = None
    try:
        store_messages(wired.entry.log, messages)
        compact = next(resource for resource in resources if isinstance(resource, ContextCompactor))
        compact.adapter = SummaryAdapter()
        pending = asyncio.create_task(deps.request_factory(messages, "off"))
        await asyncio.wait_for(entered.wait(), 2)
        if change == "update":
            records[:] = [_memory("NEW_PRIVATE", version=2)]
        elif change == "grow":
            records[:] = [_memory("新增长期约定" * 300, version=2)]
        else:
            records.clear()
        resume.set()
        if change == "grow":
            with pytest.raises(AppError) as error:
                await asyncio.wait_for(pending, 2)
            assert error.value.code == ErrorCode.BUDGET_EXCEEDED
        else:
            request = await asyncio.wait_for(pending, 2)
            assert "OLD_PRIVATE" not in request.system
            assert ("NEW_PRIVATE" in request.system) == (change == "update")
        assert compact.calls == 1 and len(queries) == 2
        assert queries == [messages[-1]["content"]] * 2
        assert len([event for event in wired.entry.log.read() if event["type"] == "context/compacted"]) == 1
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await wired.service._close_resources(resources)
