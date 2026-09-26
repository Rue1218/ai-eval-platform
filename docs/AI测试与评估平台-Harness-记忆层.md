# AI 测试与评估平台 — Harness 记忆层模块设计

> **当前状态（2026-09-26）**：正文旧 GraphState、`sessions.compact_summary` 和历史规划器内容是历史设计；AgentLoop v2 的当前实现与本地联调见文末 V0.4.5–V0.4.8，以 API V2.30 为接口权威。个人主动保存与关键词召回已接线，语义向量检索、Redis 记忆与团队共享记忆仍未交付。

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 记忆层模块设计 |
| 版本 | V0.4.8 |
| 审查日期 | 2026-09-26 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M3 记忆层（`app/harness/memory/`，含 GraphState 主体 `state.py`） |
| 上游权威 | Harness 需求文档 V1.4.4 §4.3、§2.4、§2.5、§7、§9；API.md V1.22 §3.4；PRD §5.1.3 |

> **阅读关系**：本文是 Harness §9.2「层 3 记忆」行的展开。**GraphState 主体归本层**（`state.py`，按决策从 `orchestration/` 移入）；事件契约在 M7，本层只引用；`pending_events` 的 append reducer + 图外清空策略对齐 M4-Q3 裁决。

---

## 1. 模块定位与边界

### 1.1 定位

记忆层按类型保存、检索、摘要与失效。**记忆不进上下文，而是可检索的状态**。本层承载 GraphState 主体（工作记忆载体）、情景记忆（会话/任务/ws_events）、压缩记忆（摘要派生）、偏好记忆（确认成功后写入）、语义记忆（pgvector + LightRAG，演进项）与权限溯源。

GraphState 是 LangGraph 图的状态容器，由本层定义；编排层（M4）只读写字段、不重定义。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| GraphState 主体定义（`state.py`） | 图拓扑与节点（M4 `app/agent/`） |
| 工作记忆暂态字段（`working.py`） | 节点控制流（M4） |
| 情景记忆：会话/任务/ws_events 持久化与重放（`episodic.py`） | WS 事件 emit / 广播（`ws.py`） |
| 压缩记忆：摘要派生状态（`compressed.py`） | 摘要文本生成（M2 `compact.py`） |
| 偏好记忆：确认成功后写允许字段（`preference.py`） | 偏好的规划建议消费（M4 `plan.py`） |
| 语义记忆：pgvector + LightRAG（`semantic.py`，演进） | LightRAG 服务接入（独立服务，M2/M3 里程碑） |
| 权限过滤与溯源（`acl.py`，演进） | 用户鉴权（`security.py` 通用层） |

### 1.3 红线（继承 Harness §4.3 + §2.4 + §7）

- GraphState 值必须 **JSON 可序列化**（PG 检查点兼容）；**禁止**嵌 `Callable`、DB Session、WS 连接（§2.4）。
- `should_abort` 等回调**不得入 GraphState**（V1.4.1 迁移路径，走 `RunnableConfig.configurable["abort"]["should_abort"]`，见 §2.2/M4-Q2 命名空间）。
- 工作记忆回合结束**不持久化为系统事实**（MEM-1）。
- 原始记录与摘要冲突时**原始优先**（MEM-3）。
- 偏好只作规划建议，**不可绕过 ID 溯源门禁**（MEM-4）。
- 未接入期间 `rag` 任务**必须失败**（`VALIDATION`），不得 mock（MEM-5）。
- 记忆检索带权限过滤与溯源（MEM-6）。
- `pending_events` 用 append reducer，图外收包循环消费后清空（M4-Q3）。

---

## 2. 需求发散

### 2.1 从 Harness §4.3 提取的需求

| 编号 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| MEM-1 | 工作记忆：本轮 Plan、observations、停止标志为回合内暂态 | E-1：`working.py` + GraphState 暂态字段；回合结束不持久化 | 阶段 1 |
| MEM-2 | 情景记忆：sessions/messages/ws_events/tasks 持久化于 PostgreSQL | E-2：`episodic.py` 封装重放与查询；ws_events 重放已落地 | 阶段 1 |
| MEM-3 | 压缩记忆：摘要可更新派生状态，不视为唯一真相 | E-3：`compressed.py` 派生 `sessions.compact_summary`；原始优先 | 阶段 3 |
| MEM-4 | 偏好记忆：仅确认成功入队后写允许字段 | E-4：`preference.py` 写 `settings` 键 `agent_prefs:{user_id}` | 阶段 3 |
| MEM-5 | 语义/知识记忆：pgvector + LightRAG 属演进项，接入前显式带来源检索 | E-5：`semantic.py` 占位，未接入 `rag` 必须失败 | M2/M3 |
| MEM-6 | 记忆检索带权限过滤与溯源（source_id/版本/ACL） | E-6：`acl.py` 检索过滤 + 溯源标注 | M2/M3 |

### 2.2 GraphState 字段发散（M4/M7 依赖）

| 字段 | 类型 | 来源 | 读写方 | 阶段 |
| :--- | :--- | :--- | :--- | :--- |
| `request` | `SerializableRequest` | M3 定义 | M4 路由节点读 | 阶段 1 |
| `mode` | `Literal["chat","direct","react","plan_solve"]`（等价 M4 `AgentMode`） | M4 枚举 | M4 路由节点写，条件边读 | 阶段 1 |
| `pending_events` | `list[NodeEvent]` | M7 契约 | 各节点 append，ws.py 图外消费清空 | 阶段 1 |
| `plan` | `PlanArtifact \| None` | M7 契约 | M4 `plan.py` 写，`plan_solve` 读 | 阶段 4 |
| `observations` | `list[Observation]` | M7 契约 | M5 写，M6/M2 读 | 阶段 2 |
| `stop_flag` | `bool` | M3 | 节点写，条件边读 | 阶段 2 |
| `budget` | `Mapping[str, int]`（M4 `Budget` 的 count-only 可序列化投影） | M4 dataclass | M4 节点读写 | 阶段 2 |
| `verdict` | `Literal["pass","clarify","reject"] \| None`（等价 M4 `ReflectVerdict`） | M4 枚举 | M4 `reflect` 写 | 阶段 4 |
| `response` | `Mapping[str, object]`（`ModelResponse` 投影，可序列化） | M3 定义投影（本体在 M0 `llm/contracts.py`） | M4 `chat_stream_node` 写 | 阶段 1 |

> `should_abort` **不在此表**——走 `RunnableConfig.configurable["abort"]["should_abort"]`（M4-Q2）。
> 注：`mode`/`budget`/`verdict` 在 GraphState 中存**可序列化投影**（内联 Literal/Mapping），与 M4 `AgentMode`/`Budget`/`ReflectVerdict` 等价；M4 dataclass/枚举提供 `to_dict`/`from_dict` 互转，不直接入 State。

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| E-A1 | GraphState 全字段 `json.dumps` 不抛 `TypeError` | 序列化断言 |
| E-A2 | GraphState 不含 `Callable`/`WebSocket`/DB Session 字段 | 反射断言 |
| E-A3 | `pending_events` append reducer：两节点各写 2 事件，State 累积 4 | reducer 断言 |
| E-A4 | 工作记忆回合结束不持久化（stop_flag/observations 回合后清零） | 暂态断言 |
| E-A5 | ws_events 按 `last_event_id` 重放正确 | 重放断言（已落地） |
| E-A6 | 压缩记忆派生状态与原始冲突时原始优先 | 优先级断言 |
| E-A7 | 偏好仅在 `confirm_ack.ok=true` 入队后写入 | 写入时机断言 |
| E-A8 | `rag` 未接入时 `semantic.py` 检索抛 `VALIDATION` | 占位断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/memory/
├── __init__.py        # re-export GraphState / SerializableRequest / replay_events / write_summary / ...
├── state.py          # 阶段 1：GraphState 主体 + SerializableRequest（从 orchestration 移入）
├── working.py        # 阶段 1：工作记忆暂态字段构造与回合清理
├── episodic.py       # 阶段 1：情景记忆（ws_events 重放 + 会话/任务查询封装）
├── compressed.py     # 阶段 3：压缩记忆（摘要派生 sessions.compact_summary）
├── preference.py    # 阶段 3：偏好记忆（确认成功后写 settings:agent_prefs:{user_id}）
├── semantic.py       # M2/M3：语义记忆占位（pgvector + LightRAG，未接入必失败）
└── acl.py            # M2/M3：权限过滤与溯源
```

### 3.2 state.py（阶段 1 落地，GraphState 主体）

**职责**：定义 LangGraph 图的状态容器，全部字段 JSON 可序列化。本文件是 M4/M7/M5/M6 的公共状态底座。

- **`SerializableRequest`**：`ModelRequest` 移除 `should_abort` 后的可序列化投影（`config`/`messages`/`system`/`tools`），由 M4 节点从 `RunnableConfig` 取回调后构造 `ModelRequest` 传给 `ModelGateway`；`tools` 承接 M2 `assemble` 产出的工具定义。
- **`GraphState`**：TypedDict，字段见 §2.2；`pending_events` 用 `Annotated[list[NodeEvent], add]` append reducer。
- **可序列化约束**：所有字段类型为 `str`/`int`/`bool`/`None`/`list`/`Mapping`/M7 frozen dataclass（提供 `to_dict`）；禁嵌回调与连接。
- **`pending_events` 清空策略**（M4-Q3）：append reducer 在图内累积；ws.py 通过 `astream` 的 `updates` 模式按节点边界读取该节点的增量事件并 emit；图终态后由 ws.py 置空（图外清空，非图内节点清空）。**检查点恢复语义**留阶段 3 接 Checkpointer 时定（见 §7）。

### 3.3 working.py（阶段 1 落地）

**职责**：工作记忆暂态字段（MEM-1）。

- 本轮 Plan（`plan`）、observations（`observations`）、停止标志（`stop_flag`）为回合内暂态。
- **回合结束不持久化**：图终态后这些字段不写入 DB；下一回合 GraphState 重置（阶段 0/1 进程内会话注册表承载，阶段 3 由 Checkpointer 按 `thread_id` 隔离回合）。
- `reset_working(state)`：回合清理函数，清零 `observations`/`stop_flag`（`plan` 按 `allows_replan` 决定是否保留）。

### 3.4 episodic.py（阶段 1 落地）

**职责**：情景记忆（MEM-2），封装会话/任务/ws_events 持久化与重放。

- **ws_events 重放已落地**（`ws.py:_replay_events`，按 `last_event_id` 补发）；本模块封装查询接口供 M4/M5 使用。
- `replay_events(db, session_id, last_event_id)`：返回待补发事件列表。
- `append_event(db, session_id, event, payload, task_id)`：写 `ws_events`（对齐 `ws.py:_emit_persistent` 的事件号取号逻辑）。
- 会话/任务查询：`get_session`/`get_active_tasks` 供 M4 门禁（OR-7）使用。

### 3.5 compressed.py（阶段 3 落地）

**职责**：压缩记忆（MEM-3），摘要派生状态。

- 派生 `sessions.compact_summary`（TEXT 字段，API.md §3.4）。
- **原始优先**：摘要与原始记录冲突时，`window.py` 装配仍以原始消息为准，摘要仅作上下文补充。
- 写入由 M2 `compact.py` 产出摘要文本，本模块负责写库（`sessions` 表更新）。

### 3.6 preference.py（阶段 3 落地）

**职责**：偏好记忆（MEM-4）。

- **写入时机**：仅 `confirm_ack.ok=true` 且任务已入队后写（API.md §3.4）。
- **存储**：`settings` 键 `agent_prefs:{user_id}`（跨会话下单偏好，只读对外，无 PUT）。
- **用途**：只作 M4 `plan.py` 规划建议，**不可绕过 ID 溯源门禁**（MEM-4）。

### 3.7 semantic.py（M2/M3 演进，占位）

**职责**：语义/知识记忆（MEM-5），pgvector + LightRAG。

- **当前占位**：未接入，`retrieve(query)` 直接抛 `AppError(VALIDATION, "RAG 语义记忆未接入")`。
- **接入前**：`kind=rag` 任务必须失败，**不得 mock `succeeded`**（Harness §7 红线）。
- 接入后显式带来源检索（`source_id`/版本），与 `acl.py` 协作过滤。

### 3.8 acl.py（M2/M3 演进）

**职责**：权限过滤与溯源（MEM-6）。

- 记忆检索带权限过滤（用户/会话可见性）与溯源标注（`source_id`/版本/ACL）。
- 越权记录不可检索；与 `session_access.require_visible_session` 协作。

### 3.9 接口签名规格（签名级）

#### 3.9.1 state.py（GraphState 主体）

```python
from typing import Annotated, Literal, Mapping, TypedDict
from app.harness.contracts import NodeEvent, Observation, PlanArtifact

# ModelRequest 移除 should_abort 后的可序列化投影
class SerializableRequest(TypedDict, total=False):
    config: Mapping[str, object]        # ModelConfig 投影（protocol/base_url/model/...，api_key 不入 State）
    messages: tuple[Mapping[str, object], ...]   # ModelRequest.messages（tuple[Message,...]）的可序列化投影
    system: str | None
    tools: tuple[Mapping[str, object], ...]   # M2 assemble 产出的工具定义（CX-5），承接 ModelRequest.tools

# append reducer：节点返回的 pending_events 追加到 State
def _append_events(left: list[NodeEvent], right: list[NodeEvent]) -> list[NodeEvent]:
    """LangGraph reducer：追加新事件，不覆盖。"""
    return (left or []) + (right or [])

class GraphState(TypedDict, total=False):
    """LangGraph 图状态容器；全部字段 JSON 可序列化。主体归本层。"""
    request: SerializableRequest
    mode: Literal["chat", "direct", "react", "plan_solve"]
    pending_events: Annotated[list[NodeEvent], _append_events]
    plan: PlanArtifact | None
    observations: list[Observation]
    stop_flag: bool
    budget: Mapping[str, int]            # Budget 投影（count-only）
    verdict: Literal["pass", "clarify", "reject"] | None
    response: Mapping[str, object]       # ModelResponse 投影（text/usage/latency_ms）

def to_serializable_request(req) -> SerializableRequest:
    """把含回调的请求转为可序列化投影（剔除 should_abort）。"""

def assert_serializable(state: GraphState) -> None:
    """断言 GraphState 全字段 json.dumps 安全（E-A1/A2）。"""
```

> `api_key` 不入 `SerializableRequest.config`——密钥保护红线；节点从 `RunnableConfig` 或 DB 取协议档时即时注入 `ModelGateway`，不进 State。

#### 3.9.2 working.py

```python
def reset_working(state: dict) -> dict:
    """回合清理：清零 observations/stop_flag；
    plan 按 allows_replan 决定保留与否（MEM-1）。返回更新 patch。"""

def new_working() -> dict:
    """构造空工作记忆字段（observations=[], stop_flag=False）。"""
```

#### 3.9.3 episodic.py

```python
from app.models import WsEvent

def replay_events(db, session_id: str, last_event_id: int) -> list[WsEvent]:
    """按 last_event_id 补发持久化事件（MEM-2，已落地逻辑封装）。"""

def append_event(db, session_id: str, event: str, payload: dict,
                 *, task_id: str | None = None) -> int:
    """写 ws_events，返回 event_id（对齐 ws.py 取号逻辑）。"""

def get_active_tasks(db, session_id: str) -> list:
    """查询会话非终态任务，供 M4 OR-7 占槽门禁。"""
```

#### 3.9.4 compressed.py

```python
def write_summary(db, session_id: str, summary: str) -> None:
    """写 sessions.compact_summary（MEM-3 派生状态）。
    摘要文本由 M2 compact.py 产出。"""

def get_summary(db, session_id: str) -> str | None:
    """读 compact_summary，供 M2 assembly.py 装配。"""
```

#### 3.9.5 preference.py

```python
def write_prefs(db, user_id: str, prefs: dict) -> None:
    """仅 confirm_ack.ok=true 入队后写 settings:agent_prefs:{user_id}（MEM-4）。"""

def read_prefs(db, user_id: str) -> dict:
    """读偏好，供 M4 plan.py 规划建议；不可绕过 ID 溯源门禁。"""
```

#### 3.9.6 semantic.py（占位）

```python
from app.errors import AppError, ErrorCode

def retrieve(query: str) -> list:
    """语义记忆检索占位：未接入，抛 AppError(VALIDATION, "RAG 语义记忆未接入")。
    接入后显式带来源（source_id/版本），与 acl.py 协作过滤。"""
    raise AppError(ErrorCode.VALIDATION, "RAG 语义记忆未接入")
```

#### 3.9.7 acl.py（演进）

```python
def filter_visible(records: list, user_id: str) -> list:
    """权限过滤：剔除越权记录（MEM-6）。"""

def annotate_source(record: dict) -> dict:
    """溯源标注：补 source_id/版本/ACL。"""
```

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_memory.py`（含 `test_graph_state.py`）

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_graph_state_all_fields_json_serializable` | E-A1 |
| `test_graph_state_no_callable_or_websocket_fields` | E-A2 |
| `test_pending_events_append_reducer_accumulates` | E-A3 |
| `test_working_memory_reset_clears_observations_stop_flag` | E-A4 |
| `test_reset_working_respects_allows_replan_for_plan` | E-A4 |
| `test_replay_events_by_last_event_id` | E-A5 |
| `test_compressed_summary_original_wins_on_conflict` | E-A6 |
| `test_preference_written_only_after_confirm_ack_ok` | E-A7 |
| `test_semantic_retrieve_raises_validation_when_not_wired` | E-A8 |

**TDD 顺序**：先写 `test_graph_state.py`（阶段 1）全红 → 实现 `state.py`/`working.py`/`episodic.py` → 全绿；阶段 3 补 `compressed`/`preference` 测试；M2/M3 补 `semantic`/`acl` 占位测试。`episodic.py` 重放测试需 DB 夹具。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/memory/__init__.py` | 阶段 1 | 修改（re-export） | — |
| `app/harness/memory/state.py` | 阶段 1 | 新增（从 orchestration 移入） | GraphState 主体、SerializableRequest |
| `app/harness/memory/working.py` | 阶段 1 | 新增 | MEM-1、E-1 |
| `app/harness/memory/episodic.py` | 阶段 1 | 新增 | MEM-2、E-2 |
| `app/harness/memory/compressed.py` | 阶段 3 | 新增 | MEM-3、E-3 |
| `app/harness/memory/preference.py` | 阶段 3 | 新增 | MEM-4、E-4 |
| `app/harness/memory/semantic.py` | M2/M3 | 新增（占位） | MEM-5、E-5 |
| `app/harness/memory/acl.py` | M2/M3 | 新增 | MEM-6、E-6 |
| `backend/api/tests/test_harness_memory.py` | 阶段 1/3/M2 | 新增 | E-A1~E-A8 |

> **Harness §9.1 已对齐 V1.4.3**：`state.py` 从 `app/harness/orchestration/` 移到 `app/harness/memory/`（本模块）。

---

## 6. 依赖与红线

- **上游依赖**：Harness §4.3（MEM-1~6）、§2.4（可序列化）、§2.5（pending_events）、API.md §3.4（compact_summary/agent_prefs）、PRD §5.1.3。
- **下游被依赖**：M4（GraphState 主体 + `episodic.get_active_tasks` 门禁）、M5（`observations` 字段）、M6（`observations`/`verdict`）、M2（`compressed.get_summary`/`episodic.replay_events`）、`ws.py`（`pending_events` 消费 + `episodic.append_event`）。
- **跨层协作**：M7（`NodeEvent`/`Observation`/`PlanArtifact` 契约）、M4（`Budget`/`AgentMode`/`ReflectVerdict` 枚举）。
- **红线**：
  - GraphState 可序列化，禁嵌回调/连接；
  - `should_abort` 不入 State；
  - `api_key` 不入 `SerializableRequest.config`；
  - 工作记忆回合结束不持久化；
  - 原始优先于摘要；
  - 偏好不可绕过溯源门禁；
  - `rag` 未接入必失败，禁止 mock；
  - `pending_events` append reducer + 图外清空。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M3-D1 | GraphState 主体归属 | 归本层 `memory/state.py`（从 orchestration 移入） |
| M3-D2 | `SerializableRequest` 定义 | 本层定义，`ModelRequest` 移除 `should_abort` 后的投影；`api_key` 不入 State |
| M3-D3 | `pending_events` reducer | append reducer（`Annotated[list, _append_events]`），图内累积，图外 ws.py 消费清空 |
| M3-D4 | `pending_events` 检查点恢复语义 | **已闭环**（V0.4.1 同步 M9-D3 裁决）：检查点保存图终态累积的 `pending_events`，但**恢复时重置为空**——事件已由 `ws_events` 持久化，断线重放走 `ws_events`，不依赖检查点，避免重复 emit；仅恢复 `mode`/`plan`/`verdict` 等控制字段 |
| M3-D5 | `semantic.py` 未接入行为 | 直接抛 `VALIDATION`，禁止 mock `succeeded` |
| M3-D6 | 偏好写入时机 | 仅 `confirm_ack.ok=true` 入队后写 `settings:agent_prefs:{user_id}` |

> **M3-D4 原「阶段 3 待定」已闭环**：由 M9（运行时基础设施）§7 M9-D3 承接解决——检查点保存累积 `pending_events`，恢复时重置为空，对外事件一律走 `ws_events` 断线重放，不依赖检查点。本模块不再保留检查点恢复待定项。

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.22 §3.4 为唯一真理。M3 是后端内部状态层，**前端无直接对接**：GraphState、工作记忆、情景记忆、压缩记忆均为后端内部状态，不下发前端。M3 对前端的影响是**间接的**——`preference.py` 写入的 `agent_prefs` 经 `GET /api/agent/prefs` 下发，前端用于确认卡预填；GraphState 投影字段（`mode`/`verdict`/`budget`）经 M4 节点产出的事件影响前端 stage 展示。前端不臆造字段，发现契约缺失先回写 API.md 再实现。

### 8.1 对应前端组件与任务

| M3 文件 | 前端影响 | 前端文件 | 对接契约 | 落地阶段 | 验收点 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `preference.py` `write_prefs`/`get_prefs` | 确认卡预填上次选择 | `views/Agent.vue` | API.md §3.4 `GET /api/agent/prefs` | 阶段 3/4 | 新建会话首单预填上次选择；`confirm_ack.ok=true` 后服务端写 prefs |
| `state.py` GraphState 投影（`mode`/`verdict`/`budget`） | 间接影响 `harnessStage` 与错误码 | `views/Agent.vue` `harnessStage`；`api/types.ts` | M3 §3.9.1 + M4 §3.5 | 阶段 1/2/4 | `mode='plan_solve'` 投影为前端 `harnessStage='plan_solve'`；`budget` 超限投影为 `BUDGET_EXCEEDED` |
| `compressed.py` `write_summary` | 间接影响 `compact_summary` 展示 | `components/agent/ContextMeter.vue` | API.md §3.4 `compact_summary` + M2 §3.5 | 阶段 3 | 前端只读 `compact_summary`，不解析压缩记忆内部 |
| `working.py`/`episodic.py` | 后端内部（无前端对接） | — | — | 阶段 1 | 前端无直接对接 |

### 8.2 前端验收要点

- **`/api/agent/prefs` 预填**：前端调 `GET /api/agent/prefs` 预填确认卡，prefs 由 M3 `preference.py` 写入（`confirm_ack.ok=true` 后）。
- **GraphState 投影不直传**：前端不读取 GraphState，只通过 M4 节点产出的 WS 事件感知 `mode`/`verdict`/`budget` 投影。
- **压缩记忆不泄漏**：前端只读 `compact_summary` 文本，不获取压缩记忆内部提示词（AGENTS.md：避免把压缩提示词泄漏到浏览器）。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-记忆层.md` | 新增 V0.3 → 修订 V0.4 → 修订 V0.4.1 → **修订 V0.4.2** | V0.3–V0.4.1 为设计与裁决；**V0.4.2**：`InMemoryCheckpointer` 改为进程内锁（WS / REST / TTL 可见同一份）；`cleanup_session_checkpoints` 按 `{session_id}:` 前缀联动软删除。 |

本文档仅设计记忆层，不改变任何 API、数据库、前端或 Agent 运行代码。

## AgentLoop v2 记忆增量（V0.4.3，2026-09-09）

新路径使用 PostgreSQL 事实作为恢复与模型消息的唯一权威；旧 GraphState/checkpointer 继续服务旧引擎。user、assistant、工具原始结果及必要供应商状态按事实重建。UI 的 messages、工具卡和统一事件流是事务投影，脱敏摘要不能反向充当下一轮模型输入。

请求追踪保存历史高水位、确定性的消息选择索引与输入指纹，使裁剪后的实际请求可重建。恢复补齐尚未结算的调用：未派发记 not_started，已派发而无可信结果记 outcome_unknown；不重新执行有副作用的工具。已提交的 task/queued 用真实任务回执补齐结果，避免恢复重复入队。未知工作区执行保留持久隔离；回合结束不代表解除隔离。

### 本次修改代码文件与作用清单

- `backend/api/app/harness/memory/agent_events.py`：PG 事实、原子投影、幂等回执、读模型与 Writer fence。
- `backend/api/app/harness/memory/agent_messages.py`：规范模型消息与完整工具往返重建。
- `backend/api/app/harness/memory/agent_recovery.py`：补偿事实、三类卡片恢复及未知执行结算。
- `backend/api/app/agent/loop.py`：每次实际请求的历史选择与指纹记录。

## AgentLoop v2 摘要与配置建议（V0.4.4，2026-09-26）

| 能力 | 当前实现与边界 |
| :--- | :--- |
| 会话情景记忆 | PG 原始事实、规范消息与工具结果可恢复；恢复不自动重放副作用。 |
| 会话压缩记忆 | 已由 `agent/compaction.py` 接入 v2 请求前准备，85% 触发、65% 目标，最多三次摘要调用；成功写 `context/compacted`，不写旧 `sessions.compact_summary`。 |
| 原文证据与来源 | 有界保留最多三条完整用户文本，按来源核验；主运行可通过 `history.read` 分页回读当前日志，摘要和证据不向普通诊断流公开。 |
| 结构化配置建议 | v2 确认入队同事务保存既有偏好字段，只在本人私有主会话中复验资源后注入；不代表永久偏好或任务已完成。已消费个人偏好的会话禁止转团队共享。 |
| 语义／长期记忆 | 演进设计，`semantic.retrieve` 仍占位；没有通用个人信息抽取、事实管理及跨会话语义召回。独立的 Worker RAG 评测按实际检索与降级契约执行，不受此占位模块状态影响。 |
| Redis 与记忆权限层 | Redis 不承担当前 v2 记忆主链路；现有会话 ACL 不等于完整长期记忆检索 ACL。 |

上述自动摘要和配置建议以 API V2.24–V2.27、PRD V1.44–V1.46 为准，不恢复旧手动 `/compact`。确定性恢复、来源和隔离测试与真实供应商摘要质量验收分别记录；本地实现不能直接称为生产交付。

### 修改代码文件与作用清单

- `backend/api/app/agent/{compaction,history,loop_wiring}.py`：摘要恢复、原文证据、运行内来源回读与偏好装配。
- `backend/api/app/harness/memory/preference.py`：复用既有偏好字段并复验引用资源。
- `backend/api/app/routers/sessions.py`：个人偏好消费后的共享隔离。
- `backend/api/app/harness/contracts/loop_events.py` 和对应 API 回归：来源、证据及敏感数据契约。

## AgentLoop v2 个人长期记忆（V0.4.5，2026-09-26）

本期在 `/memories` 提供本人记忆的新增、查看、搜索、更正和删除，契约以 API V2.28、PRD V1.47 为准。用户手工保存常用偏好或事实资料，选择个人全局或本人工作区；不自动抽取对话，不提供模型写记忆工具。事实资料属于用户提交的参考，不代表平台核验结果。

复用已有 PostgreSQL `memory_knowledge` 表，不新增表或迁移。个人记录使用独立 `personal:<user_id>` 命名空间、严格私有 ACL、类型标记和 `manual:<id>` 来源；版本递增，更新与撤回检查提交版本。撤回清空记忆正文与标题并排除后续召回，不追溯抹除已有对话、模型回答或请求审计。管理列表保留已失效的工作区归属，允许更正或删除；召回不把失效工作区记忆降级为全局。

仅本人私有主会话逐次读取有效记录。数据库先执行权限与范围过滤，最多 200 条候选以英文词和中文双字词做确定性排序；偏好可作为默认建议，事实资料须匹配当前用户问题。单次最多 5 条、序列化估算不超过 2048 tokens，不截断半条事实。召回段不缓存，进入实际请求预算与 `memory_files`；当前明确指令优先，记忆不能授权工具或替代任务确认。摘要等待后再次读取，最新资料造成请求超限时按预算错误结束，不越界发送。

配置建议和个人记忆共用会话行锁与无正文消费审计；已消费个人上下文的会话不能转为团队共享。子运行、团队会话及非属主访问不加载个人记忆。向量语义检索、团队知识记忆、自动抽取、Redis 记忆主链路仍未交付，旧 `semantic.retrieve` 占位状态不变。

### 修改代码文件与作用清单

- `backend/api/app/harness/memory/personal.py`：个人记录管理、版本校验、权限过滤、有界关键词召回与安全审计。
- `backend/api/app/routers/agent_memories.py`、`backend/api/app/main.py`：管理接口及路由注册。
- `backend/api/app/harness/memory/preference.py`、`backend/api/app/agent/loop_wiring.py`：私有会话隔离、逐请求读取、摘要后刷新与同源预算。
- `frontend/src/api/agentMemories.ts`、`frontend/src/views/UserMemories.vue`、路由与侧栏：记忆管理页面、范围选择及冲突提示。
- 个人记忆 ORM、HTTP、运行接线与浏览器回归：覆盖跨用户、跨工作区、更正、撤回、预算和旧版本冲突；PostgreSQL 行锁测试需显式测试数据库，跳过不能视为通过。

## V0.4.6（2026-09-26）— 凭据边界与失效范围恢复

个人记忆与压缩证据共用已知凭据值识别，避免个人记忆拒绝的敏感内容经压缩原文证据重新注入。新证据整条停止，旧证据先验真再仅保留敏感项之后的安全后缀；不改写原始会话或存量摘要正文。

工作区在编辑期间注销时，保存失败会刷新工作区目录并保留草稿与原选择，用户可在当前弹窗明确改选后保存；不自动扩大为全局。真正的记忆不可访问和版本冲突仍禁止旧版本提交。契约见 API V2.29、PRD V1.48。

### 修改代码文件与作用清单

- `backend/api/app/harness/security/loop_redaction.py`、`backend/api/app/harness/memory/personal.py`、`backend/api/app/agent/compaction.py`：共用识别及压缩派生记忆边界。
- `frontend/src/views/UserMemories.vue`、`frontend/tests/e2e/userMemories.spec.ts`：动态范围失效、草稿恢复和真实版本冲突区分。

## V0.4.7（2026-09-26）— 本地真实前后端联调

本次使用真实 Vue/Vite、FastAPI、Cookie 鉴权、WebSocket v2 和独立 PostgreSQL 18.4，完整运行 Alembic 至 `110e3362fba3`。浏览器没有拦截或伪造业务 HTTP 响应；数据库、账号、工作区和协议档环境文件均在临时环境，与本机已有服务和生产数据隔离。

| 验证范围 | 本次结果 |
| :--- | :--- |
| 记忆页面 | 10 个浏览器场景通过：登录导航、增删改查与刷新持久化、偏好与事实范围筛选、更新/删除 409、编辑/新建时工作区失效 404、记忆撤回 404、390px 窄屏保存与来源换行、51 条记录分页及删除末页唯一记录后自动回退。宽屏和窄屏均无横向溢出，无浏览器运行时异常。 |
| 权限与审计 | 43 项真实 HTTP/PG 断言通过：不同成员互不可见、跨用户更新/删除和绑定工作区返回 404；全局与工作区筛选正确，版本递增，旧版本返回 409，重新登录仍读取更正；审计不含记忆标题/正文，撤回清空标题和正文。 |
| Agent 对话 | 8 项浏览器断言通过：本人私有会话注入偏好、更正后下一轮使用新版本、撤回后下一轮停止注入、匹配工作区事实召回、团队会话不注入个人资料、消费个人资料的未绑定会话拒绝共享、实际请求记忆计量可见、浏览器无运行时异常。 |
| 上下文压缩与回放 | 独立 12000 tokens 协议档完成 6 轮对话、8 项断言；第 3/5 轮触发摘要，压缩后实际请求估算输入均为 6921 tokens，各轮输入与输出预留均未超过窗口。收到持久压缩事实及摘要用量，轨迹不公开摘要正文；新浏览器进入及刷新后仍重放 6 轮终态、压缩事件和 `context_meter.compacted=true`，前端保留摘要提示与记忆计量。 |
| PostgreSQL 回归 | `test_personal_memory_pg.py` 4 项、`test_loop_preferences_pg.py` 4 项、`test_loop_store_pg.py` 6 项，共 **14 passed / 0 skipped**；覆盖真实 JSONB、行锁配额、乐观版本、偏好原子性与事实存储。 |

模型上游使用本机确定性 Chat Completions 服务，保留真实 OpenAI SDK/Adapter 与 SSE 解码。只从本次个人记忆系统段回显预置测试标记，历史中的旧标记不算本次召回。上述结果证明请求装配、权限、持久化和前端呈现；**不证明真实供应商的摘要质量或语义理解，返回 token 用量也是测试值**。测试库未安装 pgvector，使用现有迁移的 nullable Text 回退；不覆盖向量检索，也不等于生产 PostgreSQL 16 验收。短票使用既有进程内回退，不作为 Redis 验收。

### 修改代码文件与作用清单

- `docs/AI测试与评估平台-Harness-记忆层.md`：记录联调环境、通过场景及证据边界；本次联调未发现需要修改应用代码的问题。

## V0.4.8（2026-09-26）— 编辑期间工作区故障恢复

工作区复验失败时，记忆编辑弹窗内显示错误和“重试加载工作区”，无需关闭弹窗即可恢复目录；草稿、原版本和原选择保持不变。重试只读目录，不自动保存、覆盖新版本或扩大范围。目录恢复后如确认原工作区已失效，仍需用户明确改选。

### 修改代码文件与作用清单

- `frontend/src/views/UserMemories.vue`：编辑器内显示目录错误及原位重试入口。
- `frontend/tests/e2e/userMemories.spec.ts`：注入目录请求故障，验证恢复后草稿、版本和范围约束。
