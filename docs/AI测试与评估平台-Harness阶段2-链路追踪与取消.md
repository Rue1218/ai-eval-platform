# AI 测试与评估平台 — Harness 阶段 2：链路追踪与取消

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 阶段 2 — 链路追踪与取消 |
| 版本 | V1.4 |
| 审查日期 | 2026-08-21 |
| 文档性质 | **阶段施工文档**（需求分析、功能点、实现路径、技术难点与对策 + 代码落地） |
| 对应目标架构 | [`docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md`](docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md) §2.2 / §3.2.2 / §3.5 / §4.4 / §5.3 / §5.4 |
| 前置阶段权威 | 阶段 0 冻结类型；阶段 1 单调用循环已用可选 `trace=` / `cancel=` 接入 `normalize` |
| 产品/协议裁决 | API.md、Agent 开发文档；`/stop` 与 WS 事件名以 API.md 为准，本阶段不新增字段 |
| 分支 | `feat/harness-trace-cancel`（从 `feat/harness-single-call` 拉出：阶段 1 尚未合入 `main`） |
| 前置依赖 | 阶段 1 验收通过 |
| 后续阶段 | 阶段 3 并行与流式收尾 |

---

## 1. 从架构文档抽出的需求（为什么先做阶段 2）

架构 §5.3 原文：

> 阶段 2  TraceContext / CancellationToken 强制透传 + 诊断审计持久化

阶段 0 定义了令牌和 Fail-fast；阶段 1 为了不把 `/stop` 与 Alembic 绑进热路径迁移，只把 `trace=` / `cancel=` 做成**可选**。本阶段要回答的产品问题只有一个：

**用户点停止、断线或会话关闭之后，同一条因果链必须可回放；本地取消调度必须在 100ms 内发出，且缺 trace 的结果不得再混进模型上下文。**

```text
dispatch_user_message
  → TraceContext.for_turn()     # 一个用户 Turn 一个 trace_id
  → CancellationToken(turn_id)
  → run_react(..., *, trace, cancel)     # 不可选
  → 每层 child(component)
  → /stop → cancel.request("user_stop") + 镜像 stop.set() + task.cancel()
  → PG：harness_turns / harness_spans / harness_diagnostics
```

100ms 是 **Harness 本地调度 SLO**（置位 → 停 LLM 流读取 / 取消未开始的本地 task）。不含远端真正停止时间。无 MCP 客户端时不得伪报已向 Server 发取消。本地已停的 task 记 `cancelled`；无法确认的远端记 `cancel_requested`。

---

## 2. 现状差距

| 架构要求 | 阶段 1 结束后 | 阶段 2 要补 |
| :--- | :--- | :--- |
| 公开方法 `*, trace: TraceContext` 不可选 | `run_react` 可选；总控可不传 | `dispatch_user_message` 创建根 trace 并强制下传 |
| `CancellationToken` 贯穿执行与 LLM 流 | 类型存在；活路径仍 `abort` + `threading.Event` | 令牌为主，线程 `stop` 作镜像；`/stop` 调 `request()` |
| 诊断可回放、traceback 不进模型 | 进程内 `InMemoryAuditStore` 上限 256 | Alembic 三表；`record_diagnostic` 写入 PG |
| 预算环境变量回显 | 读 `defaults.py` 常量 | 接入 §3.2.2 八键；**运行默认仍是产品 4/5/180s**，不是表里的示例 6/60 |
| `CANCELLED` 后不再编上下文、不再调模型 | 现网 `HarnessAborted` 退出 | 状态机 `CANCELLING → CANCELLED`；已开始工具 → Outcome cancelled |
| 缺 trace Fail-fast | `normalize` 已有 | 公开 API 缺 `trace` 在类型/测试层直接失败；诊断拒绝空 trace |

结论：阶段 2 **不重写 Parser / Facade 执行正文**，只把可选参数改成强制，并让取消与审计落地。

---

## 3. 需求分析

### 3.1 功能需求

| ID | 需求陈述 | 来源 | 优先级 |
| :--- | :--- | :--- | :--- |
| R2-1 | Turn 入口创建唯一 `TraceContext`；跨层必须 `child(component)`，禁止把 `call_id` 当 trace | §2.2、§3.5 | P0 |
| R2-2 | `run_react` / `Facade.execute` / `normalize` / LLM 流读取以关键字参数接收不可选 `trace`；执行路径另收不可选 `cancel` | §2.2 | P0 |
| R2-3 | `/stop`、会话关闭、WS 断开置位同一 `CancellationToken`；`request` 幂等 | §3.2.2、§4.4、API.md `/stop` | P0 |
| R2-4 | 本地取消调度 ≤100ms：停流读取、取消未开始的本地 task；**不含** MCP 远端往返（见 R2-11） | §4.4、总册挂起项 | P0 |
| R2-5 | 已开始未完成的短工具 → `ExecutionOutcome.cancelled` / `cancel_requested`，经 `normalize` 回填；**当前 Turn 禁止为回填再调模型** | §3.2.2 | P0 |
| R2-6 | Alembic 新增 `harness_turns` / `harness_spans` / `harness_diagnostics`；审计不进 Redis | §5.4、AGENTS.md 红线 4 | P0 |
| R2-7 | `record_diagnostic` 写入 PG；保留天数默认 30；缺 trace 仍 Fail-fast | §3.5、§5.4、阶段 0 diagnostics | P0 |
| R2-8 | 环境变量接入预算键，启动日志回显生效值；产品默认 硬顶 5 / 墙钟 180s / 默认轮次 4 | §3.2.2 vs Agent §5.6、阶段 1 R1-11 | P0 |
| R2-9 | WS `/stop` 语义与事件名不变；无新 REST 字段 | API.md、§5.3 | P0 |
| R2-10 | 单副本或粘性路由前提暂时不变；不把 `_HARNESS_BY_SESSION` 迁 Redis（那是扩副本议题，非本阶段） | 驾驭工程架构说明 | P1 |
| R2-11 | 100ms SLO 的本地动作仅限：置位令牌、停 LLM 流读取、`task.cancel()`、取消**尚未开始**的本地执行。**不得**声称已向 MCP Server 发出 `CancelledNotification`（`execution/mcp/` 仍空壳） | §4.4 vs 总册挂起项 | P0 |
| R2-12 | 结构化日志 / `publisher` 自动带 `trace_id`、`span_id`、`turn_id`；禁止依赖人工拼接。`agent_trace` 脱敏红线不变 | §3.5 Logging、§5.1 `log.py` | P0 |
| R2-13 | 本阶段写入 span 表的范围：编排 / 执行 / 反馈。Context / Memory span 等阶段 4 接线后补 | §3.5 树 vs 阶段 4 | P0 |
| R2-14 | 预算**键名**接入八项；**执行语义**默认仍只用产品轮次硬顶与墙钟。指纹 / 连续可重试 / 上下文重建默认关闭，未设 env 不得把循环次数改成架构表示例 | §3.2.2 vs Agent §5.6、WS 行为不变 | P0 |

### 3.2 非功能需求

| ID | 需求 | 验收口径 |
| :--- | :--- | :--- |
| N2-1 | 中文 docstring / 迁移脚本中文说明 | AGENTS.md §5.1 |
| N2-2 | traceback / API Key 不进 `agent_trace`、不进模型 observation | AGENTS.md 红线 3 |
| N2-3 | Alembic upgrade/downgrade 可逆 | `alembic upgrade head` / `downgrade -1` |
| N2-4 | 100ms 单测可用假时钟或记录 `dispatch_latency_ms`，不测远端 RTT | 与 §4.4 口径一致 |
| N2-5 | 阶段 0 tracing 用例仍绿 | `pytest tests/harness/tracing` |

### 3.3 约束与裁决

1. **不重做** Parser / 多媒体工具 / `app.llm` 再导出结构。
2. **禁止**把架构表示例 `HARNESS_MAX_REACT_STEPS=6`、`HARNESS_TURN_DEADLINE_S=60` 当成运行默认；env 缺省必须映射产品常量。
3. **禁止**实现 `merge_batch` / `ParallelFacade` / `FINALIZING_STREAM`（阶段 3）。
4. **禁止** Context 接 Redis（阶段 4）；审计三表只在 PG。
5. **禁止**新增 WS 事件名或 `/stop` JSON 字段。
6. `asyncio.Event` 为主、`threading.Event` 为镜像：`cancel.request()` 必须同时 `stop.set()`，否则 `to_thread` 里的短工具看不见取消。
7. 改 `models.py` 必须生成 Alembic，禁止服务器手工改库。
8. **`MissingTraceContext` 告警**本阶段等于：`agent_trace` + 熔断 Turn + 对外 `INTERNAL`。不接外部 pager / 不新增 REST 告警字段。
9. **不属于本阶段**：MCP Transport、`file_sandbox`、`security/`、`merge_batch`、MemoryPort 接存储、把 `HARNESS_MAX_REACT_STEPS=6` 当缺省。

### 3.4 明确不属于阶段 2

| 能力 | 归属 |
| :--- | :--- |
| MCP `CancelledNotification` / `X-Trace-Id` 请求头 | 挂起（无 MCP 客户端） |
| `cancel_ack_latency_ms`、`remote_completion_after_cancel` | 挂起；本阶段只测 `dispatch_latency_ms` |
| 长任务 `job_ref` + `idempotency_key` 取消 | 挂起（§4.3） |
| 诊断 30 天定时清理任务 | 本阶段只留 `created_at` + 保留天数常量；定时 job 可后补 |
| `FINALIZING_STREAM` / 并行子任务取消扇出 | 阶段 3（接到本阶段令牌） |
| `BUDGET_EXHAUSTED` 后再发起「最后一次无工具权限」模型调用 | 默认关闭；若设 env 显式打开再走内部 observation，对外文案仍固定、不新 WS 字段 |

---

## 4. 细分功能点

### F2-1 根 Trace 注入

- **输入**：`dispatch_user_message` / 回合入口。
- **处理**：`trace = TraceContext.for_turn()`；下传 `run_react(..., trace=trace)`。
- **输出**：本 Turn 内所有 span 同 `trace_id`。
- **验收**：结构化日志或 span 表同一 `trace_id`；缺参无法通过类型检查/单测。
- **不做**：不在服务 `__init__` 缓存上一次 Turn。

### F2-2 强制关键字参数

- **输入**：阶段 1 的可选 `trace=` / `cancel=`。
- **处理**：核心公开方法改为不可选；测试夹具一律构造 `TraceContext` + `CancellationToken`。
- **验收**：省略 `trace` 的调用在单测中失败。

### F2-3 `/stop` 接令牌

- **输入**：现网 `SessionHarness.abort` / `stop`。
- **处理**：`SessionHarness` 持有 `cancel`；`/stop`：`cancel.request("user_stop")` → 镜像 `stop.set()` → `abort.set()` → `task.cancel()`。
- **输出**：循环在下一 `raise_if_cancelled` / await 点退出。
- **验收**：现网 `/stop` 测试仍绿；WS 关闭码与事件不变。
- **不做**：不改「仅当前发言人可 stop」的产品规则。

### F2-4 双 Event 镜像

- **输入**：编排层 `asyncio.Event`，工具线程 `threading.Event`。
- **处理**：`request()` 两处置位；Facade 在 `to_thread` 前后检查。
- **验收**：取消后线程内短工具不再提交结果到已关闭会话（保持现网 `_await_thread` 语义）。

### F2-5 取消 Outcome

- **输入**：运行中的 `execute`。
- **处理**：`CancelledError` / `TurnCancelled` → `ExecutionOutcome.cancelled`（远端未 ack 则 `cancel_requested`）→ `normalize`。
- **输出**：`CANCELLED` 终态；禁止再 `build_context` / 调模型。
- **验收**：取消 Turn 不出现「为了回填再推理一轮」。

### F2-6 三张审计表

- **输入**：架构 §5.4 列定义。
- **处理**：`app/models.py` + Alembic；`publisher` / diagnostics 写入。
- **输出**：Turn 一行、Span 多行、诊断受限存储。
- **验收**：upgrade/downgrade 可逆；无 Redis 写入审计。

### F2-7 诊断迁 PG

- **输入**：阶段 0 `record_diagnostic(exc, *, trace)`。
- **处理**：实现换成 PG；测试可注入内存 store。保留 30 天（定时清理可本阶段只留常量 + 注释，任务可后补，但表结构要有 `created_at`）。
- **验收**：缺 trace 仍 `MissingTraceContext`；写入含真实异常文本（阶段 0 已修 `format_exception`）。

### F2-8 预算环境变量

- **输入**：§3.2.2 八键。
- **处理**：`budgets.py` 读 env；缺省=产品值（硬顶 5 / 墙钟 180s / 默认轮次 4）；启动 `agent_trace` 回显（无密钥）。
- **输出**：调用方可读生效值。
- **验收**：不设 env 时硬顶仍为 5、墙钟 180s。
- **不做**：不把架构表示例 6/60 写成代码缺省；不默认启用指纹 / 连续错误 / 重建次数截断（见 F2-9）。

### F2-9 预算停止条件（默认关）

- **输入**：`max_same_call_fingerprint` / `max_consecutive_retryable_error` / `max_context_rebuilds`。
- **处理**：仅当对应 env **显式设置** 才启用截断；截断时内部可记 `BUDGET_EXHAUSTED`，对外仍走现网停工具/固定文案，不新 WS 字段。
- **验收**：未设 env 的现网 `test_harness.py` 循环次数不变。
- **不做**：不实现「最后一次无工具权限再调模型」除非产品测试已覆盖且不改 WS。

### F2-10 结构化追踪日志

- **输入**：现网 `agent_trace`。
- **处理**：`publisher.py` 输出必须能带上 `trace_id`/`span_id`/`turn_id`；禁止把 API Key、Cookie、完整提示词打进日志。
- **验收**：Turn 内至少一条带同一 `trace_id` 的记录可与 `harness_turns` 对上。
- **不做**：不新增浏览器可见事件。

### F2-11 取消 Outcome（已有 F2-5 的补充口径）

与 F2-5 相同路径。额外冻结：无 MCP 适配器时，远端状态一律记 `cancel_requested` 不得伪报 `cancelled`（本地 task 已停仍可用 `cancelled`）。

---

## 5. 怎么实现

### 5.1 取消链

```text
WS /stop 或断开
  → cancel.request(reason)          # 幂等，记 monotonic
  → stop.set()                      # 线程镜像
  → abort.set()                     # 现网兼容
  → task.cancel()
  → Facade.raise_if_cancelled()
  → LLM stream 停止读取
  → Outcome cancelled → normalize
  → turn.status = CANCELLED
```

### 5.2 实现顺序

1. 从已含阶段 1 的 `main` 拉 `feat/harness-trace-cancel`。
2. Alembic 三表 + models。
3. `SessionHarness` 持有 token；`/stop` 接线。
4. `run_react` / Facade / LLM 流改为强制 `trace`/`cancel`。
5. diagnostics 切 PG，测试注入内存实现。
6. budgets 读 env，启动回显。
7. `pytest` 阶段 1 全套 + tracing + 新取消/迁移测试；`ruff`。

### 5.3 代码落点

| 功能点 | 文件 |
| :--- | :--- |
| F2-1 / F2-3 | `agent/harness.py`（总控仍在此；只加 token，不把斜杠/确认卡迁走） |
| F2-2 / F2-5 | `orchestration/react_loop.py`、`execution/facade.py`、`llm/client.py` |
| F2-4 | `contracts/cancellation.py` 或薄适配；Facade |
| F2-6 | `app/models.py`、`migrations/versions/*` |
| F2-7 | `feedback/diagnostics.py`、`feedback/publisher.py` |
| F2-8 | `orchestration/budgets.py`、`harness/app.py` 启动回显 |
| F2-9 | `orchestration/budgets.py`（默认关的截断开关） |
| F2-10 | `feedback/publisher.py`；`agent/log.py` 可再导出，禁止第二套脱敏 |
| F2-11 | 同 F2-5 |

---

## 6. 技术难点与对策

### 难点 1：100ms SLO 容易测成「远端停没停」

**对策**：只断言 `cancel.dispatch_latency_ms()`（从 `request` 到本地 cancel 调用返回）。远端 ack 另字段，不计入 SLO。

### 难点 2：asyncio.Event 与 threading.Event

**对策**：`request()` 同时置位两者。禁止只改 asyncio 侧却声称已接线。

### 难点 3：强制 `trace=` 会打碎阶段 1 测试夹具

**对策**：测试统一 `TraceContext.for_turn()`；不要在生产路径给 `trace` 默认值（默认值等于没强制）。

### 难点 4：架构表默认 6/60 与产品 5/180 冲突

**对策**：env **缺省值写产品常量**。架构表作为「可覆盖上限的键名清单」，不作为未配置时的运行数字。启动日志必须打出实际生效值。

### 难点 5：进程内 `_HARNESS_BY_SESSION` 与多副本

**对策**：本阶段不迁 Redis。文档写明仍要求单副本或粘性路由。阶段 4 的 Redis 是记忆层，不是 abort registry，除非另开扩容任务。

### 难点 6：诊断从内存切 PG 时测试不连库

**对策**：`record_diagnostic` 依赖可注入 Port；pytest 用阶段 0 的 `InMemoryAuditStore`。

### 难点 7：§4.4 清单含「向 MCP 发取消」，但客户端不存在

若本阶段写空的 `CancelledNotification`，审查者会以为 MCP 层已接通。

**对策**：取消链在 Facade / LLM 流 / 本地 task 终止。文档与单测只断言这三段的 `dispatch_latency_ms`。MCP 项留在总册挂起矩阵。

### 难点 8：八键接入被理解成「循环行为改成架构表」

`MAX_SAME_CALL_FINGERPRINT=2` 会让现网同一工具连调 4 轮的用例失败。

**对策**：缺省映射产品常量；指纹类键未设置则不截断。启动日志打印「未启用」。

---

## 7. 验收清单

- [x] 公开执行/编排/LLM 流 API 缺少 `trace`/`cancel` 无法通过单测
- [x] `/stop` 置位 token 后循环退出；WS 协议不变
- [x] `dispatch_latency_ms` 口径为本地调度，默认预算 100
- [x] Alembic upgrade/downgrade 可逆；三表在 PG 不在 Redis
- [x] `pytest tests/test_harness.py tests/harness/tracing` 及多媒体 / llm 用例全绿
- [x] 未配 env 时轮次硬顶 5、墙钟 180s；指纹类截断默认关
- [x] 无新 REST/WS 字段；无 `merge_batch`；无 LightRAG 文件
- [x] 无 MCP Transport / `file_sandbox` / `security/` 实现
- [x] `publisher` 日志含 `trace_id`；热路径 `agent_trace` 自动带链路 ID
- [x] 取消先持久化 `CANCELLING`，收敛后写 `CANCELLED`
- [x] `TurnStatus` 在契约层，feedback 不引用 orchestration
- [x] `ruff check` 通过

---

## 8. 本阶段交付后，阶段 3 才能开始的输入

```text
强制 trace / cancel 已从 dispatch 贯穿到 Facade 与 LLM 流
/stop 与令牌同一条链
harness_turns / spans / diagnostics 可写入
budgets 可读 env 且产品默认不变
normalize Fail-fast 仍然有效
```

阶段 3 **不得**重做取消链与三表，只加并行门面、正确的 `merge_batch`、`FINALIZING_STREAM`。

---

## 修改代码文件与作用清单

V1.4：按审查补齐 P0/P1。`run_react` / `stream_mcp_step` / `stream_agent_model` 强制 `trace`/`cancel`；热路径日志经 ContextVar 自动带 ID；取消先写 `CANCELLING`；`TurnStatus` 下沉契约层。

V1.3：强制 `trace`/`cancel`、`/stop` 接令牌、Alembic 三表、预算 env 与结构化追踪日志已落地。分支从 `feat/harness-single-call` 拉出（阶段 1 尚未合入 `main`）。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-Harness阶段2-链路追踪与取消.md` | 本文 |
| `backend/shared/models.py` | 新增 `HarnessTurn` / `HarnessSpan` / `HarnessDiagnostic` |
| `backend/api/app/models.py` | 再导出审计三表 |
| `backend/api/migrations/versions/b7e4a1c90825_新增harness审计三表.py` | Alembic 可逆迁移 |
| `backend/api/app/harness/contracts/cancellation.py` | `request()` 同时置位 asyncio + threading Event |
| `backend/api/app/harness/contracts/turn.py` | `TurnStatus` 下沉契约层，feedback 不再引用 orchestration |
| `backend/api/app/harness/contracts/trace.py` | `using_trace` / `current_trace`，热路径日志自动带 ID |
| `backend/api/app/agent/log.py` | `agent_trace` 从当前 span 自动加前缀 |
| `backend/api/app/harness/orchestration/state_machine.py` | 再导出 `TurnStatus`（不含 FINALIZING_STREAM） |
| `backend/api/app/harness/orchestration/budgets.py` | 八键读 env，缺省=产品 5/180s/4；指纹类默认关 |
| `backend/api/app/harness/feedback/diagnostics.py` | `record_diagnostic` 可注入；生产 `PgAuditStore` |
| `backend/api/app/harness/feedback/publisher.py` | Turn/Span 持久化；`set_turn_status` 支持 `CANCELLING` |
| `backend/api/app/harness/app.py` | 启动回显预算并切换 PG 审计存储 |
| `backend/api/app/main.py` | lifespan 调用 `configure_runtime` |
| `backend/api/app/harness/execution/facade.py` | `execute(..., *, trace, cancel)` 强制；取消 Outcome |
| `backend/api/app/harness/orchestration/react_loop.py` | 强制透传；取消后不再调模型；编排 span 记真实耗时 |
| `backend/api/app/harness/llm/client.py` | 流式调用强制 `trace`/`cancel`，块间检查取消 |
| `backend/api/app/agent/react.py` | 薄封装：`run_react` 强制同一 Turn 的 trace/cancel |
| `backend/api/app/agent/harness.py` | 根 Trace + `/stop` 先写 `CANCELLING`；闲聊流接下发令牌 |
| `backend/api/app/routers/ws.py` | 断线置位同一令牌（不直接 import `app.harness`） |
| `backend/api/app/routers/sessions.py` | 会话删除时取消进行中 Turn |
| `backend/api/tests/harness/test_trace_cancel.py` | 阶段 2 强制参数、100ms SLO、预算缺省、审计表 |
| `backend/api/tests/harness/tracing/test_contracts.py` | 总控允许引用契约；WS 仍不得 import 六层包 |
| `backend/api/tests/test_shared_models.py` | EXPECTED_TABLES 补三表 |
