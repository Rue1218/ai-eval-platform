"""API 侧 LLM 调用辅助：Agent 协议档解析与统一调用（AI 生成类端点共用）。

数据集的 AI 合成 / 用例的 AI 生成与补全都复用同一解析链：
``Setting.agent_profile_id`` -> ``ProtocolProfile`` -> 环境文件连接 -> ``call_protocol``。
"""

import logging

from sqlalchemy.orm import Session

from .adapters import AdapterResult, call_protocol
from .errors import AppError, ErrorCode
from .models import ProtocolProfile, Setting
from .routers.profiles import _profile_connection

logger = logging.getLogger("ai-eval.llm_client")

# AI 生成默认超时与 token 上限（生成内容较长，给予充足余量）
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_TOKENS = 8192


def resolve_agent_profile(db: Session) -> ProtocolProfile:
    """按 Agent 设置解析协议档；未配置/未启用 agent 用途时抛 VALIDATION。"""
    setting = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = setting.value if setting else None
    if not isinstance(profile_id, str) or not profile_id:
        raise AppError(ErrorCode.VALIDATION, "尚未配置 Agent 协议档，无法调用 AI 生成")
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在")
    if "agent" not in (profile.usages or []):
        raise AppError(ErrorCode.VALIDATION, "协议档未启用 agent 用途")
    return profile


def call_agent_model(
    db: Session,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> AdapterResult:
    """按 Agent 协议档调用模型并返回统一结果；配置或上游异常抛 AppError。"""
    profile = resolve_agent_profile(db)
    base_url, model, api_key = _profile_connection(profile, allow_global_alias=True)
    if not base_url or not model or not api_key:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档未配置完整（缺 URL / 模型 / API Key）")
    try:
        return call_protocol(
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
        # 上游 4xx/5xx / 超时 / 协议不支持已归一为 AppError，直接透传
        raise
    except Exception as exc:
        logger.exception("AI 生成调用未预期异常: %s", exc)
        raise AppError(ErrorCode.INTERNAL, "AI 生成调用失败，请稍后重试") from exc


def extract_json_array(text: str) -> list[dict]:
    """从容错模型输出提取 JSON 数组（容忍代码围栏与首尾解释文字）。"""
    cleaned = (text or "").strip()
    if not cleaned:
        raise AppError(ErrorCode.UPSTREAM, "模型返回空内容")
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")
        ).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        raise AppError(ErrorCode.UPSTREAM, "模型输出无法解析为 JSON 数组")
    import json

    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list):
        raise AppError(ErrorCode.UPSTREAM, "模型返回的不是 JSON 数组")
    return data
