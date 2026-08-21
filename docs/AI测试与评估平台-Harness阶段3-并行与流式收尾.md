# AI 测试与评估平台 — Harness 阶段 3：并行与流式收尾

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 阶段 3 — 并行与流式收尾 |
| 版本 | V1.1 |
| 审查日期 | 2026-08-21 |
| 文档性质 | **开工前分析文档**（需求分析、功能点、实现路径、技术难点与对策）；未勾验收前禁止合入、禁止开阶段 4 |
| 对应目标架构 | 架构文档 §3.2.1 / §3.2.2 / §3.5 末段 / §5.3 |
| 前置阶段权威 | 阶段 2 强制 trace/cancel；阶段 0 **禁止错误 merge_batch**（伪造 parent 绕过 Fail-fast） |
| 产品/协议裁决 | API.md；Agent §5.6 第一阶段串行保证 `tool_call`/`tool_result` 成对。本阶段实现能力，**默认行为仍串行** |
| 分支 | `feat/harness-parallel-stream` |
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
| `ToolCallBatch` + `ParallelFacade` | 类型已有；Parser 忽略 `tool_calls[]`（阶段 1 冻结的现网行为） | Parser 识别数组；门禁失败则整批拒绝并行并串行或回填 `PARALLEL_POLICY_VIOLATION` |
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
| R3-4 | 上限 `min(HARNESS_MAX_PARALLEL_CALLS, 连接池容量)`，默认 4 | §3.2.2 | P0 |
| R3-5 | `ordered_results` 按 `batch_index`；`results_by_call_id` 可反查 | §3.2.1 | P0 |
| R3-6 | 正确实现 `merge_batch` 的批次 span 树校验 | §3.5 末段、阶段 0 审查 P1 | P0 |
| R3-7 | `done=true` 且无工具 → `FINALIZING_STREAM`；流结束 + 持久化成功 → `FINISHED` | §3.2.2 | P0 |
| R3-8 | `done=true` 仍带 `tool` 或非空 `tool_calls` → 不执行，回填 `DONE_TOOL_CONFLICT` | §3.2.2 | P0 |
| R3-9 | 产品开关默认关：关时批次也串行执行，保证 `tool_call`/`tool_result` 成对、`event_id` 不乱 | Agent §5.6 | P0 |
| R3-10 | 现网四项多媒体工具不得被标成 `parallel_safe=true` | §5.1 行为不变 | P0 |
| R3-11 | 取消必须落到未开始的并行子任务；已开始的走阶段 2 cancelled Outcome | §3.2.2、§4.4 | P0 |
| R3-12 | 不新增 WS 事件名；并行开启时仍成对发 `tool_call` / `tool_result` | API.md | P0 |

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

---

## 4. 细分功能点

### F3-1 批次解析

- **输入**：模型 JSON，可能含 `tool_calls`。
- **处理**：Schema 校验（阶段 0 已禁 extra / 禁 item 级 trace）→ `ToolCallBatch`；编排绑定 trace，每 call 派生子 span。
- **输出**：合法 Batch 或内部错误类。
- **验收**：模型在 item 上塞 `trace_id` 被 Schema 拒绝。

### F3-2 并行门禁

- **输入**：Batch + 注册表。
- **处理**：逐项检查 `parallel_safe`、幂等、资源、授权、数量上限、开关。
- **输出**：允许并行 / 整批改串行 / `PARALLEL_POLICY_VIOLATION` 回填且不执行。
- **验收**：四项多媒体工具走串行；桩工具可并行。

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
| F3-2 / F3-3 / F3-8 | `orchestration/parallel_facade.py`、`state_machine.py`、`authorization.py` |
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

---

## 7. 验收清单

- [ ] 默认串行：四项多媒体 `parallel_safe=false`；现网测试全绿
- [ ] 桩工具并行：gather 局部失败保留成功项
- [ ] `ordered_results` 按 `batch_index`；`results_by_call_id` 可反查
- [ ] `merge_batch` mismatch 熔断；无伪造 parent
- [ ] `done=true` 单测经过 `FINALIZING_STREAM`
- [ ] `DONE_TOOL_CONFLICT` 不执行工具
- [ ] WS 事件名/字段不变；无新 REST
- [ ] 无 Alembic 业务新表（本阶段不改记忆表）；无 Redis；无 LightRAG
- [ ] `ruff` + `pytest tests/harness tests/test_harness.py` 等全绿

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

V1.1：按阶段 0 模板补齐五块分析；吸收阶段 0 对错误 `merge_batch` 的否决。**尚未写业务代码**。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-Harness阶段3-并行与流式收尾.md` | 本文 |
