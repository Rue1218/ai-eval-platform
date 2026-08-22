# AI 测试与评估平台 — Harness 阶段 3：并行与流式收尾

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 阶段 3 — 并行与流式收尾 |
| 版本 | V1.3 |
| 审查日期 | 2026-08-22 |
| 文档性质 | **施工与验收文档**（需求分析、功能点、实现路径、技术难点与对策）；阶段 4 仅可在本阶段验收通过后开工 |
| 对应目标架构 | 架构文档 §3.2.1 / §3.2.2 / §3.5 末段 / §5.3 |
| 前置阶段权威 | 阶段 2 强制 trace/cancel；阶段 0 **禁止错误 merge_batch**（伪造 parent 绕过 Fail-fast） |
| 产品/协议裁决 | API.md；Agent §5.6 第一阶段串行保证 `tool_call`/`tool_result` 成对。本阶段实现能力，**默认行为仍串行** |
| 分支 | `feat/harness-parallel-streaming` |
| 前置依赖 | 阶段 2 验收通过 |
| 后续阶段 | 阶段 4 记忆层接入 |

---

## 1. 从架构文档抽出的需求（为什么先做阶段 3）

架构 §5.3 原文：

> 阶段 3  ParallelFacade 批量 ToolCall + FINALIZING_STREAM 流式收尾

阶段 1/2 活路径仍是「一次 JSON 一个 `tool` 字段」。架构允许 `tool_calls[]`，但并行不是默认许可。本阶段要回答的产品问题：

**能力上可以一批执行互不依赖的只读调用，并在 `done=true` 后先流式收尾再结束；默认开关仍关，现网四项多媒体写工具永远串行，WS 事件名不变。**

```text
PARSED
  ├─ done=true 且无工具 → FINALIZING_STREAM → 流结束并落库 → FINISHED
  ├─ 单个合法 ToolCall → EXECUTING → FEEDBACK_READY
  ├─ 合法且全部 parallel_safe 的 Batch → PARALLEL_EXECUTING → merge_batch
  └─ 取消 → CANCELLING → CANCELLED（阶段 2 已有链，本阶段接到并行子任务）
```

阶段 0 审查删除的 `merge_batch` 在本阶段 **按 §3.5 正确实现**：先建批次执行 span，每个 `call_id` 独立 child；逐项校验「outcome 执行 span 的 parent == 批次 span」，失败 `TraceMismatch` 熔断整 Turn。禁止再伪造 `parent_span_id = outcome.span_id`。

---

## 2. 现状差距

| 架构要求 | 阶段 2 结束后 | 阶段 3 要补 |
| :--- | :--- | :--- |
| `ToolCallBatch` + `ParallelFacade` | 类型已有；Parser 忽略 `tool_calls[]`（阶段 1 冻结的现网行为） | Parser `oneOf`；门禁按决策表（开关关串行 / 开关开全安全才 gather / 否则 VIOLATION 不执行） |
| `parallel_safe` 缺省 false | 阶段 1 注册表已补字段；四项工具均为写 | 保持 false；单测用**桩工具**验证 gather |
| observation 按 `batch_index` | `ToolResultBatch` 类型已有 | 正确 `merge_batch`；禁止按完成时间排序 |
| `done=true` → `FINALIZING_STREAM` | 现网直接交付回复 | 流读完、消息持久化后才 `FINISHED` |
| `DONE_TOOL_CONFLICT` | 阶段 1 对外仍可能静默 | 本阶段对内回填该枚举；WS 键仍不新增 |
| `PARALLEL_READONLY_TOOLS` | `defaults.py` 为 False | 读取开关；默认关则即使数组也串行 |

---

## 3. 需求分析

### 3.1 功能需求

| ID | 需求陈述 | 来源 | 优先级 |
| :--- | :--- | :--- | :--- |
| R3-1 | 模型可输出 `tool_calls[]`；`call_id` Turn 内唯一，`batch_index` 从 0 连续 | §3.2.1 | P0 |
| R3-2 | 并行必须逐项 `parallel_safe=true`、无写副作用、无数据依赖、每项独立授权；缺省 false | §3.2.1、阶段 1 F1-5 | P0 |
| R3-3 | `asyncio.gather(..., return_exceptions=True)`；一子调用失败不得取消同批其他调用 | §3.2.1 | P0 |
| R3-4 | 并行上限 = `HARNESS_MAX_PARALLEL_CALLS`（缺省 4）。无 MCP `session_pool`，禁止再取「连接池容量」的虚构 min | §3.2.2、R3-16 | P0 |
| R3-5 | `ordered_results` 按 `batch_index`；`results_by_call_id` 可反查 | §3.2.1 | P0 |
| R3-6 | 正确实现 `merge_batch` 的批次 span 树校验 | §3.5 末段、阶段 0 审查 P1 | P0 |
| R3-7 | `done=true` 且无工具 → `FINALIZING_STREAM`；流结束 + 持久化成功 → `FINISHED` | §3.2.2 | P0 |
| R3-8 | `done=true` 仍带 `tool` 或非空 `tool_calls` → 不执行，回填 `DONE_TOOL_CONFLICT` | §3.2.2 | P0 |
| R3-9 | 产品开关默认关：关时批次也串行执行，保证 `tool_call`/`tool_result` 成对、`event_id` 不乱 | Agent §5.6 | P0 |
| R3-10 | 现网四项多媒体工具不得被标成 `parallel_safe=true` | §5.1 行为不变 | P0 |
| R3-11 | 取消必须落到未开始的并行子任务；已开始的走阶段 2 cancelled Outcome | §3.2.2、§4.4 | P0 |
| R3-12 | 不新增 WS 事件名；并行开启时仍成对发 `tool_call` / `tool_result` | API.md | P0 |
| R3-13 | Schema 改为 `oneOf`：单调用（必填 `tool`）\| 批次（必填 `tool_calls`，可无顶层 `tool`）。阶段 0 顶层 required 不得继续挡住架构 §3.2.1 示例 | 阶段 0 债务、§1.3 vs §3.2.1 | P0 |
| R3-14 | `done=false` 且 `tool=null` 且 `tool_calls` 为空 → 不执行，内部 `MISSING_TOOL`；对外不新 WS 键 | §3.2.2 | P0 |
| R3-15 | `done=false` 且参数不合规 → 不执行，内部 `ARGUMENT_VALIDATION_ERROR` | §3.2.2 | P0 |
| R3-16 | 同 R3-4：验收时 grep 不得出现用「连接池容量」参与 min 的占位实现 | 总册挂起项 | P0 |

### 3.2 非功能需求

| ID | 需求 | 验收口径 |
| :--- | :--- | :--- |
| N3-1 | 默认串行时，阶段 1/2 全部现网测试仍绿 | 多媒体 + `test_harness.py` |
| N3-2 | 并行单测不连真实上游，用桩工具 | `tests/harness/orchestration/` |
| N3-3 | `merge_batch` 必须有 Fail-fast 单测（mismatch 熔断） | 禁止回归阶段 0 的伪造 parent |
| N3-4 | 中文注释 | AGENTS.md §5.1 |

### 3.3 约束与裁决

1. **默认关**。打开并行不得作为本阶段合入 `main` 的运行默认。
2. **写工具永远串行**，即使有人把 `parallel_safe` 误标 true，执行前仍按副作用拒绝整批并行。
3. **禁止**按 Future 完成顺序组装 observation。
4. **禁止**一项失败就 cancel 同批其余调用。
5. **禁止**把 Memory/Redis、Alembic 新业务表塞进本阶段。
6. 阶段 1 兼容：`parse_mcp_step` 对外形状可继续只暴露单 `tool`；内部 Parser 可同时理解 `tool_calls`。测试 `parse_mcp_step` 旧用例仍绿。
7. `FINALIZING_STREAM` 是内部状态；对外仍是现有 token/文本事件，不新造事件名。
8. **并行门禁决策表（冻结，禁止第三种「有时串行有时违规」）**：

| 条件 | 处理 |
| :--- | :--- |
| 产品开关 `PARALLEL_READONLY_TOOLS=false`（默认） | 即使有 `tool_calls[]` 也**串行**执行；不回填 `PARALLEL_POLICY_VIOLATION` |
| 开关 true，且逐项 `parallel_safe=true`、无写副作用、无数据依赖、未超上限 | `PARALLEL_EXECUTING` + `gather` |
| 开关 true，但任一项不安全 / 写工具 / 超上限 / 有依赖 | **整批不执行**，回填 `PARALLEL_POLICY_VIOLATION`，要求模型改串行。禁止悄悄改串行（否则模型以为已并行） |
| 四项多媒体工具 | 注册表锁死 `parallel_safe=false`；即使误标 true，副作用检查仍拒绝整批并行 |

9. **不属于本阶段**：Redis/pgvector、MCP Transport、把内部 `call_id` 加成对外 WS 字段、`security/` 迁确认卡。

---

## 4. 细分功能点

### F3-1 批次解析

- **输入**：模型 JSON，可能含 `tool_calls`。
- **处理**：先按 `oneOf` Schema 校验（单调用或批次；item 级仍禁止 extra / 禁止 item 级 trace）→ `ToolCall` 或 `ToolCallBatch`；编排绑定 trace，每 call 派生子 span。
- **输出**：合法 Batch / 单调用，或内部错误类。
- **验收**：架构 §3.2.1 无顶层 `tool` 的批次示例能通过 Schema；模型在 item 上塞 `trace_id` 被拒绝；旧的单 `tool` JSON 仍通过。
- **不做**：阶段 1 的 `parse_mcp_step` 对外形状继续只暴露单 `tool`。

### F3-2 并行门禁

- **输入**：Batch + 注册表。
- **处理**：按 §3.3 决策表：开关关 → 串行；开关开且全安全 → 并行；开关开但不安全 → `PARALLEL_POLICY_VIOLATION` 且不执行。
- **输出**：允许并行 / 整批串行（仅开关关闭时） / 违规回填。
- **验收**：四项多媒体工具走串行；桩工具在开关打开时可并行；不安全批次在开关打开时**不**被改成串行执行。

### F3-3 ParallelFacade

- **输入**：已授权的 Batch。
- **处理**：`gather(return_exceptions=True)`；每项独立 deadline；异常变为该 `call_id` 的 Outcome。
- **输出**：与 Batch 等长的 Outcome 列表（含 error/timeout/cancelled）。
- **验收**：局部失败不丢成功结果。

### F3-4 merge_batch（正确版）

- **输入**：批次执行 span + 各 call Outcome。
- **处理**：逐项 `normalize`；校验 `outcome` 执行 span 的 `parent_span_id == 批次 span_id` 且 `trace_id` 相同；一项失败熔断整 Turn。
- **输出**：`ToolResultBatch`。
- **验收**：伪造 parent 的实现不得合入；单测覆盖 mismatch。
- **不做**：不得为了让校验恒真而新建 `parent_span_id=outcome.span_id` 的假 Feedback span（那是阶段 0 已否决的写法）。单调用路径仍用「Feedback child 的 parent == 执行 span」。

### F3-5 WS 成对事件

- **输入**：并行或串行执行。
- **处理**：每个 call 仍发 `tool_call` 再发对应 `tool_result`；并行时允许交错但必须成对、带可关联的 `name`（及内部 call_id 不泄漏为新对外字段，除非 API.md 先改——**本阶段不改 API.md**，故 call_id 只进内部 observation）。
- **验收**：无新 WS 字段；`event_id` 单调。

### F3-6 FINALIZING_STREAM

- **输入**：`done=true` 且无工具。
- **处理**：进入流式读取；断开/取消走阶段 2 令牌；流结束并写入消息表后 `FINISHED`。
- **输出**：用户看到完整最终回复。
- **验收**：单测状态序列必须经过 `FINALIZING_STREAM`，不能从 PARSED 直接 FINISHED。

### F3-7 DONE_TOOL_CONFLICT

- **输入**：`done=true` 且仍有 tool / tool_calls。
- **处理**：不执行工具；内部 ToolResult `error_class=DONE_TOOL_CONFLICT`；对外表现与现网「停工具」兼容（不新 WS 键）。
- **验收**：不出现「一边 done 一边还打了工具」。

### F3-7b MISSING_TOOL / ARGUMENT_VALIDATION_ERROR

- **输入**：`done=false` 且无工具；或参数不合 schema。
- **处理**：不执行；内部回填对应 `ErrorClass`；对外不新字段。现网「未知工具静默 done=True」对**未注册名**继续有效（阶段 1 冻结）；`MISSING_TOOL` 只覆盖「明确 done=false 且 tool 与 tool_calls 都空」。
- **验收**：单测区分三种：未知工具静默停、空工具 MISSING_TOOL、done+tool 冲突。

### F3-8 状态机补齐

- **输入**：阶段 2 已有取消终态。
- **处理**：落地 `PARALLEL_EXECUTING` / `FINALIZING_STREAM` / `FEEDBACK_READY` 转移表。
- **验收**：非法转移抛内部错误并 `FAILED_STOP`，不把 Agent 打崩给浏览器（对外 `INTERNAL`）。

---

## 5. 怎么实现

### 5.1 批次 span 树（强制）

```text
编排 parse span O-01
  └─ 批次执行 span X-batch      parent=O-01
        ├─ call_01 span X-01    parent=X-batch
        └─ call_02 span X-02    parent=X-batch
Feedback merge span F-01        parent=O-01（或 X-batch，文档冻结为：normalize 逐项看执行 span 的 parent 是否为 X-batch）
```

`merge_batch` 对每个 outcome：`outcome.parent_span_id == batch_exec_span.span_id` 且 `outcome.trace_id == batch_exec_span.trace_id`。不要用单调用那套「把 feedback.parent 改成 outcome.span」来骗过校验。

### 5.2 实现顺序

1. 从已含阶段 2 的 `main` 拉分支。
2. 状态机补状态；`done` 不变量。
3. Parser 识别 `tool_calls`；默认关时串行执行数组。
4. ParallelFacade + 门禁；桩工具单测。
5. 正确 `merge_batch` + tracing 单测。
6. FINALIZING_STREAM 接到现网 LLM stream。
7. 全量现网测试 + 新 orchestration 测试。

### 5.3 代码落点

| 功能点 | 文件 |
| :--- | :--- |
| F3-1 / F3-7 | `orchestration/parser.py` |
| F3-2 / F3-3 / F3-8 | `orchestration/parallel_facade.py`、`state_machine.py`、`authorization.py`（只做 parallel_safe / 副作用门禁，**不是** `security/consent` 确认卡） |
| F3-4 | `feedback/normalizer.py`（本阶段才允许出现 `merge_batch`） |
| F3-5 | `react_loop.py` 发 WS 的适配（字段仍走 `agent/harness` emit） |
| F3-6 | `orchestration/streaming.py`、`finalizer.py` |

---

## 6. 技术难点与对策

### 难点 1：默认关 vs「已经实现并行」的幻觉

**对策**：运行默认 `PARALLEL_READONLY_TOOLS=False`。合入说明写明能力已具备、生产仍串行。现网四项工具 `parallel_safe=false` 用单测锁死。

### 难点 2：merge_batch 再次伪造 parent

**对策**：单测断言：构造 `parent_span_id` 不等于批次 span 的 Outcome 必须 `TraceMismatch`。代码评审对照阶段 0 P1。

### 难点 3：并行时 WS `event_id` 乱序

**对策**：开关关闭时严格「call 事件 + result 事件」交替。开关打开时允许多 call 先发完再收 result，但每个 call 必须成对；`event_id` 仍由现网落库逻辑单调递增。不把内部 `call_id` 暴露为新对外字段。

### 难点 4：`done=true` 流式与 `/stop`

**对策**：`FINALIZING_STREAM` 必须订阅阶段 2 的 `CancellationToken`；停止后进入 `CANCELLED`，不得再 FINISHED。

### 难点 5：gather 取消传播

**对策**：未开始的子任务在 token 置位后不要启动；已开始的转为 cancelled Outcome。`return_exceptions=True` 避免一个失败取消全家。

### 难点 6：与阶段 1 `parse_mcp_step` 兼容

**对策**：对外再导出函数继续吃单 `tool` JSON。新路径走内部 `parse_model_payload`。旧测试不改断言。

### 难点 7：阶段 0 Schema 必填 `tool`，架构批次示例没有 `tool`

若阶段 3 不改 Schema，要么模型必须继续发 `tool=null`，要么批次路径永远校验失败。

**对策**：`react-output.schema.json` 改为 `oneOf` 两个分支，均 `additionalProperties: false`。单测：架构示例通过；带 item 级 `trace_id` 仍失败；阶段 1 单 `tool` 用例仍绿。

### 难点 8：F3-2 曾允许「违规则改串行」，与架构「拒绝整批」冲突

悄悄串行会让模型以为并行策略已满足。

**对策**：只在**产品开关关闭**时串行（能力未启用）。开关打开后的违规必须 `PARALLEL_POLICY_VIOLATION` 且不执行。

### 难点 9：`streaming.py` 与 `harness/llm` 流式正文双实现

**对策**：`orchestration/streaming.py` 只做状态（`FINALIZING_STREAM`）与取消订阅；字节流仍走阶段 1 的 `harness/llm` 唯一正文。禁止再写一套 Provider 读取。

---

## 7. 验收清单

- [x] 默认串行：四项多媒体 `parallel_safe=false`；现网测试全绿
- [x] 桩工具并行：gather 局部失败保留成功项
- [x] `ordered_results` 按 `batch_index`；`results_by_call_id` 可反查
- [x] `merge_batch` mismatch 熔断；无伪造 parent
- [x] `done=true` 单测经过 `FINALIZING_STREAM`
- [x] `DONE_TOOL_CONFLICT` 不执行工具
- [x] `MISSING_TOOL` 覆盖空工具；未知工具静默语义仍在
- [x] Schema `oneOf`：无顶层 `tool` 的批次示例可通过
- [x] 开关打开且批次不安全 → 不执行、不悄悄串行
- [x] WS 事件名/字段不变；无新 REST
- [x] 无 Alembic 业务新表（本阶段不改记忆表）；无 Redis；无 LightRAG；无 MCP Transport
- [x] `ruff` + `pytest tests/harness tests/test_harness.py` 等全绿

---

## 8. 本阶段交付后，阶段 4 才能开始的输入

```text
状态机含 PARALLEL_EXECUTING / FINALIZING_STREAM / CANCELLED
正确 merge_batch 与批次 span 树
默认串行、能力可开
阶段 2 取消链接到并行子任务
```

阶段 4 **不得**改并行门禁与 WS 字段，只把 Context 换成 MemoryPort。

---

## 修改代码文件与作用清单

V1.3：落地批次 Schema `oneOf`、三分支并行门禁、正确的批次 span 归并、`FINALIZING_STREAM` 与取消协同。默认仍串行，四项多媒体工具保持写操作且不可并行；无 REST/WS 契约扩展。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-Harness阶段3-并行与流式收尾.md` | 本文 |
| `backend/api/app/harness/prompts/react-output.schema.json` | 单调用 / 批次 `oneOf` 输出约束，禁止模型填 trace |
| `backend/api/app/harness/orchestration/parser.py` | 批次解析、模型完成/空工具语义保留与编排绑定 Turn |
| `backend/api/app/harness/orchestration/parallel_facade.py` | 并行三分支门禁、`gather(return_exceptions=True)` 与顺序收敛 |
| `backend/api/app/harness/feedback/normalizer.py` | `merge_batch` 的批次父子 span Fail-fast 校验 |
| `backend/api/app/harness/orchestration/{react_loop,state_machine,streaming}.py` | 批次执行、内部状态机、最终交付前流式收尾状态 |
| `backend/api/app/harness/contracts/turn.py` | 批次与流式收尾内部状态枚举 |
| `backend/api/tests/harness/test_parallel_streaming.py` | 批次解析、门禁、局部失败、归并与默认串行回归 |
| `backend/api/tests/harness/tracing/{test_contracts,test_trace}.py` | 阶段 3 Schema 与 `merge_batch` 可用性断言 |
