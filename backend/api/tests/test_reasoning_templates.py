"""供应商思考模板、探测结果与运行时请求的一致性回归。"""

import asyncio

import pytest

from app import profile_probe
from app.llm.contracts import ModelConfig
from app.llm.loop_contracts import Done, LlmRequestError, ReasoningDelta
from app.llm.providers.options import request_options
from app.llm.providers.reasoning_templates import ensure_template_compatible, list_templates
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


def test_aliyun_template_directory_matches_model_family_and_keeps_generic_fallback():
    """百炼同一端点的 DeepSeek 与千问必须分别选择对应模板。"""
    deepseek_template_ids = [
        template.id for template in list_templates("qwen", "openai_chat", "deepseek-v4.1-flash")
    ]
    qwen_template_ids = [
        template.id for template in list_templates("qwen", "openai_chat", "qwen-plus")
    ]

    assert _ALIYUN_DEEPSEEK_TEMPLATE in deepseek_template_ids
    assert "qwen-openai-thinking-budget-v1" not in deepseek_template_ids
    assert "qwen-openai-thinking-budget-v1" in qwen_template_ids
    assert _ALIYUN_DEEPSEEK_TEMPLATE not in qwen_template_ids
    assert deepseek_template_ids[-1] == qwen_template_ids[-1] == "no-reasoning-v1"


def test_aliyun_deepseek_template_cannot_be_applied_to_qwen_model():
    """即使服务地址和协议相同，也禁止用 DeepSeek 方言注册千问模型。"""
    with pytest.raises(LlmRequestError, match="模型不兼容"):
        ensure_template_compatible(
            _ALIYUN_DEEPSEEK_TEMPLATE, "qwen", "openai_chat", "qwen-plus",
        )


@pytest.mark.parametrize(
    ("provider", "protocol", "model"),
    [
        ("zhipu", "openai_chat", "glm-4.7"), ("deepseek", "openai_chat", "deepseek-v4.1-flash"),
        ("qwen", "openai_chat", "qwen-plus"), ("moonshot", "openai_chat", "kimi-k2.5"),
        ("minimax", "anthropic_messages", "MiniMax-M2.5"), ("nvidia", "openai_chat", "nvidia/nemotron-3-super-120b-a12b"),
        ("volcengine", "openai_chat", "doubao-seed-1-8-251228"), ("google", "openai_chat", "gemini-2.5-flash"),
        ("openai", "openai_chat", "gpt-5.4"), ("anthropic", "anthropic_messages", "claude-sonnet-4-6"),
    ],
)
def test_every_profile_vendor_has_a_non_generic_template(provider: str, protocol: str, model: str):
    """配置页支持的每个供应商至少有一个本厂协议模板，而非只能关闭思考。"""
    templates = list_templates(provider, protocol, model)

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


class _ProbeAdapter:
    """提供可控流事件，验证探测不会把普通完成误判为思考能力。"""

    def __init__(self, events):
        self._events = events

    async def stream(self, request):
        for event in self._events:
            yield event


@pytest.mark.asyncio
async def test_probe_rejects_completed_stream_without_reasoning_evidence(monkeypatch):
    """兼容网关静默忽略思考参数时，探测不能错误开放对应档位。"""
    adapter = _ProbeAdapter([Done("stop")])

    monkeypatch.setattr(profile_probe, "build_adapter", lambda config: (adapter, config.model))

    async def close(_adapter):
        """测试替身无需释放网络资源。"""

    monkeypatch.setattr(profile_probe, "close_adapter", close)
    ok, evidence, code = await profile_probe._probe_one(
        _config(), requires_reasoning_evidence=True,
    )

    assert (ok, evidence, code) == (False, None, "NO_REASONING_EVIDENCE")


@pytest.mark.asyncio
async def test_probe_accepts_reasoning_delta_as_evidence(monkeypatch):
    """返回的 reasoning 增量是开启思考后可安全持久化的能力证据。"""
    adapter = _ProbeAdapter([ReasoningDelta("计算中"), Done("stop")])

    monkeypatch.setattr(profile_probe, "build_adapter", lambda config: (adapter, config.model))

    async def close(_adapter):
        """测试替身无需释放网络资源。"""

    monkeypatch.setattr(profile_probe, "close_adapter", close)
    ok, evidence, code = await profile_probe._probe_one(
        _config(), requires_reasoning_evidence=True,
    )

    assert (ok, evidence, code) == (True, "reasoning_delta", None)


@pytest.mark.asyncio
async def test_probe_runs_all_template_efforts_concurrently(monkeypatch):
    """五档探测必须并发开始，避免把五个 30 秒上游超时串行相加。"""
    started = asyncio.Event()
    release = asyncio.Event()
    started_count = 0

    async def fake_probe(config, *, requires_reasoning_evidence):
        """等待所有档位均已启动后才返回，以便观测实际并发度。"""
        nonlocal started_count
        started_count += 1
        if started_count == len(_ALL_EFFORTS):
            started.set()
        await release.wait()
        return True, "reasoning_delta", None

    monkeypatch.setattr(profile_probe, "_probe_one", fake_probe)
    task = asyncio.create_task(profile_probe._probe_all(_config()))
    await asyncio.wait_for(started.wait(), timeout=0.1)
    release.set()
    result = await task

    assert started_count == len(_ALL_EFFORTS)
    assert result["status"] == "passed"
