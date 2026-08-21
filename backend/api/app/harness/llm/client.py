"""Agent 协议档短同步调用正文；仅 orchestration 与 app.llm 再导出可引用。"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.adapters import StreamAborted
from app.agent.defaults import STREAM_TIMEOUT_S
from app.agent.log import agent_trace
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken, TurnCancelled
from app.harness.contracts.trace import TraceContext, using_trace
from app.models import ProtocolProfile, Setting
from app.profile_env import read_global_llm_env, read_profile_env
from app.security import decrypt_secret

logger = logging.getLogger("ai-eval.llm")

CALL_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class AgentCallResult:
    """Agent 大模型调用统一产物（包含耗时与用量）。"""

    text: str
    latency_ms: int
    usage: dict
    raw: dict


@dataclass(frozen=True)
class AgentProfilePublicInfo:
    """Agent 驱动模型对外公开信息（脱敏、只读）。"""

    profile_id: str
    name: str
    model: str
    protocol: str


def resolve_agent_profile(db: Session) -> ProtocolProfile:
    """读取 settings.agent_profile_id 指向的 Agent 协议档。

    未配置或已被删除时抛出 VALIDATION (400)，严禁伪造默认模型。
    """
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
    """运行时走 app.llm 上的名字，以便单测 monkeypatch call_protocol。"""
    import app.llm as public

    return public.call_protocol, public.stream_protocol


def _profile_connection(profile: ProtocolProfile) -> tuple[str, str, str]:
    """读取 Agent 协议档环境参数，历史密文仅作兼容回退。"""
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
        agent_trace(f"Agent 协议档环境读取失败 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "Agent 协议档环境读取失败") from exc


def _profile_api_key(profile: ProtocolProfile) -> str | None:
    """只判断协议档是否存在可用 Key，不向日志或响应暴露内容。"""
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
        agent_trace(f"Agent 协议档 Key 读取失败 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "Agent 协议档环境读取失败") from exc


def get_agent_profile_public_info(db: Session) -> AgentProfilePublicInfo | None:
    """获取当前生效的 Agent 模型公开信息供界面只读展示；未配置时返回 None。"""
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
    """经三协议统一适配器调用 Agent 模型并返回包含耗时的结构化结果。"""
    if cancel is not None:
        cancel.raise_if_cancelled()
    call_protocol, _stream_protocol = _protocol_fns()
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile)
    ctx = using_trace(trace) if trace is not None else nullcontext()
    with ctx:
        agent_trace(f"模型调用开始 protocol={profile.protocol} model={model} timeout={timeout_s}s")
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
            agent_trace(f"模型调用完成 latency={result.latency_ms}ms chars={len(text)}")
            return AgentCallResult(
                text=result.text,
                latency_ms=result.latency_ms,
                usage=result.usage,
                raw=result.raw,
            )
        except (AppError, TurnCancelled):
            raise
        except Exception as exc:
            logger.exception("Agent 模型调用未归类异常")
            agent_trace(f"模型调用内部异常 type={type(exc).__name__}")
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
    """流式调用 Agent 模型，逐块 yield ``(kind, text)``。

    ``trace`` / ``cancel`` 不可缺省：块间检查取消，日志自动带链路 ID。
    取消回调下传到适配器读循环，避免 ``urlopen`` 整段 timeout 才返回。
    """
    cancel.raise_if_cancelled()
    _call_protocol, stream_protocol = _protocol_fns()
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile)
    with using_trace(trace):
        agent_trace(f"模型流式调用开始 protocol={profile.protocol} model={model} timeout={timeout_s}s")
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
                    agent_trace(f"模型流式首块 latency={first_ms}ms kind={kind}")
                    first_chunk = False
                cancel.raise_if_cancelled()
                yield kind, chunk
            total_ms = round((time.perf_counter() - started) * 1000)
            agent_trace(f"模型流式调用完成 latency={total_ms}ms")
        except StreamAborted as exc:
            agent_trace("模型流式调用被取消")
            raise TurnCancelled(cancel.reason or "cancelled") from exc
        except (AppError, TurnCancelled):
            raise
        except Exception as exc:
            logger.exception("Agent 模型流式调用未归类异常")
            agent_trace(f"模型流式调用内部异常 type={type(exc).__name__}")
            raise AppError(ErrorCode.INTERNAL, "Agent 模型调用失败") from exc


def call_agent_model(
    db: Session,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_s: float = CALL_TIMEOUT_S,
) -> str:
    """经三协议统一适配器调用 Agent 模型并返回纯文本内容（兼容传统接口）。"""
    res = call_agent_model_detailed(
        db,
        system,
        user,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
    return res.text
