"""H5 批次 2 测试：PgCheckpointer 生产门禁 + 实例标识（粘性路由支持）。

覆盖：
1. ``_validate_hitl_checkpointer`` 启动门禁——混合引擎开启 + memory 检查点：
   ``agent_hitl_strict_pg=true`` → fail-fast（AppError VALIDATION）；
   ``agent_hitl_strict_pg=false``（默认）→ 仅告警不抛；
   混合引擎关闭或检查点为 postgres → 放行。
2. ``_resolve_instance_id`` 实例标识——显式配置优先；空时派生 hostname:pid 且
   同进程内稳定、非空。
3. ``/api/health`` 暴露 ``instance_id`` 字段供网关粘性路由健康检查识别副本。

不依赖 PG（门禁只读配置字符串，不实际建连）；真实 PgCheckpointer 重启恢复演练
见开发计划 §4.3 Linux/Docker 环境。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.errors import AppError, ErrorCode
from app.main import _resolve_instance_id, _validate_hitl_checkpointer, app


def _set(monkeypatch, **kwargs):
    """批量覆盖 settings 字段。"""
    for key, value in kwargs.items():
        monkeypatch.setattr(settings, key, value)


# ─── 1. HITL 检查点启动门禁 ───


def test_hitl_guard_off_when_hybrid_disabled(monkeypatch):
    """混合引擎关闭时门禁不触发（无论检查点为何）。"""
    _set(monkeypatch, hybrid_engine_enabled=False, agent_checkpointer="memory", agent_hitl_strict_pg=True)
    _validate_hitl_checkpointer()  # 不抛即通过


def test_hitl_guard_off_when_postgres(monkeypatch):
    """混合引擎开启 + postgres 检查点 → 放行（HITL 可跨进程恢复）。"""
    _set(monkeypatch, hybrid_engine_enabled=True, agent_checkpointer="postgres", agent_hitl_strict_pg=True)
    _validate_hitl_checkpointer()


def test_hitl_guard_strict_blocks_memory(monkeypatch):
    """混合引擎 + memory + strict → fail-fast（生产门禁，C-7/ADR-7）。"""
    _set(monkeypatch, hybrid_engine_enabled=True, agent_checkpointer="memory", agent_hitl_strict_pg=True)
    with pytest.raises(AppError) as exc:
        _validate_hitl_checkpointer()
    assert exc.value.code == ErrorCode.VALIDATION
    assert "postgres" in exc.value.message


def test_hitl_guard_non_strict_warns_only(monkeypatch, caplog):
    """混合引擎 + memory + 非 strict（默认）→ 仅告警，不抛（单副本/测试可用）。"""
    _set(monkeypatch, hybrid_engine_enabled=True, agent_checkpointer="memory", agent_hitl_strict_pg=False)
    _validate_hitl_checkpointer()  # 不抛即通过


def test_hitl_guard_case_insensitive(monkeypatch):
    """检查点配置大小写不敏感（MEMORY / Postgres 均识别）。"""
    _set(monkeypatch, hybrid_engine_enabled=True, agent_checkpointer="MEMORY", agent_hitl_strict_pg=True)
    with pytest.raises(AppError):
        _validate_hitl_checkpointer()
    _set(monkeypatch, agent_checkpointer="Postgres")
    _validate_hitl_checkpointer()  # 不抛


# ─── 2. 实例标识派生（粘性路由支持） ───


def test_instance_id_explicit_wins(monkeypatch):
    """显式配置优先于自动派生。"""
    _set(monkeypatch, agent_instance_id="prod-api-node-1")
    assert _resolve_instance_id() == "prod-api-node-1"


def test_instance_id_auto_derived_nonempty(monkeypatch):
    """空配置时派生 hostname:pid，非空且同进程稳定。"""
    _set(monkeypatch, agent_instance_id="")
    first = _resolve_instance_id()
    second = _resolve_instance_id()
    assert first and ":" in first  # hostname:pid 形态
    assert first == second  # 同进程内稳定


def test_instance_id_strips_whitespace(monkeypatch):
    """配置含空白时去首尾空格。"""
    _set(monkeypatch, agent_instance_id="  node-2  ")
    assert _resolve_instance_id() == "node-2"


# ─── 3. /api/health 暴露 instance_id ───


def test_health_exposes_instance_id(monkeypatch):
    """健康端点携带 instance_id，供网关粘性路由识别副本。"""
    _set(monkeypatch, agent_instance_id="test-instance")
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["instance_id"] == "test-instance"
