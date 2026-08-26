"""P4：协议档灰度、脱敏指标与并行脚踢线。"""

from __future__ import annotations

import json

from app.harness.execution.stream_metrics import StreamMetrics, get_default_stream_metrics
from app.harness.execution.stream_policy import (
    native_stream_allowed,
    parallel_batch_allowed,
    parse_profile_ids,
    profile_id_from_configurable,
)
from app.routers.agent_prefs import get_agent_metrics


def test_parse_profile_ids_strips_blanks() -> None:
    """白名单解析忽略空白项。"""
    assert parse_profile_ids(" a, b , ,c") == frozenset({"a", "b", "c"})
    assert parse_profile_ids("") == frozenset()


def test_profile_id_from_configurable() -> None:
    """只读 configurable.profile.id，缺省为空串。"""
    assert profile_id_from_configurable({"profile": {"id": "p1"}}) == "p1"
    assert profile_id_from_configurable({}) == ""
    assert profile_id_from_configurable(None) == ""


def test_native_stream_default_all_native(monkeypatch) -> None:
    """P1 默认对全部 native 开放；legacy 永不走流式。"""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_native_stream_enabled", True)
    monkeypatch.setattr(settings, "agent_native_stream_profile_ids", "")
    assert native_stream_allowed("", "native") is True
    assert native_stream_allowed("p1", "legacy") is False
    monkeypatch.setattr(settings, "agent_native_stream_enabled", False)
    assert native_stream_allowed("p1", "native") is False
    monkeypatch.setattr(settings, "agent_native_stream_enabled", True)
    monkeypatch.setattr(settings, "agent_native_stream_profile_ids", "p1")
    assert native_stream_allowed("p1", "native") is True
    assert native_stream_allowed("p2", "native") is False


def test_parallel_requires_flag_and_allowlist(monkeypatch) -> None:
    """并行必须总开关 + 白名单；空白名单不开。"""
    from app.config import settings

    get_default_stream_metrics().reset()
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", False)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    assert parallel_batch_allowed("p1", has_batch=True) is False

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", True)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "")
    assert parallel_batch_allowed("p1", has_batch=True) is False
    assert parallel_batch_allowed("p1", has_batch=False) is False

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "p-test")
    assert parallel_batch_allowed("p-test", has_batch=True) is True
    assert parallel_batch_allowed("other", has_batch=True) is False

    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    assert parallel_batch_allowed("anything", has_batch=True) is True


def test_stream_metrics_snapshot_has_no_payloads() -> None:
    """快照只含计数与延迟，不含正文或参数。"""
    metrics = StreamMetrics(failure_threshold=3, cooldown_s=30.0)
    metrics.record_stream(first_delta_ms=12, tool_call_parse_ms=40)
    metrics.record_batch(duration_ms=80, wave_size=2, parallel=True)
    encoded = json.dumps(metrics.snapshot(), ensure_ascii=False)
    assert "arguments" not in encoded
    assert '"content"' not in encoded
    snap = metrics.snapshot()
    assert snap["stream"]["rounds"] == 1
    assert snap["stream"]["first_delta_avg_ms"] == 12
    assert snap["stream"]["tool_call_parse_avg_ms"] == 40
    assert snap["stream"]["incomplete_ratio"] == 0.0
    assert snap["batch"]["parallel_waves"] == 1
    assert snap["batch"]["max_wave_size"] == 2
    assert snap["rollout"]["parallel_disabled"] is False


def test_stream_metrics_trips_parallel_on_upstream_then_cools(monkeypatch) -> None:
    """连续 UPSTREAM 达阈值暂时禁用并行，冷却后恢复，不改历史事件。"""
    clock = {"now": 1000.0}

    monkeypatch.setattr(
        "app.harness.execution.stream_metrics.time.time", lambda: clock["now"]
    )
    metrics = StreamMetrics(failure_threshold=2, cooldown_s=10.0)
    metrics.record_stream(upstream=True, incomplete=True)
    assert metrics.is_parallel_disabled() is False
    metrics.record_stream(upstream=True, incomplete=True)
    assert metrics.is_parallel_disabled() is True
    assert metrics.snapshot()["rollout"]["parallel_disable_reason"] == "UPSTREAM"
    clock["now"] = 1011.0
    assert metrics.is_parallel_disabled() is False
    assert metrics.snapshot()["rollout"]["parallel_disable_reason"] is None


def test_stream_metrics_associate_error_trips_and_cancel_does_not() -> None:
    """关联错乱计入脚踢；用户取消不计入。"""
    metrics = StreamMetrics(failure_threshold=1, cooldown_s=60.0)
    metrics.record_stream(cancelled=True)
    assert metrics.is_parallel_disabled() is False
    metrics.record_stream(associate_error=True, upstream=True)
    assert metrics.is_parallel_disabled() is True
    assert metrics.snapshot()["rollout"]["parallel_disable_reason"] == "associate"
    assert metrics.snapshot()["stream"]["cancelled"] == 1


def test_stream_metrics_consecutive_associate_error_only_trips() -> None:
    """仅 associate_error、不夹成功记账时，连续两笔必须触发脚踢线。"""
    metrics = StreamMetrics(failure_threshold=2, cooldown_s=10.0)
    metrics.record_stream(associate_error=True)
    assert metrics.is_parallel_disabled() is False
    metrics.record_stream(associate_error=True)
    assert metrics.is_parallel_disabled() is True
    snap = metrics.snapshot()
    assert snap["stream"]["rounds"] == 2
    assert snap["stream"]["associate_errors"] == 2
    assert snap["rollout"]["parallel_disable_reason"] == "associate"
    assert snap["rollout"]["consecutive_incidents"] == 2


def test_parallel_denied_when_metrics_tripped(monkeypatch) -> None:
    """脚踢线生效时即使白名单命中也不并行。"""
    from app.config import settings

    get_default_stream_metrics().reset()
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_enabled", True)
    monkeypatch.setattr(settings, "agent_parallel_tool_batch_profile_ids", "*")
    tripped = StreamMetrics(failure_threshold=1, cooldown_s=60.0)
    tripped.record_stream(upstream=True, incomplete=True)
    monkeypatch.setattr(
        "app.harness.execution.stream_metrics.get_default_stream_metrics",
        lambda: tripped,
    )
    assert parallel_batch_allowed("p1", has_batch=True) is False
    get_default_stream_metrics().reset()


def test_agent_metrics_route_returns_process_snapshot() -> None:
    """GET /api/agent/metrics 与进程收集器同一快照。"""
    get_default_stream_metrics().reset()
    payload = get_agent_metrics(user=None)  # type: ignore[arg-type]
    assert set(payload) == {"stream", "batch", "rollout"}
    assert "incomplete_ratio" in payload["stream"]
    encoded = json.dumps(payload)
    assert "api_key" not in encoded
    assert "arguments" not in encoded
