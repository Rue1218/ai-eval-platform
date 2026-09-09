"""供应商采样选项只在此解析，结果进入请求头且不接受任意透传。"""

from ..loop_contracts import LlmRequest, UnsupportedReasoningEffortError
from .common import invalid, validate_request


def resolve_options(request: LlmRequest, provider: str, protocol: str) -> dict:
    """保留平台已知思考能力；不支持的显式组合在发请求前拒绝。"""
    validate_request(request, protocol)
    effort = request.reasoning_effort
    enabled = (
        effort != "off"
        if effort is not None
        else bool(request.thinking or request.reasoning_enabled)
    )
    effort = effort or ("medium" if enabled else "off")
    if effort not in {"off", "low", "medium", "high", "xhigh", "max"}:
        raise UnsupportedReasoningEffortError(provider, effort)
    model = request.model.lower()
    options: dict = {}
    if protocol == "anthropic_messages":
        # 兼容服务可能默认开启思考；off 必须显式发送，不能仅在本地关闭展示。
        if not enabled and model.startswith(("deepseek-", "qwen")):
            options["thinking"] = {"type": "disabled"}
        supported = any(
            part in model
            for part in ("claude-3-7", "claude-sonnet-4", "claude-opus-4", "claude-haiku-4")
        )
        if enabled:
            if not supported or request.max_tokens <= 1024:
                raise UnsupportedReasoningEffortError(provider, effort)
            ratio = {"low": 0.2, "medium": 0.4, "high": 0.6, "xhigh": 0.75, "max": 0.8}[effort]
            options["thinking"] = {
                "type": "enabled",
                "budget_tokens": max(
                    1024, min(request.max_tokens - 1, round(request.max_tokens * ratio))
                ),
            }
            options["omit_temperature"] = True
    elif provider == "deepseek" and protocol == "openai_chat":
        if effort == "xhigh":
            raise UnsupportedReasoningEffortError(provider, effort)
        if request.reasoning_effort is not None or request.thinking is not None:
            options["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if enabled:
                options["reasoning_effort"] = effort
    elif "[" in request.model and request.model.rstrip().endswith("]"):
        # 平台代理的模型名已编码参数，不再额外覆盖其中的档位。
        pass
    elif model.startswith(("o1", "o3", "o4", "gpt-5")):
        selected = effort if enabled else "none"
        if not enabled and model.startswith(("o1", "o3")):
            raise UnsupportedReasoningEffortError(provider, effort)
        options["omit_temperature"] = True
        if protocol == "openai_responses":
            options["reasoning"] = {"effort": selected, **({"summary": "auto"} if enabled else {})}
        else:
            options["reasoning_effort"] = selected
            options["max_tokens_parameter"] = "max_completion_tokens"
    elif provider in {"mimo", "xiaomimimo"} and protocol == "openai_chat":
        options["thinking"] = {"type": "enabled" if enabled else "disabled"}
    elif provider == "google" and model.startswith("gemini") and protocol == "openai_chat":
        if enabled:
            options["google_thinking"] = {
                "thinking_level": "high" if effort in {"xhigh", "max"} else effort,
                "include_thoughts": True,
            }
    elif enabled:
        raise UnsupportedReasoningEffortError(provider, effort)
    # 持久请求里的解析结果必须与当前 codec 一致；不提供绕过字段契约的 extra_body。
    for key, value in request.provider_options.items():
        if key in {"prompt_cache", "anthropic_version"} and protocol == "anthropic_messages":
            continue
        if key not in options or options[key] != value:
            raise invalid("供应商选项不是当前协议解析结果")
    return options


def request_options(request: LlmRequest, provider: str, protocol: str) -> dict:
    """把已经校验的解析结果转 SDK 参数，不暴露模型请求任意覆盖入口。"""
    resolved = resolve_options(request, provider, protocol)
    result = {}
    if request.timeout_s is not None:
        result["timeout"] = request.timeout_s
    if request.temperature is not None and not resolved.get("omit_temperature"):
        result["temperature"] = request.temperature
    token_key = (
        "max_output_tokens"
        if protocol == "openai_responses"
        else resolved.get("max_tokens_parameter", "max_tokens")
    )
    result[token_key] = request.max_tokens
    if protocol == "anthropic_messages":
        if "thinking" in resolved:
            result["thinking"] = resolved["thinking"]
        version = request.provider_options.get("anthropic_version")
        if version:
            result["extra_headers"] = {"anthropic-version": version}
    else:
        for key in ("reasoning", "reasoning_effort"):
            if key in resolved:
                result[key] = resolved[key]
        extra = {}
        if "thinking" in resolved:
            extra["thinking"] = resolved["thinking"]
        if "google_thinking" in resolved:
            extra["extra_body"] = {"google": {"thinking_config": resolved["google_thinking"]}}
        if extra:
            result["extra_body"] = extra
    return result
