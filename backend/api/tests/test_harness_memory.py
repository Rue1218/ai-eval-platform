"""M3 记忆层单测（E-A1~E-A8）；不依赖 DB。"""

import json

import pytest

from app.errors import AppError, ErrorCode
from app.harness.context import recent_window, summarize
from app.harness.contracts import Observation, make_event
from app.harness.memory import (
    GraphState,
    assert_serializable,
    new_working,
    reset_working,
    retrieve,
    to_serializable_request,
)
from app.harness.memory.state import _append_events
from app.llm import ModelConfig, ModelRequest


def _full_state() -> GraphState:
    """构造含全部阶段 1 字段的 GraphState。"""
    return GraphState(
        request={
            "config": {
                "protocol": "openai_chat",
                "base_url": "https://model.example.com",
                "model": "test-model",
            },
            "messages": ({"role": "user", "content": "你好"},),
        },
        mode="chat",
        pending_events=[
            make_event("thought", {"text": "先判断", "stage": "plan"}),
            make_event("assistant_message", {"text": "答案"}),
        ],
        response={"text": "答案", "usage": {}, "latency_ms": 1},
    )


def test_graph_state_all_fields_json_serializable() -> None:
    """E-A1：GraphState 全字段 json.dumps 不抛 TypeError。"""
    assert_serializable(_full_state())
    json.dumps(_full_state())


def test_graph_state_no_callable_or_websocket_fields() -> None:
    """E-A2：GraphState 不含 Callable/WebSocket/DB Session 字段（反射断言）。"""
    state = _full_state()
    assert "should_abort" not in state
    for value in state.values():
        assert not callable(value)
        assert "WebSocket" not in type(value).__name__


def test_pending_events_append_reducer_accumulates() -> None:
    """E-A3：append reducer：两节点各写 2 事件，State 累积 4。"""
    left = [make_event("thought", {"text": "a"}), make_event("thought", {"text": "b"})]
    right = [make_event("plan", {"intent": "c"}), make_event("plan", {"intent": "d"})]
    merged = _append_events(left, right)
    assert len(merged) == 4
    assert [event["payload"]["text"] for event in merged[:2]] == ["a", "b"]


def test_working_memory_reset_clears_observations_stop_flag() -> None:
    """E-A4：回合清理清零 observations/stop_flag（MEM-1 暂态）。"""
    state = {
        "observations": [Observation(tool="web_search", text="摘要", ok=True)],
        "stop_flag": True,
    }
    patch = reset_working(state)
    assert patch["observations"] == []
    assert patch["stop_flag"] is False


def test_reset_working_respects_allows_replan_for_plan() -> None:
    """E-A4：plan 按 allows_replan 决定保留与否。"""
    keeps = reset_working(
        {
            "plan": {
                "intent": "运行评测",
                "allows_replan": True,
            }
        }
    )
    assert "plan" not in keeps
    drops = reset_working(
        {
            "plan": {
                "intent": "运行评测",
                "allows_replan": False,
            }
        }
    )
    assert drops["plan"] is None


def test_to_serializable_request_strips_abort_and_api_key() -> None:
    """SerializableRequest 投影剔除 should_abort 与 api_key（M3-D2 红线）。"""
    request = ModelRequest(
        config=ModelConfig(
            protocol="openai_chat",
            base_url="https://model.example.com",
            model="test-model",
            api_key="secret-key",
        ),
        messages=({"role": "user", "content": "你好"},),
    )
    serializable = to_serializable_request(request)
    assert "api_key" not in serializable["config"]
    assert "should_abort" not in serializable
    assert serializable["messages"] == ({"role": "user", "content": "你好"},)


def test_new_working_initialises_empty() -> None:
    """工作记忆初始化：observations=[] / stop_flag=False。"""
    working = new_working()
    assert working == {"observations": [], "stop_flag": False}


def test_compressed_summary_original_window_priority() -> None:
    """E-A6：压缩摘要与原始冲突时原始优先（窗口仍装配原始消息）。"""
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant",
         "content": f"原始消息-{index}", "source_id": f"message:{index}"}
        for index in range(30)
    ]
    summary, kept_ids = summarize(messages)
    assert summary  # 摘要仅作上下文补充
    window = recent_window(messages, limit=20, keep_from=kept_ids[0])
    # 窗口内容全部是原始消息，不掺入摘要文本
    assert all("原始消息" in message["content"] for message in window)
    assert len(window) <= 20


def test_semantic_retrieve_not_available() -> None:
    """E-A8：语义记忆未接入直接抛 VALIDATION（MEM-5）。"""
    with pytest.raises(AppError) as error:
        retrieve("查询评测报告")
    assert error.value.code == ErrorCode.VALIDATION
