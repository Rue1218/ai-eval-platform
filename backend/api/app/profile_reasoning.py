"""协议档编辑、能力投影与回合默认值共用的无网络思考校验。"""

from __future__ import annotations

from collections.abc import Mapping

from .llm.contracts import ModelConfig
from .llm.loop_contracts import LlmRequestError
from .llm.providers.catalog import detect_provider, reasoning_note
from .llm.providers.reasoning_templates import ReasoningTemplate, ensure_template_compatible
from .llm.resolver import resolve_request

EFFORTS = ("off", "low", "medium", "high", "max")


def _probe_efforts(probe: object, template: ReasoningTemplate) -> tuple[str, ...]:
    """读取已持久化的探测结果；未验证和异常结构都不能放行运行时调用。"""
    if not isinstance(probe, Mapping) or probe.get("status") not in {"passed", "partial"}:
        return ()
    if probe.get("template_id") != template.id or probe.get("template_version") != template.version:
        return ()
    values = probe.get("supported_efforts")
    if not isinstance(values, list):
        return ()
    return tuple(effort for effort in template.allowed_efforts if effort in values)


def profile_reasoning(
    protocol,
    base_url,
    model,
    max_tokens,
    *,
    full_url=False,
    reasoning_template_id: str | None = None,
    reasoning_probe: object = None,
) -> dict:
    """返回 resolver 可表达的档位；模板档仅投影真实探测已通过的强度。"""
    provider = detect_provider(base_url, model, protocol)
    template = None
    if reasoning_template_id:
        try:
            template = ensure_template_compatible(
                reasoning_template_id, provider, protocol, model,
            )
        except LlmRequestError:
            return {
                "provider": provider,
                "allowed_efforts": [],
                "reasoning_effort": "off",
                "reasoning_note": "思考模板与当前供应商或协议不兼容，请重新验证模型配置。",
            }
        candidates = _probe_efforts(reasoning_probe, template)
    else:
        candidates = EFFORTS

    allowed: list[str] = []
    for effort in candidates:
        config = ModelConfig(
            protocol=protocol,
            base_url=base_url,
            model=model,
            max_tokens=max_tokens,
            full_url=full_url,
            reasoning_enabled=effort != "off",
            reasoning_effort=effort if effort != "off" else "medium",
            reasoning_template_id=reasoning_template_id,
            reasoning_allowed_efforts=tuple(candidates) if reasoning_template_id else None,
        )
        try:
            resolve_request(config, messages=[])
        except LlmRequestError:
            continue
        allowed.append(effort)

    preferred = template.default_effort if template else (
        "high" if provider == "anthropic" and model.lower().startswith("claude-") else "off"
    )
    default = preferred if preferred in allowed else (
        "high" if "high" in allowed else next(iter(allowed), "off")
    )
    note = template.description if template else reasoning_note(provider, model)
    if reasoning_template_id and not allowed:
        note = "模型思考模板尚未验证，或验证结果已失效；请在协议档中重新测试。"
    return {
        "provider": provider,
        "allowed_efforts": allowed,
        "reasoning_effort": default,
        "reasoning_note": note,
        "reasoning_mode": template.mode if template else None,
    }
