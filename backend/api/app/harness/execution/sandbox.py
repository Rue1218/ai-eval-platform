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
import threading
from collections.abc import Callable, Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared.sandbox_kernel import SandboxLimits  # noqa: F401  （对外兼容导出）

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.context.observation import MODEL_TOOL_RESULT_MAX_CHARS

logger = logging.getLogger("ai-eval.harness.sandbox")

# runner 错误码 → api ErrorCode（BUSY 归属并发冲突；DENIED = read-only 拒写，
# F5/G6 升档审批触发源）
_ERROR_MAP: Mapping[str, ErrorCode] = {
    "TIMEOUT": ErrorCode.TIMEOUT,
    "VALIDATION": ErrorCode.VALIDATION,
    "INTERNAL": ErrorCode.INTERNAL,
    "BUSY": ErrorCode.CONCURRENCY,
    "DENIED": ErrorCode.DENIED,
}

# 冒烟探测结果缓存（None=未探测；True/False=已探测）
_PROBE_RESULT: bool | None = None

# 每 scope 并发闸门（D4/G3）：同一工作区目录同时至多 1 个 bash 在途，
# 防并行写互相踩踏；与 runner 全局槽位构成双层。线程锁注册表（目录数
# 受工作区/会话数量约束，不做引用计数回收）。
_SCOPE_GATES: dict[str, threading.Lock] = {}
_SCOPE_GATES_GUARD = threading.Lock()


def _scope_gate(sandbox_dir: str) -> threading.Lock:
    with _SCOPE_GATES_GUARD:
        gate = _SCOPE_GATES.get(sandbox_dir)
        if gate is None:
            gate = threading.Lock()
            _SCOPE_GATES[sandbox_dir] = gate
        return gate


def _runner_url(path: str) -> str:
    base = (settings.sandbox_runner_url or "http://runner:8001").rstrip("/")
    return f"{base}{path}"


def run_sandboxed(
    cmd: str,
    *,
    sandbox_dir: str,
    mode: str = "isolated",
    timeout_s: float,
    limits: SandboxLimits | None = None,
    bwrap_bin: str = "/usr/bin/bwrap",
    max_output_chars: int = MODEL_TOOL_RESULT_MAX_CHARS,
    on_output: Callable[[str], None] | None = None,
) -> str:
    """经 runner 在容器内直跑命令，返回 stdout；失败归一为 AppError。

    ``mode`` ∈ {"isolated", "network"}（网络模式，见 shared.sandbox_kernel.
    NETWORK_MODES），经 ``policy{mode, workspace_root}`` 传给 runner；旧文件
    效果档位（workspace-write/read-only）自动映射为 isolated（过渡兼容）。
    ``sandbox_dir`` 参数名保留为兼容别名，语义 = policy.workspace_root。
    ``bwrap_bin`` 仅为签名兼容保留（已无 bwrap）。失败抛 AppError
    （TIMEOUT/VALIDATION/INTERNAL），runner 不可达时 fail-closed。
    """
    if not cmd.strip():
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    mode = {"workspace-write": "isolated", "read-only": "isolated"}.get(mode, mode)
    if mode not in {"isolated", "network"}:
        raise AppError(ErrorCode.VALIDATION, f"未知沙箱档位：{mode}")
    limits = limits or SandboxLimits()
    # 每 scope 闸门（D4/G3）：同目录 bash 排他，限时等待（config 可调）
    gate = _scope_gate(sandbox_dir)
    if not gate.acquire(timeout=settings.sandbox_bash_gate_timeout_s):
        raise AppError(ErrorCode.CONCURRENCY, "该工作区已有 bash 命令执行中，请稍后重试")
    try:
        payload = {
            "command": cmd,
            "policy": {"mode": mode, "workspace_root": sandbox_dir},
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
            _runner_url("/run/stream" if on_output is not None else "/run"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_s + 5) as resp:
                if on_output is None:
                    body = json.loads(resp.read().decode("utf-8"))
                else:
                    return _read_stream_response(resp, on_output)
        except (URLError, OSError, ValueError):
            # runner 不可达/超时/响应损坏：fail-closed，禁止降级为裸 subprocess
            raise AppError(ErrorCode.VALIDATION, "沙箱引擎不可用") from None
        if not isinstance(body, Mapping) or not body.get("ok"):
            error = body.get("error") if isinstance(body, Mapping) else None
            code = str((error or {}).get("code") or "INTERNAL")
            message = str((error or {}).get("message") or "沙箱执行失败")
            raise AppError(_ERROR_MAP.get(code, ErrorCode.INTERNAL), message)
        return str(body.get("output") or "（无输出）")
    finally:
        gate.release()


def _read_stream_response(response: object, on_output: Callable[[str], None]) -> str:
    """消费 runner NDJSON 输出，转发安全片段并按最终帧判定执行结果。"""
    chunks: list[str] = []
    result: Mapping[str, object] | None = None
    try:
        iterator = iter(response)  # type: ignore[arg-type]
        for raw in iterator:
            if not isinstance(raw, bytes):
                continue
            line = raw.strip()
            if not line:
                continue
            frame = json.loads(line.decode("utf-8"))
            if not isinstance(frame, Mapping):
                raise ValueError("runner 流式帧格式无效")
            if frame.get("type") == "output":
                chunk = str(frame.get("chunk") or "")
                if chunk:
                    chunks.append(chunk)
                    on_output(chunk)
            elif frame.get("type") == "result":
                result = frame
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("runner 流式响应无效") from exc
    if result is None:
        raise ValueError("runner 缺少结果帧")
    if not result.get("ok"):
        error = result.get("error") if isinstance(result.get("error"), Mapping) else {}
        code = str(error.get("code") or "INTERNAL")
        message = str(error.get("message") or "沙箱执行失败")
        raise AppError(_ERROR_MAP.get(code, ErrorCode.INTERNAL), message)
    return "".join(chunks).strip() or "（无输出）"


def probe_sandbox(bwrap_bin: str = "/usr/bin/bwrap", timeout_s: float = 5.0) -> bool:
    """经 runner 冒烟探测命名空间（unshare）可用性；结果进程内缓存。

    runner 不可达/探测失败返回 False（调用方据此 fail-closed）。``bwrap_bin``
    仅为签名兼容保留（已无 bwrap）。
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
