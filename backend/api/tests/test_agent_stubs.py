"""Agent 占位与长工具门禁单测（不连上游、不连 LightRAG）。"""

import pytest

from app.agent.lightrag_stub import LIGHTRAG_ENABLED, assert_lightrag_ready, query_lightrag
from app.agent.long_tasks import assert_short_tool
from app.errors import AppError, ErrorCode


def test_lightrag_stub_disabled():
    assert LIGHTRAG_ENABLED is False
    with pytest.raises(AppError) as exc_info:
        assert_lightrag_ready(reason="unit")
    assert exc_info.value.code == ErrorCode.VALIDATION
    assert exc_info.value.fields["feature"] == "lightrag"


def test_query_lightrag_raises_before_http():
    with pytest.raises(AppError) as exc_info:
        query_lightrag(query="什么是评测", mode="hybrid")
    assert exc_info.value.code == ErrorCode.VALIDATION


def test_assert_short_tool_allows_list():
    assert_short_tool("model.list")


def test_assert_short_tool_rejects_long_run():
    with pytest.raises(AppError) as exc_info:
        assert_short_tool("benchmark.run")
    assert exc_info.value.code == ErrorCode.VALIDATION
    assert exc_info.value.fields["tool"] == "benchmark.run"


def test_assert_short_tool_empty():
    with pytest.raises(AppError) as exc_info:
        assert_short_tool("")
    assert exc_info.value.code == ErrorCode.VALIDATION
