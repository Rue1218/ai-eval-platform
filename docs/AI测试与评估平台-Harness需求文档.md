# AI 测试与评估平台 — Harness 需求文档

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 需求文档 |
| 版本 | V1.4 |
| 审查日期 | 2026-08-23 |
| 文档性质 | 需求规格说明书（需求先行） |
| 适用范围 | `/agent` 对话智能体的 Harness 运行时：六层职责、七种模式组合、LangGraph 框架选型、技能体系与验收标准 |
| 事实来源 | `backend/api/app/llm/`、`app/agent/graph.py`、`app/routers/ws.py`、`app/adapters.py`；《Agent框架LangGraph与WebSocket重设计》（V0.1）、《Agent重设计工作区》（V0.3）、《模型调用层LangGraph重设计》（V0.2）；PRD、API.md |

> **阅读关系**：本文是**需求层**，回答"Harness 应具备哪些能力、按什么标准验收"；实现结构以《Agent重设计工作区》与《模型调用层LangGraph重设计》为准，运行行为以《Agent框架LangGraph与WebSocket重设计》为准，产品状态机与字段以 PRD / API.md 为准。本文不新增任何对外 REST/WS 字段。

> **V1.4 修订定位**：远程 `main` 已完成 LangGraph 重构——旧 `app/agent/` 自研实现（react/harness/plan/reflect/mcp_registry 等）全部移除，替换为 `app/llm/`（ModelGateway 双图）+ `app/agent/graph.py`（单轮 Agent 图）+ `app/routers/ws.py`（WS 桥接）；`app/harness/`、`app/runtime/` 保持空包边界。本版把「现状」更新为**LangGraph 最小单轮链路**，需求目标（六层、七模式、澄清卡、检查点治理）保持 V1.3 裁决不变。

---

## 1. 文档定位与需求总目标

### 1.1 定位

本平台 Agent 不是"自由调用任意工具的通用自治 Agent"，而是面向**评测任务**的受控 Harness：模型负责结构化判断，Harness 负责控制、执行、持久化与授权。当前已落地的是**最小单轮链路**（WS → LangGraph Agent → ModelGateway → 三协议适配器），Harness 与平台能力处于冻结态。本需求文档把目标运行时拆成**六层职责**与**七种设计模式组合**，逐项给出需求条目、现状差距与验收标准。

### 1.2 需求总目标

```text
上下文高效（有效信息/总 token 最大化）
  + 专业能力强（评测领域工具与技能按需注入）
  + 可并行扩展（任务级编排 + Worker 异步执行）
  + 能自我纠错（规则优先的复核与失败反馈闭环）
```

任何一条需求不得违背 AGENTS.md 红线：禁止私自扩充产品范围；未启用能力用 `VALIDATION`(400)；长任务必须走 Worker；`rag` 未接入不得 mock `succeeded`；不实现 LLM 递归子代理与外部自定义 MCP。

---

## 2. 框架选型：LangGraph

### 2.1 选型裁决

LangGraph 定位为**六层全覆盖框架**（V1.3 裁决）：提示词装配、上下文窗口、记忆/检查点、编排状态机、工具执行、反馈归一均以 LangGraph 图节点与其生态实现。**已落地部分**：`app/llm/gateway.py`（`invoke_model` / `stream_model` 两个单节点图）+ `app/agent/graph.py`（`START → call_model/stream_model → END` 单轮 Agent 图）+ `app/routers/ws.py`（事件桥接）。

> **文档影响**：本裁决要求**同步改版《Agent重设计工作区》**——其中 `app/harness/` 空包边界将按本文六层需求逐层填充，但必须先更新本文与 PRD/API.md，再实现；《模型调用层LangGraph重设计》与《Agent框架LangGraph与WebSocket重设计》保持不变，作为模型层与 WS 层的稳定基线。

选型理由：

| 需求 | LangGraph 对应能力 | V1.4 现状/裁决 |
| :--- | :--- | :--- |
| 七种模式统一表达 | `StateGraph` 节点 + 条件边；ReAct / Plan-and-Execute / Reflection 均为该框架官方参考模式 | 采用自建 `StateGraph`，**排除 `create_react_agent` 预构建**（见 §2.4） |
| 确认卡 | `interrupt()` 可暂停图等待用户输入 | **确认卡不采用** `interrupt()`：走 WS 收包循环直连（§2.5） |
| 澄清卡 | `interrupt()` 暂停图 → 用户回复 → `Command(resume)` | **采用**（§2.5），当前冻结未实现 |
| 会话级状态恢复 | Checkpointer（`PostgresSaver` / `MemorySaver`）按 `thread_id` 保存快照 | 仅存**图内部执行状态**；对外事件与断线重放仍由 `ws_events` 承担（§2.5） |
| 并行与取消 | 节点级异步执行 | `/stop` 即时中断走 `asyncio` 任务取消（已落地 `StreamAborted` 受控传播）；`interrupt()` 仅用于澄清卡 |
| 长任务分离 | 图只编排短工具与入队动作；评测/压测仍经 PG 队列交 Worker | 不变（进程级，Worker 链路已存在但 Agent 未接入） |

### 2.2 LangGraph 原语 → 七种模式映射

| 模式 | LangGraph 落地 | 现状 |
| :--- | :--- | :--- |
| ReAct | 自建 `StateGraph`：`agent` 节点（LLM 调用 + 严格 JSON 解析）→ 条件边 → `ToolNode`；**禁止 `create_react_agent`** | 🚫 冻结：当前仅单轮，无工具循环 |
| Plan-and-Execute | `plan` 节点生成 `PlanArtifact` → 条件边选 `chat/react/plan_solve`；plan_solve 进入执行子图（图内复用节点，无独立 LLM 循环） | 🚫 冻结 |
| Orchestrator-Worker | **仅进程级**：确认回执由收包循环 `handle_confirm_ack` 直连创建 `queued` 任务 → PG 队列 → Worker → 事件回写。不引入 LLM 子代理 | 🟡 Worker 进程级链路已存在；Agent 确认回执未实现 |
| Mixture of Experts | skill 路由节点：按 `intent/skill_id` 选择 Skill Hint 注入上下文；评测域 Skills 体系待建 | 🚫 冻结 |
| Progressive Disclosure | 图状态只携带 Skill Hint 索引，完整技能文档由节点按需装配 | 🚫 冻结 |
| Reflexion | `reflect` 节点：确定性门禁（规则先行）→ 条件边 pass/clarify/reject；可选模型核对只降级不放行 | 🚫 冻结 |
| Tool-Augmented | `ToolNode` 包装工具注册表（参数绑定/白名单/超时/脱敏）；Worker 长工具不走 ToolNode | 🚫 冻结：无工具注册表 |

> **冲突裁决**："子图"一律指 **LangGraph 图内复用节点**（无独立 LLM 循环）；**禁止**用 LangGraph 子图编排 LLM 子代理（子代理/递归 Harness 属平台红线，明确不做）。

### 2.3 演进阶段（每阶段 WS 协议不变）

```text
阶段 0  ✅ 已落地：app/llm（gateway+contracts）+ agent/graph.py 单轮图
        + ws.py 事件桥接 + ws_events 断线重放 + StreamAborted 取消（langgraph==1.2.10）
阶段 1  🟡 近期：以 StateGraph 承载 Chat 与 Direct（斜杠）路径，行为对齐现状；
        定义图节点返回纯数据 → WS 层统一 emit 的事件桥接契约（§2.5）
阶段 2  🚫 以 StateGraph + ToolNode 承载 ReAct（短工具），引入工具注册表
阶段 3  🚫 接入 Checkpointer（PostgresSaver，thread_id=session_id；检查点表经 Alembic 建表，
        保留策略 TTL/会话删除联动）；确认卡保持收包循环直连（§2.5）
阶段 4  🚫 Plan-and-Solve 执行子图 + reflect 节点恢复评测业务 Workflow（M1 确认卡入队）
```

每个阶段独立开 `feat/` 分支、独立 PR；阶段内不得出现"双 Agent 循环"并存。任何新能力只能新增 LangGraph 节点/边，禁止保留第二条旧循环。

### 2.4 依赖与红线

- 依赖已锁定 `langgraph==1.2.10`（`backend/api/requirements.txt`）；**禁止**引入 langchain 全家桶、外部 MCP 或 LangGraph 云服务。
- **排除 `create_react_agent`**：其 tool-calling 消息格式让模型直接传参，会绕过参数绑定与白名单门禁。只允许自建 `StateGraph` 复刻"严格 JSON → 注册表校验 → 参数系统绑定 → 脱敏执行"链路。
- `ToolNode` 必须包装工具注册表：附件参数绑定、白名单/超时、脱敏保持为节点内逻辑，**不得**被框架默认行为绕过。
- `interrupt()` 仅用于**澄清卡场景**（§2.5）；**不得**用于确认卡等待、长任务忙等。评测长任务必须走 PG 队列交 Worker。
- 状态值必须为可序列化 JSON（PG 检查点兼容）；禁止把 DB Session、WebSocket 连接等不可序列化对象写入 GraphState。
- 共享会话并发：保留"单会话单活动回合"约束，Checkpointer 写入不得覆盖并发回合。
- **检查点表治理**：`PostgresSaver` 产生的检查点表**必须经 Alembic 迁移建表**（红线 4），不得依赖框架运行时自动建表；保留策略为 TTL + 会话软删除联动，过期清理由后台任务执行。

### 2.5 确认卡、澄清卡与事件桥接裁决

**确认卡（方案①，收包循环直连）**：

```text
confirm_ack 收包 → 行锁读 sessions.pending_confirm
  → owner 校验 → patch 深合并 → TaskCreate 二次校验
  → 创建 queued Task + AuditLog → 清空 pending_confirm
  → 发 confirm_ack / tool_call / tool_result 事件
```

- **单一事实源**：`sessions.pending_confirm` 是确认卡唯一状态源；检查点只存图内部执行状态。
- **确认卡等待不计回合墙钟**：确认回执不唤醒/恢复图执行，不占用回合预算。
- **`/stop` = 即时中断**：走 `asyncio` 任务取消（已由 `StreamAborted` 受控传播支撑），**不可恢复**；`interrupt()` 是可恢复暂停，**不替代**取消。

**澄清卡场景**：模型需要向用户追问澄清（非确认卡、非任务下单）时，图节点调用 `interrupt()` 暂停，等待用户回复后以 `Command(resume)` 恢复：

```text
澄清卡触发（缺槽位/意图不清/需用户选择）
  → interrupt() 暂停图（写检查点）→ 发澄清卡事件 → 不占回合预算
  → 用户回复 → Command(resume=回复) 恢复图 → 节点继续
```

与确认卡的区别：澄清卡**不创建任务、不写 pending_confirm**，恢复后仍可能走补规划/再次 ReAct。

**事件桥接契约**：图节点**只返回纯数据**（结构化结果），不直接持有 WS 连接或 emit 回调；事件由收包循环把图节点返回值统一转广播层发出：

```text
图节点执行 → 返回纯数据（结构化结果/事件意图）→ 图输出
  → 收包循环读取图输出 → 统一发事件（session_connections 广播）
  → 断线恢复仍走 ws_events 重放，不依赖检查点
```

阶段 0/1（无 Checkpointer）期间，图状态在进程内由会话注册表承载；图节点返回值即事件来源，避免节点内注入 WS 连接违反 GraphState 可序列化红线。

---

## 3. 总体分层与模式组合图

```text
┌─────────────────────────────────────────────────────┐
│ 7. Tool-Augmented    LangGraph ToolNode + Worker 长工具│
│ 6. Reflexion         reflect 节点：门禁 + 条件边       │
│ 5. Progressive Disclosure   Skill Hint 按需装配        │
│ 4. Mixture of Experts   skill 路由节点 + Skills 体系   │
│ 3. Orchestrator-Worker  Agent 图 ↔ PG 队列 ↔ Worker   │
│ 2. Plan-and-Execute    plan 节点 + 执行子图            │
│ 1. ReAct 推理循环       StateGraph agent + ToolNode    │
├─────────────────────────────────────────────────────┤
│ 已落地：LLM 层双图 + Agent 单轮图 + WS 事件桥接          │
└─────────────────────────────────────────────────────┘
```

---

## 4. 六层职责需求（LangGraph 落点）

### 4.1 提示词工程层

**职责**：固定系统策略与阶段输出协议；模型不持有控制逻辑。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| PR-1 | 固定系统策略定义角色、安全边界、确认卡、长短任务分离、密钥保护 | 系统提示词不允许用户配置覆盖 |
| PR-2 | 规划/ReAct/复核/压缩各阶段有独立输出协议（严格 JSON） | 各阶段模型输出必须为受约束 JSON；协议版本化 |
| PR-3 | 明确"thought 是动作摘要，不是授权依据" | 解析链路只消费 `tool/arguments/done`，不执行 thought 文本动作 |
| PR-4 | 用户输入不得拼接进系统规则；system/user 消息边界固定 | 注入测试：用户文本含"忽略系统提示"时策略不变 |

**现状**：`ModelRequest.system` 已支持注入系统提示词（`llm/contracts.py`）；多阶段输出协议、角色固化与安全边界**冻结未实现**，属需求目标。

### 4.2 上下文工程层

**职责**：决定模型本轮可见输入；相关性、来源、安全、容量与成本同时优化。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| CX-1 | 最近消息窗口为**唯一**窗口算法（默认末尾 20 条，`compact_keep_from` 截断） | 窗口算法行为与单测一致 |
| CX-2 | 思考/工具/确认/进度事件不进入消息窗口，只入 `ws_events` 供回放 | 工具事件数不影响窗口消息数 |
| CX-3 | 工具结果为**脱敏、截断、带来源的 observation 摘要**，不原样注入 | `api_key/token/password/secret/cookie` 键递归脱敏；超长截断带 `truncated=true` |
| CX-4 | 上下文装配顺序固定：Persona → Skill Hint → 摘要 → 阶段输入 | 装配顺序输出断言 |
| CX-5 | 工具定义按本轮能力最小注入，不默认全量注入 | 未注册工具不出现在注入清单 |
| CX-6 | `/compact` 为可控摘要：保留最近 6 条、摘要 ≤2000 字符、不删除原始记录 | 摘要写入会话记录；原始记录保留 |
| CX-7 | ContextMeter 只读 `GET /api/sessions/{id}/messages` 的 `context_meter` | 前端不自行计算窗口 |

**现状**：`ws_events` 持久化与 `last_event_id` 断线重放已落地（`session_connections.py`）；消息窗口、摘要、脱敏、ContextMeter 均**冻结未实现**。

### 4.3 记忆层

**职责**：按类型保存、检索、摘要与失效；记忆不进上下文，而是可检索的状态。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| MEM-1 | 工作记忆：本轮 Plan、observations、停止标志为回合内暂态 | 回合结束不持久化为系统事实 |
| MEM-2 | 情景记忆：sessions / messages / ws_events / tasks 持久化于 PostgreSQL | 断线重连按 `last_event_id` 重放 |
| MEM-3 | 压缩记忆：摘要可更新派生状态，不视为唯一真相 | 原始记录与摘要冲突时原始优先 |
| MEM-4 | 偏好记忆：仅确认成功入队后写允许字段 | 偏好只作规划建议，不可绕过 ID 溯源门禁 |
| MEM-5 | 语义/知识记忆：pgvector 与 LightRAG 属**演进项**，接入前显式带来源检索 | 未接入期间 `rag` 任务必须失败（`VALIDATION`），不得 mock |
| MEM-6 | 记忆检索带权限过滤与溯源（`source_id`/版本/ACL） | 越权记录不可检索 |

**现状**：MEM-2 的 `ws_events` 重放已落地；其余（窗口、摘要、偏好、语义记忆）均**冻结未实现**。**LangGraph 落点**：MEM-1 工作记忆即 GraphState 暂态字段；MEM-2/3 情景与压缩记忆仍由 PG `ws_events`/会话记录承担，Checkpointer（`thread_id=session_id`）只存图内部执行状态。

### 4.4 编排层

**职责**：选择控制流（Chat / ReAct / Plan-and-Solve / Direct），生成可验证中间状态，模型不直接执行副作用。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| OR-1 | 模式路由：斜杠 → Direct；无工具 → Chat；短工具 → ReAct；多槽位业务 → Plan-and-Solve | 路由断言 |
| OR-2 | `PlanArtifact` 冻结字段：intent/skill_id/slots/tools_needed/delivery/budget/notes | 规划 JSON schema 校验 |
| OR-3 | 规划解析失败重试一次，仍失败走 L0 规则降级，降级后必须经复核 | 异常路径单测覆盖 |
| OR-4 | 每轮**至多执行一个短工具**，重复调用抑制 | ReAct 循环断言 |
| OR-5 | 模型调用预算受控（规划+重试+补规划+可选核对 ≤4 次；工具轮次默认 4、上限 5） | 预算消费断言 |
| OR-6 | 长任务（benchmark/testcase/rag/stress）**不得**在对话回合内同步执行 | 门禁拦截 `is_long_tool` |
| OR-7 | 会话存在活动任务时禁止再发确认卡 | 门禁返回 `CONCURRENCY` |
| OR-8 | `task.create` 只在 `confirm_ack.ok=true` 且卡片 patch 合并后二次校验通过时发生 | WS 确认回执事务断言 |

**现状**：仅"单轮图"落地（`START → call_model/stream_model → END`，`agent/graph.py`）；模式路由、预算、门禁、确认回执均**冻结未实现**。**LangGraph 落点**：图拓扑即模式路由（条件边）；确认卡由收包循环 `handle_confirm_ack` 直连（§2.5）；预算/占槽/门禁为节点内确定性检查；`/stop` 走 `asyncio` 任务取消。

### 4.5 执行层

**职责**：在权限、参数绑定、超时、脱敏与白名单边界内真正产生副作用。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| EX-1 | 工具元数据、白名单与执行分派唯一来源为注册表 | 新增工具必须同时登记并走统一执行入口 |
| EX-2 | 附件参数系统绑定，模型不得伪造附件 ID | 参数绑定校验 |
| EX-3 | 每个工具声明 `permission` 与 `timeout_s`，执行带超时与脱敏日志 | 超时返回 `timeout` observation |
| EX-4 | 长任务经 PG 队列由 Worker 消费，进度/报告/错误写 `ws_events` | Worker 主循环 `FOR UPDATE SKIP LOCKED` + 并发闸门 |
| EX-5 | 未注册工具、未启用能力一律拒绝（`VALIDATION` 400），禁止假成功 | 未注册即拒绝 |
| EX-6 | Worker 执行器自管 DB Session，禁止跨 Session 传 ORM 对象 | 任务不出现永久卡 `running` |

**现状**：三协议适配器（`app/adapters.py`，`call_protocol`/`stream_protocol`）与 WS 短票鉴权/事件落库已落地；Worker 进程级链路已存在（PG 队列轮询）；工具注册表、`ToolNode`、参数绑定、确认回执均**冻结未实现**。

### 4.6 反馈层

**职责**：把工具结果/校验/外部任务事件变成下一步可信依据。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| FB-1 | 工具结果归一为 observation，异常不裸抛 | 工具异常不导致 Agent 崩溃 |
| FB-2 | 规则门禁先行（长工具/白名单/任意代码/一单一 kind/必填槽位/资产溯源/占槽/先评后压） | 门禁用例通过 |
| FB-3 | 模型辅助核对只能 `pass→clarify` 降级，**不得**把 `reject` 改为 `pass` | 降级单测 |
| FB-4 | 失败反馈受预算约束，禁止无限重试 | 预算断言 |
| FB-5 | Worker 的 progress/report/error 只进任务/事件链路，不污染消息窗口 | 窗口污染断言 |

**现状**：错误统一映射十类 `ErrorCode`（`app/errors.py`）、模型层异常归一与 `StreamAborted` 受控传播已落地（`llm/gateway.py`）；规则门禁、observation 归一、复核均**冻结未实现**。**LangGraph 落点**：工具结果归一为节点返回值（FB-1）；`reflect` 节点条件边承载 pass/clarify/reject（FB-2/3）；确认回执由收包循环直连（§2.5）。

---

## 5. 技能体系需求（MoE + Progressive Disclosure）

平台 Skills 体系按评测域组织。现有 skill 标识：`skill-benchmark`、`skill-rag`、`skill-testcase`、`skill-stress`。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| SK-1 | 每个 skill 对外只暴露**名称 + 一句话描述**（Skill Hint），完整工作流按需加载 | Skill Hint 常驻，正文不常驻 |
| SK-2 | skill 只在当前回合按需注入，不把历史技能卡逐一重复注入 | 相邻回合 skill 注入互不污染 |
| SK-3 | skill 映射评测域职责：benchmark（评测执行）、testcase（用例生成）、rag（知识库评测）、stress（压测） | skill_id ↔ 任务 kind 对齐 |
| SK-4 | 未实现 skill（如 rag）返回 `VALIDATION`，不得伪装成功 | 未实现路径断言 |
| SK-5 | 前端自定义斜杠只请求 `/api/slash-commands`，与后端技能注册一致 | 前后端 skill 清单一致 |

**现状**：全部**冻结未实现**（`app/harness/` 空包边界）。六专家分工（planner/generator/executor/healer/reporter/scenario）如需落地为独立 skill，须作为需求变更提交评审。

---

## 6. 需求优先级与里程碑映射

| 优先级 | 需求 | 里程碑 |
| :--- | :--- | :--- |
| P0 | 已落地：模型层双图、Agent 单轮图、WS 事件桥接、错误契约、依赖锁定 | 已完成（LangGraph 最小单轮链路） |
| P0-LG | §2.3 阶段 1–2：Chat/Direct 路径迁入 StateGraph、事件桥接契约（§2.5）、ReAct+ToolNode 与工具注册表 | 近期：框架演进（不改对外契约；确认卡保持收包循环直连） |
| P1 | §2.3 阶段 3–4：Checkpointer（PostgresSaver + Alembic 建表 + TTL/会话删除联动）、澄清卡 `interrupt()`、Plan-and-Solve 执行子图、确认卡入队、OR-2/`allows_replan`、FB-3/模型核对、SK-3 完整评测工作流 | M1：Agent 确认卡驱动真实任务入队 |
| P2 | MEM-5 语义记忆（pgvector + Redis）、SK-5 技能工作流文档化 | M2/M3：评测业务恢复、LightRAG 接入评审 |

P0-LG 阶段引入新依赖时须同步更新 `backend/api/requirements.txt`；P1/P2 需求启动前须回写对应文档（API.md / Agent 开发文档），遵守文档闭环规范。

---

## 7. 冲突边界与红线

| 需求 | 裁决 |
| :--- | :--- |
| Orchestrator-Worker 子代理并行 | **禁止** LLM 递归子代理与 LangGraph 子图编排子代理（子图仅指图内复用节点）；平台仅做进程级 Agent ↔ Worker 编排 |
| 确认卡实现路径 | **收包循环直连**，不迁移 `interrupt()`；`sessions.pending_confirm` 为唯一状态源 |
| 澄清卡实现路径 | `interrupt()` + `Command(resume)`，仅限澄清（不建任务、不写 pending_confirm）；不占回合预算 |
| `/stop` 与 `interrupt` | `/stop` 即时中断走 `asyncio` 取消（`StreamAborted`，不可恢复）；`interrupt()` 仅用于澄清卡，二者语义分离 |
| 预构建 Agent | **排除 `create_react_agent`**；只允许自建 `StateGraph` |
| 检查点边界 | `PostgresSaver` 只存图内部执行状态；对外事件与断线重放仍由 `ws_events` + `last_event_id` 承担 |
| 检查点表治理 | 检查点表**经 Alembic 迁移建表**（红线 4），保留策略 TTL + 会话删除联动，后台任务清理 |
| 事件桥接 | 图节点只返回纯数据；事件由收包循环统一发出，节点内禁止持有 WS 连接/emit 回调 |
| LangGraph 依赖范围 | 仅 `langgraph==1.2.10`；禁止 langchain 全家桶、LangGraph 云服务、外部 MCP |
| 外部 MCP / 用户自定义系统提示词 | 明确不做，防越权与提示词污染 |
| RAG 语义记忆 | 未接入前 `kind=rag` 必须失败；pgvector/LightRAG 为演进项 |
| GraphState 可序列化 | 状态只放 JSON 可序列化值；DB Session / WS 连接不得入 State |
| 新 REST/WS 字段 | 必须先改 API.md，禁止私自扩充 |
| 错误码 | 对外只暴露 10 大 `ErrorCode`；observation 级内部枚举不对外 |

---

## 8. 验收与测试策略

- 已落地基线测试：`backend/api/tests/test_llm_graph.py`（图调用/异步/流式/取消/错误脱敏）、`test_agent_graph.py`（Agent 图事件顺序）。
- **LangGraph 专项**：用 `graph.invoke` / `graph.astream` 断言图拓扑与状态转移；用 Memory 版 Checkpointer 验证 `thread_id` 状态恢复；检查点表建表/清理用 Alembic 迁移测试 + TTL 用例验证。
- **行为对齐**：新增能力只增节点/边，禁止第二条 Agent 循环；对外事件与错误码回归保持绿色。
- **事件桥接验收**：图节点返回纯数据，收包循环统一发出（§2.5）——断言节点内不持有 WS 连接、事件均经统一广播发出。
- **确认卡回归**：确认回执仍走收包循环直连；`confirm_ack` 路径保持绿色。
- **澄清卡专项**：`interrupt()` 触发澄清卡 → 暂停写检查点 → 用户回复 → `Command(resume)` 恢复，断言不建任务、不占回合预算。
- 新增能力必须配套：模式路由单测、门禁用例、WS 事件回放用例、预算/超时/脱敏用例。
- 本地自检：`cd backend/api && ruff check . ../shared && pytest`；`cd backend/worker && PYTHONPATH=.:.. pytest`。

---

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness需求文档.md` | 新增（V1.0）→ 修订至 V1.3 → **修订 V1.4** | V1.0–V1.3 确立六层/七模式/LangGraph 选型与评审裁决；V1.4 同步远程 `main` 重构：现状改为「LLM 层双图 + Agent 单轮图 + WS 桥接」，`app/harness/` 空包待按本文逐层填充，依赖锁定 `langgraph==1.2.10`，测试基线更新为 `test_llm_graph.py` / `test_agent_graph.py`。 |

本次仅修订需求文档，不改变任何 API、数据库、前端或 Agent 运行代码。
