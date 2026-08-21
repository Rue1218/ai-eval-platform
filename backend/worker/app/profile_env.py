"""Worker 读取 API 容器写入的主模型、Embedding 与 Reranker 环境配置。"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .crypto import decrypt_secret

_PROFILE_ID_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class ProfileEnvValues:
    """协议档环境参数；API Key 仅在 Worker 调用瞬间进入内存。"""

    base_url: str | None
    model: str | None
    api_key: str | None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    reranker_base_url: str | None = None
    reranker_model: str | None = None
    reranker_api_key: str | None = None


@dataclass(frozen=True)
class GlobalLlmEnvValues:
    """兼容服务器既有的单模型 LLM_* 环境变量。"""

    api_key: str | None
    model: str | None
    openai_base_url: str | None
    anthropic_base_url: str | None


def _profile_env_keys(profile_id: str) -> dict[str, str]:
    """生成与 API 容器一致的环境变量名。"""
    token = _PROFILE_ID_RE.sub("_", str(profile_id)).strip("_").upper() or "UNKNOWN"
    return {
        "base_url": f"AI_PROFILE_{token}_BASE_URL",
        "model": f"AI_PROFILE_{token}_MODEL",
        "api_key": f"AI_PROFILE_{token}_API_KEY",
        "embedding_base_url": f"AI_PROFILE_{token}_EMBEDDING_BASE_URL",
        "embedding_model": f"AI_PROFILE_{token}_EMBEDDING_MODEL",
        "embedding_api_key": f"AI_PROFILE_{token}_EMBEDDING_API_KEY",
        "reranker_base_url": f"AI_PROFILE_{token}_RERANKER_BASE_URL",
        "reranker_model": f"AI_PROFILE_{token}_RERANKER_MODEL",
        "reranker_api_key": f"AI_PROFILE_{token}_RERANKER_API_KEY",
    }


def _decode_value(raw: str) -> str:
    """解析 API 写入的引号值，不执行任何 shell 语法。"""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return parsed if isinstance(parsed, str) else value[1:-1]
    return value


def read_profile_env(profile_id: str) -> ProfileEnvValues:
    """读取共享环境文件中的协议档连接参数。"""
    path = Path(os.environ.get("PROFILE_ENV_FILE", "/run/config/.env")).expanduser()
    if not path.exists() or not path.is_file():
        return ProfileEnvValues(None, None, None)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = _decode_value(raw)
    keys = _profile_env_keys(profile_id)
    return ProfileEnvValues(
        base_url=values.get(keys["base_url"]) or None,
        model=values.get(keys["model"]) or None,
        api_key=values.get(keys["api_key"]) or None,
        embedding_base_url=values.get(keys["embedding_base_url"]) or values.get("AI_EMBEDDING_BASE_URL") or None,
        embedding_model=values.get(keys["embedding_model"]) or values.get("AI_EMBEDDING_MODEL") or None,
        embedding_api_key=values.get(keys["embedding_api_key"]) or values.get("AI_EMBEDDING_API_KEY") or None,
        reranker_base_url=values.get(keys["reranker_base_url"]) or values.get("AI_RERANKER_BASE_URL") or None,
        reranker_model=values.get(keys["reranker_model"]) or values.get("AI_RERANKER_MODEL") or None,
        reranker_api_key=values.get(keys["reranker_api_key"]) or values.get("AI_RERANKER_API_KEY") or None,
    )


def read_global_llm_env() -> GlobalLlmEnvValues:
    """读取服务器既有的单模型环境变量。"""
    path = Path(os.environ.get("PROFILE_ENV_FILE", "/run/config/.env")).expanduser()
    if not path.exists() or not path.is_file():
        return GlobalLlmEnvValues(None, None, None, None)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = _decode_value(raw)
    return GlobalLlmEnvValues(
        api_key=values.get("LLM_API_KEY") or None,
        model=values.get("LLM_MODEL") or None,
        openai_base_url=values.get("OPENAI_BASE_URL") or None,
        anthropic_base_url=values.get("ANTHROPIC_BASE_URL") or None,
    )


def profile_connection(profile, *, allow_global_alias: bool = False) -> tuple[str, str, str | None]:
    """返回 Worker 调用所需参数，兼容迁移前的数据库密文。"""
    env_values = read_profile_env(profile.id)
    global_values = read_global_llm_env()
    profile_env_configured = any((env_values.base_url, env_values.model, env_values.api_key))
    global_base_url = (
        global_values.anthropic_base_url
        if profile.protocol == "anthropic_messages"
        else global_values.openai_base_url
    )
    api_key = env_values.api_key or (
        global_values.api_key if allow_global_alias and not profile_env_configured else None
    )
    if not api_key and profile.encrypted_key:
        api_key = decrypt_secret(profile.encrypted_key)
    return (
        env_values.base_url
        or (global_base_url if allow_global_alias and not profile_env_configured else None)
        or profile.base_url,
        env_values.model
        or (global_values.model if allow_global_alias and not profile_env_configured else None)
        or profile.model,
        api_key,
    )
