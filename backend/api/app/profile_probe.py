"""协议档思考模板及 Agent 原生工具往返的保存前探测服务。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

from .llm.contracts import ModelConfig
from .llm.loop_contracts import Done, LlmRequestError, ReasoningDelta, TextDelta
from .llm.providers.catalog import detect_provider
from .llm.providers.reasoning_templates import ensure_template_compatible
from .llm.resolver import build_adapter, close_adapter, resolve_request
from .profile_tool_probe import probe_tool_roundtrip

PROBE_MAX_ATTEMPTS = 5
PROBE_DEADLINE_SECONDS = 30.0
PROBE_TOTAL_DEADLINE_SECONDS = 55.0  # 留出清理/保存余量，低于 REST 代理默认的 60 秒。
_PROBE_MESSAGES = [{"role": "user", "content": "在满足 x+y=23、3x+5y=89 的整数中，求 x*y。请核对两个条件后简短回答。"}]
_REASONING_USAGE_KEYS = frozenset({
    "reasoning_tokens", "reasoning_output_tokens", "thinking_tokens", "thought_tokens",
})

# 只投影固定枚举，不把 SDK 错误正文或模型返回的字符串存入探测回执。
_PROBE_ERROR_CODES = {
    "provider_auth": "AUTH_FAILED",
    "provider_model": "MODEL_OR_ENDPOINT_UNAVAILABLE",
    "provider_rate_limit": "RATE_LIMITED",
    "provider_unavailable": "UPSTREAM_UNAVAILABLE",
    "provider_transport": "CONNECTION_FAILED",
    "provider_request": "PARAMETERS_REJECTED",
    "provider_protocol": "INVALID_RESPONSE",
}


def _has_reasoning_usage(usage: dict[str, int]) -> bool:
    """只识别正数的推理用量，不把缺失、零值或未知字段误判为思考证据。"""
    return any(
        type(usage.get(key)) is int and usage[key] > 0
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
        has_text = False
        text_tail = ""
        evidence: str | None = None
        async for event in adapter.stream(request):
            if isinstance(event, TextDelta):
                has_text |= bool(event.text.strip())
                # 某些兼容端点把思考放进正文；检查跨帧标记且不持久化正文。
                text_tail = (text_tail + event.text).lower()
                if "<think>" in text_tail:
                    evidence = "reasoning_delta"
                text_tail = text_tail[-16:]
            if isinstance(event, ReasoningDelta) and event.text.strip():
                evidence = "reasoning_delta"
            if isinstance(event, Done):
                completed = event.finish_reason == "stop"
                if evidence is None and _has_reasoning_usage(event.usage):
                    evidence = "reasoning_usage"
        if not completed:
            return False, None, "INCOMPLETE_RESPONSE"
        if config.reasoning_enabled and requires_reasoning_evidence and evidence is None:
            # 兼容网关可能静默丢弃未知字段；没有证据时绝不能开放思考滑块。
            return False, None, "NO_REASONING_EVIDENCE"
        if not config.reasoning_enabled and evidence is not None:
            return False, evidence, "THINKING_NOT_DISABLED"
        if not has_text:
            return False, evidence, "EMPTY_RESPONSE"
        return True, evidence or "request_completed", None
    except LlmRequestError as exc:
        return False, None, _PROBE_ERROR_CODES.get(exc.code, exc.public_code)
    except TimeoutError:
        return False, None, "TIMEOUT"
    except Exception:
        # 上游正文与 SDK 异常都可能含敏感内容，只保留平台安全分类。
        return False, None, "UPSTREAM"
    finally:
        if adapter is not None:
            try:
                # 清理失败不得覆盖已获得的验证结果；最多额外等待一秒释放资源。
                await asyncio.wait_for(close_adapter(adapter), timeout=1.0)
            except Exception:
                pass


async def _probe_with_deadline(config: ModelConfig, *, requires_reasoning_evidence: bool):
    """限制整段流的总耗时，持续收到 SSE 也不能无限续期。"""
    try:
        async with asyncio.timeout(min(PROBE_DEADLINE_SECONDS, config.timeout_s)):
            return await _probe_one(config, requires_reasoning_evidence=requires_reasoning_evidence)
    except TimeoutError:
        return False, None, "TIMEOUT"


async def _probe_all(config: ModelConfig, *, check_tools: bool = False) -> dict[str, object]:
    """最多探测五个思考档位，Agent 用途追加单档工具往返并返回安全状态。"""
    started = asyncio.get_running_loop().time()
    template_id = config.reasoning_template_id
    if not template_id:
        raise LlmRequestError("探测请求缺少思考模板", code="model_config")
    template = ensure_template_compatible(
        template_id,
        detect_provider(config.base_url, config.model, config.protocol),
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
            # 使用正式输出上限，避免验证小预算后运行时发送另一套大预算。
            max_tokens=config.max_tokens,
            timeout_s=config.timeout_s,
            reasoning_enabled=effort != "off",
            reasoning_effort=effort if effort != "off" else "medium",
            tool_call_mode=config.tool_call_mode,
            full_url=config.full_url,
            reasoning_template_id=template.id,
        )))
    # 预算被最小值/最大值夹紧后可能多档同参，只验证并开放一个代表档。
    # 优先保留模板默认档；非法请求仍由单档探测输出安全错误。
    representatives: dict[str, str] = {}
    duplicate_efforts: set[str] = set()
    for effort, attempt_config in sorted(attempt_inputs, key=lambda item: item[0] != template.default_effort):
        try:
            request = resolve_request(attempt_config, messages=[])
        except LlmRequestError:
            continue
        key = json.dumps(request.provider_options, sort_keys=True)
        if key in representatives:
            duplicate_efforts.add(effort)
        else:
            representatives[key] = effort
    attempt_inputs = [item for item in attempt_inputs if item[0] not in duplicate_efforts]
    # 各档共享同一最大时长；失败独立收敛，不取消已经通过的兄弟档位。
    outcomes = await asyncio.gather(*(
        _probe_with_deadline(config, requires_reasoning_evidence=template.requires_reasoning_evidence)
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
    tool_probe = {"status": "skipped"}
    if check_tools and supported:
        # 仅选择一个已验证档位，避免将未验证参数造成的错误归因于工具协议。
        selected = template.default_effort if template.default_effort in supported else supported[0]
        selected_config = next(item for effort, item in attempt_inputs if effort == selected)
        remaining = PROBE_TOTAL_DEADLINE_SECONDS - (asyncio.get_running_loop().time() - started)
        if remaining <= 0:
            tool_probe = {"status": "failed", "effort": selected, "error_code": "TIMEOUT"}
        else:
            tool_probe = await probe_tool_roundtrip(replace(selected_config, timeout_s=min(selected_config.timeout_s, remaining)))
    return {
        "status": status,
        "template_id": template.id,
        "template_version": template.version,
        "supported_efforts": supported,
        "attempts": attempts,
        "tool_probe": tool_probe,
        "tested_at": datetime.now(UTC).isoformat(),
    }


def probe_reasoning_template(config: ModelConfig, *, check_tools: bool = False) -> dict[str, object]:
    """供同步 REST 路由调用的探测入口；路由运行在线程池，不阻塞事件循环。"""
    return asyncio.run(_probe_all(config, check_tools=check_tools))
