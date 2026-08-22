"""阶段 4 记忆 Port 与 Context 编译器的纯内存回归测试。"""

import asyncio

import pytest

from app.errors import AppError, ErrorCode
from app.harness.context.compiler import compile_context
from app.harness.context.policies import WindowPolicy
from app.harness.contracts.memory import MemoryQuery, MemoryRecord
from app.harness.contracts.trace import TraceContext
from app.harness.memory.ports import InMemoryMemoryPort


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


def test_memory_port_rejects_empty_scope_and_cross_trace():
    """缺租户/用户/会话或跨 trace 不能伪装成无记忆命中。"""
    async def body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        with pytest.raises(AppError) as scope_exc:
            await port.retrieve(MemoryQuery(query_text="x", trace_id=trace.trace_id), trace=trace)
        assert scope_exc.value.code == ErrorCode.VALIDATION
        with pytest.raises(AppError) as trace_exc:
            await port.retrieve(
                _query(trace),
                trace=TraceContext(trace_id="other", span_id="other-span", turn_id="other-turn"),
            )
        assert trace_exc.value.code == ErrorCode.INTERNAL

    asyncio.run(body())


def test_memory_port_filters_acl_and_forget_source():
    """知识必须显式授权，forget 后同一来源不能再次进入候选。"""
    async def body() -> None:
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
        assert [item.record_id for item in await port.retrieve(_query(trace), trace=trace)] == ["conversation-1"]
        assert [item.record_id for item in await port.retrieve(_query(trace, permitted=["kb-doc-1"]), trace=trace)] == ["conversation-1", "knowledge-1"]
        await port.forget("kb-doc-1", trace=trace)
        assert [item.record_id for item in await port.retrieve(_query(trace, permitted=["kb-doc-1"]), trace=trace)] == ["conversation-1"]

    asyncio.run(body())


def test_compile_context_keeps_minimal_layout_and_drops_untrusted_knowledge():
    """System、用户与 observation 的位置固定；无来源知识不允许占据知识槽。"""
    async def body() -> None:
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
        # 模拟异常导入留下的无来源记录，编译器仍必须拒绝它进入知识槽。
        port.records.append(MemoryRecord(record_id="knowledge-bad", source_id="", record_type="knowledge", text="无来源知识", score=1.0, metadata={"tenant_id": "internal"}))
        compiled = await compile_context(
            port=port,
            query=_query(trace, permitted=["kb-1"]),
            trace=trace,
            system_prompt="系统约束",
            user_input="用户问题",
            observations=[{"name": "tool", "ok": True}],
            compact_summary="已有会话摘要",
        )
        assert [item.slot for item in compiled.items] == ["system", "session_state", "user_input", "observation", "knowledge"]
        assert compiled.items[-1].provenance is not None
        assert compiled.items[-1].provenance.source_id == "kb-1"
        assert compiled.ledger.total == sum(item.token_cost for item in compiled.items)

    asyncio.run(body())


def test_window_never_discards_system_or_user_input_when_budget_is_exceeded():
    """不可降级槽位超额仍保留，知识材料则按策略淘汰。"""
    async def body() -> None:
        trace = _trace()
        port = InMemoryMemoryPort()
        await port.append(MemoryRecord(record_id="knowledge-1", source_id="kb-1", record_type="knowledge", text="知识" * 200, metadata={"tenant_id": "internal"}), trace=trace)
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

    asyncio.run(body())
