"""Harness 执行层 web 工具（web_search / web_fetch）单测；不依赖 DB。

自 ``test_harness_execution.py`` 拆出：搜索适配器、SSRF 防护、正文预算、
trafilatura 降级链与回环集成对照。工具辅助（``_ARTICLE_HTML``、
``_install_fake_html_fetch``、``_RecordingHandler``、``loopback_server``）
随测试就近维护，不跨文件共享。
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import app.harness.execution.dispatch_common as dispatch_common
import app.harness.execution.dispatch_web as dispatch_web
import app.harness.execution.toolnode as toolnode_mod
from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall
from app.harness.execution import build_default_registry, build_tool_node, execute
from app.harness.memory import GraphState


def test_web_search_requires_server_side_service_configuration(monkeypatch) -> None:
    """未配置 Firecrawl Key 时明确拒绝，禁止用占位文本伪造搜索成功。"""
    from app.config import settings
    from app.harness.execution import dispatch

    monkeypatch.setattr(settings, "firecrawl_api_key", "")
    with pytest.raises(AppError) as error:
        dispatch.web_search("ReAct 原理", timeout_s=1.0)
    assert error.value.code == ErrorCode.VALIDATION


def test_web_search_projects_safe_structured_results(monkeypatch) -> None:
    """真实搜索适配器只把受控结果交给模型与 ToolCard，不泄露服务端密钥。"""
    from app.config import settings
    from app.harness.execution import dispatch

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return b'{"data":[{"title":"LangGraph","url":"https://example.com/a","description":"agent graph"}]}'

    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **_kwargs: object) -> _FakeResponse:
        captured["request"] = request
        return _FakeResponse()

    monkeypatch.setattr(settings, "firecrawl_api_key", "private-key")
    monkeypatch.setattr(dispatch_web, "urlopen", fake_urlopen)
    result = dispatch.web_search("LangGraph", limit=1, timeout_s=1.0)
    data = result.to_tool_data()
    assert result.results[0]["title"] == "LangGraph"
    assert data["display"]["search"]["results"][0]["url"] == "https://example.com/a"
    assert "private-key" not in json.dumps(data, ensure_ascii=False)
    assert captured["request"] is not None


def test_web_fetch_rejects_internal_targets(monkeypatch) -> None:
    """SSRF 防护：web_fetch 拒绝回环/内网/保留地址（IP 字面量、域名与非标准写法）。

    ``urlopen`` 被替换为必然失败的桩：若 SSRF 校验漏拦任一 URL，urlopen 被调用
    即触发 AssertionError，保证校验确实在发起请求前生效。
    """
    from app.harness.execution import dispatch

    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("SSRF 校验未拦截，urlopen 不应被调用")

    monkeypatch.setattr(dispatch_web, "urlopen", fake_urlopen)
    blocked_urls = (
        "http://127.0.0.1:8000/api/health",
        "http://localhost:8000/api/health",
        "http://[::1]:8000/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://172.31.255.254/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        # 非标准 IP 写法（十进制/十六进制/省略段），解析后仍命中回环
        "http://2130706433/",
        "http://0x7f000001/",
        "http://127.1/",
        # IPv4 映射 IPv6
        "http://[::ffff:127.0.0.1]:8000/",
    )
    for url in blocked_urls:
        with pytest.raises(AppError) as error:
            dispatch.web_fetch(url, timeout_s=1.0)
        assert error.value.code in (ErrorCode.VALIDATION, ErrorCode.UPSTREAM), url


def test_web_fetch_allows_public_target(monkeypatch) -> None:
    """SSRF 防护不误伤公网地址。"""
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/html"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return self._body

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/"

    class _FakeOpener:
        def open(self, _request: object, timeout: float) -> _FakeResponse:
            assert timeout == 1.0
            return _FakeResponse(b"<html>public</html>")

    monkeypatch.setattr(dispatch_web, "build_opener", lambda *_a, **_k: _FakeOpener())
    # 公网 IP 字面量：无需 DNS，直接放行
    assert "public" in dispatch.web_fetch("http://93.184.216.34/", timeout_s=1.0).content
    # 与 HTTP 一样固定 DNS 响应，避免本机代理/离线解析改变本例的公网前提。
    monkeypatch.setattr(dispatch_common.socket, "getaddrinfo", lambda *_a, **_k: [
        (dispatch_common.socket.AF_INET, dispatch_common.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
    ])
    result = dispatch.web_fetch("http://example.com/", timeout_s=1.0)
    assert "public" in result.content


def test_web_fetch_content_budget_and_card_preview(monkeypatch) -> None:
    """web_fetch 正文预算与卡片预览（2026-08-28 调整）：

    - 旧 8000 字符正文上限把知乎专栏等长文截掉大半，放宽为专属
      ``WEB_FETCH_MAX_CHARS`` 预算，超限仍带 ``truncated`` 诚实标记；
    - 卡片预览不再固定 500 字符，与 read 同源对齐 ``preview_char_limit()``，
      并下发 ``preview_limit_chars`` 供前端提示文案使用。
    """
    from app.config import settings
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/plain"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return self._body

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/long"

    class _FakeOpener:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def open(self, _request: object, timeout: float) -> _FakeResponse:
            _ = timeout
            return _FakeResponse(self._body)

    # 1) 介于旧 8000 与新 60000 预算之间的长文不再被截半
    monkeypatch.setattr(
        dispatch_web, "build_opener", lambda *_a, **_k: _FakeOpener(b"x" * 20_000)
    )
    mid = dispatch.web_fetch("http://93.184.216.34/long", format="text", timeout_s=1.0)
    assert len(mid.content) == 20_000
    assert mid.truncated is False

    # 2) 超出 60000 预算仍受控截断，并带诚实标记
    monkeypatch.setattr(
        dispatch_web, "build_opener", lambda *_a, **_k: _FakeOpener(b"y" * 61_000)
    )
    over = dispatch.web_fetch("http://93.184.216.34/long", format="text", timeout_s=1.0)
    assert len(over.content) == dispatch_web.WEB_FETCH_MAX_CHARS
    assert over.truncated is True

    # 3) 卡片预览与 preview_char_limit() 同源，上限随数据下发
    monkeypatch.setattr(settings, "tool_preview_max_chars", 100)
    data = over.to_tool_data()
    web = data["display"]["web"]
    assert isinstance(web, dict)
    assert web["preview_limit_chars"] == 100
    assert web["preview_truncated"] is True
    assert len(str(web["preview"])) <= 100


def test_web_fetch_streams_direct_plain_text_before_completion(monkeypatch) -> None:
    """直接抓取纯文本时，已接收片段应在 HTTP 响应结束前通过安全回调发出。"""
    from app.harness.execution import dispatch

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/plain"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self._offset = 0

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(self._body):
                return b""
            stop = len(self._body) if size < 0 else min(len(self._body), self._offset + size)
            chunk = self._body[self._offset:stop]
            self._offset = stop
            return chunk

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/stream.txt"

    class _FakeOpener:
        def open(self, _request: object, timeout: float) -> _FakeResponse:
            assert timeout == 1.0
            return _FakeResponse(("第一行\n第二行\n" * 1_000).encode("utf-8"))

    monkeypatch.setattr(dispatch_web, "build_opener", lambda *_a, **_k: _FakeOpener())
    chunks: list[tuple[str, str, int | None]] = []
    stages: list[tuple[str, str]] = []
    result = dispatch.web_fetch(
        "http://93.184.216.34/stream.txt",
        format="text",
        timeout_s=1.0,
        on_output=lambda channel, text, start_line: chunks.append((channel, text, start_line)),
        on_progress=lambda stage, message: stages.append((stage, message)),
    )

    assert result.content.startswith("第一行")
    assert len(chunks) >= 2
    assert all(channel == "document" and start_line is None for channel, _text, start_line in chunks)
    assert "".join(text for _channel, text, _start_line in chunks) == result.content
    assert [stage for stage, _message in stages] == ["downloading", "extracting"]


_ARTICLE_HTML = """<!DOCTYPE html>
<html><head><title>Agent设计模式详解 - 技术专栏</title></head>
<body>
<nav><a href="/home">首页</a><a href="/tags">标签</a></nav>
<article>
<h1>Agent设计模式详解</h1>
<p>Agent设计模式是智能化系统开发的核心要点。本系列文章将详细介绍九种常见的Agent设计模式，
帮助开发者掌握每种模式的原理和具体应用场景，先从最基础的ReAct模式开始讲起，
它是所有模式的理论基石，也是工程实践中使用频率最高的一种范式。</p>
<h2>1、ReAct 模式</h2>
<p>ReAct 模式的核心思想是<a href="https://example.com/react-paper">推理与行动交错进行</a>，
模型在思考之后立即执行工具调用，并根据观察结果调整下一步计划。
这种循环结构既保证了推理的深度，又保证了行动的准确性。</p>
<img src="https://picx.zhimg.com/v2-853507087d2befc30a742018816a7d5f_1440w.jpg" alt="ReAct架构图"/>
<h2>2、Plan-and-Solve 模式</h2>
<p>Plan-and-Solve 模式强调先制定完整计划再逐步执行。规划阶段模型会把目标拆解为有序的子步骤，
执行阶段按顺序完成每个子步骤并根据反馈动态修正，适合流程固定的批量评测任务。</p>
</article>
<footer>版权声明：本文为原创文章，转载请保留出处与作者信息。</footer>
</body></html>"""


def _install_fake_html_fetch(monkeypatch, body: bytes) -> None:
    """给 web_fetch 直抓路径装上返回固定 HTML 的假 opener（测试辅助）。"""

    class _FakeHeaders:
        def get_content_type(self) -> str:
            return "text/html"

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _n: int = -1) -> bytes:
            return body

        @property
        def headers(self) -> _FakeHeaders:
            return _FakeHeaders()

        def geturl(self) -> str:
            return "http://93.184.216.34/article"

    class _FakeOpener:
        def open(self, _request: object, timeout: float) -> _FakeResponse:
            _ = timeout
            return _FakeResponse()

    monkeypatch.setattr(dispatch_web, "build_opener", lambda *_a, **_k: _FakeOpener())


def test_web_fetch_trafilatura_markdown_extraction(monkeypatch) -> None:
    """直抓路径接入 trafilatura（2026-08-28）：正文级 Markdown 提取且格式诚实声明。"""
    from types import SimpleNamespace

    from app.harness.execution import dispatch

    captured: dict[str, object] = {}

    def _fake_extract(decoded: str, **kwargs: object) -> str:
        captured["kwargs"] = kwargs
        assert "<article>" in decoded
        return "# Agent设计模式详解\n\n正文含 [ReAct 模式](https://example.com/react-paper)。"

    monkeypatch.setattr(
        dispatch_web, "_load_trafilatura", lambda: SimpleNamespace(extract=_fake_extract)
    )
    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "markdown"
    assert "[ReAct 模式](https://example.com/react-paper)" in result.content
    # <title> 仍由内置提取器提供
    assert "Agent设计模式详解" in result.title
    kwargs = captured["kwargs"]
    assert kwargs.get("include_links") is True
    assert kwargs.get("favor_recall") is True


def test_web_fetch_falls_back_without_trafilatura(monkeypatch) -> None:
    """未安装 trafilatura 时降级回 _TextExtractor，格式诚实保持 text。"""
    from app.harness.execution import dispatch

    monkeypatch.setattr(dispatch_web, "_load_trafilatura", lambda: None)
    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "text"
    assert "Agent设计模式" in result.content
    assert "Agent设计模式详解" in result.title


def test_web_fetch_falls_back_when_trafilatura_raises(monkeypatch) -> None:
    """trafilatura 提取抛异常时不中断抓取，降级为内置提取器。"""
    from types import SimpleNamespace

    from app.harness.execution import dispatch

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(
        dispatch_web, "_load_trafilatura", lambda: SimpleNamespace(extract=_boom)
    )
    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "text"
    assert "Agent设计模式" in result.content


def test_web_fetch_real_trafilatura_integration(monkeypatch) -> None:
    """集成：真实 trafilatura 对文章式 HTML 输出结构化 Markdown。"""
    pytest.importorskip("trafilatura")
    from app.harness.execution import dispatch

    _install_fake_html_fetch(monkeypatch, _ARTICLE_HTML.encode("utf-8"))
    result = dispatch.web_fetch("http://93.184.216.34/article", format="markdown", timeout_s=1.0)
    assert result.format == "markdown"
    assert "# Agent设计模式详解" in result.content
    assert "](https://example.com/react-paper)" in result.content
    assert "![" in result.content
    # 导航/页脚噪声被剔除
    assert "首页" not in result.content
    assert "版权声明" not in result.content


class _RecordingHandler(BaseHTTPRequestHandler):
    """回环集成测试用 HTTP handler：记录请求路径、返回固定内容、不刷日志。"""

    requests: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).requests.append(self.path)
        body = b"integration-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture()
def loopback_server() -> str:
    """启动一个真实可达的回环 HTTP 服务器（127.0.0.1 随机端口），返回其 URL。

    用作集成测试的"内部可达目标"：若 SSRF 校验缺失，web_fetch 必然能抓到它。
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _RecordingHandler.requests = []
    yield f"http://127.0.0.1:{server.server_address[1]}/health"
    server.shutdown()
    thread.join(timeout=5)


def test_web_fetch_integration_blocks_reachable_loopback(loopback_server) -> None:
    """集成：SSRF 校验先于网络请求——回环服务真实可达也拦截，且服务端未收到请求。"""
    from app.harness.execution import dispatch

    with pytest.raises(AppError) as error:
        dispatch.web_fetch(loopback_server, timeout_s=3.0)
    assert error.value.code == ErrorCode.VALIDATION
    assert _RecordingHandler.requests == []


def test_web_fetch_integration_execute_path_observation(loopback_server) -> None:
    """集成：经 execute 分派路径，SSRF 拦截归一为 ok=False observation。"""
    registry = build_default_registry()
    observation = execute(
        ToolCall(name="web_fetch", arguments={"url": loopback_server}),
        timeout_s=5.0,
        permission=registry.get("web_fetch").permission,
        handler=registry.get("web_fetch").handler,
    )
    assert observation.ok is False
    assert observation.text == "操作失败（VALIDATION）"
    assert _RecordingHandler.requests == []


def test_web_fetch_integration_toolnode_event(loopback_server) -> None:
    """集成：经 ToolNode 全链路（门禁→绑定→分派→归一），产出 ok=False tool_result 事件。"""
    registry = build_default_registry()
    node = build_tool_node(registry)
    state: GraphState = {
        "request": {"config": {}, "messages": ()},
        "pending_tool": {"name": "web_fetch", "arguments": {"url": loopback_server}},
    }

    class _FakeConfig:
        def get(self, key: str, default: object = None) -> object:
            return {"configurable": {}}.get(key, default)

    original = toolnode_mod.get_config
    toolnode_mod.get_config = lambda: _FakeConfig()
    try:
        out = asyncio.run(node(state))
    finally:
        toolnode_mod.get_config = original

    result = next(event for event in out["pending_events"] if event["kind"] == "tool_result")
    payload = result["payload"]
    assert payload["ok"] is False
    assert payload["error"] == "操作失败（VALIDATION）"
    assert payload["latency_ms"] >= 0
    assert _RecordingHandler.requests == []


def test_web_fetch_integration_reachable_when_guard_disabled(loopback_server, monkeypatch) -> None:
    """集成对照：绕过 SSRF 校验后同一回环服务可正常抓取，证明拦截来自校验本身而非环境。"""
    from app.harness.execution import dispatch

    monkeypatch.setattr(dispatch_web, "_reject_internal_target", lambda _host: None)
    result = dispatch.web_fetch(loopback_server, timeout_s=3.0)
    assert "integration-ok" in result.content
    assert _RecordingHandler.requests == ["/health"]
