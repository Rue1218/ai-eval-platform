# AI 测试与评估平台 — Harness 跨层契约层模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 跨层契约层模块设计 |
| 版本 | V0.4.3 |
| 审查日期 | 2026-09-09 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计） |
| 适用模块 | M7 跨层契约层（`app/harness/contracts/`） |
| 上游权威 | Harness 需求文档 V1.4.4 §2.5、§4 各层、§7、§9；API.md V1.22 §4.3/§4.4/§5；PRD §5.1.3 |

> **阅读关系**：本文是 Harness 需求文档 §9.2「跨层契约」行的展开。GraphState 主体不在此层（归 M3 记忆层，`app/harness/memory/state.py`），本文只定义被 GraphState 引用的契约类型。

---

## 1. 模块定位与边界

### 1.1 定位

跨层契约层是 Harness 六层的**类型公共底座**：把"图节点返回纯数据""PlanArtifact""SkillHint""Observation"等跨层共享结构收敛为可序列化 TypedDict / dataclass，供编排层（M4）、执行层（M5）、反馈层（M6）、记忆层（M3）引用。

本层**不含任何控制流、不持有 WS 连接、不访问数据库**，只定义类型与最小构造/校验函数。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 图节点输出事件契约（`events.py`） | GraphState 主体定义（M3 `memory/state.py`） |
| PlanArtifact / SkillHint / Observation 等 artifact（`artifacts.py`） | 事件 emit / WS 广播（`ws.py` 收包循环） |
| 契约的可序列化约束与最小校验 | 工具注册表元数据（M5 `registry.py`） |
| 事件类型枚举（与 API.md §4.3 ws event 对齐） | 确认卡业务字段（PRD §5.1.2，M4 `confirm.py`） |

### 1.3 红线（继承 Harness §7）

- 契约类型必须 **JSON 可序列化**（PG 检查点兼容）；禁止嵌 `Callable`、DB Session、WS 连接。
- 事件类型枚举不得超出 API.md §4.3 已定义的 ws event 集合，**不私自扩充对外字段**。
- `should_abort` 等回调不得出现在任何契约类型中（V1.4.1 迁移路径）。

---

## 2. 需求发散

### 2.1 从 Harness §4 提取的契约相关需求

| 来源 | 需求 | 发散为本模块子需求 |
| :--- | :--- | :--- |
| §2.5 事件桥接契约 | 图节点只返回纯数据，事件由收包循环统一发出 | C-1：定义 `NodeEvent` TypedDict + `NodeEventKind` 枚举，覆盖 API.md §4.3 持久化事件中的图节点产出子集（归属矩阵见 §3.6.1） |
| §2.5 | 节点内禁止持有 WS 连接/emit 回调 | C-2：契约类型不得引用 `WebSocket` / `Callable` |
| §4.4 OR-2 | `PlanArtifact` 冻结字段 | C-3：`PlanArtifact` 字段 = intent/skill_id/slots/tools_needed/delivery/budget/allows_replan/notes |
| §4.5 EX-1 | 工具元数据唯一来源为注册表 | C-4：`ToolCall` / `ToolResult` 契约与注册表元数据对齐（元数据本身在 M5） |
| §4.6 FB-1 | 工具结果归一为 observation | C-5：`Observation` 契约（带 `truncated` / `source` / 脱敏标记） |
| §4.3 MEM-1 | 工作记忆为回合内暂态 | C-6：契约可被 GraphState 引用为暂态字段（GraphState 主体在 M3） |
| §2.4 | 状态值必须可序列化 JSON | C-7：所有契约提供 `to_dict()` / `from_dict()` 往返测试 |

### 2.2 从 API.md §4.3 对齐的事件集合

持久化事件（落 `ws_events`，可回放）：`user_message` / `thought`(think_final) / `tool_call` / `tool_result` / `confirm` / `confirm_ack` / `clarify` / `plan` / `progress` / `report` / `error` / `assistant_message` / `response.completed`。

> 注：`confirm_ack` 属持久化事件（API.md §4.3 落库可回放），但由 `ws.py` 收包循环直连 emit（确认卡回执，非图节点产出），**不进 `NodeEventKind` 枚举**——`NodeEvent` 只覆盖图节点返回的事件意图。

瞬态事件（不落库，不占事件号）：`assistant_delta` / `thought.stream=think` / `pong`。

> 契约只覆盖**节点返回的持久化事件意图**；瞬态帧由节点通过 `get_stream_writer` 直接投影（沿用 `gateway.py` / `graph.py` 现有实现），不进 `NodeEvent` 枚举。

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| C-A1 | `NodeEvent` kind 与 API.md §4.3 持久化事件对齐（图节点产出子集），且生产者归属矩阵与 §3.6.1 一致 | 枚举集合断言 + 归属矩阵断言 |
| C-A2 | 所有契约 `to_dict` → `from_dict` 往返相等 | 属性测试 |
| C-A3 | 契约类型 `json.dumps` 不抛 `TypeError` | 序列化断言 |
| C-A4 | `NodeEvent` 不含 `Callable` / `WebSocket` 字段 | 反射断言 |
| C-A5 | `PlanArtifact` schema 校验拒绝缺字段 / 多字段 | schema 单测 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/contracts/
├── __init__.py          # re-export NodeEvent/NodeEventKind/PlanArtifact/SkillHint/Observation/ToolCall/ToolResult
├── events.py            # 阶段 1：图节点返回纯数据契约（TypedDict + 枚举）
└── artifacts.py         # 阶段 2（早：ToolCall/ToolResult/Observation）→ 阶段 4（晚：PlanArtifact/SkillHint）
```

### 3.2 events.py（阶段 1 落地）

**职责**：定义图节点返回的"事件意图 + payload"纯数据结构，供 M4 编排层节点产出、`ws.py` 收包循环翻译为 ws event。

**核心类型（设计意图，非签名）**：

- `NodeEventKind`：字符串字面量枚举，取值 = API.md §4.3 持久化事件中**图节点可产出**的子集（生产者归属矩阵见 §3.6.1）。
- `NodeEvent`：TypedDict，字段 `kind: NodeEventKind` + `payload: Mapping[str, object]` + 可选 `task_id: str | None`。
- 节点返回 `NodeEvent | list[NodeEvent]`，由 M4 编排层 / `ws.py` 统一 `_emit_persistent`。

**与瞬态帧的边界**：`assistant_delta` / `thought.stream=think` 不进 `NodeEvent`，仍由节点 `get_stream_writer` 直接投影（沿用 `gateway.py` / `graph.py` 现有实现）。

**与 GraphState 的关系**：`NodeEvent` 不入 GraphState；节点把待发事件写入 State 的 `pending_events: list[NodeEvent]` 暂态字段（该字段属 M3 GraphState），收包循环消费后清空。

### 3.3 artifacts.py（阶段 2 早波 + 阶段 4 晚波）

**职责**：定义层间共享的 artifact dataclass，全部 frozen + 可序列化。分两波落地：阶段 2 早波（ToolCall/ToolResult/Observation，供 M5/M6/M2 消费）+ 阶段 4 晚波（PlanArtifact/SkillHint，供 M4/M10 消费）。

| 类型 | 用途 | 引用方 |
| :--- | :--- | :--- |
| `PlanArtifact` | 规划产物（OR-2 冻结字段） | M4 `plan.py` 产出，M4 `router.py` 消费 |
| `SkillHint` | 技能名称 + 一句话描述（SK-1） | M4 路由节点注入上下文 |
| `Observation` | 工具结果归一（FB-1，带 truncated/source/脱敏） | M5 `dispatch.py` 产出，M6 `feedback/observation.py` 消费 |
| `ToolCall` | 工具调用契约（name/arguments） | M4 节点产出，M5 `toolnode.py` 消费 |
| `ToolResult` | 工具结果契约（name/ok/data/error） | M5 产出，M6 消费，对齐 API.md `tool_result` 事件 |

### 3.4 数据流

```text
图节点执行
  → 产出 NodeEvent（写入 GraphState.pending_events）
  → 产出 PlanArtifact / ToolCall / Observation（写入 GraphState 对应暂态字段）
  → 图输出
  → M4 编排层 / ws.py 收包循环读 pending_events
  → 翻译为 ws event（_emit_persistent / broadcast_chunk）
  → 断线重放仍走 ws_events，不依赖契约类型
```

### 3.5 跨层引用关系

| 契约类型 | 引用层 | 引用方 |
| :--- | :--- | :--- |
| `NodeEvent` / `NodeEventKind` | M4 编排、M3 记忆、`ws.py` | 节点产出 → State 暂态 → 收包循环 emit |
| `PlanArtifact` | M4 编排 | `plan.py` 产出 → `router.py` 消费 |
| `SkillHint` | M4 编排、M10 技能 | 路由节点注入上下文 |
| `ToolCall` / `ToolResult` | M4 编排、M5 执行、M6 反馈 | 节点 → ToolNode → 归一为 Observation |
| `Observation` | M5 执行、M6 反馈、M2 上下文 | `dispatch.py` 产出 → 反馈归一 → 上下文装配脱敏摘要 |

### 3.6 接口签名规格（签名级）

> 本节给出契约类型的字段定义与构造/校验函数签名，作为 M3/M4/M5/M6 的实现契约。全部 frozen + 可序列化，禁嵌 `Callable`/`WebSocket`/DB Session。

#### 3.6.1 events.py（阶段 1）

```python
from typing import Literal, Mapping, TypedDict

# 图节点产出的持久化事件意图（与 API.md §4.3 持久化事件对齐；confirm_ack 由收包循环直产非节点产出）
# 生产者归属矩阵（V0.4.2 收敛，消除「progress 不入 messages 故不在此」与枚举含 progress 的矛盾）：
#   - 图节点产出：thought / tool_call / tool_result / confirm / clarify / plan / error / assistant_message / response.completed
#   - ws.py 收包循环直产：user_message（用户上行）、confirm_ack（回执）
#   - Worker 直产：progress / report / error（push_ws 写 ws_events，实时转发见 M9）
#   - 节点确需表达 user_message/progress/report 意图时允许产出，但禁止与直产方重复 emit
#   - task.created / task.succeeded / task.failed 为任务事件（写 task_events），不入本枚举
# V0.4：新增 clarify/plan（对齐 API.md V1.21 §4.3）
NodeEventKind = Literal[
    "user_message", "thought", "tool_call", "tool_result",
    "confirm", "clarify", "plan", "progress", "report", "error",
    "assistant_message", "response.completed",
]

class NodeEvent(TypedDict, total=False):
    """图节点返回的纯数据事件意图；由 M4 节点写入 GraphState.pending_events，
    ws.py 收包循环消费后翻译为 ws event。"""
    kind: NodeEventKind               # 必填
    payload: Mapping[str, object]     # 必填，统一 Mapping + 校验函数（不按 kind 分化子类型）
    task_id: str | None               # 可选，对齐 ws 公共头 task_id
    event_version: str                # 必填，契约演进版本（如 "event.v1"）

def make_event(kind: NodeEventKind, payload: Mapping[str, object] | None = None,
               *, task_id: str | None = None) -> NodeEvent:
    """构造 NodeEvent；kind 必须在 NodeEventKind 内，否则 ValueError。"""

def is_persistent(kind: NodeEventKind) -> bool:
    """全部 NodeEventKind 均为持久化事件（瞬态帧不进本枚举）。"""
```

#### 3.6.2 artifacts.py（阶段 2 早波 ToolCall/ToolResult/Observation + 阶段 4 晚波 PlanArtifact/SkillHint）

```python
from dataclasses import dataclass, field
from typing import Literal, Mapping

# —— 阶段 4 晚波 ——
@dataclass(frozen=True, slots=True)
class SkillHint:
    """技能名称 + 一句话描述（SK-1），常驻不常驻正文。"""
    skill_id: str          # 如 "skill-benchmark"
    name: str              # 显示名
    summary: str           # 一句话描述

@dataclass(frozen=True, slots=True)
class PlanArtifact:
    """规划产物（OR-2 冻结字段，含 allows_replan）。"""
    intent: str                       # 意图
    skill_id: str | None              # 关联技能
    slots: Mapping[str, object]      # 槽位
    tools_needed: tuple[str, ...]     # 需要的工具名
    delivery: Literal["chat", "confirm"]  # 交付方式
    budget: Mapping[str, int]         # 次数预算（count-only：model_calls/tool_turns 整数，不含 token 预算）
    allows_replan: bool               # 是否允许补规划
    notes: str = ""

# —— 阶段 2 早波 ——
@dataclass(frozen=True, slots=True)
class ToolCall:
    """工具调用契约（对齐 API.md tool_call 事件 payload）。"""
    name: str
    arguments: Mapping[str, object]

@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具结果契约（对齐 API.md tool_result 事件 payload）。"""
    name: str
    ok: bool
    data: Mapping[str, object] = field(default_factory=dict)
    error: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class Observation:
    """工具结果归一（FB-1），带脱敏/截断/来源标记。"""
    tool: str
    text: str                          # 脱敏 + 截断后的摘要
    ok: bool
    truncated: bool = False
    source: str | None = None          # 溯源标识，复用 messages 表 source_id 格式（如 "file:uuid" / "message:uuid"）
    redacted: bool = True              # 默认已脱敏
```

#### 3.6.3 序列化往返函数签名

```python
from typing import TypeVar, Type

T = TypeVar("T")

def to_dict(obj: T) -> dict:
    """把 frozen dataclass 契约转为纯 dict（json.dumps 安全）。"""

def from_dict(cls: Type[T], data: dict) -> T:
    """从 dict 重建契约；字段缺失/多余抛 ValueError。"""

def validate_plan_artifact(data: dict) -> PlanArtifact:
    """PlanArtifact schema 校验：拒绝缺字段/多字段（C-A5）。"""
```



---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_contracts.py`

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_node_event_kind_matches_api_persistent_events` | C-A1 |
| `test_contracts_roundtrip_to_dict_from_dict` | C-A2 |
| `test_contracts_json_serializable` | C-A3 |
| `test_node_event_has_no_callable_or_websocket_fields` | C-A4 |
| `test_plan_artifact_schema_rejects_missing_extra_fields` | C-A5 |

**TDD 顺序**：先写 `test_harness_contracts.py` 全红 → 实现 `events.py` → 实现 `artifacts.py` → 全绿。本模块不依赖 DB / WS，单测可独立运行（`pytest tests/test_harness_contracts.py`）。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/contracts/__init__.py` | 阶段 1 | 修改（re-export） | — |
| `app/harness/contracts/events.py` | 阶段 1 | 新增 | C-1/C-2/C-7、§2.5 事件桥接契约 |
| `app/harness/contracts/artifacts.py` | 阶段 2（早波）/ 阶段 4（晚波） | 新增（早）/ 修改（晚） | 早波 C-4/C-5（ToolCall/ToolResult/Observation）、晚波 C-3/OR-2（PlanArtifact）、SK-1（SkillHint）、FB-1 |
| `backend/api/tests/test_harness_contracts.py` | 阶段 1/4 | 新增 | C-A1~C-A5 |

> `state.py` **不在本模块**——按决策移至 `app/harness/memory/state.py`（M3 记忆层）。Harness §9.1 已对齐 V1.4.3 回写。

---

## 6. 依赖与红线

- **上游依赖**：API.md §4.3（事件集合）、PRD §5.1.2（确认卡字段，仅 `artifacts.py` 间接引用）、Harness §2.5（事件桥接契约）。
- **下游被依赖**：M3（GraphState 引用契约类型）、M4（节点产出 NodeEvent/PlanArtifact）、M5（ToolCall/ToolResult/Observation）、M6（Observation 消费）、M2（Observation 脱敏摘要）。
- **红线**：不私自扩 ws event 枚举；契约可序列化；回调不入契约。

---

## 7. 已决裁决（开放问题已闭环）

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M7-Q1 | `NodeEvent.payload` 是否按 kind 分化子类型 | **统一 `Mapping[str, object]` + 校验函数**，不分化子类型（保持可序列化简单） |
| M7-Q2 | `Observation.source` 字段格式 | **复用 messages 表 `source_id` 格式**（如 `"file:uuid"` / `"message:uuid"`） |
| M7-Q3 | `PlanArtifact.budget` 结构 | **次数预算（count-only）**：`model_calls`/`tool_turns` 整数，不含 token 预算 |
| M7-Q4 | `NodeEvent` 是否需要版本号 | **加 `event_version: str` 字段**（契约演进，如 `"event.v1"`） |

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.22 §4.3/§4.4 为唯一真理。M7 是前端事件分发的契约源头：`events.py` 的 `NodeEventKind` 与 API.md §4.3 持久化事件对齐（图节点产出子集，归属矩阵见 §3.6.1），`artifacts.py` 的 dataclass 字段即前端渲染数据来源。前端不臆造字段，发现契约缺失先回写 API.md 再实现。

### 8.1 events.py 对应前端事件分发

| NodeEventKind | 前端渲染组件 | 前端文件 | 对接契约 | 落地阶段 |
| :--- | :--- | :--- | :--- | :--- |
| `user_message` | UserBubble | `views/Agent.vue` `handleWsEvent` | API.md §4.3 | 阶段 1 |
| `thought` | ThoughtCard | `components/agent/ThoughtCard.vue` | API.md §4.3（`stage`/`skill_id`/`stream`） | 阶段 1（plan）/2（react）/4（reflect） |
| `tool_call` | ToolCard pending | `components/agent/ToolCard.vue` | API.md §4.3 + M7 §3.6.2 `ToolCall` | 阶段 2 |
| `tool_result` | ToolCard done | `components/agent/ToolCard.vue` | API.md §4.3（V1.22 加 `truncated`/`source`/`redacted`）+ M7 §3.6.2 `Observation` | 阶段 2 |
| `confirm` | ConfirmCard | `views/Agent.vue` 内联卡 / `components/agent/ConfirmCard.vue` | API.md §4.3 + §5/§6 + M7 §3.6.2 | 阶段 4 |
| `clarify`（V0.4 新增） | **ClarifyCard**（新增独立组件） | 新增 `components/agent/ClarifyCard.vue`；`Agent.vue` `handleWsEvent` 加 `clarify` 分支 | API.md §4.3 `clarify`（V1.22 新增）+ M7 §3.6.1 | 阶段 3 |
| `plan`（V0.4 新增） | **PlanCard**（新增独立组件） | 新增 `components/agent/PlanCard.vue`；`Agent.vue` `handleWsEvent` 加 `plan` 分支 | API.md §4.3 `plan`（V1.22 新增）+ M7 §3.6.2 `PlanArtifact` | 阶段 4 |
| `progress` | ProgressDock | `components/agent/ProgressDock.vue` | API.md §4.3 | 阶段 4 |
| `report` | ReportCard | `components/agent/ReportCard.vue` | API.md §4.3 | 阶段 4 |
| `error` | ErrorStrip + Toast | `components/common/ErrorStrip.vue` | API.md §4.3 + §1.3 错误码 | 全阶段 |
| `assistant_message` | AssistantBubble | `views/Agent.vue` | API.md §4.3 | 阶段 1 |
| `response.completed` | 结束流式状态 | `views/Agent.vue` | API.md §4.3 | 阶段 1 |

### 8.2 artifacts.py 对应前端渲染数据

| 契约类型 | 前端用途 | 前端文件 | 验收点 |
| :--- | :--- | :--- | :--- |
| `ToolCall`（name/arguments） | ToolCard 标题 + 参数展示 | `components/agent/ToolCard.vue` | 中文名映射（API.md §4.3 短工具中文名表） |
| `ToolResult`（name/ok/data/error） | ToolCard done 三态 | `components/agent/ToolCard.vue` | `ok=false` 显示 `error` 文案 |
| `Observation`（truncated/source/redacted） | ToolCard 截断/脱敏徽标 | `components/agent/ToolCard.vue` | `truncated=true` 显示「结果已截断」；`redacted=true` 显示「已脱敏」 |
| `PlanArtifact`（intent/skill_id/slots/tools_needed/delivery/budget/allows_replan/notes） | PlanCard 完整展示 | 新增 `components/agent/PlanCard.vue` | 用户可查看无需 ack；字段 1:1 对齐 |
| `SkillHint`（skill_id/name/summary） | SkillBadge + summary 展示 | `components/agent/SkillBadge.vue`、`agent/skillLabels.ts`、`components/modals/SkillDetailModal.vue` | `skill_id` 与 `skillLabels.ts` 4 个 key 匹配；summary 一句话展示 |

### 8.3 前端验收要点

- `handleWsEvent` 覆盖全部 `NodeEventKind`（含 V0.4 新增 `clarify`/`plan`），无遗漏分支。
- `clarify` 与 `confirm` 互斥语义在前端 UI 区分：澄清卡不显示「确认入队」按钮，只显示「回复」输入。
- `PlanArtifact` 字段前端不裁剪，完整展示（用户决策：完全可见）。
- `Observation` 的 `truncated`/`source`/`redacted` 三字段前端均渲染徽标，不静默丢弃。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-跨层契约层.md` | 新增 V0.1 → 修订 V0.2 → 修订 V0.3 → 修订 V0.4 → 修订 V0.4.1 → 修订 V0.4.2 | V0.1 M7 跨层契约层模块设计：定义契约边界、需求发散、架构设计与 TDD 验收；V0.2 升级到接口签名级：补 `NodeEventKind` 枚举、`NodeEvent` TypedDict、各 dataclass 字段、构造/校验函数签名；V0.3 开放问题闭环：`NodeEvent.payload` 统一 Mapping、`Observation.source` 复用 messages `source_id` 格式、`PlanArtifact.budget` count-only、`NodeEvent` 加 `event_version` 字段；V0.4 对齐 API.md V1.21：`NodeEventKind` 枚举新增 `clarify`/`plan`，新增 §8「前端联调」章节；V0.4.1 配合 API.md V1.22：§3.6.1 `NodeEventKind` 注释修正（不再称「与 §4.3 持久化事件 1:1」，改为「节点产出的持久化事件子集」）；V0.4.2 评审收敛版：§8 契约为 API.md V1.22；§2.2 持久化事件列表补齐 `clarify`/`plan`；§3.6.1 新增**生产者归属矩阵**（图节点/收包循环/Worker 三类 producer，消除注释与枚举自相矛盾），C-A1 验收改为归属矩阵断言。 |

本文档仅设计契约层，不改变任何 API、数据库、前端或 Agent 运行代码。

## AgentLoop v2 契约增量（V0.4.3，2026-09-09）

本节记录本次实际后端增量；上文历史设计声明不涵盖本节。API.md V1.77 为公开字段权威。

源工具调用保留 `id/name/args/arguments_raw/parse_error`；工具声明使用 `ToolSpec.parameters`，通过显式 codec 转入平台工具。结果状态为 succeeded、failed、denied、cancelled、not_started、outcome_unknown。模型流统一文本、reasoning、原生工具增量、Done、ProviderItem 与 ProtocolState；EOF 不自动等价于正常 finish。

原始事实的 seq、WS v2 的 cursor 和旧 ws_events.event_id 分工独立。持久投影有 cursor，命令回执、临时正文和 reasoning chunk 无 cursor。`turn.end` 是回合终态；`assistant.end` 仅关闭一次模型输出。所有卡片回执校验身份、turn/attempt/call、nonce 与 TTL。

### 本次修改代码文件与作用清单

- `backend/api/app/llm/loop_contracts.py`：规范请求、消息、chunk、工具与供应商状态。
- `backend/api/app/harness/contracts/loop_events.py`：源事件 schema catalog、生产者与关联字段。
- `backend/api/app/agent/events.py`：事实到公开帧/诊断轨迹投影。
- `backend/api/app/routers/ws_v2.py`：严格命令解析、快照、补发、背压与 ACL。
