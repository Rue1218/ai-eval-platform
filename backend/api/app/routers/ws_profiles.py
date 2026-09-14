"""Agent 协议档配置解析层（自 ``ws.py`` 抽出）。

承载协议档纯数据快照、模型调用配置构造（含 TTL 缓存）与供应商标识推断。

缓存 ``_MODEL_CONFIG_CACHE`` 是**模块级可变状态**，本模块是它的唯一读写入口——
``ws.py`` 侧只经 ``_selected_model_config`` 访问，不直接引用容器，避免调用方
各自持有引用造成状态分裂（测试以 ``ws_profiles._MODEL_CONFIG_CACHE`` 隔离）。

``ws.py`` 以同名符号 re-export ``_ProfileSnapshot`` / ``_selected_model_config``
/ ``_infer_provider``，既有调用点不变。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..errors import AppError, ErrorCode
from ..llm import ModelConfig
from ..models import ProtocolProfile, Setting
from .profiles import _profile_connection


@dataclass(frozen=True)
class _ProfileSnapshot:
    """协议档纯数据快照：仅含回合所需的已加载标量字段，缓存安全。

    修复根因：缓存曾直接保存 detach 后的 ProtocolProfile ORM 实例；写入缓存
    的回合随后 commit（expire_on_commit 使属性过期）并关闭 Session（实例
    detach），命中缓存的回合访问属性时抛 DetachedInstanceError，被兜底为
    INTERNAL「Agent 调用失败」。快照不再绑定任何 ORM 会话。
    """

    id: str
    name: str
    model: str
    base_url: str
    protocol: str


# 协议档配置快照缓存：Agent 每回合读取，TTL 内复用（省 profile+reasoning 两次
# 查询与环境文件解析）；管理端改档/改 Key 最迟 TTL 秒后生效。缓存只存纯数据
# 快照（_ProfileSnapshot + ModelConfig），禁止缓存 ORM 实例（detach/expire
# 后访问属性会抛 DetachedInstanceError）。
_MODEL_CONFIG_CACHE: dict[str, tuple[float, tuple[ModelConfig, _ProfileSnapshot]]] = {}
_MODEL_CONFIG_CACHE_TTL_S = 15.0


def _selected_model_config(db: Session) -> tuple[ModelConfig, _ProfileSnapshot]:
    """从 Agent 设置与协议档构造模型调用配置与协议档快照，禁止使用隐式旧客户端。"""
    setting = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = setting.value if setting else None
    if not isinstance(profile_id, str) or not profile_id:
        raise AppError(ErrorCode.VALIDATION, "尚未配置 Agent 协议档")
    cached = _MODEL_CONFIG_CACHE.get(profile_id)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在")
    if "agent" not in (profile.usages or []):
        raise AppError(ErrorCode.VALIDATION, "协议档未启用 agent 用途")
    base_url, model, api_key = _profile_connection(profile, allow_global_alias=True)
    if not base_url or not model:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档配置不完整")
    reasoning_row = db.query(Setting).filter(Setting.key == "agent_reasoning").first()
    reasoning = reasoning_row.value if reasoning_row else {}
    if not isinstance(reasoning, dict):
        reasoning = {}
    reasoning_enabled = reasoning.get("enabled", True)
    reasoning_effort = reasoning.get("effort", "medium")
    if not isinstance(reasoning_enabled, bool):
        reasoning_enabled = True
    if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
        reasoning_effort = "medium"
    from ..profile_env import read_profile_env

    config = ModelConfig(
        full_url=read_profile_env(profile.id).full_url,        protocol=profile.protocol,
        base_url=base_url,
        model=model,
        api_key=api_key or "",
        anthropic_version=profile.anthropic_version,
        temperature=0.2,
        # 输出上限从协议档 max_output_tokens 读取（默认 8192）：长文档总结/
        # 导出类任务可调大，避免回答在输出上限处被上游截断。
        max_tokens=int(getattr(profile, "max_output_tokens", 0) or 8192),
        timeout_s=60.0,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        tool_call_mode=getattr(profile, "tool_call_mode", "native") or "native",
    )
    snapshot = _ProfileSnapshot(
        id=profile.id,
        name=profile.name,
        model=profile.model,
        base_url=profile.base_url,
        protocol=profile.protocol,
    )
    _MODEL_CONFIG_CACHE[profile_id] = (now + _MODEL_CONFIG_CACHE_TTL_S, (config, snapshot))
    return config, snapshot


def _infer_provider(profile: _ProfileSnapshot | None) -> str | None:
    """根据协议档的模型名、名称、URL 与协议类型推断供应商标识，供前端精准呈现 ProviderLogo。"""
    if profile is None:
        return None
    model = (profile.model or "").lower()
    name = (profile.name or "").lower()
    url = (profile.base_url or "").lower()

    # 1. 优先匹配模型名归属（支持托管在聚合平台的特定模型）
    if "stepfun" in model or "step-" in model or "stepfun" in name or "阶跃" in name or "stepfun" in url:
        return "stepfun"
    if "deepseek" in model or "deepseek" in name or "deepseek" in url:
        return "deepseek"
    if "qwen" in model or "tongyi" in name or "aliyun" in url or "dashscope" in url:
        return "qwen"
    if model.startswith("claude-") or "claude" in model or "anthropic" in name or "anthropic" in url or profile.protocol == "anthropic_messages":
        return "anthropic"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-")) or "openai" in name or "openai" in url:
        return "openai"
    if model.startswith("gemini-") or "gemini" in model or "google" in url or "generativelanguage" in url:
        return "gemini"
    if "glm" in model or "zhipu" in name or "智谱" in name or "bigmodel.cn" in url:
        return "zhipu"
    if "kimi" in model or "moonshot" in model or "kimi" in name or "月之暗面" in name or "moonshot" in url:
        return "moonshot"
    if "mistral" in model or "mistral" in name or "mistral" in url:
        return "mistral"
    if "doubao" in model or "火山" in name or "豆包" in name or "volces.com" in url:
        return "volcengine"
    if "ernie" in model or "qianfan" in name or "文心" in name or "千帆" in name or "qianfan" in url or "baidubce" in url:
        return "qianfan"
    if "hunyuan" in model or "混元" in name or "tencent" in url:
        return "hunyuan"

    # 2. 匹配托管服务与端点平台
    if "nvidia" in url or "nvidia" in name or "nvidia" in model:
        return "nvidia"
    if "xiaomimimo" in url or "mimo" in name or "mimo" in model:
        return "mimo"
    if "siliconflow" in url or "silicon" in name or "硅基" in name:
        return "siliconflow"
    if "groq" in url or "groq" in name:
        return "groq"
    if "11434" in url or "ollama" in url or "ollama" in name:
        return "ollama"
    if "together" in url or "together" in name:
        return "together"
    return "custom"
