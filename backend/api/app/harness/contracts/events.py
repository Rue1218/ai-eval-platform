"""图节点返回纯数据的事件意图契约（M7 阶段 1）。

图节点只返回纯数据（结构化结果/事件意图），不持有 WebSocket 连接或 emit
回调；事件由收包循环把 GraphState.pending_events 统一翻译为 ws event 发出。
本模块只定义类型与最小构造函数，不含控制流、不访问数据库。

事件种类与 API.md §4.3 持久化事件对齐，但只覆盖**图节点可产出**的子集：

- 图节点产出：thought / tool_call / tool_result / confirm / clarify / plan /
  error / assistant_message / response.completed
- ws.py 收包循环直产：user_message（用户上行）、confirm_ack（回执）
- Worker 直产：progress / report / error（push_ws 写 ws_events 并实时转发）

瞬态帧（assistant_delta / thought.stream=think）不进本枚举，由节点通过
``get_stream_writer`` 直接投影。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

# 词汇表单一事实源（dsh 改进 #4）：本模块不再自持集合，全部从 shared 引用，
# 消灭 _PERSISTENT_KINDS 与 ws.py/worker 直产字符串的碎片化漂移。
from shared.event_vocab import EVENT_VERSION, NODE_EVENT_KINDS, PERSISTENT_KINDS

# 图节点产出的持久化事件意图（对齐 API.md §4.3；生产者归属矩阵见模块文档 §3.6.1）
NodeEventKind = Literal[
    "user_message",
    "thought",
    "tool_call",
    "tool_result",
    "confirm",
    "clarify",
    "plan",
    "task_state",
    "progress",
    "report",
    "error",
    "assistant_message",
    "response.completed",
    "fabrication",
]

# NodeEventKind 字面量值集合（make_event 白名单；confirm_ack 等直产事件不可由节点产出）
_NODE_EVENT_KIND_VALUES: frozenset[str] = NODE_EVENT_KINDS

# 模块加载期一致性护栏（#4 D5 注册表完整性断言的一部分）：字面量集合与
# shared 注册表必须完全一致，防止两处再次漂移（漂移即启动失败）。
assert _NODE_EVENT_KIND_VALUES == frozenset(NodeEventKind.__args__), (
    "shared.event_vocab.NODE_EVENT_KINDS 与 NodeEventKind 字面量不一致，"
    "请同步扩展词汇表单一事实源（backend/shared/event_vocab.py）"
)


class NodeEvent(TypedDict, total=False):
    """图节点返回的纯数据事件意图。

    由 M4 节点写入 GraphState.pending_events，ws.py 收包循环消费后翻译为
    ws event（落 ws_events + 广播）。payload 统一为 Mapping + 校验函数，
    不按 kind 分化子类型（M7-Q1 裁决）。
    """

    kind: NodeEventKind  # 必填
    payload: Mapping[str, object]  # 必填
    task_id: str | None  # 可选，对齐 ws 公共头 task_id
    event_version: str  # 必填，契约演进版本


def make_event(
    kind: NodeEventKind,
    payload: Mapping[str, object] | None = None,
    *,
    task_id: str | None = None,
) -> NodeEvent:
    """构造 NodeEvent；kind 必须在 NodeEventKind 内，否则 ValueError。

    ``confirm_ack`` 由收包循环直产，不允许图节点产出，故不在白名单内。
    """
    if kind not in _NODE_EVENT_KIND_VALUES:
        raise ValueError(f"未知事件类型：{kind}")
    return NodeEvent(
        kind=kind,
        payload=dict(payload or {}),
        task_id=task_id,
        event_version=EVENT_VERSION,
    )


def is_persistent(kind: NodeEventKind) -> bool:
    """NodeEventKind 全部为持久化事件（瞬态帧不进本枚举）；委托 shared 注册表。"""
    return kind in PERSISTENT_KINDS
