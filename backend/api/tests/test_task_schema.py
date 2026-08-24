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


def test_run_config_accepts_judge_profile_id():
    """RunConfig 支持 LLM 裁判字段，兼容双模型对比测评任务。"""
    task = TaskCreate.model_validate(
        {
            "kind": "benchmark",
            "profile_ids": ["profile-1", "profile-2"],
            "dataset_id": "dataset-1",
            "run": {
                "sample_size": 20,
                "use_judge": True,
                "judge_profile_id": "profile-judge",
            },
        }
    )
    assert task.run is not None
    assert task.run.use_judge is True
    assert task.run.judge_profile_id == "profile-judge"


def test_run_config_use_judge_requires_judge_profile():
    """use_judge=True 时必须提供裁判协议档，否则校验失败。"""
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(
            {
                "kind": "benchmark",
                "profile_ids": ["profile-1", "profile-2"],
                "dataset_id": "dataset-1",
                "run": {"sample_size": 20, "use_judge": True},
            }
        )


def test_run_config_judge_profile_ignored_without_use_judge():
    """use_judge=False 时携带 judge_profile_id 不报错（向后兼容）。"""
    task = TaskCreate.model_validate(
        {
            "kind": "benchmark",
            "profile_ids": ["profile-1"],
            "dataset_id": "dataset-1",
            "run": {"sample_size": 20, "judge_profile_id": "profile-judge"},
        }
    )
    assert task.run is not None
    assert task.run.use_judge is False
