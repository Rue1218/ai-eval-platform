"""API 与 Worker 共用的模型端点拼接规则。"""

import re
from urllib.parse import urlsplit, urlunsplit


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
