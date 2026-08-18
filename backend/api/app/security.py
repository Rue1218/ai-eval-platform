import base64
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet

from .config import settings

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_WS = "ws_ticket"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(
    sub: str,
    auth_version: int,
    token_type: str,
    expires_minutes: int,
) -> str:
    """签发包含账号认证版本的短期 JWT，改密后旧票自动失效。"""
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "av": auth_version,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    """校验签名和有效期后解析 JWT 负载。"""
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def _get_fernet() -> Fernet:
    """获取凭据加密器；生产环境必须显式设置独立密钥。"""
    key = settings.key_encryption_key
    if not key:
        # 开发回退：由 SECRET_KEY 派生，重启后不变（SECRET_KEY 不变即可）。生产必须显式配置。
        derived = base64.urlsafe_b64encode(settings.secret_key.encode().ljust(32)[:32])
        return Fernet(derived)
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    """加密仅写入的上游凭据。"""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """仅在服务端调用上游前解密凭据，禁止进入响应或日志。"""
    return _get_fernet().decrypt(value.encode()).decode()
