"""阶段 4.2 pgvector 知识记忆单元回归：向量、ACL、撤权均不依赖真实容器。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from app.errors import AppError, ErrorCode
from app.harness.contracts.memory import MemoryQuery, MemoryRecord
from app.harness.contracts.trace import TraceContext
from app.harness.memory.long_term_pgvector import PgvectorKnowledgeMemoryPort


def _trace() -> TraceContext:
    """创建完整 trace，确保 Port 调用走生产同一校验路径。"""
    return TraceContext(trace_id="trace-pgvector", span_id="span-pgvector", turn_id="turn-pgvector")


def _query(trace: TraceContext, *, user_id: str = "owner-1") -> MemoryQuery:
    """创建带资源授权和查询向量的知识检索请求。"""
    return MemoryQuery(
        query_text="查找知识",
        tenant_id="internal",
        user_id=user_id,
        session_id="session-1",
        permitted_resource_ids=["document:alpha"],
        record_types=["knowledge"],
        query_embedding=[0.1, 0.2, 0.3],
        trace_id=trace.trace_id,
    )


def _record() -> MemoryRecord:
    """创建已授权、带来源与嵌入的知识记录。"""
    return MemoryRecord(
        record_id="knowledge-alpha-v1",
        source_id="document:alpha",
        version=1,
        text="仅供 owner-1 使用的知识正文",
        record_type="knowledge",
        acl="resource",
        embedding=[0.1, 0.2, 0.3],
        metadata={
            "tenant_id": "internal",
            "allowed_user_ids": ["owner-1"],
            "authority": 0.9,
        },
    )


class _Mappings:
    """模拟 SQLAlchemy mappings 结果，保持生产 Port 的取数接口不变。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        """返回预设行，避免单元测试依赖 PostgreSQL。"""
        return self._rows


class _Result:
    """只实现知识 Port 所需的 mappings 接口。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Mappings:
        """返回字典行读取器。"""
        return _Mappings(self._rows)


class _FakeDb:
    """记录 SQL 和参数，验证 Port 把 ACL 留在数据库过滤阶段。"""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[tuple[object, dict[str, Any]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement: object, params: dict[str, Any]) -> _Result:
        """保存绑定参数；不解析 SQL，查询返回预设 mappings。"""
        self.statements.append((statement, params))
        return _Result(self.rows)

    def commit(self) -> None:
        """记录事务提交。"""
        self.commits += 1

    def rollback(self) -> None:
        """记录失败回滚。"""
        self.rollbacks += 1


def _row() -> dict[str, Any]:
    """构造 pgvector 查询的单行返回值。"""
    return {
        "record_id": "knowledge-alpha-v1",
        "source_id": "document:alpha",
        "version": 1,
        "content": "仅供 owner-1 使用的知识正文",
        "acl": "resource",
        "origin_trace_id": "trace-pgvector",
        "origin_span_id": "span-pgvector",
        "tenant_id": "internal",
        "user_id": None,
        "session_id": None,
        "allowed_user_ids": ["owner-1"],
        "metadata": {"tenant_id": "forged", "allowed_user_ids": ["forged"]},
        "created_at": datetime(2026, 8, 22, tzinfo=UTC),
        "score": 0.99,
    }


def test_pgvector_port_writes_bound_vector_and_authorized_recall() -> None:
    """向量、正文和 ACL 均经绑定参数写入；回读必须用列值覆盖伪造 metadata。"""

    async def body() -> None:
        trace = _trace()
        db = _FakeDb(rows=[_row()])
        port = PgvectorKnowledgeMemoryPort(db=db, tenant_id="internal")
        await port.append(_record(), trace=trace)
        records = await port.retrieve(_query(trace), trace=trace)

        assert db.commits == 1
        append_sql, append_params = db.statements[0]
        assert "CAST(:embedding AS vector)" in str(append_sql)
        assert append_params["embedding"] == "[0.10000000000000001,0.20000000000000001,0.29999999999999999]"
        assert append_params["content"] == "仅供 owner-1 使用的知识正文"
        retrieve_sql, retrieve_params = db.statements[1]
        assert str(retrieve_sql).index("memory_forgotten IS FALSE") < str(retrieve_sql).index("ORDER BY")
        assert retrieve_params["permitted_resource_ids"] == ["document:alpha"]
        assert [(item.source_id, item.metadata["tenant_id"], item.score) for item in records] == [
            ("document:alpha", "internal", 0.99)
        ]

    asyncio.run(body())


def test_pgvector_port_rechecks_acl_and_forget_marks_source() -> None:
    """即使测试桩绕过 SQL ACL，Port 复核仍拒绝越权用户；撤权必须走持久化更新。"""

    async def body() -> None:
        trace = _trace()
        db = _FakeDb(rows=[_row()])
        port = PgvectorKnowledgeMemoryPort(db=db, tenant_id="internal")
        assert await port.retrieve(_query(trace, user_id="owner-2"), trace=trace) == []
        await port.forget("document:alpha", trace=trace)
        forget_sql, forget_params = db.statements[-1]
        assert "memory_forgotten = TRUE" in str(forget_sql)
        assert forget_params == {"source_id": "document:alpha", "tenant_id": "internal"}
        assert db.commits == 1

    asyncio.run(body())


def test_pgvector_port_rejects_missing_embedding_and_foreign_tenant() -> None:
    """知识写入必须有向量，且运行时实例不能写入其他租户。"""

    async def body() -> None:
        trace = _trace()
        port = PgvectorKnowledgeMemoryPort(db=_FakeDb(), tenant_id="internal")
        with pytest.raises(AppError) as missing_embedding:
            await port.append(_record().model_copy(update={"embedding": None}), trace=trace)
        assert missing_embedding.value.code == ErrorCode.VALIDATION

        foreign = _record().model_copy(update={"metadata": {"tenant_id": "other"}})
        with pytest.raises(AppError) as foreign_tenant:
            await port.append(foreign, trace=trace)
        assert foreign_tenant.value.code == ErrorCode.UNAUTHORIZED

    asyncio.run(body())
