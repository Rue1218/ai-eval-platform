"""供应商思考模板、探测结果与运行时请求的一致性回归。"""

import pytest

from app.llm.contracts import ModelConfig
from app.llm.loop_contracts import LlmRequestError
from app.llm.providers.options import request_options
from app.llm.providers.reasoning_templates import list_templates
from app.llm.resolver import resolve_request
from app.profile_reasoning import profile_reasoning


_ALIYUN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_ALIYUN_DEEPSEEK_TEMPLATE = "aliyun-deepseek-openai-v1"
_ALL_EFFORTS = ["off", "low", "medium", "high", "max"]


def _config(*, effort: str = "medium", enabled: bool = True, allowed: tuple[str, ...] | None = tuple(_ALL_EFFORTS)):
    """构造百炼新 DeepSeek 型号的无密钥请求配置，供纯解析测试使用。"""
    return ModelConfig(
        protocol="openai_chat",
        base_url=_ALIYUN_URL,
        model="deepseek-v4.1-flash",
        max_tokens=8192,
        reasoning_enabled=enabled,
        reasoning_effort=effort if effort != "off" else "medium",
        reasoning_template_id=_ALIYUN_DEEPSEEK_TEMPLATE,
        reasoning_allowed_efforts=allowed,
    )


def test_aliyun_template_directory_includes_deepseek_and_generic_fallback():
    """百炼兼容端点应提供 DeepSeek 专用模板，而不是依赖模型名正则。"""
    template_ids = [template.id for template in list_templates("qwen", "openai_chat")]

    assert _ALIYUN_DEEPSEEK_TEMPLATE in template_ids
    assert "qwen-openai-thinking-budget-v1" in template_ids
    assert template_ids[-1] == "no-reasoning-v1"


@pytest.mark.parametrize(
    ("provider", "protocol"),
    [
        ("zhipu", "openai_chat"), ("deepseek", "openai_chat"),
        ("qwen", "openai_chat"), ("moonshot", "openai_chat"),
        ("minimax", "anthropic_messages"), ("nvidia", "openai_chat"),
        ("volcengine", "openai_chat"), ("google", "openai_chat"),
        ("openai", "openai_chat"), ("anthropic", "anthropic_messages"),
    ],
)
def test_every_profile_vendor_has_a_non_generic_template(provider: str, protocol: str):
    """配置页支持的每个供应商至少有一个本厂协议模板，而非只能关闭思考。"""
    templates = list_templates(provider, protocol)

    assert any(template.id != "no-reasoning-v1" for template in templates)


def test_new_aliyun_deepseek_model_uses_template_effort_wire_options():
    """新型号名称不在旧规则时，模板仍应生成百炼要求的思考参数。"""
    request = resolve_request(_config(), messages=[])
    wire = request_options(request, "qwen", "openai_chat")

    assert request.reasoning_template_id == _ALIYUN_DEEPSEEK_TEMPLATE
    assert wire["reasoning_effort"] == "medium"
    assert wire["extra_body"]["enable_thinking"] is True


def test_template_projection_only_exposes_real_probe_successes():
    """运行时能力投影只能返回探测已通过的档位，不能复用模板声明的全量档位。"""
    capability = profile_reasoning(
        "openai_chat",
        _ALIYUN_URL,
        "deepseek-v4.1-flash",
        8192,
        reasoning_template_id=_ALIYUN_DEEPSEEK_TEMPLATE,
        reasoning_probe={
            "status": "partial",
            "supported_efforts": ["off", "high"],
        },
    )

    assert capability["allowed_efforts"] == ["off", "high"]
    assert capability["reasoning_effort"] == "high"


def test_unverified_template_cannot_send_thinking_request():
    """模板存在但没有探测结果时，任何思考请求都必须在 SDK 分配前被拒绝。"""
    with pytest.raises(LlmRequestError, match="尚未通过模型验证"):
        resolve_request(_config(allowed=()), messages=[])


def test_template_turns_off_thinking_without_model_name_fallback():
    """关闭思考同样经模板编码为 enable_thinking=false，不退回旧 DeepSeek 分支。"""
    request = resolve_request(_config(effort="off", enabled=False), messages=[])
    wire = request_options(request, "qwen", "openai_chat")

    assert request.reasoning_effort == "off"
    assert wire["extra_body"]["enable_thinking"] is False
    assert "reasoning_effort" not in wire
