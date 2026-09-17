"""供应商采样选项只在此解析，结果进入请求头且不接受任意透传。"""

import re

from shared.reasoning import openai_effort

from ..loop_contracts import LlmRequest, UnsupportedReasoningEffortError
from .common import invalid, validate_request
from .reasoning_templates import resolve_template_options


def _qwen_budget_model(model: str) -> bool:
    """只开放已核对百炼预算契约的 Flash 型号，不推断全部 Qwen 能力。"""
    return re.fullmatch(r"qwen3\.[68]-flash(?:-\d{4}-\d{2}-\d{2})?", model) is not None


def _qwen_budget_inside_max_tokens(model: str) -> bool:
    """3.8 Flash 起端点把 max_tokens 当总输出上限，思考预算必须小于它，不能再从预留中扣除。"""
    return re.fullmatch(r"qwen3\.8-flash(?:-\d{4}-\d{2}-\d{2})?", model) is not None


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
    if request.reasoning_template_id:
        options = resolve_template_options(request, provider, protocol)
        for key, value in request.provider_options.items():
            if key in {"prompt_cache", "anthropic_version"} and protocol == "anthropic_messages":
                continue
            if key not in options or options[key] != value:
                raise invalid("供应商选项不是当前协议解析结果")
        return options
    model = request.model.lower().split("/")[-1]
    options: dict = {}
    ratio = {"low": 0.2, "medium": 0.4, "high": 0.6, "xhigh": 0.75, "max": 0.8}
    budget = max(1024, min(request.max_tokens - 1, round(request.max_tokens * ratio.get(effort, 0.4))))
    deepseek_v4 = re.fullmatch(r"deepseek-v4-(?:flash|pro)(?:-\d{4})?", model)
    qwen_thinking = (model.startswith(("qwen3", "qwen-plus", "qwen-flash", "qwen-turbo", "qwq"))
                     and "coder" not in model and "instruct" not in model)
    glm_thinking = model.startswith(("glm-4.5", "glm-4.6", "glm-4.7", "glm-5"))
    kimi_switch = model.startswith(("kimi-k2.5", "kimi-k2.6"))
    fixed_thinking = ((provider == "minimax" and model.startswith("minimax-m2"))
                      or (provider == "moonshot" and "thinking" in model)
                      or (provider == "qwen" and ("thinking" in model or model.startswith("qwq"))))
    if fixed_thinking and not enabled:
        raise UnsupportedReasoningEffortError(provider, effort)
    # 代理已在模型名中编码参数时，不通过滑块伪装覆盖它。
    if "[" in request.model and request.model.rstrip().endswith("]"):
        if enabled:
            raise UnsupportedReasoningEffortError(provider, effort)
    elif protocol == "openai_responses":
        # Responses 方言不能透传 Chat 的 thinking/enable_thinking 扩展。
        if enabled:
            options["reasoning_effort"] = openai_effort(request.model, effort)
        elif model.startswith(("gpt-5.1", "gpt-5.2", "gpt-5.3", "gpt-5.4")):
            options["reasoning_effort"] = "none"
        if enabled or model.startswith(("o1", "o3", "o4", "gpt-5")):
            options["omit_temperature"] = True
    elif protocol == "anthropic_messages":
        if provider in {"deepseek", "qwen"} and (deepseek_v4 or model in {"deepseek-chat", "deepseek-reasoner"}):
            options["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if enabled and deepseek_v4:
                options["output_config"] = {"effort": {"medium": "high", "xhigh": "high"}.get(effort, effort)}
        elif provider == "minimax" and model.startswith(("minimax-m2", "minimax-m3")):
            if model.startswith("minimax-m3"):
                options["thinking"] = {"type": "adaptive" if enabled else "disabled"}
        elif provider in {"zhipu", "moonshot", "qwen"} and (glm_thinking or kimi_switch or fixed_thinking):
            options["thinking"] = {"type": "enabled" if enabled else "disabled"}
        elif model.startswith("claude-"):
            adaptive = re.match(r"claude-(?:opus|sonnet)-4[.-][678](?:-|$)", model)
            supported = adaptive or model.startswith(("claude-3-7", "claude-sonnet-4", "claude-opus-4", "claude-haiku-4"))
            if enabled and not supported:
                raise UnsupportedReasoningEffortError(provider, effort)
            if adaptive:
                options["thinking"] = {"type": "adaptive" if enabled else "disabled"}
                if enabled:
                    options["output_config"] = {"effort": "high" if effort == "xhigh" else effort}
            elif enabled:
                if request.max_tokens <= 1024:
                    raise UnsupportedReasoningEffortError(provider, effort)
                options["thinking"] = {"type": "enabled", "budget_tokens": budget}
            else:
                options["thinking"] = {"type": "disabled"}
        elif _qwen_budget_model(model):
            if enabled and request.max_tokens <= 1024:
                raise UnsupportedReasoningEffortError(provider, effort)
            options["thinking"] = ({"type": "enabled", "budget_tokens": budget}
                                   if enabled else {"type": "disabled"})
        elif not enabled and model.startswith(("deepseek-", "qwen")):
            options["thinking"] = {"type": "disabled"}
        elif enabled:
            raise UnsupportedReasoningEffortError(provider, effort)
        if enabled:
            options["omit_temperature"] = True
    elif provider == "nvidia":
        # NIM 的参数取决于托管模型卡，不沿用模型原厂方言。
        if model.startswith("nemotron-3-"):
            options["chat_template_kwargs"] = {"enable_thinking": enabled}
        elif enabled:
            raise UnsupportedReasoningEffortError(provider, effort)
    elif provider == "deepseek" or (provider == "qwen" and deepseek_v4):
        if effort == "xhigh" and not deepseek_v4:
            raise UnsupportedReasoningEffortError(provider, effort)
        options["thinking"] = {"type": "enabled" if enabled else "disabled"}
        if enabled and deepseek_v4:
            options["reasoning_effort"] = {"medium": "high", "xhigh": "high"}.get(effort, effort)
        if enabled:
            options["omit_temperature"] = True
    elif provider == "qwen" and qwen_thinking:
        options["enable_thinking"] = enabled
        if enabled:
            if request.max_tokens <= 1024:
                raise UnsupportedReasoningEffortError(provider, effort)
            options["thinking_budget"] = min(32768, budget)
    elif provider in {"zhipu", "qwen"} and glm_thinking:
        options["thinking"] = {"type": "enabled" if enabled else "disabled"}
    elif provider == "moonshot" and (kimi_switch or fixed_thinking):
        options["thinking"] = {"type": "enabled" if enabled else "disabled"}
        options["omit_temperature"] = True
    elif provider == "minimax" and model.startswith(("minimax-m2", "minimax-m3")):
        options["reasoning_split"] = True
        options["omit_temperature"] = True
        if model.startswith("minimax-m3"):
            options["thinking"] = {"type": "adaptive" if enabled else "disabled"}
    elif provider == "volcengine" and model.startswith("doubao-seed-"):
        options["thinking"] = {"type": "enabled" if enabled else "disabled"}
        if enabled and model.startswith(("doubao-seed-1-8", "doubao-seed-1.8", "doubao-seed-2")):
            options["reasoning_effort"] = "high" if effort in {"xhigh", "max"} else effort
    elif provider == "openai" and model.startswith(("o1", "o3", "o4", "gpt-5")):
        modern = re.match(r"gpt-5[.][2-9](?:-|$)", model)
        can_disable = modern or model.startswith("gpt-5.1")
        if (not enabled and not can_disable) or model.startswith("gpt-5-pro") and effort != "high":
            raise UnsupportedReasoningEffortError(provider, effort)
        selected = ("xhigh" if modern else "high") if effort in {"max", "xhigh"} else effort
        options["omit_temperature"] = True
        options["reasoning_effort"] = selected if enabled else "none"
        options["max_tokens_parameter"] = "max_completion_tokens"
    elif provider in {"mimo", "xiaomimimo"}:
        options["thinking"] = {"type": "enabled" if enabled else "disabled"}
    elif provider == "google" and model.startswith(("gemini-2.5", "gemini-3")):
        if not enabled and ("pro" in model or model.startswith("gemini-3")):
            raise UnsupportedReasoningEffortError(provider, effort)
        if model.startswith("gemini-2.5"):
            options["google_thinking"] = {"thinking_budget": min(24576, budget) if enabled else 0,
                                           "include_thoughts": enabled}
        else:
            level = "high" if effort in {"max", "xhigh"} else effort
            if model.startswith("gemini-3-pro") and level == "medium":
                level = "high"
            options["google_thinking"] = {"thinking_level": level, "include_thoughts": True}
            options["omit_temperature"] = True
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
    token_key = "max_output_tokens" if protocol == "openai_responses" else resolved.get("max_tokens_parameter", "max_tokens")
    result[token_key] = request.max_tokens
    if protocol == "openai_responses":
        if "reasoning_effort" in resolved:
            result["reasoning"] = {"effort": resolved["reasoning_effort"]}
            if resolved["reasoning_effort"] != "none":
                result["reasoning"]["summary"] = "auto"
    elif protocol == "anthropic_messages":
        if "thinking" in resolved:
            result["thinking"] = resolved["thinking"]
            if (not request.reasoning_template_id and _qwen_budget_model(request.model.lower()) and "budget_tokens" in resolved["thinking"]
                    and not _qwen_budget_inside_max_tokens(request.model.lower())):
                # 3.6 的 max_tokens 仅约束正文；保持平台总输出预留不被思考额外突破。
                result["max_tokens"] -= resolved["thinking"]["budget_tokens"]
        if "output_config" in resolved:
            result["extra_body"] = {"output_config": resolved["output_config"]}
        version = request.provider_options.get("anthropic_version")
        if version:
            result["extra_headers"] = {"anthropic-version": version}
    else:
        if "reasoning_effort" in resolved:
            result["reasoning_effort"] = resolved["reasoning_effort"]
        extra = {}
        for key in ("thinking", "enable_thinking", "thinking_budget", "chat_template_kwargs", "reasoning_split"):
            if key in resolved:
                extra[key] = resolved[key]
        if "google_thinking" in resolved:
            extra["extra_body"] = {"google": {"thinking_config": resolved["google_thinking"]}}
        if extra:
            result["extra_body"] = extra
    return result
