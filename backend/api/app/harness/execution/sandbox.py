"""Harness 执行层：沙箱远程客户端（M5 阶段 3，EX-6 / P4-2）。

bwrap 内核已迁至 ``shared.sandbox_kernel`` 并由**独立 runner 容器**执行；
本模块是 api 侧客户端：``run_sandboxed`` 经 HTTP JSON 调 runner（compose 内网
``SANDBOX_RUNNER_URL``），**api 进程内不再运行 bwrap**（api 容器不再需要
privileged/seccomp:unconfined/SYS_ADMIN/bubblewrap）。

- 成功：``ok=true`` + ``output``；
- runner 返回错误：映射 ``TIMEOUT/VALIDATION/INTERNAL`` → 对应 ``AppError``；
- fail-closed：runner 不可达/请求超时/响应损坏一律抛
  ``AppError(VALIDATION, "沙箱引擎不可用")``，禁止降级为裸 subprocess。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared.sandbox_kernel import SandboxLimits  # noqa: F401  （对外兼容导出）

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS

logger = logging.getLogger("ai-eval.harness.sandbox")

# runner 错误码 → api ErrorCode
_ERROR_MAP: Mapping[str, ErrorCode] = {
    "TIMEOUT": ErrorCode.TIMEOUT,
    "VALIDATION": ErrorCode.VALIDATION,
    "INTERNAL": ErrorCode.INTERNAL,
}

# 冒烟探测结果缓存（None=未探测；True/False=已探测）
_PROBE_RESULT: bool | None = None


def _runner_url(path: str) -> str:
    base = (settings.sandbox_runner_url or "http://runner:8001").rstrip("/")
    return f"{base}{path}"


def run_sandboxed(
    cmd: str,
    *,
    sandbox_dir: str,
    timeout_s: float,
    limits: SandboxLimits | None = None,
    bwrap_bin: str = "/usr/bin/bwrap",
    max_output_chars: int = MODEL_TOOL_RESULT_MAX_CHARS,
) -> str:
    """经 runner 在一次性 bwrap 沙箱内执行命令，返回 stdout；失败归一为 AppError。

    ``bwrap_bin`` 仅为签名兼容保留（bwrap 路径由 runner 侧 env 决定，api 不
    可指定——安全边界）。失败抛 AppError（TIMEOUT/VALIDATION/INTERNAL），
    runner 不可达时 fail-closed（VALIDATION「沙箱引擎不可用」）。
    """
    if not cmd.strip():
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    limits = limits or SandboxLimits()
    payload = {
        "command": cmd,
        "sandbox_dir": sandbox_dir,
        "timeout_s": timeout_s,
        "limits": {
            "memory_kb": limits.memory_kb,
            "nproc": limits.nproc,
            "cpu_s": limits.cpu_s,
        },
        "max_output_chars": max_output_chars,
    }
    # 记录脱敏摘要（命令长度与目录，不打印命令原文/密钥）
    logger.info("bash 沙箱执行 len=%d dir=%s timeout=%s", len(cmd), sandbox_dir, timeout_s)
    request = Request(
        _runner_url("/run"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s + 5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        # runner 不可达/超时/响应损坏：fail-closed，禁止降级为裸 subprocess
        raise AppError(ErrorCode.VALIDATION, "沙箱引擎不可用") from None
    if not isinstance(body, Mapping) or not body.get("ok"):
        error = body.get("error") if isinstance(body, Mapping) else None
        code = str((error or {}).get("code") or "INTERNAL")
        message = str((error or {}).get("message") or "沙箱执行失败")
        raise AppError(_ERROR_MAP.get(code, ErrorCode.INTERNAL), message)
    return str(body.get("output") or "（无输出）")


def probe_sandbox(bwrap_bin: str = "/usr/bin/bwrap", timeout_s: float = 5.0) -> bool:
    """经 runner 冒烟探测 bwrap 可用性；结果进程内缓存。

    runner 不可达/探测失败返回 False（调用方据此 fail-closed）。``bwrap_bin``
    仅为签名兼容保留，实际由 runner 侧 env 决定。
    """
    global _PROBE_RESULT
    if _PROBE_RESULT is not None:
        return _PROBE_RESULT
    request = Request(
        _runner_url("/probe"),
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        _PROBE_RESULT = bool(body.get("ok")) if isinstance(body, Mapping) else False
    except (URLError, OSError, ValueError):
        _PROBE_RESULT = False
    logger.info("沙箱 runner 冒烟探测 result=%s", _PROBE_RESULT)
    return _PROBE_RESULT


def reset_probe_cache() -> None:
    """清空冒烟探测缓存（测试用）。"""
    global _PROBE_RESULT
    _PROBE_RESULT = None
