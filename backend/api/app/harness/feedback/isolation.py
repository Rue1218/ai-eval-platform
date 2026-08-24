"""Harness 反馈层：Worker 事件隔离（M6 阶段 4，FB-5）。

Worker 的 progress/report/error 只进 ``ws_events``/``task_events``，**不进
``messages`` 表**、不污染消息窗口（FB-5）；M2 ``window.py`` 的过滤规则
（CX-2）依赖本层标记。事件归属边界（M6-D5）：progress/report/error 为 WS
持久化事件（Worker ``push_ws`` 写 ws_events），task.* 为任务事件（写
task_events），均非图节点产出、不进 ``NodeEventKind``。
"""

from __future__ import annotations

from app.errors import AppError, ErrorCode

# Worker 链路事件集合（M6-D5）
WORKER_EVENTS: frozenset[str] = frozenset(
    {
        "progress",
        "report",
        "error",
        "task.created",
        "task.succeeded",
        "task.failed",
    }
)


def isolate_worker_event(event: str) -> bool:
    """判定事件是否属 Worker 链路（FB-5）。"""
    return event in WORKER_EVENTS


def assert_not_in_messages(event: str) -> None:
    """断言 Worker 事件不进消息窗口（供 M2 window.py 调用）。"""
    if event in WORKER_EVENTS:
        raise AppError(ErrorCode.VALIDATION, "Worker 事件不进消息窗口")
