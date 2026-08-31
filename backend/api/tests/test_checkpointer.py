"""M3 记忆层 Checkpointer 单测（阶段 3）；不依赖 DB。"""

from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

from app.harness.memory import (
    InMemoryCheckpointer,
    cleanup_orphaned_checkpoints,
    cleanup_session_checkpoints,
    get_default_checkpointer,
)


def _checkpoint(cp_id: str, ts: str = "2026-08-24T00:00:00Z") -> Checkpoint:
    """构造最小 v1 检查点。"""
    return Checkpoint(
        v=1,
        ts=ts,
        id=cp_id,
        channel_values={"mode": "chat", "request": {"messages": ()}},
        channel_versions={},
        versions_seen={},
        pending_sends=[],
    )


def _metadata(step: int) -> CheckpointMetadata:
    """构造最小元数据。"""
    return CheckpointMetadata(
        source="loop",
        step=step,
        writes=None,
        parents=None,
        tasks=[],
    )


def test_inmemory_put_get_roundtrip() -> None:
    """put → get_tuple 往返一致（含序列化/反序列化）。"""
    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    new_config = checkpointer.put(config, _checkpoint("cp1"), _metadata(1), {})
    assert new_config["configurable"]["checkpoint_id"] == "cp1"
    latest = checkpointer.get_tuple(config)
    assert latest is not None
    assert latest.checkpoint["id"] == "cp1"
    assert latest.metadata["step"] == 1
    exact = checkpointer.get_tuple(new_config)
    assert exact is not None
    assert exact.checkpoint["id"] == "cp1"


def test_inmemory_latest_returns_most_recent() -> None:
    """同一 thread 多个检查点时 get_tuple 取最新。"""
    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    checkpointer.put(config, _checkpoint("cp1"), _metadata(1), {})
    checkpointer.put(config, _checkpoint("cp2"), _metadata(2), {})
    latest = checkpointer.get_tuple(config)
    assert latest is not None
    assert latest.checkpoint["id"] == "cp2"


def test_inmemory_thread_isolation() -> None:
    """thread_id 隔离：不同线程互不可见。"""
    checkpointer = InMemoryCheckpointer()
    checkpointer.put(
        {"configurable": {"thread_id": "ta", "checkpoint_ns": ""}},
        _checkpoint("cp-a"),
        _metadata(1),
        {},
    )
    assert checkpointer.get_tuple({"configurable": {"thread_id": "tb"}}) is None
    assert checkpointer.get_tuple({"configurable": {"thread_id": "ta"}}) is not None


def test_inmemory_put_writes_roundtrip() -> None:
    """put_writes → get_tuple.pending_writes 往返。"""
    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    checkpointer.put(config, _checkpoint("cp1"), _metadata(1), {})
    checkpointer.put_writes(config, [("pending_events", [{"kind": "thought"}])], task_id="task1")
    latest = checkpointer.get_tuple(config)
    assert latest is not None
    assert latest.pending_writes == [("task1", "pending_events", [{"kind": "thought"}])]


def test_inmemory_list_orders_and_limits() -> None:
    """list 按 checkpoint_id 排序并支持 limit。"""
    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    for index in range(3):
        checkpointer.put(config, _checkpoint(f"cp{index}"), _metadata(index), {})
    tuples = list(checkpointer.list(config))
    assert [item.checkpoint["id"] for item in tuples] == ["cp0", "cp1", "cp2"]
    limited = list(checkpointer.list(config, limit=2))
    assert len(limited) == 2


def test_inmemory_delete_thread_removes_all() -> None:
    """delete_thread 删除该 thread 全部检查点与待写入。"""
    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    checkpointer.put(config, _checkpoint("cp1"), _metadata(1), {})
    checkpointer.put_writes(config, [("pending_events", [{"kind": "thought"}])], task_id="t1")
    checkpointer.delete_thread("t1")
    assert checkpointer.get_tuple(config) is None
    assert checkpointer.get_tuple({"configurable": {"thread_id": "t2"}}) is None


def test_inmemory_capacity_evicts_oldest() -> None:
    """容量保护：超限淘汰最旧检查点，进程内存不膨胀。"""
    checkpointer = InMemoryCheckpointer(max_checkpoints=8)
    for index in range(12):
        checkpointer.put(
            {"configurable": {"thread_id": f"t{index % 2}", "checkpoint_ns": ""}},
            _checkpoint(f"cp{index}"),
            _metadata(index),
            {},
        )
    # 淘汰后总量 ≤ 容量上限
    remaining = list(checkpointer.list())
    assert len(remaining) <= 8
    # 最新检查点仍可读取
    latest = checkpointer.get_tuple({"configurable": {"thread_id": "t1"}})
    assert latest is not None


def test_cleanup_removes_orphaned_threads() -> None:
    """cleanup 删除超保留窗口的 thread，保留新 thread。"""
    from datetime import UTC, datetime

    checkpointer = InMemoryCheckpointer()
    # 旧 thread：检查点 ts 在保留窗口之前
    checkpointer.put(
        {"configurable": {"thread_id": "old", "checkpoint_ns": ""}},
        _checkpoint("cp-old", ts="2026-01-01T00:00:00Z"),
        _metadata(1),
        {},
    )
    # 新 thread：检查点 ts 为当前时间（避免测试时间敏感）
    checkpointer.put(
        {"configurable": {"thread_id": "new", "checkpoint_ns": ""}},
        _checkpoint("cp-new", ts=datetime.now(UTC).isoformat()),
        _metadata(1),
        {},
    )
    removed = cleanup_orphaned_checkpoints(checkpointer, retention_days=7)
    assert removed == 1
    assert checkpointer.get_tuple({"configurable": {"thread_id": "old"}}) is None
    assert checkpointer.get_tuple({"configurable": {"thread_id": "new"}}) is not None


def test_default_checkpointer_stays_in_memory() -> None:
    """P3：默认 AGENT_CHECKPOINTER=memory，不在生产默认打开 PgCheckpointer。"""
    assert isinstance(get_default_checkpointer(), InMemoryCheckpointer)


def test_default_checkpointer_is_process_singleton() -> None:
    """WS / 会话删除 / TTL 必须共用同一 Checkpointer 实例。"""
    assert get_default_checkpointer() is get_default_checkpointer()


def test_inmemory_visible_across_threads() -> None:
    """进程内共享存储：后台线程写入后，调用方可读（非 threading.local）。"""
    import threading

    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "cross-thread", "checkpoint_ns": ""}}

    def _writer() -> None:
        checkpointer.put(config, _checkpoint("cp-thread"), _metadata(1), {})

    worker = threading.Thread(target=_writer)
    worker.start()
    worker.join()
    assert checkpointer.get_tuple(config) is not None


def test_cleanup_session_removes_prefixed_threads() -> None:
    """R-A4：会话软删除清掉 `{session_id}:*` 与裸 session_id，保留其他会话。"""
    checkpointer = InMemoryCheckpointer()
    session_id = "11111111-1111-4111-8111-111111111111"
    other_id = "22222222-2222-4222-8222-222222222222"
    checkpointer.put(
        {"configurable": {"thread_id": f"{session_id}:turn-a", "checkpoint_ns": ""}},
        _checkpoint("cp-a"),
        _metadata(1),
        {},
    )
    checkpointer.put(
        {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}},
        _checkpoint("cp-bare"),
        _metadata(1),
        {},
    )
    checkpointer.put(
        {"configurable": {"thread_id": f"{other_id}:turn-b", "checkpoint_ns": ""}},
        _checkpoint("cp-b"),
        _metadata(1),
        {},
    )
    removed = cleanup_session_checkpoints(checkpointer, session_id)
    assert removed == 2
    assert checkpointer.get_tuple(
        {"configurable": {"thread_id": f"{session_id}:turn-a"}}
    ) is None
    assert checkpointer.get_tuple({"configurable": {"thread_id": session_id}}) is None
    assert checkpointer.get_tuple(
        {"configurable": {"thread_id": f"{other_id}:turn-b"}}
    ) is not None


def test_cleanup_session_does_not_match_prefix_sibling() -> None:
    """短前缀不得误删更长 session_id 的检查点。"""
    checkpointer = InMemoryCheckpointer()
    checkpointer.put(
        {"configurable": {"thread_id": "s10:turn", "checkpoint_ns": ""}},
        _checkpoint("cp-keep"),
        _metadata(1),
        {},
    )
    assert cleanup_session_checkpoints(checkpointer, "s1") == 0
    assert checkpointer.get_tuple({"configurable": {"thread_id": "s10:turn"}}) is not None


def test_cleanup_session_blank_id_is_noop() -> None:
    """空 session_id 不得清全部检查点。"""
    checkpointer = InMemoryCheckpointer()
    config = {"configurable": {"thread_id": "keep", "checkpoint_ns": ""}}
    checkpointer.put(config, _checkpoint("cp-keep"), _metadata(1), {})
    assert cleanup_session_checkpoints(checkpointer, "") == 0
    assert cleanup_session_checkpoints(checkpointer, "   ") == 0
    assert checkpointer.get_tuple(config) is not None


def test_pg_checkpointer_roundtrip_sqlite() -> None:
    """PgCheckpointer SQL 全链路读写删（sqlite 内存库，方言无关语义）。

    曾因 SELECT 缺 metadata_type 列导致 get_tuple/list 读已有检查点必炸
    （a1f3c5e7b9d1 建表漏列；该类此前从未启用，零测试覆盖而漏网）。
    """
    import sqlalchemy as sa

    from app.harness.memory.checkpoint import PgCheckpointer

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE harness_checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB NOT NULL,
                metadata_type TEXT NOT NULL DEFAULT 'msgpack',
                metadata BLOB NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE harness_checkpoint_writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT NOT NULL,
                blob BLOB NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
        """))

    checkpointer = PgCheckpointer(engine)
    config = {"configurable": {"thread_id": "pg-t1", "checkpoint_ns": ""}}
    stored = checkpointer.put(config, _checkpoint("cp-1"), _metadata(1), {})

    got = checkpointer.get_tuple(config)
    assert got is not None, "get_tuple 未读回刚写入的检查点"
    assert got.checkpoint["id"] == "cp-1"
    assert got.metadata["step"] == 1

    checkpointer.put_writes(stored, [("messages", "hello")], "task-1")
    got = checkpointer.get_tuple(config)
    assert got is not None and got.pending_writes
    assert got.pending_writes[0][0] == "task-1"

    items = list(checkpointer.list(config))
    assert len(items) == 1
    assert items[0].metadata["step"] == 1

    assert checkpointer.iter_thread_ids() == ["pg-t1"]
    checkpointer.delete_thread("pg-t1")
    assert checkpointer.get_tuple(config) is None
    assert list(checkpointer.list(config)) == []
