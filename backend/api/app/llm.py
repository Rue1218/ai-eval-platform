"""Agent 协议档的短同步调用助手（MCP 短工具语义的 REST 落地）。

仅供候选生成类接口（数据集 ai-generate、用例 ai-generate / ai-fill）使用：
同步、超时短、只返回文本，不做长任务。被测三协议与 Agent / Judge 共用同一
协议档模型；未配置 Agent 协议档或调用失败时抛出统一 AppError，绝不回显 Key。
"""

import json

from sqlalchemy.orm import Session

from .adapters import call_protocol
from .errors import AppError, ErrorCode
from .models import ProtocolProfile, Setting
from .security import decrypt_secret

# 候选生成属于短工具调用，超过该时长按 TIMEOUT 归一
CALL_TIMEOUT_S = 30


def _resolve_agent_profile(db: Session) -> ProtocolProfile:
    """读取 settings.agent_profile_id 指向的 Agent 协议档。"""
    row = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = row.value if row else None
    if not profile_id:
        raise AppError(ErrorCode.VALIDATION, "未配置 Agent 协议档，请先在协议档页指定 Agent 核心驱动")
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在或已删除，请重新指定")
    if not profile.encrypted_key:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档未配置 API Key")
    return profile


def call_agent_model(
    db: Session,
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
    timeout_s: float = CALL_TIMEOUT_S,
) -> str:
    """经三协议统一适配器调用 Agent 模型并返回纯文本内容。

    ``timeout_s`` 允许调用方按场景收紧：意图识别等交互式短调用传 12 秒，
    候选生成等可稍长；超时归一为 TIMEOUT 抛给调用方降级处理。
    失败语义：上游 4xx/5xx 与连接错误归一为 UPSTREAM；超时归一为 TIMEOUT。
    响应解析失败同样按 UPSTREAM 处理，避免把上游原文抛给浏览器。
    """
    profile = _resolve_agent_profile(db)
    result = call_protocol(
        protocol=profile.protocol,
        base_url=profile.base_url,
        model=profile.model,
        api_key=decrypt_secret(profile.encrypted_key),
        messages=[{"role": "user", "content": user}],
        system=system,
        temperature=0.3,
        max_tokens=max_tokens,
        anthropic_version=profile.anthropic_version,
        timeout_s=timeout_s,
    )
    if not result.text.strip():
        raise AppError(ErrorCode.UPSTREAM, "Agent 模型返回空内容")
    return result.text


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
