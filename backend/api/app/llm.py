"""Agent 协议档的短同步调用助手（MCP 短工具语义的 REST 落地）。

仅供候选生成类接口（数据集 ai-generate、用例 ai-generate / ai-fill）使用：
同步、超时短、只返回文本，不做长任务。被测三协议与 Agent / Judge 共用同一
协议档模型；未配置 Agent 协议档或调用失败时抛出统一 AppError，绝不回显 Key。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .adapters import call_protocol, stream_protocol
from .agent.log import agent_trace
from .errors import AppError, ErrorCode
from .models import ProtocolProfile, Setting
from .profile_env import read_global_llm_env, read_profile_env
from .security import decrypt_secret

logger = logging.getLogger("ai-eval.llm")

# 候选生成属于短工具调用，超过该时长按 TIMEOUT 归一
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


# 别名兼容内部下划线调用
_resolve_agent_profile = resolve_agent_profile


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
) -> AgentCallResult:
    """经三协议统一适配器调用 Agent 模型并返回包含耗时的结构化结果。

    ``timeout_s`` 允许调用方按场景收紧：意图识别等交互式短调用传 12 秒，
    候选生成等可稍长；超时归一为 TIMEOUT 抛给调用方降级处理。
    失败语义：上游 4xx/5xx 与连接错误归一为 UPSTREAM；超时归一为 TIMEOUT。
    控制台只打印协议名、模型名、耗时与字数，绝不打印 API Key 或完整提示词。
    """
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile)
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
    except AppError:
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
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_s: float = CALL_TIMEOUT_S,
) -> Iterator[tuple[str, str]]:
    """流式调用 Agent 模型，逐块 yield ``(kind, text)``。

    ``kind`` 为 ``content``（正文）或 ``reasoning``（思考链），与
    ``stream_protocol`` 同源。失败语义与 ``call_agent_model_detailed`` 一致：
    上游 4xx/5xx 归一 UPSTREAM，超时归一 TIMEOUT。
    """
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile)
    agent_trace(f"模型流式调用开始 protocol={profile.protocol} model={model} timeout={timeout_s}s")
    try:
        yield from stream_protocol(
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
    except AppError:
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


def parse_json_candidates(text: str) -> list[dict]:
    """从模型输出中容错提取 JSON 数组（允许 ```json 代码块或首尾解释文字）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉 markdown 代码围栏
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型未返回可解析的候选 JSON 数组")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型候选 JSON 解析失败") from exc
    if not isinstance(data, list):
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型候选格式不是数组")
    return [item for item in data if isinstance(item, dict)]
