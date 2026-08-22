"""阶段 4 记忆 Port 与 Context 编译器的纯内存回归测试。"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.errors import AppError, ErrorCode
from app.harness.context.compiler import compile_context, compile_history_window
from app.harness.context.policies import WindowPolicy
from app.harness.contracts.memory import MemoryQuery, MemoryRecord
from app.harness.contracts.trace import TraceContext
from app.harness.memory.ports import CompositeMemoryPort, InMemoryMemoryPort
from app.harness.memory.short_term_redis import RedisMemoryPort


def _trace() -> TraceContext:
    """生成与检索请求同源的测试 trace。"""
    return TraceContext(trace_id="trace-memory", span_id="span-memory", turn_id="turn-memory")


def _query(trace: TraceContext, *, permitted: list[str] | None = None) -> MemoryQuery:
    """构造完整归属的查询，避免测试意外走空归属降级。"""
    return MemoryQuery(
        query_text="查询",
        tenant_id="internal",
        user_id="user-1",
        session_id="session-1",
        permitted_resource_ids=permitted or [],
        trace_id=trace.trace_id,
    )


class _FakeRedisPipeline:
    """用同步内存字典模拟 Redis pipeline，覆盖阶段 4 的短期存储语义。"""

    def __init__(self, client: _FakeRedis) -> None:
        self._client = client

    def __enter__(self) -> _FakeRedisPipeline:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def rpush(self, key: str, *values: str) -> None:
        self._client.rpush(key, *values)

    def expire(self, key: str, ttl: int) -> None:
        self._client.expire(key, ttl)

    def sadd(self, key: str, *values: str) -> None:
        self._client.sadd(key, *values)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def execute(self) -> None:
        return None


class _FakeRedis:
    """最小 Redis 桩：不依赖本机服务，验证 key、TTL、forget 与幂等键。"""

    def __init__(self) -> None:
        self.values: dict[str, list[str] | set[str] | str] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline(self)

    def rpush(self, key: str, *values: str) -> None:
        bucket = self.values.setdefault(key, [])
        assert isinstance(bucket, list)
        bucket.extend(values)

    def lrange(self, key: str, _start: int, _end: int) -> list[str]:
        bucket = self.values.get(key, [])
        return list(bucket) if isinstance(bucket, list) else []

    def sadd(self, key: str, *values: str) -> None:
        bucket = self.values.setdefault(key, set())
        assert isinstance(bucket, set)
        bucket.update(values)

    def smembers(self, key: str) -> set[str]:
        bucket = self.values.get(key, set())
        return set(bucket) if isinstance(bucket, set) else set()

    def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    def scan_iter(self, *, match: str) -> list[str]:
        assert match == "harness:memory:*:records"
        return [key for key in self.values if key.endswith(":records")]

    def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    def exists(self, key: str) -> int:
        return int(key in self.values)


def test_memory_port_rejects_empty_scope_and_cross_trace():
    """缺租户/用户/会话或跨 trace 不能伪装成无记忆命中。"""
    async def _body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        bad_scope = MemoryQuery(query_text="x", trace_id=trace.trace_id)
        with pytest.raises(AppError) as scope_exc:
            await port.retrieve(bad_scope, trace=trace)
        assert scope_exc.value.code == ErrorCode.VALIDATION

        query = _query(trace)
        with pytest.raises(AppError) as trace_exc:
            await port.retrieve(
                query,
                trace=TraceContext(trace_id="other-trace", span_id="span-other", turn_id="turn-other"),
            )
        assert trace_exc.value.code == ErrorCode.INTERNAL

    asyncio.run(_body())


def test_memory_port_filters_acl_and_forget_source():
    """知识必须显式授权，forget 后同一来源不能再次进入候选。"""
    async def _body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        await port.append(
            MemoryRecord(
                record_id="conversation-1",
                source_id="message-1",
                text="上一轮讨论了评测配置",
                metadata={"tenant_id": "internal", "user_id": "user-1", "session_id": "session-1"},
            ),
            trace=trace,
        )
        await port.append(
            MemoryRecord(
                record_id="knowledge-1",
                source_id="kb-doc-1",
                record_type="knowledge",
                text="授权知识片段",
                metadata={"tenant_id": "internal", "allowed_user_ids": ["user-1"]},
            ),
            trace=trace,
        )
        assert [item.record_id for item in await port.retrieve(_query(trace), trace=trace)] == [
            "conversation-1"
        ]
        assert [item.record_id for item in await port.retrieve(_query(trace, permitted=["kb-doc-1"]), trace=trace)] == [
            "conversation-1",
            "knowledge-1",
        ]
        await port.forget("kb-doc-1", trace=trace)
        assert [item.record_id for item in await port.retrieve(_query(trace, permitted=["kb-doc-1"]), trace=trace)] == [
            "conversation-1"
        ]

    asyncio.run(_body())


def test_compile_context_keeps_minimal_layout_and_drops_untrusted_knowledge():
    """System、用户与 observation 的位置固定；无来源知识不允许占据知识槽。"""
    async def _body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        await port.append(
            MemoryRecord(
                record_id="knowledge-ok",
                source_id="kb-1",
                version=2,
                record_type="knowledge",
                text="有来源的知识内容",
                score=0.8,
                metadata={"tenant_id": "internal", "authority": 0.9},
            ),
            trace=trace,
        )
        # 模拟旧数据/异常导入留下的无来源记录，编译器仍必须拒绝它进入知识槽。
        port.records.append(
            MemoryRecord(
                record_id="knowledge-bad",
                source_id="",
                record_type="knowledge",
                text="不能进入窗口的无来源知识",
                score=1.0,
                metadata={"tenant_id": "internal"},
            )
        )
        compiled = await compile_context(
            port=port,
            query=_query(trace, permitted=["kb-1"]),
            trace=trace,
            system_prompt="系统约束",
            user_input="用户问题",
            observations=[{"name": "tool", "ok": True}],
            compact_summary="已有会话摘要",
        )
        assert [item.slot for item in compiled.items] == [
            "system",
            "session_state",
            "user_input",
            "observation",
            "knowledge",
        ]
        assert compiled.items[-1].provenance is not None
        assert compiled.items[-1].provenance.source_id == "kb-1"
        assert compiled.ledger.total == sum(item.token_cost for item in compiled.items)

    asyncio.run(_body())


def test_window_never_discards_system_or_user_input_when_budget_is_exceeded():
    """不可降级槽位超过预算时仍保留，知识材料则按策略被淘汰。"""
    async def _body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        await port.append(
            MemoryRecord(
                record_id="knowledge-1",
                source_id="kb-1",
                record_type="knowledge",
                text="知识" * 200,
                metadata={"tenant_id": "internal"},
            ),
            trace=trace,
        )
        compiled = await compile_context(
            port=port,
            query=_query(trace, permitted=["kb-1"]),
            trace=trace,
            system_prompt="系统" * 100,
            user_input="用户" * 100,
            policy=WindowPolicy(max_tokens=10),
        )
        assert [item.slot for item in compiled.items] == ["system", "user_input"]
        assert compiled.ledger.total > compiled.ledger.max_tokens

    asyncio.run(_body())


class _ChronologicalStore:
    """按写入序返回会话记录的最小 Port 桩，模拟 ConversationStore 的时间序语义。"""

    def __init__(self, records: list[MemoryRecord]) -> None:
        self._records = records

    async def retrieve(self, query: MemoryQuery, *, trace: TraceContext) -> list[MemoryRecord]:
        return list(self._records)


def test_composite_merge_and_history_window_preserve_chronology():
    """随机 UUID 主键下，Composite 合并与历史窗口都不得按字典序打乱会话时间序。"""
    async def _body() -> None:
        trace = _trace()
        ids = [uuid.uuid4().hex for _ in range(6)]
        records = [
            MemoryRecord(
                record_id=ids[index],
                source_id=f"message-{index}",
                text=f"第{index}轮",
                score=1.0,
                metadata={
                    "tenant_id": "internal",
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "role": "user" if index % 2 == 0 else "assistant",
                },
            )
            for index in range(6)
        ]
        port = CompositeMemoryPort(conversation=_ChronologicalStore(records))

        kept = await compile_history_window(
            port=port,
            query=_query(trace),
            trace=trace,
            keep_from=ids[2],
            max_records=99,
        )
        assert [record.record_id for record in kept] == ids[2:]

        windowed = await compile_history_window(
            port=port,
            query=_query(trace),
            trace=trace,
            max_records=2,
        )
        assert [record.record_id for record in windowed] == ids[-2:]

    asyncio.run(_body())


def test_redis_memory_keeps_trace_keys_but_retrieves_same_session_history_and_forgets():
    """短期记录键含 trace，后续回合仍可经会话索引召回；forget 与幂等键可验证。"""
    async def _body() -> None:
        first_trace = _trace()
        second_trace = TraceContext(trace_id="trace-next", span_id="span-next", turn_id="turn-next")
        port = RedisMemoryPort(_FakeRedis())
        await port.append(
            MemoryRecord(
                record_id="short-1",
                source_id="message-1",
                text="短期会话记录",
                metadata={"tenant_id": "internal", "user_id": "user-1", "session_id": "session-1"},
            ),
            trace=first_trace,
        )
        assert [item.record_id for item in await port.retrieve(_query(second_trace), trace=second_trace)] == [
            "short-1"
        ]
        await port.put_idempotency_key("browser-message-id", trace=first_trace)
        assert await port.has_idempotency_key("browser-message-id", trace=first_trace)
        await port.forget("message-1", trace=second_trace)
        assert await port.retrieve(_query(second_trace), trace=second_trace) == []

    asyncio.run(_body())
