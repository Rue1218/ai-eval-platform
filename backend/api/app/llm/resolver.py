"""授权配置到可持久化请求的边界；本模块不查询数据库或自行授权。"""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from .contracts import ModelConfig, SystemSegment
from .loop_contracts import LlmAdapter, LlmRequest, LlmRequestError, MissingApiKeyError, ToolSpec
from .providers.common import close_async, compatibility_key, normalize_base_url


@dataclass(frozen=True)
class AuthorizedProfileSnapshot:
    """由 ACL 层提供的已授权运行时快照；config 含密钥，不进入图 State。"""

    config: ModelConfig = field(repr=False)
    profile_id: str | None = None
    profile_version: str | int | None = None
    provider: str | None = None
    prompt_cache: bool = False


def _snapshot(config: ModelConfig | AuthorizedProfileSnapshot) -> AuthorizedProfileSnapshot:
    """只接受显式类型，避免把未经授权的客户端字典视为协议档。"""
    if isinstance(config, ModelConfig):
        return AuthorizedProfileSnapshot(config)
    if not isinstance(config, AuthorizedProfileSnapshot):
        raise LlmRequestError("需要已授权模型配置快照", code="model_config")
    return config


def _provider(snapshot: AuthorizedProfileSnapshot) -> str:
    """有明确供应商时优先使用；旧配置仅按模型标识兼容 DeepSeek。"""
    if snapshot.provider:
        return snapshot.provider
    if snapshot.config.protocol == "anthropic_messages":
        return "anthropic"
    if snapshot.config.model.lower().startswith("deepseek"):
        return "deepseek"
    if snapshot.config.model.lower().startswith("mimo"):
        return "mimo"
    if snapshot.config.model.lower().startswith("gemini"):
        return "google"
    return "openai"


def resolve_request(
    config: ModelConfig | AuthorizedProfileSnapshot,
    *,
    messages: Sequence[dict],
    system: str = "",
    tools: Sequence[ToolSpec | Mapping[str, Any]] = (),
    system_segments: Sequence[SystemSegment] = (),
) -> LlmRequest:
    """冻结当前档位与消息；只从授权快照生成供应商选项，不复制凭据。"""
    snapshot = _snapshot(config)
    model = snapshot.config
    # 即使只构建请求也校验连接格式，但地址本身不进入持久请求头。
    normalize_base_url(model.base_url, model.protocol)
    if not model.model or model.protocol not in {
        "openai_chat",
        "anthropic_messages",
    }:
        raise LlmRequestError("模型或协议不合法", code="model_config")
    segments = tuple(deepcopy(system_segments))
    if segments:
        rendered = "\n\n".join(segment.text for segment in segments)
        if system and system != rendered:
            raise LlmRequestError("system 与分段正文不一致", code="model_config")
        system = rendered
        dynamic = False
        for segment in segments:
            if dynamic and segment.cacheable:
                raise LlmRequestError("缓存段必须位于动态段之前", code="model_config")
            dynamic |= not segment.cacheable
    specs = []
    for tool in tools:
        if isinstance(tool, ToolSpec):
            specs.append(deepcopy(tool))
        else:
            schema = tool.get("parameters_schema", tool.get("parameters"))
            if not isinstance(schema, dict) or not tool.get("name"):
                raise LlmRequestError("工具定义不合法", code="model_config")
            specs.append(
                ToolSpec(str(tool["name"]), str(tool.get("description", "")), deepcopy(schema))
            )
    provider = _provider(snapshot)
    options: dict[str, Any] = {}
    if model.protocol == "anthropic_messages":
        options["prompt_cache"] = snapshot.prompt_cache
        if model.anthropic_version:
            options["anthropic_version"] = model.anthropic_version
    request = LlmRequest(
        model=model.model,
        messages=deepcopy(list(messages)),
        system=system,
        tools=specs,
        max_tokens=model.max_tokens,
        provider=provider,
        reasoning_effort=model.reasoning_effort if model.reasoning_enabled else "off",
        thinking=model.reasoning_enabled,
        profile_id=snapshot.profile_id,
        profile_version=snapshot.profile_version,
        protocol=model.protocol,
        system_segments=segments,
        temperature=model.temperature,
        timeout_s=model.timeout_s,
        reasoning_enabled=model.reasoning_enabled,
        provider_options=options,
        compatibility_key=compatibility_key(provider, model.protocol, model.model),
    )
    # 提前解析实际 wire 选项，使 header 可重建真正发送的参数。
    from .providers.options import resolve_options

    resolved = resolve_options(request, provider, model.protocol)
    return replace(request, provider_options={**options, **resolved})


def build_adapter(config: ModelConfig | AuthorizedProfileSnapshot) -> tuple[LlmAdapter, str]:
    """兼容源 factory 的返回形状；每个授权配置拥有独立可关闭客户端。"""
    snapshot = _snapshot(config)
    model = snapshot.config
    if not model.api_key.strip():
        raise MissingApiKeyError("授权协议档未配置模型凭据")
    # 在分配 SDK 资源前完成校验，不因为无效思考配置泄漏连接池。
    resolve_request(snapshot, messages=[])
    from .providers.anthropic import AnthropicAdapter
    from .providers.openai import OpenAiAdapter

    classes = {
        "openai_chat": OpenAiAdapter,
        "anthropic_messages": AnthropicAdapter,
    }
    return classes[model.protocol](
        api_key=model.api_key,
        base_url=model.base_url,
        provider=_provider(snapshot),
        timeout_s=model.timeout_s,
    ), model.model


async def close_adapter(adapter: Any) -> None:
    """应用或会话资源拥有者调用；不要求 fake adapter 必须提供 close。"""
    await close_async(adapter)
