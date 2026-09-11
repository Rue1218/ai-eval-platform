"""协议档环境文件共享工具（api 与 worker 共用，消除双副本漂移）。

职责边界：
- 本模块提供数据类、键名生成、dotenv 解析与只读投影（路径参数化，无副作用）；
- 写能力（快照 / 回滚 / 全局 RAG 写入）仅 API 侧使用，保留在 ``api/app/profile_env.py``；
- Worker 侧只读（``worker/app/profile_env.py`` 委托本模块并保留 ``profile_connection``）。

约定：不执行 shell、不展开变量、不把敏感值写入日志。
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_PROFILE_ID_RE = re.compile(r"[^A-Za-z0-9]+")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ProfileEnvValues:
    """协议档从环境文件读取的连接参数；不存在的字段为 ``None``。"""

    base_url: str | None
    model: str | None
    api_key: str | None
    full_url: bool = False  # 完整端点不追加协议后缀。
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    reranker_base_url: str | None = None
    reranker_model: str | None = None
    reranker_api_key: str | None = None


@dataclass(frozen=True)
class GlobalLlmEnvValues:
    """兼容服务器既有单模型 LLM_* 环境变量。"""

    api_key: str | None
    model: str | None
    openai_base_url: str | None
    anthropic_base_url: str | None


@dataclass(frozen=True)
class GlobalRagEnvValues:
    """系统全局唯一的 Embedding 与 Reranker 模型环境参数。"""

    embedding_base_url: str | None
    embedding_model: str | None
    embedding_api_key: str | None
    reranker_base_url: str | None
    reranker_model: str | None
    reranker_api_key: str | None


def profile_env_keys(profile_id: str) -> dict[str, str]:
    """根据协议档 ID 生成固定、无冲突的环境变量名。"""
    token = _PROFILE_ID_RE.sub("_", str(profile_id)).strip("_").upper() or "UNKNOWN"
    return {
        "base_url": f"AI_PROFILE_{token}_BASE_URL",
        "model": f"AI_PROFILE_{token}_MODEL",
        "full_url": f"AI_PROFILE_{token}_FULL_URL",
        "api_key": f"AI_PROFILE_{token}_API_KEY",
        "embedding_base_url": f"AI_PROFILE_{token}_EMBEDDING_BASE_URL",
        "embedding_model": f"AI_PROFILE_{token}_EMBEDDING_MODEL",
        "embedding_api_key": f"AI_PROFILE_{token}_EMBEDDING_API_KEY",
        "reranker_base_url": f"AI_PROFILE_{token}_RERANKER_BASE_URL",
        "reranker_model": f"AI_PROFILE_{token}_RERANKER_MODEL",
        "reranker_api_key": f"AI_PROFILE_{token}_RERANKER_API_KEY",
    }


def decode_value(raw: str) -> str:
    """解析简单 dotenv 值；仅处理本模块写入的单引号/双引号值。"""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return parsed if isinstance(parsed, str) else value[1:-1]
    return value


def parse_env_lines(lines: list[str]) -> dict[str, str]:
    """读取 KEY=VALUE 行，不执行 shell 替换或命令；键名做正则校验。"""
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if _KEY_RE.fullmatch(key):
            values[key] = decode_value(raw)
    return values


def read_env_values(path: Path) -> dict[str, str]:
    """读取并解析环境文件；文件缺失或不是普通文件时返回空字典。"""
    if not path.exists() or not path.is_file():
        return {}
    return parse_env_lines(path.read_text(encoding="utf-8").splitlines())


def profile_values_from(values: Mapping[str, str], profile_id: str) -> ProfileEnvValues:
    """从已解析键值投影协议档连接参数（Embedding/Reranker 兼容全局别名）。"""
    keys = profile_env_keys(profile_id)
    return ProfileEnvValues(
        full_url=str(values.get(keys["full_url"], "false")).lower() == "true",
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


def global_llm_values_from(values: Mapping[str, str]) -> GlobalLlmEnvValues:
    """从已解析键值投影服务器既有单模型 LLM_* 环境变量。"""
    return GlobalLlmEnvValues(
        api_key=values.get("LLM_API_KEY") or None,
        model=values.get("LLM_MODEL") or None,
        openai_base_url=values.get("OPENAI_BASE_URL") or None,
        anthropic_base_url=values.get("ANTHROPIC_BASE_URL") or None,
    )


def global_rag_values_from(values: Mapping[str, str]) -> GlobalRagEnvValues:
    """从已解析键值投影系统全局唯一的 Embedding / Reranker 参数。"""
    return GlobalRagEnvValues(
        embedding_base_url=values.get("AI_EMBEDDING_BASE_URL") or None,
        embedding_model=values.get("AI_EMBEDDING_MODEL") or None,
        embedding_api_key=values.get("AI_EMBEDDING_API_KEY") or None,
        reranker_base_url=values.get("AI_RERANKER_BASE_URL") or None,
        reranker_model=values.get("AI_RERANKER_MODEL") or None,
        reranker_api_key=values.get("AI_RERANKER_API_KEY") or None,
    )
