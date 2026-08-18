"""认证令牌安全边界测试。"""

from app.security import TOKEN_TYPE_ACCESS, create_token, decode_token


def test_access_token_includes_auth_version():
    """认证版本进入 JWT，服务端可在改密后拒绝旧 Cookie。"""
    token = create_token("user-1", 7, TOKEN_TYPE_ACCESS, 10)
    payload = decode_token(token)

    assert payload["sub"] == "user-1"
    assert payload["av"] == 7
    assert payload["type"] == TOKEN_TYPE_ACCESS
