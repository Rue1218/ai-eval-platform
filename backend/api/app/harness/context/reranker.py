"""确定性重排序：会话历史保持检索时序，知识按权威、相关度、稳定 ID 重排。"""

from __future__ import annotations

from app.harness.contracts.memory import MemoryRecord


def rerank_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """使用可审计的启发式分数完成首期五信号中的权威与多样性最小切片。

    对话记录的时间序本身就是语义序，重排会打散轮次连贯性；因此只对知识证据
    排序，并在每个来源内保留最高优先级的一项（最小多样性约束）。
    """
    conversation: list[MemoryRecord] = []
    knowledge: list[MemoryRecord] = []
    for record in records:
        if record.record_type == "knowledge":
            knowledge.append(record)
        else:
            conversation.append(record)

    def rank(record: MemoryRecord) -> tuple[float, float, str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        authority = float(metadata.get("authority", 0.0) or 0.0)
        return (authority, record.score, record.record_id)

    seen_sources: set[str] = set()
    ranked_knowledge: list[MemoryRecord] = []
    for record in sorted(knowledge, key=rank, reverse=True):
        if record.source_id in seen_sources:
            continue
        seen_sources.add(record.source_id)
        ranked_knowledge.append(record)
    # 会话历史保持原顺序在前，重排后的知识证据追加在后。
    return conversation + ranked_knowledge
