"""阶段 4.1 回归：归属 ACL、消息角色、Redis 容错与 PG 对话 Port 活路径。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agent.context import history_for_plan
from app.errors import AppError, ErrorCode
from app.harness.context.compiler import compile_context
from app.harness.contracts.memory import MemoryQuery, MemoryRecord
from app.harness.contracts.trace import TraceContext, using_trace
from app.harness.memory.conversation_store import ConversationMemoryPort
from app.harness.memory.ports import InMemoryMemoryPort
from app.harness.memory.retention import MemoryRetention
from app.harness.memory.runtime import append_persisted_conversation_message
from app.harness.memory.short_term_redis import RedisMemoryPort
from app.harness.orchestration.session_runtime import _deliver_sentence
from app.models import Message
from app.models import Session as AgentSession


def _trace() -> TraceContext:
    """创建本模块共享的完整 trace，避免测试走空 trace 分支。"""
    return TraceContext(trace_id="trace-activation", span_id="span-activation", turn_id="turn-activation")


def _query(trace: TraceContext, *, user_id: str = "owner-1") -> MemoryQuery:
    """创建会话对话查询。"""
    return MemoryQuery(
        query_text="history",
        tenant_id="internal",
        user_id=user_id,
        session_id="session-1",
        record_types=["conversation"],
        trace_id=trace.trace_id,
    )


def _conversation(
    record_id: str,
    text: str,
    *,
    role: str = "user",
    timestamp: str = "2026-08-22T00:00:00+00:00",
) -> MemoryRecord:
    """构造完整归属的对话记录。"""
    return MemoryRecord(
        record_id=record_id,
        source_id=f"message:{record_id}",
        text=text,
        record_type="conversation",
        timestamp=timestamp,
        metadata={
            "tenant_id": "internal",
            "user_id": "owner-1",
            "session_id": "session-1",
            "role": role,
        },
    )


class _FakePipeline:
    """以同步即时执行模拟 redis-py pipeline，覆盖本模块实际调用的最小接口。"""

    def __init__(self, client: _FakeRedis) -> None:
        self._client = client

    def __enter__(self) -> _FakePipeline:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def rpush(self, key: str, *values: str) -> _FakePipeline:
        self._client.rpush(key, *values)
        return self

    def expire(self, key: str, ttl: int) -> _FakePipeline:
        self._client.expire(key, ttl)
        return self

    def sadd(self, key: str, value: str) -> _FakePipeline:
        self._client.sadd(key, value)
        return self

    def delete(self, key: str) -> _FakePipeline:
        self._client.delete(key)
        return self

    def execute(self) -> list[object]:
        return []


class _FakeRedis:
    """无需真实 Redis 服务的内存替身，保留 list/set/TTL 语义。"""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}
        self.values: dict[str, str] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    def lrange(self, key: str, _start: int, _end: int) -> list[str]:
        return list(self.lists.get(key, []))

    def rpush(self, key: str, *values: str) -> int:
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    def sadd(self, key: str, value: str) -> int:
        self.sets.setdefault(key, set()).add(value)
        return 1

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def scan_iter(self, *, match: str) -> list[str]:
        assert match == "harness:memory:*:records"
        return [key for key in self.lists if key.startswith("harness:memory:") and key.endswith(":records")]

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    def delete(self, key: str) -> int:
        existed = key in self.lists or key in self.sets or key in self.values
        self.lists.pop(key, None)
        self.sets.pop(key, None)
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.ttls[key] = ex
        return True


class _FakeQuery:
    """只实现 ConversationMemoryPort 所需的链式 ORM 接口。"""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def filter(self, *_args: object) -> _FakeQuery:
        return self

    def order_by(self, *_args: object) -> _FakeQuery:
        return self

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeDb:
    """按模型返回预设会话或消息行，记录提交与回滚次数。"""

    def __init__(self, session: object | None, messages: list[object]) -> None:
        self.session = session
        self.messages = messages
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model: object) -> _FakeQuery:
        if model is AgentSession:
            return _FakeQuery([self.session] if self.session is not None else [])
        assert model is Message
        return _FakeQuery(self.messages)

    def commit(self) -> None:
        self.commits += 1

    def add(self, row: object) -> None:
        self.added.append(row)

    def rollback(self) -> None:
        self.rollbacks += 1


def test_unscoped_conversation_is_rejected_and_not_visible() -> None:
    """缺 tenant/user/session 的对话既不能写入，也不能经手工脏数据越权召回。"""
    async def body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        malformed = MemoryRecord(
            record_id="unscoped",
            source_id="message:unscoped",
            text="不应跨会话可见",
            record_type="conversation",
        )
        with pytest.raises(AppError) as exc:
            await port.append(malformed, trace=trace)
        assert exc.value.code == ErrorCode.VALIDATION
        port.records.append(malformed)
        assert await port.retrieve(_query(trace), trace=trace) == []

    asyncio.run(body())


def test_compiled_context_preserves_assistant_role_and_history_order() -> None:
    """对话记录按时间正序输出，assistant 不能在窗口序列化时变成 user。"""
    async def body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        await port.append(
            _conversation("first", "用户第一句", timestamp="2026-08-22T00:00:00+00:00"), trace=trace
        )
        await port.append(
            _conversation(
                "second",
                "助手第一句",
                role="assistant",
                timestamp="2026-08-22T00:01:00+00:00",
            ),
            trace=trace,
        )
        compiled = await compile_context(
            port=port,
            query=_query(trace),
            trace=trace,
            system_prompt="系统",
            user_input="当前问题",
        )
        assert compiled.messages == [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "当前问题"},
            {"role": "user", "content": "用户第一句"},
            {"role": "assistant", "content": "助手第一句"},
        ]

    asyncio.run(body())


def test_redis_port_is_idempotent_and_forget_tolerates_corruption() -> None:
    """Redis 重复 append 只保留一条，坏序列化记录不得阻断撤权。"""
    async def body() -> None:
        trace = _trace()
        client = _FakeRedis()
        port = RedisMemoryPort(client, retention=MemoryRetention(ttl_seconds=30))
        first = _conversation("redis-1", "初始文本")
        second = first.model_copy(update={"text": "覆盖后的文本"})
        await port.append(first, trace=trace)
        await port.append(second, trace=trace)
        records_key = port._records_key(_query(trace), trace.trace_id)
        assert len(client.lrange(records_key, 0, -1)) == 1
        assert client.ttl(records_key) == 30
        client.rpush(records_key, "{坏数据")
        await port.forget(first.source_id, trace=trace)
        assert await port.retrieve(_query(trace), trace=trace) == []

    asyncio.run(body())


def test_conversation_store_enforces_owner_and_emits_provenance() -> None:
    """PG Port 只返回 owner 对应会话，且把角色、来源和 trace 列带入记录。"""
    async def body() -> None:
        trace = _trace()
        row = SimpleNamespace(
            id="m-1",
            role="assistant",
            content="已归档回复",
            created_at=datetime(2026, 8, 22, tzinfo=UTC),
            origin_trace_id="origin-trace",
            origin_span_id="origin-span",
            memory_forgotten=False,
        )
        owner_session = SimpleNamespace(user_id="owner-1")
        port = ConversationMemoryPort(_FakeDb(owner_session, [row]), tenant_id="internal")
        records = await port.retrieve(_query(trace), trace=trace)
        assert [(item.source_id, item.metadata["role"], item.origin_trace_id) for item in records] == [
            ("message:m-1", "assistant", "origin-trace")
        ]
        foreign_port = ConversationMemoryPort(
            _FakeDb(SimpleNamespace(user_id="owner-2"), [row]), tenant_id="internal"
        )
        assert await foreign_port.retrieve(_query(trace), trace=trace) == []

    asyncio.run(body())


def test_conversation_store_append_rejects_foreign_owner() -> None:
    """写入侧必须复核会话 owner，不能仅相信 MemoryRecord 的 metadata。"""

    async def body() -> None:
        trace = _trace()
        row = SimpleNamespace(
            id="m-foreign",
            session_id="session-1",
            origin_trace_id=None,
            origin_span_id=None,
        )
        db = _FakeDb(SimpleNamespace(user_id="owner-2"), [row])
        port = ConversationMemoryPort(db, tenant_id="internal")
        with pytest.raises(AppError) as exc:
            await port.append(_conversation("m-foreign", "不得越权写入"), trace=trace)
        assert exc.value.code == ErrorCode.UNAUTHORIZED
        assert db.commits == 0

    asyncio.run(body())


def test_conversation_store_respects_compact_boundary_before_recall() -> None:
    """压缩后只从 compact_keep_from 召回，不能把已归入摘要的原文放回规划历史。"""
    async def body() -> None:
        trace = _trace()
        rows = [
            SimpleNamespace(
                id=f"m-{index}",
                role="user" if index % 2 else "assistant",
                content=f"消息 {index}",
                created_at=datetime(2026, 8, 22, 0, index, tzinfo=UTC),
                origin_trace_id=None,
                origin_span_id=None,
                memory_forgotten=False,
            )
            for index in range(1, 4)
        ]
        session = SimpleNamespace(user_id="owner-1", compact_keep_from="m-2")
        records = await ConversationMemoryPort(_FakeDb(session, rows), tenant_id="internal").retrieve(
            _query(trace), trace=trace
        )
        assert [record.source_id for record in records] == ["message:m-2", "message:m-3"]

    asyncio.run(body())


def test_persisted_message_is_written_to_memory_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """已提交的 user/assistant 消息必须携带归属和 trace 写入组合记忆。"""
    async def body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        monkeypatch.setattr("app.harness.memory.runtime.memory_port_for_session", lambda _db: port)
        session = SimpleNamespace(id="session-1", user_id="owner-1")
        db = _FakeDb(session, [])
        for message_id, role in (("m-user", "user"), ("m-assistant", "assistant")):
            message = SimpleNamespace(
                id=message_id,
                session_id="session-1",
                role=role,
                content=f"{role} 需要进入短期记忆",
                created_at=datetime(2026, 8, 22, tzinfo=UTC),
                origin_trace_id=trace.trace_id,
                origin_span_id=trace.span_id,
            )
            await append_persisted_conversation_message(db, message, trace=trace)
        assert [
            (record.record_id, record.metadata["role"], record.origin_trace_id)
            for record in port.records
        ] == [
            ("message:m-user", "user", trace.trace_id),
            ("message:m-assistant", "assistant", trace.trace_id),
        ]

    asyncio.run(body())


def test_deliver_sentence_writes_assistant_message_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """助手交付句提交成功后必须进入记忆适配器，不能只写 messages 表。"""
    async def body() -> None:
        trace = _trace()
        db = _FakeDb(SimpleNamespace(id="session-1", user_id="owner-1"), [])
        captured: list[tuple[object, int, TraceContext]] = []

        async def append_message(_db: object, message: object, *, trace: TraceContext) -> None:
            captured.append((message, db.commits, trace))

        async def emit(_event: str, _payload: dict, *, task_id: str | None = None) -> int:
            return 1

        monkeypatch.setattr(
            "app.harness.orchestration.session_runtime.append_persisted_conversation_message",
            append_message,
        )
        with using_trace(trace):
            await _deliver_sentence(db, "session-1", emit, "助手回复")
        assert len(db.added) == 1
        assert [(message.role, message.content, commits, item_trace) for message, commits, item_trace in captured] == [
            ("assistant", "助手回复", 1, trace)
        ]

    asyncio.run(body())


def test_history_for_plan_uses_memory_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent 活路径经编译器取历史，保留 assistant 角色而非直接调用 window_rows。"""
    async def body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        await port.append(
            _conversation("u-1", "用户历史", timestamp="2026-08-22T00:00:00+00:00"), trace=trace
        )
        await port.append(
            _conversation(
                "a-1",
                "助手历史",
                role="assistant",
                timestamp="2026-08-22T00:01:00+00:00",
            ),
            trace=trace,
        )
        monkeypatch.setattr("app.agent.context.memory_port_for_session", lambda _db: port)
        session = AgentSession(id="session-1", user_id="owner-1", title="测试会话")
        history = await history_for_plan(object(), session, trace=trace)
        assert history == [
            {"role": "user", "content": "用户历史"},
            {"role": "assistant", "content": "助手历史"},
        ]

    asyncio.run(body())
