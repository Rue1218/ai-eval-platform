"""Harness 记忆层：孤儿检查点清理（M3 阶段 3）。

每回合独立 ``thread_id``（``{session_id}:{turn_id}``）隔离回合，回合结束后
检查点成为孤儿；``cleanup_orphaned_checkpoints`` 按「thread 最新检查点
超过保留窗口」删除整 thread（``checkpointer.delete_thread``），防止
PG/内存表无限膨胀。``cleanup_session_checkpoints`` 在会话软删除时按
``{session_id}:`` 前缀（及历史裸 ``session_id``）清掉该会话全部检查点。

通用实现只依赖 Checkpointer 的 ``list``/``iter_thread_ids``/``delete_thread``
接口，内存版与 PG 版均可复用。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# 默认保留窗口：检查点保存天数（Harness §2.4 / M9-D5）
DEFAULT_RETENTION_DAYS = 7


def _parse_ts(value: object) -> datetime | None:
    """解析检查点 ts（ISO 字符串，LangGraph 用 Z 后缀）；失败返回 None。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def thread_belongs_to_session(thread_id: str, session_id: str) -> bool:
    """判断 thread_id 是否属于某会话。

    现行约定为 ``{session_id}:{turn_id}``；兼容早期 ``thread_id=session_id``。
    空 session_id 永不匹配，避免误删全部检查点。
    """
    sid = str(session_id).strip()
    tid = str(thread_id).strip()
    if not sid or not tid:
        return False
    return tid == sid or tid.startswith(f"{sid}:")


def _collect_thread_ids(checkpointer: object) -> set[str]:
    """收集 Checkpointer 中的去重 thread_id。"""
    method = getattr(checkpointer, "iter_thread_ids", None)
    if callable(method):
        return {str(item) for item in method() if str(item).strip()}
    ids: set[str] = set()
    for tup in checkpointer.list():  # type: ignore[attr-defined]
        thread_id = str(tup.config["configurable"].get("thread_id", ""))
        if thread_id:
            ids.add(thread_id)
    return ids


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


def cleanup_session_checkpoints(checkpointer: object, session_id: str) -> int:
    """会话软删除联动：删除该会话全部检查点；返回清理的 thread 数。"""
    if not str(session_id).strip():
        return 0
    removed = 0
    for thread_id in _collect_thread_ids(checkpointer):
        if thread_belongs_to_session(thread_id, session_id):
            checkpointer.delete_thread(thread_id)  # type: ignore[attr-defined]
            removed += 1
    return removed


def purge_session_checkpoints(
    session_id: str,
    checkpointer: object | None = None,
) -> int:
    """对默认（或指定）Checkpointer 执行会话联动清理。"""
    saver = checkpointer if checkpointer is not None else None
    if saver is None:
        from .checkpoint import get_default_checkpointer

        saver = get_default_checkpointer()
    return cleanup_session_checkpoints(saver, session_id)
