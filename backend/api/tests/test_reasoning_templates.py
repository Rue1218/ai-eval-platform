"""供应商思考模板、探测结果与运行时请求的一致性回归。"""

import asyncio
from dataclasses import replace

import pytest

from app import profile_probe
from app.llm.contracts import ModelConfig
from app.llm.loop_contracts import Done, LlmRequestError, ReasoningDelta, TextDelta
from app.llm.providers.options import request_options
from app.llm.providers.reasoning_templates import (
    TEMPLATES,
    ensure_template_compatible,
    get_template,
    list_templates,
)
from app.llm.resolver import resolve_request
from app.profile_reasoning import profile_reasoning

_ALIYUN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_ALIYUN_DEEPSEEK_TEMPLATE = "aliyun-numeric-effort-v1"
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
    """同一供应商保留全部方言，名称只影响推荐顺序。"""
    deepseek_template_ids = [
        template.id for template in list_templates("qwen", "openai_chat", "deepseek-v4.1-flash")
    ]
    qwen_template_ids = [
        template.id for template in list_templates("qwen", "openai_chat", "qwen-plus")
    ]

    assert deepseek_template_ids[0] == 'aliyun-deepseek-openai-v1'
    assert qwen_template_ids[0] == "qwen-openai-thinking-budget-v1"
    assert set(deepseek_template_ids) == set(qwen_template_ids)
    assert deepseek_template_ids[-1] == qwen_template_ids[-1] == "no-reasoning-v1"


@pytest.mark.parametrize(('provider', 'protocol'), [('deepseek', 'openai_chat'), ('qwen', 'anthropic_messages')])
def test_template_cannot_cross_provider_or_protocol(provider, protocol):
    """取消型号硬限制不等于允许跨供应商或跨协议套用方言。"""
    with pytest.raises(LlmRequestError, match="不兼容"):
        ensure_template_compatible(_ALIYUN_DEEPSEEK_TEMPLATE, provider, protocol, "unknown-new-model")


@pytest.mark.parametrize(
    ("provider", "protocol", "model"),
    [
        ("zhipu", "openai_chat", "glm-4.7"), ("deepseek", "openai_chat", "deepseek-v4.1-flash"),
        ("qwen", "openai_chat", "qwen-plus"), ("qwen", "anthropic_messages", "qwen3.8-max"),
        ("moonshot", "openai_chat", "kimi-k2.5"),
        ("minimax", "openai_chat", "MiniMax-M3"), ("minimax", "anthropic_messages", "MiniMax-M2.5"),
        ("volcengine", "openai_chat", "doubao-seed-1-8-251228"), ("google", "openai_chat", "gemini-2.5-flash"),
        ("openai", "openai_chat", "gpt-5.4"), ("anthropic", "anthropic_messages", "claude-sonnet-4-6"),
        ("deepseek", "anthropic_messages", "deepseek-v4-flash"),
        ("moonshot", "anthropic_messages", "kimi-k3"), ("zhipu", "anthropic_messages", "glm-4.7"),
        ("volcengine", "anthropic_messages", "doubao-seed-evolving"),
        ("nvidia", "anthropic_messages", "nvidia/nemotron-3-super-120b-a12b"),
    ],
)
def test_every_profile_vendor_has_a_non_generic_template(provider: str, protocol: str, model: str):
    """配置页支持的每个供应商至少有一个本厂协议模板，而非只能关闭思考。"""
    templates = list_templates(provider, protocol, model)

    assert any(template.id != "no-reasoning-v1" for template in templates)


def test_minimax_china_endpoint_is_detected_by_host_before_model_brand():
    """MiniMax 中国区官方域名必须按托管服务识别，不能依赖模型名猜测。"""
    from app.llm.providers.catalog import detect_provider

    assert detect_provider(
        "https://api.minimax.cn/anthropic", "custom-model-alias", "anthropic_messages",
    ) == "minimax"


def test_explicit_numeric_template_uses_integer_wire_options():
    """显式选择数值候选时仍受真实探测约束，不能把整数序列化成字符串。"""
    request = resolve_request(_config(), messages=[])
    wire = request_options(request, "qwen", "openai_chat")

    assert request.reasoning_template_id == _ALIYUN_DEEPSEEK_TEMPLATE
    assert wire["reasoning_effort"] == 33
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
            "template_id": _ALIYUN_DEEPSEEK_TEMPLATE,
            "template_version": 2,
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
    adapter = _ProbeAdapter([ReasoningDelta("计算中"), TextDelta("120"), Done("stop")])

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


@pytest.mark.asyncio
async def test_rate_limited_efforts_retry_serially(monkeypatch):
    """单并发网关拒绝关闭思考时，限流的开启档位仍能逐档验证成功。"""
    active = 0
    calls = []

    async def gateway(config, **kwargs):
        """模拟仅允许单并发、强制思考的供应商。"""
        nonlocal active
        calls.append(config.reasoning_effort if config.reasoning_enabled else "off")
        if active:
            return False, None, "RATE_LIMITED"
        active += 1
        try:
            await asyncio.sleep(0.01)
            return (True, "reasoning_delta", None) if config.reasoning_enabled else (False, None, "PARAMETERS_REJECTED")
        finally:
            active -= 1

    monkeypatch.setattr(profile_probe, "_probe_one", gateway)
    result = await profile_probe._probe_all(_config())
    assert result["status"] == "partial"
    assert result["supported_efforts"] == ["low", "medium", "high", "max"]
    assert len(calls) == 9
    assert calls.count("off") == 1


@pytest.mark.asyncio
async def test_rate_limit_retry_has_total_deadline(monkeypatch):
    """限流重试仍受整次探测截止时间约束，预算耗尽不继续发请求。"""
    calls = []

    async def gateway(config, **kwargs):
        """首批立即限流，重试模拟持续挂起的上游。"""
        calls.append(config.timeout_s)
        if len(calls) <= 5:
            return False, None, "RATE_LIMITED"
        await asyncio.Event().wait()

    monkeypatch.setattr(profile_probe, "_probe_one", gateway)
    monkeypatch.setattr(profile_probe, "PROBE_TOTAL_DEADLINE_SECONDS", 0.35)
    result = await asyncio.wait_for(profile_probe._probe_all(_config()), timeout=0.8)
    assert len(calls) == 6 and calls[-1] < 0.11
    assert result["status"] == "failed"


@pytest.mark.parametrize(('provider', 'protocol', 'model', 'first'), [
    ('qwen', 'openai_chat', 'qwen3-235b-a22b', 'qwen-openai-thinking-budget-v1'),
    ('qwen', 'openai_chat', 'deepseek-v4.1-flash', 'aliyun-deepseek-openai-v1'),
    ('anthropic', 'anthropic_messages', 'claude-opus-4-7', 'anthropic-adaptive-effort-v1'),
    ('anthropic', 'anthropic_messages', 'claude-sonnet-4-5', 'anthropic-thinking-v1'),
    ('google', 'openai_chat', 'gemini-3-pro', 'google-gemini-level-v1'),
    ('moonshot', 'openai_chat', 'kimi-k3', 'moonshot-reasoning-effort-v1'),
    ('moonshot', 'anthropic_messages', 'kimi-k3', 'moonshot-anthropic-output-effort-v1'),
    ('deepseek', 'anthropic_messages', 'deepseek-v4-flash', 'deepseek-anthropic-effort-v1'),
    ('zhipu', 'anthropic_messages', 'glm-4.7', 'zhipu-anthropic-thinking-switch-v1'),
    ('volcengine', 'openai_chat', 'ep-20260915-example', 'volcengine-seed-thinking-v1'),
    ('volcengine', 'anthropic_messages', 'doubao-seed-evolving', 'volcengine-anthropic-thinking-switch-v1'),
    ('nvidia', 'openai_chat', 'nvidia/unknown-next-model', 'nvidia-nim-thinking-v1'),
    ('nvidia', 'anthropic_messages', 'nvidia/nemotron-3-super-120b-a12b', 'nvidia-nim-anthropic-budget-v1'),
    ('openai', 'openai_chat', 'unknown-next-model', 'openai-reasoning-effort-v1'),
])
def test_new_models_and_deployment_ids_remain_probeable(provider, protocol, model, first):
    """新型号和部署 ID 保留可探测模板，已知方言优先推荐。"""
    assert list_templates(provider, protocol, model)[0].id == first
    ensure_template_compatible(first, provider, protocol, model)


def _wire(template_id, provider, effort, *, enabled=True, model='future-model'):
    """通过真实 resolver 与 SDK 参数组装检查端到端方言，完全不访问网络。"""
    from app.llm.resolver import AuthorizedProfileSnapshot

    template = get_template(template_id)
    config = ModelConfig(protocol=template.protocol, base_url='https://example.com/v1', model=model,
                         reasoning_template_id=template_id, reasoning_enabled=enabled, reasoning_effort=effort)
    request = resolve_request(AuthorizedProfileSnapshot(config, provider=provider), messages=[])
    return request_options(request, provider, template.protocol)


@pytest.mark.parametrize(('effort', 'expected'), [('low', 1), ('medium', 33), ('high', 67), ('max', 100)])
def test_numeric_effort_wire_contract(effort, expected):
    """百炼数值强度必须作为整数到达 SDK，不能降级为字符串或布尔值。"""
    wire = _wire(_ALIYUN_DEEPSEEK_TEMPLATE, 'qwen', effort)
    assert type(wire['reasoning_effort']) is int
    assert wire['reasoning_effort'] == expected


@pytest.mark.parametrize(('template_id', 'provider'), [
    ('deepseek-reasoning-effort-v1', 'deepseek'), ('aliyun-deepseek-openai-v1', 'qwen'),
    ('moonshot-reasoning-effort-v1', 'moonshot'),
])
def test_real_effort_levels_do_not_collapse_to_same_request(template_id, provider):
    """低档与最高档必须真正传递不同枚举，最高档不能改写成 high。"""
    assert _wire(template_id, provider, 'low')['reasoning_effort'] == 'low'
    assert _wire(template_id, provider, 'max')['reasoning_effort'] == 'max'


def test_adaptive_anthropic_and_gemini_levels_use_correct_fields():
    """现代方言不发送旧预算字段，Google 的嵌套 extra_body 保持 SDK 契约。"""
    claude = _wire('anthropic-adaptive-effort-v1', 'anthropic', 'high')
    assert claude['thinking'] == {'type': 'adaptive'}
    assert claude['extra_body'] == {'output_config': {'effort': 'high'}}
    gemini = _wire('google-gemini-level-v1', 'google', 'low')
    assert gemini['extra_body']['extra_body']['google']['thinking_config'] == {
        'thinking_level': 'low', 'include_thoughts': True,
    }


def test_kimi_off_does_not_send_invalid_default_temperature():
    """Kimi 关闭模式不能发送平台默认 0.2，交由供应商使用固定默认值。"""
    wire = _wire('moonshot-thinking-switch-v1', 'moonshot', 'high', enabled=False)
    assert 'temperature' not in wire
    assert wire['extra_body']['thinking'] == {'type': 'disabled'}


def test_kimi_messages_uses_output_config_effort_without_unsupported_budget():
    """Kimi K3 的 Messages 端点通过 output_config 控制强度，不能误发 Anthropic 预算。"""
    wire = _wire('moonshot-anthropic-output-effort-v1', 'moonshot', 'max', model='kimi-k3')

    assert wire['extra_body'] == {'output_config': {'effort': 'max'}}
    assert 'thinking' not in wire
    assert 'temperature' not in wire


def test_deepseek_messages_uses_thinking_and_output_effort():
    """DeepSeek 原厂 Messages 同时发送开关与强度，不能回退成无思考模板。"""
    wire = _wire('deepseek-anthropic-effort-v1', 'deepseek', 'max', model='deepseek-v4-flash')

    assert wire['thinking'] == {'type': 'enabled'}
    assert wire['extra_body'] == {'output_config': {'effort': 'max'}}
    assert 'temperature' not in wire


def test_nvidia_messages_uses_standard_budget_and_requires_probe():
    """NIM Messages 只发送标准 thinking 预算，具体部署支持度交由真实探测决定。"""
    wire = _wire(
        'nvidia-nim-anthropic-budget-v1', 'nvidia', 'high',
        model='nvidia/nemotron-3-super-120b-a12b',
    )

    assert wire['thinking']['type'] == 'enabled'
    assert 1024 <= wire['thinking']['budget_tokens'] < wire['max_tokens']


@pytest.mark.parametrize(
    ('template_id', 'provider', 'model'),
    [
        ('zhipu-anthropic-thinking-switch-v1', 'zhipu', 'glm-4.7'),
        ('volcengine-anthropic-thinking-switch-v1', 'volcengine', 'doubao-seed-evolving'),
    ],
)
def test_anthropic_compatible_switch_templates_preserve_standard_thinking_wire(template_id, provider, model):
    """智谱和火山兼容端点使用标准 thinking 开关，供应商探测再确认各模型是否实际支持。"""
    enabled = _wire(template_id, provider, 'high', model=model)
    disabled = _wire(template_id, provider, 'off', enabled=False, model=model)

    assert enabled['thinking'] == {'type': 'enabled'}
    assert disabled['thinking'] == {'type': 'disabled'}


@pytest.mark.parametrize('template', [item for item in TEMPLATES if item.mode == 'switch'], ids=lambda t: t.id)
def test_switch_templates_only_expose_one_enabled_state(template):
    """开关型供应商不再提供四个相同参数的伪强度。"""
    assert template.allowed_efforts == ('off', 'high')
    with pytest.raises(LlmRequestError):
        _wire(template.id, template.provider, 'low')


@pytest.mark.parametrize('override', [{'template_version': 1}, {'template_id': 'other'}, {'template_version': None}])
def test_old_or_other_template_probe_cannot_authorize_runtime(override):
    """模板修订、错绑或历史缺版本的结果均需要重新验证。"""
    probe = {'status': 'passed', 'template_id': _ALIYUN_DEEPSEEK_TEMPLATE,
             'template_version': 2, 'supported_efforts': ['high'], **override}
    capability = profile_reasoning('openai_chat', _ALIYUN_URL, 'deepseek-v4.1-flash', 8192,
                                   reasoning_template_id=_ALIYUN_DEEPSEEK_TEMPLATE, reasoning_probe=probe)
    assert capability['allowed_efforts'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(('events', 'code'), [
    ([ReasoningDelta('thinking'), TextDelta('120'), Done('stop')], 'THINKING_NOT_DISABLED'),
    ([TextDelta('<thi'), TextDelta('nk>thinking'), Done('stop')], 'THINKING_NOT_DISABLED'),
    ([TextDelta('120'), Done('stop', {'reasoning_tokens': 10})], 'THINKING_NOT_DISABLED'),
    ([TextDelta('unfinished'), Done('length')], 'INCOMPLETE_RESPONSE'),
    ([Done('stop')], 'EMPTY_RESPONSE'),
])
async def test_probe_rejects_false_off_and_incomplete_results(monkeypatch, events, code):
    """静默忽略关闭参数、截断和空响应都不能成为保存依据。"""
    monkeypatch.setattr(profile_probe, 'build_adapter', lambda config: (_ProbeAdapter(events), config.model))
    result = await profile_probe._probe_one(_config(enabled=False), requires_reasoning_evidence=False)
    assert result[0] is False and result[2] == code


@pytest.mark.asyncio
async def test_total_deadline_cancels_continuously_active_stream(monkeypatch):
    """连续输出不应刷新总截止时间，超时取消后必须释放客户端。"""
    closed = asyncio.Event()

    class SlowAdapter:
        """持续输出短帧，模拟从不触发读取空闲超时的上游。"""
        async def stream(self, request):
            while True:
                yield TextDelta('x')
                await asyncio.sleep(0.002)

        async def close(self):
            """记录资源释放。"""
            closed.set()

    monkeypatch.setattr(profile_probe, 'build_adapter', lambda config: (SlowAdapter(), config.model))
    result = await asyncio.wait_for(profile_probe._probe_with_deadline(
        replace(_config(), timeout_s=0.02), requires_reasoning_evidence=True), timeout=1)
    assert result == (False, None, 'TIMEOUT')
    assert closed.is_set()


@pytest.mark.asyncio
async def test_probe_keeps_production_token_budget(monkeypatch):
    """验证与保存后的预算请求必须一致，不再按 2048 截断。"""
    observed = []

    async def probe(config, *, requires_reasoning_evidence):
        """记录每档输出配置。"""
        observed.append(config.max_tokens)
        return True, 'request_completed', None

    monkeypatch.setattr(profile_probe, '_probe_one', probe)
    await profile_probe._probe_all(replace(_config(), max_tokens=16000))
    assert observed == [16000] * 5


@pytest.mark.asyncio
async def test_clamped_budget_does_not_expose_duplicate_levels(monkeypatch):
    """输出上限较小时 low/medium 同为 1024，只开放默认代表档 medium。"""
    async def probe(config, *, requires_reasoning_evidence):
        """替代网络，仅检查实际调度和能力去重。"""
        return True, 'request_completed', None

    monkeypatch.setattr(profile_probe, '_probe_one', probe)
    result = await profile_probe._probe_all(replace(
        _config(), model='qwen3-test', max_tokens=2048,
        reasoning_template_id='qwen-openai-thinking-budget-v1'))
    assert result['supported_efforts'] == ['off', 'medium', 'high', 'max']
