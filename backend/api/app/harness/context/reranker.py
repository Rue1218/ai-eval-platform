"""确定性重排序：先信任、再相关度、最后稳定 ID；不把向量原始排序直接塞窗口。"""

from app.harness.contracts.memory import MemoryRecord


def rerank_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """使用可审计启发式完成首期权威与多样性最小切片。"""
    def rank(record: MemoryRecord) -> tuple[float, float, str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        return (float(metadata.get("authority", 0.0) or 0.0), record.score, record.record_id)

    seen_sources: set[str] = set()
    ranked: list[MemoryRecord] = []
    for record in sorted(records, key=rank, reverse=True):
        if record.source_id in seen_sources:
            continue
        seen_sources.add(record.source_id)
        ranked.append(record)
    return ranked
