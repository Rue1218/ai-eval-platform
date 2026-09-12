"""验证减负路径的查询/读取次数，同时保留可见性和配置新鲜度。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import profile_env
from app.models import Task
from app.routers import sessions


@pytest.mark.parametrize("size", [0, 1, 20, 501])
def test_session_list_batches_active_tasks_without_per_session_fallback(size):
    """空列表不查任务，每批最多 500 会话；无任务项不能再单查。"""
    now = datetime.now(UTC)
    rows = [SimpleNamespace(
        id=f"s-{i}", title=f"会话 {i}", user_id="u", visibility="private",
        workspace_id=None, created_at=now, updated_at=now,
        engine_version="agent_loop_v2",
    ) for i in range(size)]
    newest = SimpleNamespace(id="new", session_id="s-0", kind="benchmark", status="running")
    older = SimpleNamespace(id="old", session_id="s-0", kind="rag", status="queued")
    db = MagicMock()
    session_query = MagicMock()
    session_query.filter.return_value = session_query
    session_query.order_by.return_value = session_query
    session_query.all.return_value = rows
    task_queries = []

    def query(model):
        """保留过滤表达式供断言，仅模拟返回行，不连接生产数据库。"""
        if model is sessions.AgentSession:
            return session_query
        assert model is Task
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = [newest, older] if not task_queries and size else []
        task_queries.append(q)
        return q

    db.query.side_effect = query
    result = sessions.list_sessions(db, SimpleNamespace(id="u"))
    assert result["total"] == size
    assert len(task_queries) == (size + 499) // 500
    queried_ids = []
    for q in task_queries:
        by_session, by_status = q.filter.call_args.args
        queried_ids.extend(by_session.right.value)
        assert set(by_status.right.value) == sessions.ACTIVE_STATUSES
        q.first.assert_not_called()
        assert "created_at DESC" in str(q.order_by.call_args.args[0])
    assert queried_ids == [row.id for row in rows]
    assert all(item["active_task"] is None for item in result["items"][1:])
    if size:
        assert result["items"][0]["active_task"] == {"id": "new", "kind": "benchmark", "status": "running"}
        assert all(item["can_manage"] and item["can_delete"] for item in result["items"])


def test_env_read_scope_is_single_snapshot_and_resets_after_failure(tmp_path, monkeypatch):
    """同一投影不重复读文件；下一请求与异常退出后立即看见新配置。"""
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=before\n", encoding="utf-8")
    monkeypatch.setattr(profile_env.settings, "profile_env_file", str(env_file))
    original = profile_env._read_snapshot
    reads = []

    def read(path):
        """只计次数，不记录文件内容或凭据。"""
        reads.append(path)
        return original(path)

    monkeypatch.setattr(profile_env, "_read_snapshot", read)
    with pytest.raises(RuntimeError), profile_env.profile_env_read_scope():
        assert profile_env.read_global_llm_env().model == "before"
        profile_env.read_profile_env("p")
        env_file.write_text("LLM_MODEL=after\n", encoding="utf-8")
        assert profile_env.read_global_llm_env().model == "before"
        assert len(reads) == 1
        raise RuntimeError("测试作用域退出")
    assert profile_env.read_global_llm_env().model == "after"
    assert len(reads) == 2
