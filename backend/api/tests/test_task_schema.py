"""任务确认卡 Pydantic 契约测试。"""

import pytest
from pydantic import ValidationError

from app.schemas import TaskCreate


def test_task_create_accepts_frontend_config_wrapper():
    """已完成前端的 config 包装仍应转换为冻结的 TaskSpec 快照。"""
    task = TaskCreate.model_validate(
        {
            "kind": "benchmark",
            "session_id": "session-1",
            "config": {
                "kind": "benchmark",
                "profile_ids": ["profile-1"],
                "dataset_id": "dataset-1",
                "run": {"sample_size": 20, "concurrency": 4, "timeout_s": 60},
                "with_stress": False,
            },
        }
    )

    assert task.session_id == "session-1"
    assert task.profile_ids == ["profile-1"]
    assert task.snapshot()["dataset_id"] == "dataset-1"
    assert "session_id" not in task.snapshot()


def test_benchmark_rejects_missing_profile_or_dataset():
    """确认卡缺少 Benchmark 必填资产时必须在入队前失败。"""
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(
            {
                "kind": "benchmark",
                "profile_ids": [],
                "run": {"sample_size": 20},
            }
        )


def test_stress_requires_successful_parent_reference_field():
    """手动压测不能脱离质量父任务单独创建。"""
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(
            {
                "kind": "stress",
                "stress": {"env": "test", "qps": 10, "duration_s": 60},
            }
        )
