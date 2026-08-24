"""会话工作区：每个会话一个独立文件夹（会话级沙箱目录）。

- 目录结构：``{root}/{session_id}``，root 由 ``AGENT_WORKSPACE_ROOT`` 环境变量
  覆盖，容器内默认 ``/data/workspaces``（api 容器挂载 ``./data:/data`` 持久
  卷），本地回退 ``data/workspaces``（相对运行目录）；
- ``session_id`` 严格校验（UUID 安全字符集），**禁止路径穿越**（M5-D7 红线
  的目录侧闭环）；
- 工作区经 ``RunnableConfig.configurable["sandbox"]["dir"]`` 注入
  （toolnode 已支持读取），``read``/``write``/``edit`` 与后续 ``bash``
  均以工作区为根天然隔离——一个会话一个工作区，会话间互不可见。
"""

from __future__ import annotations

import os
import re

from app.errors import AppError, ErrorCode

# 会话标识严格校验：UUID 或安全短标识（防路径穿越）
_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def get_workspace_root() -> str:
    """工作区根目录：env 优先 → 容器 /data/workspaces → 本地 data/workspaces。"""
    env_root = os.getenv("AGENT_WORKSPACE_ROOT")
    if env_root:
        return env_root
    if os.path.isdir("/data"):
        return "/data/workspaces"
    return "data/workspaces"


def session_workspace_dir(session_id: str) -> str:
    """校验 session_id 并返回其工作区目录（不创建，纯路径计算）。"""
    if not _SESSION_ID_RE.fullmatch(session_id or ""):
        raise AppError(ErrorCode.VALIDATION, "非法会话标识，无法创建工作区")
    return os.path.join(get_workspace_root(), session_id)


def ensure_session_workspace(session_id: str) -> str:
    """确保会话工作区存在并返回其绝对路径（mkdir -p，幂等）。"""
    directory = session_workspace_dir(session_id)
    os.makedirs(directory, exist_ok=True)
    return directory
