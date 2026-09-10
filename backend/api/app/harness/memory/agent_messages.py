"""从已提交事件纯粹推导模型历史，保留正文、原始工具参数和供应商协议状态。"""

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from app.llm.loop_contracts import Message


class MessageProjectionError(ValueError):
    """已提交事件无法组成合法的模型历史。"""


def protocol_state_compatible(state: Any, target: dict[str, Any]) -> bool:
    """判断不透明状态能否回传给当前模型；未知结构一律不可迁移。"""
    if not isinstance(state, dict):
        return False
    return all(
        state.get(key) == value
        for key, value in target.items()
    )


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    """读取规范事实数据，拒绝非对象事件。"""
    data = event.get("data")
    if not isinstance(data, dict):
        raise MessageProjectionError(f"event {event.get('seq')} has non-object data")
    return data


def _assistant_message(data: dict[str, Any], seq: Any) -> Message:
    """恢复助手消息副本，保留工具与原始协议状态。"""
    candidate = data.get("message")
    if candidate is None:
        candidate = {
            "role": "assistant",
            "content": data.get("content", ""),
            "tool_calls": data.get("tool_calls"),
            "reasoning_content": data.get("reasoning_content"),
            **({"protocol_state": data["protocol_state"]} if "protocol_state" in data else {}),
        }
    if not isinstance(candidate, dict) or candidate.get("role") != "assistant":
        raise MessageProjectionError(f"assistant/message {seq} has invalid message")
    message = deepcopy(candidate)
    message.setdefault("content", "")
    if not isinstance(message["content"], str):
        raise MessageProjectionError(f"assistant/message {seq} content must be text")
    return message


def derive_messages(
    events: Iterable[dict[str, Any]], *, allow_open_tool_calls: bool = False,
    protocol_state_compatibility: dict[str, Any] | None = None,
) -> list[Message]:
    """推导并验证工具调用与结果配对；开放调用仅允许用于运行中的节点边界。"""

    messages: list[Message] = []
    pending: dict[str, tuple[str, Any]] = {}

    for event in events:
        type_ = event.get("type")
        data = _event_data(event)
        seq = event.get("seq")

        if type_ == "user/message":
            if pending:
                unresolved = ", ".join(sorted(pending))
                raise MessageProjectionError(
                    f"user/message {seq} appears before tool results: {unresolved}"
                )
            content = data.get("content")
            if not isinstance(content, str | list):
                raise MessageProjectionError(f"user/message {seq} content must be text or blocks")
            messages.append({"role": "user", "content": deepcopy(content)})
            continue

        if type_ == "assistant/message":
            if pending:
                unresolved = ", ".join(sorted(pending))
                raise MessageProjectionError(
                    f"assistant/message {seq} appears before tool results: {unresolved}"
                )
            message = _assistant_message(data, seq)
            if (
                protocol_state_compatibility is not None
                and "protocol_state" in message
                and not protocol_state_compatible(
                    message["protocol_state"], protocol_state_compatibility
                )
            ):
                # 跨模型只迁移用户可见文本，绝不把旧供应商签名伪装成新模型状态。
                message.pop("protocol_state", None)
                message.pop("reasoning_content", None)
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise MessageProjectionError(f"assistant/message {seq} tool_calls must be a list")
            for call in calls:
                if not isinstance(call, dict):
                    raise MessageProjectionError(f"assistant/message {seq} has invalid tool call")
                call_id = call.get("id")
                name = call.get("name")
                if not isinstance(call_id, str) or not call_id:
                    raise MessageProjectionError(f"assistant/message {seq} tool call has no id")
                if not isinstance(name, str) or not name:
                    raise MessageProjectionError(f"assistant/message {seq} tool call has no name")
                if call_id in pending:
                    raise MessageProjectionError(f"duplicate pending tool call id {call_id!r}")
                pending[call_id] = (name, seq)
            messages.append(message)
            continue

        if type_ == "tool/result":
            call_id = data.get("call_id", data.get("id"))
            if call_id is None:
                # 旧日志缺失调用 ID 时仅接受同名唯一候选，歧义必须明确报错。
                legacy_name = data.get("name")
                matches = [
                    candidate_id
                    for candidate_id, (candidate_name, _) in pending.items()
                    if candidate_name == legacy_name
                ]
                if len(matches) == 1:
                    call_id = matches[0]
            if not isinstance(call_id, str) or not call_id:
                raise MessageProjectionError(f"tool/result {seq} has no call id")
            expected = pending.pop(call_id, None)
            if expected is None:
                raise MessageProjectionError(
                    f"tool/result {seq} does not match a pending call {call_id!r}"
                )
            name = data.get("name", expected[0])
            if name != expected[0]:
                raise MessageProjectionError(
                    f"tool/result {seq} name {name!r} does not match {expected[0]!r}"
                )
            content = data.get("content", data.get("output", ""))
            if not isinstance(content, str):
                raise MessageProjectionError(f"tool/result {seq} content must be text")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": content,
                    "is_error": (
                        data["status"] != "succeeded"
                        if "status" in data else bool(data.get("is_error", False))
                    ),
                }
            )

    if pending and not allow_open_tool_calls:
        unresolved = ", ".join(sorted(pending))
        raise MessageProjectionError(f"unresolved tool calls: {unresolved}")
    return messages
