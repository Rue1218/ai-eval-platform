"""M3 记忆层 Checkpointer 单测（阶段 3）；不依赖 DB。"""

from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

from app.harness.memory import InMemoryCheckpointer, cleanup_orphaned_checkpoints


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
