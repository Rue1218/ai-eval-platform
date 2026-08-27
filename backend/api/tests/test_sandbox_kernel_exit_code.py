"""回归测试：沙箱命令非零退出码归 VALIDATION 并携带截断摘要。

背景（生产探针实测）：bash 写 /etc 只读目录被拒时模型只见
"操作失败（INTERNAL）"——退出码分支此前归 INTERNAL，api 侧 hint 过滤后
模型无法得知具体原因（permission denied），只能盲目重试。
修复后归 VALIDATION，摘要（"命令执行失败（退出码 1）：..."）可到达模型。
"""

import io
from unittest.mock import patch

import pytest
from shared.sandbox_kernel import SandboxError, run_sandboxed


class _FakeProc:
    """模拟 subprocess.Popen：固定 stdout 行与退出码。"""

    def __init__(self, lines: list[str], returncode: int) -> None:
        self.pid = 9999
        self.returncode = returncode
        self.stdout = io.StringIO("\n".join(lines) + "\n")

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        return self.returncode


def _run(lines: list[str], returncode: int) -> str:
    fake = _FakeProc(lines, returncode)
    with patch("shared.sandbox_kernel.subprocess.Popen", return_value=fake):
        return run_sandboxed(
            "echo x > /etc/t.txt",
            sandbox_dir="/data/workspaces/session-1",
            timeout_s=5.0,
        )


def test_nonzero_exit_code_maps_to_validation_with_snippet() -> None:
    """非零退出码归 VALIDATION，且 message 携带退出码与 stderr 摘要（模型可迭代）。"""
    with pytest.raises(SandboxError) as excinfo:
        _run(["sh: 1: cannot create /etc/t.txt: Permission denied"], returncode=1)
    assert excinfo.value.code == "VALIDATION"
    assert "退出码 1" in excinfo.value.message
    assert "Permission denied" in excinfo.value.message


def test_zero_exit_code_returns_output() -> None:
    """退出码 0 正常返回 stdout。"""
    output = _run(["hello-kernel"], returncode=0)
    assert output == "hello-kernel"


def test_zero_exit_code_empty_output_fallback() -> None:
    """退出码 0 且无输出时返回占位文案。"""
    output = _run([], returncode=0)
    assert output == "（无输出）"
