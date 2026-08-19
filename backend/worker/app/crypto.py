"""凭据解密（与 ``api/app/security.py`` 的 ``_get_fernet`` 口径一致）。

Worker 容器不安装 pydantic-settings / jwt / bcrypt，因此独立实现最小
Fernet 解密：优先读 ``KEY_ENCRYPTION_KEY``，缺失时与 api 侧相同地由
``SECRET_KEY`` 派生回退密钥。修改加密口径时必须同步 api 侧实现。
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken


def decrypt_secret(value: str) -> str:
    """解密协议档密文；密钥来源与 api 容器保持一致。"""
    key = os.environ.get("KEY_ENCRYPTION_KEY", "")
    if not key:
        secret = os.environ.get("SECRET_KEY", "dev-secret-change-me")
        key = base64.urlsafe_b64encode(secret.encode().ljust(32)[:32]).decode()
    try:
        return Fernet(key.encode()).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        # 不回显密文与密钥，仅提示口径不一致便于排查部署配置
        raise ValueError("凭据解密失败：请检查 worker 与 api 的 KEY_ENCRYPTION_KEY 配置一致") from exc
