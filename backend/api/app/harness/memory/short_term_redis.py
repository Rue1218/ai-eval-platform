"""Redis 短期记忆：会话索引、回合记录与幂等键均显式携带 trace。"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from app.errors import AppError, ErrorCode
from app.harness.contracts.memory import (
    MemoryPort,
    MemoryQuery,
    MemoryRecord,
    validate_memory_query,
)
from app.harness.contracts.trace import TraceContext

from .ports import is_record_visible
from .retention import MemoryRetention


class RedisMemoryPort(MemoryPort):
    """同步 Redis 客户端的异步 Port 适配；连接失败必须上浮，不能伪装空召回。"""

    def __init__(self, client: Any, *, retention: MemoryRetention | None = None) -> None:
        self._client = client
        self._retention = retention or MemoryRetention()

    @classmethod
    def from_url(cls, url: str, *, retention: MemoryRetention | None = None) -> RedisMemoryPort:
        """按需导入 Redis SDK，单元测试无需安装或启动 Redis。"""
        try:
            from redis import Redis
        except ImportError as exc:
            raise AppError(ErrorCode.INTERNAL, "记忆服务依赖不可用") from exc
        return cls(Redis.from_url(url, decode_responses=True), retention=retention)

    @staticmethod
    def _scope_prefix(*, tenant_id: str, user_id: str, session_id: str) -> str:
        """构造不可含用户原文的稳定作用域键前缀。"""
        return f"harness:memory:tenant:{tenant_id}:user:{user_id}:session:{session_id}"

    def _records_key(self, query: MemoryQuery, trace_id: str) -> str:
        """每回合记录键必须含 trace_id，满足审计与失效隔离要求。"""
        return f"{self._scope_prefix(tenant_id=query.tenant_id, user_id=query.user_id, session_id=query.session_id)}:trace:{trace_id}:records"

    def _trace_index_key(self, query: MemoryQuery) -> str:
        """会话索引只保存 trace_id，供后续回合跨 trace 召回短期记录。"""
        return f"{self._scope_prefix(tenant_id=query.tenant_id, user_id=query.user_id, session_id=query.session_id)}:traces"

    def _raise_upstream(self, exc: Exception) -> AppError:
        """Redis 细节只进服务端日志；浏览器得到统一 UPSTREAM。"""
        from app.agent.log import agent_trace

        agent_trace(f"memory Redis异常 type={type(exc).__name__}")
        return AppError(ErrorCode.UPSTREAM, "记忆服务不可用")

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        """遍历本会话尚未过期的 trace 键并在内存中执行 ACL 过滤。"""
        validate_memory_query(query, trace)
        try:
            return await asyncio.to_thread(self._retrieve_sync, query)
        except AppError:
            raise
        except Exception as exc:
            raise self._raise_upstream(exc) from exc

    def _retrieve_sync(self, query: MemoryQuery) -> list[MemoryRecord]:
        """Redis 同步读取实现；只在本模块访问客户端。"""
        trace_ids = self._client.smembers(self._trace_index_key(query)) or set()
        records: list[MemoryRecord] = []
        for trace_id in sorted(str(item) for item in trace_ids):
            for raw in self._client.lrange(self._records_key(query, trace_id), 0, -1) or []:
                try:
                    record = MemoryRecord.model_validate_json(raw)
                except ValueError:
                    continue
                if record.record_type in query.record_types and is_record_visible(record, query):
                    records.append(record)
        return sorted(records, key=lambda item: (-item.score, item.record_id))[: query.top_k_recall]

    async def append(self, record: MemoryRecord, *, trace: TraceContext) -> None:
        """以记录 metadata 的归属写入本回合 Redis 列表并设置 TTL。"""
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        try:
            query = MemoryQuery(
                query_text="append",
                tenant_id=str(metadata.get("tenant_id") or ""),
                user_id=str(metadata.get("user_id") or ""),
                session_id=str(metadata.get("session_id") or ""),
                trace_id=trace.trace_id,
            )
            validate_memory_query(query, trace)
            normalized = record.model_copy(
                update={
                    "origin_trace_id": record.origin_trace_id or trace.trace_id,
                    "origin_span_id": record.origin_span_id or trace.span_id,
                }
            )
            await asyncio.to_thread(self._append_sync, query, normalized)
        except AppError:
            raise
        except Exception as exc:
            raise self._raise_upstream(exc) from exc

    def _append_sync(self, query: MemoryQuery, record: MemoryRecord) -> None:
        """用 pipeline 保证记录键与会话 trace 索引有相同 TTL。"""
        ttl = self._retention.normalized_ttl()
        record_key = self._records_key(query, query.trace_id)
        index_key = self._trace_index_key(query)
        with self._client.pipeline() as pipeline:
            pipeline.rpush(record_key, record.model_dump_json())
            pipeline.expire(record_key, ttl)
            pipeline.sadd(index_key, query.trace_id)
            pipeline.expire(index_key, ttl)
            pipeline.execute()

    async def forget(self, source_id: str, *, trace: TraceContext) -> None:
        """扫描短期记录并重写受影响列表，撤权后不允许继续命中缓存。"""
        if not source_id.strip():
            raise AppError(ErrorCode.VALIDATION, "记忆来源不可为空")
        try:
            await asyncio.to_thread(self._forget_sync, source_id)
        except Exception as exc:
            raise self._raise_upstream(exc) from exc

    def _forget_sync(self, source_id: str) -> None:
        """只扫描本模块自己的 records 键，不触碰审计或 abort 数据。"""
        for key in self._client.scan_iter(match="harness:memory:*:records"):
            values = self._client.lrange(key, 0, -1) or []
            kept = []
            for raw in values:
                try:
                    record = MemoryRecord.model_validate_json(raw)
                except ValueError:
                    continue
                if record.source_id != source_id:
                    kept.append(raw)
            if len(kept) == len(values):
                continue
            ttl = self._client.ttl(key)
            with self._client.pipeline() as pipeline:
                pipeline.delete(key)
                if kept:
                    pipeline.rpush(key, *kept)
                    pipeline.expire(key, ttl if ttl > 0 else self._retention.normalized_ttl())
                pipeline.execute()

    async def put_idempotency_key(self, key: str, *, trace: TraceContext) -> None:
        """记录可过期幂等键；用户原文只使用哈希，原键不进 Redis key。"""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        redis_key = f"harness:memory:idempotency:trace:{trace.trace_id}:{digest}"
        try:
            await asyncio.to_thread(self._client.set, redis_key, "1", ex=self._retention.normalized_ttl())
        except Exception as exc:
            raise self._raise_upstream(exc) from exc

    async def has_idempotency_key(self, key: str, *, trace: TraceContext) -> bool:
        """查询同一 trace 的幂等键，过期后自然视为未见。"""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        redis_key = f"harness:memory:idempotency:trace:{trace.trace_id}:{digest}"
        try:
            return bool(await asyncio.to_thread(self._client.exists, redis_key))
        except Exception as exc:
            raise self._raise_upstream(exc) from exc
