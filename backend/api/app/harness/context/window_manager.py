"""窗口构建与 token 账本：不可降级槽位优先，observation 紧邻用户输入。"""

from collections import defaultdict

from app.harness.contracts.context import CompiledContext, ContextItem, TokenLedger

from .policies import IMMUTABLE_SLOTS, SLOT_ORDER, WindowPolicy
from .summarizer import estimate_tokens


def _ledger_slot(slot: str) -> str:
    """将内部 slot 收敛为公开 TokenLedger 键名。"""
    return {"system": "system", "user_input": "user_input", "session_state": "session_state"}.get(
        slot,
        "observations" if slot == "observation" else "knowledge" if slot == "knowledge" else "history",
    )


def build_window(items: list[ContextItem], *, policy: WindowPolicy) -> CompiledContext:
    """按固定槽位顺序构造最小 Lost-in-the-Middle 布局与消息列表。"""
    grouped: dict[str, list[ContextItem]] = defaultdict(list)
    for item in items:
        if item.text.strip():
            grouped[item.slot].append(item)
    selected: list[ContextItem] = []
    used = 0
    ledger_values: dict[str, int] = defaultdict(int)
    for slot in SLOT_ORDER:
        slot_cap = policy.slot_budget(slot)
        slot_used = 0
        for item in grouped.get(slot, []):
            token_cost = item.token_cost or estimate_tokens(item.text)
            if slot not in IMMUTABLE_SLOTS and (
                used + token_cost > policy.max_tokens or slot_used + token_cost > slot_cap
            ):
                continue
            normalized = item.model_copy(update={"token_cost": token_cost})
            selected.append(normalized)
            used += token_cost
            slot_used += token_cost
            ledger_values[_ledger_slot(slot)] += token_cost
    ledger = TokenLedger(
        system=ledger_values["system"],
        user_input=ledger_values["user_input"],
        session_state=ledger_values["session_state"],
        observations=ledger_values["observations"],
        knowledge=ledger_values["knowledge"],
        history=ledger_values["history"],
        total=used,
        max_tokens=policy.max_tokens,
    )
    messages = [
        {"role": "system" if item.slot in {"system", "session_state"} else "user", "content": item.text}
        for item in selected
    ]
    return CompiledContext(items=selected, ledger=ledger, messages=messages)
