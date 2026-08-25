"""压测参数夹紧、白名单与报告映射回归。"""

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
