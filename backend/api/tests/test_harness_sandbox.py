"""bwrap 沙箱集成测试（真实沙箱环境，M5 阶段 3，EX-6）。

覆盖：正常执行、会话目录隔离、系统目录只读、敏感路径遮蔽、超时整树清理、
内存超限、无网络。宿主机无 bwrap / 被 seccomp 拦截时自动跳过（不假成功）。
"""

import os
import tempfile
import time

import pytest

from app.errors import AppError, ErrorCode
from app.harness.execution.sandbox import SandboxLimits, probe_sandbox, run_sandboxed

pytestmark = pytest.mark.skipif(
    not probe_sandbox(),
    reason="bwrap 不可用（缺失或 userns/seccomp 拦截），跳过沙箱集成测试",
)

_LIMITS = SandboxLimits(memory_kb=262144, nproc=32, cpu_s=10)


def _run(cmd: str, *, timeout_s: float = 5.0, sandbox_dir: str | None = None) -> str:
    """在真实沙箱内执行命令（固定挂载点 /work）。"""
    with tempfile.TemporaryDirectory() as root:
        target = sandbox_dir or root
        return run_sandboxed(cmd, sandbox_dir=target, timeout_s=timeout_s, limits=_LIMITS)


def test_sandbox_echo_and_cwd() -> None:
    """正常执行：输出命令结果，cwd 为沙箱工作区挂载点。"""
    output = _run("echo hello; pwd")
    assert "hello" in output
    assert "/work" in output


def test_sandbox_workspace_writable() -> None:
    """会话工作区可写：文件创建后跨命令可见（同一宿主机目录）。"""
    with tempfile.TemporaryDirectory() as root:
        run_sandboxed("echo data > f.txt", sandbox_dir=root, timeout_s=5.0, limits=_LIMITS)
        assert os.path.exists(os.path.join(root, "f.txt"))
        output = run_sandboxed("cat f.txt", sandbox_dir=root, timeout_s=5.0, limits=_LIMITS)
        assert output == "data"


def test_sandbox_system_dirs_readonly() -> None:
    """系统目录只读：/usr 不可写（沙箱内唯一可写面为工作区）。"""
    with pytest.raises(AppError) as error:
        _run("touch /usr/x.txt")
    assert error.value.code == ErrorCode.INTERNAL


def test_sandbox_sensitive_paths_shielded() -> None:
    """敏感路径遮蔽：/data（其他会话工作区/备份）、/run/config（.env）、/app 源码均不可见。"""
    # 每个探测后接 true，避免最后一个失败命令的退出码污染整体结果
    output = _run("ls /data 2>&1 || true; ls /run/config 2>&1 || true; ls /app 2>&1 || true")
    assert "No such file or directory" in output
    assert "total" not in output


def test_sandbox_other_session_workspace_hidden() -> None:
    """会话目录隔离：沙箱内仅当前工作区可见，其他会话目录不存在。"""
    with tempfile.TemporaryDirectory() as root:
        other = os.path.join(root, "other-session")
        os.makedirs(other)
        with open(os.path.join(other, "secret.txt"), "w", encoding="utf-8") as handle:
            handle.write("top-secret")
        # 沙箱仅挂载当前工作区（root/current）；other-session 不可见
        current = os.path.join(root, "current")
        os.makedirs(current)
        output = run_sandboxed(
            "ls .. 2>&1", sandbox_dir=current, timeout_s=5.0, limits=_LIMITS
        )
        assert "other-session" not in output


def test_sandbox_timeout_kills_process_tree() -> None:
    """超时：wall-clock 超时抛 AppError(TIMEOUT)，进程树被清理。"""
    with pytest.raises(AppError) as error:
        _run("sleep 5", timeout_s=1.0)
    assert error.value.code == ErrorCode.TIMEOUT


def test_sandbox_memory_limit_enforced() -> None:
    """内存超限：分配超 256MB 虚拟内存的命令失败（非零退出码）。"""
    with pytest.raises(AppError) as error:
        _run("python3 -c 'a=[0]*10**8'")
    assert error.value.code == ErrorCode.INTERNAL


def test_sandbox_no_network() -> None:
    """无网络：--unshare-net 下外部连接失败（即使 curl 二进制存在）。"""
    with pytest.raises(AppError) as error:
        _run("curl -s --connect-timeout 2 http://example.com")
    assert error.value.code == ErrorCode.INTERNAL


def test_sandbox_fork_bomb_blocked() -> None:
    """fork 炸弹受限：进程数上限（ulimit -u）+ 超时兜底，不拖垮宿主。"""
    started = time.monotonic()
    try:
        _run(":(){ :|:& };:", timeout_s=3.0)
    except AppError:
        return  # 超时或命令失败均视为受限
    # 未抛错时也必须快速返回（fork 被 ulimit -u 32 拦截），证明未无限派生进程
    assert time.monotonic() - started < 3.0
