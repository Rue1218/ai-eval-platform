"""Harness 执行层：bwrap 进程级沙箱内核（M5 阶段 3，EX-6）。

- ``run_sandboxed`` 每次调用构造一次性 bwrap 沙箱（秒级启动，无常驻进程）：
  无网络（--unshare-net）、会话工作区唯一可写（其余只读 bind）、
  资源受限（ulimit 内存/进程数/CPU）、超时整树清理（--die-with-parent +
  killpg）；
- ``probe_sandbox`` 冒烟探测 bwrap 可用性（懒加载 + 进程内缓存）；探测失败
  或引擎不可用时调用方必须 fail-closed（禁止降级为裸 subprocess）；
- 日志遵循红线：只打工具名/耗时/退出码/错误码，不打印命令细节与密钥。
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from dataclasses import dataclass

from app.errors import AppError, ErrorCode

logger = logging.getLogger("ai-eval.harness.sandbox")

# 沙箱内工作区挂载点（固定路径，避免被 --tmpfs /tmp 遮蔽；模型相对路径落在此处）
_SANDBOX_MOUNT = "/work"

# 冒烟探测结果缓存（None=未探测；True/False=已探测）
_PROBE_RESULT: bool | None = None


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """沙箱资源限制（ulimit 注入 + 外层墙钟超时兜底）。"""

    memory_kb: int = 262144  # 虚拟内存上限（KB），默认 256MB
    nproc: int = 32  # 最大进程数（防 fork 炸弹）
    cpu_s: int = 10  # CPU 时间上限（秒）


def _build_bwrap_argv(
    *,
    bwrap_bin: str,
    sandbox_dir: str,
    cmd: str,
    limits: SandboxLimits,
) -> list[str]:
    """构造 bwrap 命令行（工作区唯一可写 + 无网络 + ulimit 限制）。

    最小 bind 而非 ``--ro-bind / /``：不暴露 ``/app`` 源码、``/run/config/.env``
    （供应商 Key，已被 ``--tmpfs /run`` 遮蔽）、``/data`` 下其他会话工作区与
    备份文件；ulimit 由 bash 设置后 ``exec`` 继承（RLIMIT 在 exec 后保留）。
    """
    argv = [
        bwrap_bin,
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/sbin", "/sbin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/usr/local", "/usr/local",
        "--ro-bind", "/etc", "/etc",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        "--bind", sandbox_dir, _SANDBOX_MOUNT,
        "--clearenv",
        "--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--setenv", "HOME", "/tmp",
        "--chdir", _SANDBOX_MOUNT,
        "--",
        "bash", "-c",
        f"ulimit -v {limits.memory_kb}; ulimit -u {limits.nproc}; ulimit -t {limits.cpu_s}; exec bash -c \"$1\"",
        "bash", cmd,
    ]
    return argv


def run_sandboxed(
    cmd: str,
    *,
    sandbox_dir: str,
    timeout_s: float,
    limits: SandboxLimits | None = None,
    bwrap_bin: str = "/usr/bin/bwrap",
    max_output_chars: int = 20000,
) -> str:
    """在一次性 bwrap 沙箱内执行命令，返回 stdout；失败归一为 AppError。

    - 超时：wall-clock 超时后 ``killpg(SIGKILL)`` 整树清理（配合
      ``--die-with-parent`` 回收沙箱内全部进程），抛 ``AppError(TIMEOUT)``；
    - 非零退出码：抛 ``AppError(INTERNAL)``，附截断的 stderr 摘要（工具反馈
      语义，供模型迭代；非未处理异常原文）；
    - fail-closed：bwrap 缺失/被 seccomp 拦截导致启动失败即抛
      ``AppError(VALIDATION, "沙箱引擎不可用")``，禁止降级为裸 subprocess。
    """
    if not cmd.strip():
        raise AppError(ErrorCode.VALIDATION, "bash 命令为空")
    limits = limits or SandboxLimits()
    argv = _build_bwrap_argv(
        bwrap_bin=bwrap_bin, sandbox_dir=sandbox_dir, cmd=cmd, limits=limits
    )
    # 记录脱敏摘要（命令长度与摘要，不打印命令原文/密钥）
    logger.info(
        "bash 沙箱执行 len=%d dir=%s timeout=%s",
        len(cmd), sandbox_dir, timeout_s,
    )
    try:
        started = subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        # bwrap 二进制缺失：fail-closed，禁止降级为裸 subprocess
        raise AppError(ErrorCode.VALIDATION, "沙箱引擎不可用") from exc
    except OSError as exc:
        # userns/seccomp 拒绝等启动失败：fail-closed
        raise AppError(ErrorCode.VALIDATION, "沙箱引擎不可用") from exc
    try:
        output, _ = started.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # 超时：整进程组强杀，防孤儿进程残留
        try:
            os.killpg(started.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        started.communicate()
        raise AppError(ErrorCode.TIMEOUT, "命令执行超时") from None
    stdout = (output or "")[:max_output_chars]
    if started.returncode != 0:
        # 附截断 stderr 摘要便于模型迭代；退出码归位 INTERNAL
        detail = stdout.strip().splitlines()
        snippet = detail[-1][:500] if detail else ""
        raise AppError(ErrorCode.INTERNAL, f"命令执行失败（退出码 {started.returncode}）：{snippet}")
    return stdout.strip() or "（无输出）"


def probe_sandbox(bwrap_bin: str = "/usr/bin/bwrap", timeout_s: float = 5.0) -> bool:
    """冒烟探测 bwrap 可用性（userns/seccomp 放行）；结果进程内缓存。

    用最小参数组合验证 ``--unshare-user`` + ``--ro-bind`` 可执行；被 seccomp
    拦截/二进制缺失返回 False，调用方据此 fail-closed。
    """
    global _PROBE_RESULT
    if _PROBE_RESULT is not None:
        return _PROBE_RESULT
    try:
        result = subprocess.run(
            [
                bwrap_bin,
                "--unshare-user",
                "--ro-bind", "/", "/",
                "--die-with-parent",
                "--", "true",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
        _PROBE_RESULT = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _PROBE_RESULT = False
    logger.info("bwrap 冒烟探测 result=%s", _PROBE_RESULT)
    return _PROBE_RESULT


def reset_probe_cache() -> None:
    """清空冒烟探测缓存（测试用）。"""
    global _PROBE_RESULT
    _PROBE_RESULT = None
