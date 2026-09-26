"""压测参数夹紧、白名单与报告映射回归。"""

from unittest.mock import Mock

import pytest
from app import stress
from app.models import ProtocolProfile, Setting, Task, TaskEvent
from app.stress import clamp_stress, host_allowed, metrics_from_status


def test_clamp_stress_respects_platform_caps() -> None:
    settings = {"max_qps": 50, "max_duration_s": 30}
    assert clamp_stress(500, 1800, settings) == (50, 30)
    assert clamp_stress(None, None, settings) == (10, 30)
    assert clamp_stress(True, True, settings) == (10, 30)


def test_host_allowed_empty_whitelist_blocks_prod() -> None:
    url = "https://api.example.com/v1/chat/completions"
    assert host_allowed(url, [], "test") is True
    assert host_allowed(url, [], "prod") is False
    assert host_allowed(url, [{"host": "api.example.com", "status": "active"}], "prod") is True
    assert host_allowed(url, [{"host": "other.com", "status": "active"}], "test") is False


def test_metrics_from_status_writes_series_and_aliases() -> None:
    status = {
        "status": "done",
        "qps": 9.5,
        "rt": 210.2,
        "p99_ms": 400,
        "error_rate": 0.01,
        "sla_met": True,
        "time_series": [
            {"ts": "2026-08-25T00:00:00Z", "qps": 8, "rt_ms": 180, "error_rate": 0},
            {"ts": "2026-08-25T00:00:01Z", "qps": 12, "rt_ms": 240, "error_rate": 0.02},
        ],
    }
    metrics = metrics_from_status(status, sla_p99_ms=500)
    assert metrics["qps"] == 9.5
    assert metrics["qps_peak"] == 12
    assert metrics["p99"] == 400
    assert metrics["sla_met"] is True
    assert len(metrics["time_series"]) == 2
    assert metrics["series"] == metrics["time_series"]


@pytest.mark.parametrize("approval", [
    {}, {"need_approval": True, "approved_by": "reviewer"},
    {"need_approval": False}, {"need_approval": False, "approved_by": "creator"},
    {"need_approval": 0, "approved_by": "reviewer"},
    {"need_approval": False, "approved_by": " "},
])
def test_prod_stress_refuses_missing_or_invalid_cosign_before_engine_call(
    worker_db_factory, monkeypatch, approval,
):
    """旧任务或绕过入口的生产压测在任何引擎请求之前失败收束。"""
    with worker_db_factory() as db:
        db.add(Task(
            id="stress", kind="stress", status="running", created_by="creator",
            config={"stress": {"env": "prod"}, **approval},
        ))
        db.commit()
    request = Mock(side_effect=AssertionError("不得请求压测引擎"))
    monkeypatch.setattr(stress, "_request_json", request)
    stress.run_stress("stress")
    request.assert_not_called()
    with worker_db_factory() as db:
        assert db.get(Task, "stress").status == "failed"
        assert db.query(TaskEvent).one().payload["code"] == "NEED_APPROVAL"


@pytest.mark.parametrize("whitelist", [[], ["example.test"]])
def test_valid_prod_cosign_still_requires_host_whitelist(worker_db_factory, monkeypatch, whitelist):
    """有效非创建者会签不绕过生产 Host 白名单；合法任务仍可解析执行配置。"""
    with worker_db_factory() as db:
        db.add(Setting(key="stress", value={"host_whitelist": whitelist}))
        db.add(ProtocolProfile(
            id="profile", name="local", protocol="openai_chat",
            base_url="https://example.test", model="local",
        ))
        task = Task(
            id="stress", kind="stress", status="running", created_by="creator",
            config={"stress": {"env": "prod"}, "profile_ids": ["profile"],
                    "need_approval": False, "approved_by": "reviewer"},
        )
        db.add(task)
        db.commit()
        monkeypatch.setattr(stress, "_build_probe", lambda _profile: (
            "https://example.test/v1/chat/completions", "local", {}, {},
        ))
        if whitelist:
            assert stress.resolve_job(db, task)["env"] == "prod"
        else:
            with pytest.raises(PermissionError, match="whitelist"):
                stress.resolve_job(db, task)
