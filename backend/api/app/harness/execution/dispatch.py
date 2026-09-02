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

import codecs
import ipaddress
import json
import logging
import os
import re
import shlex
import socket
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from types import ModuleType
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

# read 的行级窗口与内容硬上限。行数上限 2000 不变；字符预算与全局
# MODEL_TOOL_RESULT_MAX_CHARS 解耦（2026-08-26 调整：旧 8000 字符预算导致
# 1000 行文件必须分几十次读完）。模型不能通过 arguments 扩大字符预算，
# 避免大文件直接填满模型上下文或 WebSocket 持久化事件。
READ_DEFAULT_LIMIT = 2_000
READ_MAX_LIMIT = 2_000
# read 专属字符预算：覆盖 1000 行量级的长文件（含少量超长行）一次读完。
READ_MAX_CHARS = 600_000
# 预留元数据头与未读完提示，避免 model_text + 前缀/后缀再被截断半行。
READ_UNREAD_HINT_RESERVE = 320
READ_CONTENT_BUDGET = max(1, READ_MAX_CHARS - READ_UNREAD_HINT_RESERVE)
# 对齐 Agent 附件接口的 20MB 上限；窗口内仍只解码受控文本片段。
READ_MAX_BYTES = 20 * 1024 * 1024
# 剩余正文按块统计行数/字符，避免对未返回内容逐行建 Python 字符串导致超时。
READ_SCAN_CHUNK = 256 * 1024
WRITE_MAX_BYTES = 2 * 1024 * 1024
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


def preview_char_limit() -> int:
    """ToolCard 浏览器预览上限（字符，完整行边界截取）。

    默认与 read 模型窗口预算（READ_MAX_CHARS）同源对齐，保证「卡片所见 ==
    模型真实读取内容」；部署经 TOOL_PREVIEW_MAX_CHARS 调整（如设 4000 收紧
    回旧版安全窗，避免大文件进入 WS 广播与历史事件）。
    """
    return max(1, int(settings.tool_preview_max_chars))

# handler 可在受控输出生成时调用回调；回调由 ToolNode 注入，未运行在图内时为 None。
ToolOutputCallback = Callable[[str, str, int | None], None]
# 网络工具的阶段回调只描述生命周期，不包含 URL、正文或密钥。
ToolProgressCallback = Callable[[str, str], None]

# bash 命令硬黑名单（纵深防御；bwrap 沙箱之外的第二道防线）。
#
# ``rm`` / ``chmod`` / ``chown`` 等会改动会话工作区的命令不再在这里一律拒绝：
# 它们会先走 LangGraph 的人工确认中断，得到用户明确确认后才能进入 bwrap。网络、
# 提权和远程连接命令则不属于「可确认后执行」的范围，仍必须直接拒绝。
BASH_BLOCKLIST: frozenset[str] = frozenset(
    {"sudo", "curl", "wget", "nc", "ssh", "scp"}
)
_BASH_COMMAND_SEPARATOR = re.compile(r"(?:&&|\|\||[;|&\n])")
# 嵌套 shell（如 ``bash -c 'sudo id'``）不会让 sudo 出现在命令段首词；仍必须
# 识别其独立命令词，不能让人工确认卡意外放宽提权/网络/远程连接硬拒绝。
_BASH_BLOCK_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:sudo|curl|wget|nc|ssh|scp)(?![A-Za-z0-9_.-])"
)

# 只读白名单足够小才能作为「无需确认」的可靠例外。未识别的命令、shell 展开和
# 组合语法全部要求确认，宁可多问一次，也不能漏过会改动工作区的写操作。
_BASH_READONLY_COMMANDS: frozenset[str] = frozenset(
    {"cat", "diff", "du", "file", "head", "ls", "pwd", "stat", "tail", "wc", "grep"}
)
_BASH_SHELL_SYNTAX = re.compile(r"(?:[;&|<>`]|\$\(|\$\{|\n)")
_BASH_DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(
    {"rm", "rmdir", "unlink", "shred", "truncate"}
)
_BASH_MUTATING_COMMANDS: frozenset[str] = frozenset(
    {"chmod", "chown", "cp", "dd", "install", "ln", "mkdir", "mv", "sed", "tee", "touch"}
)


def bash_block_reason(cmd: str) -> str | None:
    """检查 bash 硬黑名单，返回命中原因；命中时不得进入人工确认卡。

    这里与 ``run_bash`` 共用同一段切分逻辑，保证多段命令既不能绕过 Runner
    的纵深防御，也不会出现「用户已确认但命令仍被硬拒绝」的误导性流程。
    """
    for segment in _BASH_COMMAND_SEPARATOR.split(cmd.strip()):
        first = segment.strip().split(maxsplit=1)[0] if segment.strip() else ""
        if first in BASH_BLOCKLIST:
            return f"bash 命令命中黑名单：{first}"
    # ``bash -c 'sudo id'``、``env ssh host`` 等嵌套/包装写法也不能降级为
    # “等待确认”：命中任一硬黑名单命令词就应直接结束，不调用 Runner。
    if matched := _BASH_BLOCK_TOKEN.search(cmd):
        return f"bash 命令命中黑名单：{matched.group(0)}"
    return None


def bash_approval_reason(cmd: str) -> str | None:
    """识别 bash 是否必须人工确认，返回供确认卡展示的脱敏风险原因。

    工具调用始终运行在无网络、仅会话工作区可写的 bwrap 沙箱中；本函数只决定
    是否暂停等待人工审核，不放宽沙箱或硬黑名单。``None`` 仅表示确定的简单
    只读命令，可直接执行。
    """
    command = cmd.strip()
    if not command:
        return "命令为空或无法判断其影响范围"
    if bash_block_reason(command):
        # 调用方会优先将其归一为 VALIDATION；本分支只是防止后续逻辑误判。
        return None
    if _BASH_SHELL_SYNTAX.search(command):
        return "命令包含重定向、管道、变量展开或多段 shell 语法，无法证明只读"
    try:
        parts = shlex.split(command)
    except ValueError:
        return "命令引号或转义格式异常，无法安全分析"
    if not parts:
        return "命令为空或无法判断其影响范围"
    program = parts[0].rsplit("/", maxsplit=1)[-1]
    if program in _BASH_DESTRUCTIVE_COMMANDS:
        return "命令会删除或清空当前会话工作区中的文件"
    if program in _BASH_MUTATING_COMMANDS:
        return "命令可能创建、覆盖、移动文件或修改文件权限"
    if program == "git":
        if len(parts) > 1 and parts[1] in {"diff", "log", "show", "status"}:
            return None
        return "Git 子命令可能修改当前会话工作区"
    if program == "find":
        if any(part in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for part in parts[1:]):
            return "find 命令包含会执行或删除文件的动作"
        return None
    if program in _BASH_READONLY_COMMANDS:
        return None
    return "命令不在受控只读白名单中，无法证明不会修改会话工作区"

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
    # 不只检查整条命令首词，避免 ``echo ok; sudo ...`` 绕过纵深防御；bwrap
    # 仍是最终隔离边界，黑名单不能替代沙箱。
    if blocked := bash_block_reason(command):
        raise AppError(ErrorCode.VALIDATION, blocked)
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
        preview_limit = preview_char_limit()
        preview, preview_truncated = clip_at_line_boundary(self.content, preview_limit)
        status = "已读完" if self.is_complete else "未读完"
        summary = (
            f"已读取 {self.path} 第 {self.start_line + 1}–{self.end_line} 行"
            f"（共 {self.total_lines} 行，{status}）"
        )
        # 元数据头随正文一起注入模型（native tool_result 与 legacy 观察注入
        # 同源）：让模型明确知道读取范围、总行数与是否读完，避免读完后再
        # 发确认性重读或绕路 bash 核实行数。
        model_text = f"{summary}\n{self.content}"
        if not self.is_complete and self.next_offset is not None:
            model_text = (
                f"{model_text.rstrip()}\n"
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
                "status": "success",
                "content": preview,
                "metadata": {
                    "total_lines": self.total_lines,
                    "truncated": not self.is_complete or preview_truncated,
                    "start_line": self.start_line,
                    "end_line": self.end_line,
                    "next_offset": self.next_offset,
                },
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
                    # 生效的预览上限随数据下发，前端提示文案不硬编码数字。
                    "preview_limit_chars": preview_limit,
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
    600,000 字符；达到字符预算时仅在完整行边界停止，
    返回准确的 ``next_offset``。窗口收齐后不再对剩余正文逐行迭代，只按块累计
    ``total_lines`` / ``total_chars``，避免大文档在工具超时内扫不完。
    完整正文只留在 ``ReadResult.content``，调用方必须投影为 Observation，
    不能直接写进 WebSocket 事件。
    """
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    if os.path.getsize(target) > READ_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "文件超过 read 单次允许的 20MB 上限")
    start = _read_non_negative_int(offset, name="offset", default=0)
    requested_limit = _read_non_negative_int(limit, name="limit", default=READ_DEFAULT_LIMIT)
    if requested_limit == 0:
        raise AppError(ErrorCode.VALIDATION, "limit 必须大于 0")
    size = min(requested_limit, READ_MAX_LIMIT)
    selected: list[str] = []
    chars_used = 0
    preview_chars = 0
    preview_limit = preview_char_limit()
    stream_lines: list[str] = []
    stream_start: int | None = None

    def flush_stream() -> None:
        """按完整行输出当前浏览器安全预览块，不超出配置的字符上限。"""
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
            # read 的实时输出与最终 ToolCard 同一上限：完整行、按配置截取。
            if on_output is not None and preview_chars + len(line) <= preview_limit:
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
                "status": "success",
                "path": f"workspace/{self.path.lstrip('./')}",
                "content": summary,
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
    replacements: int = 1
    modified_lines: int = 1
    diff: str = ""

    def to_tool_data(self) -> dict[str, object]:
        """生成模型摘要与 ToolCard 安全展示投影。"""
        summary = (
            f"已编辑 {self.path}（替换 {self.replacements} 处，"
            f"{self.old_length}→{self.new_length} 字符）"
        )
        return {
            "summary": summary,
            "display": {
                "summary": summary,
                "status": "success",
                "modified_lines": self.modified_lines,
                "diff": self.diff,
                "edit": {
                    "path": self.path,
                    "replacements": self.replacements,
                    "old_length": self.old_length,
                    "new_length": self.new_length,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class BashResult:
    """bash 的结构化安全投影，正文按行号显示且不持久化完整输出。"""

    output: str
    exit_code: int = 0
    duration_ms: int | None = None

    def to_tool_data(self) -> dict[str, object]:
        """把沙箱输出限制为 ToolCard 可见预览，完整片段仅供当前模型回合。"""
        preview, preview_truncated = clip_at_line_boundary(self.output, preview_char_limit())
        summary = "沙箱命令执行完成"
        return {
            "summary": summary,
            "model_text": self.output[:MODEL_TOOL_RESULT_MAX_CHARS],
            "truncated": len(self.output) > MODEL_TOOL_RESULT_MAX_CHARS,
            "source": "sandbox:bash",
            "display": {
                "summary": summary,
                "stdout": preview,
                "stderr": "",
                "exit_code": self.exit_code,
                "duration_ms": self.duration_ms if self.duration_ms is not None else 0,
                "is_background": False,
                "bash": {
                    "exit_code": self.exit_code,
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
    preview, preview_truncated = clip_at_line_boundary(content, preview_char_limit())
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


def _count_occurrences(content: str, needle: str) -> int:
    """统计精确子串出现次数，空串视为 0。"""
    if not needle:
        return 0
    return content.count(needle)


def _modified_line_count(content: str, needle: str) -> int:
    """估算被替换片段覆盖的行数，至少为 1。"""
    if not needle:
        return 0
    lines = 0
    start = 0
    while True:
        index = content.find(needle, start)
        if index < 0:
            break
        lines += needle.count("\n") + 1
        start = index + max(len(needle), 1)
    return max(lines, 1) if content.find(needle) >= 0 else 0


def _short_edit_diff(old: str, new: str) -> str:
    """生成限长统一差异摘要，避免把全文写进浏览器事件。"""
    old_preview = old[:80] + ("…" if len(old) > 80 else "")
    new_preview = new[:80] + ("…" if len(new) > 80 else "")
    return f"@@ -{len(old)} +{len(new)} @@\n-{old_preview}\n+{new_preview}"


def edit_file_safe(
    path: str,
    old: str,
    new: str,
    sandbox_dir: str,
    *,
    replace_all: bool = False,
) -> EditResult:
    """受控目录内精确原子替换（防目录穿越；默认必须唯一匹配）。"""
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    with open(target, encoding="utf-8") as handle:
        content = handle.read()
    matches = _count_occurrences(content, old)
    if matches == 0:
        raise AppError(
            ErrorCode.VALIDATION,
            "原文不匹配，编辑已拒绝",
            fields={
                "error": "StringNotFound",
                "repair_hint": _edit_mismatch_hint(content, old),
            },
        )
    if matches > 1 and not replace_all:
        raise AppError(
            ErrorCode.VALIDATION,
            "原文出现多处，编辑已拒绝",
            fields={
                "error": "MultipleMatches",
                "repair_hint": f"old_string 匹配 {matches} 处；请先 read 收窄原文，或显式传 replace_all=true。",
            },
        )
    replacement = content.replace(old, new) if replace_all else content.replace(old, new, 1)
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
    return EditResult(
        path=path,
        old_length=len(old),
        new_length=len(new),
        replacements=matches,
        modified_lines=_modified_line_count(content, old),
        diff=_short_edit_diff(old, new),
    )


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


@dataclass(frozen=True, slots=True)
class TaskPlanResult:
    """会话内任务拆解结果，不对应数据库 Task 或 Worker 队列。"""

    goal: str
    steps: tuple[dict[str, str], ...]
    description: str = ""

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
            "display": {
                "summary": summary,
                "status": "success",
                "result": summary,
                "task": {
                    "goal": self.goal,
                    "description": self.description,
                    "prompt": self.goal,
                    "steps": list(self.steps),
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


def build_task_plan(arguments: Mapping[str, object]) -> TaskPlanResult:
    """构造会话内任务清单；它不是 ``Task`` ORM 行，也不会触发 Worker。"""
    goal = str(arguments.get("prompt") or arguments.get("goal") or "").strip()
    description = str(arguments.get("description") or "").strip()
    raw_steps = arguments.get("steps")
    if not goal:
        raise AppError(ErrorCode.VALIDATION, "任务指令不能为空")
    if raw_steps is None:
        raw_steps = []
    if not isinstance(raw_steps, list) or len(raw_steps) > 12:
        raise AppError(ErrorCode.VALIDATION, "任务步骤数量必须在 0 到 12 之间")
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
    return TaskPlanResult(goal=goal, steps=tuple(steps), description=description)


def execute_raw(
    call: ToolCall,
    *,
    timeout_s: float,
    permission: str,
    sandbox_dir: str | None = None,
    handler: object | None = None,
    context: object | None = None,
    recovery_policy: ToolRecoveryPolicy = DEFAULT_RECOVERY_POLICY,
    output_schema: Mapping[str, object] | None = None,
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
        # output_schema 是 handler 展示投影的契约（非装饰字段）：运行期按声明比对，
        # 失败不外泄原始返回，归一为 INTERNAL 并只记录工具名与失败字段名。
        # 比对对象是 handler 原始返回（result），不是归一后的 data——data 已被
        # execute_raw 包成 {"summary","display"}，与 handler 声明的 output_schema 不同层。
        if output_schema:
            from .registry import validate_tool_output

            raw_projection: Mapping[str, object] | None = None
            if isinstance(result, Mapping):
                raw_projection = result
            else:
                to_tool_data = getattr(result, "to_tool_data", None)
                if callable(to_tool_data):
                    candidate = to_tool_data()
                    if isinstance(candidate, Mapping):
                        raw_projection = candidate
            if raw_projection is not None:
                output_error = validate_tool_output(output_schema, raw_projection)
                if output_error:
                    logger.warning(
                        "工具展示投影与 output_schema 不符 name=%s reason=%s",
                        call.name,
                        output_error,
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
        # 修复建议优先取 fields.repair_hint；无则回退 exc.message（如 write 覆盖
        # 拒绝的"文件已存在，请使用 edit"），避免模型只看到模糊错误盲目重试。
        hint = (exc.fields or {}).get("repair_hint") if exc.fields else None
        if not hint:
            message = str(getattr(exc, "message", "") or "")
            if message and message not in {"操作失败", "操作失败（INTERNAL）"}:
                hint = message
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
    output_schema: Mapping[str, object] | None = None,
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
            output_schema=output_schema,
        ),
        None,
        tool=call.name,
        arguments=dict(call.arguments or {}),
    )
