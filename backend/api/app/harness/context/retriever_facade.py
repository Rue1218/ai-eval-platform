"""MemoryPort 查询编排；Context 只经协议取回候选，绝不触碰存储 SDK。"""

from app.harness.contracts.memory import (
    MemoryPort,
    MemoryQuery,
    MemoryRecord,
    validate_memory_query,
)
from app.harness.contracts.trace import TraceContext


async def retrieve_records(
    port: MemoryPort,
    query: MemoryQuery,
    *,
    trace: TraceContext,
) -> list[MemoryRecord]:
    """执行一次已校验的召回；空归属不是“无结果”，而是 VALIDATION。"""
    validate_memory_query(query, trace)
    return await port.retrieve(query, trace=trace)
