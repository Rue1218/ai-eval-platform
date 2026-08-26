# AI 测试与评估平台 — Harness 需求文档

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 需求文档 |
| 版本 | V1.5.2 |
| 审查日期 | 2026-08-26 |
| 文档性质 | 需求规格说明书（需求先行） |
| 适用范围 | `/agent` 对话智能体的 Harness 运行时：六层职责、七种模式组合、LangGraph 框架选型、技能体系与验收标准 |
| 事实来源 | `backend/api/app/llm/`、`app/agent/graph.py`、`app/routers/ws.py`、`app/adapters.py`；《Agent框架LangGraph与WebSocket重设计》（V0.1）、《Agent重设计工作区》（V0.3）、《模型调用层LangGraph重设计》（V0.2）；PRD、API.md |

> **阅读关系**：本文是**需求层**，回答"Harness 应具备哪些能力、按什么标准验收"；实现结构以《Agent重设计工作区》与《模型调用层LangGraph重设计》为准，运行行为以《Agent框架LangGraph与WebSocket重设计》为准，产品状态机与字段以 PRD / API.md 为准。本文不新增任何对外 REST/WS 字段。

> **V1.4 修订定位**：远程 `main` 已完成 LangGraph 重构——旧 `app/agent/` 自研实现（react/harness/plan/reflect/mcp_registry 等）全部移除，替换为 `app/llm/`（ModelGateway 双图）+ `app/agent/graph.py`（单轮 Agent 图）+ `app/routers/ws.py`（WS 桥接）；`app/harness/`、`app/runtime/` 保持空包边界。本版把「现状」更新为**LangGraph 最小单轮链路**，需求目标（六层、七模式、澄清卡、检查点治理）保持 V1.3 裁决不变。

> **V1.4.1 修订定位**：评审补丁版，不改需求范围——① 补充阶段 3 接入 Checkpointer 前的 GraphState 可序列化迁移路径（`should_abort` 等回调不得入 State）；② OR-2 冻结字段补登 `allows_replan`，消除 §6 悬空引用；③ 显式声明阶段 3 允许新增 `langgraph-checkpoint-postgres` 依赖；④ 标注 `handle_confirm_ack` 为规划中函数（阶段 4 落地）。

> **V1.4.2 修订定位**：架构落地补丁版，不改需求范围——新增 §9「架构文件树与待生成代码清单」，把六层职责（§4）与演进阶段（§2.3）映射到 `app/harness/`、`app/agent/`、`app/runtime/` 的具体包/文件骨架，明确每阶段需生成的代码文件、所属层与对应需求编号，作为阶段 1–4 逐层填充的施工蓝图。本版不新增任何对外 REST/WS 字段，不改变已落地基线。

> **V1.4.3 修订定位**：模块设计回写版，不改需求范围——① §7 新增「内部短 MCP 允许 + 基础工具集为通用能力」裁决行（对齐 M5-D4，澄清 `web_search`/`web_fetch` 等基础工具由平台内置适配器实现，非外部 MCP 服务器，不触碰「禁止外部 MCP」红线）；② §9.1/§9.2/§9.3 把 `state.py` 从 `app/harness/orchestration/` 移到 `app/harness/memory/`（对齐 M3-D1，GraphState 归记忆层所有）。本版不新增任何对外 REST/WS 字段，不改变已落地基线。

> **V1.4.4 修订定位**：契约分期修正版，不改需求范围——§9.1/§9.2/§9.3 把 `contracts/artifacts.py` 由「阶段 4 整体落地」修正为**两波分期**：阶段 2 早波（`ToolCall`/`ToolResult`/`Observation`，供 M5/M6/M2 阶段 2 消费）+ 阶段 4 晚波（`PlanArtifact`/`SkillHint`，供 M4/M10 阶段 4 消费）。消除原分期下 M5/M6 阶段 2 引用尚未生成的 artifact 契约导致的 ImportError 阶段倒挂。本版不新增任何对外 REST/WS 字段，不改变已落地基线。

> **V1.4.5 修订定位**：评审收敛版（2026-08-24）——① 全部模块文档（M1–M10）上游权威与前端联调契约统一为 API.md V1.22；② §2.5 收敛**事件生产者归属**（图节点 / `ws.py` 收包循环直产 / Worker 直产三类 producer，归属矩阵唯一源见 M7 §3.6.1）；③ `should_abort` 全链路迁移（O-12）与 Worker 事件实时转发（M9-D8）列为**阶段 3 阻断验收项**（§8）；④ §7 标注 `bash` 命令黑名单**非安全沙箱**，阶段 2 不开放通用 bash；⑤ `pending_events` 检查点恢复语义闭环（M9-D3：恢复时重置为空，事件走 `ws_events`）。本次不新增任何对外 REST/WS 字段，不改变已落地基线。

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
| Progressive Disclosure | 图状态只携带 Skill Hint 索引，完整技能文档由节点按需装配 | 🟢 已落地：`skills/workflows.py` 按 `plan.skill_id` 装配 |
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
        保留策略 TTL/会话删除联动）；确认卡保持收包循环直连（§2.5）；
        前置阻断项：`should_abort` 迁移 + GraphState 可序列化 + Worker 事件实时转发（§8）
阶段 4  🚫 Plan-and-Solve 执行子图 + reflect 节点恢复评测业务 Workflow（M1 确认卡入队）
```

每个阶段独立开 `feat/` 分支、独立 PR；阶段内不得出现"双 Agent 循环"并存。任何新能力只能新增 LangGraph 节点/边，禁止保留第二条旧循环。

### 2.4 依赖与红线

- 依赖已锁定 `langgraph==1.2.10`（`backend/api/requirements.txt`）；**禁止**引入 langchain 全家桶、外部 MCP 或 LangGraph 云服务。阶段 3 接入 `PostgresSaver` 时**允许**新增 `langgraph-checkpoint-postgres`（`PostgresSaver` 所在独立包，非 langchain 全家桶），引入时同步更新 `requirements.txt` 并在 PR 说明。
- **排除 `create_react_agent`**：其 tool-calling 消息格式让模型直接传参，会绕过参数绑定与白名单门禁。只允许自建 `StateGraph` 复刻"严格 JSON → 注册表校验 → 参数系统绑定 → 脱敏执行"链路。
- `ToolNode` 必须包装工具注册表：附件参数绑定、白名单/超时、脱敏保持为节点内逻辑，**不得**被框架默认行为绕过。
- `interrupt()` 仅用于**澄清卡场景**（§2.5）；**不得**用于确认卡等待、长任务忙等。评测长任务必须走 PG 队列交 Worker。
- 状态值必须为可序列化 JSON（PG 检查点兼容）；禁止把 DB Session、WebSocket 连接等不可序列化对象写入 GraphState。**阶段 3 前置迁移路径**：当前 `_AgentState` 携带的 `ModelRequest`（含 `should_abort` 回调）与 `ModelResponse` 为 dataclass，不可序列化；接入 Checkpointer 前须先把 `should_abort` 等回调移出 State（改由节点闭包或 `RunnableConfig` 注入），State 内只保留 JSON 可序列化的请求/响应字段。
- 共享会话并发：保留"单会话单活动回合"约束，Checkpointer 写入不得覆盖并发回合。
- **检查点表治理**：`PostgresSaver` 产生的检查点表**必须经 Alembic 迁移建表**（红线 4），不得依赖框架运行时自动建表；保留策略为 TTL + 会话软删除联动，过期清理由后台任务执行。

### 2.5 确认卡、澄清卡与事件桥接裁决

**确认卡（方案①，收包循环直连）**：

> 下文 `handle_confirm_ack` 为**规划中函数名**（阶段 4 落地）；当前 `confirm_ack` 由收包循环直接拒绝并返回 `VALIDATION`（"尚未启用任务控制"），与 §4.4 现状一致。

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

> **事件生产者归属（V1.4.5 收敛）**：`pending_events` 只承载**图节点**产出的事件意图；`user_message`（用户上行）与 `confirm_ack`（回执）由 `ws.py` 收包循环直产，`progress`/`report`/`error` 由 Worker `push_ws` 直产并实时转发（阶段 3 阻断项，M9-D8）——三者不得由图节点重复产出。归属矩阵唯一源见 M7 §3.6.1。

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
| OR-2 | `PlanArtifact` 冻结字段：intent/skill_id/slots/tools_needed/delivery/budget/allows_replan/notes | 规划 JSON schema 校验 |
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

**现状**：Skill Hint 目录、`skill_id ↔ kind` 与 `skill-rag` 启用门禁已落地。SK-1 Progressive Disclosure（完整工作流按 `plan.skill_id` 按需加载、不进 GraphState）已接线；六专家分工如需落地为独立 skill，须作为需求变更提交评审。

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
| 内部短 MCP + 基础工具集 | **允许**：`web_search`/`web_fetch` 等基础工具集为**通用能力**，由平台内置适配器实现（**内部短 MCP**，非外部 MCP 服务器）；`app/harness/execution/mcp/` 保留包边界但**不做外部 MCP 接入**。不触碰「禁止外部 MCP」红线 |
| 通用 `bash` 工具（V1.5.0 bwrap 闭环） | **阶段 3 开放通用 bash**：一次性 **bwrap 进程级沙箱**（`--unshare-net` 无网络、会话工作区唯一可写、ulimit 内存/进程数/CPU 限制、`--die-with-parent` + 墙钟超时整树清理）；命令黑名单（rm/sudo/curl 等）为**纵深防御**；bwrap 不可用或引擎关闭时 **fail-closed（VALIDATION）**，禁止降级为裸 subprocess。`read`/`write`/`edit` 仍基于受控文件 ID/根目录 |
| RAG 语义记忆 | 未接入前 `kind=rag` 必须失败；pgvector/LightRAG 为演进项 |
| GraphState 可序列化 | 状态只放 JSON 可序列化值；DB Session / WS 连接不得入 State |
| 新 REST/WS 字段 | 必须先改 API.md，禁止私自扩充 |
| 错误码 | 对外只暴露 10 大 `ErrorCode`；observation 级内部枚举不对外 |

---

## 8. 验收与测试策略

- 已落地基线测试：`backend/api/tests/test_llm_graph.py`（图调用/异步/流式/取消/错误脱敏）、`test_agent_graph.py`（Agent 图事件顺序）。
- **LangGraph 专项**：用 `graph.invoke` / `graph.astream` 断言图拓扑与状态转移；用 Memory 版 Checkpointer（`MemorySaver`，来自 `langgraph.checkpoint.memory`，主包内置、无新依赖）验证 `thread_id` 状态恢复；检查点表建表/清理用 Alembic 迁移测试 + TTL 用例验证。
- **行为对齐**：新增能力只增节点/边，禁止第二条 Agent 循环；对外事件与错误码回归保持绿色。
- **事件桥接验收**：图节点返回纯数据，收包循环统一发出（§2.5）——断言节点内不持有 WS 连接、事件均经统一广播发出。
- **确认卡回归**：确认回执仍走收包循环直连；`confirm_ack` 路径保持绿色。
- **澄清卡专项**：`interrupt()` 触发澄清卡 → 暂停写检查点 → 用户回复 → `Command(resume)` 恢复，断言不建任务、不占回合预算。
- 新增能力必须配套：模式路由单测、门禁用例、WS 事件回放用例、预算/超时/脱敏用例。
- **阶段 3 阻断验收（V1.4.5 评审收敛）**：接入 `PostgresSaver` 前必须完成——① `should_abort` 全链路迁移至 `RunnableConfig.configurable`（O-12，含反射断言）；② GraphState 全字段 `json.dumps` 通过；③ Worker 事件实时转发落地（M9-D8，在线连接实时收 `progress`/`report`/`error` 且断线补发不重复）。未满足不得进入阶段 3 联调。
- 本地自检：`cd backend/api && ruff check . ../shared && pytest`；`cd backend/worker && PYTHONPATH=.:.. pytest`。

---

## 9. 架构文件树与待生成代码清单

本节是 §4 六层职责与 §2.3 演进阶段的**施工蓝图**：把需求条目落到 `app/harness/`、`app/agent/`、`app/runtime/` 的具体包/文件骨架上，明确每阶段需生成的代码文件、所属层与对应需求编号。**红线**：本节只规定文件骨架与职责边界，不规定具体实现；任何文件落地必须先满足 §7 红线（不私自扩字段、不跳 Alembic、不 mock `rag` 成功、GraphState 可序列化等）。

### 9.1 总体文件树（已落地 + 待生成）

> **图例**：✅ 已落地 ｜ 🟡 部分落地 ｜ 🚫 冻结/待生成（按阶段填充）。

**模型层稳定基线（阶段 0 已落地，不再膨胀）**：

- `app/llm/__init__.py` — re-export ModelConfig/Request/Response/StreamEvent/Gateway
- `app/llm/contracts.py` ✅ — 模型层契约（frozen dataclass）
- `app/llm/gateway.py` ✅ — ModelGateway 双图（invoke + stream）

**Agent 图（阶段 0 单轮已落地；阶段 1–4 扩展图拓扑）**：

- `app/agent/__init__.py` — re-export LangGraphAgent（+ 后续路由/子图入口）
- `app/agent/graph.py` ✅ — 单轮 Agent 图（call_model / stream_model）
- `app/agent/routing.py` 🚫 阶段 1 — 模式路由节点（斜杠→Direct / 无工具→Chat）
- `app/agent/react.py` 🚫 阶段 2 — ReAct 子图（agent 节点 + ToolNode 条件边）
- `app/agent/clarify.py` 🚫 阶段 3 — 澄清卡 interrupt() / Command(resume) 节点
- `app/agent/plan_solve.py` 🚫 阶段 4 — Plan-and-Solve 执行子图（图内复用节点）
- `app/agent/reflect.py` 🚫 阶段 4 — reflect 节点（pass/clarify/reject 条件边）

**Harness 六层包（空包边界，按层填充）**：

- `app/harness/contracts/` — 层间契约（跨层共用 dataclass / TypedDict）
  - `__init__.py`
  - `artifacts.py` 🚫 阶段 2（早：ToolCall/ToolResult/Observation）→ 阶段 4（晚：PlanArtifact/SkillHint）— 跨层 artifact 契约
  - `events.py` 🚫 阶段 1 — 图节点返回的纯数据结构（事件意图 + payload）
- `app/harness/prompts/` — 层 1 提示词工程（§4.1）
  - `__init__.py`
  - `system.py` 🚫 阶段 1 — 固定系统策略（角色/安全/确认/长短任务/密钥）PR-1
  - `protocols.py` 🚫 阶段 1 — 各阶段输出协议（严格 JSON）PR-2/PR-3
  - `safety.py` 🚫 阶段 4 — 注入测试与 system/user 边界 PR-4
- `app/harness/context/` — 层 2 上下文工程（§4.2）
  - `__init__.py`
  - `window.py` 🚫 阶段 1 — 最近消息窗口算法（末尾 20 + compact_keep_from）CX-1/2
  - `observation.py` 🚫 阶段 2 — 脱敏/截断/带来源 observation 摘要 CX-3
  - `assembly.py` 🚫 阶段 1 — 装配顺序 + 按需工具定义注入 CX-4/5
  - `compact.py` 🚫 阶段 3 — /compact 可控摘要 CX-6
  - `meter.py` 🚫 阶段 3 — ContextMeter 投影 CX-7
- `app/harness/memory/` — 层 3 记忆（§4.3）
  - `__init__.py`
  - `working.py` 🚫 阶段 1 — 工作记忆（GraphState 暂态）MEM-1
  - `episodic.py` 🟡 阶段 1 — 情景记忆（ws_events 重放已落地；会话/任务表扩展）MEM-2
  - `compressed.py` 🚫 阶段 3 — 压缩记忆（摘要派生状态）MEM-3
  - `preference.py` 🚫 阶段 3 — 偏好记忆（确认成功后写入）MEM-4
  - `semantic.py` 🚫 M2/M3 — 语义/知识记忆（pgvector + LightRAG，演进项）MEM-5
  - `acl.py` 🚫 M2/M3 — 权限过滤与溯源（source_id/版本/ACL）MEM-6
  - `state.py` 🚫 阶段 1 — GraphState 定义（JSON 可序列化；回调不入 State；归记忆层所有，M3-D1）
- `app/harness/orchestration/` — 层 4 编排（§4.4）
  - `__init__.py`
  - `router.py` 🚫 阶段 1 — 模式路由（条件边）OR-1
  - `plan.py` 🚫 阶段 4 — PlanArtifact + 规划解析 + 重试降级 OR-2/3
  - `budget.py` 🚫 阶段 2 — 模型调用预算 + 工具轮次预算 OR-5
  - `gates.py` 🚫 阶段 2 — 长工具/占槽/会话活动门禁 OR-6/7
  - `confirm.py` 🚫 阶段 4 — 确认卡回执（handle_confirm_ack）OR-8
- `app/harness/execution/` — 层 5 执行（§4.5）
  - `__init__.py`
  - `registry.py` 🚫 阶段 2 — 工具注册表（元数据/白名单/分派唯一源）EX-1/5
  - `binding.py` 🚫 阶段 2 — 附件参数系统绑定 EX-2
  - `toolnode.py` 🚫 阶段 2 — ToolNode 包装（LangGraph 节点，包装注册表）EX-1
  - `dispatch.py` 🚫 阶段 2 — 短工具分派 + 超时 + 脱敏日志 EX-3
  - `worker_bridge.py` 🚫 阶段 4 — 长任务入队（PG 队列 → Worker）EX-4
  - `session_guard.py` 🚫 阶段 4 — Worker 自管 Session 守卫 EX-6
  - `adapters/` — 占位：执行适配器边界（保留边界，按需填充）
  - `mcp/` — 占位：MCP 边界（明确不做外部 MCP，保留包边界）
- `app/harness/feedback/` — 层 6 反馈（§4.6）
  - `__init__.py`
  - `observation.py` 🚫 阶段 2 — 工具结果归一为 observation FB-1
  - `rules.py` 🚫 阶段 2 — 规则门禁先行 FB-2
  - `review.py` 🚫 阶段 4 — 模型辅助核对（pass→clarify 降级）FB-3
  - `budget.py` 🚫 阶段 4 — 失败反馈预算约束 FB-4
  - `isolation.py` 🚫 阶段 4 — Worker 事件不污染消息窗口 FB-5
- `app/harness/security/` — 跨层安全（确认卡 owner / 脱敏）
  - `__init__.py`
  - `auth.py` 🚫 阶段 4 — 确认卡 owner 校验 + 行锁
  - `secrets.py` 🚫 阶段 2 — 递归脱敏（api_key/token/password/secret/cookie）

**运行时基础设施（阶段 3 起填充）**：

- `app/runtime/__init__.py`
- `app/runtime/checkpoint.py` 🚫 阶段 3 — PostgresSaver + thread_id=session_id
- `app/runtime/cleanup.py` 🚫 阶段 3 — 检查点 TTL + 会话删除联动后台任务

**WS 桥接层（阶段 0 已落地，阶段 1/4 接入图输出与确认回执）**：

- `app/routers/ws.py` ✅ — WS 事件桥接（收包循环 + `_emit` 广播 + `ws_events` 重放）；阶段 1 接图输出统一 emit，阶段 4 接 `handle_confirm_ack`

### 9.2 六层 → 包映射

| 层 | 需求章节 | 主包 | 关键文件 | 阶段 |
| :--- | :--- | :--- | :--- | :--- |
| 层 1 提示词工程 | §4.1 | `app/harness/prompts/` | `system.py` / `protocols.py` / `safety.py` | 阶段 1（system/protocols）→ 阶段 4（safety） |
| 层 2 上下文工程 | §4.2 | `app/harness/context/` | `window.py` / `observation.py` / `assembly.py` / `compact.py` / `meter.py` | 阶段 1（window/assembly）→ 阶段 2（observation）→ 阶段 3（compact/meter） |
| 层 3 记忆 | §4.3 | `app/harness/memory/` | `state.py` / `working.py` / `episodic.py` / `compressed.py` / `preference.py` / `semantic.py` / `acl.py` | 阶段 1（state/working）→ 阶段 3（compressed/preference）→ M2/M3（semantic/acl） |
| 层 4 编排 | §4.4 | `app/harness/orchestration/` + `app/agent/` | `router.py` / `plan.py` / `budget.py` / `gates.py` / `confirm.py` + `agent/routing.py` / `plan_solve.py` / `reflect.py` | 阶段 1（router/routing）→ 阶段 2（budget/gates）→ 阶段 4（plan/confirm/plan_solve/reflect） |
| 层 5 执行 | §4.5 | `app/harness/execution/` + `app/agent/react.py` | `registry.py` / `binding.py` / `toolnode.py` / `dispatch.py` / `worker_bridge.py` / `session_guard.py` | 阶段 2（registry/binding/toolnode/dispatch + react）→ 阶段 4（worker_bridge/session_guard） |
| 层 6 反馈 | §4.6 | `app/harness/feedback/` + `app/agent/reflect.py` | `observation.py` / `rules.py` / `review.py` / `budget.py` / `isolation.py` | 阶段 2（observation/rules）→ 阶段 4（review/budget/isolation） |
| 跨层契约 | §4 各层 | `app/harness/contracts/` | `artifacts.py` / `events.py` | 阶段 1（events）→ 阶段 2（artifacts 早：ToolCall/ToolResult/Observation）→ 阶段 4（artifacts 晚：PlanArtifact/SkillHint） |
| 跨层安全 | §4.4/4.5/4.6 | `app/harness/security/` | `auth.py` / `secrets.py` | 阶段 2（secrets）→ 阶段 4（auth） |
| 运行时基础设施 | §2.3 阶段 3 | `app/runtime/` | `checkpoint.py` / `cleanup.py` | 阶段 3 |

### 9.3 演进阶段 → 文件生成清单

每阶段独立开 `feat/` 分支、独立 PR；阶段内不得出现"双 Agent 循环"并存。

**阶段 1（P0-LG 近期）：StateGraph 承载 Chat/Direct + 事件桥接契约**

| 文件 | 操作 | 所属层 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/contracts/events.py` | 新增 | 契约 | §2.5 事件桥接契约 |
| `app/harness/memory/state.py` | 新增 | 层 3 | GraphState 可序列化（§2.4 红线；归记忆层，M3-D1） |
| `app/harness/orchestration/router.py` | 新增 | 层 4 | OR-1 |
| `app/harness/prompts/system.py` | 新增 | 层 1 | PR-1 |
| `app/harness/prompts/protocols.py` | 新增 | 层 1 | PR-2/PR-3 |
| `app/harness/context/window.py` | 新增 | 层 2 | CX-1/CX-2 |
| `app/harness/context/assembly.py` | 新增 | 层 2 | CX-4/CX-5 |
| `app/harness/memory/working.py` | 新增 | 层 3 | MEM-1 |
| `app/harness/memory/episodic.py` | 修改 | 层 3 | MEM-2（会话/任务表扩展） |
| `app/agent/routing.py` | 新增 | 层 4 | OR-1（路由节点 + 条件边） |
| `app/agent/graph.py` | 修改 | 层 4 | 接入路由节点，保留单轮 Chat 路径 |
| `app/routers/ws.py` | 修改 | 桥接 | 图输出 → 收包循环统一 `_emit` |
| `backend/api/tests/test_agent_graph.py` | 修改 | 测试 | 路由断言 + 事件桥接断言 |

**阶段 2（P0-LG）：ReAct + ToolNode + 工具注册表**

| 文件 | 操作 | 所属层 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/contracts/artifacts.py` | 新增（早） | 契约 | EX-1/EX-2 ToolCall/ToolResult、FB-1 Observation（阶段 2 早波，供 M5/M6/M2 消费） |
| `app/harness/execution/registry.py` | 新增 | 层 5 | EX-1/EX-5 |
| `app/harness/execution/binding.py` | 新增 | 层 5 | EX-2 |
| `app/harness/execution/toolnode.py` | 新增 | 层 5 | EX-1（ToolNode 包装） |
| `app/harness/execution/dispatch.py` | 新增 | 层 5 | EX-3 |
| `app/harness/feedback/observation.py` | 新增 | 层 6 | FB-1 |
| `app/harness/feedback/rules.py` | 新增 | 层 6 | FB-2 |
| `app/harness/security/secrets.py` | 新增 | 安全 | CX-3 脱敏递归 |
| `app/harness/context/observation.py` | 新增 | 层 2 | CX-3 |
| `app/harness/orchestration/budget.py` | 新增 | 层 4 | OR-4/OR-5 |
| `app/harness/orchestration/gates.py` | 新增 | 层 4 | OR-6 |
| `app/agent/react.py` | 新增 | 层 4 | ReAct 子图 |
| `app/agent/graph.py` | 修改 | 层 4 | 接入 ReAct 条件边 |

**阶段 3（P1）：Checkpointer + 澄清卡**

| 文件 | 操作 | 所属层 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/runtime/checkpoint.py` | 新增 | 运行时 | §2.3 阶段 3（PostgresSaver） |
| `app/runtime/cleanup.py` | 新增 | 运行时 | §2.4 检查点 TTL + 会话删除联动 |
| `app/agent/clarify.py` | 新增 | 层 4 | §2.5 澄清卡 interrupt() |
| `app/harness/memory/compressed.py` | 新增 | 层 3 | MEM-3 |
| `app/harness/memory/preference.py` | 新增 | 层 3 | MEM-4 |
| `app/harness/context/compact.py` | 新增 | 层 2 | CX-6 |
| `app/harness/context/meter.py` | 新增 | 层 2 | CX-7 |
| `backend/api/migrations/versions/xxxx_add_checkpointer_tables.py` | 新增 | 迁移 | §2.4 检查点表经 Alembic 建表 |
| `backend/api/requirements.txt` | 修改 | 依赖 | 新增 `langgraph-checkpoint-postgres` |

**阶段 4（P1 / M1）：Plan-and-Solve + 确认卡入队 + reflect**

| 文件 | 操作 | 所属层 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/contracts/artifacts.py` | 修改（补晚波） | 契约 | OR-2 PlanArtifact、SK-1 SkillHint（阶段 4 晚波） |
| `app/harness/orchestration/plan.py` | 新增 | 层 4 | OR-2/OR-3 |
| `app/harness/orchestration/confirm.py` | 新增 | 层 4 | OR-8（handle_confirm_ack） |
| `app/harness/execution/worker_bridge.py` | 新增 | 层 5 | EX-4 |
| `app/harness/execution/session_guard.py` | 新增 | 层 5 | EX-6 |
| `app/harness/feedback/review.py` | 新增 | 层 6 | FB-3 |
| `app/harness/feedback/budget.py` | 新增 | 层 6 | FB-4 |
| `app/harness/feedback/isolation.py` | 新增 | 层 6 | FB-5 |
| `app/harness/security/auth.py` | 新增 | 安全 | OR-8 owner 校验 + 行锁 |
| `app/harness/prompts/safety.py` | 新增 | 层 1 | PR-4 注入测试 |
| `app/agent/plan_solve.py` | 新增 | 层 4 | Plan-and-Solve 执行子图 |
| `app/agent/reflect.py` | 新增 | 层 4 | reflect 节点 |
| `app/agent/graph.py` | 修改 | 层 4 | 接入 plan_solve / reflect 条件边 |
| `app/routers/ws.py` | 修改 | 桥接 | 接入 `handle_confirm_ack` 收包循环直连 |

> **M2/M3 演进项**（不在本蓝图阶段内）：`app/harness/memory/semantic.py`、`app/harness/memory/acl.py`（pgvector + LightRAG 接入评审后启动）。

---

## 10. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness需求文档.md` | 新增（V1.0）→ 修订至 V1.3 → 修订 V1.4 → 修订 V1.4.1 → 修订 V1.4.2 → 修订 V1.4.3 → 修订 V1.4.4 → 修订 V1.4.5 → **修订 V1.4.6** | V1.0–V1.3 确立六层/七模式/LangGraph 选型与评审裁决；V1.4 同步远程 `main` 重构：现状改为「LLM 层双图 + Agent 单轮图 + WS 桥接」，`app/harness/` 空包待按本文逐层填充，依赖锁定 `langgraph==1.2.10`，测试基线更新为 `test_llm_graph.py` / `test_agent_graph.py`；V1.4.1 评审补丁：补 GraphState 可序列化迁移路径、OR-2 补登 `allows_replan`、声明 `langgraph-checkpoint-postgres` 依赖白名单、标注 `handle_confirm_ack` 为规划中函数；V1.4.2 架构落地补丁：新增 §9「架构文件树与待生成代码清单」，把六层职责与演进阶段映射到 `app/harness/`、`app/agent/`、`app/runtime/` 的包/文件骨架，给出阶段 1–4 的文件生成清单与所属层/需求编号；V1.4.3 模块设计回写：§7 新增「内部短 MCP 允许 + 基础工具集为通用能力」裁决行（M5-D4），§9.1/§9.2/§9.3 把 `state.py` 从 `orchestration/` 移到 `memory/`（M3-D1，GraphState 归记忆层所有）；V1.4.4 契约分期修正：§9.1/§9.2/§9.3 把 `contracts/artifacts.py` 改为两波分期（阶段 2 早波 ToolCall/ToolResult/Observation + 阶段 4 晚波 PlanArtifact/SkillHint），消除 M5/M6 阶段 2 引用未生成契约的 ImportError 阶段倒挂；V1.4.5 评审收敛：§2.5 收敛事件生产者归属（图节点/收包循环/Worker 三类，唯一源 M7 §3.6.1）；§7 新增「通用 bash 阶段 2 不开放」红线；§8 新增阶段 3 阻断验收（`should_abort` 迁移 + GraphState 序列化 + Worker 事件实时转发）；**V1.4.6 阶段 1–4 实现闭环（分支 `feat/agent-stage1`）**：按 §9.3 清单落地 M1–M10 全部模块（`app/harness/` 六层 + `app/agent/` 路由/ReAct/澄清/Plan-Solve/reflect + Checkpointer 双实现与 `harness_checkpoints` 迁移 + M10 技能目录），完成 `should_abort` 全链路迁移（`RunnableConfig.configurable`）、`pending_events` 事件桥接（节点产出 → ws.py 统一 emit）、`/stop`/`/compact`/`confirm_ack` 收包循环直连、窗口算法与 observation 脱敏注入；新增 8 个测试文件并改造既有测试，`ruff check . ../shared` 与 159 项 pytest 全绿。 |
| 实现代码（阶段 1–4，分支 `feat/agent-stage1`） | 新增 | `app/harness/contracts/`（events/artifacts）、`app/harness/memory/`（state/working/episodic/compressed/preference/semantic/checkpoint/cleanup）、`app/harness/prompts/`（system/protocols/safety）、`app/harness/context/`（window/assembly/observation/compact/meter）、`app/harness/orchestration/`（router/budget/gates/plan/confirm）、`app/harness/execution/`（registry/binding/dispatch/toolnode/worker_bridge）、`app/harness/feedback/`（observation/rules/review/budget/isolation）、`app/harness/security/`（secrets/auth）、`app/harness/skills/`（registry）、`app/agent/`（routing/react/clarify/plan_solve/reflect + graph 改造）、`app/llm/`（contracts/gateway should_abort 迁移）、`app/routers/ws.py`（事件桥接 + /stop + /compact + confirm_ack）、`migrations/versions/a1f3c5e7b9d1_新增harness检查点表.py`、`tests/`（新增 8 个测试文件 + 改造 test_agent_graph/test_llm_graph 等） | 按 §9.3 六层 × 阶段清单逐文件落地，全部 TDD 验收点（O-A*/X-A*/E-A*/F-A*/P-A*/C-A*）有对应测试覆盖；`should_abort` 不入 GraphState；`api_key` 不入 SerializableRequest；节点不持 WS 连接；长工具门禁拦截；`rag` 未接入必失败。 |

本次修订含需求文档版本闭环与 `feat/agent-stage1` 分支的实现代码清单；不改变任何 API、数据库表结构（新增 harness 检查点表迁移）、前端或 Worker 运行契约。

### V1.4.7 澄清卡链路实现闭环（main 直接迭代，2026-08-24）

按 §3.9.6 / M9 §3.5.1 补齐澄清卡前后端缺口：

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/graph.py` | `LangGraphAgent.astream` 增加 `resume` 参数：`Command(resume=answer)` 恢复被澄清卡中断的图（thread_id 与中断时一致） |
| `backend/api/app/routers/ws.py` | 新增 `_SESSION_CLARIFY` 待回复澄清卡注册表；`_run_turn` 支持 `resume` 模式（复用 thread_id、不构造新请求）；消费 `__interrupt__` 帧翻译为 `clarify` 事件（`_handle_clarify_interrupt`）；收包循环新增 `clarify_reply` 分支（`_handle_clarify_reply`：id 匹配校验/空回复拒绝/回合串行 CONCURRENCY，`Command(resume)` 恢复）；新用户消息作废旧澄清卡 |
| `frontend/src/api/ws.ts` | 新增 `sendClarifyReply(id, answer)`；`types.ts` 事件联合类型补 `'clarify'` |
| `frontend/src/components/agent/ClarifyCard.vue` | 新增澄清卡组件：问题 + 可选选项 chips + 回复输入 + 发送（**仅回复，无确认入队**，与 ConfirmCard 互斥） |
| `frontend/src/views/Agent.vue` | StreamItem 补 `clarify` 项；模板渲染 ClarifyCard；三处事件分支（live/replay/buffer）处理 `clarify`；`handleClarifyReply` 发送并盖章；`harnessStage` 类型与标签补 `plan_solve`（「Plan-Solve 执行中」） |
| `backend/api/tests/test_ws_clarify.py` | 新增 6 项链路测试（中断注册/无待回复/失效 id/空回复/恢复同 thread/并发拒绝） |

验收：`ruff check . ../shared` 全绿；后端 pytest **303 项全绿**；前端 `npm run typecheck` + `npm run build` 通过。澄清卡仅回复输入、不建任务、不写 pending_confirm（M4 §3.9.6）。

### V1.4.8 验收文案修正（2026-08-24）

生产验收（47.119.132.83）发现 `/help` 帮助文本仍标注「/compact 后续版本开放」，与事实不符（`/compact` 已由 ws.py 收包循环直连实现）。修正：

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/routing.py` | `HELP_TEXT` 更新：`/compact：压缩本会话模型窗口（仅会话负责人）`，`/cancel、/stress：后续版本开放`；`direct_node` 的 `/compact` 分支移出「未启用」集合，改为不可达路径防御提示「由平台会话控制处理」（WS 拦截为唯一入口，图节点不持 DB） |
| `backend/api/tests/test_agent_routing.py` | 更新 `test_unimplemented_slash_returns_validation`（/compact 断言变更）；新增 `test_help_text_mentions_compact_available`（帮助文本与现状一致性回归） |

验收：routing 9 项测试全过、ruff 全绿；生产 WS 层 T3 `/compact` 实测通过。

### V1.4.9 会话工作区隔离（2026-08-24）

实现「每个会话一个独立文件夹（工作区）」：会话级沙箱根目录 `{root}/{session_id}`，`read`/`write`/`edit` 与后续 `bash` 均以工作区为根天然隔离。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/workspace.py`（新增） | `get_workspace_root()`（env `AGENT_WORKSPACE_ROOT` 优先 → 容器 `/data/workspaces`（`./data` 持久卷挂载）→ 本地 `data/workspaces`）；`session_workspace_dir()`（session_id 严格校验 UUID 安全字符集，**防路径穿越**，M5-D7 目录侧闭环）；`ensure_session_workspace()`（mkdir -p 幂等） |
| `backend/api/app/routers/ws.py` | `_run_turn` 每回合 `ensure_session_workspace(session_id)` 并注入 `configurable["sandbox"]["dir"]`（toolnode 已有读取路径，优先于构造默认值） |
| `backend/api/app/harness/execution/__init__.py` | 导出 workspace 三函数 |
| `backend/api/tests/test_harness_workspace.py`（新增） | 5 项测试：目录创建、双会话隔离、非法 id 拒绝（路径穿越/空/超长）、根解析、toolnode 集成（`configurable['sandbox']['dir']` 生效 + 跨工作区读取被拒） |

说明：不新增任何对外 REST/WS 字段（sandbox 仅内部 `RunnableConfig.configurable`）；`bash` 命令仍按红线不注册（阶段 2 不开放通用 bash），工作区目录即后续 bash 的 cwd 边界。验收：ruff 全绿、相关 20 项测试全过。

### V1.5.0 bwrap 沙箱开放通用 bash（2026-08-24）

把 V1.4.5 起冻结的「bash 不开放」升级为**阶段 3 bwrap 进程级沙箱**：每次 bash 调用起一次性沙箱，无网络、会话工作区唯一可写、资源受限（ulimit 内存/进程数/CPU）、超时整树清理；黑名单保留为纵深防御，bwrap 不可用/引擎关闭时 fail-closed。§7「通用 bash 工具」红线行已回写。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/sandbox.py`（新增） | `SandboxLimits`（memory/nproc/cpu）；`_build_bwrap_argv`（`--unshare-*` + 最小只读 bind + `--bind` 工作区到 `/work` + `--tmpfs /tmp /run` + clearenv）；`run_sandboxed`（Popen + `start_new_session`，超时 `killpg(SIGKILL)` 整树清理，非零退出码归一 INTERNAL，bwrap 缺失/启动失败归一 VALIDATION fail-closed）；`probe_sandbox`（冒烟探测 + 进程内缓存） |
| `backend/api/app/harness/execution/dispatch.py` | `run_bash` 保留 `BASH_BLOCKLIST` 首词校验（纵深防御），执行体改走 `run_sandboxed`；模块头部安全边界更新 |
| `backend/api/app/harness/execution/registry.py` | 注册 `bash` 工具（`permission="sandbox.bash"`、`timeout_s=15.0`）；`_bash_handler` 读 Settings 构造 `SandboxLimits`，引擎非 `bwrap` 时 fail-closed |
| `backend/api/app/harness/feedback/rules.py` | 门禁 #3 bash 黑名单语义更新为「纵深防御（bwrap 之外第二道防线）」，集合保留 |
| `backend/api/app/config.py` | 新增 `sandbox_engine/memory_mb/nproc/cpu_s/bwrap_bin` Settings |
| `backend/api/app/routers/ws.py` | `configurable["sandbox"]` 扩展为 `{dir, engine, limits}`（仍仅内部配置，无对外字段） |
| `backend/api/app/harness/execution/toolnode.py` | `tool_node` 转 **async 节点**，`execute` 经 `asyncio.to_thread` 线程池执行（防 15s bash 阻塞 api 事件循环） |
| `backend/api/Dockerfile` | apt 安装 `bubblewrap` |
| `docker-compose.yml` | api 服务加 `security_opt: [seccomp:unconfined]`（Docker 默认 seccomp 拦截 bwrap 所需的 unshare/mount/pivot_root） |
| `backend/api/tests/test_harness_execution.py` | 注册表断言改为含 bash；新增 mock `run_sandboxed`、fail-closed、引擎 off 用例 |
| `backend/api/tests/test_harness_sandbox.py`（新增） | 集成测试（`skipif not probe_sandbox()`）：正常执行/工作区可写/系统目录只读/敏感路径遮蔽/跨会话隔离/超时整树清理/内存超限/无网络/fork 炸弹受限 |

说明：不新增任何对外 REST/WS 字段（sandbox 仅内部 `RunnableConfig.configurable`，API.md 契约不变）；无 Alembic 迁移（无表变更）；`bash` 沙箱在 api 容器内以 root 运行，依赖 compose `seccomp:unconfined`，更严格的自定义 seccomp profile 列为后续项。验收：ruff 全绿、API 全量 314 项测试过、worker 12 项测试过。

### V1.5.1 Progressive Disclosure 技能工作流按需加载（2026-08-26）

落地 SK-1：Skill Hint 常驻目录，完整工作流不进 GraphState，由本轮 `plan.skill_id` 按需装配进【当前技能工作流】；相邻回合互不污染（SK-2）；`skill-rag` 规划即 `VALIDATION`（SK-4）。不新增对外 REST/WS 字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/skills/workflows.py` | 启用技能工作流正文；`load_skill_workflow` |
| `backend/api/app/harness/skills/registry.py` | `plan_skill_id` 只返回索引 |
| `backend/api/app/harness/context/assembly.py` | `skill_hints_for_turn`；`assemble(skill_workflow=)` |
| `backend/api/app/agent/react.py` / `plan_solve.py` / `routing.py` | ReAct 按需注入；规划拦截未启用 skill |
| `backend/api/tests/test_harness_skills.py` | K-A1~K-A5 |

### V1.5.2 检查点 TTL + 会话软删除联动（2026-08-26）

闭环 §2.4 / M9-D5 / M9-D6：会话软删除按 `{session_id}:` 前缀（兼容裸 `session_id`）清理检查点；TTL 默认 7 天，由 **API 进程 lifespan** 每 6 小时执行（默认 memory 引擎只存在于 API 进程，不新增 Worker 职责）。不改默认 Checkpointer 为 postgres，不新增对外 REST/WS 字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/memory/checkpoint.py` | 内存检查点改为进程内锁；`get_default_checkpointer` 进程单例 |
| `backend/api/app/harness/memory/cleanup.py` | `cleanup_session_checkpoints` / `purge_session_checkpoints` |
| `backend/api/app/runtime/cleanup.py` | TTL 后台循环（M9-D6） |
| `backend/api/app/routers/sessions.py` | `DELETE /api/sessions/{id}` 软删除后联动清理 |
| `backend/api/app/main.py` | lifespan 挂载 TTL 任务 |
| `backend/api/tests/test_checkpointer.py` / `test_runtime_checkpoint.py` | R-A3 / R-A4 |
