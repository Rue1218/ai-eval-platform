"""Harness 执行层：web_search / web_fetch 原生网络工具（SSRF 防护 + 正文提取）。

从 dispatch.py 拆出（2026-09-11 巨型文件治理）：共享底层（预览预算 / 行边界截断 /
网络防护）见 dispatch_common.py；本模块只保留网络工具域。
"""

from __future__ import annotations

import codecs
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS

from .dispatch_common import (
    ToolOutputCallback,
    ToolProgressCallback,
    _reject_internal_target,
    clip_at_line_boundary,
    preview_char_limit,
)

logger = logging.getLogger("ai-eval.harness.dispatch.web")

# web_fetch 专属正文预算：与全局 MODEL_TOOL_RESULT_MAX_CHARS 解耦（2026-08-28
# 调整：旧 8000 字符上限把知乎专栏等长文截掉大半，模型只能基于半篇作答）。
# 网页正文噪声高于本地文件，预算按 READ_MAX_CHARS 的十分之一量级熔断。
WEB_FETCH_MAX_CHARS = 60_000
# web_search 拼接摘要仍用全局 8000 字符预算，避免多条搜索结果挤占上下文。
WEB_MAX_SEARCH_CHARS = MODEL_TOOL_RESULT_MAX_CHARS
WEB_MAX_SEARCH_RESULTS = 10
# 直接抓取路径的 HTML 字节窗口：知乎等长文单页 HTML 常超 256KB，窗口过小会
# 让正文提取器只见半页标记；放宽到 1MB 仍保持受控读取。
WEB_RESPONSE_MAX_BYTES = 1024 * 1024
# 直接抓取纯文本时的网络读取粒度。HTML 必须完成正文提取后才能安全展示，因此
# 不在这里将原始标签流推给浏览器。
WEB_RESPONSE_STREAM_CHUNK_BYTES = 8 * 1024


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    """网页搜索结果：模型正文与 ToolCard 投影分离。"""

    query: str
    results: tuple[dict[str, str], ...]

    def to_tool_data(self) -> dict[str, object]:
        """返回受控搜索结果，完整描述仅保留给下一模型回合。"""
        lines: list[str] = [f"搜索关键词：{self.query}"]
        for index, result in enumerate(self.results, start=1):
            lines.append(f"[{index}] {result['title']}\nURL: {result['url']}\n{result['description']}")
        model_text = "\n\n".join(lines)[:WEB_MAX_SEARCH_CHARS]
        summary = f"网络搜索完成，返回 {len(self.results)} 条结果"
        return {
            "summary": summary,
            "model_text": model_text,
            "truncated": len("\n\n".join(lines)) > len(model_text),
            "source": "web:search",
            "display": {
                "summary": summary,
                "results": [
                    {
                        "title": item.get("title") or "",
                        "url": item.get("url") or "",
                        "content": item.get("description") or "",
                        "score": item.get("score") or "",
                    }
                    for item in self.results
                ],
                "search": {"query": self.query, "results": list(self.results)},
            },
        }


@dataclass(frozen=True, slots=True)
class WebFetchResult:
    """网页抓取结果：正文仅进入 Observation，浏览器只看元数据与短预览。"""

    url: str
    title: str
    content: str
    format: str
    truncated: bool

    def to_tool_data(self) -> dict[str, object]:
        """返回模型正文和受控 ToolCard 投影。

        卡片预览与 read/write/bash 同源对齐 ``preview_char_limit()``（2026-08-28
        调整：旧 500 字符预览让网页抓取卡片几乎不可读），保证「卡片所见 ==
        模型真实读取内容」，并下发实际预览上限供前端提示文案使用。
        """
        title = self.title or urlparse(self.url).hostname or "网页"
        summary = f"已抓取 {title}"
        preview_limit = preview_char_limit()
        preview, preview_truncated = clip_at_line_boundary(self.content, preview_limit)
        return {
            "summary": summary,
            "model_text": self.content,
            "truncated": self.truncated,
            "source": f"web:{urlparse(self.url).hostname or 'unknown'}",
            "display": {
                "summary": summary,
                "content": preview,
                "title": self.title,
                "url": self.url,
                "web": {
                    "url": self.url,
                    "title": self.title,
                    "format": self.format,
                    "preview": preview,
                    "preview_truncated": preview_truncated,
                    # 生效的预览上限随数据下发，前端提示文案不硬编码数字。
                    "preview_limit_chars": preview_limit,
                },
            },
        }


class _TextExtractor(HTMLParser):
    """最小 HTML 正文提取器，供未配置抓取服务时的安全降级使用。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._title: list[str] = []
        self._parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """忽略脚本/样式等非正文节点，并记录页面标题。"""
        _ = attrs
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        elif lower == "title":
            self._in_title = True
        elif lower in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """结束忽略节点或标题节点。"""
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        """保留正文可见文本，丢弃脚本与样式文本。"""
        if self._ignored_depth:
            return
        if self._in_title:
            self._title.append(data)
        self._parts.append(data)

    def result(self) -> tuple[str, str]:
        """输出去除空白后的标题和正文。"""
        title = " ".join("".join(self._title).split())
        body = "\n".join(line.strip() for line in "".join(self._parts).splitlines() if line.strip())
        return title, body


def _load_trafilatura() -> ModuleType | None:
    """懒加载 trafilatura 可选依赖；未安装返回 None，由调用方走内置降级提取器。"""
    try:
        import trafilatura
    except ImportError:
        return None
    return trafilatura


def _extract_article_with_trafilatura(decoded: str, url: str, format: str) -> str | None:
    """用 trafilatura 做正文级提取（2026-08-28 接入，替代朴素全文本展开）。

    trafilatura 以可读性算法识别文章主体：丢弃导航/页脚/脚本噪声，保留
    标题层级、链接、图片、列表与表格，Markdown 输出与 Firecrawl 对齐。
    未安装、提取失败或无正文时返回 None，调用方降级回内置 ``_TextExtractor``。
    """
    trafilatura = _load_trafilatura()
    if trafilatura is None:
        return None
    try:
        extracted = trafilatura.extract(
            decoded,
            url=url,
            # favor_recall：宁可多保留正文也不丢段落（知乎等长文剪枝保护）。
            favor_recall=True,
            output_format="markdown" if format == "markdown" else "txt",
            include_links=True,
            include_images=True,
            include_formatting=True,
            include_tables=True,
            include_comments=False,
        )
    except Exception as exc:
        # 只记异常类型不记原文（§5.2.1）；失败降级为内置提取器，不中断抓取。
        logger.info("trafilatura 提取失败 type=%s", type(exc).__name__)
        return None
    if not isinstance(extracted, str) or not extracted.strip():
        return None
    return extracted


def _validate_public_url(url: str) -> str:
    """校验 HTTP(S) URL、拒绝凭据和内网目标，供首次与重定向请求共用。"""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise AppError(ErrorCode.VALIDATION, "仅支持 http/https 地址")
    if not parsed.hostname:
        raise AppError(ErrorCode.VALIDATION, "URL 缺少主机名")
    if parsed.username or parsed.password:
        raise AppError(ErrorCode.VALIDATION, "URL 不允许包含访问凭据")
    _reject_internal_target(parsed.hostname)
    return parsed.geturl()


class _SafeRedirectHandler(HTTPRedirectHandler):
    """在每次 HTTP 重定向前重新执行 SSRF 校验，阻断 DNS/跳转绕过。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001,D102
        _ = (fp, code, msg, headers)
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_limited_response(
    response,
    *,
    on_chunk: Callable[[bytes], None] | None = None,
) -> tuple[bytes, bool]:
    """读取受控字节窗口，并可将已确认的文本字节分块交给调用方。

    多读一个字节只用于判断截断，绝不通过 ``on_chunk`` 发给浏览器。未传回调时
    保持一次性读取，避免改变 Firecrawl 等 JSON 响应的既有行为。
    """
    if on_chunk is None:
        body = response.read(WEB_RESPONSE_MAX_BYTES + 1)
        return body[:WEB_RESPONSE_MAX_BYTES], len(body) > WEB_RESPONSE_MAX_BYTES

    buffered = bytearray()
    limit_with_probe = WEB_RESPONSE_MAX_BYTES + 1
    while len(buffered) < limit_with_probe:
        size = min(WEB_RESPONSE_STREAM_CHUNK_BYTES, limit_with_probe - len(buffered))
        chunk = response.read(size)
        if not chunk:
            break
        allowed = max(0, WEB_RESPONSE_MAX_BYTES - len(buffered))
        visible = chunk[:allowed]
        if visible:
            on_chunk(visible)
        buffered.extend(chunk)
    return bytes(buffered[:WEB_RESPONSE_MAX_BYTES]), len(buffered) > WEB_RESPONSE_MAX_BYTES


def _request_firecrawl(path: str, payload: dict[str, object], *, timeout_s: float) -> object:
    """调用服务端配置的 Firecrawl REST，不向模型、日志或事件暴露密钥。"""
    api_key = settings.firecrawl_api_key.strip()
    if not api_key:
        raise AppError(ErrorCode.VALIDATION, "网络搜索服务未配置")
    request = Request(
        f"{settings.firecrawl_api_url.rstrip('/')}/{path.lstrip('/')}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ai-eval-platform/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - 固定服务端配置地址
            raw, _ = _read_limited_response(response)
    except HTTPError as exc:
        if exc.code == 401:
            raise AppError(ErrorCode.UPSTREAM, "网络搜索服务鉴权失败") from exc
        if exc.code == 429:
            raise AppError(ErrorCode.UPSTREAM, "网络搜索服务繁忙，请稍后重试") from exc
        raise AppError(ErrorCode.UPSTREAM, "网络搜索服务请求失败") from exc
    except URLError as exc:
        raise AppError(ErrorCode.UPSTREAM, "网络搜索服务不可达") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "网络搜索服务超时") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "网络搜索服务返回无效数据") from exc


def _coerce_limit(value: object | None) -> int:
    """解析搜索结果数，避免布尔和异常类型穿透到上游请求。"""
    if value is None:
        return 5
    if isinstance(value, bool):
        raise AppError(ErrorCode.VALIDATION, "搜索结果数量必须为整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION, "搜索结果数量必须为整数") from exc
    if not 1 <= parsed <= WEB_MAX_SEARCH_RESULTS:
        raise AppError(ErrorCode.VALIDATION, "搜索结果数量必须在 1 到 10 之间")
    return parsed


def web_search(
    query: str,
    *,
    limit: object | None = None,
    timeout_s: float,
) -> WebSearchResult:
    """通过服务端 Firecrawl REST 执行真实网络搜索（非 MCP transport）。"""
    normalized_query = query.strip()
    if not normalized_query:
        raise AppError(ErrorCode.VALIDATION, "检索关键词不能为空")
    result_limit = _coerce_limit(limit)
    response = _request_firecrawl(
        "search",
        {"query": normalized_query, "limit": result_limit},
        timeout_s=timeout_s,
    )
    raw_items = response.get("data", []) if isinstance(response, dict) else response
    if not isinstance(raw_items, list):
        raise AppError(ErrorCode.UPSTREAM, "网络搜索服务返回格式无效")
    results: list[dict[str, str]] = []
    for item in raw_items[:result_limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": str(item.get("title") or item.get("name") or url)[:300],
                "url": url[:2048],
                "description": str(item.get("description") or item.get("snippet") or item.get("summary") or "")[:500],
            }
        )
    logger.info("web_search completed query_length=%d result_count=%d", len(normalized_query), len(results))
    return WebSearchResult(query=normalized_query, results=tuple(results))


def _fetch_via_firecrawl(
    url: str,
    format: str,
    *,
    timeout_s: float,
    on_progress: ToolProgressCallback | None = None,
) -> WebFetchResult:
    """使用已配置的 Firecrawl 提取网页 Markdown，复用真实搜索服务配额。"""
    if on_progress is not None:
        on_progress("fetching", "正在请求受控网页抓取服务")
    response = _request_firecrawl(
        "scrape",
        {"url": url, "formats": ["markdown" if format == "markdown" else "html"]},
        timeout_s=timeout_s,
    )
    if on_progress is not None:
        on_progress("extracting", "正在整理网页正文")
    data = response.get("data", response) if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        raise AppError(ErrorCode.UPSTREAM, "网页抓取服务返回格式无效")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    raw_content = data.get("markdown" if format == "markdown" else "html")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise AppError(ErrorCode.UPSTREAM, "网页抓取服务未返回正文")
    content = raw_content[:WEB_FETCH_MAX_CHARS]
    return WebFetchResult(
        url=url,
        title=str(metadata.get("title") or "")[:300],
        content=content,
        format=format,
        truncated=len(raw_content) > len(content),
    )


def _fetch_direct(
    url: str,
    format: str,
    *,
    timeout_s: float,
    on_output: ToolOutputCallback | None = None,
    on_progress: ToolProgressCallback | None = None,
) -> WebFetchResult:
    """未配置 Firecrawl 时，以受控 HTTP 抓取 + trafilatura 正文提取提供降级。"""
    opener = build_opener(_SafeRedirectHandler(), ProxyHandler({}))
    request = Request(
        url,
        headers={
            "Accept": "text/html, text/plain, application/json;q=0.9, */*;q=0.1",
            "User-Agent": "ai-eval-platform/1.0",
        },
    )
    try:
        with opener.open(request, timeout=timeout_s) as response:  # noqa: S310 - 已在入口/重定向校验
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            if not (
                content_type.startswith("text/")
                or content_type in {"application/json", "application/xml"}
            ):
                raise AppError(ErrorCode.VALIDATION, "仅支持抓取文本或 HTML 页面")
            if on_progress is not None:
                on_progress("downloading", "正在流式接收网页响应")

            text_decoder = None
            streamed_chars = 0

            def emit_text_chunk(chunk: bytes) -> None:
                """仅为非 HTML 文本逐块解码并推送，不泄露未受控的二进制响应。"""
                nonlocal streamed_chars
                if text_decoder is None or on_output is None:
                    return
                text = text_decoder.decode(chunk)
                remaining = WEB_FETCH_MAX_CHARS - streamed_chars
                visible = text[:remaining]
                if visible:
                    on_output("document", visible, None)
                    streamed_chars += len(visible)

            # HTML 的可读正文依赖完整 DOM 与正文提取器，不能把原始标签流伪装成
            # 正文；纯文本、JSON 和 XML 则可以安全地边下载边展示。
            if on_output is not None and content_type != "text/html":
                try:
                    text_decoder = codecs.getincrementaldecoder(charset)(errors="replace")
                except LookupError:
                    text_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            raw, truncated_by_bytes = _read_limited_response(
                response,
                on_chunk=emit_text_chunk if text_decoder is not None else None,
            )
            if text_decoder is not None:
                emit_text_chunk(b"")
            final_url = _validate_public_url(response.geturl())
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"抓取失败（HTTP {exc.code}）") from exc
    except URLError as exc:
        raise AppError(ErrorCode.UPSTREAM, "抓取失败（网络错误）") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "抓取超时") from exc
    if on_progress is not None:
        on_progress("extracting", "正在提取可读网页正文")
    decoded = raw.decode(charset, errors="replace")
    title = ""
    content = decoded
    result_format = "text"
    if content_type == "text/html":
        # 正文提取降级链：trafilatura 正文级提取（保标题层级/链接/图片）→
        # 内置 _TextExtractor 全文本展开 → 空正文报 UPSTREAM。
        # _TextExtractor 始终先跑一次以取 <title>；trafilatura 失败时直接复用其正文。
        extractor = _TextExtractor()
        extractor.feed(decoded)
        title, fallback_content = extractor.result()
        article = _extract_article_with_trafilatura(decoded, url, format)
        if article is not None:
            content = article
            # trafilatura 真实产出结构化 Markdown 时才声明对应格式，保持诚实。
            result_format = format
        else:
            content = fallback_content
    if not content.strip():
        raise AppError(ErrorCode.UPSTREAM, "页面未返回可读取正文")
    content = content[:WEB_FETCH_MAX_CHARS]
    return WebFetchResult(
        url=final_url,
        title=title,
        content=content,
        format=result_format,
        truncated=truncated_by_bytes or len(decoded) > len(content),
    )


def _normalize_domain_list(value: object) -> list[str]:
    """把域名白/黑名单规范为小写 host 列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError(ErrorCode.VALIDATION, "域名列表必须是字符串数组")
    domains: list[str] = []
    for item in value:
        host = str(item or "").strip().lower().lstrip(".")
        if host:
            domains.append(host)
    return domains


def _host_matches(host: str, domains: list[str]) -> bool:
    """精确或后缀匹配域名（含 www 与子域）。"""
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def assert_fetch_domains(url: str, *, allowed: object, blocked: object) -> None:
    """按最终 URL host 强制白/黑名单；空名单表示不额外限制。"""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise AppError(ErrorCode.VALIDATION, "抓取地址缺少有效域名")
    allowed_domains = _normalize_domain_list(allowed)
    blocked_domains = _normalize_domain_list(blocked)
    if allowed_domains and not _host_matches(host, allowed_domains):
        raise AppError(ErrorCode.VALIDATION, "目标域名不在 allowed_domains 白名单")
    if blocked_domains and _host_matches(host, blocked_domains):
        raise AppError(ErrorCode.VALIDATION, "目标域名命中 blocked_domains 黑名单")


def apply_fetch_content_budget(result: WebFetchResult, max_tokens: object) -> WebFetchResult:
    """把 max_content_tokens 映射为字符上限，且不放宽 WEB_FETCH_MAX_CHARS。"""
    if max_tokens is None or max_tokens == "":
        return result
    try:
        tokens = int(max_tokens)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION, "max_content_tokens 必须是整数") from exc
    if tokens <= 0:
        raise AppError(ErrorCode.VALIDATION, "max_content_tokens 必须大于 0")
    max_chars = min(WEB_FETCH_MAX_CHARS, tokens * 4)
    if len(result.content) <= max_chars:
        return result
    return WebFetchResult(
        url=result.url,
        title=result.title,
        content=result.content[:max_chars],
        format=result.format,
        truncated=True,
    )


def web_fetch(
    url: str,
    *,
    format: str = "markdown",
    timeout_s: float,
    on_output: ToolOutputCallback | None = None,
    on_progress: ToolProgressCallback | None = None,
) -> WebFetchResult:
    """抓取单页正文：优先 Firecrawl，未配置时走受控直接抓取，不走 MCP。"""
    if format not in {"markdown", "text"}:
        raise AppError(ErrorCode.VALIDATION, "抓取格式仅支持 markdown 或 text")
    normalized_url = _validate_public_url(url)
    if settings.firecrawl_api_key.strip():
        return _fetch_via_firecrawl(
            normalized_url,
            format,
            timeout_s=timeout_s,
            on_progress=on_progress,
        )
    return _fetch_direct(
        normalized_url,
        format,
        timeout_s=timeout_s,
        on_output=on_output,
        on_progress=on_progress,
    )
