"""阶段 4.2 容器集成验收：真实 pgvector 与 Redis 的 MemoryPort 行为。"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.harness.contracts.memory import MemoryQuery, MemoryRecord
from app.harness.contracts.trace import TraceContext
from app.harness.memory.long_term_pgvector import PgvectorKnowledgeMemoryPort
from app.harness.memory.retention import MemoryRetention
from app.harness.memory.short_term_redis import RedisMemoryPort

pytestmark = pytest.mark.memory_integration


def _required_url(name: str) -> str:
    """仅在专用 CI 服务环境读取连接串；日常单元测试不要求本机容器。"""
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"未配置 {name}，跳过容器集成测试")
    return value


def _trace(suffix: str) -> TraceContext:
    """为每次集成测试创建互不冲突的 Trace 范围。"""
    return TraceContext(
        trace_id=f"container-trace-{suffix}",
        span_id=f"container-span-{suffix}",
        turn_id=f"container-turn-{suffix}",
    )


def test_memory_ports_with_real_pgvector_and_redis() -> None:
    """迁移后的容器必须支持向量 ACL/撤权和 Redis TTL，不依赖任何外部模型服务。"""
    if os.getenv("RUN_MEMORY_CONTAINER_TESTS") != "1":
        pytest.skip("仅 CI 的 pgvector/Redis 服务环境执行")

    async def body() -> None:
        suffix = uuid4().hex
        trace = _trace(suffix)
        database_url = _required_url("MEMORY_INTEGRATION_DATABASE_URL")
        redis_url = _required_url("MEMORY_INTEGRATION_REDIS_URL")
        source_id = f"document:container-{suffix}"
        record_id = f"knowledge:container-{suffix}"
        session_id = f"session-{suffix}"
        engine = create_engine(database_url, future=True)
        db = Session(bind=engine)
        redis = Redis.from_url(redis_url, decode_responses=True)
        try:
            assert db.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            ).scalar_one()

            knowledge_port = PgvectorKnowledgeMemoryPort(db=db, tenant_id="internal")
            knowledge = MemoryRecord(
                record_id=record_id,
                source_id=source_id,
                version=1,
                text="仅 owner-container 可见的 pgvector 知识",
                record_type="knowledge",
                embedding=[0.1, 0.2, 0.3],
                metadata={
                    "tenant_id": "internal",
                    "allowed_user_ids": ["owner-container"],
                    "authority": 0.8,
                },
            )
            await knowledge_port.append(knowledge, trace=trace)
            query = MemoryQuery(
                query_text="容器知识查询",
                tenant_id="internal",
                user_id="owner-container",
                session_id=session_id,
                permitted_resource_ids=[source_id],
                record_types=["knowledge"],
                query_embedding=[0.1, 0.2, 0.3],
                trace_id=trace.trace_id,
            )
            assert [record.record_id for record in await knowledge_port.retrieve(query, trace=trace)] == [
                record_id
            ]
            assert await knowledge_port.retrieve(
                query.model_copy(update={"user_id": "foreign-container"}), trace=trace
            ) == []
            await knowledge_port.forget(source_id, trace=trace)
            assert await knowledge_port.retrieve(query, trace=trace) == []

            redis_port = RedisMemoryPort(redis, retention=MemoryRetention(ttl_seconds=60))
            conversation = MemoryRecord(
                record_id=f"message:container-{suffix}",
                source_id=f"message:container-{suffix}",
                text="Redis 短期记忆",
                record_type="conversation",
                metadata={
                    "tenant_id": "internal",
                    "user_id": "owner-container",
                    "session_id": session_id,
                    "role": "user",
                },
            )
            await redis_port.append(conversation, trace=trace)
            conversation_query = query.model_copy(
                update={
                    "record_types": ["conversation"],
                    "query_embedding": None,
                    "permitted_resource_ids": [],
                }
            )
            records_key = redis_port._records_key(conversation_query, trace.trace_id)
            assert 0 < redis.ttl(records_key) <= 60
            assert [record.record_id for record in await redis_port.retrieve(conversation_query, trace=trace)] == [
                conversation.record_id
            ]
            await redis_port.forget(conversation.source_id, trace=trace)
            assert await redis_port.retrieve(conversation_query, trace=trace) == []
        finally:
            db.execute(text("DELETE FROM memory_knowledge WHERE record_id = :record_id"), {"record_id": record_id})
            db.commit()
            db.close()
            engine.dispose()
            redis.close()

    asyncio.run(body())
