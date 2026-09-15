"""供应商思考模板目录与受控参数映射。

模板只描述已经登记的供应商方言，不能让调用方提交任意请求体。新模型先用
模板进行真实探测；运行时只接受该次探测已经验证通过的档位。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..loop_contracts import LlmRequest, LlmRequestError, UnsupportedReasoningEffortError

TemplateMode = Literal["none", "switch", "effort", "budget", "fixed"]
_EFFORTS = ("off", "low", "medium", "high", "max")
_SWITCH = ("off", "high")
_DEEPSEEK_EFFORTS = ("off", "low", "high", "max")


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
    version: int = 2
    # 名称只用于推荐排序；是否可用由供应商、协议边界和真实探测决定。
    model_pattern: str | None = None
    # 启用思考时必须从流或用量拿到证据，不能只按 HTTP 成功推断能力。
    requires_reasoning_evidence: bool = True

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
        "aliyun-numeric-effort-v1", "百炼 · 数值思考强度（可选）", "qwen", "openai_chat",
        "effort", _EFFORTS, "medium", "aliyun_numeric",
        "仅供已支持整数强度的兼容端点验证：低/中/高/最高为 1/33/67/100；不按型号默认启用。",
        model_pattern=r"(?!)",
    ),
    ReasoningTemplate(
        "deepseek-reasoning-effort-v1", "DeepSeek 思考强度", "deepseek", "openai_chat",
        "effort", _DEEPSEEK_EFFORTS, "high", "thinking_effort",
        "发送 thinking 开关及 low/high/max 强度；无 medium 别名档位。", model_pattern=r"^deepseek-v4",
    ),
    ReasoningTemplate(
        "moonshot-reasoning-effort-v1", "Kimi 思考强度（固定开启）", "moonshot", "openai_chat",
        "effort", ("low", "high", "max"), "max", "moonshot_effort",
        "始终思考，通过 reasoning_effort 调整 low/high/max，不发送 K2 的 thinking 开关。",
        model_pattern=r"^kimi-k[3-9]",
    ),
    ReasoningTemplate(
        "anthropic-adaptive-effort-v1", "Anthropic 自适应思考强度", "anthropic", "anthropic_messages",
        "effort", _EFFORTS, "high", "anthropic_adaptive_effort",
        "使用 adaptive thinking 与 output_config.effort；旧型号可改选预算模板。",
        model_pattern=r"^claude-(?!.*(?:3[-.]|4[-.][0-5](?:-|$)))",
    ),
    ReasoningTemplate(
        "google-gemini-level-v1", "Google Gemini 思考等级", "google", "openai_chat",
        "effort", ("low", "medium", "high"), "high", "google_level",
        "通过 thinking_level 请求等级，不提供关闭或重复的最高档；各等级需要验证。",
        model_pattern=r"^gemini-[3-9]",
    ),
    ReasoningTemplate(
        "openai-reasoning-effort-v1", "OpenAI Reasoning Effort", "openai", "openai_chat",
        "effort", _EFFORTS, "medium", "openai_effort",
        "适用于 OpenAI 原生 reasoning_effort 参数的推理模型。", model_pattern=r"^(?:o1|o3|o4|gpt-5)(?:[.-]|$)",
    ),
    ReasoningTemplate(
        "deepseek-thinking-switch-v1", "DeepSeek 思考开关", "deepseek", "openai_chat",
        "switch", _SWITCH, "high", "thinking_switch",
        "仅切换思考开启/关闭，不提供多档强度。", model_pattern=r"^deepseek-",
    ),
    ReasoningTemplate(
        "aliyun-deepseek-openai-v1", "百炼 DeepSeek · OpenAI Chat", "qwen", "openai_chat",
        "effort", _DEEPSEEK_EFFORTS, "high", "aliyun_enable_effort",
        "适用于百炼兼容模式中需要 enable_thinking 与 reasoning_effort 的 DeepSeek 模型。", model_pattern=r"^deepseek-",
    ),
    ReasoningTemplate(
        "aliyun-deepseek-anthropic-v1", "百炼 DeepSeek · Anthropic Messages", "qwen", "anthropic_messages",
        "effort", _DEEPSEEK_EFFORTS, "high", "anthropic_thinking_effort",
        "适用于百炼 Anthropic Messages 兼容端点的 DeepSeek 思考方言。", model_pattern=r"^deepseek-",
    ),
    ReasoningTemplate(
        "qwen-openai-thinking-budget-v1", "百炼千问 · OpenAI Chat", "qwen", "openai_chat",
        "budget", _EFFORTS, "medium", "qwen_budget",
        "适用于支持 enable_thinking 和 thinking_budget 的千问兼容模型。", model_pattern=r"^(?:qwen|qwq)",
    ),
    ReasoningTemplate(
        "qwen-anthropic-thinking-budget-v1", "百炼千问 · Anthropic Messages", "qwen", "anthropic_messages",
        "budget", _EFFORTS, "medium", "anthropic_budget",
        "适用于百炼 Anthropic Messages 兼容模式的千问预算思考模型。", model_pattern=r"^(?:qwen|qwq)",
    ),
    ReasoningTemplate(
        "zhipu-thinking-switch-v1", "智谱 GLM 思考开关", "zhipu", "openai_chat",
        "switch", _SWITCH, "high", "thinking_switch",
        "适用于智谱 OpenAI 兼容端点的 thinking 开关。", model_pattern=r"^glm-",
    ),
    ReasoningTemplate(
        "moonshot-thinking-switch-v1", "Moonshot/Kimi 思考开关", "moonshot", "openai_chat",
        "switch", _SWITCH, "high", "moonshot_switch",
        "适用于 Moonshot OpenAI 兼容端点的 thinking 开关。", model_pattern=r"^(?:kimi|moonshot)(?:[.-]|$)",
    ),
    ReasoningTemplate(
        "moonshot-anthropic-output-effort-v1", "Kimi K3 · Anthropic Messages 思考强度", "moonshot", "anthropic_messages",
        "effort", ("low", "high", "max"), "high", "anthropic_output_effort",
        "Kimi Messages 通过 output_config.effort 选择推理强度；当前官方 Messages 文档仅列出 Kimi K3，强度须经连通性验证。",
        model_pattern=r"^kimi-k3(?:[.-]|$)",
    ),
    ReasoningTemplate(
        "zhipu-anthropic-thinking-switch-v1", "智谱 GLM · Anthropic Messages 思考开关", "zhipu", "anthropic_messages",
        "switch", _SWITCH, "high", "thinking_switch",
        "智谱 Claude 兼容端点使用 Anthropic thinking 开关；仅在探测同时验证请求和思考证据后启用。",
        model_pattern=r"^glm-",
    ),
    ReasoningTemplate(
        "minimax-m2-fixed-v1", "MiniMax M2 固定思考", "minimax", "openai_chat",
        "fixed", ("high",), "high", "minimax_fixed",
        "适用于始终开启思考的 MiniMax M2 系列；不提供关闭选项。", model_pattern=r"^minimax-m2",
    ),
    ReasoningTemplate(
        "minimax-m3-switch-v1", "MiniMax M3 自适应思考", "minimax", "openai_chat",
        "switch", _SWITCH, "high", "minimax_adaptive",
        "适用于支持 adaptive thinking 的 MiniMax M3 系列。", model_pattern=r"^minimax-m3",
    ),
    ReasoningTemplate(
        "minimax-anthropic-m2-fixed-v1", "MiniMax M2 固定思考 · Anthropic Messages", "minimax", "anthropic_messages",
        "fixed", ("high",), "high", "minimax_anthropic_fixed",
        "适用于 Anthropic Messages 兼容端点中始终思考的 MiniMax M2 系列。", model_pattern=r"^minimax-m2",
    ),
    ReasoningTemplate(
        "minimax-anthropic-m3-adaptive-v1", "MiniMax M3 自适应思考 · Anthropic Messages", "minimax", "anthropic_messages",
        "switch", _SWITCH, "high", "anthropic_adaptive",
        "适用于 Anthropic Messages 兼容端点的 MiniMax M3 adaptive thinking。", model_pattern=r"^minimax-m3",
    ),
    ReasoningTemplate(
        "nvidia-nim-thinking-v1", "NVIDIA NIM 思考开关", "nvidia", "openai_chat",
        "switch", _SWITCH, "high", "nvidia_chat_template",
        "适用于 NIM 通过 chat_template_kwargs.enable_thinking 控制的托管模型。", model_pattern=r"^nemotron-3-",
    ),
    ReasoningTemplate(
        "volcengine-seed-thinking-v1", "火山引擎 Seed 思考强度", "volcengine", "openai_chat",
        "effort", ("off", "low", "medium", "high"), "medium", "thinking_effort",
        "适用于 Doubao Seed OpenAI 兼容模型的 thinking 与 reasoning_effort 参数。", model_pattern=r"^doubao-seed-",
    ),
    ReasoningTemplate(
        "volcengine-anthropic-thinking-switch-v1", "火山方舟豆包 · Anthropic Messages 思考开关", "volcengine", "anthropic_messages",
        "switch", _SWITCH, "high", "thinking_switch",
        "火山方舟 Anthropic Messages 兼容端点通过 thinking 开关控制扩展思考；模型和区域差异由真实探测裁定。",
        model_pattern=r"^doubao-",
    ),
    ReasoningTemplate(
        "google-gemini-thinking-v1", "Google Gemini 思考配置", "google", "openai_chat",
        "budget", _EFFORTS, "medium", "google_thinking",
        "适用于 Gemini 预算参数；预算按拟保存输出上限计算，关闭也需要验证。", model_pattern=r"^gemini-2[.]5",
    ),
    ReasoningTemplate(
        "anthropic-thinking-v1", "Anthropic 思考预算", "anthropic", "anthropic_messages",
        "budget", _EFFORTS, "high", "anthropic_budget",
        "适用于 Anthropic Messages 的 thinking budget 参数。", model_pattern=r"^claude-.*(?:3[-.]|4[-.][0-5](?:-|$))",
    ),
    ReasoningTemplate(
        "no-reasoning-v1", "不启用思考", "*", "*",
        "none", ("off",), "off", "none",
        "只发送普通文本请求；若仍观察到思考则验证失败，未观察到也不代表模型没有内部推理。", requires_reasoning_evidence=False,
    ),
)


def _model_id_variants(model: str) -> tuple[str, ...]:
    """归一化模型 ID，兼容 NVIDIA 等以 ``组织/模型`` 形式传入的标识。"""
    raw = model.strip().lower().split("[", 1)[0].strip()
    if not raw:
        return ()
    tail = raw.rsplit("/", 1)[-1]
    return (raw,) if tail == raw else (raw, tail)


def _matches_model(template: ReasoningTemplate, model: str) -> bool:
    """按模型名称给候选排序，不把名称匹配当作能力判定。"""
    if template.model_pattern is None:
        return True
    return any(re.search(template.model_pattern, item) is not None for item in _model_id_variants(model))


def list_templates(provider: str, protocol: str, model: str) -> list[ReasoningTemplate]:
    """列出供应商和协议允许的全部模板，匹配名称的优先，普通模板置后。"""
    normalized_provider = provider.strip().lower()
    normalized_protocol = protocol.strip()
    matched = [
        template for template in TEMPLATES
        if template.provider in {normalized_provider, "*"}
        and template.protocol in {normalized_protocol, "*"}
    ]
    return sorted(matched, key=lambda item: (
        item.provider == "*", not _matches_model(item, model), item.adapter == "aliyun_numeric",
    ))


def get_template(template_id: str) -> ReasoningTemplate:
    """按稳定 ID 读取模板，缺失时返回可安全展示的配置错误。"""
    for template in TEMPLATES:
        if template.id == template_id:
            return template
    raise LlmRequestError("思考模板不存在", code="model_config")


def ensure_template_compatible(
    template_id: str, provider: str, protocol: str, model: str,
) -> ReasoningTemplate:
    """保留供应商与协议硬边界，允许未知模型 ID 参与验证。"""
    template = get_template(template_id)
    if (
        template.provider not in {"*", provider}
        or template.protocol not in {"*", protocol}
    ):
        raise LlmRequestError("思考模板与供应商、协议或模型不兼容", code="model_config")
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


def resolve_template_options(request: LlmRequest, provider: str, protocol: str) -> dict:
    """将请求绑定的模板转换成 SDK 参数中间表示。"""
    template_id = request.reasoning_template_id
    if not template_id:
        raise LlmRequestError("缺少思考模板", code="model_config")
    template = ensure_template_compatible(template_id, provider, protocol, request.model)
    enabled, effort = _enabled_effort(request, provider, template)
    adapter = template.adapter
    if adapter == "none":
        return {}
    if adapter == "openai_effort":
        return {"reasoning_effort": "none" if not enabled else ("xhigh" if effort == "max" else effort),
                "omit_temperature": True, "max_tokens_parameter": "max_completion_tokens"}
    if adapter == "thinking_switch":
        return {"thinking": {"type": "enabled" if enabled else "disabled"}, "omit_temperature": enabled}
    if adapter == "moonshot_switch":
        # Kimi 的开启和关闭都有固定温度要求，均交由供应商使用默认值。
        return {"thinking": {"type": "enabled" if enabled else "disabled"}, "omit_temperature": True}
    if adapter == "moonshot_effort":
        return {"reasoning_effort": effort, "omit_temperature": True}
    if adapter == "aliyun_numeric":
        return {"enable_thinking": enabled, **({"reasoning_effort": {"low": 1, "medium": 33, "high": 67, "max": 100}[effort]} if enabled else {})}
    if adapter == "aliyun_enable_effort":
        return {"enable_thinking": enabled, **({"reasoning_effort": effort} if enabled else {})}
    if adapter == "anthropic_thinking_effort":
        options = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if enabled:
            options["output_config"] = {"effort": effort}
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
    if adapter == "anthropic_adaptive_effort":
        return {"thinking": {"type": "adaptive" if enabled else "disabled"}, "omit_temperature": True,
                **({"output_config": {"effort": effort}} if enabled else {})}
    if adapter == "anthropic_output_effort":
        # Kimi Messages 以 output_config 选择推理深度，不接受人为拼装的 thinking 预算。
        return {"output_config": {"effort": effort}, "omit_temperature": True}
    if adapter == "nvidia_chat_template":
        return {"chat_template_kwargs": {"enable_thinking": enabled}}
    if adapter == "thinking_effort":
        return {"thinking": {"type": "enabled" if enabled else "disabled"},
                "omit_temperature": enabled,
                **({"reasoning_effort": effort} if enabled else {})}
    if adapter == "google_level":
        return {"google_thinking": {"thinking_level": effort, "include_thoughts": True}, "omit_temperature": True}
    if adapter == "google_thinking":
        return {"google_thinking": ({"thinking_budget": min(24576, _budget(request, effort)), "include_thoughts": True}
                                     if enabled else {"thinking_budget": 0, "include_thoughts": False})}
    raise LlmRequestError("思考模板适配器未登记", code="model_config")
