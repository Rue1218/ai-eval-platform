# AI 测试与评估平台 — Harness 阶段 1：单调用路径

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 阶段 1 — 单调用路径 |
| 版本 | V1.5 |
| 审查日期 | 2026-08-21 |
| 文档性质 | **开工前分析文档**（需求分析、功能点、实现路径、技术难点与对策）；代码必须按本文验收，不得超出范围 |
| 对应目标架构 | [`docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md`](docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md) **第八章为需求索引**；展开以本文为准 |
| 阶段 0 契约权威 | [`docs/AI测试与评估平台-Harness阶段0-契约骨架.md`](docs/AI测试与评估平台-Harness阶段0-契约骨架.md) V1.3（类型与 `normalize` 仍以已落地代码为准）；禁止重定义 |
| 产品/协议裁决 | PRD、[`docs/AI测试与评估平台-API.md`](docs/AI测试与评估平台-API.md)、[`docs/AI测试与评估平台-Agent开发文档.md`](docs/AI测试与评估平台-Agent开发文档.md)；JSON 字段名与路径以 API.md 为准 |
| 分支 | `feat/harness-single-call`（阶段 0 PR #52 未合入前从 `feat/harness-contracts` 拉出；合入后应 rebase 到 `origin/main`） |
| 前置依赖 | 阶段 0 验收通过（契约 + tracing Fail-fast；活路径未迁） |
| 后续阶段 | 阶段 2 强制透传与取消令牌、Alembic 三表 |

---

## 1. 从架构文档抽出的需求（为什么先做阶段 1）

目标架构 §5.3 原文：

> 阶段 1  编排/执行/反馈三层接管单调用路径（`react.py` + `mcp_tools.py` 逻辑迁入，外部行为不变）

阶段 0 已经回答「大家用哪一套对象说话」。阶段 1 要回答的产品问题只有一个：

**现网「模型 JSON → 调一个短工具 → 观察回填」仍挤在 `react.py` / `mcp_tools.py` / `app/llm.py` 里；迁进六层之后，浏览器看到的 WS、确认卡、四项多媒体工具必须与现在一样。**

六层边界在本阶段开始第一次真正被活路径踩到，但仍只踩 **单调用 ReAct 热路径**：

```text
模型 JSON
  → Parser（Schema 后的 ToolCall，trace 由编排绑定）
  → 每轮 0 或 1 次 ExecutionFacade → ExecutionOutcome
  → normalize(outcome, *, trace) → ToolResult
  → 写回 ReactArtifact.observations / WS tool_result
编排独占 harness/llm；execution / feedback 不得调模型
```

若跳过本阶段直接做阶段 2 的强制 `trace`/`cancel` 签名，回归面等于「迁循环 + 改 `/stop` + Alembic」一次爆炸。所以本阶段允许 `run_react` **新增可选** `trace=` / `cancel=`，不得删除现有参数，也不得替换 `/stop`。

---

## 2. 现状差距（架构需求 vs 现网 vs 阶段 0 已交付）

| 架构要求 | 现网 | 阶段 0 已有 | 阶段 1 要补 |
| :--- | :--- | :--- | :--- |
| 编排只认 Schema 后的 JSON | [`react.py`](backend/api/app/agent/react.py) 内联 `parse_mcp_step` + `_call_mcp_step` | `ToolCall` + `prompts/react-output.schema.json` | Parser 用 Schema，再绑定 trace；`parse_mcp_step` 变薄再导出 |
| 执行只出 `ExecutionOutcome` | `execute_short_tool` 返回 `(ok, data, error, latency)`，部分 `raise AppError` | Outcome / `error.class` 类型 | `execution/facade.py` 一份正文；tuple 包装留给测试 |
| Feedback 无条件回填 | `summarize_observation` 直接写 dict | `normalize` Fail-fast；**不公开** `merge_batch` | 循环接入 `normalize`；观察 dict 形状保持 |
| LLM 仅编排层持有 | `react.py` / `plan.py` / `reflect.py` / `context.py` / routers 直接 `app.llm` | `harness/llm/` 空壳 | 正文迁入 `harness/llm/`；`app/llm.py` 只再导出 |
| 注册表 `parallel_safe` 缺省 false | [`mcp_registry.py`](backend/api/app/agent/mcp_registry.py) 无此字段 | 无 | 补字段；本阶段强制串行 |
| `TraceContext` 贯穿 | 无 | `for_turn()` / `child()` | 循环内每次工具调用打执行 span + feedback child；总控可不传 |
| 取消 100ms SLO | `abort` + `threading.Event` | 令牌类型已定义 | **不替换** `/stop`（阶段 2） |

结论：阶段 1 是 **热路径迁入**，不是六层写满。`agent/harness.py` 总控、斜杠、确认卡、TurnMode、`run_gates` 仍留现网。

阶段 0 目录里已有空壳（`orchestration/react_loop.py`、`execution/facade.py` 等）。本阶段只填本文 §5.5 列出的文件；禁止顺手实现 Redis、并行门面、MCP 传输、`FINALIZING_STREAM`。

---

## 3. 需求分析

### 3.1 功能需求

| ID | 需求陈述 | 来源 | 优先级 |
| :--- | :--- | :--- | :--- |
| R1-1 | 编排只消费 Schema 校验后的 JSON，不把自然语言当动作 | 架构 §1.1、§3.2、AR1-01 | P0 |
| R1-2 | 一次模型响应最多执行 **1** 个短工具；忽略 `tool_calls` 并行 | 架构 §5.3、Agent §5.6、AR1-02 | P0 |
| R1-3 | 执行层公开 `execute(..., *, trace)` 只返回 `ExecutionOutcome`，普通工具错不得打崩进程 | 架构 §3.3、AR1-03 | P0 |
| R1-4 | 成功/失败/超时都经 `normalize(outcome, *, trace)` 回填；缺 trace 熔断 Turn | 架构 §3.3、§3.5、阶段 0 F0-6、AR1-04 | P0 |
| R1-5 | 注册表补 `parallel_safe=False`（缺省）、`idempotency`、沿用 `timeout_s=90` | 架构 §5.1、AR1-05 | P0 |
| R1-6 | 四项多媒体工具行为原样：`image.generate` / `audio.voiceclone` / `audio.speech_recognition` / `audio.speech_synthesis` | 架构 §5.1、AR1-06 | P0 |
| R1-7 | 长工具名不得在 api 进程执行，文案与现网 `assert_short_tool` 一致 | 架构 §4.3、AGENTS.md §5.2.4、AR1-07 | P0 |
| R1-8 | LLM 实现迁入 `harness/llm/`；仅 `orchestration/` 与 `harness/app.py` 可 import 该包 | 架构 §1.1、AR1-08 | P0 |
| R1-9 | `app/llm.py` 再导出给 REST / `plan.py` / `reflect.py` / `context.py`；错误仍归一 `VALIDATION` / `UPSTREAM` / `TIMEOUT` | 现网 `llm.py`、AR1-09 | P0 |
| R1-10 | 斜杠、确认卡、TurnMode、复核门禁、WS 事件、`dispatch_user_message` 不迁 | 架构 §5.1、§6.3、AR1-10 | P0 |
| R1-11 | 预算读现网常量：默认 4 轮、硬顶 5、墙钟 180s；禁止把架构示例 `HARNESS_MAX_REACT_STEPS=6` 当运行默认 | Agent §5.6、阶段 0 约束 3、AR1-09 | P0 |
| R1-12 | 迁完即消灭双实现：一份正文 + 薄再导出 | 架构 §5.3、AR1-11 | P0 |
| R1-13 | 只使用阶段 0 冻结名；`McpStep` 可作产品适配别名，字段必须能转到 `ToolCall` | 阶段 0 §8、AR1-13 | P0 |
| R1-14 | Parser 先走 `react-output.schema.json`，再由编排写 `trace_id`/`span_id`；禁止 `ToolCall.model_validate` 直接吃模型 JSON | 阶段 0 F0-4 / F0-8、审查残留风险 | P0 |
| R1-15 | §5.1 映射表以**现网四项工具**为准（含 `mimo_audio.py`）；领域函数正文留在 `agent/`，只经注册表分派，不复制进 `execution/adapters/` | 架构 §5.1「两项」过时；总册 V1.4 | P0 |
| R1-16 | JSON/Schema 不合法时保持现网解析失败语义（不执行工具）；不在本阶段实现「FEEDBACK_READY 回填后再调模型」的完整状态机 | 架构 §3.2.2 vs 现网 `parse_mcp_step` | P0 |

### 3.2 非功能需求

| ID | 需求 | 验收口径 |
| :--- | :--- | :--- |
| N1-1 | 对外协议冻结 | 不新增 REST/WS 字段；`tool_call`/`tool_result` 仍为 `name` / `ok` / `data|error` / `latency_ms` |
| N1-2 | 测试 import 路径兼容 | `from app.agent.react import parse_mcp_step, run_react, McpStep`；`from app.agent.mcp_tools import execute_short_tool, redact_secrets`；`from app.llm import ...` 仍可用 |
| N1-3 | 中文 docstring / 关键分支注释 | AGENTS.md §5.1 |
| N1-4 | `execution/`、`feedback/` 不 import `harness.llm` 或 `app.adapters` | ruff / grep |
| N1-5 | `harness/app.py` 仍禁止 Redis、禁止缓存请求级 `TraceContext` | 阶段 0 N0-2 继续有效；本阶段最多装配无状态 Facade / LLM 客户端工厂 |
| N1-6 | `kind=rag` 不得 mock `succeeded` | LightRAG 未接入时走 `VALIDATION` |

### 3.3 约束与裁决（本阶段冻结，避免返工）

1. **先合入阶段 0 再开本分支**。禁止在 `feat/harness-contracts` 上直接改 `react.py`。
2. **不得重定义** `TraceContext` / `CancellationToken` / `ToolCall` / `ExecutionOutcome` / `ToolResult` / `ErrorClass` / `normalize` / `MemoryPort`。要改字段，先改阶段 0 文档与架构，再改代码。
3. **禁止实现 `merge_batch`**。阶段 0 已删掉会绕过 Fail-fast 的公开实现；批量 span 树归阶段 3。
4. **现网 `parse_mcp_step` 只认 `tool` 字段**，不读 `tool_calls[]`。本阶段保持该对外行为；数组即使出现也不并行、不取多项执行。
5. **未知工具 / 写工具对外仍静默 `done=True`**（`test_parse_mcp_step_keeps_long_tool_and_drops_writes`）。内部可记 `TOOL_NOT_ALLOWED`，不改 WS payload 键。
6. **确认卡 / 鉴权 / 槽位校验继续 `raise AppError`**。Facade 只包已注册短工具。
7. **`/stop` 仍用 `abort` + `threading.Event`**。`cancel=` 可选，缺省不启用阶段 2 语义。
8. **`persona.py` 人设不迁 YAML**。Schema 已在阶段 0。
9. **禁止创建 `long_term_lightrag.py`**，禁止改 `models.py` / Alembic。
10. **空壳层不得提前填满**：`memory/short_term_redis.py`、`orchestration/parallel_facade.py`、`orchestration/streaming.py`、`execution/mcp/*` 保持空壳。
11. **`llm/usage.py` 本阶段不实现**。token 记账回填 Context 账本归阶段 4（有 `CompiledContext.ledger` 之后）。本阶段 LLM 迁入只保留现网 `call_agent_model*` / `stream_agent_model` / `parse_json_candidates`。
12. **状态机本阶段保持隐式**（Think → 0/1 工具 → 观察）。具名状态 `CONTEXT_READY` / `FEEDBACK_READY` / `FINALIZING_STREAM` / `PARALLEL_EXECUTING` 归阶段 2（取消终态）与阶段 3。

### 3.4 明确不属于阶段 1（对照架构第二章 / §4 / §5.1 / §6）

| 能力 | 架构出处 | 归属 |
| :--- | :--- | :--- |
| 强制 `trace`/`cancel`、`/stop` 令牌、Alembic 三表 | §2.2、§5.3 | 阶段 2 |
| `tool_calls[]` 可执行、`oneOf` Schema、`merge_batch`、`FINALIZING_STREAM` | §3.2.1、§3.2.2 | 阶段 3 |
| Redis / pgvector / Context 去存储 SDK | §5.2 | 阶段 4 |
| MCP Transport、`file_sandbox`、Eval-Core 适配器 | §4.1、§4.2 | **挂起**（总册覆盖矩阵） |
| 长任务 `pending` + 队列控制面 | §4.3 | **挂起**；本阶段只 `assert_short_tool` |
| `security/policy|consent|secrets` | §6.1 | **挂起**；确认卡仍 `AppError` |
| `reflect.py` / `plan.py` / `run_gates` 迁入编排 | §5.1 | **挂起** |
| `persona.py` → `system.yaml` | §1.3、§5.1 | **挂起** |
| `MISSING_TOOL` / `DONE_TOOL_CONFLICT` 对模型可见回填 | §3.2.2 | 阶段 3；本阶段对外仍静默 `done=True` |

---

## 4. 细分功能点（可开发、可测试）

每个功能点格式：输入 → 处理 → 输出 → 验收。本阶段有活路径改动，但 **HTTP/WS 契约不变**。

### F1-1 严格解析

- **输入**：模型输出的 JSON 对象或字符串（可带 Markdown 围栏）。
- **处理**：剥围栏 → 只接受 object → 用阶段 0 `react-output.schema.json` 校验（顶层与 `tool_calls[]` 均 `additionalProperties: false`）→ 映射为 `ToolCall`。
- **输出**：合法 `ToolCall`（此时 `trace_id`/`span_id` 仍为空）或内部 `ErrorClass`（`ARGUMENT_VALIDATION_ERROR` / `DONE_TOOL_CONFLICT` 等）。
- **验收**：不把「我会调用 xx」纯文本当动作；缺 `thought`/`tool`/`arguments`/`done` 失败；模型 JSON 自带 `trace_id` 被 Schema 拒绝。
- **不做**：不在 Parser 里 `execute`；不实现批次并行解析执行。

### F1-2 产品兼容解析

- **输入**：现网 `parse_mcp_step` 用例（长工具名保留、写工具丢弃、未知工具丢弃并 `done=True`）。
- **处理**：Schema 通过后，再用现网规则做产品裁剪；结果填入 `McpStep`（别名）与 `ToolCall`。
- **输出**：`parse_mcp_step` 对 `test_harness.py` 的返回形状不变。
- **验收**：`test_parse_mcp_step_keeps_long_tool_and_drops_writes` 仍绿。
- **实现要点**：`agent/react.py` 只再导出，正文在 `orchestration/parser.py`。

### F1-3 ReAct 单步循环

- **输入**：现网 `run_react(..., use_llm=True/False, stop=..., check_abort=...)`。
- **处理**：Think → 0 或 1 个短工具 → observation；模型不可用走 `tools_needed` 串行队列。可增可选 `trace=` / `cancel=`。
- **输出**：`ReactArtifact` 字段不变。
- **验收**：`run_react` 不得删现有参数；`test_harness.py` 里 monkeypatch `_stream_mcp_step` / `execute_short_tool` 的用例仍绿。
- **不做**：不把 `build_proposed_spec`、`_redirect_creative_tool`、TurnMode 迁进 harness。

### F1-4 执行门面

- **输入**：已绑定 trace 的 `ToolCall` + `db` + `user_id`。
- **处理**：`assert_short_tool` → 注册表分派 → `asyncio.to_thread` 跑领域函数；捕获超时 / `AppError` / 异常 → `ExecutionOutcome`（`error.class` 用阶段 0 枚举）。
- **输出**：永不因普通工具错向上裸抛。
- **验收**：`tests/test_imagegen.py`、`test_voiceclone.py`、`test_mimo_audio.py` 全绿。
- **不做**：不复制 `imagegen.py` / `voiceclone.py` / `mimo_audio.py` 正文。

### F1-5 注册表

- **输入**：现网四项工具定义。
- **处理**：迁到 `execution/tool_registry.py`，增加 `parallel_safe: bool = False`、`idempotency: bool = False`；`timeout_s` 仍 90。
- **输出**：`get_tool_definition` / `bind_tool_arguments` / `execute_registered_tool` / `REGISTERED_TOOLS`。
- **验收**：`test_mcp_registry.py` 绿；`SHORT_TOOLS` 仍从同一元组派生，禁止手写第二份工具名。

### F1-6 脱敏与观察

- **输入**：工具 `data` / `error` / `latency_ms`。
- **处理**：以阶段 0 `feedback/redaction.py` 为唯一正文；`collect_ids` / `summarize_observation` 迁到 `feedback/observation.py`。`mcp_tools.py` 再导出。
- **输出**：`data_summary` 形状不变（`ids` / `count` / `names` / 截断标记）。
- **验收**：`test_harness.py` 脱敏与 `collect_ids` 用例绿。
- **不做**：禁止 `mcp_tools.py` 与 `redaction.py` 再各留一份 `truncate_tool_data` 正文。

### F1-7 接入 normalize

- **输入**：Facade 的 `ExecutionOutcome` + Feedback child span。
- **处理**：`feedback_span = exec_span.child("feedback.normalize")`；`normalize(outcome, trace=feedback_span)`。`MissingTraceContext` / `TraceMismatch` **不得**变成 ToolResult，编排捕获后走失败停工具 + 对外 `INTERNAL`。
- **输出**：下一轮 `observations`；WS `tool_result` 仍用 `name/ok/data|error/latency_ms`。
- **验收**：阶段 0 tracing 三测仍绿；循环单测构造 Outcome 时显式传执行 span。
- **不做**：不调用、不重新实现 `merge_batch`。

### F1-8 LLM 迁入

- **输入**：现网 `call_agent_model` / `call_agent_model_detailed` / `stream_agent_model` / `parse_json_candidates`。
- **处理**：正文迁 `harness/llm/client.py` 与 `structured.py`；`app/llm.py` 只再导出。
- **输出**：错误码语义不变。
- **验收**：`test_agent_llm.py` 绿；`context.py` / `plan.py` / `routers` 继续 `from app.llm import ...`，**不得** `from app.harness.llm import ...`。
- **不做**：禁止 `execution/` import LLM。

### F1-9 预算读取

- **输入**：`plan.budget.max_tool_rounds`。
- **处理**：`min(值, HARD_MAX_TOOL_ROUNDS)`，常量仍来自 [`defaults.py`](backend/api/app/agent/defaults.py)（4 / 5 / 180s）。
- **输出**：轮次硬顶不变。
- **验收**：不引入环境变量 `HARNESS_MAX_REACT_STEPS=6` 作为运行默认（那是阶段 2）。

### F1-10 长工具门禁

- **输入**：工具名。
- **处理**：`jobs.py` 包装现有 `assert_short_tool`；长工具结果走 Outcome/观察，`tool_result.ok=false`，文案保持「只能入队后由 Worker 执行」。
- **输出**：对话进程不跑评测 / RAG / 压测。
- **验收**：`test_harness.py` 长任务移交用例绿；禁止 mock RAG `succeeded`。
- **不做**：不在本阶段接任务队列。

### F1-11 删除双实现

- **输入**：迁完的模块。
- **处理**：旧文件只留再导出或删除函数正文。
- **验收**：禁止 `mcp_tools.execute_short_tool` 与 `facade` 各写一份执行循环；禁止 `app/llm.py` 留完整 `call_agent_model_detailed` 正文。
- **再导出表**见 §5.3。

产品侧 **不迁**（避免范围膨胀）：`build_proposed_spec`、`_redirect_creative_tool`、TurnMode、`run_gates`、斜杠、确认卡、`dispatch_user_message`。

---

## 5. 怎么实现（技术路径）

### 5.1 包位置与导入

阶段 0 已把物理路径放在 `backend/api/app/harness/`。阶段 1 只填空壳，导入约定：

```text
允许：  orchestration/*          → harness.llm、contracts、execution.facade、feedback.normalize
允许：  harness.app              → harness.llm、execution.facade（无状态工厂；不缓存 TraceContext）
允许：  app.llm                  → harness.llm          （再导出）
允许：  app.agent.mcp_tools      → harness.feedback / execution.facade（再导出）
允许：  app.agent.react          → harness.orchestration（再导出 parse / run 入口适配）
禁止：  execution/*、feedback/*  → harness.llm 或 app.adapters
禁止：  context.py / plan.py     → app.harness.llm      （继续走 app.llm 再导出）
禁止：  routers/ws.py            → 直接 import 并执行空壳层
```

解析顺序锁死（对应 R1-14）：

```text
模型文本 → 剥围栏 → json object
  → jsonschema 校验 prompts/react-output.schema.json
  → 产品裁剪（未知工具 / 写工具 / 长工具）
  → ToolCall(...)          # 此时不填 trace
  → 编排：call.trace_id = exec_span.trace_id; call.span_id = exec_span.span_id
  → Facade.execute(..., trace=exec_span)
```

`ToolCall` 上虽有可选 `trace_id` 字段，**模型 JSON 不得经 Pydantic 直接写入**。阶段 0 Schema 已禁止顶层与 `tool_calls[]` 多余字段。

### 5.2 与活路径的接线手法

```text
阶段 1 提交内容
  ├─ 填充 parser / react_loop / facade / tool_registry / observation / llm
  ├─ agent/react.py、mcp_tools.py、mcp_registry.py、app/llm.py 改为薄再导出 + 产品适配
  ├─ 单测：现网用例 + harness tracing 仍绿
  └─ 禁止：Alembic、ws.py 新字段、Redis、merge_batch、/stop 改令牌
```

`agent/harness.py` 继续调用 `run_react`，不直接 import 执行层。循环内若调用方未传 `trace`，内部 `TraceContext.for_turn()` 仅服务本轮工具 span（与阶段 2 从 `dispatch_user_message` 注入的同一 Turn 不是一回事，见难点 6）。

### 5.3 旧路径处理（消灭双实现）

| 旧模块 | 迁完后 |
| :--- | :--- |
| `mcp_registry.py` | 薄再导出 `REGISTERED_TOOLS` / `get_tool_definition` / `bind_tool_arguments` / `execute_registered_tool` |
| `mcp_tools.py` | 薄再导出 `redact_secrets`、`truncate_tool_data`、`collect_ids`、`summarize_observation`、`execute_short_tool`、`tool_title` |
| `react.py` | 保留 `ReactArtifact`、`build_proposed_spec`、`run_react` 入口、`McpStep` 别名；解析/执行/循环正文在 harness |
| `app/llm.py` | 再导出，**禁止**留一份完整 `call_agent_model_detailed` 正文 |
| `imagegen.py` 等 | **不删**，由注册表分派 |
| `long_tasks.py` | 保留；`jobs.py` 调用它，不复制名单 |

`execute_short_tool` 对测试保持 tuple 签名：内部调 Facade 再拆开，**只一份执行正文**。

再导出文件只 import harness；**harness 的 registry / facade 不得 import `mcp_tools.py`**，避免循环。

### 5.4 实现顺序（本阶段任务流）

1. 确认阶段 0 已合入 `main`，再 `git fetch origin && git checkout -b feat/harness-single-call origin/main`。
2. 填 `tool_registry`（补 `parallel_safe`）→ 把 `redaction` 收成唯一正文 → `observation.py` → `facade.execute` 返回 Outcome。
3. 填 `parser.py`：Schema + 现网裁剪 + `ToolCall`；`react.py` 再导出 `parse_mcp_step`。
4. 填 `react_loop.py` / 薄 `budgets.py`（读 `defaults.py`）：`_emit_and_run_tool` 改为 Facade + `normalize`；WS 字段保持。
5. 迁 `llm` 正文，`app/llm.py` 改再导出；编排 import `app.harness.llm`。
6. 删重复正文；`ruff check`；跑 §7 清单中的 pytest。
7. 对照本文第 3、4 节勾验收，超范围文件（Redis、并行、Alembic）一律移出本 PR。

### 5.5 代码落点对照

| 功能点 | 文件 |
| :--- | :--- |
| F1-1 / F1-2 | `harness/orchestration/parser.py`；`agent/react.py` 再导出 |
| F1-3 / F1-9 | `harness/orchestration/react_loop.py`、`budgets.py`（只读产品常量） |
| F1-4 / F1-5 / F1-10 | `harness/execution/facade.py`、`tool_registry.py`、`jobs.py` |
| F1-6 / F1-7 | `harness/feedback/redaction.py`（已有）、`observation.py`、`normalizer.py`（已有，只接入不改 Fail-fast） |
| F1-8 | `harness/llm/client.py`、`structured.py`；`app/llm.py` 再导出 |
| F1-11 | 旧模块删正文、只留再导出 |

`harness/app.py`：若需要无状态工厂，只构造 Facade / LLM 客户端；**禁止** `RedisShortTermMemory`、禁止 `_RUNTIME` 保存 `TraceContext`。

---

## 6. 技术难点与对策

### 难点 1：架构要 `TOOL_NOT_ALLOWED` 回填模型，现网却静默 `done=True`

`parse_mcp_step` 对未知工具丢弃名称并 `done=True`；架构 §3.2.2 希望 observation 带内部枚举。§5.1 又要求行为不变。

**对策**：对外 WS / `McpStep` 保持静默停工具；对内 Outcome 或日志可带 `error_class=TOOL_NOT_ALLOWED`。阶段 3 再考虑让模型看见该枚举。

### 难点 2：`run_react` 测试耦合私有函数与 `McpStep`

`test_harness.py` import `_stream_mcp_step`、`McpStep`，并 monkeypatch `app.agent.react.execute_short_tool`。

**对策**：这些名字作为适配别名保留。`McpStep` 由 `ToolCall` 填充。`execute_short_tool` 继续挂在 `react` 模块可 patch 的位置（再导出或显式绑定），避免测试大爆炸。

### 难点 3：Facade 一律 Outcome，确认卡仍是产品 `AppError`

确认卡不进六层（架构 §6.3）。

**对策**：门面只包已注册短工具。`confirm_ack` / 槽位 / 鉴权仍在 `harness.py` 里 `raise AppError`。

### 难点 4：模型 JSON 可能自带 `trace_id`，而 `ToolCall` 恰好有该可选字段

阶段 0 审查残留：`ToolCall.model_validate(模型JSON)` 会把伪造 trace 写进去。

**对策**：Parser 必须先走 JSON Schema（已 `additionalProperties: false`），再构造 `ToolCall` 且不拷贝 trace 字段。单测覆盖「模型带 `trace_id` → 校验失败」。

### 难点 5：`to_thread` 生图与取消令牌不是同一套 Event

现网短工具在线程里跑，取消靠 `threading.Event`。阶段 0 令牌是 `asyncio.Event`。

**对策**：本阶段 Facade 保持 `stop: threading.Event` 与现网一致。`cancel=` 可选且默认空。不伪称已实现 100ms SLO（阶段 2 做双事件镜像）。

### 难点 6：循环内临时 `for_turn()` 与阶段 2 全链路不是同一 trace

阶段 0 禁止改几十处签名。

**对策**：`run_react` 增加可选 `trace=`；`agent/harness.py` 本阶段可不传。内部自建的 Turn 只保证「这一次工具调用的执行 span 与 feedback parent 成对」，以便 `normalize` Fail-fast。阶段 2 再从 `dispatch_user_message` 注入同一 Turn。

### 难点 7：`PARALLEL_READONLY_TOOLS` 已存在但为 False

**对策**：可读该开关，本阶段 **强制串行**。不要 `asyncio.gather`，不要填 `parallel_facade.py`。

### 难点 8：再导出造成循环 import

现网链：`mcp_tools` → `defaults` → `mcp_registry`。

**对策**：再导出文件只 import harness。`tool_registry` / `facade` 不得 import `mcp_tools.py`。`SHORT_TOOLS` 继续从迁后的 `REGISTERED_TOOLS` 派生。

### 难点 9：Fail-fast 与「工具异常不得打崩 Agent」

阶段 0 难点 3 已裁决：`MissingTraceContext` / `TraceMismatch` 不是可重试 `ErrorClass`。

**对策**：`normalize` 继续直接 raise。编排捕获后停工具，对外 `INTERNAL`，不生成无来源 ToolResult。普通工具超时/失败仍走 Outcome → `normalize` → 回填。

### 难点 10：空壳被一次填满，造成「六层已经迁完」的假象

阶段 0 难点 8 的续篇。

**对策**：本 PR 必选仅 §5.5 文件 + 再导出。`memory/`、`context/`、`security/`、`execution/mcp/` 保持空壳。审查时用 grep：`ws.py` / `harness.py` 不得引用未验收层。

### 难点 11：架构 §5.1 写「迁入 adapters/」，复制领域函数会造成双实现

**对策**：`imagegen.py` / `voiceclone.py` / `mimo_audio.py` **不搬文件**。注册表分派调用现网函数。§5.1 该行视为「经注册表分发」，不是「复制一份到 adapters」。`execution/adapters/` 保持空壳（挂起 MCP/文件适配）。

### 难点 12：架构示例 JSON 与阶段 0 Schema 不一致

批次示例没有顶层 `tool`。本阶段 Schema 仍要求 `tool`，且忽略 `tool_calls[]` 不执行。

**对策**：不在本阶段放宽 Schema。阶段 3 用 `oneOf` 解决。单测继续用现网单 `tool` 载荷。

---

## 7. 验收清单

- [x] 阶段 0 类型被循环使用，没有第三套 dict / 第二套 `McpStep` 契约
- [x] 模型 JSON 先 Schema 后绑定 trace；带 `trace_id` 的模型输出被拒绝
- [x] 每轮最多 1 个工具；`parallel_safe` 缺省 false；无 `gather` / 无 `merge_batch`
- [x] `pytest tests/test_harness.py tests/test_mcp_registry.py tests/test_imagegen.py tests/test_voiceclone.py tests/test_mimo_audio.py tests/test_agent_llm.py tests/harness/tracing tests/test_errors.py` 全绿
- [x] `ruff check app/harness app/llm.py app/agent`
- [x] WS `tool_call` / `tool_result` 字段名不变
- [x] `app/llm.py` 无重复实现正文；`execution/` 不 import `harness.llm`
- [x] `mcp_tools.py` 与 `facade.py` 不各写一份 `execute_short_tool` 正文
- [x] 无 Alembic、无新 REST/WS 字段、无 Redis 业务读写、无 `/stop` 改令牌
- [x] `kind=rag` 仍不得 mock succeeded
- [x] `agent/harness.py` 总控、斜杠、确认卡未迁
- [x] 未实现 `llm/usage.py` 账本、未填 `execution/mcp/` / `security/` / `file_sandbox`
- [x] `imagegen.py` / `voiceclone.py` / `mimo_audio.py` 无第二份正文

---

## 8. 本阶段交付后，阶段 2 才能开始的输入

阶段 2 开工前必须已经：

```text
run_react 可选 trace= / cancel=（缺省兼容现网）
ExecutionFacade.execute(..., *, trace) → ExecutionOutcome
normalize 接入单调用循环
harness/llm 为唯一模型正文；app.llm 再导出
REGISTERED_TOOLS.parallel_safe 缺省 false
parse_mcp_step / execute_short_tool / redact_secrets 测试 import 仍可用
```

阶段 2 **不得**重做 Parser / Facade 正文。它只做：公开方法改为强制 `trace`/`cancel`、`/stop` 接令牌、Alembic 三表、预算环境变量。

阶段 2 文档若与本文冲突，以本文冻结的「单调用行为」为准，以阶段 2 文档冻结的「透传与持久化」为准。

---

## 修改代码文件与作用清单

V1.5：审查修复——活路径改为 `execute(..., *, trace)`，`normalize` 的 ToolResult 回填观察；`execute_short_tool` 仅作测试 tuple 与 monkeypatch 锚点。

V1.4：在 `feat/harness-single-call` 落地单调用热路径。阶段 0 PR #52 尚未合入 `main`，本分支从 `feat/harness-contracts` 拉出，避免把阶段 1 代码堆进阶段 0 PR。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/tool_registry.py` | 四项工具注册表正文；补 `parallel_safe=False`、`idempotency=False` |
| `backend/api/app/harness/execution/facade.py` | 公开 `execute(..., *, trace)`；tuple 包装给测试；`bind_arguments` 供编排调用 |
| `backend/api/app/harness/execution/jobs.py` | 包装现网 `assert_short_tool` |
| `backend/api/app/harness/feedback/observation.py` | `collect_ids` / `summarize_observation` 唯一正文 |
| `backend/api/app/harness/orchestration/parser.py` | Schema 校验 + 现网产品裁剪 + `McpStep`/`ToolCall` |
| `backend/api/app/harness/orchestration/react_loop.py` | 单调用循环：`execute` → `normalize` → 观察 / WS |
| `backend/api/app/harness/orchestration/budgets.py` | 只读产品 4/5/180s |
| `backend/api/app/harness/llm/client.py` | `call_agent_model*` / `stream_agent_model` 正文 |
| `backend/api/app/harness/llm/structured.py` | `parse_json_candidates` 正文 |
| `backend/api/app/agent/mcp_registry.py` | 薄再导出 |
| `backend/api/app/agent/mcp_tools.py` | 薄再导出 |
| `backend/api/app/agent/react.py` | 保留确认卡规格组装；循环/解析再导出；保留 monkeypatch 锚点 |
| `backend/api/app/llm.py` | 薄再导出；保留 `call_protocol` 测试锚点 |
| `backend/api/tests/harness/test_parser.py` | Schema 拒绝 `trace_id` |
| `backend/api/tests/harness/test_single_call.py` | 调用方 trace 进入 Outcome；normalize 脱敏后回填 |
| `backend/api/tests/harness/tracing/test_contracts.py` | 阶段 1 再导出允许 import harness；WS/总控仍禁止 |
| `docs/AI测试与评估平台-Harness阶段1-单调用路径.md` | 回写落地 diff 与验收勾选（本文） |
