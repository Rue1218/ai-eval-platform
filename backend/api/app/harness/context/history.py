"""规划历史编译：Context 只经 MemoryPort 读取会话素材。"""

from app.harness.context.compiler import compile_context
from app.harness.contracts.memory import MemoryPort, MemoryQuery
from app.harness.contracts.trace import TraceContext


async def history_for_plan(
    *,
    port: MemoryPort,
    tenant_id: str,
    user_id: str,
    session_id: str,
    trace: TraceContext,
    top_k_recall: int,
) -> list[dict[str, str]]:
    """编译规划历史，保留 user/assistant 角色且不让 Context 接触数据库会话。"""
    query = MemoryQuery(
        query_text="plan-history",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        record_types=["conversation"],
        top_k_recall=top_k_recall,
        trace_id=trace.trace_id,
    )
    compiled = await compile_context(
        port=port,
        query=query,
        trace=trace.child("context_retrieve"),
        system_prompt="",
        user_input="",
    )
    return [
        {"role": message["role"], "content": message["content"]}
        for message in compiled.messages
        if message["role"] in {"user", "assistant"}
    ]
