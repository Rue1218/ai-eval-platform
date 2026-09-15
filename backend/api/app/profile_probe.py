"""协议档思考模板的预注册真实探测服务。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .llm.contracts import ModelConfig
from .llm.loop_contracts import Done, LlmRequestError
from .llm.providers.reasoning_templates import ensure_template_compatible
from .llm.resolver import build_adapter, close_adapter, resolve_request

PROBE_MAX_TOKENS = 2048
PROBE_MAX_ATTEMPTS = 5
_PROBE_MESSAGES = [{"role": "user", "content": "请只回复 OK。"}]


async def _probe_one(config: ModelConfig) -> tuple[bool, str | None]:
    """执行单一档位的真实流式请求，只返回安全成功标识或平台错误码。"""
    adapter = None
    try:
        adapter, _ = build_adapter(config)
        request = resolve_request(config, messages=_PROBE_MESSAGES)
        completed = False
        async for event in adapter.stream(request):
            if isinstance(event, Done):
                completed = True
        return completed, None if completed else "UPSTREAM"
    except LlmRequestError as exc:
        return False, exc.public_code
    except TimeoutError:
        return False, "TIMEOUT"
    except Exception:
        # 上游正文与 SDK 异常都可能含敏感内容，只保留平台安全分类。
        return False, "UPSTREAM"
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
    )
    attempts: list[dict[str, object]] = []
    supported: list[str] = []
    for effort in template.allowed_efforts[:PROBE_MAX_ATTEMPTS]:
        attempt_config = ModelConfig(
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
        )
        ok, error_code = await _probe_one(attempt_config)
        attempt = {"effort": effort, "ok": ok}
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
