# AI 测试与评估平台 — Harness 反馈层模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 反馈层模块设计 |
| 版本 | V0.3 |
| 审查日期 | 2026-08-23 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M6 反馈层（`app/harness/feedback/`；`reflect_node` 归 M4 `app/agent/reflect.py`，本层仅提供库函数供其调用） |
| 上游权威 | Harness 需求文档 V1.4.4 §4.6、§2.5、§7、§9；API.md V1.4+；PRD §5.1.3 |

> **阅读关系**：本文是 Harness §9.2「层 6 反馈」行的展开。`Observation` 归一逻辑归本层（M5 `dispatch` 执行后调本层归一）；规则门禁先行；模型辅助核对只能 `pass→clarify` 降级（FB-3）；Worker 事件不污染消息窗口（FB-5，与 M2 协作）。

---

## 1. 模块定位与边界

### 1.1 定位

反馈层把工具结果、校验、外部任务事件变成下一步可信依据。本层提供工具结果归一为 observation（异常不裸抛）、规则门禁先行、模型辅助核对（仅降级不放行）、失败反馈预算约束、Worker 事件与消息窗口隔离。本层不执行工具、不调模型（核对除外）、不持 WS 连接。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 工具结果归一为 observation（`observation.py`，FB-1） | 工具执行（M5 `dispatch.py`） |
| 规则门禁先行（`rules.py`，FB-2） | 门禁调用时机（M4 节点） |
| 模型辅助核对 pass→clarify 降级（`review.py`，FB-3） | 复核 verdict 消费（M4 `reflect` 条件边） |
| 失败反馈预算约束（`budget.py`，FB-4） | 模型调用预算（M4 `orchestration/budget.py`） |
| Worker 事件不污染消息窗口（`isolation.py`，FB-5） | 消息窗口算法（M2 `window.py`） |
| `reflect_node` 图节点（`app/agent/reflect.py`） | **M4 owner**：图拓扑与节点签名；本层仅提供 `review`/`check_gates`/`FeedbackBudget` 供其调用 |

> **与 M5/M2 的归一分工**：M5 `dispatch` 执行工具产出原始 `ToolResult` → 本层 `observation.py` 归一为 `Observation`（异常不裸抛，FB-1）→ M2 `context/observation.py` 把 `Observation` 截断/脱敏后注入上下文。本层是归一逻辑 owner，M5 调本层归一函数。

### 1.3 红线（继承 Harness §4.6 + §2.5 + §7）

- 工具结果归一为 observation，**异常不裸抛**，不导致 Agent 崩溃（FB-1）。
- 规则门禁先行：长工具/白名单/任意代码/一单一 kind/必填槽位/资产溯源/占槽/先评后压（FB-2）。
- 模型辅助核对只能 `pass→clarify` 降级，**不得**把 `reject` 改为 `pass`（FB-3）。
- 失败反馈受预算约束，**禁止无限重试**（FB-4）。
- Worker 的 progress/report/error 只进任务/事件链路，**不污染消息窗口**（FB-5）。
- observation 级内部枚举不对外，对外只暴露 10 大 `ErrorCode`（§7）。
- 不私自扩充对外字段。

---

## 2. 需求发散

### 2.1 从 Harness §4.6 提取的需求

| 编号 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| FB-1 | 工具结果归一为 observation，异常不裸抛 | F-1：`observation.py` `normalize(raw, exc)` 产出 `Observation`；异常转 `ok=False` observation | 阶段 2 |
| FB-2 | 规则门禁先行（长工具/白名单/任意代码/一单一 kind/必填槽位/资产溯源/占槽/先评后压） | F-2：`rules.py` `check_gates(call, ctx)` 返回 `GateResult` | 阶段 2 |
| FB-3 | 模型辅助核对只能 pass→clarify 降级，不得 reject→pass | F-3：`review.py` `review(plan, obs)` 仅允许降级 | 阶段 4 |
| FB-4 | 失败反馈受预算约束，禁止无限重试 | F-4：`budget.py` `feedback_budget` 计数与熔断 | 阶段 4 |
| FB-5 | Worker 的 progress/report/error 只进任务/事件链路，不污染消息窗口 | F-5：`isolation.py` 隔离 Worker 事件与窗口 | 阶段 4 |

### 2.2 规则门禁发散（FB-2 细化）

| 门禁 | 检查 | 失败码 |
| :--- | :--- | :--- |
| 长工具 | `call.name ∈ LONG_TOOLS` → 拒绝图内执行 | `VALIDATION` |
| 白名单 | `call.name` 未注册 | `VALIDATION` |
| 任意代码 | `bash` 命中黑名单 | `VALIDATION` |
| 一单一 kind | 确认卡 `kind` 四选一，不混跑 | `VALIDATION` |
| 必填槽位 | PlanArtifact 缺必填字段 | `VALIDATION` |
| 资产溯源 | file_id 非归属 | `VALIDATION` |
| 占槽 | 会话存在活动任务再发确认卡 | `CONCURRENCY` |
| 先评后压 | `stress` 须由质量任务 `succeeded` 派生 | `VALIDATION` |

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| F-A1 | 工具异常被归一为 `ok=False` observation，Agent 不崩溃 | 归一断言 |
| F-A2 | 8 类门禁各有通过/拒绝用例 | 门禁用例 |
| F-A3 | 模型核对 `reject` 不被改为 `pass`；`pass` 可降级为 `clarify` | 降级断言 |
| F-A4 | 失败反馈超预算熔断，不再重试 | 预算断言 |
| F-A5 | Worker progress/report/error 不进 `messages` 表，只进 `ws_events`/`task_events` | 隔离断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/feedback/
├── __init__.py        # re-export normalize / check_gates / review / feedback_budget / isolate_worker_event
├── observation.py    # 阶段 2：工具结果归一为 observation（FB-1）
├── rules.py          # 阶段 2：规则门禁先行（FB-2）
├── review.py         # 阶段 4：模型辅助核对 pass→clarify 降级（FB-3）
├── budget.py         # 阶段 4：失败反馈预算约束（FB-4）
└── isolation.py      # 阶段 4：Worker 事件不污染消息窗口（FB-5）

# 注：app/agent/reflect.py（reflect_node）归 M4 owner，调用本层 review/check_gates/FeedbackBudget
```

### 3.2 observation.py（阶段 2 落地）

**职责**：工具结果归一为 `Observation`（FB-1），异常不裸抛。

- `normalize(raw: ToolResult | None, exc: Exception | None, *, tool, source) -> Observation`：
  - 正常：`raw` → `Observation(ok=True, text=摘要, source=...)`；
  - 异常：`exc` → `Observation(ok=False, text=归一错误码描述, redacted=True)`，**不裸抛**，不导致 Agent 崩溃。
- 异常归一为 observation 级内部枚举（不对外），对外只暴露 10 大 `ErrorCode`（§7）。
- M5 `dispatch` 执行后调本函数归一。
- **脱敏责任分工**（M6-D1）：本层归一时异常标 `redacted=True`，但不做递归脱敏；递归脱敏（`api_key`/`token` 等键）由 M2 `context/observation.py` 注入上下文前调 M8 `security/secrets.py` 完成。本层只负责归一，M2 负责脱敏。

### 3.3 rules.py（阶段 2 落地）

**职责**：规则门禁先行（FB-2），确定性检查，不调模型。

- `check_gates(call: ToolCall, ctx: GateContext) -> GateResult`：按 §2.2 八类门禁顺序检查，返回 `passed` + 失败码。
- 门禁失败抛 `AppError`（`VALIDATION`/`CONCURRENCY`），由 M4 节点捕获转 `NodeEvent(error)`。
- 与 M4 `gates.py` 协作：M4 `gates` 提供会话级门禁（OR-6/OR-7），本层提供工具级门禁（FB-2）。

### 3.4 review.py（阶段 4 落地）

**职责**：模型辅助核对，仅降级不放行（FB-3）。

- `review(plan: PlanArtifact, obs: Observation, *, model_call=None) -> ReflectVerdict`：
  - 确定性门禁先行（调 `rules`）；
  - 可选模型核对：只能 `pass→clarify` 降级，**不得** `reject→pass`；
  - 返回 `pass`/`clarify`/`reject`。
- 模型核对只降级不放行——即使模型说"通过"，规则 `reject` 仍保持 `reject`。

### 3.5 budget.py（阶段 4 落地）

**职责**：失败反馈预算约束（FB-4），禁止无限重试。

- `FeedbackBudget`：失败反馈次数计数 + 熔断阈值。
- `consume_failure(b) -> Budget`：失败 +1；超阈值熔断，不再重试，转 `NodeEvent(error)`。
- 与 M4 `orchestration/budget.py` 区分：M4 管模型调用与工具轮次预算，本层管**失败反馈**预算。

### 3.6 isolation.py（阶段 4 落地）

**职责**：Worker 事件不污染消息窗口（FB-5）。

- `isolate_worker_event(event: str) -> bool`：判定事件是否属 Worker 链路（`progress`/`report`/`error`/`task.*`），只进 `ws_events`/`task_events`，**不进 `messages` 表**。
- M2 `window.py` 的过滤规则（CX-2）依赖本层标记：Worker 事件被排除出窗口。

### 3.7 reflect_node 协作（阶段 4，M4 owner）

**职责**：`reflect_node` 由 M4 `app/agent/reflect.py` 承载（图拓扑节点），本层提供其调用的库函数。

- M4 `reflect_node(state: GraphState) -> dict`：先调本层 `rules.check_gates`（确定性门禁先行，FB-2），再按需调 `review.review`（模型辅助核对，FB-3），写 `state.verdict` + `pending_events`。
- 条件边按 `verdict` 分流：`pass` → 确认卡（写 `pending_confirm`）；`clarify` → 澄清卡 `interrupt()`（阶段 3）；`reject` → 失败反馈。
- 模型辅助核对只降级不放行（FB-3）在 `review` 内保证；失败反馈预算（FB-4）由 `FeedbackBudget` 约束。
- **本层不定义 `reflect_node`**，仅提供 `review`/`check_gates`/`FeedbackBudget` 供 M4 调用。

### 3.8 接口签名规格（签名级）

#### 3.8.1 observation.py

```python
from app.harness.contracts import Observation, ToolResult

def normalize(raw: ToolResult | None, exc: Exception | None, *,
              tool: str, source: str | None = None) -> Observation:
    """工具结果归一为 Observation（FB-1）：
    正常 → ok=True；异常 → ok=False（不裸抛，Agent 不崩溃）。
    异常归一为内部枚举，对外只暴露 10 大 ErrorCode。"""

def normalize_exception(exc: Exception, *, tool: str) -> Observation:
    """异常专归一：返回 ok=False observation，不抛出。"""
```

#### 3.8.2 rules.py

```python
from dataclasses import dataclass
from app.harness.contracts import ToolCall
from app.errors import AppError, ErrorCode

@dataclass(frozen=True, slots=True)
class GateContext:
    """门禁上下文（确定性，不含回调/连接）。
    has_active_task 由 M4 节点在调用前查 DB 填入（OR-7 会话级门禁同源），
    避免与 M4 check_session_active_task 双查；本层只消费不查 DB。"""
    session_id: str
    user_id: str
    has_active_task: bool
    owned_file_ids: frozenset[str]

@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    failed_code: str | None = None    # ErrorCode.value 或 None
    failed_message: str | None = None

def check_gates(call: ToolCall, ctx: GateContext) -> GateResult:
    """8 类门禁顺序检查（FB-2）：长工具/白名单/任意代码/一单一kind/
    必填槽位/资产溯源/占槽/先评后压。失败返回 failed_code。"""

def assert_gates(call: ToolCall, ctx: GateContext) -> None:
    """门禁失败抛 AppError（VALIDATION/CONCURRENCY）。"""
```

#### 3.8.3 review.py

```python
from typing import Callable, Literal
from app.harness.contracts import Observation, PlanArtifact

ReflectVerdict = Literal["pass", "clarify", "reject"]

def review(plan: PlanArtifact, obs: Observation,
           *, model_call: "Callable[..., object] | None" = None) -> ReflectVerdict:
    """模型辅助核对（FB-3）：确定性门禁先行（调 rules），可选模型核对。
    只允许 pass→clarify 降级，不得 reject→pass。
    model_call 为可选模型调用句柄（注入便于测试用 mock LLM 夹具）；None 时跳过模型核对。"""
```

#### 3.8.4 budget.py

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class FeedbackBudget:
    """失败反馈预算（FB-4）。"""
    failures: int = 0
    max_failures: int = 3          # 熔断阈值

def consume_failure(b: FeedbackBudget) -> FeedbackBudget:
    """失败 +1；超 max_failures 熔断。"""

def is_exhausted(b: FeedbackBudget) -> bool:
    """是否已熔断（禁止再重试）。"""
```

#### 3.8.5 isolation.py

```python
WORKER_EVENTS: frozenset[str] = frozenset(
    {"progress", "report", "error", "task.created", "task.succeeded", "task.failed"}
)
# 注：Worker 错误事件归 "error"（与 M7 持久化事件集合一致）；task.failed 为任务终态失败。

def isolate_worker_event(event: str) -> bool:
    """判定事件是否属 Worker 链路（FB-5）。
    Worker 事件只进 ws_events/task_events，不进 messages 表。"""

def assert_not_in_messages(event: str) -> None:
    """断言 Worker 事件不进消息窗口（供 M2 window.py 调用）。"""
```

#### 3.8.6 reflect_node 协作（M4 owner，本层不定义）

```python
# reflect_node 由 M4 app/agent/reflect.py 定义，签名：reflect_node(state: GraphState) -> dict
# 本层提供其调用的库函数（见 3.8.2 check_gates / 3.8.3 review / 3.8.4 FeedbackBudget）
```

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_feedback.py`（含 `test_gates.py`/`test_review.py`/`test_isolation.py`）

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_normalize_exception_returns_ok_false_no_raise` | F-A1 |
| `test_normalize_normal_result_returns_ok_true` | F-A1 |
| `test_gate_long_tool_rejected` | F-A2 |
| `test_gate_unregistered_rejected` | F-A2 |
| `test_gate_bash_blocklist_rejected` | F-A2 |
| `test_gate_one_kind_per_card` | F-A2 |
| `test_gate_required_slots_missing` | F-A2 |
| `test_gate_asset_source_foreign_file_id` | F-A2 |
| `test_gate_active_task_concurrency` | F-A2 |
| `test_gate_stress_must_derive_from_quality` | F-A2 |
| `test_review_reject_not_upgraded_to_pass` | F-A3 |
| `test_review_pass_can_downgrade_to_clarify` | F-A3 |
| `test_feedback_budget_exhausted_no_retry` | F-A4 |
| `test_worker_event_not_in_messages_table` | F-A5 |

**TDD 顺序**：先写 `test_gates.py`（阶段 2）全红 → 实现 `observation.py`/`rules.py` → 全绿；阶段 4 补 `review`/`budget`/`isolation`/`reflect` 测试。`review` 模型核对测试用 mock LLM 夹具。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/feedback/__init__.py` | 阶段 2 | 修改（re-export） | — |
| `app/harness/feedback/observation.py` | 阶段 2 | 新增 | FB-1、F-1 |
| `app/harness/feedback/rules.py` | 阶段 2 | 新增 | FB-2、F-2 |
| `app/harness/feedback/review.py` | 阶段 4 | 新增 | FB-3、F-3 |
| `app/harness/feedback/budget.py` | 阶段 4 | 新增 | FB-4、F-4 |
| `app/harness/feedback/isolation.py` | 阶段 4 | 新增 | FB-5、F-5 |
| `backend/api/tests/test_harness_feedback.py` | 阶段 2/4 | 新增 | F-A1~F-A5 |

> `app/agent/reflect.py`（`reflect_node`）归 M4 owner，见 M4 §5 文件清单。

---

## 6. 依赖与红线

- **上游依赖**：Harness §4.6（FB-1~5）、§2.5、§7；API.md；PRD §5.1.3。
- **下游被依赖**：M4（`review`/`check_gates`/`FeedbackBudget` 供 `reflect_node` 调用）、M5（`normalize` 供 dispatch 归一）、M2（`isolate_worker_event` 供窗口过滤）。
- **跨层协作**：M7（`Observation`/`ToolCall`/`ToolResult`/`PlanArtifact` 契约）、M4（`gates.py` 会话级门禁、`budget.py` 模型预算区分）、M8（脱敏）。
- **命名区分**：本层 `app/harness/feedback/budget.py`（失败反馈预算 FB-4）与 M4 `app/harness/orchestration/budget.py`（模型/工具轮次预算 OR-5）跨包同名，import 时用全路径区分（`from app.harness.feedback.budget import FeedbackBudget` / `from app.harness.orchestration.budget import Budget`）。
- **红线**：
  - 异常不裸抛，不导致 Agent 崩溃；
  - 规则门禁先行；
  - 模型核对只降级不放行；
  - 失败反馈预算约束，禁无限重试；
  - Worker 事件不污染消息窗口；
  - observation 内部枚举不对外，对外只 10 大 ErrorCode；
  - 不私自扩字段。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M6-D1 | 归一逻辑归属 | 本层 `observation.py` 为归一 owner，M5 `dispatch` 调本层归一；M2 `context/observation.py` 负责注入前截断/脱敏 |
| M6-D2 | 门禁分层 | M4 `gates.py` 管会话级（OR-6/OR-7），本层 `rules.py` 管工具级（FB-2 八类） |
| M6-D3 | 预算分层 | M4 `orchestration/budget.py` 管模型调用/工具轮次，本层 `budget.py` 管失败反馈 |
| M6-D4 | 模型核对边界 | 只允许 `pass→clarify` 降级，`reject` 不可被模型改为 `pass`（FB-3 硬约束） |
| M6-D5 | Worker 事件集合 | `{progress, report, error, task.created, task.succeeded, task.failed}`，只进 ws_events/task_events（`error` 与 M7 持久化集合一致） |
| M6-D6 | 异常对外暴露 | observation 级内部枚举不对外，对外只 10 大 ErrorCode |

---

## 8. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-反馈层.md` | 新增 V0.3 | M6 反馈层模块设计：定义工具结果归一（异常不裸抛）、规则门禁先行（8 类）、模型辅助核对（仅 pass→clarify 降级）、失败反馈预算、Worker 事件隔离；含接口签名级（`normalize`/`check_gates`/`review`/`FeedbackBudget`/`isolate_worker_event`/`reflect_node`）与 TDD 验收；明确与 M5/M2/M4 的归一/门禁/预算分层边界。 |

本文档仅设计反馈层，不改变任何 API、数据库、前端或 Agent 运行代码。




