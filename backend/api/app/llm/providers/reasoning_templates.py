"""供应商思考模板目录与受控参数映射。

模板只描述已经登记的供应商方言，不能让调用方提交任意请求体。新模型先用
模板进行真实探测；运行时只接受该次探测已经验证通过的档位。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..loop_contracts import LlmRequest, LlmRequestError, UnsupportedReasoningEffortError

TemplateMode = Literal["none", "switch", "effort", "budget", "fixed"]
_EFFORTS = ("off", "low", "medium", "high", "max")


@dataclass(frozen=True, slots=True)
class ReasoningTemplate:
    """一个供应商和协议方言对应的受控思考参数模板。"""

    id: str
    name: str
    provider: str
    protocol: str
    mode: TemplateMode
    allowed_efforts: tuple[str, ...]
    default_effort: str
    adapter: str
    description: str
    version: int = 1

    def summary(self) -> dict[str, object]:
        """输出给配置页的脱敏模板摘要。"""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "protocol": self.protocol,
            "mode": self.mode,
            "allowed_efforts": list(self.allowed_efforts),
            "default_effort": self.default_effort,
            "description": self.description,
            "version": self.version,
        }


TEMPLATES: tuple[ReasoningTemplate, ...] = (
    ReasoningTemplate(
        "openai-reasoning-effort-v1", "OpenAI Reasoning Effort", "openai", "openai_chat",
        "effort", _EFFORTS, "medium", "openai_effort",
        "适用于 OpenAI 原生 reasoning_effort 参数的推理模型。",
    ),
    ReasoningTemplate(
        "deepseek-thinking-switch-v1", "DeepSeek 思考开关", "deepseek", "openai_chat",
        "switch", _EFFORTS, "medium", "thinking_switch",
        "适用于 DeepSeek 原生 OpenAI 兼容端点的 thinking 开关。",
    ),
    ReasoningTemplate(
        "aliyun-deepseek-openai-v1", "百炼 DeepSeek · OpenAI Chat", "qwen", "openai_chat",
        "effort", _EFFORTS, "medium", "aliyun_enable_effort",
        "适用于百炼兼容模式中需要 enable_thinking 与 reasoning_effort 的 DeepSeek 模型。",
    ),
    ReasoningTemplate(
        "aliyun-deepseek-anthropic-v1", "百炼 DeepSeek · Anthropic Messages", "qwen", "anthropic_messages",
        "effort", _EFFORTS, "medium", "anthropic_thinking_effort",
        "适用于百炼 Anthropic Messages 兼容端点的 DeepSeek 思考方言。",
    ),
    ReasoningTemplate(
        "qwen-openai-thinking-budget-v1", "百炼千问 · OpenAI Chat", "qwen", "openai_chat",
        "budget", _EFFORTS, "medium", "qwen_budget",
        "适用于支持 enable_thinking 和 thinking_budget 的千问兼容模型。",
    ),
    ReasoningTemplate(
        "qwen-anthropic-thinking-budget-v1", "百炼千问 · Anthropic Messages", "qwen", "anthropic_messages",
        "budget", _EFFORTS, "medium", "anthropic_budget",
        "适用于百炼 Anthropic Messages 兼容模式的千问预算思考模型。",
    ),
    ReasoningTemplate(
        "zhipu-thinking-switch-v1", "智谱 GLM 思考开关", "zhipu", "openai_chat",
        "switch", _EFFORTS, "medium", "thinking_switch",
        "适用于智谱 OpenAI 兼容端点的 thinking 开关。",
    ),
    ReasoningTemplate(
        "moonshot-thinking-switch-v1", "Moonshot/Kimi 思考开关", "moonshot", "openai_chat",
        "switch", _EFFORTS, "medium", "thinking_switch",
        "适用于 Moonshot OpenAI 兼容端点的 thinking 开关。",
    ),
    ReasoningTemplate(
        "minimax-m2-fixed-v1", "MiniMax M2 固定思考", "minimax", "openai_chat",
        "fixed", ("high",), "high", "minimax_fixed",
        "适用于始终开启思考的 MiniMax M2 系列；不提供关闭选项。",
    ),
    ReasoningTemplate(
        "minimax-m3-switch-v1", "MiniMax M3 自适应思考", "minimax", "openai_chat",
        "switch", _EFFORTS, "medium", "minimax_adaptive",
        "适用于支持 adaptive thinking 的 MiniMax M3 系列。",
    ),
    ReasoningTemplate(
        "minimax-anthropic-m2-fixed-v1", "MiniMax M2 固定思考 · Anthropic Messages", "minimax", "anthropic_messages",
        "fixed", ("high",), "high", "minimax_anthropic_fixed",
        "适用于 Anthropic Messages 兼容端点中始终思考的 MiniMax M2 系列。",
    ),
    ReasoningTemplate(
        "minimax-anthropic-m3-adaptive-v1", "MiniMax M3 自适应思考 · Anthropic Messages", "minimax", "anthropic_messages",
        "switch", _EFFORTS, "medium", "anthropic_adaptive",
        "适用于 Anthropic Messages 兼容端点的 MiniMax M3 adaptive thinking。",
    ),
    ReasoningTemplate(
        "nvidia-nim-thinking-v1", "NVIDIA NIM 思考开关", "nvidia", "openai_chat",
        "switch", _EFFORTS, "medium", "nvidia_chat_template",
        "适用于 NIM 通过 chat_template_kwargs.enable_thinking 控制的托管模型。",
    ),
    ReasoningTemplate(
        "volcengine-seed-thinking-v1", "火山引擎 Seed 思考强度", "volcengine", "openai_chat",
        "effort", _EFFORTS, "medium", "thinking_effort",
        "适用于 Doubao Seed OpenAI 兼容模型的 thinking 与 reasoning_effort 参数。",
    ),
    ReasoningTemplate(
        "google-gemini-thinking-v1", "Google Gemini 思考配置", "google", "openai_chat",
        "budget", _EFFORTS, "medium", "google_thinking",
        "适用于 Gemini OpenAI 兼容端点的 google.thinking_config 参数。",
    ),
    ReasoningTemplate(
        "anthropic-thinking-v1", "Anthropic 思考预算", "anthropic", "anthropic_messages",
        "budget", _EFFORTS, "high", "anthropic_budget",
        "适用于 Anthropic Messages 的 thinking budget 参数。",
    ),
    ReasoningTemplate(
        "no-reasoning-v1", "不启用思考", "*", "*",
        "none", ("off",), "off", "none",
        "适用于已确认不支持思考参数的模型，只发送普通文本请求。",
    ),
)


def list_templates(provider: str, protocol: str) -> list[ReasoningTemplate]:
    """列出与已识别供应商、协议兼容的模板，通用关闭模板始终置后。"""
    normalized_provider = provider.strip().lower()
    normalized_protocol = protocol.strip()
    matched = [
        template for template in TEMPLATES
        if template.provider in {normalized_provider, "*"}
        and template.protocol in {normalized_protocol, "*"}
    ]
    return sorted(matched, key=lambda item: item.provider == "*")


def get_template(template_id: str) -> ReasoningTemplate:
    """按稳定 ID 读取模板，缺失时返回可安全展示的配置错误。"""
    for template in TEMPLATES:
        if template.id == template_id:
            return template
    raise LlmRequestError("思考模板不存在", code="model_config")


def ensure_template_compatible(template_id: str, provider: str, protocol: str) -> ReasoningTemplate:
    """确认模板只能用于已登记的供应商和协议，禁止跨端点套用。"""
    template = get_template(template_id)
    if template.provider not in {"*", provider} or template.protocol not in {"*", protocol}:
        raise LlmRequestError("思考模板与供应商或协议不兼容", code="model_config")
    return template


def _enabled_effort(request: LlmRequest, provider: str, template: ReasoningTemplate) -> tuple[bool, str]:
    """把统一档位转换为模板可识别的开关，先拒绝越过模板边界的选择。"""
    effort = request.reasoning_effort
    enabled = effort != "off" if effort is not None else bool(request.thinking or request.reasoning_enabled)
    selected = effort or (template.default_effort if enabled else "off")
    if selected == "xhigh":
        selected = "max"
    if selected not in template.allowed_efforts:
        raise UnsupportedReasoningEffortError(provider, selected)
    return enabled, selected


def _budget(request: LlmRequest, effort: str) -> int:
    """按固定比例计算预算，确保思考预算不与最小输出约束冲突。"""
    if request.max_tokens <= 1024:
        raise UnsupportedReasoningEffortError(request.provider or "", effort)
    ratio = {"low": 0.2, "medium": 0.4, "high": 0.6, "max": 0.8}
    return max(1024, min(request.max_tokens - 1, round(request.max_tokens * ratio.get(effort, 0.4))))


def _normalized_effort(effort: str) -> str:
    """把平台最高档映射为多数供应商声明的最高可接受枚举。"""
    return "high" if effort == "max" else effort


def resolve_template_options(request: LlmRequest, provider: str, protocol: str) -> dict:
    """将请求绑定的模板转换成 SDK 参数中间表示。"""
    template_id = request.reasoning_template_id
    if not template_id:
        raise LlmRequestError("缺少思考模板", code="model_config")
    template = ensure_template_compatible(template_id, provider, protocol)
    enabled, effort = _enabled_effort(request, provider, template)
    adapter = template.adapter
    if adapter == "none":
        return {}
    if adapter == "openai_effort":
        return {"reasoning_effort": "none" if not enabled else ("xhigh" if effort == "max" else effort),
                "omit_temperature": True, "max_tokens_parameter": "max_completion_tokens"}
    if adapter == "thinking_switch":
        return {"thinking": {"type": "enabled" if enabled else "disabled"}, "omit_temperature": enabled}
    if adapter == "aliyun_enable_effort":
        return {"enable_thinking": enabled, **({"reasoning_effort": _normalized_effort(effort)} if enabled else {})}
    if adapter == "anthropic_thinking_effort":
        options = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if enabled:
            options["output_config"] = {"effort": _normalized_effort(effort)}
            options["omit_temperature"] = True
        return options
    if adapter == "qwen_budget":
        return {"enable_thinking": enabled, **({"thinking_budget": min(32768, _budget(request, effort))} if enabled else {})}
    if adapter == "anthropic_budget":
        return {"thinking": ({"type": "enabled", "budget_tokens": _budget(request, effort)} if enabled else {"type": "disabled"}),
                "omit_temperature": enabled}
    if adapter == "minimax_fixed":
        return {"reasoning_split": True, "omit_temperature": True}
    if adapter == "minimax_adaptive":
        return {"reasoning_split": True, "thinking": {"type": "adaptive" if enabled else "disabled"},
                "omit_temperature": True}
    if adapter == "minimax_anthropic_fixed":
        return {"omit_temperature": True}
    if adapter == "anthropic_adaptive":
        return {"thinking": {"type": "adaptive" if enabled else "disabled"}, "omit_temperature": True}
    if adapter == "nvidia_chat_template":
        return {"chat_template_kwargs": {"enable_thinking": enabled}}
    if adapter == "thinking_effort":
        return {"thinking": {"type": "enabled" if enabled else "disabled"},
                **({"reasoning_effort": _normalized_effort(effort)} if enabled else {})}
    if adapter == "google_thinking":
        return {"google_thinking": ({"thinking_budget": min(24576, _budget(request, effort)), "include_thoughts": True}
                                     if enabled else {"thinking_budget": 0, "include_thoughts": False})}
    raise LlmRequestError("思考模板适配器未登记", code="model_config")
