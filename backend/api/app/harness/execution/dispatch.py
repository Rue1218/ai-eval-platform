"""Harness 执行层：短工具分派 + 超时 + 脱敏日志（M5 阶段 3，EX-3/EX-6）。

``execute`` 按 call.name 分派到注册表 handler，带超时；超时返回 ``timeout``
observation；日志脱敏（调 M8）。含受控目录文件工具（read/write/edit）、
原生网络适配器（web_search/web_fetch）与 **bwrap 沙箱 bash**
（阶段 3 开放通用 bash，安全边界见 ``sandbox.py``）。

**bash 安全边界（F2/G4 修订）**：无字符串词表/静态裁决（§6.3，物理边界
覆盖：无网络、scope 按档位 bind、系统目录只读、资源受限、超时整树清理）；
按档位（``mode`` ∈ workspace-write/read-only）执行——准入由「会话档位 +
升档审批」承担（§6.1.1/§6.4），沙箱不可用时 fail-closed，**禁止降级为裸
subprocess**。
"""

from __future__ import annotations

import base64
import fnmatch
import json
import logging
import os
import re
import struct
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS
from app.harness.contracts import Observation, ToolCall, ToolResult
from app.harness.execution.sandbox import SandboxLimits, run_sandboxed
from app.harness.feedback.observation import normalize
from app.harness.security.secrets import redact_for_log

from .aliases import normalize_tool_arguments
from .dispatch_common import (  # noqa: F401  （对外兼容导出，共享底层见 dispatch_common）
    ToolOutputCallback,
    ToolProgressCallback,
    clip_at_line_boundary,
    preview_char_limit,
)
from .dispatch_web import (  # noqa: F401  （对外兼容导出，web 工具域见 dispatch_web）
    WebFetchResult,
    WebSearchResult,
    apply_fetch_content_budget,
    assert_fetch_domains,
    web_fetch,
    web_search,
)
from .policy import DEFAULT_RECOVERY_POLICY, ToolRecoveryPolicy
from .quota import check_workspace_write_capacity, invalidate_usage_cache

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
# 图片工具仅接收当前会话工作区中的常见静态图片；上限与对话图片附件一致。
READ_IMAGE_MAX_BYTES = 4 * 1024 * 1024
# 文件搜索不能借单次调用无限枚举工作区或填满下一步上下文。
SEARCH_MAX_RESULTS = 500
SEARCH_MAX_CHARS = 60_000
# 剩余正文按块统计行数/字符，避免对未返回内容逐行建 Python 字符串导致超时。
READ_SCAN_CHUNK = 256 * 1024
WRITE_MAX_BYTES = 2 * 1024 * 1024
# F2/G4：bash 字符串词表与静态裁决已全部删除（《工作区与沙箱设计方案》§6.3）
# ——准入不再对命令文本做静态分析：网络命令由 bwrap --unshare-net 覆盖、提权
# 与破坏命令由「降权容器 + scope bind + 会话档位/升档审批」承担（§6.1.1/§6.4）。

def run_bash(
    cmd: str,
    *,
    sandbox_dir: str,
    mode: str = "isolated",
    timeout_s: float,
    limits: SandboxLimits | None = None,
    on_output: ToolOutputCallback | None = None,
) -> str:
    """按网络模式经 runner 容器执行 shell 命令（阶段 3 开放通用 bash）。

    无字符串词表/静态裁决（§6.3）——准入由权限档位审批 + 物理边界承担：
    经 ``run_sandboxed`` 在 runner 容器内执行（isolated → unshare --net 断网；
    network → 保留网络；资源受限、超时整树清理）；引擎不可用时 fail-closed，
    禁止降级为无隔离执行。
    """
    command = cmd.strip()
    if not command:
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    return run_sandboxed(
        command,
        sandbox_dir=sandbox_dir,
        mode=mode,
        timeout_s=timeout_s,
        limits=limits,
        on_output=(
            (lambda chunk: on_output("stdout", chunk, None))
            if on_output is not None
            else None
        ),
    )


def _resolve_safe_path(path: str, root: str) -> str:
    """解析文件工具目标路径，返回 canonical 绝对路径（M5-D7 红线）。

    - **相对路径**：解析到受控工作区 ``root`` 内；目录穿越/越界拒绝。
    - **绝对路径**：必须位于外部白名单基目录 ``settings.external_base_dir``
      之下（realpath 逐段解析，符号链接逃逸拒绝）；未配置基目录时一律拒绝。

    越界/非法一律抛 ``AppError(VALIDATION)``（fail-closed）。
    """
    if not path:
        raise AppError(ErrorCode.VALIDATION, "路径不能为空")
    if os.path.isabs(path):
        base = (settings.external_base_dir or "").strip()
        if not base:
            raise AppError(ErrorCode.VALIDATION, "未启用外部目录访问")
        base_real = os.path.realpath(base)
        target = os.path.realpath(os.path.abspath(path))
        if target != base_real and not target.startswith(base_real + os.sep):
            raise AppError(ErrorCode.VALIDATION, "绝对路径越出外部白名单目录")
        return target
    if not root:
        raise AppError(ErrorCode.VALIDATION, "未配置沙箱目录")
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, path))
    if not target.startswith(root_real + os.sep) and target != root_real:
        raise AppError(ErrorCode.VALIDATION, "路径越出沙箱目录")
    return target


def _workspace_relative(path: str, root: str) -> str:
    """返回稳定的工作区相对路径，供搜索工具回传给模型而非暴露绝对路径。"""
    return os.path.relpath(path, os.path.realpath(root)).replace(os.sep, "/")


def _iter_workspace_files(root: str, workspace_root: str):
    """遍历受控目录中的普通文件，排除 VCS、依赖缓存和所有符号链接。"""
    excluded = {".git", ".hg", ".svn", "node_modules", "__pycache__"}
    root_real = os.path.realpath(root)
    workspace_real = os.path.realpath(workspace_root)
    for directory, names, files in os.walk(root_real, followlinks=False):
        # os.walk 默认不跟随链接；仍显式移除目录链接，避免未来参数调整导致越界。
        names[:] = [
            name for name in names
            if name not in excluded and not os.path.islink(os.path.join(directory, name))
        ]
        for name in files:
            candidate = os.path.join(directory, name)
            if os.path.islink(candidate) or not os.path.isfile(candidate):
                continue
            real = os.path.realpath(candidate)
            if real.startswith(workspace_real + os.sep) or real == workspace_real:
                yield real


def _image_metadata(payload: bytes) -> tuple[str, int | None, int | None]:
    """从常见图片头读取格式与尺寸，不引入会阻塞 API 进程的图像解码依赖。"""
    if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
        width, height = struct.unpack(">II", payload[16:24])
        return "image/png", width, height
    if payload.startswith((b"GIF87a", b"GIF89a")) and len(payload) >= 10:
        width, height = struct.unpack("<HH", payload[6:10])
        return "image/gif", width, height
    if payload.startswith(b"\xff\xd8"):
        cursor = 2
        while cursor + 9 < len(payload):
            if payload[cursor] != 0xFF:
                cursor += 1
                continue
            marker = payload[cursor + 1]
            cursor += 2
            if marker in {0xD8, 0xD9}:
                continue
            if cursor + 2 > len(payload):
                break
            length = struct.unpack(">H", payload[cursor:cursor + 2])[0]
            if length < 2 or cursor + length > len(payload):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and length >= 7:
                height, width = struct.unpack(">HH", payload[cursor + 3:cursor + 7])
                return "image/jpeg", width, height
            cursor += length
        return "image/jpeg", None, None
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        if payload[12:16] == b"VP8X" and len(payload) >= 30:
            width = 1 + int.from_bytes(payload[24:27], "little")
            height = 1 + int.from_bytes(payload[27:30], "little")
            return "image/webp", width, height
        return "image/webp", None, None
    raise AppError(ErrorCode.VALIDATION, "仅支持 PNG、JPEG、GIF 或 WebP 图片")


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


@dataclass(frozen=True, slots=True)
class ImageReadResult:
    """图片读取结果：日志只保存摘要，当前工具链向模型回填受限图文块。"""

    path: str
    media_type: str
    size_bytes: int
    width: int | None
    height: int | None
    data_url: str

    def to_tool_data(self) -> dict[str, object]:
        """构造仅当前回合可见的图文内容，避免 Base64 进入事件、ToolCard 或恢复日志。"""
        dimensions = (
            f"，{self.width}×{self.height} 像素"
            if self.width is not None and self.height is not None
            else ""
        )
        summary = f"已读取图片 {self.path}（{self.media_type}，{self.size_bytes} 字节{dimensions}）"
        return {
            "summary": summary,
            "model_text": summary,
            # 模型适配器会把该图文块转换为当前 provider 的 tool-result 内容格式。
            "model_content": [
                {"type": "text", "text": summary},
                {"type": "image_url", "image_url": {"url": self.data_url}},
            ],
            "source": f"workspace:{self.path}",
            "display": {
                "summary": summary,
                "status": "success",
                "read_image": {
                    "path": self.path,
                    "media_type": self.media_type,
                    "size_bytes": self.size_bytes,
                    "width": self.width,
                    "height": self.height,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class FileSearchResult:
    """glob/grep 的共享回传结构，模型正文与浏览器安全预览使用同一受控窗口。"""

    kind: str
    query: str
    lines: tuple[str, ...]
    truncated: bool

    def to_tool_data(self) -> dict[str, object]:
        """返回相对路径搜索结果，超限时明确告知模型缩窄范围。"""
        body = "\n".join(self.lines)
        if self.truncated:
            body = f"{body}\n…[结果已截断，请缩小 path、pattern 或 include]" if body else "…[结果已截断，请缩小查询范围]"
        summary = f"{self.kind} 完成，返回 {len(self.lines)} 条结果"
        preview, preview_truncated = clip_at_line_boundary(body, preview_char_limit())
        return {
            "summary": summary,
            "model_text": body,
            "truncated": self.truncated,
            "source": f"workspace:{self.kind}",
            "display": {
                "summary": summary,
                "status": "success",
                "content": preview,
                self.kind: {
                    "query": self.query,
                    "count": len(self.lines),
                    "truncated": self.truncated or preview_truncated,
                    "preview": preview,
                },
            },
        }


def read_image_safe(path: str, sandbox_dir: str) -> ImageReadResult:
    """读取工作区图片并构造图文块；不接受绝对路径、链接或超限文件。"""
    target = _resolve_safe_path(path, sandbox_dir)
    if os.path.islink(target) or not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "图片文件不存在")
    size_bytes = os.path.getsize(target)
    if size_bytes > READ_IMAGE_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "图片超过 read_image 单次允许的 4MB 上限")
    try:
        with open(target, "rb") as handle:
            payload = handle.read(READ_IMAGE_MAX_BYTES + 1)
    except OSError as exc:
        raise AppError(ErrorCode.INTERNAL, "图片读取失败") from exc
    if len(payload) != size_bytes or len(payload) > READ_IMAGE_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "图片超过 read_image 单次允许的 4MB 上限")
    media_type, width, height = _image_metadata(payload)
    encoded = base64.b64encode(payload).decode("ascii")
    return ImageReadResult(
        path=path,
        media_type=media_type,
        size_bytes=size_bytes,
        width=width,
        height=height,
        data_url=f"data:{media_type};base64,{encoded}",
    )


def glob_files_safe(pattern: str, sandbox_dir: str, path: str | None = None) -> FileSearchResult:
    """在工作区内按 glob 枚举普通文件；无斜杠模式匹配任意层级的文件名。"""
    if not pattern.strip():
        raise AppError(ErrorCode.VALIDATION, "pattern 不能为空")
    root = _resolve_safe_path(path or ".", sandbox_dir)
    if not os.path.isdir(root) or os.path.islink(root):
        raise AppError(ErrorCode.VALIDATION, "glob 的 path 必须是工作区内目录")
    has_separator = "/" in pattern.replace("\\", "/")
    matches: list[str] = []
    for candidate in _iter_workspace_files(root, sandbox_dir):
        relative_root = _workspace_relative(candidate, root)
        target = relative_root if has_separator else os.path.basename(candidate)
        if not fnmatch.fnmatchcase(target, pattern):
            continue
        matches.append(_workspace_relative(candidate, sandbox_dir))
    matches.sort()
    truncated = len(matches) > SEARCH_MAX_RESULTS
    return FileSearchResult("glob", pattern, tuple(matches[:SEARCH_MAX_RESULTS]), truncated)


def grep_files_safe(
    pattern: str,
    sandbox_dir: str,
    *,
    path: str | None = None,
    include: str | None = None,
) -> FileSearchResult:
    """在工作区普通文本文件中执行 Python 正则搜索，返回 ``path:line:text``。"""
    if not pattern.strip():
        raise AppError(ErrorCode.VALIDATION, "pattern 不能为空")
    try:
        expression = re.compile(pattern)
    except re.error as exc:
        raise AppError(ErrorCode.VALIDATION, "grep 正则表达式无效") from exc
    root = _resolve_safe_path(path or ".", sandbox_dir)
    if not os.path.isdir(root) or os.path.islink(root):
        raise AppError(ErrorCode.VALIDATION, "grep 的 path 必须是工作区内目录")
    matches: list[str] = []
    chars = 0
    truncated = False
    for candidate in _iter_workspace_files(root, sandbox_dir):
        relative_root = _workspace_relative(candidate, root)
        if include and not fnmatch.fnmatchcase(relative_root, include):
            continue
        try:
            with open(candidate, "rb") as handle:
                if b"\x00" in handle.read(4096):
                    continue
            with open(candidate, encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if expression.search(line) is None:
                        continue
                    rendered = f"{_workspace_relative(candidate, sandbox_dir)}:{line_number}:{line.rstrip()}"
                    if len(matches) >= SEARCH_MAX_RESULTS or chars + len(rendered) > SEARCH_MAX_CHARS:
                        truncated = True
                        break
                    matches.append(rendered)
                    chars += len(rendered)
        except OSError:
            # 单个文件在遍历期间消失或不可读不能扩大搜索根；继续查其他文件。
            continue
        if truncated:
            break
    return FileSearchResult("grep", pattern, tuple(matches), truncated)


def resolve_read_offset(arguments: Mapping[str, object] | None) -> object | None:
    """取 read 起始行：优先 ``offset``，否则接受模型回填的 ``next_offset``。"""
    raw = arguments or {}
    offset = raw.get("offset")
    return raw.get("next_offset") if offset is None else offset


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
    """受控目录内原子新建文本文件（防目录穿越与覆盖竞争）。

    F5/G6：写前做工作区容量检查（§6.6——单次 2MB 上限之外的工作区总配额与
    卷水位；超限 VALIDATION 明确文案）；成功后标脏用量缓存（下一查重算）。
    """
    target = _resolve_safe_path(path, sandbox_dir)
    bytes_written = _ensure_write_size(content)
    check_workspace_write_capacity(sandbox_dir, extra_bytes=bytes_written)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise AppError(ErrorCode.VALIDATION, "文件已存在，请使用 edit") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    invalidate_usage_cache(sandbox_dir)
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
    # F5/G6：edit 净增容量检查（新文件字节 - 旧文件字节，负净增不额外占额）
    try:
        old_size = os.path.getsize(target)
    except OSError:
        old_size = 0
    extra = max(0, len(replacement.encode("utf-8")) - old_size)
    check_workspace_write_capacity(sandbox_dir, extra_bytes=extra)
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
    invalidate_usage_cache(sandbox_dir)
    return EditResult(
        path=path,
        old_length=len(old),
        new_length=len(new),
        replacements=matches,
        modified_lines=_modified_line_count(content, old),
        diff=_short_edit_diff(old, new),
    )


@dataclass(frozen=True, slots=True)
class TaskPlanResult:
    """会话内任务拆解结果，不对应数据库 Task 或 Worker 队列。"""

    goal: str
    steps: tuple[dict[str, str], ...]
    description: str = ""

    def to_snapshot(self) -> dict[str, object]:
        """返回写入会话事实的完整规划快照，供回放按最后一次成功写入覆盖。"""
        counts = {
            status: sum(step["status"] == status for step in self.steps)
            for status in ("pending", "in_progress", "completed")
        }
        return {
            "goal": self.goal,
            "description": self.description or self.goal,
            "steps": [dict(step) for step in self.steps],
            "counts": {
                "pending": counts["pending"],
                "in_progress": counts["in_progress"],
                "completed": counts["completed"],
            },
        }

    def to_tool_data(self) -> dict[str, object]:
        """返回模型可读清单和 ToolCard 摘要。"""
        lines = [f"目标：{self.goal}"]
        for index, step in enumerate(self.steps, start=1):
            lines.append(f"{index}. [{step['status']}] {step['title']}")
        model_text = "\n".join(lines)
        summary = f"已拆解为 {len(self.steps)} 个步骤（仅当前会话，不创建评测任务）"
        snapshot = self.to_snapshot()
        return {
            "summary": summary,
            "model_text": model_text,
            "source": "session:task-plan",
            "display": {
                "summary": summary,
                "status": "success",
                "result": summary,
                "task": {
                    "goal": snapshot["goal"],
                    "description": snapshot["description"],
                    "prompt": self.goal,
                    "steps": snapshot["steps"],
                },
            },
        }


def build_task_plan(arguments: Mapping[str, object]) -> TaskPlanResult:
    """构造会话内任务清单；整表参数不对应 ``Task`` ORM 行或 Worker 队列。"""
    # 执行入口和持久化校验均使用同一份归一结果，避免旧目标的摘要与快照分歧。
    arguments = normalize_tool_arguments("task", arguments)
    description = str(arguments.get("description") or "").strip()
    goal = description or str(arguments.get("prompt") or arguments.get("goal") or "").strip()
    raw_steps = arguments.get("steps")
    if not goal:
        raise AppError(ErrorCode.VALIDATION, "任务概括不能为空")
    if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > 12:
        raise AppError(ErrorCode.VALIDATION, "任务步骤数量必须在 1 到 12 之间")
    steps: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    in_progress_count = 0
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, Mapping):
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤格式无效")
        title = str(raw_step.get("title") or "").strip()
        status = str(raw_step.get("status") or "pending")
        if not title or len(title) > 300:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤标题无效")
        normalized_title = title.casefold()
        if normalized_title in seen_titles:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤与已有步骤重复")
        seen_titles.add(normalized_title)
        if status not in {"pending", "in_progress", "completed"}:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个任务步骤状态无效")
        if status == "in_progress":
            in_progress_count += 1
        steps.append({"title": title, "status": status})
    if in_progress_count > 1:
        raise AppError(ErrorCode.VALIDATION, "顺序会话规划同时只能有一个进行中的步骤")
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
        # 映射型 handler 直接返回展示投影；带 to_tool_data 的结果则固定以 data.display
        # 为投影。禁止对包含 model_text/source 等内部字段的外层包装校验，以免契约失焦。
        if output_schema:
            from .registry import validate_tool_output

            raw_projection: Mapping[str, object] | None = None
            if isinstance(result, Mapping):
                raw_projection = result
            elif isinstance(data, Mapping):
                candidate = data.get("display")
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
        # MAJ-1 修复：仅 bash 的 VALIDATION（退出码/stderr 摘要）把可读原因直接
        # 放 message——原生回填中模型可见具体失败原因，避免只见「操作失败
        # （VALIDATION）」对同命令盲重试直至撞墙钟。其余工具维持通用文案契约
        # （具体原因经 repair_hint，ToolCard/observation.text 既有断言不变）。
        detail = str(getattr(exc, "message", "") or "")
        message = f"操作失败（{code}）"
        if (
            code == "VALIDATION"
            and getattr(call, "name", "") == "bash"
            and detail
            and "操作失败" not in detail
        ):
            message = detail[:300]
        error: dict[str, object] = {"code": code, "message": message}
        # 修复建议优先取 fields.repair_hint；无则回退 exc.message（如 write 覆盖
        # 拒绝的"文件已存在，请使用 edit"），避免模型只看到模糊错误盲目重试。
        hint = (exc.fields or {}).get("repair_hint") if exc.fields else None
        if not hint:
            if detail and detail not in {"操作失败", "操作失败（INTERNAL）", "操作失败（VALIDATION）"}:
                hint = detail
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
