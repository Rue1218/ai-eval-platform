"""容器内直跑内核的 argv / 清理 / 取消测试，以及需要 Linux 命名空间的真实验证。"""

import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import shared.sandbox_kernel as kernel


class _Process:
    """受控 Popen 替身：运行中 wait 抛 TimeoutExpired，被 killpg 置码后回收。"""

    def __init__(self, returncode=0):
        self.pid = 10001
        self.returncode = returncode
        self.stdout = io.StringIO("hello\n")

    def poll(self):
        """暴露预设退出状态。"""
        return self.returncode

    def wait(self, timeout=None):
        """运行中等待模拟真实 TimeoutExpired。"""
        if self.returncode is None:
            raise subprocess.TimeoutExpired("unshare", timeout)
        return self.returncode


def test_normalize_mode():
    """isolated/network 直通；旧文件效果档位映射 isolated；未知值 fail-closed。"""
    assert kernel.normalize_mode("isolated") == "isolated"
    assert kernel.normalize_mode("network") == "network"
    assert kernel.normalize_mode("workspace-write") == "isolated"
    assert kernel.normalize_mode("read-only") == "isolated"
    with pytest.raises(kernel.SandboxError):
        kernel.normalize_mode("nope")


def test_build_exec_argv_modes():
    """isolated 直接 unshare 断网；network 走受信启动器建 netns/veth 并阻断内网。"""
    limits = kernel.SandboxLimits(memory_kb=1024, nproc=8, cpu_s=3)
    iso = kernel.build_exec_argv(cmd="echo hi", mode="isolated", limits=limits)
    net = kernel.build_exec_argv(cmd="echo hi", mode="network", limits=limits)
    # isolated：unshare 断网 + 私有 pidns；命令只作 $1
    assert iso[0] == "unshare" and "--net" in iso
    assert "--pid" in iso and "--fork" in iso and "--mount-proc" in iso
    assert iso[-1] == "echo hi"
    assert "echo hi" not in iso[iso.index("-c") + 1]
    assert "ulimit -v 1024" in iso[iso.index("-c") + 1]
    # network：受信启动器（位置参数传命令，绝不拼进脚本）
    assert net[0] == "bash" and net[1] == "-c"
    script = net[2]
    assert "sandbox-network" in net and "echo hi" in net
    assert "echo hi" not in script
    assert "ip netns add" in script and "MASQUERADE" in script
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert cidr in script  # 内网阻断
    # ulimit 值以位置参数传入（mem_kb/nproc/cpu_s）
    assert "ulimit -v $mem_kb" in script
    assert net[5:8] == ["1024", "8", "3"]


@pytest.mark.parametrize("reason", ["success", "cancel", "timeout", "nonzero"])
def test_kernel_control_paths(monkeypatch, reason):
    """所有退出路径都给出 process_exited 证据，且命令环境不含内部令牌。"""
    control = kernel.SandboxExecutionControl()
    process = _Process(0 if reason == "success" else 1 if reason == "nonzero" else None)

    def spawn(argv, **kwargs):
        """校验新会话、最小环境，并在取消场景下于派发后置取消。"""
        assert kwargs["start_new_session"] is True
        assert "RUNNER_INTERNAL_TOKEN" not in (kwargs.get("env") or {})
        if reason == "cancel":
            control.cancel_event.set()
        return process

    monkeypatch.setattr(kernel.subprocess, "Popen", spawn)
    monkeypatch.setattr(kernel.os, "killpg", lambda *a: setattr(process, "returncode", -9), raising=False)
    if reason == "success":
        assert kernel.run_sandboxed("echo hi", sandbox_dir="scope", timeout_s=1, control=control) == "hello"
        assert control.process_tree_terminated and control.termination_evidence == "process_exited"
        return
    with pytest.raises(kernel.SandboxError) as error:
        kernel.run_sandboxed("echo hi", sandbox_dir="scope",
                             timeout_s=0.01 if reason == "timeout" else 1, control=control)
    assert error.value.code == {"cancel": "CANCELLED", "timeout": "TIMEOUT", "nonzero": "VALIDATION"}[reason]
    assert control.process_tree_terminated and control.termination_evidence == "process_exited"


def test_cancel_before_spawn(monkeypatch):
    """取消先到不得发起任何子进程。"""
    monkeypatch.setattr(kernel.subprocess, "Popen", lambda *a, **k: pytest.fail("不应启动"))
    control = kernel.SandboxExecutionControl()
    control.cancel_event.set()
    with pytest.raises(kernel.SandboxError, match="启动前取消"):
        kernel.run_sandboxed("echo hi", sandbox_dir="scope", timeout_s=1, control=control)
    assert control.process_tree_terminated and not control.started


def test_engine_unavailable_is_fail_closed(monkeypatch):
    """unshare 缺失/被拒 → VALIDATION，且不得报告已启动。"""
    def boom(*a, **k):
        raise FileNotFoundError("unshare")
    monkeypatch.setattr(kernel.subprocess, "Popen", boom)
    control = kernel.SandboxExecutionControl()
    with pytest.raises(kernel.SandboxError, match="沙箱引擎不可用"):
        kernel.run_sandboxed("echo hi", sandbox_dir="scope", timeout_s=1, control=control)
    assert not control.started and control.termination_evidence == "not_started"


@pytest.mark.skipif(sys.platform != "linux" or not os.environ.get("RUNNER_TEST_UNSHARE"),
                    reason="需要 Linux unshare 命名空间（设 RUNNER_TEST_UNSHARE=1）")
def test_linux_cancel_kills_setsid_descendants(tmp_path):
    """真实 setsid 后代持续写文件；取消后确认整树停止（pidns 清空）且写入停止。"""
    control = kernel.SandboxExecutionControl()
    command = "setsid bash -c 'while :; do echo x >> heartbeat; sleep 0.05; done' & wait"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(kernel.run_sandboxed, command, sandbox_dir=str(tmp_path),
                             timeout_s=8, control=control)
        try:
            deadline = time.monotonic() + 4
            while not (tmp_path / "heartbeat").exists() and time.monotonic() < deadline:
                if future.done():
                    future.result()
                time.sleep(0.02)
            assert (tmp_path / "heartbeat").exists()
        finally:
            control.cancel_event.set()
        with pytest.raises(kernel.SandboxError) as error:
            future.result(timeout=6)
    assert error.value.code == "CANCELLED"
    assert control.process_tree_terminated and control.termination_evidence == "process_exited"
    size = (tmp_path / "heartbeat").stat().st_size
    time.sleep(0.2)
    assert (tmp_path / "heartbeat").stat().st_size == size
