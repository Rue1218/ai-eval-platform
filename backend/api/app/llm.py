"""Agent 协议档的短同步调用助手；正文在 harness.llm，本模块只再导出。"""

from __future__ import annotations

from app.adapters import call_protocol, stream_protocol
from app.harness.llm.client import (
    CALL_TIMEOUT_S,
    AgentCallResult,
    AgentProfilePublicInfo,
    call_agent_model,
    call_agent_model_detailed,
    get_agent_profile_public_info,
    resolve_agent_profile,
    stream_agent_model,
)
from app.harness.llm.structured import parse_json_candidates

_resolve_agent_profile = resolve_agent_profile

__all__ = [
    "CALL_TIMEOUT_S",
    "AgentCallResult",
    "AgentProfilePublicInfo",
    "call_agent_model",
    "call_agent_model_detailed",
    "call_protocol",
    "get_agent_profile_public_info",
    "parse_json_candidates",
    "resolve_agent_profile",
    "stream_agent_model",
    "stream_protocol",
]
