"""部署准入锁拒绝竞态提交，异常和正常结束均释放共享锁。"""

import sys
from types import SimpleNamespace

import pytest

from app.agent import deploy_guard
from app.errors import AppError


@pytest.mark.parametrize("blocked,body_error", [(False, False), (False, True), (True, False)])
def test_admission_lock_lifetime(tmp_path, monkeypatch, blocked, body_error):
    """用系统调用替身在 Windows 也验证共享锁、非阻塞拒绝与 finally 释放。"""
    operations = []

    def flock(handle, mode):
        """记录真实打开的句柄，模拟部署排他锁占用。"""
        assert not handle.closed
        operations.append(mode)
        if blocked:
            raise BlockingIOError()

    monkeypatch.setattr(deploy_guard, "os", SimpleNamespace(name="posix"))
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(flock=flock, LOCK_SH=1, LOCK_NB=4, LOCK_UN=8))
    if blocked:
        with pytest.raises(AppError, match="服务正在部署"):
            with deploy_guard.turn_admission(str(tmp_path)):
                pytest.fail("部署期间不能提交新回合")
        assert operations == [5]
    elif body_error:
        with pytest.raises(RuntimeError):
            with deploy_guard.turn_admission(str(tmp_path)):
                raise RuntimeError("输入事务失败")
        assert operations == [5, 8]
    else:
        with deploy_guard.turn_admission(str(tmp_path)):
            assert operations == [5]
        assert operations == [5, 8]
    assert (tmp_path / ".agent-deploy.lock").exists()


def test_real_linux_flock_blocks_new_turn_until_deploy_releases(tmp_path):
    """Linux 上真实独立文件描述符验证排他锁与共享准入锁互斥。"""
    fcntl = pytest.importorskip("fcntl")
    path = tmp_path / ".agent-deploy.lock"
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(AppError):
            with deploy_guard.turn_admission(str(tmp_path)):
                pytest.fail("不应绕过部署锁")
        fcntl.flock(handle, fcntl.LOCK_UN)
        with deploy_guard.turn_admission(str(tmp_path)):
            pass
