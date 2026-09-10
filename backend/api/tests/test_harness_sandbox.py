"""容器内直跑沙箱内核集成测试（真实命名空间环境）。

验证 ``shared.sandbox_kernel``（api 与 runner 共用内核）：正常执行、cwd=工作区、
工作区可写、超时整树清理、内存/进程限额、isolated 断网。文件边界由 runner
容器挂载承担（不在本内核单测范围）。宿主无 unshare / 被 seccomp 拦截时自动
跳过（不假成功）。
"""

import os
import tempfile
import time

import pytest
from shared.sandbox_kernel import SandboxError, SandboxLimits, probe_sandbox, run_sandboxed

pytestmark = pytest.mark.skipif(
    not probe_sandbox(),
    reason="unshare 命名空间不可用（缺失或被 seccomp 拦截），跳过沙箱集成测试",
)

_LIMITS = SandboxLimits(memory_kb=262144, nproc=32, cpu_s=10)


def _run(cmd: str, *, timeout_s: float = 5.0, sandbox_dir: str | None = None) -> str:
    """在真实（isolated）沙箱内执行命令，cwd 为工作区目录。"""
    with tempfile.TemporaryDirectory() as root:
        target = sandbox_dir or root
        return run_sandboxed(cmd, sandbox_dir=target, timeout_s=timeout_s, limits=_LIMITS)


def test_sandbox_echo_and_cwd() -> None:
    """正常执行：输出命令结果，cwd 为传入的工作区目录。"""
    with tempfile.TemporaryDirectory() as root:
        output = run_sandboxed("echo hello; pwd", sandbox_dir=root, timeout_s=5.0, limits=_LIMITS)
        assert "hello" in output
        assert os.path.realpath(root) in output


def test_sandbox_workspace_writable() -> None:
    """工作区可写：文件创建后跨命令可见（同一宿主机目录）。"""
    with tempfile.TemporaryDirectory() as root:
        run_sandboxed("echo data > f.txt", sandbox_dir=root, timeout_s=5.0, limits=_LIMITS)
        assert os.path.exists(os.path.join(root, "f.txt"))
        output = run_sandboxed("cat f.txt", sandbox_dir=root, timeout_s=5.0, limits=_LIMITS)
        assert output == "data"


def test_sandbox_timeout_kills_process_tree() -> None:
    """超时：wall-clock 超时抛 SandboxError(TIMEOUT)，进程树被清理。"""
    with pytest.raises(SandboxError) as error:
        _run("sleep 5", timeout_s=1.0)
    assert error.value.code == "TIMEOUT"


def test_sandbox_memory_limit_enforced() -> None:
    """内存超限：分配超 256MB 虚拟内存的命令非零退出（归 VALIDATION）。"""
    with pytest.raises(SandboxError) as error:
        _run("python3 -c 'a=[0]*10**8'")
    assert error.value.code == "VALIDATION"


def test_sandbox_no_network_isolated() -> None:
    """isolated 模式断网：netns 内外部连接失败（即使有网络二进制）。"""
    with pytest.raises(SandboxError) as error:
        _run("python3 -c \"import socket; socket.create_connection(('1.1.1.1', 80), 2)\"")
    assert error.value.code == "VALIDATION"


def test_sandbox_fork_bomb_blocked() -> None:
    """fork 炸弹受限：进程数上限（ulimit -u）+ 超时兜底，不拖垮宿主。"""
    started = time.monotonic()
    try:
        _run(":(){ :|:& };:", timeout_s=3.0)
    except SandboxError:
        return  # 超时或命令失败均视为受限
    # 未抛错时也必须快速返回（fork 被 ulimit -u 32 拦截），证明未无限派生进程
    assert time.monotonic() - started < 5.0
