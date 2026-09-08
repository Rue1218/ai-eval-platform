"""为中断回合生成确定性的收尾事件，不重放工具，也不推断未知外部副作用已完成。"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecoveryEvent:
    """调用者须按顺序持久化的恢复事件。"""

    type: str
    data: dict[str, Any]


def recovery_events(
    events: list[dict[str, Any]], *, turn_reason: str = "interrupted"
) -> list[RecoveryEvent]:
    """生成最后一个开放回合所需的补偿；已派发记未知，未派发记未启动。"""

    open_turn: int | None = None
    open_step: int | None = None
    pending: dict[str, dict[str, Any]] = {}
    interaction_ends = {
        "approval/asked": "approval/decided",
        "question/asked": "question/answered",
        "task_confirmation/requested": "task_confirmation/resolved",
    }
    # 交互卡独立于 turn/end 跟踪，兼容已收尾但卡片仍未关闭的崩溃边界。
    interactions: dict[tuple[str, str], dict[str, Any]] = {}

    for event in events:
        type_ = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            continue

        interaction_id = data.get("interaction_id") or data.get("approval_id") or data.get("id")
        if isinstance(interaction_id, str) and interaction_id:
            if type_ in interaction_ends:
                interactions[(interaction_ends[type_], interaction_id)] = deepcopy(data)
            elif type_ in interaction_ends.values():
                interactions.pop((type_, interaction_id), None)

        if type_ == "turn/start":
            open_turn = data.get("turn")
            open_step = None
            pending = {}
        elif type_ == "turn/end":
            open_turn = None
            open_step = None
            pending = {}
        elif open_turn is None:
            continue
        elif type_ == "step/start":
            open_step = data.get("step")
        elif type_ == "step/end":
            open_step = None
        elif type_ == "assistant/message":
            message = data.get("message")
            calls = message.get("tool_calls", []) if isinstance(message, dict) else data.get(
                "tool_calls", []
            )
            if not isinstance(calls, list):
                continue
            for call in calls:
                if not isinstance(call, dict):
                    continue
                call_id = call.get("id")
                name = call.get("name")
                if isinstance(call_id, str) and call_id and isinstance(name, str) and name:
                    pending[call_id] = {
                        "name": name,
                        "args": call.get("args"),
                        "dispatched": False,
                        "turn": data.get("turn", open_turn),
                        "step": data.get("step", open_step),
                        "attempt_id": data.get("attempt_id", "recovery"),
                        "call_seq": None,
                    }
        elif type_ == "tool/call":
            call_id = data.get("call_id", data.get("id"))
            if call_id in pending:
                pending[call_id]["call_seq"] = event.get("seq")
        elif type_ == "tool/dispatch":
            call_id = data.get("call_id", data.get("id"))
            if call_id in pending:
                pending[call_id]["dispatched"] = True
        elif type_ == "task/queued":
            # 入队与此事实同事务；只采信精确关联到当前调用的已知成功收据。
            call_id = data.get("call_id")
            call = pending.get(call_id)
            if (
                call is not None
                and data.get("turn") == call["turn"]
                and data.get("attempt_id") == call["attempt_id"]
                and isinstance(data.get("task_id"), str)
                and data["task_id"]
            ):
                call["queued_receipt"] = deepcopy(data)
                call["queued_seq"] = event.get("seq")
        elif type_ == "tool/result":
            call_id = data.get("call_id", data.get("id"))
            if isinstance(call_id, str):
                pending.pop(call_id, None)

    repairs = [
        RecoveryEvent(kind, {
            **data, "outcome": "cancelled", "source_outcome": "cancelled",
            "synthetic": True,
            **({"decision": "cancelled"} if kind == "task_confirmation/resolved" else {}),
        })
        for (kind, _identity), data in interactions.items()
    ]
    if open_turn is None:
        return repairs

    for call_id, call in pending.items():
        receipt = call.get("queued_receipt")
        status = (
            "succeeded" if receipt else
            "outcome_unknown" if call["dispatched"] else "not_started"
        )
        if receipt:
            content = receipt.get("content")
            if not isinstance(content, str) or not content:
                content = f"任务已入队，task_id={receipt['task_id']}"
        elif status == "outcome_unknown":
            content = (
                "The previous run was interrupted after dispatching this tool. "
                "Its external outcome is unknown; inspect before retrying."
            )
        else:
            content = "The previous run stopped before this tool started."
        repairs.append(
            RecoveryEvent(
                "tool/result",
                {
                    "call_id": call_id,
                    "id": call_id,
                    "name": call["name"],
                    "turn": call["turn"],
                    "step": call["step"],
                    "attempt_id": call["attempt_id"],
                    **(
                        {"call_seq": call["call_seq"]}
                        if isinstance(call["call_seq"], int)
                        else {}
                    ),
                    "content": content,
                    "is_error": status != "succeeded",
                    "status": status,
                    "synthetic": True,
                    **({
                        "task_id": receipt["task_id"],
                        "metadata": {
                            "task_id": receipt["task_id"],
                            "source_task_event_seq": call["queued_seq"],
                        },
                    } if receipt else {}),
                },
            )
        )

    if open_step is not None:
        repairs.append(
            RecoveryEvent(
                "step/end",
                {"turn": open_turn, "step": open_step, "reason": "interrupted"},
            )
        )
    repairs.append(RecoveryEvent("turn/end", {"turn": open_turn, "reason": turn_reason}))
    return repairs
