"""独立大模型调用层公开门面。

本门面只暴露模型协议调用、流式读取、协议档信息和结构化解析；
Agent Harness、ReAct、确认卡、事件和 Worker 均不得在此实现。
"""

from app.adapters import call_protocol, stream_protocol

from .client import (
    CALL_TIMEOUT_S,
    STREAM_TIMEOUT_S,
    AgentCallResult,
    AgentJsonStreamResult,
    AgentProfilePublicInfo,
    call_agent_model,
    call_agent_model_detailed,
    get_agent_profile_public_info,
    resolve_agent_profile,
    stream_agent_json,
    stream_agent_model,
)
from .structured import parse_json_candidates

__all__ = [
    "CALL_TIMEOUT_S",
    "STREAM_TIMEOUT_S",
    "AgentCallResult",
    "AgentJsonStreamResult",
    "AgentProfilePublicInfo",
    "call_agent_model",
    "call_agent_model_detailed",
    "call_protocol",
    "get_agent_profile_public_info",
    "parse_json_candidates",
    "resolve_agent_profile",
    "stream_agent_json",
    "stream_agent_model",
    "stream_protocol",
]
