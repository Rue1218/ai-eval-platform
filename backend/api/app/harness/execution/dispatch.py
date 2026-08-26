"""Harness 执行层：短工具分派 + 超时 + 脱敏日志（M5 阶段 3，EX-3/EX-6）。

``execute`` 按 call.name 分派到注册表 handler，带超时；超时返回 ``timeout``
observation；日志脱敏（调 M8）。含受控目录文件工具（read/write/edit）、
原生网络适配器（web_search/web_fetch）与 **bwrap 沙箱 bash**
（阶段 3 开放通用 bash，安全边界见 ``sandbox.py``）。

**bash 安全边界（阶段 3 bwrap 闭环）**：命令黑名单（纵深防御）+ 一次性
bwrap 沙箱（无网络、工作区唯一可写、资源受限、超时整树清理）；黑名单与
沙箱均失败即拒绝，**禁止降级为裸 subprocess**。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS
from app.harness.contracts import Observation, ToolCall, ToolResult
from app.harness.execution.sandbox import SandboxLimits, run_sandboxed
from app.harness.feedback.observation import normalize
from app.harness.security.secrets import redact_for_log

from .policy import DEFAULT_RECOVERY_POLICY, ToolRecoveryPolicy

logger = logging.getLogger("ai-eval.harness.dispatch")

# read 的行级窗口与内容硬上限。模型不能通过 arguments 扩大字符预算，避免大文件
# 直接填满模型上下文或 WebSocket 持久化事件。
READ_DEFAULT_LIMIT = 2_000
READ_MAX_LIMIT = 2_000
READ_MAX_CHARS = MODEL_TOOL_RESULT_MAX_CHARS
# 预留未读完提示，避免 model_text + 前缀再被截断半行。
READ_UNREAD_HINT_RESERVE = 180
READ_CONTENT_BUDGET = max(1, READ_MAX_CHARS - READ_UNREAD_HINT_RESERVE)
READ_MAX_BYTES = 10 * 1024 * 1024
READ_PREVIEW_CHARS = 4_000
# 剩余正文按块统计行数/字符，避免对未返回内容逐行建 Python 字符串导致超时。
READ_SCAN_CHUNK = 256 * 1024
WRITE_MAX_BYTES = 2 * 1024 * 1024
WEB_MAX_CONTENT_CHARS = MODEL_TOOL_RESULT_MAX_CHARS
WEB_PREVIEW_CHARS = 500
WEB_MAX_SEARCH_RESULTS = 10
WEB_RESPONSE_MAX_BYTES = 256 * 1024

# handler 可在受控输出生成时调用回调；回调由 ToolNode 注入，未运行在图内时为 None。
ToolOutputCallback = Callable[[str, str, int | None], None]

# bash 命令黑名单（纵深防御；bwrap 沙箱之外的第二道防线，禁止命令开头命中）
BASH_BLOCKLIST: frozenset[str] = frozenset(
    {"rm", "sudo", "curl", "wget", "nc", "ssh", "scp", "chmod", "chown"}
)
_BASH_COMMAND_SEPARATOR = re.compile(r"(?:&&|\|\||[;|&\n])")

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
    on_output: ToolOutputCallback | None = None,
) -> str:
    """bwrap 沙箱 + 黑名单双防护执行 shell 命令（阶段 3 开放通用 bash）。

    黑名单命中抛 AppError(VALIDATION)；其余经 ``run_sandboxed`` 在一次性
    bwrap 沙箱内执行（无网络、会话工作区唯一可写、资源受限、超时整树清理）；
    bwrap 不可用时 fail-closed，禁止降级为裸 subprocess。
    """
    command = cmd.strip()
    if not command:
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    # 不只检查整条命令首词，避免 ``echo ok; rm ...`` 绕过纵深防御；bwrap 仍是
    # 最终隔离边界，黑名单不能替代沙箱。
    for segment in _BASH_COMMAND_SEPARATOR.split(command):
        first = segment.strip().split(maxsplit=1)[0] if segment.strip() else ""
        if first in BASH_BLOCKLIST:
            raise AppError(ErrorCode.VALIDATION, f"bash 命令命中黑名单：{first}")
    return run_sandboxed(
        command,
        sandbox_dir=sandbox_dir,
        timeout_s=timeout_s,
        limits=limits,
        on_output=(
            (lambda chunk: on_output("stdout", chunk, None))
            if on_output is not None
            else None
        ),
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
        """生成 API.md 允许写入 ToolCard 的受控数据。"""
        preview, preview_truncated = clip_at_line_boundary(self.content, READ_PREVIEW_CHARS)
        status = "已读完" if self.is_complete else "未读完"
        summary = (
            f"已读取 {self.path} 第 {self.start_line + 1}–{self.end_line} 行"
            f"（共 {self.total_lines} 行，{status}）"
        )
        model_text = self.content
        if not self.is_complete and self.next_offset is not None:
            model_text = (
                f"{self.content.rstrip()}\n"
                f"…[未读完] 下一页请传 offset={self.next_offset}"
                f"（参数名是 offset，不要重复本次 offset={self.start_line}）。"
            )
        if len(model_text) > READ_MAX_CHARS:
            model_text, _ = clip_at_line_boundary(model_text, READ_MAX_CHARS)
        return {
            "summary": summary,
            # 只在 normalize() 内部取用，ToolNode 绝不能投影此字段到 ws_events。
            "model_text": model_text,
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


def resolve_read_offset(arguments: Mapping[str, object] | None) -> object | None:
    """取 read 起始行：优先 ``offset``，否则接受模型回填的 ``next_offset``。"""
    raw = arguments or {}
    offset = raw.get("offset")
    return raw.get("next_offset") if offset is None else offset


def clip_at_line_boundary(text: str, max_chars: int) -> tuple[str, bool]:
    """按字符预算截取，只保留完整行；单行超长才截断该行。"""
    if max_chars <= 0:
        return "", True
    if len(text) <= max_chars:
        return text, False
    window = text[:max_chars]
    last_nl = window.rfind("\n")
    if last_nl >= 0:
        return window[: last_nl + 1], True
    return window, True


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


def _count_remaining_text(handle: object, prefix: str = "") -> tuple[int, int]:
    """按块统计窗口之后的行数与字符数，不保留剩余全文、不逐行建对象。

    与文本模式 ``readline`` 同一套通用换行语义；``prefix`` 用于字符预算触发时
    把未选中的当前行计入总量。
    """
    extra_lines = 0
    extra_chars = 0
    ends_with_newline = True
    if prefix:
        extra_chars += len(prefix)
        extra_lines += prefix.count("\n")
        ends_with_newline = prefix.endswith("\n")
    read = getattr(handle, "read")
    while True:
        chunk = read(READ_SCAN_CHUNK)
        if not chunk:
            break
        extra_chars += len(chunk)
        extra_lines += chunk.count("\n")
        ends_with_newline = chunk.endswith("\n")
    if extra_chars and not ends_with_newline:
        extra_lines += 1
    return extra_lines, extra_chars


def read_file_safe(
    path: str,
    sandbox_dir: str,
    *,
    offset: object | None = None,
    limit: object | None = None,
    on_output: ToolOutputCallback | None = None,
) -> ReadResult:
    """受控目录内按行读取文本文件（防目录穿越与半行截断）。

    ``offset`` 与 ``limit`` 统一为 0-based 行号/行数。单次最多 2,000 行、
    8,000 字符（与模型可见上限对齐）；达到字符预算时仅在完整行边界停止，
    返回准确的 ``next_offset``。窗口收齐后不再对剩余正文逐行迭代，只按块累计
    ``total_lines`` / ``total_chars``，避免大文档在工具超时内扫不完。
    完整正文只留在 ``ReadResult.content``，调用方必须投影为 Observation，
    不能直接写进 WebSocket 事件。
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
    selected: list[str] = []
    chars_used = 0
    preview_chars = 0
    stream_lines: list[str] = []
    stream_start: int | None = None

    def flush_stream() -> None:
        """按完整行输出当前浏览器安全预览块，绝不超出 4000 字符。"""
        nonlocal stream_lines, stream_start
        if on_output is not None and stream_lines and stream_start is not None:
            on_output("document", "".join(stream_lines), stream_start)
        stream_lines = []
        stream_start = None
    total_lines = 0
    total_chars = 0
    hit_character_limit = False
    overflow_line = ""
    extra_lines = 0
    with open(target, encoding="utf-8", errors="replace") as handle:
        skipped = 0
        while skipped < start:
            line = handle.readline()
            if not line:
                break
            total_lines += 1
            total_chars += len(line)
            skipped += 1
        if skipped < start:
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
        while len(selected) < size:
            line = handle.readline()
            if not line:
                break
            if chars_used + len(line) > READ_CONTENT_BUDGET:
                if not selected:
                    raise AppError(
                        ErrorCode.VALIDATION,
                        f"单行内容超过 read 的 {READ_MAX_CHARS} 字符上限",
                    )
                hit_character_limit = True
                overflow_line = line
                break
            selected.append(line)
            chars_used += len(line)
            total_lines += 1
            total_chars += len(line)
            # read 的实时输出与最终 ToolCard 同一安全边界：最多 4000 字符、完整行。
            if on_output is not None and preview_chars + len(line) <= READ_PREVIEW_CHARS:
                if stream_start is None:
                    stream_start = start + len(selected)
                stream_lines.append(line)
                preview_chars += len(line)
                if len("".join(stream_lines)) >= 700:
                    flush_stream()
        flush_stream()
        extra_lines, extra_chars = _count_remaining_text(handle, overflow_line)
        total_lines += extra_lines
        total_chars += extra_chars
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
    end_line = start + len(selected)
    is_complete = extra_lines == 0 and not hit_character_limit
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
        content_truncated=hit_character_limit,
        source=f"workspace:{path}",
    )


@dataclass(frozen=True, slots=True)
class WriteResult:
    """write 的结构化成功结果，避免把写入正文回显给模型或浏览器。"""

    path: str
    bytes_written: int
    lines_written: int
    preview: str
    preview_truncated: bool

    def to_tool_data(self) -> dict[str, object]:
        """生成模型摘要与 ToolCard 安全展示投影。"""
        summary = f"已新建 {self.path}（{self.lines_written} 行，{self.bytes_written} 字节）"
        return {
            "summary": summary,
            "display": {
                "summary": summary,
                "write": {
                    "path": self.path,
                    "bytes_written": self.bytes_written,
                    "lines_written": self.lines_written,
                    "preview": self.preview,
                    "preview_truncated": self.preview_truncated,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class EditResult:
    """edit 的结构化成功结果，记录一次精确原子替换。"""

    path: str
    old_length: int
    new_length: int

    def to_tool_data(self) -> dict[str, object]:
        """生成模型摘要与 ToolCard 安全展示投影。"""
        summary = f"已编辑 {self.path}（替换 {self.old_length}→{self.new_length} 字符）"
        return {
            "summary": summary,
            "display": {
                "summary": summary,
                "edit": {
                    "path": self.path,
                    "replacements": 1,
                    "old_length": self.old_length,
                    "new_length": self.new_length,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class BashResult:
    """bash 的结构化安全投影，正文按行号显示且不持久化完整输出。"""

    output: str

    def to_tool_data(self) -> dict[str, object]:
        """把沙箱输出限制为 ToolCard 可见预览，完整片段仅供当前模型回合。"""
        preview, preview_truncated = clip_at_line_boundary(self.output, READ_PREVIEW_CHARS)
        summary = "沙箱命令执行完成"
        return {
            "summary": summary,
            "model_text": self.output[:MODEL_TOOL_RESULT_MAX_CHARS],
            "truncated": len(self.output) > MODEL_TOOL_RESULT_MAX_CHARS,
            "source": "sandbox:bash",
            "display": {
                "summary": summary,
                "bash": {
                    "exit_code": 0,
                    "preview": preview,
                    "preview_truncated": preview_truncated,
                },
            },
        }


def _ensure_write_size(content: str) -> int:
    """限制单次写入大小，避免模型一次工具调用耗尽会话工作区。"""
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > WRITE_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "写入内容超过单次允许的 2MB 上限")
    return content_bytes


def write_file_safe(path: str, content: str, sandbox_dir: str) -> WriteResult:
    """受控目录内原子新建文本文件（防目录穿越与覆盖竞争）。"""
    target = _resolve_safe_path(path, sandbox_dir)
    bytes_written = _ensure_write_size(content)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise AppError(ErrorCode.VALIDATION, "文件已存在，请使用 edit") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    preview, preview_truncated = clip_at_line_boundary(content, READ_PREVIEW_CHARS)
    lines_written = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return WriteResult(
        path=path,
        bytes_written=bytes_written,
        lines_written=lines_written,
        preview=preview,
        preview_truncated=preview_truncated,
    )


def _edit_mismatch_hint(content: str, old: str, *, preview_chars: int = 80) -> str:
    """构造 edit 失败的模型修复建议：邻近行号 + 短预览，不含全文。"""
    lines = content.splitlines() or [""]
    needle = (old or "").strip()[:24]
    target = 0
    if needle:
        for index, line in enumerate(lines):
            if needle[:8] and needle[:8] in line:
                target = index
                break
    start = max(0, target - 1)
    end = min(len(lines), target + 2)
    nearby = "\n".join(lines[start:end])
    if len(nearby) > preview_chars:
        nearby = nearby[:preview_chars] + "…"
    return (
        f"edit 失败：未找到匹配文本；文件第 {target + 1} 行附近内容为：{nearby}。"
        "请先 read 确认 old 与文件完全一致后再 edit。"
    )


def edit_file_safe(path: str, old: str, new: str, sandbox_dir: str) -> EditResult:
    """受控目录内精确原子替换（防目录穿越；不匹配则拒绝）。"""
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    with open(target, encoding="utf-8") as handle:
        content = handle.read()
    if old not in content:
        raise AppError(
            ErrorCode.VALIDATION,
            "原文不匹配，编辑已拒绝",
            fields={"repair_hint": _edit_mismatch_hint(content, old)},
        )
    replacement = content.replace(old, new, 1)
    _ensure_write_size(replacement)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".agent-edit-", dir=os.path.dirname(target), text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
    return EditResult(path=path, old_length=len(old), new_length=len(new))


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
        model_text = "\n\n".join(lines)[:WEB_MAX_CONTENT_CHARS]
        summary = f"网络搜索完成，返回 {len(self.results)} 条结果"
        return {
            "summary": summary,
            "model_text": model_text,
            "truncated": len("\n\n".join(lines)) > len(model_text),
            "source": "web:search",
            "display": {
                "summary": summary,
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
        """返回模型正文和受控 ToolCard 投影。"""
        title = self.title or urlparse(self.url).hostname or "网页"
        summary = f"已抓取 {title}"
        return {
            "summary": summary,
            "model_text": self.content,
            "truncated": self.truncated,
            "source": f"web:{urlparse(self.url).hostname or 'unknown'}",
            "display": {
                "summary": summary,
                "web": {
                    "url": self.url,
                    "title": self.title,
                    "format": self.format,
                    "preview": self.content[:WEB_PREVIEW_CHARS],
                    "preview_truncated": len(self.content) > WEB_PREVIEW_CHARS,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class TaskPlanResult:
    """会话内任务拆解结果，不对应数据库 Task 或 Worker 队列。"""

    goal: str
    steps: tuple[dict[str, str], ...]

    def to_tool_data(self) -> dict[str, object]:
        """返回模型可读清单和 ToolCard 摘要。"""
        lines = [f"目标：{self.goal}"]
        for index, step in enumerate(self.steps, start=1):
            lines.append(f"{index}. [{step['status']}] {step['title']}")
        model_text = "\n".join(lines)
        summary = f"已拆解为 {len(self.steps)} 个步骤（仅当前会话，不创建评测任务）"
        return {
            "summary": summary,
            "model_text": model_text,
            "source": "session:task-plan",
            "display": {"summary": summary, "task": {"goal": self.goal, "steps": list(self.steps)}},
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


def _read_limited_response(response) -> tuple[bytes, bool]:
    """读取上游响应的受控字节窗口，并保留是否截断标识。"""
    body = response.read(WEB_RESPONSE_MAX_BYTES + 1)
    return body[:WEB_RESPONSE_MAX_BYTES], len(body) > WEB_RESPONSE_MAX_BYTES


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


def web_search(query: str, *, limit: object | None = None, timeout_s: float) -> WebSearchResult:
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


def _fetch_via_firecrawl(url: str, format: str, *, timeout_s: float) -> WebFetchResult:
    """使用已配置的 Firecrawl 提取网页 Markdown，复用真实搜索服务配额。"""
    response = _request_firecrawl(
        "scrape",
        {"url": url, "formats": ["markdown" if format == "markdown" else "html"]},
        timeout_s=timeout_s,
    )
    data = response.get("data", response) if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        raise AppError(ErrorCode.UPSTREAM, "网页抓取服务返回格式无效")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    raw_content = data.get("markdown" if format == "markdown" else "html")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise AppError(ErrorCode.UPSTREAM, "网页抓取服务未返回正文")
    content = raw_content[:WEB_MAX_CONTENT_CHARS]
    return WebFetchResult(
        url=url,
        title=str(metadata.get("title") or "")[:300],
        content=content,
        format=format,
        truncated=len(raw_content) > len(content),
    )


def _fetch_direct(url: str, format: str, *, timeout_s: float) -> WebFetchResult:
    """未配置 Firecrawl 时，以受控 HTTP 文本抓取提供最小可用降级。"""
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
            raw, truncated_by_bytes = _read_limited_response(response)
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = _validate_public_url(response.geturl())
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"抓取失败（HTTP {exc.code}）") from exc
    except URLError as exc:
        raise AppError(ErrorCode.UPSTREAM, "抓取失败（网络错误）") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "抓取超时") from exc
    if not (content_type.startswith("text/") or content_type in {"application/json", "application/xml"}):
        raise AppError(ErrorCode.VALIDATION, "仅支持抓取文本或 HTML 页面")
    decoded = raw.decode(charset, errors="replace")
    title = ""
    content = decoded
    if content_type == "text/html":
        extractor = _TextExtractor()
        extractor.feed(decoded)
        title, content = extractor.result()
    if not content.strip():
        raise AppError(ErrorCode.UPSTREAM, "页面未返回可读取正文")
    content = content[:WEB_MAX_CONTENT_CHARS]
    return WebFetchResult(
        url=final_url,
        title=title,
        content=content,
        # 没有 Firecrawl 时只提取受控文本；不能把文本降级伪称 Markdown。
        format="text",
        truncated=truncated_by_bytes or len(decoded) > len(content),
    )


def web_fetch(url: str, *, format: str = "markdown", timeout_s: float) -> WebFetchResult:
    """抓取单页正文：优先 Firecrawl，未配置时走受控直接抓取，不走 MCP。"""
    if format not in {"markdown", "text"}:
        raise AppError(ErrorCode.VALIDATION, "抓取格式仅支持 markdown 或 text")
    normalized_url = _validate_public_url(url)
    if settings.firecrawl_api_key.strip():
        return _fetch_via_firecrawl(normalized_url, format, timeout_s=timeout_s)
    return _fetch_direct(normalized_url, format, timeout_s=timeout_s)


def build_task_plan(arguments: Mapping[str, object]) -> TaskPlanResult:
    """构造会话内任务清单；它不是 ``Task`` ORM 行，也不会触发 Worker。"""
    goal = str(arguments.get("goal") or "").strip()
    raw_steps = arguments.get("steps")
    if not goal:
        raise AppError(ErrorCode.VALIDATION, "任务目标不能为空")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 12:
        raise AppError(ErrorCode.VALIDATION, "任务步骤数量必须在 1 到 12 之间")
    steps: list[dict[str, str]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, Mapping):
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤格式无效")
        title = str(raw_step.get("title") or "").strip()
        status = str(raw_step.get("status") or "pending")
        if not title or len(title) > 300:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤标题无效")
        if status not in {"pending", "in_progress", "completed"}:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤状态无效")
        steps.append({"title": title, "status": status})
    return TaskPlanResult(goal=goal, steps=tuple(steps))


def execute_raw(
    call: ToolCall,
    *,
    timeout_s: float,
    permission: str,
    sandbox_dir: str | None = None,
    handler: object | None = None,
    context: object | None = None,
    recovery_policy: ToolRecoveryPolicy = DEFAULT_RECOVERY_POLICY,
) -> ToolResult:
    """按 call.name 分派到 handler，返回 ``ToolResult``（不抛，错误归一）。

    成功：``ok=True`` + 受控 data（read 用 ``ReadResult.to_tool_data``）；
    ``AppError`` → ``ok=False`` + error{code, message=中性文案}；未知异常 →
    INTERNAL。日志脱敏（调 M8 ``redact_for_log``，X-A4）。结果仍须由调用方
    经 ``normalize`` 转为 Observation（ToolResult 与 Observation 分离，§5.4）。

    ``context`` 为 ``ToolExecutionContext``（仅 contextual 工具由 provider
    透传）；非 None 时以第三位置参数传给 handler（platform 注入的会话/用户
    上下文，模型不可传）。
    """
    started = time.perf_counter()
    try:
        if handler is None:
            raise AppError(ErrorCode.VALIDATION, f"工具未注册：{call.name}")
        if context is None:
            result = handler(call.arguments, sandbox_dir)  # type: ignore[call-arg]
        else:
            result = handler(call.arguments, sandbox_dir, context)  # type: ignore[call-arg]
        latency_ms = round((time.perf_counter() - started) * 1000)
        to_tool_data = getattr(result, "to_tool_data", None)
        if callable(to_tool_data):
            data = to_tool_data()
        elif isinstance(result, Mapping):
            # 结构化结果（如 platform.tasks 三工具返回 dict）序列化为 JSON 文本，
            # 模型可直接解析；不暴露 Python repr。
            summary = json.dumps(dict(result), ensure_ascii=False)
            data = {"summary": summary, "display": {"summary": summary}}
        else:
            data = {
                "summary": str(result),
                "display": {"summary": str(result)},
            }
        data["latency_ms"] = latency_ms
        return ToolResult(name=call.name, ok=True, data=data, call_id=call.call_id)
    except AppError as exc:
        logger.info(
            "工具执行失败 name=%s code=%s args=%s",
            call.name,
            exc.code.value,
            redact_for_log(dict(call.arguments or {})),
        )
        code = exc.code.value
        error: dict[str, object] = {"code": code, "message": f"操作失败（{code}）"}
        hint = (exc.fields or {}).get("repair_hint") if exc.fields else None
        if hint:
            error["repair_hint"] = str(hint)[:500]
        error["recovery"] = recovery_policy.to_payload(code, str(hint or ""))
        return ToolResult(
            name=call.name,
            ok=False,
            error=error,
            call_id=call.call_id,
        )
    except Exception as exc:
        logger.warning(
            "工具执行内部异常 name=%s type=%s args=%s",
            call.name,
            type(exc).__name__,
            redact_for_log(dict(call.arguments or {})),
        )
        return ToolResult(
            name=call.name,
            ok=False,
            error={
                "code": "INTERNAL",
                "message": "操作失败（INTERNAL）",
                "recovery": recovery_policy.to_payload("INTERNAL"),
            },
            call_id=call.call_id,
        )


def execute(
    call: ToolCall,
    *,
    timeout_s: float,
    permission: str,
    sandbox_dir: str | None = None,
    handler: object | None = None,
    context: object | None = None,
    recovery_policy: ToolRecoveryPolicy = DEFAULT_RECOVERY_POLICY,
) -> Observation:
    """按 call.name 分派到 handler，带超时；归一为 observation（FB-1）。

    委托 ``execute_raw`` 获取 ToolResult 后经 ``normalize`` 归一；异常不裸抛、
    不导致 Agent 崩溃（对外只暴露 10 大 ErrorCode 语义，§5.2.1）。
    """
    return normalize(
        execute_raw(
            call,
            timeout_s=timeout_s,
            permission=permission,
            sandbox_dir=sandbox_dir,
            handler=handler,
            context=context,
            recovery_policy=recovery_policy,
        ),
        None,
        tool=call.name,
        arguments=dict(call.arguments or {}),
    )
