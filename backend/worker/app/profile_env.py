"""Worker 读取 API 容器写入的主模型、Embedding 与 Reranker 环境配置。

共享读取逻辑（数据类 / 键名生成 / dotenv 解析 / 只读投影）收敛在
``shared/profile_env.py``；本模块只保留 Worker 特有的 ``profile_connection``
（含迁移前数据库密文兜底）。
"""

from __future__ import annotations

import os
from pathlib import Path

from shared.profile_env import (  # noqa: F401  （对外兼容导出）
    GlobalLlmEnvValues,
    ProfileEnvValues,
    global_llm_values_from,
    profile_values_from,
    read_env_values,
)

from .crypto import decrypt_secret


def _env_path() -> Path:
    """Worker 侧环境文件路径（容器内只读挂载）。"""
    return Path(os.environ.get("PROFILE_ENV_FILE", "/run/config/.env")).expanduser()


def read_profile_env(profile_id: str) -> ProfileEnvValues:
    """读取共享环境文件中的协议档连接参数。"""
    return profile_values_from(read_env_values(_env_path()), profile_id)


def read_global_llm_env() -> GlobalLlmEnvValues:
    """读取服务器既有的单模型环境变量。"""
    return global_llm_values_from(read_env_values(_env_path()))


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
