"""协议档环境文件读写工具（API 侧：读写 + 快照回滚）。

共享部分（数据类 / 键名生成 / dotenv 解析 / 只读投影）收敛在 ``shared/profile_env.py``，
本模块保留 API 独有的写能力（快照 / 回滚 / 全局 RAG 写入）与 URL→Key 解析。
模块不执行 shell、不展开变量，也不会把敏感值写入日志。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from shared.profile_env import (  # noqa: F401  （对外兼容导出）
    GlobalLlmEnvValues,
    GlobalRagEnvValues,
    ProfileEnvValues,
    global_llm_values_from,
    global_rag_values_from,
    profile_env_keys,
    profile_values_from,
)
from shared.profile_env import parse_env_lines as _parse_lines

from .config import settings

_ENV_WRITE_LOCK = RLock()
# 仅能力投影的同步请求作用域复用，不跨请求缓存凭据或影响写入后的读取。
_ENV_READ_VALUES: ContextVar[list[dict[str, str]] | None] = ContextVar("profile_env_read_values", default=None)


@contextmanager
def profile_env_read_scope():
    """一次只读能力投影使用同一份文件快照，结束或异常时立即归还上下文。"""
    # 惰性读取保留调用方原有的异常归一化边界；容器最多保存一份解析快照。
    token = _ENV_READ_VALUES.set([])
    try:
        yield
    finally:
        _ENV_READ_VALUES.reset(token)


def _read_values() -> dict[str, str]:
    """读取当前作用域快照；普通调用仍从文件获取最新值。"""
    scope = _ENV_READ_VALUES.get()
    if scope:
        return scope[0]
    values = _parse_lines(_read_snapshot(env_path()).content.splitlines())
    if scope is not None:
        scope.append(values)
    return values


@dataclass(frozen=True)
class ProfileEnvSnapshot:
    """环境文件更新前的内容，用于数据库事务失败时回滚文件。"""

    path: Path
    existed: bool
    content: str
    mode: int | None


@dataclass(frozen=True)
class MediaMcpEnvValues:
    """媒体 MCP 的受控配置投影；密钥仅以是否存在的形式对外暴露。"""

    enabled: bool | None
    compatible_base_url: str | None
    api_key: str | None
    image_model: str | None
    video_model: str | None
    request_timeout_s: float | None


def env_path() -> Path:
    """解析协议档环境文件路径；相对路径按当前服务工作目录解析。"""
    return Path(settings.profile_env_file).expanduser().resolve()


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
        # Windows Python 3.12 无 fchmod；创建模式和下方路径 chmod 仍生效。
        if hasattr(os, "fchmod"):
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
    values = _read_values()
    return profile_values_from(values, profile_id)


def read_global_rag_env() -> GlobalRagEnvValues:
    """读取系统全局唯一的 Embedding 与 Reranker 模型环境参数。"""
    values = _read_values()
    return global_rag_values_from(values)


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
    values = _read_values()
    return global_llm_values_from(values)


def read_media_mcp_env() -> MediaMcpEnvValues:
    """读取媒体 MCP 配置；格式非法的超时值按缺失处理，避免把异常带入响应。"""
    values = _read_values()
    raw_timeout = values.get("MEDIA_MCP_REQUEST_TIMEOUT_S")
    try:
        timeout = float(raw_timeout) if raw_timeout else None
    except ValueError:
        timeout = None
    raw_enabled = values.get("MEDIA_MCP_ENABLED")
    enabled = raw_enabled.strip().lower() in {"1", "true", "yes", "on"} if raw_enabled else None
    return MediaMcpEnvValues(
        enabled=enabled,
        compatible_base_url=values.get("MEDIA_MCP_COMPATIBLE_BASE_URL") or None,
        api_key=values.get("MEDIA_MCP_API_KEY") or None,
        image_model=values.get("MEDIA_MCP_IMAGE_MODEL") or None,
        video_model=values.get("MEDIA_MCP_VIDEO_MODEL") or None,
        request_timeout_s=timeout,
    )


def write_media_mcp_env(
    *,
    enabled: bool | None = None,
    compatible_base_url: str | None = None,
    api_key: str | None = None,
    image_model: str | None = None,
    video_model: str | None = None,
    request_timeout_s: float | None = None,
) -> ProfileEnvSnapshot:
    """原位保存媒体 MCP 配置；空 API Key 表示保留，禁止意外清除既有凭据。"""
    updates: dict[str, str] = {}
    if enabled is not None:
        updates["MEDIA_MCP_ENABLED"] = str(enabled).lower()
    if compatible_base_url is not None:
        updates["MEDIA_MCP_COMPATIBLE_BASE_URL"] = compatible_base_url.rstrip("/")
    if api_key is not None and api_key.strip():
        updates["MEDIA_MCP_API_KEY"] = api_key.strip()
    if image_model is not None:
        updates["MEDIA_MCP_IMAGE_MODEL"] = image_model.strip()
    if video_model is not None:
        updates["MEDIA_MCP_VIDEO_MODEL"] = video_model.strip()
    if request_timeout_s is not None:
        updates["MEDIA_MCP_REQUEST_TIMEOUT_S"] = str(request_timeout_s)
    if not updates:
        with _ENV_WRITE_LOCK:
            return _read_snapshot(env_path())
    with _ENV_WRITE_LOCK:
        path = env_path()
        snapshot = _read_snapshot(path)
        rendered: list[str] = []
        seen: set[str] = set()
        for line in snapshot.content.splitlines():
            key = line.strip().split("=", 1)[0].strip() if "=" in line else ""
            if key in updates:
                rendered.append(f"{key}={json.dumps(updates[key], ensure_ascii=False)}")
                seen.add(key)
            else:
                rendered.append(line)
        for key, value in updates.items():
            if key not in seen:
                rendered.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
        _write_content(path, "\n".join(rendered).rstrip("\n") + "\n")
        return snapshot


def write_profile_env(
    profile_id: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    full_url: bool | None = None,
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
            "full_url": str(full_url).lower() if full_url is not None else None,
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
    """仅从已配置的同源端点解析凭据，不按 URL 子串或协议向任意主机兜底。"""
    from shared.model_urls import same_origin

    try:
        snapshot = _read_snapshot(env_path())
        values = _parse_lines(snapshot.content.splitlines())
    except Exception:
        values = {}
    # 环境文件与原有读取语义一致，优先于进程环境，避免端点和密钥来源混搭。
    combined = {**os.environ, **values}
    for name, configured_url in combined.items():
        if name.startswith("AI_PROFILE_") and name.endswith("_BASE_URL"):
            if same_origin(base_url, configured_url):
                candidate = combined.get(name[:-9] + "_API_KEY")
                if candidate:
                    return candidate
    # 全局别名也必须与它自己的显式端点成对；原厂默认地址仅用于无自定义地址的专属 Key。
    prefixes = ("ANTHROPIC", "LLM") if protocol == "anthropic_messages" else ("OPENAI", "LLM")
    for prefix in prefixes:
        configured_url = combined.get(prefix + "_BASE_URL")
        default_url = {"OPENAI": "https://api.openai.com", "ANTHROPIC": "https://api.anthropic.com"}.get(prefix)
        if same_origin(base_url, configured_url or default_url):
            candidate = combined.get(prefix + "_API_KEY")
            if not candidate and configured_url and prefix in {"OPENAI", "ANTHROPIC"}:
                # 历史部署使用 OPENAI/ANTHROPIC_BASE_URL + LLM_API_KEY，仍须显式地址匹配。
                candidate = combined.get("LLM_API_KEY")
            if candidate:
                return candidate
    # 其它厂商仅接受部署者明确配置的 BASE_URL / API_KEY 对，不猜测凭据所属主机。
    for name, configured_url in combined.items():
        if name.endswith("_BASE_URL") and not name.startswith("AI_PROFILE_"):
            if same_origin(base_url, configured_url):
                candidate = combined.get(name[:-9] + "_API_KEY")
                if candidate:
                    return candidate
    return None


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
