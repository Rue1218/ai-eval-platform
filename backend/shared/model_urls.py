"""API 与 Worker 共用的模型端点拼接规则。"""

import re
from urllib.parse import urlsplit, urlunsplit


def same_origin(left: str | None, right: str | None) -> bool:
    """凭据只允许复用到相同协议、主机和有效端口，非法地址一律不匹配。"""
    def origin(value: str | None) -> tuple | None:
        """拒绝用户信息、反斜线和畸形端口，避免不同 URL 解析器产生歧义。"""
        if not value or "\\" in value:
            return None
        try:
            parsed = urlsplit(value.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                return None
            port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
            return parsed.scheme, parsed.hostname.lower(), port
        except ValueError:
            return None

    first = origin(left)
    return first is not None and first == origin(right)


def model_request_url(base_url: str, protocol: str, *, full_url: bool = False) -> str:
    """完整 URL 保持路径与查询串；Base URL 仅补缺失的版本和资源段。"""
    url = base_url.strip()
    parts = urlsplit(url)
    if (parts.scheme not in {"https", "http"} or not parts.hostname
            or parts.username or parts.password or parts.fragment
            or (parts.query and not full_url)):
        raise ValueError("模型服务地址不合法")
    if full_url:
        return url
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/messages", "/models"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    # GLM /v4、火山 /v3、Gemini /v1beta/openai 已含供应商版本，不能再补 /v1。
    versioned = (path.endswith("/v1") if protocol == "anthropic_messages"
                 else re.search(r"/v\d+(?:beta\d*|alpha\d*)?(?:/openai)?$", path))
    if not versioned:
        path += "/v1"
    path += {"anthropic_messages": "/messages", "openai_responses": "/responses"}.get(protocol, "/chat/completions")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
