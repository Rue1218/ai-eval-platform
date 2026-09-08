"""可取消内核的确定性清理测试及需要 Linux 委派的真实整树验证。"""

import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import shared.sandbox_kernel as kernel


class _Process:
    """受控 Popen 替身，不启动宿主命令。"""

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
            raise subprocess.TimeoutExpired("bwrap", timeout)
        return self.returncode


@pytest.mark.parametrize("reason", ["success", "cancel", "timeout", "wait_error", "nonzero"])
@pytest.mark.parametrize("proven", [True, False])
def test_kernel_cleanup_all_exit_paths(monkeypatch, reason, proven):
    """所有退出路径都清理执行域，证明缺失时不能报告 cancelled 或 succeeded。"""
    control = kernel.SandboxExecutionControl()
    process = _Process(1 if reason == "nonzero" else 0 if reason == "success" else None)
    cleaned = []

    class Group:
        """模拟 cgroup 生命周期，记录是否按证据删除执行域。"""

        def __init__(self, root):
            assert root == "delegated"
            self.path = "delegated/execution"

        def wrap(self, argv):
            """仍校验模型命令经过原有 bwrap 安全参数。"""
            assert "--unshare-net" in argv and "--die-with-parent" in argv
            assert "--clearenv" in argv and "--ro-bind" in argv
            return argv

        def terminate(self, proc):
            """仅在模拟成功清理时提供证明。"""
            cleaned.append("terminate")
            if proven and proc.returncode is None:
                proc.returncode = -9
            return proven

        def close(self):
            """空执行域才能删除。"""
            cleaned.append("close")

    def spawn(argv, **kwargs):
        """取消在派发之后到达，不能误当作启动前取消。"""
        assert kwargs["start_new_session"] is True
        if reason == "cancel":
            control.cancel_event.set()
        return process

    monkeypatch.setattr(kernel, "_ExecutionCgroup", Group)
    monkeypatch.setattr(kernel.subprocess, "Popen", spawn)
    if reason == "wait_error":
        def broken_wait(timeout=None):
            """注入等待异常，检查 finally 不跳过清理。"""
            raise RuntimeError("wait failed")
        monkeypatch.setattr(process, "wait", broken_wait)
    try:
        result = kernel.run_sandboxed("echo hi", sandbox_dir="scope", timeout_s=0.01,
                                      control=control, cgroup_root="delegated")
    except kernel.SandboxError as exc:
        if not proven:
            assert exc.code == "OUTCOME_UNKNOWN"
        else:
            assert exc.code == {"cancel": "CANCELLED", "timeout": "TIMEOUT", "nonzero": "VALIDATION"}[reason]
    except RuntimeError:
        assert reason == "wait_error"
    else:
        assert reason == "success" and proven and result == "hello"
    assert cleaned == (["terminate", "close"] if proven else ["terminate"])
    assert control.process_tree_terminated is proven


def test_cancel_before_spawn_and_unconfigured_cgroup(monkeypatch):
    """取消先到和未配置委派都不能发起任何子进程。"""
    monkeypatch.setattr(kernel.subprocess, "Popen", lambda *a, **k: pytest.fail("不应启动"))
    control = kernel.SandboxExecutionControl()
    control.cancel_event.set()
    with pytest.raises(kernel.SandboxError, match="启动前取消"):
        kernel.run_sandboxed("echo hi", sandbox_dir="scope", timeout_s=1, control=control)
    assert control.process_tree_terminated and not control.started
    control = kernel.SandboxExecutionControl()
    with pytest.raises(kernel.SandboxError, match="cgroup"):
        kernel.run_sandboxed("echo hi", sandbox_dir="scope", timeout_s=1, control=control)
    assert control.termination_evidence == "not_started"


@pytest.mark.parametrize("populated", ["0", "1", "invalid"])
def test_cgroup_termination_requires_reap_and_empty_evidence(tmp_path, monkeypatch, populated):
    """kill 调用成功本身不足以证明结束，必须读取 populated=0。"""
    group = object.__new__(kernel._ExecutionCgroup)
    group.path = tmp_path
    (tmp_path / "cgroup.events").write_text(f"populated {populated}\n")
    monkeypatch.setattr(kernel.os, "killpg", lambda *a: None, raising=False)
    clock = iter([0, 0.01, 3])
    monkeypatch.setattr(kernel.time, "monotonic", lambda: next(clock))
    assert group.terminate(_Process()) is (populated == "0")
    assert (tmp_path / "cgroup.kill").read_text() == "1"


def test_trusted_launcher_attaches_before_bwrap(tmp_path):
    """模型命令仅是 bwrap 参数，不能插入可信启动器脚本。"""
    group = object.__new__(kernel._ExecutionCgroup)
    group.path = tmp_path
    command = 'echo "$SECRET"; touch /tmp/model-command'
    argv = group.wrap(["/usr/bin/bwrap", "--", "bash", "-c", command])
    assert "cgroup.procs" in argv[2] and 'exec "$@"' in argv[2]
    assert command not in argv[2] and argv[-1] == command


@pytest.mark.skipif(sys.platform != "linux" or not os.environ.get("RUNNER_TEST_CGROUP_ROOT"),
                    reason="需要 Linux bwrap 和 RUNNER_TEST_CGROUP_ROOT 可写 cgroup v2 委派")
def test_linux_cancel_kills_setsid_descendants(tmp_path):
    """真实 setsid 后代持续写文件；取消后确认执行域为空且写入停止。"""
    control = kernel.SandboxExecutionControl()
    command = "setsid bash -c 'while :; do echo x >> heartbeat; sleep 0.05; done' & wait"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(kernel.run_sandboxed, command, sandbox_dir=str(tmp_path),
                             timeout_s=8, control=control, cgroup_root=os.environ["RUNNER_TEST_CGROUP_ROOT"])
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
    assert control.process_tree_terminated and control.termination_evidence == "cgroup_empty"
    size = (tmp_path / "heartbeat").stat().st_size
    time.sleep(0.2)
    assert (tmp_path / "heartbeat").stat().st_size == size
