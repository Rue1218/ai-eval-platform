"""协议档环境文件读写工具。

协议档的主模型、Embedding、Reranker 的 Base URL、模型 ID 和 API Key 不再写入数据库；本模块以 profile ID
生成稳定的环境变量名，并在 bind mount 受控 ``.env`` 文件上加锁刷新。
模块不执行 shell、不展开变量，也不会把敏感值写入日志。
"""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .config import settings

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROFILE_ID_RE = re.compile(r"[^A-Za-z0-9]+")
_ENV_WRITE_LOCK = RLock()


@dataclass(frozen=True)
class ProfileEnvSnapshot:
    """环境文件更新前的内容，用于数据库事务失败时回滚文件。"""

    path: Path
    existed: bool
    content: str
    mode: int | None


@dataclass(frozen=True)
class ProfileEnvValues:
    """协议档从环境文件读取的连接参数。"""

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
    """兼容服务器既有单模型 LLM_* 环境变量。"""

    api_key: str | None
    model: str | None
    openai_base_url: str | None
    anthropic_base_url: str | None


def env_path() -> Path:
    """解析协议档环境文件路径；相对路径按当前服务工作目录解析。"""
    return Path(settings.profile_env_file).expanduser().resolve()


def profile_env_keys(profile_id: str) -> dict[str, str]:
    """根据协议档 ID 生成固定、无冲突的环境变量名。"""
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
    """解析简单 dotenv 值；仅处理本模块写入的单引号/双引号值。"""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return parsed if isinstance(parsed, str) else value[1:-1]
    return value


def _parse_lines(lines: list[str]) -> dict[str, str]:
    """读取 KEY=VALUE 行，不执行 shell 替换或命令。"""
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if _KEY_RE.fullmatch(key):
            values[key] = _decode_value(raw)
    return values


def _read_snapshot(path: Path) -> ProfileEnvSnapshot:
    """读取文件快照；文件不存在时返回空快照。"""
    if not path.exists():
        return ProfileEnvSnapshot(path, False, "", None)
    if not path.is_file():
        raise ValueError("协议档环境文件路径不是普通文件")
    stat = path.stat()
    return ProfileEnvSnapshot(path, True, path.read_text(encoding="utf-8"), stat.st_mode & 0o777)


def _write_content(path: Path, content: str, mode: int = 0o600) -> None:
    """原位刷新 bind mount 文件，确保 API 与只读 Worker 看到同一个 inode。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as env_file:
            env_file.write(content)
            env_file.flush()
            os.fsync(env_file.fileno())
        os.chmod(path, mode)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def read_profile_env(profile_id: str) -> ProfileEnvValues:
    """读取一个协议档的环境参数；不存在的字段返回 ``None``。"""
    path = env_path()
    snapshot = _read_snapshot(path)
    values = _parse_lines(snapshot.content.splitlines())
    keys = profile_env_keys(profile_id)
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


@dataclass(frozen=True)
class GlobalRagEnvValues:
    """系统全局唯一的 Embedding 与 Reranker 模型环境参数。"""

    embedding_base_url: str | None
    embedding_model: str | None
    embedding_api_key: str | None
    reranker_base_url: str | None
    reranker_model: str | None
    reranker_api_key: str | None


def read_global_rag_env() -> GlobalRagEnvValues:
    """读取系统全局唯一的 Embedding 与 Reranker 模型环境参数。"""
    snapshot = _read_snapshot(env_path())
    values = _parse_lines(snapshot.content.splitlines())
    return GlobalRagEnvValues(
        embedding_base_url=values.get("AI_EMBEDDING_BASE_URL") or None,
        embedding_model=values.get("AI_EMBEDDING_MODEL") or None,
        embedding_api_key=values.get("AI_EMBEDDING_API_KEY") or None,
        reranker_base_url=values.get("AI_RERANKER_BASE_URL") or None,
        reranker_model=values.get("AI_RERANKER_MODEL") or None,
        reranker_api_key=values.get("AI_RERANKER_API_KEY") or None,
    )


def write_global_rag_env(
    *,
    embedding_base_url: str | None = None,
    embedding_model: str | None = None,
    embedding_api_key: str | None = None,
    reranker_base_url: str | None = None,
    reranker_model: str | None = None,
    reranker_api_key: str | None = None,
) -> ProfileEnvSnapshot:
    """安全保存系统全局唯一的 Embedding 与 Reranker 模型环境参数。"""
    with _ENV_WRITE_LOCK:
        path = env_path()
        snapshot = _read_snapshot(path)
        lines = snapshot.content.splitlines()
        updates: dict[str, str] = {}
        if embedding_base_url is not None:
            updates["AI_EMBEDDING_BASE_URL"] = str(embedding_base_url).rstrip("/")
        if embedding_model is not None:
            updates["AI_EMBEDDING_MODEL"] = str(embedding_model).strip()
        if embedding_api_key is not None and str(embedding_api_key).strip():
            updates["AI_EMBEDDING_API_KEY"] = str(embedding_api_key).strip()
        if reranker_base_url is not None:
            updates["AI_RERANKER_BASE_URL"] = str(reranker_base_url).rstrip("/")
        if reranker_model is not None:
            updates["AI_RERANKER_MODEL"] = str(reranker_model).strip()
        if reranker_api_key is not None and str(reranker_api_key).strip():
            updates["AI_RERANKER_API_KEY"] = str(reranker_api_key).strip()

        if not updates:
            return snapshot

        rendered: list[str] = []
        seen: set[str] = set()
        for line in lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if key in updates:
                rendered.append(f"{key}={json.dumps(updates[key], ensure_ascii=False)}")
                seen.add(key)
            else:
                rendered.append(line)
        for key, value in updates.items():
            if key not in seen:
                rendered.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
        content = "\n".join(rendered).rstrip("\n") + "\n"
        _write_content(path, content)
        return snapshot


def read_global_llm_env() -> GlobalLlmEnvValues:
    """读取服务器既有的单模型环境变量，供未迁移旧协议档兼容使用。"""
    snapshot = _read_snapshot(env_path())
    values = _parse_lines(snapshot.content.splitlines())
    return GlobalLlmEnvValues(
        api_key=values.get("LLM_API_KEY") or None,
        model=values.get("LLM_MODEL") or None,
        openai_base_url=values.get("OPENAI_BASE_URL") or None,
        anthropic_base_url=values.get("ANTHROPIC_BASE_URL") or None,
    )


def write_profile_env(
    profile_id: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    embedding_base_url: str | None = None,
    embedding_model: str | None = None,
    embedding_api_key: str | None = None,
    reranker_base_url: str | None = None,
    reranker_model: str | None = None,
    reranker_api_key: str | None = None,
    remove_api_key: bool = False,
    remove_embedding_api_key: bool = False,
    remove_reranker_api_key: bool = False,
    protocol: str | None = None,
    write_global_aliases: bool = False,
    remove_global_api_key: bool = False,
) -> ProfileEnvSnapshot:
    """安全刷新协议档连接参数并返回写入前快照。

    ``None`` 表示保留原值，``remove_*_api_key`` 仅用于明确删除密钥；API 页面留空
    时不会误删既有 Key。值采用 JSON 字符串转义，避免 ``#``、空格和换行破坏 dotenv。
    """
    with _ENV_WRITE_LOCK:
        path = env_path()
        snapshot = _read_snapshot(path)
        lines = snapshot.content.splitlines()
        keys = profile_env_keys(profile_id)
        updates: dict[str, str] = {}
        removals: set[str] = set()
        endpoint_values = {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "embedding_base_url": embedding_base_url,
            "embedding_model": embedding_model,
            "embedding_api_key": embedding_api_key,
            "reranker_base_url": reranker_base_url,
            "reranker_model": reranker_model,
            "reranker_api_key": reranker_api_key,
        }
        for field, value in endpoint_values.items():
            if value is not None:
                updates[keys[field]] = value
        if remove_api_key:
            removals.add(keys["api_key"])
        if remove_embedding_api_key:
            removals.add(keys["embedding_api_key"])
        if remove_reranker_api_key:
            removals.add(keys["reranker_api_key"])
        if write_global_aliases:
            if api_key is not None:
                updates["LLM_API_KEY"] = api_key
            elif remove_global_api_key:
                removals.add("LLM_API_KEY")
            if model is not None:
                updates["LLM_MODEL"] = model
            if base_url is not None:
                alias = "ANTHROPIC_BASE_URL" if protocol == "anthropic_messages" else "OPENAI_BASE_URL"
                updates[alias] = base_url
        if not updates and not removals:
            return snapshot

        rendered: list[str] = []
        seen: set[str] = set()
        for line in lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if key in removals:
                continue
            if key in updates:
                rendered.append(f"{key}={json.dumps(updates[key], ensure_ascii=False)}")
                seen.add(key)
            else:
                rendered.append(line)
        for key, value in updates.items():
            if key not in seen:
                rendered.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
        content = "\n".join(rendered).rstrip("\n") + "\n"
        _write_content(path, content)
        return snapshot


def remove_profile_env(profile_id: str) -> ProfileEnvSnapshot:
    """从环境文件删除协议档的主模型、Embedding、Reranker 全部变量。"""
    with _ENV_WRITE_LOCK:
        path = env_path()
        snapshot = _read_snapshot(path)
        lines = snapshot.content.splitlines()
        keys = set(profile_env_keys(profile_id).values())
        rendered = [
            line
            for line in lines
            if not ("=" in line and line.strip().split("=", 1)[0].strip() in keys)
        ]
        if rendered == lines:
            return snapshot
        content = "\n".join(rendered).rstrip("\n") + ("\n" if rendered else "")
        _write_content(path, content)
        return snapshot


def restore_snapshot(snapshot: ProfileEnvSnapshot) -> None:
    """恢复一次环境文件变更；仅供同一事务失败回滚使用。"""
    path = snapshot.path
    if not snapshot.existed:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    with _ENV_WRITE_LOCK:
        _write_content(path, snapshot.content, snapshot.mode or 0o600)


def resolve_env_api_key_for_url(base_url: str | None, protocol: str | None = None) -> str | None:
    """根据给定的 Base URL 或协议类型，从 .env 环境文件（及进程环境变量）中自动匹配可用的 API Key。"""
    try:
        snapshot = _read_snapshot(env_path())
        values = _parse_lines(snapshot.content.splitlines())
    except Exception:
        values = {}

    def _get(key: str) -> str | None:
        return values.get(key) or os.environ.get(key) or None

    norm_target = str(base_url or "").strip().rstrip("/")
    if norm_target.endswith("/v1"):
        norm_target = norm_target[:-3].rstrip("/")

    # 1. 优先在已有的 AI_PROFILE_*_BASE_URL 中寻找匹配的 profile Key
    if norm_target:
        combined = {**values, **os.environ}
        for k, v in combined.items():
            if k.startswith("AI_PROFILE_") and k.endswith("_BASE_URL"):
                profile_base = str(v).strip().rstrip("/")
                if profile_base.endswith("/v1"):
                    profile_base = profile_base[:-3].rstrip("/")
                if profile_base == norm_target:
                    key_var = k[:-9] + "_API_KEY"
                    cand = _get(key_var)
                    if cand:
                        return cand

    # 2. 根据 Base URL 中的厂商域名特征映射环境变量
    url_lower = norm_target.lower()
    if "xiaomimimo" in url_lower or "mimo" in url_lower:
        for var in ("MIMO_API_KEY", "MIMO_TTS_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "openai" in url_lower:
        for var in ("OPENAI_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "anthropic" in url_lower:
        for var in ("ANTHROPIC_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "deepseek" in url_lower:
        for var in ("DEEPSEEK_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "siliconflow" in url_lower:
        for var in ("SILICONFLOW_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "dashscope" in url_lower or "aliyuncs" in url_lower or "qwen" in url_lower:
        for var in ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "QWEN_IMAGE_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "nvidia" in url_lower or "integrate.api.nvidia" in url_lower:
        for var in ("NVIDIA_API_KEY", "NIM_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "volces" in url_lower or "volcengine" in url_lower:
        for var in ("VOLCENGINE_API_KEY", "DOUBAO_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "baidubce" in url_lower or "qianfan" in url_lower:
        for var in ("QIANFAN_API_KEY", "BAIDU_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "bigmodel" in url_lower or "zhipu" in url_lower:
        for var in ("ZHIPU_API_KEY", "GLM_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "moonshot" in url_lower or "kimi" in url_lower:
        for var in ("MOONSHOT_API_KEY", "KIMI_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "groq" in url_lower:
        for var in ("GROQ_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "together" in url_lower:
        for var in ("TOGETHER_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "mistral" in url_lower:
        for var in ("MISTRAL_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "lingyi" in url_lower or "01.ai" in url_lower:
        for var in ("LINGYI_API_KEY", "YI_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val
    elif "baichuan" in url_lower:
        for var in ("BAICHUAN_API_KEY", "LLM_API_KEY"):
            val = _get(var)
            if val:
                return val

    # 3. 按协议类型或通用别名兜底
    if protocol == "anthropic_messages":
        return _get("ANTHROPIC_API_KEY") or _get("LLM_API_KEY")
    return _get("OPENAI_API_KEY") or _get("LLM_API_KEY")


def resolve_env_base_url(protocol: str | None = None) -> str | None:
    """根据协议类型从 .env 环境文件中读取默认 Base URL。"""
    try:
        snapshot = _read_snapshot(env_path())
        values = _parse_lines(snapshot.content.splitlines())
    except Exception:
        values = {}

    def _get(key: str) -> str | None:
        return values.get(key) or os.environ.get(key) or None

    if protocol == "anthropic_messages":
        return _get("ANTHROPIC_BASE_URL") or _get("LLM_BASE_URL")
    return _get("OPENAI_BASE_URL") or _get("LLM_BASE_URL")

