# AI 测试与评估平台 — Harness 阶段 0：契约骨架

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 阶段 0 — 契约骨架 |
| 版本 | V1.3 |
| 审查日期 | 2026-08-21 |
| 文档性质 | **开工前分析文档**（需求分析、功能点、实现路径、技术难点与对策）；代码必须按本文验收，不得超出范围 |
| 对应目标架构 | [`docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md`](docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md) **第七章为阶段 0 需求权威**（从第一至六章抽出） |
| 产品/协议裁决 | PRD、[`docs/AI测试与评估平台-API.md`](docs/AI测试与评估平台-API.md)、[`docs/AI测试与评估平台-Agent开发文档.md`](docs/AI测试与评估平台-Agent开发文档.md)；JSON 字段名与路径以 API.md 为准 |
| 分支 | `feat/harness-contracts` |
| 前置依赖 | 无 |
| 后续阶段 | 阶段 1 单调用路径（必须等本阶段验收通过） |

---

## 1. 从架构文档抽出的需求（为什么先做阶段 0）

目标架构（以当前架构文档为准，现为 V1.7）的核心原则是：**模型只推理并产出结构化 JSON；Harness 是唯一控制、执行、持久化和授权主体。** 六层之间有不可跨越边界：

```text
Context ──只通过 MemoryPort──> Memory；不得 import 存储 SDK
Orchestration ──只接收 JSON──> 不把纯文本当动作；独占经 llm/ 调模型
Execution ──只返回 Outcome──> 不调模型、不决定下一轮
Feedback ──只生成 ToolResult──> 不重试、不访问模型
TraceContext ──贯穿六层──> 每次跨层必须带 trace_id 与 span_id
```

§5.3 把迁移拆成五阶段，阶段 0 原文是：

> 建立 `harness/` 目录骨架 + `contracts/`（trace、cancellation、tool_call）+ `tests/tracing` fail-fast 用例

这不是「先把六层全写完」，而是：**先冻结跨层会说话的类型，用测试锁住不变量，活路径（WS / ReAct / LLM）一概不迁。** 若跳过本阶段直接改 `react.py`，会出现三件事同时爆炸：类型漂移、双实现、WS 回归无法归因。

本阶段要回答的产品问题只有一个：**后面四阶段迁代码时，大家用同一套 JSON/对象说话，缺 trace 立刻失败，而不是各写各的 dict。**

---

## 2. 现状差距（架构需求 vs 现网）

| 架构要求 | 现网实现 | 阶段 0 要补的缺口 |
| :--- | :--- | :--- |
| `TraceContext(trace_id, span_id)` 不可选 | [`agent/log.py`](backend/api/app/agent/log.py) 只有 `agent_trace` 打 stderr，无结构化链路 | 冻结 Trace 类型 + child span 规则 + 单测 |
| `CancellationToken` 100ms SLO | [`harness.py`](backend/api/app/agent/harness.py) 进程内 `abort: asyncio.Event` + `stop: threading.Event` | 只定义令牌类型；**不替换** `/stop`（那是阶段 2） |
| 唯一可执行输入是 Schema 后的 `ToolCall` | [`react.py`](backend/api/app/agent/react.py) `McpStep` + `parse_mcp_step` 内联 | 冻结 ToolCall/Batch 模型；解析逻辑仍留 react.py |
| 执行失败必须是 `ExecutionOutcome`，禁止裸抛 | `execute_short_tool` 返回 `(ok, data, error, latency)`，部分路径 `raise AppError` | 冻结 Outcome/ToolResult；执行函数不迁 |
| 缺 trace 的 Outcome Fail-fast | 无 | `normalize()` 纯函数 + 单测 |
| 内部 `ErrorClass` ≠ 10 大 `ErrorCode` | 只有 [`errors.py`](backend/api/app/errors.py) 十码 | 增加 observation 级枚举与映射表，不改对外码 |
| `MemoryPort` 解耦存储 | `context.py` 直接 `query(Message)` | 只定义 Port；不接 Redis/PG |
| 物理目录 `harness/` | 不存在（现为扁平 `app/agent/`） | 建 `backend/api/app/harness/` |

结论：阶段 0 是 **契约与隔离**，不是运行时重构。现网对话、工具卡、确认卡必须继续走 `app/agent/`。

---

## 3. 需求分析

### 3.1 功能需求

| ID | 需求陈述 | 来源 | 优先级 |
| :--- | :--- | :--- | :--- |
| R0-1 | 提供独立 Python 包 `app.harness`，目录对齐架构第二章树，可被后续阶段增量填入 | 架构 §2、§5.3 | P0 |
| R0-2 | 冻结 `TraceContext`：`trace_id`/`span_id`/`turn_id` 非空；`child(component)` 同 trace、新 span、parent=当前 span | 架构 §2.2、§3.5 | P0 |
| R0-3 | 冻结 `CancellationToken`：默认传播预算 100ms；`request` 幂等；已取消则 `raise_if_cancelled` | 架构 §2.2、§3.2.2、§4.4 | P0 |
| R0-4 | 冻结 `ToolCall` / `ToolCallBatch` / `ExecutionOutcome` / `ToolResult` / `ToolResultBatch`；模型 JSON 不得自带 trace | 架构 §3.2、§3.3 | P0 |
| R0-5 | 内部 `ErrorClass` 只用于 observation；对外映射遵守架构 §6.2；不新增 REST/WS 码 | 架构 §6.2、AGENTS.md 红线 2 | P0 |
| R0-6 | `normalize(outcome, *, trace)`：缺 trace 或父子不匹配必须抛 `MissingTraceContext`/`TraceMismatch`，不得降级成工具错误 | 架构 §3.5 | P0 |
| R0-7 | 定义 `MemoryPort`/`MemoryQuery`/`MemoryRecord` 与 `CompiledContext`，供阶段 4 接线，本阶段无存储实现 | 架构 §2.1、§3.1、§5.2 | P1 |
| R0-8 | 静态 JSON Schema 进 `prompts/`，不改 `persona.py` 运行时人设 | 架构 §1.3 | P1 |
| R0-9 | pytest 可发现 tracing 用例（项目 `testpaths=tests`） | 架构 §5.3、§2 tests/tracing | P0 |
| R0-10 | 活路径零行为变化：不改 WS、斜杠、确认卡、四项多媒体工具、`app/llm.py` | 架构 §5.1「行为保持不变」、API.md | P0 |

### 3.2 非功能需求

| ID | 需求 | 验收口径 |
| :--- | :--- | :--- |
| N0-1 | 契约无 I/O、无 LLM SDK、无 SQLAlchemy/Redis | `contracts/` 不得 import `redis`/`sqlalchemy`/`app.llm`/`app.adapters` |
| N0-2 | 请求级 trace 禁止缓存在服务 `__init__` | `harness/app.py` 若存在装配根，不得保存上一次 Turn 的 TraceContext |
| N0-3 | 中文 docstring / 关键分支注释 | AGENTS.md §5.1 |
| N0-4 | 单测不连库、不连上游 | tracing 测试纯内存 |
| N0-5 | 物理路径必须在 FastAPI 包内 | `backend/api/app/harness/`，以便 `from app.harness.contracts...` |

### 3.3 约束与裁决（本阶段冻结，避免返工）

1. **对外协议冻结**：不新增 REST/WS 字段；ContextMeter、确认卡默认值仍以 API.md / PRD 为准。
2. **错误分层**：`DONE_TOOL_CONFLICT` 等只回填模型；浏览器仍只见 10 大 `ErrorCode`。
3. **预算数字不在本阶段落地**：运行时继续 Agent 说明书（轮次 4 / 硬顶 5 / 墙钟 180s）。架构表里的 `HARNESS_MAX_REACT_STEPS=6` 等留到阶段 2 用环境变量接入。
4. **取消不替换 `/stop`**：本阶段只定义令牌；现网仍用 `abort`+`stop`。
5. **禁止双活路径**：不得把 `mcp_tools.py` / `llm.py` 改成再导出。后续层目录可以空壳存在，但不得接管会话。
6. **LightRAG 不出现**：禁止创建 `long_term_lightrag.py`。
7. **Schema 前向兼容债务（留给阶段 3）**：`react-output.schema.json` 已允许可选 `tool_calls[]`，但顶层仍 `required: [thought, tool, arguments, done]`。架构 §3.2.1 的批次示例（无顶层 `tool`）在本阶段**故意不能通过**校验，避免阶段 1 误把数组当可执行输入。阶段 3 再改 `oneOf`。
8. **`MemoryQuery` 只预埋字段**：`tenant_id`/`user_id`/`session_id` 本阶段允许空串，以便纯类型测试；阶段 4 收紧「retrieve 拒绝空租户/会话」，不算重定义类型名。
9. **`planner-output.schema.json` / `system.yaml` 本阶段不建正文**（可空文件或不创建）；人设仍在 `persona.py`。

---

## 4. 细分功能点（可开发、可测试）

每个功能点格式：输入 → 处理 → 输出 → 验收。阶段 0 全部是 **库内纯逻辑**，没有 HTTP 接口。

### F0-1 目录骨架

- **做什么**：创建 `backend/api/app/harness/` 及 `contracts/` `prompts/` `context/` `memory/` `orchestration/` `execution/` `feedback/` `llm/` `security/` `app.py`。
- **怎么验收**：包可导入；`app.harness` 不在 import 时接管 WS。
- **不做**：把 `dispatch_user_message` 改到 `harness/app.py`。

### F0-2 TraceContext

- **输入**：Turn 入口或父 span。
- **处理**：`for_turn()` 生成根；`child(name)` 派生。
- **输出**：新对象，`trace_id` 不变，`span_id` 新，`parent_span_id` 为父 span。
- **验收**：空 id 构造失败；child 单测见 `test_child_span_keeps_same_trace_id`。
- **实现要点**：`frozen` dataclass，避免调用方原地改 id；id 用短 hex，日志可读、不等于 `call_id`。

### F0-3 CancellationToken

- **输入**：`turn_id`、取消原因。
- **处理**：`request(reason)` 首次置位并记录单调时钟；重复 request 忽略。
- **输出**：`is_cancelled()` / `raise_if_cancelled()` → `TurnCancelled`。
- **验收**：默认 `propagation_budget_ms==100`。
- **不做**：接入 `_HARNESS_BY_SESSION`、测量真实 100ms 调度（需阶段 2 与事件循环挂钩）。

### F0-4 Tool 数据契约

- **ToolCall**：`thought≤512`、`reply≤4000`、`arguments` 必须是 object；`trace_id`/`span_id` 可选且由编排绑定，不从模型 JSON 信任。
- **ToolCallBatch**：`call_id` Turn 内唯一；`batch_index` 从 0 连续（本阶段只建模，不执行并行）。
- **ExecutionOutcome**：`status ∈ {ok,error,timeout,cancelled,pending,cancel_requested}`；失败走 `error.class`（内部枚举）。
- **ToolResultBatch**：同时提供 `ordered_results`（按 batch_index）与 `results_by_call_id`。
- **验收**：Pydantic 能 round-trip；构造缺字段的 Outcome 供 Fail-fast 测试。

### F0-5 内部错误与对外码隔离

- **功能点**：`ErrorClass` StrEnum + `map_error_class_to_code()`。
- **映射（架构 §6.2）**：deadline 耗尽 → `TIMEOUT`；步数耗尽 → `VALIDATION`；`NEED_APPROVAL` → 403 同名码；上游超时/错误 → `TIMEOUT`/`UPSTREAM`；其余不对外。
- **验收**：`ErrorCode` 枚举个数仍为 10（`test_errors.py` 不被破坏）。

### F0-6 Feedback normalize Fail-fast

- **输入**：`ExecutionOutcome` + 当前 Feedback `TraceContext`。
- **规则**：
  1. outcome 无 `trace_id` 或 `span_id` → `MissingTraceContext`；
  2. `outcome.trace_id != trace.trace_id` → `TraceMismatch`；
  3. 若 `trace.parent_span_id` 存在，必须等于 `outcome.span_id`（单调用父子）；
  4. 成功则脱敏截断后产出 `ToolResult`，`caused_by_span_id=outcome.span_id`。
- **验收**：对应 tracing 三测。批量父子树（批次 span → 多 call span）留阶段 3。

### F0-7 MemoryPort / CompiledContext 类型预埋

- **只定义协议与字段**（`source_id`、`origin_trace_id` 等）。
- **不实现** Redis TTL、pgvector SQL、消息表改列。

### F0-8 静态 Schema

- `prompts/react-output.schema.json` 固定 ReAct JSON 外形；禁止写「请逐步展示推理」类 CoT 指令。
- 运行时人设仍在 `persona.py`。

### F0-9 Tracing 测试包

- 落点必须是 [`backend/api/tests/harness/tracing/`](backend/api/tests/harness/tracing/)，因为 pytest `testpaths=["tests"]`，架构树里的 `harness/tests/` 不会被收集。

---

## 5. 怎么实现（技术路径）

### 5.1 包位置与导入

架构文档写的是逻辑树 `harness/`。实现必须放在 **`backend/api/app/harness/`**，否则 FastAPI / pytest 的 `pythonpath` 找不到。后续阶段用：

```text
from app.harness.contracts.trace import TraceContext
from app.harness.feedback.normalizer import normalize
```

`app/harness/__init__.py` **不要**在 import 包时拉起 Redis、ExecutionFacade、会话表，避免测试/启动副作用。

### 5.2 类型选型

| 对象 | 选型 | 原因 |
| :--- | :--- | :--- |
| `TraceContext` | frozen dataclass | 值对象、高频 child()、不需要 schema 校验器 |
| `CancellationToken` | 可变 dataclass + `asyncio.Event` | 需要原地置位；Event 不能 frozen |
| ToolCall / Outcome / Result | Pydantic v2 | 与架构「JSON Schema / Pydantic」一致，extra=forbid 挡模型多余字段 |
| `MemoryPort` | `typing.Protocol` | 阶段 4 可替换 Redis/PG，Context 不改 |
| `ErrorClass` | StrEnum | 可进 JSON `error.class` |

### 5.3 与活路径隔离的落地手法

```text
阶段 0 提交内容
  ├─ 新增 app/harness/**（契约 + 可单测的 normalize）
  ├─ 新增 tests/harness/tracing/**
  ├─ 本分析文档
  └─ 禁止修改：app/agent/*.py 行为、app/llm.py、routers/ws.py、models.py、Alembic
```

若开发过程中误把 `mcp_tools.py`/`llm.py` 改成再导出，必须 **git checkout 回滚**，否则阶段 1 前就会出现双实现。

后续阶段目录里可以有空壳文件，但 **WS 收包循环不得 import 并执行** 这些空壳。判断标准：现有 `test_harness.py` / `test_agent_llm.py` / 多媒体工具测试不依赖 `app.harness`。

### 5.4 实现顺序（本阶段任务流）

1. 从 `origin/main` 拉 `feat/harness-contracts`（禁止在 `main` 改）。
2. 写 `contracts/trace.py` → `cancellation.py` → `errors.py` → `tool_call.py` → `memory.py` → `context.py`。
3. 写 `feedback/normalizer.py`（只依赖 contracts + 现有脱敏纯函数，或最小截断）。
4. 写 tracing 单测，先红后绿。
5. `ruff check app/harness tests/harness`；`pytest tests/harness/tracing tests/test_mcp_registry.py tests/test_agent_llm.py tests/test_errors.py`。
6. 对照本文第 3、4 节勾验收，超范围文件一律移出本 PR。

### 5.5 代码落点对照

| 功能点 | 文件 |
| :--- | :--- |
| F0-1 | `backend/api/app/harness/` 各层目录、`app.py` |
| F0-2 | `contracts/trace.py` |
| F0-3 | `contracts/cancellation.py` |
| F0-4 | `contracts/tool_call.py` |
| F0-5 | `contracts/errors.py` |
| F0-6 | `feedback/normalizer.py`、`feedback/diagnostics.py` |
| F0-7 | `contracts/memory.py`、`contracts/context.py` |
| F0-8 | `prompts/react-output.schema.json`、`prompts/versions.yaml` |
| F0-9 | `tests/harness/tracing/test_trace.py` |

---

## 6. 技术难点与对策

### 难点 1：契约要「将来能强制透传」，但现在不能改函数签名

活路径几十处 `run_react(..., check_abort=...)` 若本阶段全部加 `*, trace, cancel`，回归面等于阶段 1+2 一次做完。

**对策**：类型和 `normalize()` 先独立存在；公开方法只在 contracts/feedback 上使用关键字-only `trace`。`agent/react.py` 签名不动。阶段 2 再把关键字参数打进循环。

### 难点 2：`call_id` vs `trace_id` vs `span_id` 易混用

现网工具卡只有 `name`，没有链路 id。架构明确：`call_id` 只标识一次工具调用，**不得**替代 trace/span；模型不得填写后两者。

**对策**：`ToolCall.trace_id` 允许 None；Parser（阶段 1）成功后由编排层写入当前 Turn 的 Trace。阶段 0 单测构造 Outcome 时显式传执行 span，不把 call_id 当 trace。

### 难点 3：Fail-fast 与「工具异常不得打崩 Agent」打架

架构同时要求：普通工具错误 → ToolResult；缺 trace → 熔断 Turn。若都变成 `status=error` 回填模型，可观测性缺口会被模型「自纠」吃掉。

**对策**：`MissingTraceContext`/`TraceMismatch` 继承普通 `Exception`，**不是** `ErrorClass` 里的可重试工具错。`normalize` 直接 raise。阶段 1 编排捕获后走 `FAILED_STOP` + 对外 `INTERNAL`，不生成无来源 ToolResult。

### 难点 4：Pydantic Outcome 如何表达「非法空 trace」供测试

若 `TraceContext` 禁止空 id，测试缺 trace 只能造 `ExecutionOutcome(trace_id="")`。`TraceContext.__post_init__` 与 Outcome 字段约束必须分开：Context 构造期挡错；Outcome 允许空串以便 Feedback 做 Fail-fast（生产路径应由执行层保证非空）。

**对策**：空 id 校验放在 `normalize`/`record_diagnostic`，不放在 Outcome 的 Field 约束里。

### 难点 5：pytest 发现不了架构树里的 `harness/tests/`

`backend/api/pyproject.toml` 的 `testpaths = ["tests"]`。

**对策**：测试放 `backend/api/tests/harness/tracing/`。文档与代码都以这里为准，不在 `app/harness/tests/` 再放一份。

### 难点 6：取消令牌里的 `asyncio.Event` 与现网 `threading.Event` 并存

现网短工具在 `asyncio.to_thread` 里跑，取消靠 `threading.Event`。阶段 0 若在 Token 里只用 asyncio.Event，线程内看不到。

**对策**：本阶段不接线。阶段 2 设计为「asyncio.Event 为主 + 同步 `stop` 镜像」，或在 `request()` 时同时 `threading.Event.set()`。写入阶段 2 文档，不在阶段 0 假装已解决 100ms SLO。

### 难点 7：内部 ErrorClass 与 10 大码被抄成第二套对外协议

**对策**：`map_error_class_to_code` 对「其余编排枚举」返回 `None`；注释写明只进 observation。`test_errors.py` 继续断言对外恰好 10 个码。

### 难点 8：空壳层文件变成提前实现，造成双实现幻觉

一次把 Redis/执行门面写满，但活路径仍用 `mcp_tools.py`，审查者会以为已经迁完。

**对策**：阶段 0 PR 以 **contracts + tracing 测试 + 本分析文档** 为必选。其它层文件若存在，必须未从 `routers/ws.py` / `agent/harness.py` 引用。误改 `llm.py` 再导出必须回滚。

---

## 7. 验收清单

- [x] `pytest tests/harness/tracing -q` 全绿
- [x] 缺 trace 的 Outcome → `MissingTraceContext`
- [x] 不同 `trace_id` 合并 → `TraceMismatch`
- [x] `child()` 同 trace、异 span、parent 正确
- [x] `CancellationToken.propagation_budget_ms == 100`
- [x] `tests/test_errors.py` 仍为 10 大 ErrorCode
- [x] `app/llm.py`、`app/agent/mcp_tools.py`、`app/agent/mcp_registry.py` 相对 `main` 无行为性 diff
- [x] 无 Alembic、无新 REST/WS 字段
- [x] `ruff check app/harness tests/harness` 通过
- [x] `react-output.schema.json` 顶层仍要求 `tool`；`tool_calls[]` 仅可选且 item 级 `additionalProperties: false`（阶段 3 再 `oneOf`）
- [x] 未创建 `long_term_lightrag.py`；`execution/mcp/` 与 `security/` 为空壳

---

## 8. 本阶段交付后，阶段 1 才能开始的输入

阶段 1 开工前必须能 import 并稳定使用：

```text
TraceContext.for_turn() / .child()
CancellationToken
ToolCall / ToolCallBatch / ExecutionOutcome / ToolResult
ErrorClass / MissingTraceContext / TraceMismatch
normalize(outcome, *, trace)
MemoryPort 协议（仅类型）
```

阶段 1 **不得**重定义上述名字。若要改字段，先改本文与架构文档，再改代码。

---

## 修改代码文件与作用清单

V1.3：补 Schema 与 MemoryQuery 的前向债务、挂起模板清单。代码仍以 V1.2 落地为准，本修订不改契约运行时行为。

V1.2：按本文落地契约骨架；后续层仅保留空壳，禁止 Redis / 执行门面 / `app.llm` 再导出。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-Harness阶段0-契约骨架.md` | 阶段 0 需求分析、功能点、实现路径、难点对策（本文） |
| `backend/api/app/harness/__init__.py` / `app.py` | 包入口；装配根不连接存储、不缓存 TraceContext |
| `backend/api/app/harness/contracts/*` | 跨层唯一 schema（Trace / Cancel / ToolCall / ErrorClass / MemoryPort / CompiledContext） |
| `backend/api/app/harness/feedback/normalizer.py` | 单调用 Fail-fast；不公开 merge_batch |
| `backend/api/app/harness/feedback/redaction.py` | 最小脱敏截断，不改活路径 `mcp_tools` |
| `backend/api/app/harness/feedback/diagnostics.py` | 写入传入异常；进程内库可注入、有上限 |
| `backend/api/app/harness/prompts/*` | 静态 ReAct JSON Schema；无人设/CoT 指令 |
| `backend/api/app/harness/{context,memory,orchestration,execution,llm,security}/*` | 目录骨架空壳，实现归属阶段 1–4 |
| `backend/api/tests/harness/tracing/test_trace.py` | F0-2/3/6 验收单测 |
| `backend/api/tests/harness/tracing/test_contracts.py` | ErrorClass 映射、契约无 I/O、活路径零引用 |
