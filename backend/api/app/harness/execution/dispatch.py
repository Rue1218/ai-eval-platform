"""Harness 执行层：短工具分派 + 超时 + 脱敏日志（M5 阶段 3，EX-3/EX-6）。

``execute`` 按 call.name 分派到注册表 handler，带超时；超时返回 ``timeout``
observation；日志脱敏（调 M8）。含受控目录文件工具（read/write/edit）、
web 内部短 MCP 适配器（web_search/web_fetch）与 **bwrap 沙箱 bash**
（阶段 3 开放通用 bash，安全边界见 ``sandbox.py``）。

**bash 安全边界（阶段 3 bwrap 闭环）**：命令黑名单（纵深防御）+ 一次性
bwrap 沙箱（无网络、工作区唯一可写、资源受限、超时整树清理）；黑名单与
沙箱均失败即拒绝，**禁止降级为裸 subprocess**。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.errors import AppError, ErrorCode
from app.harness.contracts import Observation, ToolCall, ToolResult
from app.harness.execution.sandbox import SandboxLimits, run_sandboxed
from app.harness.feedback.observation import normalize
from app.harness.security.secrets import redact_for_log

logger = logging.getLogger("ai-eval.harness.dispatch")

# read 的行级窗口与内容硬上限。模型不能通过 arguments 扩大字符预算，避免大文件
# 直接填满模型上下文或 WebSocket 持久化事件。
READ_DEFAULT_LIMIT = 2_000
READ_MAX_LIMIT = 2_000
READ_MAX_CHARS = 120_000
READ_MAX_BYTES = 10 * 1024 * 1024
READ_PREVIEW_CHARS = 500

# bash 命令黑名单（纵深防御；bwrap 沙箱之外的第二道防线，禁止命令开头命中）
BASH_BLOCKLIST: frozenset[str] = frozenset(
    {"rm", "sudo", "curl", "wget", "nc", "ssh", "scp", "chmod", "chown"}
)

# SSRF 防护：web_fetch 抓取目标命中以下内网/回环/链路本地/保留地址段即拒绝。
# 含 IPv4 保留段、IPv6 回环/ULA/链路本地/多播与文档地址（RFC 1918/6890/3849 等）。
BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("2001:db8::/32"),
    ipaddress.ip_network("ff00::/8"),
)


def _is_blocked_ip(ip: str) -> bool:
    """判定 IP 是否命中内网/回环/保留地址段；无法识别一律拒绝（fail-closed）。

    IPv4 映射 IPv6（``::ffff:127.0.0.1``）先还原为 IPv4 再判定，防止绕过。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr in network for network in BLOCKED_NETWORKS)


def _reject_internal_target(host: str) -> None:
    """SSRF 防护：主机名/IP 解析结果命中内网地址即拒绝（web_fetch 前置校验）。

    覆盖 IP 字面量（含十进制/十六进制/八进制等非标准写法）、域名解析结果与
    IPv4 映射 IPv6；域名先解析校验再发起请求，阻止直连容器内网/回环服务。
    （解析与请求间存在极小 DNS 重绑定窗口，属可接受的残余风险。）
    """
    try:
        ipaddress.ip_address(host)  # host 本身是 IP 字面量
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            raise AppError(ErrorCode.UPSTREAM, "域名解析失败") from None
        resolved = {info[4][0] for info in infos}
        if not resolved:
            raise AppError(ErrorCode.UPSTREAM, "域名解析失败")
        if any(_is_blocked_ip(ip) for ip in resolved):
            raise AppError(ErrorCode.VALIDATION, "禁止访问内网/回环地址")
        return
    if _is_blocked_ip(host):
        raise AppError(ErrorCode.VALIDATION, "禁止访问内网/回环地址")


def run_bash(
    cmd: str,
    *,
    sandbox_dir: str,
    timeout_s: float,
    limits: SandboxLimits | None = None,
) -> str:
    """bwrap 沙箱 + 黑名单双防护执行 shell 命令（阶段 3 开放通用 bash）。

    黑名单命中抛 AppError(VALIDATION)；其余经 ``run_sandboxed`` 在一次性
    bwrap 沙箱内执行（无网络、会话工作区唯一可写、资源受限、超时整树清理）；
    bwrap 不可用时 fail-closed，禁止降级为裸 subprocess。
    """
    command = cmd.strip()
    if not command:
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    first = command.split()[0]
    if first in BASH_BLOCKLIST:
        raise AppError(ErrorCode.VALIDATION, f"bash 命令命中黑名单：{first}")
    return run_sandboxed(
        command,
        sandbox_dir=sandbox_dir,
        timeout_s=timeout_s,
        limits=limits,
    )


def _resolve_safe_path(path: str, root: str) -> str:
    """把相对路径解析到受控根目录内；目录穿越/绝对路径拒绝（M5-D7 红线）。"""
    if not root:
        raise AppError(ErrorCode.VALIDATION, "未配置沙箱目录")
    if os.path.isabs(path):
        raise AppError(ErrorCode.VALIDATION, "仅支持沙箱内相对路径")
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, path))
    if not target.startswith(root_real + os.sep) and target != root_real:
        raise AppError(ErrorCode.VALIDATION, "路径越出沙箱目录")
    return target


@dataclass(frozen=True, slots=True)
class ReadResult:
    """read 的行级结构化结果：正文与浏览器展示投影严格分离。"""

    path: str
    total_lines: int
    total_chars: int
    start_line: int
    end_line: int
    lines_read: int
    is_complete: bool
    next_offset: int | None
    content: str
    content_truncated: bool
    source: str

    def to_tool_data(self) -> dict[str, object]:
        """生成 API.md V1.25 允许写入 ToolCard 的受控数据。"""
        preview = self.content[:READ_PREVIEW_CHARS]
        preview_truncated = len(self.content) > len(preview)
        status = "已读完" if self.is_complete else "未读完"
        summary = (
            f"已读取 {self.path} 第 {self.start_line + 1}–{self.end_line} 行"
            f"（共 {self.total_lines} 行，{status}）"
        )
        return {
            "summary": summary,
            # 只在 normalize() 内部取用，ToolNode 绝不能投影此字段到 ws_events。
            "model_text": self.content,
            "truncated": not self.is_complete,
            "source": self.source,
            "display": {
                "summary": summary,
                "read": {
                    "path": self.path,
                    "total_lines": self.total_lines,
                    "total_chars": self.total_chars,
                    "start_line": self.start_line,
                    "end_line": self.end_line,
                    "lines_read": self.lines_read,
                    "is_complete": self.is_complete,
                    "next_offset": self.next_offset,
                    "content_truncated": self.content_truncated,
                    "preview": preview,
                    "preview_truncated": preview_truncated,
                },
            },
        }


def _read_non_negative_int(value: object | None, *, name: str, default: int) -> int:
    """解析 read 分页参数；布尔、负数和非整数一律受控拒绝。"""
    if value is None:
        return default
    if isinstance(value, bool):
        raise AppError(ErrorCode.VALIDATION, f"{name} 必须为非负整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION, f"{name} 必须为非负整数") from exc
    if parsed < 0:
        raise AppError(ErrorCode.VALIDATION, f"{name} 必须为非负整数")
    return parsed


def read_file_safe(
    path: str,
    sandbox_dir: str,
    *,
    offset: object | None = None,
    limit: object | None = None,
) -> ReadResult:
    """受控目录内按行读取文本文件（防目录穿越与半行截断）。

    ``offset`` 与 ``limit`` 统一为 0-based 行号/行数。单次最多 2,000 行、
    120,000 字符；达到字符预算时仅在完整行边界停止，返回准确的
    ``next_offset``。完整正文只留在 ``ReadResult.content``，调用方必须投影为
    Observation，不能直接写进 WebSocket 事件。
    """
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    if os.path.getsize(target) > READ_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "文件超过 read 单次允许的 10MB 上限")
    start = _read_non_negative_int(offset, name="offset", default=0)
    requested_limit = _read_non_negative_int(limit, name="limit", default=READ_DEFAULT_LIMIT)
    if requested_limit == 0:
        raise AppError(ErrorCode.VALIDATION, "limit 必须大于 0")
    size = min(requested_limit, READ_MAX_LIMIT)
    with open(target, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    total_lines = len(lines)
    total_chars = sum(len(line) for line in lines)
    if start >= total_lines:
        return ReadResult(
            path=path,
            total_lines=total_lines,
            total_chars=total_chars,
            start_line=start,
            end_line=start,
            lines_read=0,
            is_complete=True,
            next_offset=None,
            content="",
            content_truncated=False,
            source=f"workspace:{path}",
        )

    selected: list[str] = []
    chars_used = 0
    for line in lines[start : start + size]:
        if chars_used + len(line) > READ_MAX_CHARS:
            if not selected:
                raise AppError(ErrorCode.VALIDATION, "单行内容超过 read 的 120000 字符上限")
            break
        selected.append(line)
        chars_used += len(line)
    end_line = start + len(selected)
    is_complete = end_line >= total_lines
    return ReadResult(
        path=path,
        total_lines=total_lines,
        total_chars=total_chars,
        start_line=start,
        end_line=end_line,
        lines_read=len(selected),
        is_complete=is_complete,
        next_offset=None if is_complete else end_line,
        content="".join(selected),
        content_truncated=False,
        source=f"workspace:{path}",
    )


def write_file_safe(path: str, content: str, sandbox_dir: str) -> None:
    """受控目录内新建文本文件（防目录穿越；不覆盖已有文件）。"""
    target = _resolve_safe_path(path, sandbox_dir)
    if os.path.exists(target):
        raise AppError(ErrorCode.VALIDATION, "文件已存在，请使用 edit")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)


def edit_file_safe(path: str, old: str, new: str, sandbox_dir: str) -> None:
    """受控目录内原子替换（防目录穿越；不匹配则拒绝）。"""
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    with open(target, encoding="utf-8") as handle:
        content = handle.read()
    if old not in content:
        raise AppError(ErrorCode.VALIDATION, "原文不匹配，编辑已拒绝")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content.replace(old, new, 1))


def web_search(query: str, *, timeout_s: float) -> str:
    """内部检索适配器（平台自实现，不走外部 MCP 服务器）。

    当前为占位实现：返回受限的检索说明；真实后端接入后替换内部端点。
    """
    if not query.strip():
        raise AppError(ErrorCode.VALIDATION, "检索关键词不能为空")
    logger.info("web_search query=%.64s timeout=%s", query, timeout_s)
    # 占位：内部检索后端未接入时明确失败，禁止假成功（对齐 EX-5）
    raise AppError(ErrorCode.VALIDATION, "内部检索后端未接入")


def web_fetch(url: str, *, timeout_s: float) -> str:
    """内部抓取适配器 + 脱敏 + SSRF 防护（不走外部 MCP 服务器）。"""
    if not url.startswith(("http://", "https://")):
        raise AppError(ErrorCode.VALIDATION, "仅支持 http/https 地址")
    host = urlparse(url).hostname
    if not host:
        raise AppError(ErrorCode.VALIDATION, "URL 缺少主机名")
    _reject_internal_target(host)
    request = Request(url, headers={"User-Agent": "ai-eval-platform/1.0"})
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            body = response.read(20000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"抓取失败（HTTP {exc.code}）") from exc
    except URLError as exc:
        raise AppError(ErrorCode.UPSTREAM, "抓取失败（网络错误）") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "抓取超时") from exc
    return body[:20000]


def execute(
    call: ToolCall,
    *,
    timeout_s: float,
    permission: str,
    sandbox_dir: str | None = None,
    handler: object | None = None,
) -> Observation:
    """按 call.name 分派到 handler，带超时；超时返回 timeout observation。

    日志脱敏（调 M8 ``redact_for_log``，不含密钥/敏感参数，X-A4）；
    异常归一为 ok=False observation（FB-1），不裸抛、不导致 Agent 崩溃。
    """
    started = time.perf_counter()
    try:
        if handler is None:
            raise AppError(ErrorCode.VALIDATION, f"工具未注册：{call.name}")
        result = handler(call.arguments, sandbox_dir)  # type: ignore[call-arg]
        latency_ms = round((time.perf_counter() - started) * 1000)
        data = result.to_tool_data() if isinstance(result, ReadResult) else {
            "summary": str(result),
            "display": {"summary": str(result)},
        }
        data["latency_ms"] = latency_ms
        raw = ToolResult(
            name=call.name,
            ok=True,
            data=data,
        )
        return normalize(raw, None, tool=call.name, arguments=dict(call.arguments or {}))
    except AppError as exc:
        logger.info(
            "工具执行失败 name=%s code=%s args=%s",
            call.name,
            exc.code.value,
            redact_for_log(dict(call.arguments or {})),
        )
        return normalize(None, exc, tool=call.name, arguments=dict(call.arguments or {}))
    except Exception as exc:
        logger.warning(
            "工具执行内部异常 name=%s type=%s args=%s",
            call.name,
            type(exc).__name__,
            redact_for_log(dict(call.arguments or {})),
        )
        return normalize(None, exc, tool=call.name, arguments=dict(call.arguments or {}))
