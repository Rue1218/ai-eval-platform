"""Linux Compose 部署与新回合提交共用数据目录文件锁，活跃回合不持锁。"""

import os
from contextlib import contextmanager
from pathlib import Path

from app.errors import AppError, ErrorCode


@contextmanager
def turn_admission(data_dir: str):
    """提交事务持共享锁；部署持排他锁直到切换完成，拒绝竞态中的新回合。

    生产部署仅支持 Linux Compose；Windows 本地开发不使用该部署脚本。
    锁文件始终保留，禁止 unlink 导致新旧进程锁住不同 inode。
    """
    if os.name == "nt":
        yield
        return
    import fcntl

    path = Path(data_dir) / ".agent-deploy.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a")
    except OSError:
        raise AppError(ErrorCode.CONCURRENCY, "部署状态不可用，请稍后重试") from None
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            raise AppError(ErrorCode.CONCURRENCY, "服务正在部署，当前回合可继续，请稍后发起新回合") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
