"""Harness 记忆层：孤儿检查点清理（M3 阶段 3）。

每回合独立 ``thread_id``（``{session_id}:{turn_id}``）隔离回合，回合结束后
检查点成为孤儿；``cleanup_orphaned_checkpoints`` 按「thread 最新检查点
超过保留窗口」删除整 thread（``checkpointer.delete_thread``），防止
PG/内存表无限膨胀。通用实现只依赖 Checkpointer 的 ``list``/``delete_thread``
接口，内存版与 PG 版均可复用。

> 注意：InMemoryCheckpointer 为线程隔离存储（threading.local），跨线程调用
> 清理时看不到其他线程的检查点；当前单副本单线程运行不受影响，PG 引擎
> 接入后由 ``PgCheckpointer`` 承担跨进程清理。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# 默认保留窗口：检查点保存天数
DEFAULT_RETENTION_DAYS = 7


def _parse_ts(value: object) -> datetime | None:
    """解析检查点 ts（ISO 字符串，LangGraph 用 Z 后缀）；失败返回 None。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def cleanup_orphaned_checkpoints(
    checkpointer: object,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """清理超过保留窗口的检查点；返回清理的 thread 数。

    判定：遍历 ``checkpointer.list()``，统计每个 thread 的最新检查点 ts，
    最新 ts 早于 cutoff 的 thread 整体删除（``delete_thread``）。
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    latest_by_thread: dict[str, datetime | None] = {}
    for tup in checkpointer.list():  # type: ignore[attr-defined]
        thread_id = str(tup.config["configurable"].get("thread_id", ""))
        if not thread_id:
            continue
        ts = _parse_ts(tup.checkpoint.get("ts"))
        current = latest_by_thread.get(thread_id)
        if ts is not None and (current is None or ts > current):
            latest_by_thread[thread_id] = ts
    removed = 0
    for thread_id, latest in latest_by_thread.items():
        if latest is not None and latest < cutoff:
            checkpointer.delete_thread(thread_id)  # type: ignore[attr-defined]
            removed += 1
    return removed
