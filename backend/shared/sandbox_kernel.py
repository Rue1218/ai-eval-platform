"""bwrap 进程级沙箱内核（api 与独立 sandbox runner 共用，P4-2）。

从 api 的 ``app.harness.execution.sandbox`` 迁移，**不依赖任何 ``app.*``
模块**：api 侧沙箱模块包装为远程客户端，runner 服务直接调用本内核。

- ``run_sandboxed`` 每次调用构造一次性 bwrap 沙箱（秒级启动，无常驻进程）：
  无网络（--unshare-net）、会话工作区唯一可写（其余只读 bind）、资源受限
  （ulimit 内存/进程数/CPU）、超时整树清理（--die-with-parent + killpg）；
- ``probe_sandbox`` 冒烟探测 bwrap 可用性（懒加载 + 进程内缓存）；探测失败
  或引擎不可用时调用方必须 fail-closed（禁止降级为裸 subprocess）；
- 错误以 ``SandboxError(code, message)`` 表达（code ∈ TIMEOUT/VALIDATION/
  INTERNAL），由调用方映射到各自错误模型。
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("ai-eval.sandbox_kernel")

# 沙箱内工作区挂载点（固定路径，避免被 --tmpfs /tmp 遮蔽；模型相对路径落在此处）
_SANDBOX_MOUNT = "/work"

# 沙箱档位（F2/G4，《工作区与沙箱设计方案》§6）：只声明文件效果——
# "read-only"（scope 只读 bind）与 "workspace-write"（scope 可写 bind）。
# "none"（bash 不可达）由 api 侧 sandbox_engine=off fail-closed 承担，不进 runner。
SANDBOX_MODES: frozenset[str] = frozenset({"read-only", "workspace-write"})


class SandboxError(Exception):
    """沙箱执行错误（code ∈ TIMEOUT/VALIDATION/INTERNAL）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """沙箱资源限制（ulimit 注入 + 外层墙钟超时兜底）。"""

    memory_kb: int = 262144  # 虚拟内存上限（KB），默认 256MB
    nproc: int = 32  # 最大进程数（防 fork 炸弹）
    cpu_s: int = 10  # CPU 时间上限（秒）


def resolve_workspace_path(path: str, root: str) -> str:
    """校验工作区路径位于 ``root`` 前缀内，返回 canonical 绝对路径供 bind。

    F2/G4（MAJ-5）：替代旧「root 直接子目录 + 会话标识」校验（runner 侧不再
    依赖会话形态）——接受嵌套 scope（``{root}/<ws>/<folder>/…``），逐段
    realpath 后重验前缀（符号链接逃逸拒绝），仍拒相对路径与 ``..`` 段；
    bind 使用返回值（realpath 最终路径），消除 resolve→bind 换链窗口。
    越界/非法一律抛 ``SandboxError(VALIDATION)``（fail-closed）。
    """
    if not path or not root:
        raise SandboxError("VALIDATION", "非法工作区路径")
    root_real = os.path.realpath(root)
    abs_path = os.path.abspath(path)
    if abs_path == root_real or not abs_path.startswith(root_real + os.sep):
        raise SandboxError("VALIDATION", "工作区路径越出根目录")
    rel = os.path.relpath(abs_path, root_real)
    if rel == "." or rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        raise SandboxError("VALIDATION", "工作区路径非法")
    # 逐段 realpath 重验：任一中间段为指向前缀外的符号链接即拒绝
    current = root_real
    for segment in rel.split(os.sep):
        current = os.path.realpath(os.path.join(current, segment))
        if current != root_real and not current.startswith(root_real + os.sep):
            raise SandboxError("VALIDATION", "工作区路径含越界符号链接")
    return current


def _build_bwrap_argv(
    *,
    bwrap_bin: str,
    sandbox_dir: str,
    cmd: str,
    limits: SandboxLimits,
    mode: str = "workspace-write",
) -> list[str]:
    """构造 bwrap 命令行（按档位绑定 scope + 无网络 + ulimit 限制）。

    F2/G4：scope 按 ``mode`` 组装 bind——"workspace-write" 可写（--bind）、
    "read-only" 只读（--ro-bind）；调用方须先行校验 mode ∈ SANDBOX_MODES。
    最小 bind 而非 ``--ro-bind / /``：不暴露源码、``/run/config/.env``
    （供应商 Key，已被 ``--tmpfs /run`` 遮蔽）、其他会话工作区与备份文件；
    ulimit 由 bash 设置后 ``exec`` 继承（RLIMIT 在 exec 后保留）。
    """
    argv = [
        bwrap_bin,
        "--unshare-user",
        # PoC 勘误（G2，2026-09-07，见《…G2G3实施评估与PoC结论.md》）：非特权
        # 容器下 `--unshare-pid` + `--proc` 组合 mount proc EPERM（bwrap 0.12/
        # Docker 26 实测），故移除私有 PID ns——`/proc` 呈容器 pid ns 级视图
        # （仅 runner 容器自身进程，无宿主/跨容器进程；沙箱 userns root 对
        # 容器内他进程无 ptrace 权限，防护语义保持）。bwrap ≥1.0.4 可复测。
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
        ("--bind" if mode == "workspace-write" else "--ro-bind"),
        sandbox_dir, _SANDBOX_MOUNT,
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
    mode: str = "workspace-write",
    timeout_s: float,
    limits: SandboxLimits | None = None,
    bwrap_bin: str = "/usr/bin/bwrap",
    max_output_chars: int = 20000,
    on_output: Callable[[str], None] | None = None,
) -> str:
    """在一次性 bwrap 沙箱内按档位执行命令，返回 stdout；失败抛 SandboxError。

    - ``mode`` ∈ SANDBOX_MODES（文件效果档位，F2/G4）：workspace-write →
      scope 可写 bind；read-only → scope 只读 bind；未知档位 fail-closed；
    - 超时：wall-clock 超时后 ``killpg(SIGKILL)`` 整树清理（配合
      ``--die-with-parent`` 回收沙箱内全部进程），抛 ``SandboxError(TIMEOUT)``；
    - 非零退出码：抛 ``SandboxError(INTERNAL)``，附截断的 stderr 摘要；
    - fail-closed：bwrap 缺失/被 seccomp 拦截导致启动失败即抛
      ``SandboxError(VALIDATION, "沙箱引擎不可用")``，禁止降级为裸 subprocess。
    """
    if not cmd.strip():
        raise SandboxError("VALIDATION", "bash 命令为空")
    if mode not in SANDBOX_MODES:
        raise SandboxError("VALIDATION", f"未知沙箱档位：{mode}")
    limits = limits or SandboxLimits()
    argv = _build_bwrap_argv(
        bwrap_bin=bwrap_bin, sandbox_dir=sandbox_dir, cmd=cmd, limits=limits, mode=mode
    )
    # 记录脱敏摘要（命令长度与摘要，不打印命令原文/密钥）
    logger.info(
        "bash 沙箱执行 mode=%s len=%d dir=%s timeout=%s",
        mode, len(cmd), sandbox_dir, timeout_s,
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
        raise SandboxError("VALIDATION", "沙箱引擎不可用") from exc
    except OSError as exc:
        # userns/seccomp 拒绝等启动失败：fail-closed
        raise SandboxError("VALIDATION", "沙箱引擎不可用") from exc
    output_parts: list[str] = []
    output_chars = 0

    def drain_stdout() -> None:
        """逐行排空 stdout；即使超出展示上限仍持续读取以避免子进程阻塞。"""
        nonlocal output_chars
        stdout = started.stdout
        if stdout is None:
            return
        try:
            for chunk in iter(stdout.readline, ""):
                remaining = max_output_chars - output_chars
                if remaining <= 0:
                    continue
                safe_chunk = chunk[:remaining]
                if not safe_chunk:
                    continue
                output_parts.append(safe_chunk)
                output_chars += len(safe_chunk)
                if on_output is not None:
                    try:
                        on_output(safe_chunk)
                    except Exception:  # noqa: BLE001 —— 客户端断开不应影响沙箱清理
                        logger.info("bash 输出回调失败，继续执行并回收沙箱")
        finally:
            stdout.close()

    reader = threading.Thread(target=drain_stdout, name="sandbox-stdout", daemon=True)
    reader.start()
    try:
        started.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # 超时：整进程组强杀，防孤儿进程残留
        try:
            os.killpg(started.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        started.wait()
        reader.join(timeout=1.0)
        raise SandboxError("TIMEOUT", "命令执行超时") from None
    reader.join(timeout=1.0)
    stdout = "".join(output_parts)
    if started.returncode != 0:
        # 命令已在沙箱内成功启动，非零退出码属业务失败（如写只读目录被拒），
        # 归 VALIDATION 并把截断摘要送达模型（INTERNAL 会被 api 侧 hint 过滤
        # 成"操作失败"，模型无法得知具体原因而盲目重试）。
        detail = stdout.strip().splitlines()
        snippet = detail[-1][:500] if detail else ""
        raise SandboxError("VALIDATION", f"命令执行失败（退出码 {started.returncode}）：{snippet}")
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


_PROBE_RESULT: bool | None = None
