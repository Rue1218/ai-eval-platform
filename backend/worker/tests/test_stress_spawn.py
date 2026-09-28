"""样本量夹紧与停用压测后的派生门禁。"""

import pytest
from app.models import Task
from app.sampling import SAMPLE_SIZE_CAP, clamp_sample_size
from app.stress_spawn import maybe_spawn_stress


def test_clamp_sample_size_caps_at_1000():
    assert clamp_sample_size(5000, 8000) == SAMPLE_SIZE_CAP
    assert clamp_sample_size(20, 8) == 8
    assert clamp_sample_size(None, 2000) == SAMPLE_SIZE_CAP
    assert clamp_sample_size(-1, 50) == 50
    assert clamp_sample_size(True, 50) == 50


@pytest.mark.parametrize("kind", ["benchmark", "rag"])
def test_retired_quality_task_does_not_spawn_stress(kind):
    """旧质量任务即使成功且带派生参数，也不能创建新压测。"""
    parent = Task(id="parent", kind=kind, status="succeeded", config={
        "with_stress": True,
        "stress": {"env": "prod", "qps": 10, "duration_s": 30},
    })

    class _Db:
        """任何数据库写入都代表停用门禁失效。"""

        def __getattr__(self, name):
            raise AssertionError(f"unexpected db access: {name}")

    assert maybe_spawn_stress(_Db(), parent) is None
