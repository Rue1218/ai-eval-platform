"""Context 编译器：召回、来源校验、压缩、重排与窗口构建均不依赖存储 SDK。"""

import json
from typing import Any

from app.harness.contracts.context import CompiledContext, ContextItem, Provenance
from app.harness.contracts.memory import MemoryPort, MemoryQuery
from app.harness.contracts.trace import TraceContext

from .policies import WindowPolicy
from .provenance import discard_conflicting_records
from .reranker import rerank_records
from .retriever_facade import retrieve_records
from .summarizer import compress_record, estimate_tokens
from .window_manager import build_window


def _observation_text(observation: dict[str, Any]) -> str:
    """将工具 observation 收敛为安全 JSON，位置固定在用户问题之后。"""
    return json.dumps(observation, ensure_ascii=False, separators=(",", ":"))


async def compile_context(
    *,
    port: MemoryPort,
    query: MemoryQuery,
    trace: TraceContext,
    system_prompt: str,
    user_input: str,
    observations: list[dict[str, Any]] | None = None,
    compact_summary: str | None = None,
    policy: WindowPolicy | None = None,
) -> CompiledContext:
    """产生唯一 CompiledContext；System、用户输入、observation 均有确定位置。"""
    window_policy = policy or WindowPolicy()
    records = rerank_records(discard_conflicting_records(await retrieve_records(port, query, trace=trace)))
    items: list[ContextItem] = [
        ContextItem(slot="system", text=system_prompt, priority="critical"),
        ContextItem(slot="user_input", text=user_input, priority="critical"),
    ]
    if compact_summary and compact_summary.strip():
        items.append(ContextItem(slot="session_state", text=compact_summary.strip(), priority="high"))
    for observation in observations or []:
        items.append(ContextItem(slot="observation", text=_observation_text(observation), priority="high"))
    for record in records:
        slot = "knowledge" if record.record_type == "knowledge" else "history"
        text = compress_record(record, max_tokens=window_policy.slot_budget(slot))
        if not text:
            continue
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        items.append(
            ContextItem(
                slot=slot,
                text=text,
                token_cost=estimate_tokens(text),
                provenance=Provenance(
                    source_id=record.source_id,
                    version=record.version,
                    timestamp=record.timestamp,
                    acl=record.acl,
                    authority=float(metadata.get("authority", 0.0) or 0.0),
                ),
            )
        )
    return build_window(items, policy=window_policy).model_copy(update={"compact_summary": compact_summary})
