"""来源约束：无来源文本不能进入知识槽，冲突版本只保留可信候选。"""

from __future__ import annotations

from app.harness.contracts.memory import MemoryRecord


def has_trusted_provenance(record: MemoryRecord) -> bool:
    """知识材料必须同时拥有来源、版本和非空正文。"""
    return bool(record.source_id.strip() and record.version >= 1 and record.text.strip())


def discard_conflicting_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """同一来源只保留最高版本、最高分记录，防止旧摘要覆盖已撤销事实。"""
    selected: dict[str, MemoryRecord] = {}
    for record in records:
        if record.record_type == "knowledge" and not has_trusted_provenance(record):
            continue
        previous = selected.get(record.source_id)
        if previous is None or (record.version, record.score, record.record_id) > (
            previous.version,
            previous.score,
            previous.record_id,
        ):
            selected[record.source_id] = record
    return list(selected.values())
