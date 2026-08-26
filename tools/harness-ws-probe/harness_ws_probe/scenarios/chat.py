"""真模型对话诊断：看路由收尾、思考链帧密度与正文时序。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..errors import ProbeError
from ..expect import ExpectMatcher
from ..recorder import TraceFrame, TraceRecorder


def _payload(frame: TraceFrame) -> dict[str, Any]:
    inner = frame.raw.get("payload")
    return inner if isinstance(inner, dict) else {}


def summarize_turn(trace: TraceRecorder, *, after_frame: int = 0) -> dict[str, Any]:
    """从 after_frame 起切出一轮下行，统计思考链与正文。"""
    frames = [item for item in trace.frames[after_frame:] if item.dir == "down"]
    counts = Counter(item.event for item in frames)
    thinks = [
        item
        for item in frames
        if item.event == "thought" and _payload(item).get("stream") == "think"
    ]
    finals = [
        item
        for item in frames
        if item.event == "thought" and _payload(item).get("stream") == "think_final"
    ]
    deltas = [item for item in frames if item.event == "assistant_delta"]
    messages = [item for item in frames if item.event == "assistant_message"]
    completed = [item for item in frames if item.event == "response.completed"]
    tools = [item for item in frames if item.event in {"tool_call", "tool_result", "plan", "confirm"}]
    think_chars = sum(len(str(_payload(item).get("text") or "")) for item in thinks)
    think_final_text = str(_payload(finals[-1]).get("text") or "") if finals else ""
    answer = str(_payload(messages[-1]).get("text") or "") if messages else ""
    base = frames[0].t_ms if frames else 0
    first_think = thinks[0].t_ms - base if thinks else None
    first_delta = deltas[0].t_ms - base if deltas else None
    done_at = completed[-1].t_ms - base if completed else None
    event_order = [item.event for item in frames if item.event != "pong"]
    persistent = [item.event for item in frames if item.persistent and item.event != "pong"]
    final_before_done = False
    if "thought" in persistent and "response.completed" in persistent:
        final_before_done = persistent.index("thought") < persistent.index(
            "response.completed"
        )
    return {
        "counts": dict(counts),
        "think_frames": len(thinks),
        "think_chars": think_chars,
        "think_final_chars": len(think_final_text),
        "delta_frames": len(deltas),
        "first_think_ms": first_think,
        "first_delta_ms": first_delta,
        "completed_ms": done_at,
        "answer": answer,
        "think_final_preview": think_final_text[:400],
        "tools": [item.event for item in tools],
        "persistent_order": persistent,
        "event_tail": event_order[-12:],
        "completed_before_think_final": bool(finals and completed and not final_before_done),
    }


async def run_chat_turn(
    client: Any, text: str, *, timeout_s: float = 90.0, check: bool = True
) -> dict[str, Any]:
    """发一条闲聊/任务句，等到 response.completed；默认按思考链契约断言。"""
    mark = len(client.trace.frames)
    await client.send_user_message(text)
    await client.wait_event("response.completed", timeout_s=timeout_s)
    await client.drain(0.5)
    stats = summarize_turn(client.trace, after_frame=mark)
    stats["prompt"] = text
    stats["after_frame"] = mark
    if not stats["completed_ms"] and stats["completed_ms"] != 0:
        raise ProbeError("对话未收到 response.completed")
    if check:
        ExpectMatcher(client.trace).chat_turn_contract(after_frame=mark)
    return stats


def print_stats(stats: dict[str, Any]) -> None:
    """CLI 可读摘要，不打印完整思维链。"""
    print(f"prompt: {stats['prompt']}")
    print(
        f"  think={stats['think_frames']}帧/{stats['think_chars']}字"
        f"  delta={stats['delta_frames']}"
        f"  first_think={stats['first_think_ms']}ms"
        f"  first_delta={stats['first_delta_ms']}ms"
        f"  completed={stats['completed_ms']}ms"
    )
    print(f"  persistent={stats['persistent_order']}")
    print(f"  completed_before_think_final={stats['completed_before_think_final']}")
    if stats["tools"]:
        print(f"  tools={stats['tools']}")
    answer = stats["answer"].replace("\n", " ")
    if len(answer) > 180:
        answer = answer[:180] + "…"
    print(f"  answer: {answer}")
    preview = stats["think_final_preview"].replace("\n", " ")
    if preview:
        print(f"  think_final: {preview[:180]}{'…' if len(preview) > 180 else ''}")
