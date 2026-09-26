"""v2 确认偏好闭环、逐请求复验及个人上下文共享保护。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.agent import loop_wiring
from app.errors import AppError, ErrorCode
from app.harness.memory import preference
from app.harness.memory.preference import prepare_private_prefs
from app.models import (
    AuditLog,
    Dataset,
    GoldQa,
    KnowledgeBase,
    ProtocolProfile,
    Session,
    Setting,
    User,
)
from app.routers import sessions
from app.schemas import SessionSharingUpdate
from tests import test_loop_wiring as wiring_fixtures

wired = wiring_fixtures.wired


def _prefs_db(raw=None):
    """只模拟查询接缝，保留实际白名单过滤、使用审计与请求装配。"""
    session = SimpleNamespace(id="session", visibility="private", user_id="actor", workspace_id=None,
                              deleted_at=None, pending_confirm_author_id=None)
    user = SimpleNamespace(id="actor", disabled=False)
    rows = {(User, "actor"): user}
    db = MagicMock()
    db.get.side_effect = lambda model, key: rows.get((model, key))
    session_query, setting_query, audit_query = MagicMock(), MagicMock(), MagicMock()
    for query in (session_query, setting_query, audit_query):
        query.filter.return_value = query
        query.populate_existing.return_value = query
        query.with_for_update.return_value = query
    session_query.first.return_value = session
    setting = Setting(key="agent_prefs:actor", value=raw or {}) if raw is not None else None
    setting_query.first.return_value = setting
    audit_query.first.return_value = None
    queries = {Session: session_query, Setting: setting_query, AuditLog.id: audit_query}
    db.query.side_effect = queries.__getitem__
    return SimpleNamespace(db=db, session=session, user=user, rows=rows, setting=setting,
                           session_query=session_query, audit_query=audit_query)


def test_preferences_validate_assets_and_only_keep_public_fields():
    """共享目录资产不按创建者过滤，已删除 ID 与不匹配黄金集不再注入。"""
    case = _prefs_db({
        "last_kind": "rag", "last_profile_ids": ["profile", "gone", "profile", 123],
        "last_dataset_id": "dataset", "last_kb_id": "kb", "last_gold_qa_id": "gold",
        "last_with_stress": False, "api_key": "must-not-leak", "free_text": "ignore-rules",
    })
    case.rows.update({
        (ProtocolProfile, "profile"): SimpleNamespace(created_by="another-member"),
        (Dataset, "dataset"): SimpleNamespace(created_by="another-member"),
        (KnowledgeBase, "kb"): SimpleNamespace(created_by="another-member"),
        (GoldQa, "gold"): SimpleNamespace(kb_id="other-kb"),
    })
    assert prepare_private_prefs(case.db, "session", "actor") == {
        "last_kind": "rag", "last_profile_ids": ["profile"],
        "last_dataset_id": "dataset", "last_kb_id": "kb", "last_with_stress": False,
    }
    case.rows[(GoldQa, "gold")].kb_id = "kb"
    assert prepare_private_prefs(case.db, "session", "actor")["last_gold_qa_id"] == "gold"
    marker = case.db.add.call_args.args[0]
    assert marker.action == "session_personal_context_used"
    assert marker.detail == {"source": "confirmed_task_preferences"}
    case.session_query.populate_existing.assert_called()
    case.session_query.with_for_update.assert_called()
    case.db.commit.assert_not_called()


@pytest.mark.parametrize("restriction", ["team", "other-owner", "disabled", "missing-session"])
def test_preferences_do_not_read_personal_rows_without_owner_private_scope(restriction):
    """权限不满足时连个人 settings 行也不读取，更不登记使用标记。"""
    case = _prefs_db({"last_kind": "benchmark"})
    if restriction == "team":
        case.session.visibility = "team"
    elif restriction == "other-owner":
        case.session.user_id = "another-member"
    elif restriction == "disabled":
        case.user.disabled = True
    else:
        case.session_query.first.return_value = None
    assert prepare_private_prefs(case.db, "session", "actor") == {}
    assert all(call.args[0] is not Setting for call in case.db.query.call_args_list)
    case.db.add.assert_not_called()


def test_malformed_or_missing_assets_do_not_mark_or_leak_preferences():
    """未知类型与已删除引用全部丢弃，没有可用建议时不限制后续共享。"""
    case = _prefs_db({"last_kind": {}, "last_with_stress": "yes", "last_profile_ids": {},
                      "last_dataset_id": "gone", "last_kb_id": "gone", "last_gold_qa_id": "gold"})
    case.rows[(GoldQa, "gold")] = SimpleNamespace(kb_id="gone")
    assert prepare_private_prefs(case.db, "session", "actor") == {}
    case.db.add.assert_not_called()


def test_existing_privacy_marker_is_not_duplicated():
    """同会话多步请求只保留一条使用审计，锁内复验仍然执行。"""
    case = _prefs_db({"last_kind": "testcase"})
    case.audit_query.first.return_value = (1,)
    assert prepare_private_prefs(case.db, "session", "actor") == {"last_kind": "testcase"}
    case.db.add.assert_not_called()


def test_dirty_preferences_have_bounded_reference_count_and_length():
    """异常历史的超长 ID 和模型列表不能扩大查询与模型输入。"""
    too_long = "x" * 129
    case = _prefs_db({"last_profile_ids": ["profile"] * 10000, "last_dataset_id": too_long,
                      "last_kb_id": too_long, "last_gold_qa_id": too_long})
    case.rows[(ProtocolProfile, "profile")] = SimpleNamespace()
    assert prepare_private_prefs(case.db, "session", "actor") == {"last_profile_ids": ["profile"]}
    assert len(case.db.get.call_args_list) == 6
    assert all(call.args[1] != too_long for call in case.db.get.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["team", "owner", "member", "asset"])
async def test_wiring_refreshes_private_prefs_for_every_model_request(wired, monkeypatch, revocation):
    """工具之后再次请求必须重查权限和引用，不复用上一步的个人系统段。"""
    case = _prefs_db({"last_profile_ids": ["old-profile"]})
    case.rows[(ProtocolProfile, "old-profile")] = SimpleNamespace(created_by="other")

    def prepare(db, session_id, actor_id):
        """复用真实偏好查询，但保留现有服务身份数据库替身。"""
        assert (db, session_id, actor_id) == (wired.db, "session", "actor")
        return prepare_private_prefs(case.db, session_id, actor_id)

    def commit():
        """注入前必须已经登记无正文标记。"""
        assert case.db.add.call_count == 1

    monkeypatch.setattr(preference, "prepare_private_prefs", prepare)
    wired.db.commit = Mock(side_effect=commit)
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "当前明确使用新模型"},
    )
    try:
        assert "old-profile" not in deps.request.system
        request = await deps.request_factory(deps.request.messages, "off")
        wired.db.commit.assert_called_once()
        assert "old-profile" in request.system and request.system_segments[-1].cacheable is False
        assert "当前明确指令优先" in request.system and "不是授权或审批" in request.system
        assert request.messages[-1]["content"] == "当前明确使用新模型"
        if revocation == "team":
            case.session.visibility = "team"
        elif revocation == "owner":
            case.session.user_id = "other"
        elif revocation == "member":
            case.user.disabled = True
        else:
            case.rows.pop((ProtocolProfile, "old-profile"))
        request = await deps.request_factory(deps.request.messages, "off")
        assert "old-profile" not in request.system and "个人历史配置建议" not in request.system
        wired.db.commit.assert_called_once()
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
async def test_wiring_does_not_send_preferences_when_audit_commit_fails(wired, monkeypatch):
    """标记提交失败时请求构建中止，不能让未保护的个人资料进入模型。"""
    monkeypatch.setattr(preference, "prepare_private_prefs", lambda *args: {"last_kind": "rag"})
    wired.db.commit = Mock(side_effect=RuntimeError("commit failed"))
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "hi"},
    )
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            await deps.request_factory(deps.request.messages, "off")
        assert "个人历史配置建议" not in deps.request.system
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
async def test_subagent_never_reads_personal_preferences(wired, monkeypatch):
    """子专家使用委派上下文，不直接读取主成员跨会话偏好。"""
    read = Mock(side_effect=AssertionError("不得读取个人偏好"))
    monkeypatch.setattr(preference, "prepare_private_prefs", read)
    wired.session.permission_tier = "standard"
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "hi", "_subagent": True},
    )
    try:
        request = await deps.request_factory(deps.request.messages, "off")
        assert "个人历史配置建议" not in request.system
        read.assert_not_called()
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["confirm", "deny", "enqueue-failed", "spec-changed"])
async def test_confirmed_preferences_share_enqueue_transaction(wired, monkeypatch, outcome):
    """只记录已确认入队规格，拒绝、复验失败和入队失败不写偏好。"""
    from app.harness.execution import task_tools, worker_bridge

    prepared = 0
    writes = []

    def prepare(db, arguments, context):
        """规格变化发生在确认后的复验阶段。"""
        nonlocal prepared
        prepared += 1
        return "benchmark", {"profile_ids": ["new-profile"],
                             "dataset_id": "changed" if outcome == "spec-changed" and prepared == 2 else "dataset"}, None

    def enqueue(db, **kwargs):
        """任务创建与偏好写入必须由同一事务持有。"""
        assert db is wired.db and wired.entry.log.in_transaction and kwargs["commit"] is False
        if outcome == "enqueue-failed":
            raise RuntimeError("enqueue failed")
        return "task-id"

    def write(db, actor_id, prefs, *, commit):
        """检查实际业务回调传入的白名单快照及事务边界。"""
        assert db is wired.db and wired.entry.log.in_transaction and commit is False
        writes.append((actor_id, prefs))

    async def decision(entry, card):
        """模拟确认选择已通过命令回执鉴权并持久化。"""
        wired.session.pending_confirm["response"] = "confirm"
        return "deny" if outcome == "deny" else "confirm"

    monkeypatch.setattr(task_tools, "prepare_task_request", prepare)
    monkeypatch.setattr(worker_bridge, "enqueue_long_task", enqueue)
    monkeypatch.setattr(preference, "write_prefs", write)
    monkeypatch.setattr(wired.service, "_wait_interaction", decision)
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "run"},
    )
    tool = next(t for t in deps.scheduler._by_name.values() if t.definition.name == "task.create")
    try:
        operation = tool.callback(tool.definition, {}, SimpleNamespace(session_id="session", user_id="actor"),
                                  {"session_id": "session", "turn": 1, "step": 1,
                                   "attempt_id": "a", "call_id": "c", "call_seq": 0})
        if outcome in {"enqueue-failed", "spec-changed"}:
            with pytest.raises(RuntimeError if outcome == "enqueue-failed" else AppError):
                await operation
        else:
            result = await operation
            assert result.status == ("succeeded" if outcome == "confirm" else "denied")
        if outcome == "confirm":
            assert writes == [("actor", {"last_kind": "benchmark", "last_profile_ids": ["new-profile"],
                                         "last_dataset_id": "dataset", "last_kb_id": None,
                                         "last_gold_qa_id": None, "last_with_stress": False})]
        else:
            assert not writes
            assert not any(event["type"] == "task/queued" for event in wired.entry.log.events)
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("used_personal_context", [True, False])
async def test_sharing_private_session_checks_personal_context_under_owner_lock(monkeypatch, used_personal_context):
    """读取过个人记忆的会话拒转团队，未使用的普通会话仍可共享。"""
    case = _prefs_db()
    owner = Mock(return_value=case.session)
    monkeypatch.setattr(sessions, "require_session_owner", owner)
    monkeypatch.setattr(sessions, "_session_out", lambda db, session, user: session)
    case.audit_query.first.return_value = (1,) if used_personal_context else None
    operation = sessions.update_session_sharing(
        "session", SessionSharingUpdate(visibility="team"), case.db, case.user,
    )
    if used_personal_context:
        with pytest.raises(AppError) as exc:
            await operation
        assert exc.value.code == ErrorCode.VALIDATION and "个人记忆" in exc.value.message
        assert case.session.visibility == "private"
        case.db.commit.assert_not_called()
    else:
        assert (await operation).visibility == "team"
        case.db.commit.assert_called_once()
    owner.assert_called_once_with(case.db, "session", "actor", lock=True)
