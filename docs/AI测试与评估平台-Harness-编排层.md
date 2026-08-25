# AI 测试与评估平台 — Harness 编排层模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 编排层模块设计 |
| 版本 | V0.4.3 |
| 审查日期 | 2026-08-25 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计） |
| 适用模块 | M4 编排层（`app/harness/orchestration/` + `app/agent/`） |
| 上游权威 | Harness 需求文档 V1.4.4 §2.3/§2.4/§2.5、§4.4、§7、§9；API.md V1.22 §4.3/§4.4/§5；PRD §5.1.2/§5.1.3 |

> **阅读关系**：本文是 Harness §9.2「层 4 编排」行的展开，定义图拓扑、模式路由、GraphState 引用、`should_abort` 全链路迁移与 Direct 路径。GraphState 主体在 M3（`memory/state.py`），事件契约在 M7（`contracts/events.py`），本文只引用不重定义。

---

## 1. 模块定位与边界

### 1.1 定位

编排层是 Harness 的**控制流核心**：选择模式（Chat / Direct / ReAct / Plan-and-Solve）、生成可验证中间状态、把图节点产出收敛为 `NodeEvent` 交收包循环 emit。模型只做结构化判断，副作用由执行层（M5）与 Worker 承担，编排层不直接执行长任务。

当前已落地的是**单轮图**（`app/agent/graph.py`：`START → call_model/stream_model → END`）。本模块按阶段 1→2→4 把模式路由、预算、门禁、确认回执逐层接入图拓扑。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 图拓扑（节点 + 条件边）与模式路由 | GraphState 主体定义（M3 `memory/state.py`） |
| `should_abort` 全链路迁移（Agent 图 + ModelGateway + adapters） | 模型协议适配（`app/llm/`、`app/adapters.py` 稳定基线） |
| Direct 路径 L0 路由（斜杠识别，不进模型） | 系统斜杠 15 条前端本地注册表（前端） |
| `PlanArtifact` 规划解析 + 重试降级（OR-2/3） | PlanArtifact 类型定义（M7 `contracts/artifacts.py`） |
| 预算 / 占槽 / 长工具门禁（OR-5/6/7） | 工具注册表与执行（M5） |
| 确认卡回执 `handle_confirm_ack`（OR-8，阶段 4） | 确认卡业务字段校验（PRD §5.1.2，由 `confirm.py` 调用） |
| 节点产出 `NodeEvent` 交收包循环 | WS emit / 广播（`ws.py` 收包循环） |

### 1.3 红线（继承 Harness §7 + AGENTS.md）

- 图节点**只返回纯数据**（`NodeEvent` / artifact），不持有 WS 连接、不直接 emit。
- `should_abort` 等回调**不得入 GraphState**；走 `RunnableConfig.configurable`（非检查点内容）。
- 长任务（benchmark/testcase/rag/stress）**不得**在对话回合内同步执行（OR-6）。
- `confirm_ack` 当前返回 `VALIDATION`，阶段 4 才落地 `handle_confirm_ack`，**禁止** mock 任务成功。
- 不私自扩充 ws event；不引入 `create_react_agent`；不编排 LLM 子代理。

---

## 2. 需求发散

### 2.1 从 Harness §4.4 提取的编排需求

| 编号 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| OR-1 | 模式路由：斜杠→Direct；无工具→Chat；短工具→ReAct；多槽位业务→Plan-and-Solve | O-1：路由节点按 `text` 前缀与 PlanArtifact 分流 | 阶段 1（Direct/Chat）→2（ReAct）→4（Plan-Solve） |
| OR-2 | `PlanArtifact` 冻结字段（含 `allows_replan`） | O-2：`plan.py` 产出 PlanArtifact（类型在 M7） | 阶段 4 |
| OR-3 | 规划解析失败重试一次，仍失败走 L0 规则降级，降级后必须经复核 | O-3：规划解析重试 + L0 降级 + 复核门禁 | 阶段 4 |
| OR-4 | 同轮多个原生 ToolCall **串行**过门禁，禁止无门禁并行；legacy 每轮至多一个短工具；重复调用抑制 | O-4：ReAct 循环内串行执行 + 重复抑制 | 阶段 2 |
| OR-5 | 默认模型调用 / 工具轮次均为 12（`budget.py`）；计划可派生收紧；死循环由预算兜底 | O-5：`budget.py` 预算计数与熔断 | 阶段 2 |
| OR-6 | 长任务不得在对话回合内同步执行 | O-6：`gates.py` `is_long_tool` 门禁 | 阶段 2 |
| OR-7 | 会话存在活动任务时禁止再发确认卡 | O-7：`gates.py` 占槽门禁返回 `CONCURRENCY` | 阶段 4 |
| OR-8 | `task.create` 只在 `confirm_ack.ok=true` 且 patch 合并后二次校验通过时发生 | O-8：`confirm.py` `handle_confirm_ack` 事务 | 阶段 4 |

### 2.2 从 §2.5 提取的事件桥接与确认卡需求

| 来源 | 需求 | 发散 |
| :--- | :--- | :--- |
| §2.5 事件桥接 | 图节点返回纯数据，事件由收包循环统一发出 | O-9：节点产出 `NodeEvent` 写入 `GraphState.pending_events`，`ws.py` 消费后清空 |
| §2.5 确认卡 | 收包循环直连，`sessions.pending_confirm` 唯一状态源 | O-10：`handle_confirm_ack` 在 `ws.py` 收包循环直连，不唤醒图、不占回合预算 |
| §2.5 /stop | `asyncio` 任务取消，不可恢复；`interrupt()` 仅澄清卡 | O-11：`/stop` 保持现有 `StreamAborted` 传播，不接 `interrupt()` |

### 2.3 从 §2.4 提取的 `should_abort` 迁移需求

| 来源 | 需求 | 发散 |
| :--- | :--- | :--- |
| §2.4 | 接入 Checkpointer 前须先把 `should_abort` 等回调移出 State | O-12：阶段 1 启动全链路迁移 `should_abort` 至 `RunnableConfig.configurable`（Agent 图 + ModelGateway + adapters）；**阶段 3 接入 Checkpointer 前必须完成（阻断验收项，见 §3.4）** |

### 2.4 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| O-A1 | 阶段 1：斜杠 `text` 进 Direct 分支，不调模型；非斜杠进 Chat | 路由断言 |
| O-A2 | 阶段 1：`should_abort` 不出现在 GraphState 字段中 | 反射断言 |
| O-A3 | 阶段 1：`should_abort` 经 `RunnableConfig.configurable` 注入，取消仍触发 `StreamAborted` | 取消单测 |
| O-A4 | 阶段 1：节点产出 `NodeEvent` 写入 `pending_events`，收包循环 emit 后清空 | 事件桥接断言 |
| O-A5 | 阶段 2：ReAct 每轮至多一个工具，重复调用抑制 | 循环断言 |
| O-A6 | 阶段 2：长工具被门禁拦截（`VALIDATION`/`CONCURRENCY`） | 门禁用例 |
| O-A7 | 阶段 4：`confirm_ack.ok=true` + patch 合并 + 二次校验通过才 `task.create` | 确认回执事务断言 |
| O-A8 | 阶段 4：`confirm_ack.ok=false` 不入队，卡标已取消 | 取消断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/orchestration/
├── __init__.py
├── router.py          # 阶段 1：模式路由（条件边分流）
├── plan.py            # 阶段 4：PlanArtifact 规划解析 + 重试降级
├── budget.py          # 阶段 2：模型调用预算 + 工具轮次预算
├── gates.py           # 阶段 2：长工具/占槽/会话活动门禁
└── confirm.py         # 阶段 4：handle_confirm_ack 确认卡回执

app/agent/
├── graph.py           # 修改：阶段 1 接入路由节点；阶段 2/4 接入 ReAct/Plan-Solve/reflect 条件边
├── routing.py         # 阶段 1：路由节点（Direct/Chat 分流）
├── clarify.py         # 阶段 3：澄清卡 interrupt() 节点（Command(resume)，不建任务不写 pending_confirm）
├── react.py           # 阶段 2：ReAct 子图（agent 节点 + ToolNode 条件边）
├── plan_solve.py      # 阶段 4：Plan-and-Solve 执行子图（图内复用节点）
└── reflect.py         # 阶段 4：reflect 节点（pass/clarify/reject 条件边）
```

> `state.py` 不在本模块——按决策移至 `app/harness/memory/state.py`（M3）。本模块通过 M3 提供的 GraphState 引用 `pending_events` 等字段。

### 3.2 GraphState 引用关系（M3 主体 + M7 契约）

GraphState 由 M3 定义，本模块只**消费/写入**字段，不重定义。阶段 1 涉及的字段（设计意图）：

| 字段 | 类型 | 归属 | 本模块用法 |
| :--- | :--- | :--- | :--- |
| `request` | 可序列化请求投影（不含 `should_abort`） | M3 | 路由节点读取 `text` 判断斜杠 |
| `pending_events` | `list[NodeEvent]` | M3（引用 M7） | 节点写入，收包循环消费后清空 |
| `mode` | `Literal["chat","direct","react","plan_solve"]` | M3 | 路由节点写入，条件边消费 |
| `plan` | `PlanArtifact \| None` | M3（引用 M7） | 阶段 4 `plan.py` 写入 |

> `should_abort` **不在此表**——它走 `RunnableConfig.configurable`，不是 GraphState 字段（见 §3.4）。

### 3.3 阶段 1 图拓扑（Chat + Direct）

```text
START
  → routing（路由节点：读 text 前缀）
       ├─ text 以 "/" 开头 → direct 分支（L0 规则，不调模型）
       │      → 产出 NodeEvent（控制动作 / VALIDATION）→ END
       └─ 否则 → chat 分支（沿用现有 call_model / stream_model）
              → 产出 NodeEvent（assistant_message / response.completed）→ END
```

**路由节点职责**（`app/agent/routing.py`）：

1. 读 `state.request` 的用户文本（M3 提供可序列化投影，不含回调）。
2. 判定 `text.strip().startswith("/")` → 写 `state.mode = "direct"`；否则 `state.mode = "chat"`。
3. 条件边按 `mode` 分流到 `direct` 或 `chat` 节点。

**Direct 节点职责**（L0 规则路由，不进模型）：

- 识别已知斜杠（`/stop` `/compact` `/cancel` `/stress` `/help`），命中则产出对应 `NodeEvent` 或触发控制动作。
- `/stop`：保持现有 `asyncio` 任务取消（不在图内处理，由 `ws.py` 收包循环拦截，见 §3.7）。
- 未命中已知斜杠 → 产出 `NodeEvent(kind="error", payload={"code":"validation","message":"未知斜杠命令"})`。
- 系统斜杠 15 条前端本地注册表不在 Agent 侧处理（API.md：前端本地）。

**Chat 节点职责**：沿用现有 `_stream_model_node` / `_call_model_node`，但 `should_abort` 改从 `RunnableConfig` 读取（§3.4），产出 `NodeEvent` 写入 `pending_events`。

### 3.4 `should_abort` 全链路迁移（阶段 1 启动，阶段 3 阻断）

**现状**：`ModelRequest.should_abort: StreamAbort | None`（`llm/contracts.py:49`），由 `ws.py:_run_turn` 闭包 `abort.is_set` 注入；`_AgentState.request: ModelRequest` 把含回调的 `ModelRequest` 塞进 State——违反 §2.4 可序列化红线。

**迁移目标**：`should_abort` 全链路走 `RunnableConfig.configurable`，不进 GraphState、不进 `ModelRequest`。

**迁移点**：

| 层 | 现状 | 迁移后 |
| :--- | :--- | :--- |
| `app/llm/contracts.py` | `ModelRequest.should_abort` 字段 | **移除**该字段 |
| `app/llm/gateway.py` | 节点从 `state.request.should_abort` 取 | 节点从 `get_config()["configurable"]["abort"]["should_abort"]` 取，传给 `stream_protocol` |
| `app/adapters.py` | `stream_protocol(..., should_abort=...)` 参数保留 | 参数保留（函数参数，不入 State） |
| `app/agent/graph.py` | `_AgentState.request: ModelRequest` | `request` 改为可序列化投影（M3 提供），回调不入 State |
| `app/routers/ws.py` | `ModelRequest.from_messages(..., should_abort=abort.is_set)` | `graph.astream({...}, config={"configurable": {"abort": {"should_abort": abort.is_set}}})` |

**关键约束**：`RunnableConfig` 不是 GraphState，不进 Checkpointer 检查点，回调放此处安全。`ModelRequest` 移除 `should_abort` 后变为纯数据，可序列化。

**向后兼容**：本次迁移是阶段 1 一次性完成，不留双路径；测试 `test_llm_graph.py` / `test_agent_graph.py` 同步改造（夹具改用 `RunnableConfig` 注入回调）。

**阶段 3 阻断验收项（V0.4.2 评审闭环）**：`should_abort` 迁移是接入 Checkpointer 的**硬前置条件**，不得当作普通后续优化。阶段 3 PR 合入前必须全部满足，否则不得引入 `PostgresSaver`：

1. `ModelRequest` 不含任何回调字段（反射断言，O-A2）；
2. GraphState 全字段 `json.dumps` 通过（对齐 M3 E-A1/E-A2）；
3. 取消回调经 `RunnableConfig.configurable["abort"]["should_abort"]` 注入，`/stop` 仍触发 `StreamAborted`（O-A3）；
4. `test_llm_graph.py` / `test_agent_graph.py` 夹具全部改用 `RunnableConfig` 注入，无遗留 `should_abort` 传参。

### 3.5 模式路由（OR-1，跨阶段演进）

```text
阶段 1：routing 节点
         ├─ "/" 前缀 → direct
         └─ 否则    → chat

阶段 2：routing 节点
         ├─ "/" 前缀 → direct
         ├─ 无工具需求 → chat
         └─ 短工具需求 → react（ReAct 子图）

阶段 4：routing 节点
         ├─ "/" 前缀 → direct
         ├─ 无工具需求 → chat
         ├─ 短工具需求 → react
         └─ 多槽位业务 → plan_solve（PlanArtifact 驱动）
```

**路由判定输入**：阶段 1 只看 `text` 前缀；阶段 2+ 需要模型先输出"是否需要工具"的轻量判断（或规则启发式），具体在 `router.py` 实现时定（见 §7 开放问题）。

### 3.6 Direct 路径 L0 路由规则

**已知斜杠与处理方式**（对齐 API.md §4.4）：

| 斜杠 | 处理位置 | 阶段 | 产出 |
| :--- | :--- | :--- | :--- |
| `/stop` | `ws.py` 收包循环拦截（不进图） | 阶段 0 已落地 | `asyncio` 取消 + `response.completed(cancelled)` |
| `/compact` | M2 上下文层（会话级副作用，仅 owner） | 阶段 3 | `NodeEvent(progress)` + 上下文摘要 |
| `/cancel` | `ws.py` 收包循环（取消本会话非终态任务） | 阶段 4 | `task.cancel` + `NodeEvent` |
| `/stress` | 对话路径不得发 `kind=stress` 确认卡 | 阶段 4 | `NodeEvent(error, validation)` |
| `/help` | Direct 节点直接返回帮助文本 | 阶段 1 | `NodeEvent(assistant_message)` |
| 未知 `/xxx` | Direct 节点 | 阶段 1 | `NodeEvent(error, validation)` |

**阶段 1 Direct 节点最小实现**：只处理 `/help`（返回帮助文本）与未知斜杠（`VALIDATION`）；`/stop` 仍由 `ws.py` 拦截；`/compact` `/cancel` `/stress` 留阶段 3/4 填充，阶段 1 命中时返回 `VALIDATION`（"能力未启用"）。

**与系统斜杠 15 条的关系**：API.md 规定系统 15 条命令前端本地注册表，不走 Agent；Agent 侧只处理上表控制类斜杠。两者不重叠。

### 3.7 事件桥接（节点 → NodeEvent → 收包循环）

```text
图节点执行
  → 产出 NodeEvent（M7 契约）写入 GraphState.pending_events
  → 图输出（astream updates 模式）
  → ws.py 收包循环读 pending_events
  → 翻译为 ws event：
       持久化 kind → _emit_persistent（落 ws_events + 广播）
       瞬态增量（assistant_delta / thought.stream=think）→ 沿用 get_stream_writer 直接投影
  → 消费后清空 pending_events
```

**与现有 `ws.py:_run_turn` 的关系**：当前 `_run_turn` 在 WS 层直接调 `_AGENT.astream` 并投影流事件。阶段 1 改造后，`_run_turn` 仍负责消费 `astream` 输出，但改为读 `pending_events` 统一 emit，节点内不再持有 `websocket`。瞬态帧（`assistant_delta`）仍由节点 `get_stream_writer` 投影，`_run_turn` 通过 `stream_mode=["custom","updates"]` 接收——沿用现有机制。

**`pending_events` 消费时机（已决）**：每节点完成即消费（流式友好），通过 `astream` 的 `updates` 模式按节点边界读取 `pending_events`；清空由**图外收包循环**完成（消费后置空，不依赖图内下一节点）。`pending_events` 在 GraphState 用 append reducer 累积，收包循环消费后通过图外置空（非图内节点清空）。

**事件生产者归属（V0.4.2 收敛，对齐 M7 §3.6.1 归属矩阵）**：`pending_events` 只承载**图节点**产出的事件意图；`user_message`（用户上行）由 `ws.py` 收包循环直产，`progress`/`report`/`error`（Worker 链路）由 Worker `push_ws` 直产并实时转发（见 M9）——图节点不得与直产方重复 emit 同名事件。`confirm_ack` 回执由收包循环直连（O-10），不进 `pending_events`。

**`/stop` 拦截点**：`/stop` 在 `ws.py` 收包循环识别（`text.startswith("/stop")`），直接 `abort.set()` + 取消 `active_turn`，不进图。与 Direct 节点不冲突（`/stop` 不路由到图）。

### 3.8 阶段 2/4 图拓扑演进

**阶段 2（ReAct 接入）**：

```text
routing → mode="react"
  → react 子图（app/agent/react.py）
       agent 节点（LLM 调用 + 严格 JSON 解析）
         → 条件边：done → END / tool → ToolNode（M5）
       ToolNode（M5 toolnode.py，包装注册表）
         → 回 agent 节点（受 budget.py 轮次预算约束，OR-4/5）
```

- `budget.py`：默认 `model_calls=12` / `tool_turns=12`；计划可派生收紧，死循环仍由预算兜底。
- `gates.py`：`is_long_tool` 门禁拦截 benchmark/testcase/rag/stress（OR-6）。
- 重复工具调用抑制（OR-4）在 react 子图内实现；native 同轮多 ToolCall 必须逐个过门禁后串行执行。

**阶段 4（Plan-and-Solve + reflect；确认卡仍 WS 直连）**：

```text
routing → mode="plan_solve"
  → plan_solve（build_plan：解析失败重试一次→L0 合并全部命中技能，3–7 步）
  → react_agent ⇄ tools（按【当前规划】执行短工具；长任务只说明确认卡入队）
  → reflect（确定性门禁 + 可选 review；发出本轮唯一 response.completed）
       pass / clarify → completed(stop)（clarify interrupt 属后续阶段）
       reject → error + completed(error)
```

- `confirm.py` `handle_confirm_ack`（OR-8）：在 `ws.py` 收包循环直连，不唤醒图：
  - `ok=true`：patch 深合并 → 按 PRD §5.1.2 / API.md §5 二次校验 → 通过则 `task.create`（创建 `queued` Task + AuditLog）→ 清空 `pending_confirm` → emit `confirm_ack`/`tool_call`/`tool_result`。
  - `ok=false`：不入队，卡标已取消，清空 `pending_confirm`。
- `gates.py` 占槽门禁（OR-7）：会话存在活动任务时禁止再发 `confirm`，返回 `CONCURRENCY`。
- `reflect` 模型辅助核对只能 `pass→clarify` 降级，不得 `reject→pass`（FB-3）。

> Plan-Solve 子图与 ReAct 子图均为**图内复用节点**（Harness §2.2 裁决），不引入独立 LLM 循环、不编排 LLM 子代理。

### 3.9 接口签名规格（签名级）

> 本节给出本模块对外/对内接口的函数签名与类型定义，作为实现契约。GraphState 主体在 M3，本节只列被引用字段的签名；契约类型在 M7，本节只列引用。

#### 3.9.1 枚举与字面量

```python
from typing import Literal

# 路由模式（写入 GraphState.mode，条件边消费）
AgentMode = Literal["chat", "direct", "react", "plan_solve"]

# 已知斜杠（Direct 节点 L0 路由匹配）
KnownSlash = Literal["/help", "/compact", "/cancel", "/stress", "/stop"]
```

#### 3.9.2 GraphState 被引用字段（M3 主体，本模块读写）

> 以下为签名级 sketch，`Observation`/`Mapping`/`to_dict` 等导入在实现 PR 时按需补齐（`from app.harness.contracts import Observation`、`from typing import Mapping`、`from app.harness.contracts import to_dict`）。

```python
from typing import TypedDict
from app.harness.contracts import NodeEvent, PlanArtifact

class _AgentStateRef(TypedDict, total=False):
    """本模块读写的 GraphState 字段切片；主体定义在 app/harness/memory/state.py。"""
    request: "SerializableRequest"   # M3 提供，不含 should_abort 回调
    mode: AgentMode                   # 路由节点写，条件边读（GraphState 内投影为 Literal，见 M3 §2.2）
    pending_events: list[NodeEvent]   # 节点 append，收包循环消费后清空
    plan: PlanArtifact | None         # 阶段 4 plan.py 写，plan_solve 读
    response: Mapping[str, object]    # chat_stream_node 写（ModelResponse 投影，可序列化）
    verdict: "ReflectVerdict | None"  # 阶段 4 reflect_node 写（GraphState 内投影为 Literal，见 M3 §2.2）
    observations: list[Observation]   # 阶段 2 ReAct 子图内 ToolNode（M5）写
    stop_flag: bool                   # 节点写，条件边读
    budget: Mapping[str, int]         # 阶段 2 budget 节点写（Budget 投影，见 M3 §2.2）
```

> `SerializableRequest` 由 M3 定义，是 `ModelRequest` 移除 `should_abort` 后的可序列化投影（`config`/`messages`/`system`/`tools`）；`tools` 承接 M2 `assemble` 产出的工具定义（CX-5）。

#### 3.9.3 路由与节点签名（`app/agent/routing.py` + `graph.py`）

```python
from langgraph.graph import StateGraph, END, START
from app.harness.memory.state import GraphState  # M3 主体
from app.harness.contracts import NodeEvent

def route(state: GraphState) -> AgentMode:
    """路由条件边函数：读 state['request'] 文本前缀，返回分流模式。
    斜杠前缀 → 'direct'；否则 'chat'（阶段 2+ 增 'react'/'plan_solve'）。"""

def routing_node(state: GraphState) -> dict:
    """路由节点：写 state['mode']，不调模型。返回 {'mode': AgentMode}。"""

def direct_node(state: GraphState) -> dict:
    """Direct 节点：L0 规则匹配已知斜杠，不调模型。
    返回 {'pending_events': [NodeEvent, ...]}。
    未知斜杠 → NodeEvent(kind='error', payload={'code':'validation','message':'未知斜杠命令'})。
    /help → NodeEvent(kind='assistant_message', payload={...})。
    /compact /cancel /stress（阶段 1 未启用）→ NodeEvent(kind='error', validation)。"""

def chat_stream_node(state: GraphState) -> dict:
    """Chat 流式节点（沿用现有 _stream_model_node，改造回调来源）。
    从 state['request']（SerializableRequest）+ config 回调构造 ModelRequest 调 ModelGateway。
    should_abort 从 RunnableConfig.configurable 读取（见 3.9.4）。
    正文/推理增量经 get_stream_writer 投影；收尾写
    {'pending_events': [NodeEvent(kind='assistant_message',...),
                        NodeEvent(kind='response.completed',...)],
     'response': to_dict(ModelResponse)}。  # 投影为 Mapping，保证 GraphState 可序列化（§2.4）"""

def build_agent_graph() -> StateGraph:
    """阶段 1 Agent 图构造：
    START → routing → (direct | chat_stream) → END。
    条件边：routing → route(state) 映射 mode 到节点名。"""
```

#### 3.9.4 `should_abort` 全链路迁移签名

```python
# app/llm/contracts.py —— 移除 should_abort 字段
@dataclass(frozen=True, slots=True)
class ModelRequest:
    config: ModelConfig
    messages: tuple[Message, ...] = field(default_factory=tuple, repr=False)
    system: str | None = field(default=None, repr=False)
    tools: tuple[Mapping[str, object], ...] = field(default_factory=tuple, repr=False)  # M2 assemble 产出的工具定义（CX-5）
    # should_abort 字段移除（迁移至 RunnableConfig）

# app/llm/gateway.py —— 节点从 RunnableConfig 读取回调
from langgraph.config import get_config

def _stream_node(state) -> dict:
    should_abort = get_config().get("configurable", {}).get("abort", {}).get("should_abort")
    # 传给 stream_protocol(..., should_abort=should_abort)

# app/routers/ws.py —— 调用方注入回调（命名空间 abort）
await graph.astream(
    {"request": serializable_request},
    config={"configurable": {"abort": {"should_abort": abort.is_set}}},
    stream_mode=["custom", "updates"],
)
```

> `RunnableConfig` 不进 Checkpointer 检查点，回调放此处安全。`adapters.stream_protocol` 的 `should_abort` 参数保留（函数参数，不入 State）。

#### 3.9.5 编排辅助模块签名（`app/harness/orchestration/`）

```python
# router.py —— 模式路由判定（阶段 2+ 扩展）
def decide_mode(text: str, *, has_tool_intent: bool = False,
                has_multi_slots: bool = False) -> AgentMode:
    """阶段 1：仅按 text 前缀（斜杠→direct，否则 chat）。
    阶段 2+：hybrid 策略——先规则启发式（关键词匹配）判 has_tool_intent；
              不确定时再轻量模型调用确认；has_multi_slots→plan_solve。"""

# budget.py —— 预算控制（OR-4/OR-5）
@dataclass(frozen=True, slots=True)
class Budget:
    model_calls: int = 0       # 规划+重试+补规划+核对，上限 4
    tool_turns: int = 0          # 工具轮次，默认上限 4、硬上限 5
    max_model_calls: int = 4
    max_tool_turns: int = 4
    hard_max_tool_turns: int = 5

def consume_model_call(b: Budget) -> Budget:
    """模型调用预算 +1；超限抛 AppError(BUDGET_EXCEEDED)。"""

def consume_tool_turn(b: Budget) -> Budget:
    """工具轮次 +1；超 hard_max 抛 AppError(BUDGET_EXCEEDED)。"""

def is_budget_exhausted(b: Budget) -> bool: ...

# gates.py —— 门禁（OR-6/OR-7）
LONG_TOOLS: frozenset[str] = frozenset(
    {"benchmark.run", "testcase.generate", "rag.evaluate", "stress.run"}
)

def is_long_tool(name: str) -> bool:
    """判定是否长工具（OR-6，对话回合内禁止同步执行）。"""

def check_session_active_task(db, session_id: str) -> None:
    """会话存在活动任务时抛 AppError(CONCURRENCY)（OR-7，禁止再发确认卡）。"""

# confirm.py —— 确认卡回执（OR-8，阶段 4）
@dataclass(frozen=True, slots=True)
class ConfirmAckResult:
    ok: bool
    task_id: str | None = None
    reason: str | None = None

def handle_confirm_ack(db, session_id: str, user_id: str,
                        payload: dict) -> ConfirmAckResult:
    """收包循环直连，不唤醒图：
    1. 行锁读 sessions.pending_confirm + owner 校验
    2. ok=true → patch 深合并 → 按 PRD §5.1.2/API.md §5 二次校验
       → 通过则 task.create(queued) + AuditLog → 清空 pending_confirm
    3. ok=false → 清空 pending_confirm，不入队
    返回 ConfirmAckResult，由 ws.py emit confirm_ack/tool_call/tool_result。"""

# plan.py —— 规划解析（OR-2/OR-3，阶段 4）
def build_plan(raw: str) -> PlanArtifact:
    """严格 JSON 解析为 PlanArtifact；内部调 M1 `parse_plan_protocol` 做协议校验。
    失败重试一次，仍失败走 L0 规则降级；降级产物必须经 reflect 复核（FB-2）。"""
```

#### 3.9.6 阶段 2/4 子图签名（`app/agent/react.py` / `clarify.py` / `plan_solve.py` / `reflect.py`）

```python
# react.py —— ReAct 子图（阶段 2）
def build_react_subgraph(tool_node) -> StateGraph:
    """agent 节点（LLM + 严格 JSON 解析）→ 条件边 → ToolNode（M5）→ 回 agent。
    受 budget.consume_tool_turn 约束；重复工具调用抑制（OR-4）。"""

# clarify.py —— 澄清卡 interrupt() 节点（阶段 3）
def clarify_node(state: GraphState) -> dict:
    """澄清卡节点：产出 NodeEvent(kind='clarify', payload={'id': str, 'question': str,
    'options': list[str] | None, 'context': str | None})，调用 LangGraph `interrupt()` 暂停图。
    不建任务、不占回合预算、不写 sessions.pending_confirm（与 confirm 互斥）。
    `id` 为本次澄清的唯一标识（uuid4），用于匹配前端 `clarify_reply.id`。
    用户回复后由 ws.py 转 `Command(resume, update={'clarify_answer': answer})` 恢复图（M9 §3.5.1）。"""

# plan_solve.py —— Plan-and-Solve 执行子图（阶段 4）
def build_plan_solve_subgraph() -> StateGraph:
    """图内复用节点（无独立 LLM 循环）：按 PlanArtifact.steps 顺序复用
    chat/react 节点执行。禁止编排 LLM 子代理。"""

# reflect.py —— reflect 节点（阶段 4）
ReflectVerdict = Literal["pass", "clarify", "reject"]

def reflect_node(state: GraphState) -> dict:
    """确定性门禁先行：调 M6 `rules.check_gates`（规则）→ 按需调 M6 `review.review`（模型辅助核对）
    → 条件边 pass/clarify/reject。模型辅助核对只能 pass→clarify 降级，不得 reject→pass（FB-3）。
    失败反馈预算由 M6 `FeedbackBudget` 约束（FB-4）。本节点为 reflect.py owner，调 M6 库函数。
    返回 {'verdict': ReflectVerdict, 'pending_events': [NodeEvent, ...]}。"""
```







---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_agent_routing.py`（阶段 1）、`test_agent_react.py`（阶段 2）、`test_agent_plan_solve.py` / `test_confirm_ack.py`（阶段 4）。`test_agent_graph.py` / `test_llm_graph.py` 同步改造。

| 阶段 | 测试用例 | 覆盖验收 |
| :--- | :--- | :--- |
| 1 | `test_routing_slash_goes_direct_no_model_call` | O-A1 |
| 1 | `test_routing_plain_text_goes_chat` | O-A1 |
| 1 | `test_graph_state_has_no_should_abort_field` | O-A2 |
| 1 | `test_should_abort_via_runnable_config_triggers_stream_aborted` | O-A3 |
| 1 | `test_node_events_emitted_via_pending_events` | O-A4 |
| 1 | `test_unknown_slash_returns_validation` | O-A1 |
| 2 | `test_react_at_most_one_tool_per_turn` | O-A5 |
| 2 | `test_react_duplicate_tool_suppressed` | O-A5 |
| 2 | `test_long_tool_blocked_by_gate` | O-A6 |
| 4 | `test_confirm_ack_ok_true_creates_task_after_patch_merge` | O-A7 |
| 4 | `test_confirm_ack_ok_false_cancels_card` | O-A8 |

**TDD 顺序**：每阶段先写测试全红 → 实现节点/路由 → 全绿。`should_abort` 迁移测试需同步改造 `test_llm_graph.py` 夹具（`RunnableConfig` 注入回调）。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/orchestration/router.py` | 阶段 1 | 新增 | OR-1 |
| `app/agent/routing.py` | 阶段 1 | 新增 | OR-1（路由节点 + 条件边） |
| `app/agent/graph.py` | 阶段 1 | 修改 | 接入路由节点，保留 Chat 路径 |
| `app/routers/ws.py` | 阶段 1 | 修改 | 图输出 → 收包循环统一 emit；`should_abort` 走 `RunnableConfig` |
| `app/llm/contracts.py` | 阶段 1 | 修改 | 移除 `ModelRequest.should_abort` |
| `app/llm/gateway.py` | 阶段 1 | 修改 | `should_abort` 从 `RunnableConfig` 读取 |
| `app/harness/orchestration/budget.py` | 阶段 2 | 新增 | OR-4/OR-5 |
| `app/harness/orchestration/gates.py` | 阶段 2 | 新增 | OR-6 |
| `app/agent/react.py` | 阶段 2 | 新增 | ReAct 子图 |
| `app/agent/clarify.py` | 阶段 3 | 新增 | 澄清卡 interrupt() 节点（Command(resume)，§2.5） |
| `app/harness/orchestration/plan.py` | 阶段 4 | 新增 | OR-2/OR-3 |
| `app/harness/orchestration/confirm.py` | 阶段 4 | 新增 | OR-8（handle_confirm_ack） |
| `app/agent/plan_solve.py` | 阶段 4 | 新增 | Plan-and-Solve 执行子图 |
| `app/agent/reflect.py` | 阶段 4 | 新增 | reflect 节点 |
| `backend/api/tests/test_agent_routing.py` | 阶段 1 | 新增 | O-A1~O-A4 |
| `backend/api/tests/test_agent_graph.py` | 阶段 1 | 修改 | `should_abort` 夹具改造 |
| `backend/api/tests/test_llm_graph.py` | 阶段 1 | 修改 | `should_abort` 夹具改造 |

> `state.py` 不在本清单——移至 `app/harness/memory/state.py`（M3）。

---

## 6. 依赖与红线

- **上游依赖**：M7（`NodeEvent`/`PlanArtifact` 契约）、M3（GraphState 主体）、API.md §4.4（斜杠规则）/§5（确认卡校验）、PRD §5.1.2（确认卡字段）/§5.1.3（事件）。
- **下游被依赖**：M5（执行层消费 `mode`/`ToolCall`）、M6（反馈层消费 `Observation`）、M2（上下文层消费 `pending_events`）、`ws.py`（消费 `pending_events` + `handle_confirm_ack`）。
- **红线**：
  - 节点只返回纯数据，不持 WS 连接；
  - `should_abort` 不入 GraphState；
  - 长任务不进对话回合；
  - `confirm_ack` 阶段 4 前返回 `VALIDATION`，禁止 mock 成功；
  - 不用 `create_react_agent`；不编排 LLM 子代理；
  - 不私自扩 ws event。

---

## 7. 已决裁决（开放问题已闭环）

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M4-Q1 | 阶段 2+ 路由判定"是否需要工具"方式 | **hybrid**：先规则启发式（关键词匹配），不确定时再轻量模型调用确认 |
| M4-Q2 | `RunnableConfig.configurable` 键名 | **命名空间**：`configurable["abort"]["should_abort"]`（预留 abort 命名空间扩展） |
| M4-Q3 | `pending_events` 消费时机与清空 | **每节点完成即消费**（流式友好，经 `updates` 模式按节点边界读）；**图外收包循环清空**（消费后置空，非图内节点清空）；GraphState 用 append reducer |
| M4-Q4 | Direct 节点 `/help` 内容来源 | **阶段 1 硬编码占位**，后续从 M1 `system.py` 读 |
| M4-Q5 | `handle_confirm_ack` 事务边界 | **同一 DB 事务**：patch 深合并 + 二次校验 + `task.create` + 清 `pending_confirm` + AuditLog 同事务 |
| M4-Q6 | Plan-Solve/ReAct 子图节点复用边界 | **阶段 4 设计时再定**（本版不锁定，遵守"图内复用节点、不独立 LLM 循环"裁决）。触发条件：阶段 4 启动 PR（`feat/agent-plan-solve`）前回写本项裁决 |

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.22 §4.3/§4.4 为唯一真理。M4 是前端交互事件的主要产出方：路由节点、子图节点、确认卡/澄清卡/Plan-Solve 节点产出的 `NodeEvent` 经 `ws.py` 翻译为 WS 事件，前端据此渲染。前端不臆造字段，发现契约缺失先回写 API.md 再实现。

### 8.1 路由与节点对应前端事件

| M4 节点/模块 | 产出 NodeEvent | 前端渲染 | 前端文件 | 落地阶段 |
| :--- | :--- | :--- | :--- | :--- |
| Direct 路径 L0 路由（§3.6） | `assistant_message`（`/help`）/ `error(VALIDATION)`（未知斜杠、`/compact`/`/cancel`/`/stress` 阶段 1） | AssistantBubble / ErrorStrip+Toast | `views/Agent.vue` `handleWsEvent`；`agent/slashRegistry.ts` | 阶段 1 |
| Chat 节点（§3.3） | `assistant_delta`/`assistant_message`/`response.completed`/`thought` | AssistantBubble + ThoughtCard | `views/Agent.vue`；`components/agent/ThoughtCard.vue` | 阶段 1 |
| `should_abort` 迁移（§3.4） | `/stop` 中止流式 | 流式中断 | `api/ws.ts`（`/stop` 走 user_message） | 阶段 1（回归） |
| `budget.py`（§3.9.5） | `error(BUDGET_EXCEEDED)` | ErrorStrip + Toast | `api/types.ts` `ERROR_MESSAGES`（文案中性化，预算为次数非美元） | 阶段 2 |
| `gates.py`（§3.9.5） | `error(VALIDATION)`/`error(CONCURRENCY)`（长工具门禁） | ErrorStrip + Toast | `api/types.ts` | 阶段 2 |
| `react.py`（§3.9.6） | `thought(stage=react)`/`tool_call`/`tool_result` | ThoughtCard + ToolCard | `components/agent/ThoughtCard.vue`/`ToolCard.vue` | 阶段 2 |
| `clarify.py`（§3.9.6） | `clarify`（`interrupt()` 暂停） | **ClarifyCard**（新增） | 新增 `components/agent/ClarifyCard.vue`；`api/ws.ts` `sendClarifyReply` | 阶段 3 |
| `plan.py`（§3.9.5）+ `plan_solve.py`（§3.9.6） | `plan`（PlanArtifact）+ `thought(stage=plan_solve)` | **PlanCard**（新增）+ stage 档 | 新增 `components/agent/PlanCard.vue`；`views/Agent.vue` `harnessStage` 补 `plan_solve` | 阶段 4 |
| `reflect.py`（§3.9.6） | `thought(stage=reflect)` | ThoughtCard「复核中」/「已复核」 | `components/agent/ThoughtCard.vue` | 阶段 4 |
| `confirm.py` `handle_confirm_ack`（§3.9.5） | `confirm`（下发）+ `confirm_ack`（回执） | ConfirmCard | `views/Agent.vue`；`components/agent/ConfirmCard.vue`；`api/ws.ts` `sendConfirmAck` | 阶段 4 |

### 8.2 前端验收要点

- **斜杠注册**：`slashRegistry.ts` 补 `/help`/`/cancel`/`/stress`（占位，命中由后端返回 `VALIDATION`），与 §3.6 Direct 路由规则对齐。
- **`harnessStage` 补档**：`views/Agent.vue` `harnessStage` 由 `'plan'|'react'|'reflect'|''` 补 `'plan_solve'`，`harnessStageLabel` 补「Plan-Solve 执行中」，对齐 §3.5 模式路由。
- **澄清卡 vs 确认卡 UI 区分**：澄清卡（`clarify`）只显示「回复」输入，不显示「确认入队」按钮，不写 `pending_confirm`；确认卡（`confirm`）显示确认/取消/patch。`clarify_reply.id` 必须匹配最近待回复澄清卡。
- **错误码文案中性化**：`BUDGET_EXCEEDED` fallback 改中性（预算为次数预算非美元），`CONCURRENCY` 确认卡场景文案为「确认卡已被他人处理」，场景文案由后端 `message` 透传。
- **`/stop` 回归**：`should_abort` 迁移到 `RunnableConfig` 后，`/stop` 仍能中止 `assistant_delta` 流，不取消已 queued 任务。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-编排层.md` | 新增 V0.1 → 修订 V0.2 → 修订 V0.3 → 修订 V0.4 → 修订 V0.4.1 → 修订 V0.4.2 → 修订 V0.4.3 | V0.1–V0.4.2 见既有设计演进。V0.4.3 回写运行事实：OR-4 为同轮串行多 ToolCall + 重复抑制；默认预算 12/12；`plan_solve → react ⇄ tools → reflect`，`response.completed` 由 reflect 在有计划回合发出。 |

本文档仅设计编排层，不改变任何 API、数据库、前端或 Agent 运行代码。
