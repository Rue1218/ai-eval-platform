"""上下文编译产物：每项可追溯，并公开 token 预算账本。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """来源、时效、权限；冲突时由 Context 丢弃而非塞进窗口中部。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    version: int = 1
    timestamp: str = ""
    acl: str = "session"
    authority: float = 0.0


class ContextItem(BaseModel):
    """窗口中的独立证据单元。"""

    model_config = ConfigDict(extra="forbid")

    slot: str
    text: str
    token_cost: int = 0
    provenance: Provenance | None = None
    priority: str = "medium"


class TokenLedger(BaseModel):
    """CompiledContext 公开的 token 预算账本。"""

    model_config = ConfigDict(extra="forbid")

    system: int = 0
    user_input: int = 0
    session_state: int = 0
    observations: int = 0
    knowledge: int = 0
    history: int = 0
    total: int = 0
    max_tokens: int = 8000


class CompiledContext(BaseModel):
    """Context 层唯一产物：静态消息素材，不发起模型调用。"""

    model_config = ConfigDict(extra="forbid")

    items: list[ContextItem] = Field(default_factory=list)
    ledger: TokenLedger = Field(default_factory=TokenLedger)
    messages: list[dict[str, str]] = Field(default_factory=list)
    compact_summary: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
