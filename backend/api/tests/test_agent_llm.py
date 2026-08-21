"""Agent 模型接入、三层耗时与脱敏追踪单元测试（AGT-LLM-01 / AGT-LLM-02）。

通过内存 FakeDb 桩替换 SQLAlchemy 会话，验证单模型绑定、结构化耗时出参、
上游错误归一化与日志脱敏等核心能力；不依赖真实数据库与外部网络。
"""

from __future__ import annotations

import io
import sys
from uuid import uuid4

import pytest

from app.adapters import AdapterResult
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.trace import TraceContext
from app.llm import (
    call_agent_model,
    call_agent_model_detailed,
    get_agent_profile_public_info,
    resolve_agent_profile,
    stream_agent_model,
)
from app.models import ProtocolProfile, Setting
from app.security import encrypt_secret


class _FakeQuery:
    """可根据模型类型和 filter 条件返回预置结果的最小查询桩。"""

    def __init__(self, db_store: dict):
        self._store = db_store
        self._target_model = None
        self._filter_key = None
        self._filter_val = None

    def set_model(self, model):
        self._target_model = model
        return self

    def filter(self, *expressions):
        # 简单捕获 Setting.key == 'agent_profile_id' 或 ProtocolProfile.id == ...
        for exp in expressions:
            if hasattr(exp, "left") and hasattr(exp, "right"):
                self._filter_key = getattr(exp.left, "key", None) or getattr(exp.left, "name", None)
                self._filter_val = getattr(exp.right, "value", None)
        return self

    def first(self):
        if self._target_model == Setting:
            for s in self._store.get("settings", []):
                if self._filter_key == "key" and s.key == self._filter_val:
                    return s
            return None
        if self._target_model == ProtocolProfile:
            for p in self._store.get("profiles", []):
                if self._filter_key == "id" and p.id == self._filter_val:
                    return p
            return None
        return None

    def all(self):
        if self._target_model == Setting:
            return list(self._store.get("settings", []))
        if self._target_model == ProtocolProfile:
            return list(self._store.get("profiles", []))
        return []


class _FakeDb:
    """覆盖 resolve_agent_profile / get_agent_profile_public_info 的轻量会话桩。"""

    def __init__(self, settings: list[Setting] | None = None, profiles: list[ProtocolProfile] | None = None):
        self._store = {
            "settings": settings or [],
            "profiles": profiles or [],
        }

    def query(self, model):
        q = _FakeQuery(self._store)
        return q.set_model(model)

    def add(self, obj):
        if isinstance(obj, Setting):
            self._store["settings"].append(obj)
        elif isinstance(obj, ProtocolProfile):
            self._store["profiles"].append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def sample_profile() -> ProtocolProfile:
    """构造示例 Agent 协议档。"""
    return ProtocolProfile(
        id=str(uuid4()),
        name="测试-Claude-3.5",
        protocol="anthropic_messages",
        base_url="https://api.anthropic.com",
        model="claude-3-5-sonnet-20241022",
        encrypted_key=encrypt_secret("sk-ant-secret-key-123456"),
        anthropic_version="2023-06-01",
        usages=["agent", "benchmark"],
        created_by="user-admin",
    )


def test_resolve_agent_profile_success(sample_profile: ProtocolProfile):
    """测试正常解析 Agent 协议档。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    resolved = resolve_agent_profile(fake_db)
    assert resolved.id == sample_profile.id
    assert resolved.model == "claude-3-5-sonnet-20241022"


def test_resolve_agent_profile_missing_setting():
    """测试未配置 settings.agent_profile_id 时抛出 VALIDATION (400)。"""
    fake_db = _FakeDb(settings=[])

    with pytest.raises(AppError) as exc_info:
        resolve_agent_profile(fake_db)
    assert exc_info.value.code == ErrorCode.VALIDATION
    assert "未配置 Agent 协议档" in exc_info.value.message


def test_resolve_agent_profile_not_found():
    """测试配置的协议档 ID 已在库中删除时抛出 VALIDATION。"""
    fake_id = str(uuid4())
    setting = Setting(key="agent_profile_id", value=fake_id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[])

    with pytest.raises(AppError) as exc_info:
        resolve_agent_profile(fake_db)
    assert exc_info.value.code == ErrorCode.VALIDATION
    assert "不存在或已删除" in exc_info.value.message


def test_resolve_agent_profile_no_key(sample_profile: ProtocolProfile):
    """测试协议档未配置 API Key 时抛出 VALIDATION。"""
    sample_profile.encrypted_key = None
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    with pytest.raises(AppError) as exc_info:
        resolve_agent_profile(fake_db)
    assert exc_info.value.code == ErrorCode.VALIDATION
    assert "未配置 API Key" in exc_info.value.message


def test_get_agent_profile_public_info(sample_profile: ProtocolProfile):
    """测试读取公开信息（脱敏，无密钥）。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    info = get_agent_profile_public_info(fake_db)
    assert info is not None
    assert info.profile_id == sample_profile.id
    assert info.name == "测试-Claude-3.5"
    assert info.model == "claude-3-5-sonnet-20241022"
    assert info.protocol == "anthropic_messages"
    assert not hasattr(info, "encrypted_key")
    assert not hasattr(info, "api_key")


def test_call_agent_model_detailed_success(sample_profile: ProtocolProfile, monkeypatch):
    """测试调用大模型返回结构化耗时与文本。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    mock_result = AdapterResult(
        text='{"intent": "benchmark"}',
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        raw={"id": "msg_123"},
        latency_ms=320,
    )
    monkeypatch.setattr("app.llm.call_protocol", lambda **kwargs: mock_result)

    result = call_agent_model_detailed(fake_db, "System prompt", "User prompt")
    assert result.text == '{"intent": "benchmark"}'
    assert result.latency_ms == 320
    assert result.usage["total_tokens"] == 15

    # 验证普通兼容接口返回文本
    text_only = call_agent_model(fake_db, "System prompt", "User prompt")
    assert text_only == '{"intent": "benchmark"}'


def test_call_agent_model_upstream_error(sample_profile: ProtocolProfile, monkeypatch):
    """测试上游 502/异常归一化为 UPSTREAM。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    def _mock_raise(**kwargs):
        raise AppError(ErrorCode.UPSTREAM, "上游接口 500 Internal Server Error")

    monkeypatch.setattr("app.llm.call_protocol", _mock_raise)

    with pytest.raises(AppError) as exc_info:
        call_agent_model_detailed(fake_db, "System prompt", "User prompt")
    assert exc_info.value.code == ErrorCode.UPSTREAM


def test_call_agent_model_timeout_error(sample_profile: ProtocolProfile, monkeypatch):
    """测试上游超时归一化为 TIMEOUT。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    def _mock_raise_timeout(**kwargs):
        raise AppError(ErrorCode.TIMEOUT, "请求模型超时 (30.0s)")

    monkeypatch.setattr("app.llm.call_protocol", _mock_raise_timeout)

    with pytest.raises(AppError) as exc_info:
        call_agent_model_detailed(fake_db, "System prompt", "User prompt")
    assert exc_info.value.code == ErrorCode.TIMEOUT


def test_agent_trace_redacts_key(sample_profile: ProtocolProfile, monkeypatch):
    """测试控制台日志包含耗时与模型名，但绝不泄露 API Key。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])

    mock_result = AdapterResult(
        text="规划完成",
        usage={"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        raw={},
        latency_ms=1250,
    )
    monkeypatch.setattr("app.llm.call_protocol", lambda **kwargs: mock_result)

    captured_err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured_err)

    call_agent_model_detailed(fake_db, "System", "User")
    log_output = captured_err.getvalue()

    assert "[agent]" in log_output
    assert "latency=1250ms" in log_output
    assert "model=claude-3-5-sonnet-20241022" in log_output
    # 严禁出现解密前后的 Key
    assert "sk-ant-secret-key-123456" not in log_output


def test_stream_agent_model_yields_reasoning_and_content(sample_profile: ProtocolProfile, monkeypatch):
    """流式调用把思考链与正文原样转交，不在 llm 层拼接。"""
    setting = Setting(key="agent_profile_id", value=sample_profile.id, updated_by="user-admin")
    fake_db = _FakeDb(settings=[setting], profiles=[sample_profile])
    monkeypatch.setattr(
        "app.llm.stream_protocol",
        lambda **_kwargs: iter([("reasoning", "先想"), ("content", "你好")]),
    )
    chunks = list(
        stream_agent_model(
            fake_db,
            "System",
            "User",
            trace=TraceContext.for_turn(),
            cancel=CancellationToken(turn_id="t-stream"),
        )
    )
    assert chunks == [("reasoning", "先想"), ("content", "你好")]
