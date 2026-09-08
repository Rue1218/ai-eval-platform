"""纯历史投影与重启收尾的幂等性及错误边界测试。"""

from copy import deepcopy

import pytest

from app.harness.memory.agent_messages import MessageProjectionError, derive_messages
from app.harness.memory.agent_recovery import recovery_events


def event(seq, kind, data):
    """构建不依赖持久后端的历史事件。"""
    return {"seq": seq, "type": kind, "data": data}


def open_history():
    """两个调用中只有第二个到达 dispatch，尚无任何结果。"""
    return [
        event(0, "turn/start", {"turn": 1}),
        event(1, "user/message", {"turn": 1, "content": "执行"}),
        event(2, "step/start", {"turn": 1, "step": 1}),
        event(3, "assistant/message", {
            "turn": 1, "step": 1, "attempt_id": "attempt",
            "message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "a", "name": "read", "args": {}},
                {"id": "b", "name": "edit", "args": {}},
            ], "protocol_state": {"items": [{"encrypted_content": "opaque"}]}},
        }),
        event(4, "tool/call", {"call_id": "a", "name": "read"}),
        event(5, "tool/call", {"call_id": "b", "name": "edit"}),
        event(6, "tool/dispatch", {"call_id": "b", "name": "edit"}),
    ]


def test_recovery_is_pure_ordered_idempotent_and_preserves_protocol_state():
    """恢复只规划补偿，已派发标未知，未派发标未启动，重复恢复无新增。"""
    events = open_history()
    before = deepcopy(events)
    repairs = recovery_events(events)
    assert events == before
    assert [(r.data["call_id"], r.data["status"]) for r in repairs[:2]] == [
        ("a", "not_started"), ("b", "outcome_unknown"),
    ]
    assert [r.data["call_seq"] for r in repairs[:2]] == [4, 5]
    events += [event(7 + i, repair.type, repair.data) for i, repair in enumerate(repairs)]
    assert recovery_events(events) == []
    messages = derive_messages(events)
    assert [m.get("tool_call_id") for m in messages[-2:]] == ["a", "b"]
    assert messages[1]["protocol_state"] == before[3]["data"]["message"]["protocol_state"]


@pytest.mark.parametrize("kind", ["user/message", "assistant/message"])
def test_interleaved_message_cannot_hide_unresolved_tool_calls(kind):
    """工具结果配齐前插入新消息必须明确失败。"""
    events = open_history()
    events.append(event(7, kind, {"content": "不合法插入"}))
    with pytest.raises(MessageProjectionError, match="before tool results"):
        derive_messages(events)


def test_open_history_is_only_allowed_for_live_node_boundary():
    """重启不能带着开放 tool call 继续请求模型。"""
    with pytest.raises(MessageProjectionError, match="unresolved tool calls"):
        derive_messages(open_history())
    assert derive_messages(open_history(), allow_open_tool_calls=True)[-1]["tool_calls"]


def test_tool_result_name_and_duplicate_result_are_rejected():
    """未知调用、重复结果和调用名称错配不得组成模型历史。"""
    events = open_history()
    with pytest.raises(MessageProjectionError, match="does not match"):
        derive_messages([*events, event(7, "tool/result", {
            "call_id": "a", "name": "edit", "content": "错误名称",
        })])
    result = event(7, "tool/result", {"call_id": "a", "name": "read", "content": "结果"})
    with pytest.raises(MessageProjectionError, match="does not match a pending call"):
        derive_messages([*events, result, {**result, "seq": 8}])


def test_user_multimodal_content_is_preserved_without_mutating_facts():
    """图片内容块沿事实进入请求，投影与日志不共享可变引用。"""
    content = [{"type": "text", "text": "识图"}, {"type": "image_url", "image_url": {"url": "x"}}]
    events = [event(0, "user/message", {"content": content})]
    messages = derive_messages(events)
    assert messages[0]["content"] == content
    messages[0]["content"][0]["text"] = "changed"
    assert content[0]["text"] == "识图"


@pytest.mark.parametrize("asked,ended", [
    ("approval/asked", "approval/decided"),
    ("question/asked", "question/answered"),
    ("task_confirmation/requested", "task_confirmation/resolved"),
])
@pytest.mark.parametrize("turn_closed", [False, True])
def test_recovery_closes_pending_interactions_even_after_turn_end(asked, ended, turn_closed):
    """三类悬挂交互都按原身份终结；已有 turn/end 也不遗留 pending_confirm。"""
    events = open_history()
    asked_data = {
        "interaction_id": "interaction", "turn": 1, "step": 1,
        "attempt_id": "attempt", "call_id": "b", "nonce": "nonce", "owner_user_id": "actor",
    }
    events.append(event(7, asked, asked_data))
    if turn_closed:
        events.append(event(8, "turn/end", {"turn": 1, "reason": "error"}))
    repairs = recovery_events(events)
    assert repairs[0].type == ended
    assert repairs[0].data["interaction_id"] == "interaction"
    assert repairs[0].data["nonce"] == "nonce"
    assert repairs[0].data["outcome"] == "cancelled"
    repaired = [*events, *[
        event(9 + index, repair.type, repair.data) for index, repair in enumerate(repairs)
    ]]
    assert recovery_events(repaired) == []


def test_resolved_interaction_is_not_cancelled_again():
    """已收到有效回答的卡不被崩溃恢复覆盖。"""
    events = open_history()
    events += [
        event(7, "question/asked", {"interaction_id": "q", "turn": 1}),
        event(8, "question/answered", {"interaction_id": "q", "turn": 1,
                                     "outcome": "answered", "answer": "是"}),
    ]
    assert not any(r.type == "question/answered" for r in recovery_events(events))


@pytest.mark.parametrize("matching", [True, False])
def test_queued_receipt_recovers_known_success_without_reenqueue(matching):
    """仅精确关联的入队事实可替代未知结果；模型拿真实 task_id 和正文。"""
    events = open_history()
    events.append(event(7, "task/queued", {
        "turn": 1, "attempt_id": "attempt" if matching else "other",
        "call_id": "b", "task_id": "task-123", "content": "已入队 task-123",
    }))
    repairs = recovery_events(events)
    result = next(r.data for r in repairs if r.type == "tool/result" and r.data["call_id"] == "b")
    assert result["status"] == ("succeeded" if matching else "outcome_unknown")
    if matching:
        assert result["task_id"] == "task-123" and result["is_error"] is False
        assert result["content"] == "已入队 task-123"
        repaired = events + [
            event(8 + index, repair.type, repair.data) for index, repair in enumerate(repairs)
        ]
        assert derive_messages(repaired)[-1] == {
            "role": "tool", "tool_call_id": "b", "name": "edit",
            "content": "已入队 task-123", "is_error": False,
        }
        assert recovery_events(repaired) == []
    assert not any(r.type == "task/queued" for r in repairs)
