"""确定性重排序：先信任、再相关度、最后稳定 ID；不把向量原始排序直接塞窗口。"""

from app.harness.contracts.memory import MemoryRecord


def rerank_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """知识按权威重排，对话历史保持时间正序，避免颠倒 user/assistant 语义。"""
    def rank(record: MemoryRecord) -> tuple[float, float, str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        return (float(metadata.get("authority", 0.0) or 0.0), record.score, record.record_id)

    knowledge_records = [record for record in records if record.record_type == "knowledge"]
    history_records = [record for record in records if record.record_type == "conversation"]
    seen_sources: set[str] = set()
    ranked: list[MemoryRecord] = []
    for record in sorted(knowledge_records, key=rank, reverse=True):
        if record.source_id in seen_sources:
            continue
        seen_sources.add(record.source_id)
        ranked.append(record)
    # ISO 8601 时间戳按字符串即可稳定排序；空时间戳再按 record_id，保证结果可审计。
    return ranked + sorted(history_records, key=lambda record: (record.timestamp, record.record_id))
