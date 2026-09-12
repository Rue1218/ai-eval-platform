"""Worker 侧共享模型单一事实源回归测试。

worker 的 models.py 必须是 backend/shared/models.py 的 re-export；
一旦有人误改回独立副本，本测试立刻失败。
"""

from shared.models import Base as SharedBase

from app.models import Base as WorkerBase


def test_worker_models_share_single_source():
    """worker 与共享包必须是同一个 Base（同一份元数据）。"""
    assert WorkerBase is SharedBase
