"""WS 事件词汇表单一事实源（api/worker 共用，对齐 API.md §4.3）。

来源：dsh 借鉴与 Agent Harness 改进方案 #4（事件词汇表版本化，D1）。
演进纪律（与 API.md §4.3 同步，禁止两处漂移）：

- ``EVENT_VERSION`` 语义化：**增删持久事件 kind 必须递增版本**（event.v1 →
  event.v2 …），演进理由随 API.md §4.3 修订记录留档；
- 历史 ``ws_events`` 中无版本行按当前版本解释（缺省 ``event.v1``，向后兼容只读）；
- 新增/恢复事件类型必须先经契约评审（API.md §4.3 现行清单）再扩展本模块；
- 本模块是 api ``contracts/events.py``（图内契约）与 worker ``events.py::push_ws``
  的**唯一词汇表来源**，禁止再出现第三份碎片集合。

集合划分（生产者归属矩阵，对齐 API.md §3.6.1 / §4.3）：

- ``NODE_EVENT_KINDS``：LangGraph 图节点可经 ``pending_events`` 产出的子集
  （白名单；``confirm_ack`` 等直产事件不可由节点产出）；
- ``PERSISTENT_KINDS``：全部持久化事件（落 ``ws_events``、占 ``event_id``、
  断线重连按 ``last_event_id`` 补发），含 ws.py 收包循环直产
  （``confirm_ack`` / ``task_cancelled`` / ``tool_approval_ack`` / ``session_title``）
  与 Worker 直产（``progress`` / ``report`` / ``error`` / ``thought``）；
- 瞬态帧（``assistant_delta`` / ``pong`` / ``thought.stream=think`` 等）**不进**
  本模块——不落库、不占事件号，词汇表版本只约束持久事件。
"""

from __future__ import annotations

# 事件契约演进版本（M7-Q4 裁决；#4 起语义化：增删 kind 必须递增）。
# V1.72（#1 clarify 恢复）：新增回执事件 clarify_ack → event.v2；
# V1.73（#3 审批终态）：新增终态事件 approval_terminal → event.v3；
# V1.74（#2 压缩事件化）：新增留痕事件 context_trim → event.v4；
# V1.75（原生工具 P3）：新增编造对账事件 fabrication → event.v5。
EVENT_VERSION = "event.v5"

# 图节点可产出的持久化事件意图子集（对齐 NodeEventKind 字面量；make_event 白名单）
NODE_EVENT_KINDS: frozenset[str] = frozenset(
    {
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
        "fabrication",  # V1.75（P3）：收尾声明无工具证据的编造对账留痕（仅审计，不入正文事件）
    }
)

# 收包循环 / 标题后台 / Worker 直产且落库的持久事件（图节点不可经 pending_events 产出）
_EMITTER_ONLY_KINDS: frozenset[str] = frozenset(
    {
        "confirm_ack",
        "task_cancelled",
        "tool_approval_ack",
        "clarify_ack",  # V1.72（#1）：clarify_reply 清卡后的服务端回执（新增 kind 已升版）
        "approval_terminal",  # V1.73（#3）：审批卡终态（expired/cancelled，新增 kind 已升版）
        "context_trim",  # V1.74（#2）：窗口裁剪留痕（仅元信息，不落原文；新增 kind 已升版）
        "session_title",
    }
)

# 全部持久化事件集合（含直产方），供翻译/转发校验与注册表一致性断言使用
PERSISTENT_KINDS: frozenset[str] = NODE_EVENT_KINDS | _EMITTER_ONLY_KINDS


def is_persistent(kind: str) -> bool:
    """判断事件是否属持久事件词汇表（落 ws_events、占 event_id）。"""
    return kind in PERSISTENT_KINDS


def is_node_event(kind: str) -> bool:
    """判断事件是否可由图节点经 make_event/pending_events 产出。"""
    return kind in NODE_EVENT_KINDS
