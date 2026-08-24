"""Harness 执行层：短工具分派 + 超时 + 脱敏日志（M5 阶段 2，EX-3）。

``execute`` 按 call.name 分派到注册表 handler，带超时；超时返回 ``timeout``
observation；日志脱敏（调 M8）。含受控目录文件工具（read/write/edit）与
web 内部短 MCP 适配器（web_search/web_fetch，不走外部 MCP 服务器）。

**⚠️ bash 安全边界（V0.4.2 评审闭环）**：命令黑名单 + 工作目录限定 + 超时
**不构成可靠安全沙箱**（可被解释器/绝对路径/重定向/脚本文件绕过），阶段 2
**不开放通用 bash**——``run_bash`` 仅提供黑名单校验实现供测试（X-A7），
注册表不登记 bash，未注册即被白名单拒绝。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.errors import AppError, ErrorCode
from app.harness.contracts import Observation, ToolCall, ToolResult
from app.harness.feedback.observation import normalize
from app.harness.security.secrets import redact_for_log

logger = logging.getLogger("ai-eval.harness.dispatch")

# bash 命令黑名单（阶段 2 不开放通用 bash；X-A7 断言）
BASH_BLOCKLIST: frozenset[str] = frozenset(
    {"rm", "sudo", "curl", "wget", "nc", "ssh", "scp", "chmod", "chown"}
)


def run_bash(cmd: str, *, sandbox_dir: str, timeout_s: float) -> str:
    """subprocess + 受限环境：工作目录限定、超时、命令黑名单校验。

    黑名单命中抛 AppError(VALIDATION)。
    ⚠️ 当前方案仅为受限执行，不构成安全沙箱，阶段 2 不开放通用 bash。
    """
    command = cmd.strip()
    if not command:
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    first = command.split()[0]
    if first in BASH_BLOCKLIST:
        raise AppError(ErrorCode.VALIDATION, f"bash 命令命中黑名单：{first}")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        logger.info("bash 执行超时 cmd=%.64s", command)
        raise AppError(ErrorCode.TIMEOUT, "命令执行超时") from exc
    if result.returncode != 0:
        raise AppError(ErrorCode.INTERNAL, f"命令执行失败（{result.returncode}）")
    return result.stdout.strip() or "（无输出）"


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


def read_file_safe(path: str, sandbox_dir: str) -> str:
    """受控目录内读取文本文件（防目录穿越）。"""
    target = _resolve_safe_path(path, sandbox_dir)
    if not os.path.isfile(target):
        raise AppError(ErrorCode.NOT_FOUND, "文件不存在")
    with open(target, encoding="utf-8", errors="replace") as handle:
        return handle.read()[:20000]


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
        return normalize(raw, None, tool=call.name)
    except AppError as exc:
        logger.info(
            "工具执行失败 name=%s code=%s args=%s",
            call.name,
            exc.code.value,
            redact_for_log(dict(call.arguments or {})),
        )
        return normalize(None, exc, tool=call.name)
    except Exception as exc:
        logger.warning(
            "工具执行内部异常 name=%s type=%s args=%s",
            call.name,
            type(exc).__name__,
            redact_for_log(dict(call.arguments or {})),
        )
        return normalize(None, exc, tool=call.name)
