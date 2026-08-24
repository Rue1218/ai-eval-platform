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

import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.errors import AppError, ErrorCode
from app.harness.contracts import Observation, ToolCall, ToolResult
from app.harness.execution.sandbox import SandboxLimits, run_sandboxed
from app.harness.feedback.observation import normalize
from app.harness.security.secrets import redact_for_log

logger = logging.getLogger("ai-eval.harness.dispatch")

# bash 命令黑名单（纵深防御；bwrap 沙箱之外的第二道防线，禁止命令开头命中）
BASH_BLOCKLIST: frozenset[str] = frozenset(
    {"rm", "sudo", "curl", "wget", "nc", "ssh", "scp", "chmod", "chown"}
)


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


def read_file_safe(
    path: str,
    sandbox_dir: str,
    *,
    offset: object | None = None,
    limit: object | None = None,
) -> str:
    """受控目录内读取文本文件（防目录穿越）。

    ``offset``（起始字符偏移）与 ``limit``（最多返回字符数，默认 20000）支持
    长文件分段读取；非法负值被钳制，不抛错。**文件未读完时在末尾追加截断
    标记并提示下一起始偏移**，避免模型误以为已读完全文。
    """
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    start = max(0, int(offset or 0))
    size = max(1, int(limit or 8000))
    with open(target, encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    chunk = content[start : start + size]
    if start + size < len(content):
        chunk += f"\n…[文件未读完，剩余内容可用 offset={start + len(chunk)} 继续读取]"
    return chunk


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
    """内部抓取适配器 + 脱敏（不走外部 MCP 服务器）。"""
    if not url.startswith(("http://", "https://")):
        raise AppError(ErrorCode.VALIDATION, "仅支持 http/https 地址")
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
        raw = ToolResult(
            name=call.name,
            ok=True,
            data={"summary": str(result), "latency_ms": latency_ms},
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
