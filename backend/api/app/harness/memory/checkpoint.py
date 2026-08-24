"""Harness 记忆层：LangGraph Checkpointer（M3 阶段 3）。

- ``InMemoryCheckpointer``：线程隔离的内存实现（threading.local），供测试与
  单副本无 PG 场景；
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
    """线程隔离的内存 Checkpointer（threading.local，不入进程共享状态）。

    带容量上限（``max_checkpoints``，默认 512）：超限按 checkpoint_id 淘汰
    最旧检查点，防止长运行进程内存膨胀（配合 ``cleanup_orphaned_checkpoints``
    超龄清理）。
    """

    def __init__(self, max_checkpoints: int = 512) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self._local = threading.local()
        self._max_checkpoints = max(1, max_checkpoints)

    def _storage(self) -> dict:
        return self._local.__dict__.setdefault("checkpoints", {})

    def _writes(self) -> dict:
        return self._local.__dict__.setdefault("writes", {})

    def delete_thread(self, thread_id: str) -> None:
        """删除某 thread 的全部检查点与待写入（线程隔离存储内）。"""
        target = str(thread_id)
        for key in [item for item in self._storage() if item[0] == target]:
            del self._storage()[key]
        for key in [item for item in self._writes() if item[0] == target]:
            del self._writes()[key]

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
        storage = self._storage()
        storage[(thread_id, checkpoint_ns, checkpoint_id)] = (
            checkpoint,
            metadata,
            parent_id,
        )
        # 容量保护：超限淘汰最旧检查点（按 checkpoint_id 排序，优先淘汰最早）
        if len(storage) > self._max_checkpoints:
            for key in sorted(storage, key=lambda item: item[2])[: len(storage) // 4]:
                del storage[key]
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
        checkpoint_id = _checkpoint_id(config)
        if checkpoint_id is None:
            # config 未指定 checkpoint_id 时，写入当前 thread 最新检查点
            latest = self.get_tuple(config)
            checkpoint_id = (
                latest.config["configurable"]["checkpoint_id"] if latest else ""
            )
        self._writes()[(thread_id, checkpoint_ns, checkpoint_id, task_id)] = list(writes)

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, checkpoint_ns = _thread_key(config)
        storage = self._storage()
        target_id = _checkpoint_id(config)
        if target_id is not None:
            item = storage.get((thread_id, checkpoint_ns, target_id))
            if item is None:
                return None
            checkpoint, metadata, parent_id = item
        else:
            matches = [
                (key, value)
                for key, value in storage.items()
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
            for key, writes in self._writes().items()
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
        storage = self._storage()
        items = sorted(storage.items(), key=lambda kv: kv[0][2])
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
    thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
) VALUES (:thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, :type, :checkpoint, :metadata)
ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET
    parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
    checkpoint = EXCLUDED.checkpoint,
    metadata = EXCLUDED.metadata
"""

_CHECKPOINT_GET = """
SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
FROM harness_checkpoints
WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
  AND checkpoint_id = :checkpoint_id
"""

_CHECKPOINT_GET_LATEST = """
SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
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


def get_default_checkpointer() -> BaseCheckpointSaver:
    """生产默认 Checkpointer。

    当前返回线程隔离的内存实现（单副本运行安全）；PG 持久化引擎接入后
    返回 ``PgCheckpointer``（表结构迁移已就绪）。
    """
    return InMemoryCheckpointer()
