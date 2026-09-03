"""Harness 记忆层：LangGraph Checkpointer（M3 阶段 3）。

- ``InMemoryCheckpointer``：进程内共享的内存实现（实例锁保护），供测试与
  单副本无 PG 场景；WS 回合、REST 会话删除与 TTL 后台任务必须看见同一份检查点；
- ``PgCheckpointer``：PostgreSQL 持久化（``harness_checkpoints`` +
  ``harness_checkpoint_writes``，迁移见 migrations）。

检查点恢复语义（M3-D4）：检查点保存图终态累积的 ``pending_events``，但
**恢复时重置为空**——事件已由 ``ws_events`` 持久化，断线重放走
``ws_events``，不依赖检查点，避免重复 emit；仅恢复 ``mode``/``plan``/
``verdict`` 等控制字段（由调用方按需过滤）。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import RunnableConfig

__all__ = ["InMemoryCheckpointer", "PgCheckpointer", "get_default_checkpointer"]


def _thread_key(config: RunnableConfig) -> tuple[str, str]:
    """从 RunnableConfig 提取 (thread_id, checkpoint_ns)。"""
    configurable = config.get("configurable") or {}
    thread_id = str(configurable.get("thread_id") or "default")
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    return thread_id, checkpoint_ns


def _checkpoint_id(config: RunnableConfig) -> str | None:
    """从 RunnableConfig 提取 checkpoint_id（None 表示取最新）。"""
    configurable = config.get("configurable") or {}
    value = configurable.get("checkpoint_id")
    return str(value) if value else None


class _AsyncBridgeMixin:
    """async 桥接（LangGraph 1.2 async 执行路径调用 aget_tuple/aput 等）。"""

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)  # type: ignore[attr-defined]

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)  # type: ignore[attr-defined]

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return self.put_writes(config, writes, task_id, task_path)  # type: ignore[attr-defined]

    async def alist(
        self,
        config: RunnableConfig | None = None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Any:
        for item in self.list(config, filter=filter, before=before, limit=limit):  # type: ignore[attr-defined]
            yield item

    async def aget(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)  # type: ignore[attr-defined]

    def delete_thread(self, thread_id: str) -> None:
        """删除某 thread 的全部检查点（清理用）；子类可覆盖。"""
        raise NotImplementedError

    async def adelete_thread(self, thread_id: str) -> None:
        return self.delete_thread(thread_id)


class InMemoryCheckpointer(_AsyncBridgeMixin, BaseCheckpointSaver):
    """进程内共享的内存 Checkpointer（实例锁，跨线程可见）。

    带容量上限（``max_checkpoints``，默认 512）：超限按 checkpoint_id 淘汰
    最旧检查点，防止长运行进程内存膨胀（配合 ``cleanup_orphaned_checkpoints``
    超龄清理）。会话软删除与 TTL 后台任务依赖这份进程内可见性。
    """

    def __init__(self, max_checkpoints: int = 512) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self._lock = threading.RLock()
        self._checkpoints: dict = {}
        self._pending_writes: dict = {}
        self._max_checkpoints = max(1, max_checkpoints)

    def iter_thread_ids(self) -> list[str]:
        """返回当前存储中的去重 thread_id（供会话前缀清理）。"""
        with self._lock:
            return sorted({str(key[0]) for key in self._checkpoints})

    def delete_thread(self, thread_id: str) -> None:
        """删除某 thread 的全部检查点与待写入。"""
        target = str(thread_id)
        with self._lock:
            for key in [item for item in self._checkpoints if item[0] == target]:
                del self._checkpoints[key]
            for key in [item for item in self._pending_writes if item[0] == target]:
                del self._pending_writes[key]

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, checkpoint_ns = _thread_key(config)
        checkpoint_id = str(checkpoint["id"])
        parent_id = _checkpoint_id(config)
        with self._lock:
            self._checkpoints[(thread_id, checkpoint_ns, checkpoint_id)] = (
                checkpoint,
                metadata,
                parent_id,
            )
            # 容量保护：超限淘汰最旧检查点（按 checkpoint_id 排序，优先淘汰最早）
            if len(self._checkpoints) > self._max_checkpoints:
                for key in sorted(self._checkpoints, key=lambda item: item[2])[
                    : len(self._checkpoints) // 4
                ]:
                    del self._checkpoints[key]
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, checkpoint_ns = _thread_key(config)
        with self._lock:
            checkpoint_id = _checkpoint_id(config)
            if checkpoint_id is None:
                # config 未指定 checkpoint_id 时，写入当前 thread 最新检查点
                latest = self.get_tuple(config)
                checkpoint_id = (
                    latest.config["configurable"]["checkpoint_id"] if latest else ""
                )
            self._pending_writes[(thread_id, checkpoint_ns, checkpoint_id, task_id)] = (
                list(writes)
            )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, checkpoint_ns = _thread_key(config)
        with self._lock:
            return self._get_tuple_locked(config, thread_id, checkpoint_ns)

    def _get_tuple_locked(
        self,
        config: RunnableConfig,
        thread_id: str,
        checkpoint_ns: str,
    ) -> CheckpointTuple | None:
        """持锁读取最新或指定检查点（供 get_tuple / put_writes 复用）。"""
        target_id = _checkpoint_id(config)
        if target_id is not None:
            item = self._checkpoints.get((thread_id, checkpoint_ns, target_id))
            if item is None:
                return None
            checkpoint, metadata, parent_id = item
        else:
            matches = [
                (key, value)
                for key, value in self._checkpoints.items()
                if key[:2] == (thread_id, checkpoint_ns)
            ]
            if not matches:
                return None
            matches.sort(key=lambda kv: kv[0][2])
            _, (checkpoint, metadata, parent_id) = matches[-1]
            target_id = checkpoint["id"]
        parent_config = None
        if parent_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_id,
                }
            }
        pending_writes = [
            (key[3], channel, value)
            for key, writes in self._pending_writes.items()
            if key[:3] == (thread_id, checkpoint_ns, target_id)
            for channel, value in writes
        ]
        pending_writes = pending_writes or None
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": target_id,
            }
        }
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    def list(
        self,
        config: RunnableConfig | None = None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        with self._lock:
            items = sorted(self._checkpoints.items(), key=lambda kv: kv[0][2])
        count = 0
        for (thread_id, checkpoint_ns, _), (checkpoint, metadata, parent_id) in items:
            if before is not None and checkpoint["id"] >= (_checkpoint_id(before) or ""):
                continue
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint["id"],
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=(
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": parent_id,
                        }
                    }
                    if parent_id
                    else None
                ),
                pending_writes=None,
            )
            count += 1
            if limit is not None and count >= limit:
                break


# —— PostgreSQL 持久化 Checkpointer ——

_CHECKPOINT_UPSERT = """
INSERT INTO harness_checkpoints (
    thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata_type, metadata
) VALUES (:thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, :type, :checkpoint, :metadata_type, :metadata)
ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET
    parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
    checkpoint = EXCLUDED.checkpoint,
    metadata_type = EXCLUDED.metadata_type,
    metadata = EXCLUDED.metadata
"""

_CHECKPOINT_GET = """
SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata_type, metadata
FROM harness_checkpoints
WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
  AND checkpoint_id = :checkpoint_id
"""

_CHECKPOINT_GET_LATEST = """
SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata_type, metadata
FROM harness_checkpoints
WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
ORDER BY checkpoint_id DESC
LIMIT 1
"""

_WRITES_GET = """
SELECT task_id, channel, type, blob
FROM harness_checkpoint_writes
WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns AND checkpoint_id = :checkpoint_id
ORDER BY task_id, idx
"""

_WRITES_INSERT = """
INSERT INTO harness_checkpoint_writes (
    thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob
) VALUES (:thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :blob)
"""


class PgCheckpointer(_AsyncBridgeMixin, BaseCheckpointSaver):
    """PostgreSQL 持久化 Checkpointer（sqlalchemy core，无 ORM 模型）。"""

    def __init__(self, engine: object) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self.engine = engine

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, checkpoint_ns = _thread_key(config)
        checkpoint_id = str(checkpoint["id"])
        parent_id = _checkpoint_id(config)
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(metadata)
        sqlalchemy = __import__("sqlalchemy")
        with self.engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(_CHECKPOINT_UPSERT),
                {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "parent_checkpoint_id": parent_id,
                    "type": checkpoint_type,
                    "checkpoint": checkpoint_blob,
                    "metadata_type": metadata_type,
                    "metadata": metadata_blob,
                },
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, checkpoint_ns = _thread_key(config)
        checkpoint_id = _checkpoint_id(config) or ""
        sqlalchemy = __import__("sqlalchemy")
        with self.engine.begin() as conn:
            for index, (channel, value) in enumerate(writes):
                value_type, value_blob = self.serde.dumps_typed(value)
                conn.execute(
                    sqlalchemy.text(_WRITES_INSERT),
                    {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "idx": index,
                        "channel": channel,
                        "type": value_type,
                        "blob": value_blob,
                    },
                )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, checkpoint_ns = _thread_key(config)
        target_id = _checkpoint_id(config)
        sqlalchemy = __import__("sqlalchemy")
        with self.engine.connect() as conn:
            if target_id is not None:
                row = conn.execute(
                    sqlalchemy.text(_CHECKPOINT_GET),
                    {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": target_id,
                    },
                ).first()
            else:
                row = conn.execute(
                    sqlalchemy.text(_CHECKPOINT_GET_LATEST),
                    {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns},
                ).first()
            if row is None:
                return None
            checkpoint = self.serde.loads_typed((row.type, row.checkpoint))
            metadata = self.serde.loads_typed((row.metadata_type, row.metadata))
            parent_id = row.parent_checkpoint_id
            writes_rows = conn.execute(
                sqlalchemy.text(_WRITES_GET),
                {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                },
            ).all()
        pending_writes = [
            (
                writes_row.task_id,
                writes_row.channel,
                self.serde.loads_typed((writes_row.type, writes_row.blob)),
            )
            for writes_row in writes_rows
        ]
        parent_config = None
        if parent_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_id,
                }
            }
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    def iter_thread_ids(self) -> list[str]:
        """返回检查点表中的去重 thread_id（供会话前缀清理）。"""
        sqlalchemy = __import__("sqlalchemy")
        with self.engine.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text("SELECT DISTINCT thread_id FROM harness_checkpoints")
            ).all()
        return [str(row.thread_id) for row in rows if row.thread_id]

    def delete_thread(self, thread_id: str) -> None:
        """删除某 thread 的全部检查点与待写入（SQL DELETE）。"""
        sqlalchemy = __import__("sqlalchemy")
        with self.engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(
                    "DELETE FROM harness_checkpoint_writes WHERE thread_id = :thread_id"
                ),
                {"thread_id": str(thread_id)},
            )
            conn.execute(
                sqlalchemy.text(
                    "DELETE FROM harness_checkpoints WHERE thread_id = :thread_id"
                ),
                {"thread_id": str(thread_id)},
            )

    def list(
        self,
        config: RunnableConfig | None = None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        sqlalchemy = __import__("sqlalchemy")
        with self.engine.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text("SELECT * FROM harness_checkpoints ORDER BY checkpoint_id")
            ).all()
        for row in rows:
            if before is not None and row.checkpoint_id >= (_checkpoint_id(before) or ""):
                continue
            checkpoint = self.serde.loads_typed((row.type, row.checkpoint))
            metadata = self.serde.loads_typed((row.metadata_type, row.metadata))
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=(
                    {
                        "configurable": {
                            "thread_id": row.thread_id,
                            "checkpoint_ns": row.checkpoint_ns,
                            "checkpoint_id": row.parent_checkpoint_id,
                        }
                    }
                    if row.parent_checkpoint_id
                    else None
                ),
                pending_writes=None,
            )
            if limit is not None:
                limit -= 1
                if limit <= 0:
                    break


_default_checkpointer: BaseCheckpointSaver | None = None
_default_checkpointer_lock = threading.Lock()


def get_default_checkpointer() -> BaseCheckpointSaver:
    """生产默认 Checkpointer（进程内单例）。

    默认 ``memory``（单副本、每回合独立 thread_id）。仅当
    ``AGENT_CHECKPOINTER=postgres`` 时启用 ``PgCheckpointer``；恢复时
    ``pending_events`` 仍须由图外清空，事件重放只走 ``ws_events``。

    单例保证 WS 图、会话软删除与 TTL 后台任务操作同一份检查点；
    禁止默认改为 postgres（多副本粘性需单独评审）。

    H5 批次 2 生产门禁：混合引擎开启时，HITL 审批 resume 需跨进程恢复，
    ``main.py::_validate_hitl_checkpointer`` 在启动期校验——``agent_hitl_strict_pg``
    为 true 时 ``memory`` 检查点 fail-fast 阻止启动；为 false（默认）仅告警。
    正式发布 HITL 前必须切 ``postgres`` 并完成重启恢复演练（开发计划 §3 H5）。
    """
    global _default_checkpointer
    with _default_checkpointer_lock:
        if _default_checkpointer is None:
            from app.config import settings

            mode = str(
                getattr(settings, "agent_checkpointer", "memory") or "memory"
            ).strip().lower()
            if mode == "postgres":
                from app.db import engine

                _default_checkpointer = PgCheckpointer(engine)
            else:
                _default_checkpointer = InMemoryCheckpointer()
        return _default_checkpointer
