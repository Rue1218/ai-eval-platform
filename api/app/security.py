import base64
from datetime import datetime, timedelta, timezone

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


def create_token(sub: str, role: str, token_type: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def _get_fernet() -> Fernet:
    key = settings.key_encryption_key
    if not key:
        # 开发回退：由 SECRET_KEY 派生，重启后不变（SECRET_KEY 不变即可）。生产必须显式配置。
        derived = base64.urlsafe_b64encode(settings.secret_key.encode().ljust(32)[:32])
        return Fernet(derived)
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()
