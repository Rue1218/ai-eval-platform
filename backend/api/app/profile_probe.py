"""协议档思考模板的预注册真实探测服务。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .llm.contracts import ModelConfig
from .llm.loop_contracts import Done, LlmRequestError, ReasoningDelta
from .llm.providers.reasoning_templates import ensure_template_compatible
from .llm.resolver import build_adapter, close_adapter, resolve_request

PROBE_MAX_TOKENS = 2048
PROBE_MAX_ATTEMPTS = 5
_PROBE_MESSAGES = [{"role": "user", "content": "请计算 17 × 29，只回复计算结果。"}]
_REASONING_USAGE_KEYS = frozenset({
    "reasoning_tokens", "reasoning_output_tokens", "thinking_tokens", "thought_tokens",
})


def _has_reasoning_usage(usage: dict[str, int]) -> bool:
    """只识别正数的推理用量，不把缺失、零值或未知字段误判为思考证据。"""
    return any(
        isinstance(usage.get(key), int) and usage[key] > 0
        for key in _REASONING_USAGE_KEYS
    )


async def _probe_one(
    config: ModelConfig,
    *,
    requires_reasoning_evidence: bool,
) -> tuple[bool, str | None, str | None]:
    """执行单一档位真实请求，并在开启思考时校验流或用量中的可观测证据。"""
    adapter = None
    try:
        adapter, _ = build_adapter(config)
        request = resolve_request(config, messages=_PROBE_MESSAGES)
        completed = False
        evidence: str | None = None
        async for event in adapter.stream(request):
            if isinstance(event, ReasoningDelta) and event.text.strip():
                evidence = "reasoning_delta"
            if isinstance(event, Done):
                completed = True
                if evidence is None and _has_reasoning_usage(event.usage):
                    evidence = "reasoning_usage"
        if not completed:
            return False, None, "UPSTREAM"
        if config.reasoning_enabled and requires_reasoning_evidence and evidence is None:
            # 兼容网关可能静默丢弃未知字段；没有证据时绝不能开放思考滑块。
            return False, None, "NO_REASONING_EVIDENCE"
        return True, evidence or "request_completed", None
    except LlmRequestError as exc:
        return False, None, exc.public_code
    except TimeoutError:
        return False, None, "TIMEOUT"
    except Exception:
        # 上游正文与 SDK 异常都可能含敏感内容，只保留平台安全分类。
        return False, None, "UPSTREAM"
    finally:
        if adapter is not None:
            await close_adapter(adapter)


async def _probe_all(config: ModelConfig) -> dict[str, object]:
    """按模板声明顺序逐档探测，最多五次并始终收敛为非敏感结果。"""
    template_id = config.reasoning_template_id
    if not template_id:
        raise LlmRequestError("探测请求缺少思考模板", code="model_config")
    provider_request = resolve_request(config, messages=[])
    template = ensure_template_compatible(
        template_id,
        provider_request.provider or "",
        config.protocol,
        config.model,
    )
    attempts: list[dict[str, object]] = []
    supported: list[str] = []
    attempt_inputs: list[tuple[str, ModelConfig]] = []
    for effort in template.allowed_efforts[:PROBE_MAX_ATTEMPTS]:
        attempt_inputs.append((effort, ModelConfig(
            protocol=config.protocol,
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            anthropic_version=config.anthropic_version,
            temperature=config.temperature,
            max_tokens=min(config.max_tokens, PROBE_MAX_TOKENS),
            timeout_s=config.timeout_s,
            reasoning_enabled=effort != "off",
            reasoning_effort=effort if effort != "off" else "medium",
            tool_call_mode=config.tool_call_mode,
            full_url=config.full_url,
            reasoning_template_id=template.id,
        )))
    # 各档位互不依赖，并发执行使整次预注册受单次 30 秒超时约束，而非五次累加。
    outcomes = await asyncio.gather(*(
        _probe_one(config, requires_reasoning_evidence=template.requires_reasoning_evidence)
        for _effort, config in attempt_inputs
    ))
    for (effort, _attempt_config), (ok, evidence, error_code) in zip(attempt_inputs, outcomes, strict=True):
        attempt = {"effort": effort, "ok": ok}
        if evidence:
            attempt["evidence"] = evidence
        if error_code:
            attempt["error_code"] = error_code
        attempts.append(attempt)
        if ok:
            supported.append(effort)
    status = "passed" if len(supported) == len(attempts) else "partial" if supported else "failed"
    return {
        "status": status,
        "template_id": template.id,
        "template_version": template.version,
        "supported_efforts": supported,
        "attempts": attempts,
        "tested_at": datetime.now(UTC).isoformat(),
    }


def probe_reasoning_template(config: ModelConfig) -> dict[str, object]:
    """供同步 REST 路由调用的探测入口；路由运行在线程池，不阻塞事件循环。"""
    return asyncio.run(_probe_all(config))
