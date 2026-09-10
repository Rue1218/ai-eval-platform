"""协议档编辑、能力投影与回合默认值共用的无网络思考校验。"""

from .llm.contracts import ModelConfig
from .llm.loop_contracts import LlmRequestError
from .llm.providers.catalog import detect_provider, reasoning_note
from .llm.resolver import resolve_request

EFFORTS = ("off", "low", "medium", "high", "max")


def profile_reasoning(protocol, base_url, model, max_tokens, *, full_url=False) -> dict:
    """返回由实际 resolver 校验过的档位；默认关闭不可能时明确返回可用开启档。"""
    provider = detect_provider(base_url, model, protocol)
    allowed = []
    for effort in EFFORTS:
        config = ModelConfig(protocol=protocol, base_url=base_url, model=model,
                             max_tokens=max_tokens, full_url=full_url, reasoning_enabled=effort != "off",
                             reasoning_effort=effort if effort != "off" else "medium")
        try:
            resolve_request(config, messages=[])
        except LlmRequestError:
            continue
        allowed.append(effort)
    preferred = "high" if provider == "anthropic" and model.lower().startswith("claude-") else "off"
    default = preferred if preferred in allowed else ("high" if "high" in allowed else next(iter(allowed), "off"))
    return {"provider": provider, "allowed_efforts": allowed,
            "reasoning_effort": default,
            "reasoning_note": reasoning_note(provider, model)}
