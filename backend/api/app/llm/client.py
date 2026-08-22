"""独立大模型调用层。

本模块只负责协议档解析、三协议调用、流式读取、结构化结果封装和错误归一化。
Harness、ReAct、确认卡、事件持久化、工具白名单和 Worker 队列均不得进入本模块。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.adapters import StreamAborted
from app.errors import AppError, ErrorCode
from app.models import ProtocolProfile, Setting
from app.profile_env import read_global_llm_env, read_profile_env
from app.runtime.cancellation import CancellationToken, TurnCancelled
from app.runtime.trace import TraceContext, using_trace
from app.security import decrypt_secret

from .log import llm_exception, llm_trace

logger = logging.getLogger("ai-eval.llm")

CALL_TIMEOUT_S = 30.0
STREAM_TIMEOUT_S = 45.0


@dataclass(frozen=True)
class AgentCallResult:
    """同步调用统一产物。"""

    text: str
    latency_ms: int
    usage: dict
    raw: dict


@dataclass(frozen=True)
class AgentJsonStreamResult:
    """流式结构化调用产物；正文和推理增量分开返回。"""

    text: str
    reasoning: str
    latency_ms: int


@dataclass(frozen=True)
class AgentProfilePublicInfo:
    """当前驱动模型的脱敏公开信息。"""

    profile_id: str
    name: str
    model: str
    protocol: str


def resolve_agent_profile(db: Session) -> ProtocolProfile:
    """读取当前 Agent 协议档并校验可用凭据。"""
    row = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = row.value if row else None
    if not profile_id:
        raise AppError(ErrorCode.VALIDATION, "未配置 Agent 协议档，请先在协议档页指定 Agent 核心驱动")
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在或已删除，请重新指定")
    if not _profile_api_key(profile):
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档未配置 API Key")
    return profile


_resolve_agent_profile = resolve_agent_profile


def _protocol_fns():
    """读取公开门面上的协议函数，保留测试和部署替换点。"""
    import app.llm as public

    return public.call_protocol, public.stream_protocol


def _profile_connection(profile: ProtocolProfile) -> tuple[str, str, str]:
    """读取协议档环境参数，兼容历史数据库密文回退。"""
    try:
        env_values = read_profile_env(profile.id)
        global_values = read_global_llm_env()
        profile_env_configured = any((env_values.base_url, env_values.model, env_values.api_key))
        global_base_url = (
            global_values.anthropic_base_url
            if profile.protocol == "anthropic_messages"
            else global_values.openai_base_url
        )
        api_key = env_values.api_key or (None if profile_env_configured else global_values.api_key)
        if not api_key and profile.encrypted_key:
            api_key = decrypt_secret(profile.encrypted_key)
        if not api_key:
            raise AppError(ErrorCode.VALIDATION, "Agent 协议档未配置 API Key")
        return (
            env_values.base_url
            or (None if profile_env_configured else global_base_url)
            or profile.base_url,
            env_values.model
            or (None if profile_env_configured else global_values.model)
            or profile.model,
            api_key,
        )
    except AppError:
        raise
    except Exception as exc:
        llm_trace(f"Agent 协议档环境读取失败 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "Agent 协议档环境读取失败") from exc


def _profile_api_key(profile: ProtocolProfile) -> str | None:
    """只检查是否存在 Key，不返回或记录 Key 内容。"""
    try:
        env_values = read_profile_env(profile.id)
        if env_values.api_key:
            return env_values.api_key
        if any((env_values.base_url, env_values.model)):
            return None
        global_api_key = read_global_llm_env().api_key
        if global_api_key:
            return global_api_key
        if profile.encrypted_key:
            return decrypt_secret(profile.encrypted_key)
        return None
    except AppError:
        raise
    except Exception as exc:
        llm_trace(f"Agent 协议档 Key 读取失败 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "Agent 协议档环境读取失败") from exc


def get_agent_profile_public_info(db: Session) -> AgentProfilePublicInfo | None:
    """获取当前模型的脱敏公开信息；未配置时返回 None。"""
    try:
        profile = resolve_agent_profile(db)
        _base_url, model, _api_key = _profile_connection(profile)
        return AgentProfilePublicInfo(
            profile_id=str(profile.id),
            name=profile.name,
            model=model,
            protocol=profile.protocol,
        )
    except AppError:
        return None


def call_agent_model_detailed(
    db: Session,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_s: float = CALL_TIMEOUT_S,
    trace: TraceContext | None = None,
    cancel: CancellationToken | None = None,
) -> AgentCallResult:
    """通过三协议适配器完成一次非流式大模型调用。"""
    if cancel is not None:
        cancel.raise_if_cancelled()
    call_protocol, _stream_protocol = _protocol_fns()
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile)
    ctx = using_trace(trace) if trace is not None else nullcontext()
    with ctx:
        llm_trace(f"模型调用开始 protocol={profile.protocol} model={model} timeout={timeout_s}s")
        try:
            result = call_protocol(
                protocol=profile.protocol,
                base_url=base_url,
                model=model,
                api_key=api_key,
                messages=[{"role": "user", "content": user}],
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                anthropic_version=profile.anthropic_version,
                timeout_s=timeout_s,
            )
            text = result.text.strip()
            if not text:
                raise AppError(ErrorCode.UPSTREAM, "Agent 模型返回空内容")
            llm_trace(f"模型调用完成 latency={result.latency_ms}ms chars={len(text)}")
            return AgentCallResult(
                text=result.text,
                latency_ms=result.latency_ms,
                usage=result.usage,
                raw=result.raw,
            )
        except AppError as exc:
            llm_trace(
                f"模型调用失败 protocol={profile.protocol} model={model} "
                f"code={exc.code.value} error={exc.message}"
            )
            raise
        except TurnCancelled:
            llm_trace(f"模型调用取消 protocol={profile.protocol} model={model}")
            raise
        except Exception as exc:
            llm_exception("Agent 模型调用未归类异常", exc)
            raise AppError(ErrorCode.INTERNAL, "Agent 模型调用失败") from exc


def stream_agent_model(
    db: Session,
    system: str,
    user: str,
    *,
    trace: TraceContext,
    cancel: CancellationToken,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_s: float = STREAM_TIMEOUT_S,
) -> Iterator[tuple[str, str]]:
    """流式调用模型，逐块返回 ``(reasoning|content, text)``。"""
    cancel.raise_if_cancelled()
    _call_protocol, stream_protocol = _protocol_fns()
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile)
    with using_trace(trace):
        llm_trace(f"模型流式调用开始 protocol={profile.protocol} model={model} timeout={timeout_s}s")
        started = time.perf_counter()
        first_chunk = True
        try:
            for kind, chunk in stream_protocol(
                protocol=profile.protocol,
                base_url=base_url,
                model=model,
                api_key=api_key,
                messages=[{"role": "user", "content": user}],
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                anthropic_version=profile.anthropic_version,
                timeout_s=timeout_s,
                should_abort=cancel.is_cancelled,
            ):
                if first_chunk:
                    first_ms = round((time.perf_counter() - started) * 1000)
                    llm_trace(f"模型流式首块 latency={first_ms}ms kind={kind}")
                    first_chunk = False
                cancel.raise_if_cancelled()
                yield kind, chunk
            total_ms = round((time.perf_counter() - started) * 1000)
            llm_trace(f"模型流式调用完成 latency={total_ms}ms")
        except StreamAborted as exc:
            llm_trace("模型流式调用被取消")
            raise TurnCancelled(cancel.reason or "cancelled") from exc
        except AppError as exc:
            llm_trace(
                f"模型流式调用失败 protocol={profile.protocol} model={model} "
                f"code={exc.code.value} error={exc.message}"
            )
            raise
        except TurnCancelled:
            llm_trace("模型流式调用被取消")
            raise
        except Exception as exc:
            llm_exception("Agent 模型流式调用未归类异常", exc)
            raise AppError(ErrorCode.INTERNAL, "Agent 模型调用失败") from exc


def stream_agent_json(
    db: Session,
    system: str,
    user: str,
    *,
    trace: TraceContext,
    cancel: CancellationToken,
    on_reasoning: Callable[[str], None] | None = None,
    temperature: float = 0,
    max_tokens: int = 2048,
    timeout_s: float = STREAM_TIMEOUT_S,
) -> AgentJsonStreamResult:
    """流式调用模型并拆分 JSON 正文与推理链。"""
    content_parts: list[str] = []
    thought_parts: list[str] = []
    started = time.perf_counter()
    # 通过公开门面读取流函数，保留独立调用层的可替换测试与运行时注入点。
    import app.llm as public

    for kind, chunk in public.stream_agent_model(
        db,
        system,
        user,
        trace=trace,
        cancel=cancel,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    ):
        cancel.raise_if_cancelled()
        if not chunk:
            continue
        if kind == "reasoning":
            thought_parts.append(chunk)
            if on_reasoning is not None:
                on_reasoning(chunk)
        else:
            content_parts.append(chunk)
    text = "".join(content_parts)
    if not text.strip():
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型返回空内容")
    return AgentJsonStreamResult(
        text=text,
        reasoning="".join(thought_parts).strip()[:12000],
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


def call_agent_model(
    db: Session,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_s: float = CALL_TIMEOUT_S,
) -> str:
    """完成一次大模型调用并仅返回文本。"""
    result = call_agent_model_detailed(
        db,
        system,
        user,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
    return result.text
