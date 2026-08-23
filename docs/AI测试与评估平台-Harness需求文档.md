# AI 测试与评估平台 — Harness 需求文档

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 需求文档 |
| 版本 | V1.3 |
| 审查日期 | 2026-08-23 |
| 文档性质 | 需求规格说明书（需求先行） |
| 适用范围 | `/agent` 对话智能体的 Harness 运行时：六层职责、七种模式组合、LangGraph 框架选型、技能体系与验收标准 |
| 事实来源 | 现行 `backend/api/app/agent/`、`routers/ws.py`、`backend/worker/app/`；PRD、API.md、Agent 开发文档 |

> **阅读关系**：本文是**需求层**，回答"Harness 应具备哪些能力、按什么标准验收"；实现结构以《AI测试与评估平台-Harness六层ReAct核心架构设计.md》（目标架构）为准，运行行为校正以《AI测试与评估平台-Harness运行逻辑与架构校正说明.md》为准，产品状态机与字段以 PRD / API.md 为准。本文不新增任何对外 REST/WS 字段。

> **V1.1 修订定位**：新增第二章"框架选型：LangGraph"，明确 Harness 以 **LangGraph（StateGraph + Checkpointer + interrupt）** 为唯一实现框架；七种模式映射到 LangGraph 原语；原自研 asyncio harness 代码（`react.py`/`harness.py` 循环）定位为**迁移前现状**，按 §2.3 分阶段替换。对外 WS 协议、确认卡、错误码与红线不变。

> **V1.2 修订定位**：按 V1.1 评审结论收敛设计——① 裁决**确认卡继续走 WS 收包循环直连**（`handle_confirm_ack` 事务），不迁移 `interrupt()`；② `interrupt()` 仅作为"需模型继续的中间暂停"预留；③ **排除 `create_react_agent` 预构建**，只允许自建 `StateGraph` 复刻解析/绑定/门禁链路；④ 明确 Checkpointer 只存**图内部执行状态**，对外事件与断线重放仍由 `ws_events` 承担；⑤ 保留"单会话单活动回合"并发约束；⑥ `ToolNode` 必须包装 `mcp_registry` 参数绑定/白名单/超时/脱敏；⑦ 澄清"子图=图内复用节点，≠sub-agent 编排"。

> **V1.3 修订定位**：落实第二轮评审四项裁决——① **LangGraph 覆盖六层全部实现**，六层架构文档需大幅改版（自研 `harness/` 目录作废）；② `interrupt()` 明确用于**澄清卡场景**（模型追问澄清而非确认卡，用户回复后 `Command(resume)` 继续）；③ **PostgresSaver 检查点表纳入 Alembic 管理**并定义保留策略（TTL/会话删除联动，遵守红线 4）；④ P0-LG 阶段图节点**返回纯数据、WS 层统一 emit**，断线恢复仍靠 `ws_events` 不依赖检查点。

---

## 1. 文档定位与需求总目标

### 1.1 定位

本平台 Agent 不是"自由调用任意工具的通用自治 Agent"，而是面向**评测任务**的受控 Harness：模型负责结构化判断，Harness 负责控制、执行、持久化与授权。本需求文档把该运行时拆成**六层职责**与**七种设计模式组合**，逐项给出需求条目、现状差距与验收标准。

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

LangGraph 定位为**六层全覆盖框架**（V1.3 裁决）：提示词装配、上下文窗口、记忆/检查点、编排状态机、工具执行、反馈归一均以 LangGraph 图节点与其生态实现，承载七种模式的图拓扑与节点状态机。不继续扩展自研 asyncio harness 循环（`react.py` / `harness.py`），逐步替换为 LangGraph 图节点。

> **文档影响（V1.3）**：本裁决要求**同步大幅改版《AI测试与评估平台-Harness六层ReAct核心架构设计.md》**——其中自研 `harness/` 目录树作废，改为 LangGraph 落地映射（编排层=StateGraph、上下文=节点装配、记忆=Checkpointer/Store、执行=ToolNode、反馈=节点返回值）。六层职责边界（各层可依赖/禁止承担）与 trace/取消契约保留，作为节点内确定性逻辑。

选型理由：

| 需求 | LangGraph 对应能力 | V1.3 裁决 |
| :--- | :--- | :--- |
| 七种模式统一表达 | `StateGraph` 节点 + 条件边；ReAct / Plan-and-Execute / Reflection 均为该框架官方参考模式 | 采用自建 `StateGraph`，**排除 `create_react_agent` 预构建**（见 §2.4） |
| 确认卡 | `interrupt()` 可暂停图等待用户输入，`Command(resume)` 恢复 | **确认卡不采用** `interrupt()`：继续走 WS 收包循环直连（`handle_confirm_ack` 事务，§2.5） |
| 澄清卡（Human-in-the-Loop） | `interrupt()` 暂停图 → 用户回复 → `Command(resume)` | **采用**：模型需向用户追问澄清（非确认卡）时暂停图，用户回复后恢复（§2.5） |
| 会话级状态恢复 | Checkpointer（`PostgresSaver` / `MemorySaver`）按 `thread_id` 保存快照 | 仅存**图内部执行状态**（plan/observations/暂停点）；对外事件与断线重放仍由 `ws_events` 承担（§2.5） |
| 并行与取消 | 节点级异步执行 | `/stop` 即时中断仍走 `asyncio` 任务取消；`interrupt()` 可恢复暂停**不替代**取消（§2.5） |
| 长任务分离 | 图只编排短工具与入队动作；评测/压测仍经 PG 队列交 Worker | 不变（进程级） |

### 2.2 LangGraph 原语 → 七种模式映射

| 模式 | LangGraph 落地 | 迁移前现状 |
| :--- | :--- | :--- |
| ReAct | 自建 `StateGraph`：`agent` 节点（LLM 调用 + 严格 JSON 解析）→ 条件边 → `ToolNode`；**禁止 `create_react_agent`**（tool-calling 直传参数会绕过绑定/门禁） | `agent/react.py` 自研循环 |
| Plan-and-Execute | `plan` 节点生成 `PlanArtifact` → 条件边选 `chat/react/plan_solve`；plan_solve 进入执行子图（**图内复用节点，无独立 LLM 循环**） | `agent/plan.py`、`agent/turn_mode.py` |
| Orchestrator-Worker | **仅进程级**：确认回执由收包循环 `handle_confirm_ack` 直接创建 `queued` 任务（图不等待确认）→ PG 队列 → Worker → 事件回写。不引入 LLM 子代理 | `routers/ws.py`、`worker/app/main.py` |
| Mixture of Experts | skill 路由节点：按 `intent/skill_id` 选择 Skill Hint 注入上下文；评测域 Skills 体系不变 | `agent/persona.py`、`agent/defaults.py` |
| Progressive Disclosure | 图状态只携带 Skill Hint 索引，完整技能文档由节点按需装配，不常驻 State | `agent/persona.py` `SKILL_HINTS` |
| Reflexion | `reflect` 节点：确定性 `run_gates`（G1–G9）→ 条件边 pass/clarify/reject；可选 `maybe_model_check` 只降级不放行 | `agent/reflect.py` |
| Tool-Augmented | `ToolNode` 包装 `mcp_registry.py`（参数绑定/白名单/超时/脱敏，§4.5）；Worker 长工具不走 ToolNode | `agent/mcp_registry.py` |

> **冲突裁决**：模式 3 在本平台定义为**进程级**「控制面 Agent ↔ 执行面 Worker」。文档中"子图"一律指 **LangGraph 图内复用节点**（无独立 LLM 循环）；**禁止**用 LangGraph 子图编排 LLM 子代理（子代理/递归 Harness 属平台红线，明确不做）。

### 2.3 迁移策略（每阶段 WS 协议不变）

```text
阶段 0  引入 langgraph 依赖（入 requirements.txt）+ 建 GraphState/TypedDict 契约
        + 行为对齐测试夹具（旧循环测试与新图测试双跑基准）
        + 定义图节点返回纯数据 → WS 层统一 emit 的事件桥接契约（§2.5）
阶段 1  以 StateGraph 承载 Chat 与 Direct（斜杠）路径，行为对齐现状
阶段 2  以 StateGraph + ToolNode 承载 ReAct（4 项短工具），替换 react.py 自研循环
阶段 3  接入 Checkpointer（PostgresSaver，thread_id=session_id；检查点表经 Alembic 建表，
        保留策略 TTL/会话删除联动）持久化图内部状态；
        确认卡保持收包循环直连（§2.5）
阶段 4  Plan-and-Solve 执行子图 + reflect 节点恢复评测业务 Workflow（M1 确认卡入队）
```

每个阶段独立开 `feat/` 分支、独立 PR；阶段内不得出现"自研循环 + LangGraph"双实现并存（迁移完成即删旧路径）。迁移不影响 `routers/ws.py` 对外事件流、确认卡、斜杠与错误码契约。

### 2.4 依赖与红线

- 新增依赖 `langgraph`（含 `langgraph-checkpoint-postgres` 等运行时包）写入 `backend/api/requirements.txt`，CI（`ci.yml` 后端 job）自动覆盖；**禁止**引入 langchain 全家桶、外部 MCP 或 LangGraph 云服务。实施前须验证 Python 3.12 + Pydantic v2 兼容。
- **排除 `create_react_agent`**：其 tool-calling 消息格式让模型直接传参，会绕过 `bind_tool_arguments` 附件绑定与白名单门禁（AGENTS.md §3.3.1）。只允许自建 `StateGraph` 复刻现有"严格 JSON → 注册表校验 → 参数系统绑定 → 脱敏执行"链路。
- `ToolNode` 必须包装 `mcp_registry.py`：附件参数绑定（EX-2）、白名单/超时（EX-3）、脱敏（CX-3）保持为节点内逻辑，**不得**被框架默认行为绕过。
- `interrupt()` 仅用于**澄清卡场景**（§2.5）；**不得**用于确认卡等待、长任务忙等。评测长任务必须走 PG 队列交 Worker。
- 状态值必须为可序列化 JSON（PG 检查点兼容）；禁止把 DB Session、WebSocket 连接等不可序列化对象写入 GraphState。
- 共享会话并发：保留"单会话单活动回合"约束（§2.5 方案①），Checkpointer 写入不得覆盖并发回合。
- **检查点表治理（V1.3）**：`PostgresSaver` 产生的检查点表**必须经 Alembic 迁移建表**（红线 4），不得依赖框架在运行时自动建表；保留策略为 TTL + 会话软删除联动（会话删除时清理其检查点），过期清理由后台任务执行。

### 2.5 确认卡、澄清卡与事件桥接裁决（V1.3）

**方案①（裁决采用）**：确认卡继续走 **WS 收包循环直连**，与现行 `harness.py:877` `handle_confirm_ack` 行为一致：

```text
confirm_ack 收包 → 行锁读 sessions.pending_confirm
  → owner 校验 → patch 深合并 → TaskCreate 二次校验
  → 创建 queued Task + AuditLog → 清空 pending_confirm
  → 发 confirm_ack / tool_call / tool_result 事件
```

- **单一事实源**：`sessions.pending_confirm` 是确认卡唯一状态源；`PostgresSaver` 检查点只存图内部执行状态，二者职责不重叠。
- **确认卡等待不计回合墙钟**：确认回执不唤醒/恢复图执行，因此不占用 180s 回合预算（与现状一致）；仅当确认后需要模型继续时，才以新回合启动并可选从检查点恢复。
- **`/stop` = 即时中断**：走 `asyncio` 任务取消（`stop.set()` + `abort.set()` + `task.cancel()`），**不可恢复**；`interrupt()` 是可恢复暂停，**不替代**取消。二者语义分离。
- **并发约束**：保留 `_HARNESS_BY_SESSION` registry + lock 保证单会话单活动回合；Checkpointer 写入需在回合完成后提交，避免覆盖并发回合状态。

**澄清卡场景（V1.3 裁决）**：`interrupt()` 用于**澄清卡**——模型需要向用户追问澄清（非确认卡、非任务下单）时，图节点调用 `interrupt()` 暂停，等待用户回复后以 `Command(resume)` 恢复：

```text
澄清卡触发（缺槽位/意图不清/需用户选择）
  → interrupt() 暂停图（写检查点）→ 发澄清卡事件 → 不占 180s 回合预算
  → 用户回复 → Command(resume=回复) 恢复图 → 节点继续
```

与确认卡的区别：澄清卡**不创建任务、不写 pending_confirm**，恢复后仍可能走补规划/再次 ReAct；澄清卡是图内 HITL，确认卡是图外直连。

**事件桥接契约（V1.3 裁决）**：图节点**只返回纯数据**（结构化结果），不直接持有 WS 连接或 emit 回调；事件（thought/tool_call/tool_result/message）由收包循环把图节点返回值统一转 `emit_factory` 发出：

```text
图节点执行 → 返回纯数据（结构化结果/事件意图）→ 图输出
  → 收包循环读取图输出 → 统一调 emit_factory 发事件
  → 断线恢复仍走 ws_events 重放，不依赖检查点
```

P0-LG（阶段 0–2）无 Checkpointer 期间，图状态在进程内由 `_HARNESS_BY_SESSION` 承载；图节点返回值即事件来源，避免节点内注入 WS 连接违反 GraphState 可序列化红线。

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
└─────────────────────────────────────────────────────┘
```

| 模式 | 平台落地形态 | LangGraph 落点 | 当前状态 |
| :--- | :--- | :--- | :--- |
| ReAct | `thought/tool/arguments/done/reply` 严格 JSON 循环 | `StateGraph` + `ToolNode` | 🟡 自研已实现，待迁 LangGraph（§2.3 阶段 2） |
| Plan-and-Execute | `PlanArtifact` + `loop` 路由（chat/react/plan_solve） | `plan` 节点 + 执行子图 | 🟡 骨架已实现，业务 Workflow 关闭 |
| Orchestrator-Worker | 收包循环 `handle_confirm_ack` 入队（图不等待确认，§2.5）→ PG 队列 → Worker 执行 → 事件回写 | 确认回执直连 + Worker | ✅ 进程级已实现 |
| Mixture of Experts | Skills 体系 + Skill Hint（评测域专家） | skill 路由节点 | 🟡 Skill 索引已实现，完整工作流待评测业务恢复 |
| Progressive Disclosure | 技能仅暴露名称+一句话，正文按需加载 | 图状态只存 Skill Hint 索引 | ✅ 已实现 |
| Reflexion | 确定性 `run_gates`（G1–G9）+ `maybe_model_check` | `reflect` 节点 + 条件边 | 🟡 门禁已实现，模型核对默认关闭 |
| Tool-Augmented | 注册表短工具（4 项）+ Worker 长工具 | `ToolNode` 绑定注册表 | ✅ 已实现（范围最小化） |

---

## 4. 六层职责需求（LangGraph 落点）

### 4.1 提示词工程层

**职责**：固定系统策略与阶段输出协议；模型不持有控制逻辑。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| PR-1 | 固定 `PERSONA_SYSTEM` 定义角色、安全边界、确认卡、长短任务分离、密钥保护 | 系统提示词不允许用户配置覆盖；注入关键词验证存在 |
| PR-2 | 规划/ReAct/复核/压缩各阶段有独立输出协议（`PLAN_JSON_SUFFIX`、`REACT_LOOP_SUFFIX`、`REFLECT_CHECK_SUFFIX`、`COMPACT_SYSTEM`） | 各阶段模型输出必须为受约束 JSON；协议版本化 |
| PR-3 | 明确"thought 是动作摘要，不是授权依据" | 解析链路只消费 `tool/arguments/done`，不执行 thought 文本动作 |
| PR-4 | 用户输入不得拼接进系统规则；system/user 消息边界固定 | 注入测试：用户文本含"忽略系统提示"时策略不变 |

**现状**：`persona.py` 已实现四段提示词；`agent/log.py` 提供脱敏追踪。**LangGraph 落点**：提示词模板仍是静态节点常量，不进入图状态。验收补：阶段协议独立存在 + 单测覆盖（`tests/test_harness.py`）。

### 4.2 上下文工程层

**职责**：决定模型本轮可见输入；相关性、来源、安全、容量与成本同时优化。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| CX-1 | 最近消息窗口为**唯一**窗口算法（默认末尾 20 条，`compact_keep_from` 截断） | `window_rows()` 行为与单测一致 |
| CX-2 | 思考/工具/确认/进度事件不进入消息窗口，只入 `ws_events` 供回放 | 断言工具事件数不影响窗口消息数 |
| CX-3 | 工具结果为**脱敏、截断、带来源的 observation 摘要**，不原样注入 | `api_key/token/password/secret/cookie` 键递归脱敏；超长截断带 `truncated=true` |
| CX-4 | 上下文装配顺序固定：Persona → Skill Hint → compact_summary → 阶段输入 | `turn_system()` 输出顺序断言 |
| CX-5 | 工具定义按本轮能力最小注入，不默认全量注入所有工具 schema | 本轮未注册工具不出现在注入清单 |
| CX-6 | `/compact` 为可控摘要：保留最近 6 条、摘要 ≤2000 字符、不删除原始记录 | 摘要写入 `sessions.compact_summary`；原始 messages/ws_events 保留 |
| CX-7 | ContextMeter 只读 `GET /api/sessions/{id}/messages` 的 `context_meter` | 前端不自行计算窗口 |

**现状**：`context.py` 已实现窗口/摘要/ContextMeter。**LangGraph 落点**：上下文装配为图节点输出，窗口内容经 `messages` reducer 由 Checkpointer 保存。缺：语义召回、Rerank（当前明确未接入，属记忆层演进，见 4.3）。

### 4.3 记忆层

**职责**：按类型保存、检索、摘要与失效；记忆不进上下文，而是可检索的状态。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| MEM-1 | 工作记忆：本轮 Plan、observations、停止标志为回合内暂态 | 回合结束不持久化为系统事实 |
| MEM-2 | 情景记忆：sessions / messages / ws_events / tasks 持久化于 PostgreSQL | 断线重连按 `last_event_id` 重放 |
| MEM-3 | 压缩记忆：`compact_summary` 可更新派生状态，不视为唯一真相 | 原始记录与摘要冲突时原始优先 |
| MEM-4 | 偏好记忆：仅确认成功入队后写 `settings.agent_prefs:{user_id}` 允许字段 | 偏好只作规划建议，不可绕过 ID 溯源门禁 |
| MEM-5 | 语义/知识记忆：pgvector 与 LightRAG 属**演进项**，接入前显式带来源检索 | 未接入期间 `rag` 任务必须失败（`VALIDATION`），不得 mock |
| MEM-6 | 记忆检索带权限过滤与溯源（`source_id`/版本/ACL） | 越权记录不可检索 |

**现状**：MEM-1/2/3/4 已实现；MEM-5/6 为演进需求，对应《Harness六层ReAct核心架构设计》§5.2（首期 PG+pgvector+Redis，LightRAG 暂不接入）。**LangGraph 落点（V1.2）**：MEM-2 情景记忆与断线重放**仍由 `ws_events` + `last_event_id` 承担**，Checkpointer（`thread_id=session_id`）只存图内部执行状态（plan/observations/暂停点），二者职责不重叠；MEM-1 工作记忆即 GraphState 的暂态字段；MEM-3 `compact_summary` 继续存 `sessions`；MEM-4 偏好记忆继续存 `settings.agent_prefs`。

### 4.4 编排层

**职责**：选择控制流（Chat / ReAct / Plan-and-Solve / Direct），生成可验证中间状态，模型不直接执行副作用。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| OR-1 | 模式路由：斜杠 → Direct；无工具 → Chat；短工具 → ReAct；多槽位业务 → Plan-and-Solve | `select_turn_mode/resolve_turn_mode` 断言 |
| OR-2 | `PlanArtifact` 冻结字段：intent/skill_id/slots/tools_needed/delivery/budget/notes | 规划 JSON schema 校验 |
| OR-3 | 规划解析失败重试一次，仍失败走 L0 规则降级，降级后必须经复核 | 异常路径单测覆盖 |
| OR-4 | 每轮**至多执行一个短工具**，重复调用抑制 | ReAct 循环断言 |
| OR-5 | 模型调用预算受控（规划+重试+补规划+可选核对 ≤4 次；工具轮次默认 4、上限 5） | `TurnBudget.consume()` 断言 |
| OR-6 | 长任务（benchmark/testcase/rag/stress）**不得**在对话回合内同步执行 | 门禁 G4/G9 拦截 `is_long_tool` |
| OR-7 | 会话存在活动任务时禁止再发确认卡 | 门禁 G5 返回 `CONCURRENCY` |
| OR-8 | `task.create` 只在 `confirm_ack.ok=true` 且卡片 patch 合并后二次校验通过时发生 | WS 确认回执事务断言 |

**现状**：OR-1/3/4/5/6/7/8 已实现；`allows_replan=False`、`allows_model_check=False` 因评测业务未注册默认关闭（恢复业务时按需求打开）。**LangGraph 落点（V1.2）**：图拓扑即模式路由（条件边替代 `select_turn_mode`）；**确认卡不迁移 `interrupt()`**，OR-8 由收包循环 `handle_confirm_ack` 直连保证（§2.5）；预算/占槽/门禁为节点内确定性检查（OR-5/6/7）；`/stop` 走 `asyncio` 任务取消而非 `interrupt`。

### 4.5 执行层

**职责**：在权限、参数绑定、超时、脱敏与白名单边界内真正产生副作用。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| EX-1 | 工具元数据、白名单与执行分派唯一来源为 `mcp_registry.py` | 新增工具必须同时登记并走 `execute_registered_tool` |
| EX-2 | 附件参数系统绑定，模型不得伪造附件 ID | `bind_tool_arguments` 校验 |
| EX-3 | 每个工具声明 `permission` 与 `timeout_s`，执行带超时与脱敏日志 | 超时返回 `timeout` observation |
| EX-4 | 长任务经 PG 队列由 Worker 消费，进度/报告/错误写 `ws_events` | Worker 主循环 `FOR UPDATE SKIP LOCKED` + 并发闸门 |
| EX-5 | 未注册工具、未启用能力一律拒绝（`VALIDATION` 400），禁止假成功 | `get_tool_definition` 返回空即拒绝 |
| EX-6 | Worker 执行器自管 DB Session，禁止跨 Session 传 ORM 对象 | 任务不出现永久卡 `running` |

**现状**：EX-1/2/3/4/6 已实现；EX-5 中 `rag`/`report` 已按需求拒绝。当前短工具 4 项：`audio.voiceclone`、`image.generate`、`audio.speech_recognition`、`audio.speech_synthesis`。**LangGraph 落点（V1.2）**：短工具经 `ToolNode` 分派且**必须包装 `mcp_registry.py`**——附件参数绑定（EX-2）、白名单/超时（EX-3）、脱敏（CX-3）为节点内逻辑，禁止 `create_react_agent` tool-calling 直传参数绕过；长任务入队节点仅写 PG 队列（EX-4）。

### 4.6 反馈层

**职责**：把工具结果/校验/外部任务事件变成下一步可信依据；区分 observation、确定性门禁与用户/Worker 事件。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| FB-1 | 工具结果归一为 observation（工具名/成功标志/可读错误/耗时/必要摘要），异常不裸抛 | 工具异常不导致 Agent 崩溃 |
| FB-2 | 规则门禁先行：长工具/白名单/任意代码/一单一 kind/必填槽位/资产溯源/占槽/先评后压 | `run_gates` G1–G9 用例通过 |
| FB-3 | 模型辅助核对只能 `pass→clarify` 降级，**不得**把 `reject` 改为 `pass` | `maybe_model_check` 单测 |
| FB-4 | 失败反馈受预算约束，禁止无限重试；超限要求模型澄清或结束 | 预算断言 |
| FB-5 | Worker 的 progress/report/error 只进任务/事件链路，不污染 20 条窗口 | 窗口污染断言 |

**现状**：FB-1/2/4/5 已实现；FB-3 代码保留但 `allows_model_check=False`（业务恢复时启用）。**LangGraph 落点**：工具结果归一为节点返回值（FB-1）；`reflect` 节点条件边承载 pass/clarify/reject（FB-2/3）；确认回执（FB-2 中确认授权）由收包循环 `handle_confirm_ack` 直连完成，图节点不等待确认（§2.5）。

---

## 5. 技能体系需求（MoE + Progressive Disclosure）

平台 Skills 体系按评测域组织。现有 skill 标识：`skill-benchmark`、`skill-rag`、`skill-testcase`、`skill-stress`。

| 需求编号 | 需求条目 | 验收标准 |
| :--- | :--- | :--- |
| SK-1 | 每个 skill 对外只暴露**名称 + 一句话描述**（Skill Hint），完整工作流按需加载 | `SKILL_HINTS` 常驻，正文不常驻 |
| SK-2 | skill 只在当前回合按需注入，不把历史技能卡逐一重复注入 | 相邻回合 skill 注入互不污染 |
| SK-3 | skill 映射评测域职责：benchmark（评测执行）、testcase（用例生成）、rag（知识库评测）、stress（压测） | skill_id ↔ 任务 kind 对齐 |
| SK-4 | 未实现 skill（如 rag）返回 `VALIDATION`，不得伪装成功 | `/benchmark` `/testcase` 之外路径断言 |
| SK-5 | 前端自定义斜杠只请求 `/api/slash-commands`，与后端技能注册一致 | 前后端 skill 清单一致 |

> **需求说明**：六专家分工（planner/generator/executor/healer/reporter/scenario）如需落地为独立 skill，须作为需求变更提交评审；当前以 SK-1～SK-5 最小体系满足"按需加载"与"评测域能力声明"。

---

## 6. 需求优先级与里程碑映射

| 优先级 | 需求 | 里程碑 |
| :--- | :--- | :--- |
| P0 | PR-1~4、CX-1~7、MEM-1~4、OR-1/3/4/5/6/7/8、EX-1~6、FB-1/2/4/5、SK-1/2/4/5 | 已实现（当前最小内核） |
| P0-LG | §2.3 阶段 0–2：引入 langgraph，Chat/Direct/ReAct 迁入 StateGraph + ToolNode；图节点返回纯数据、WS 层统一 emit（§2.5）；进程内状态由 `_HARNESS_BY_SESSION` 承载，断线靠 `ws_events` | 近期：框架迁移（不改对外契约；确认卡保持收包循环直连；不接 Checkpointer） |
| P1 | §2.3 阶段 3–4：Checkpointer（PostgresSaver + Alembic 建表 + TTL/会话删除联动）、澄清卡 `interrupt()`、Plan-and-Solve 执行子图、OR-2/`allows_replan`、FB-3/`allows_model_check`、SK-3 完整评测工作流 | M1：Agent 确认卡驱动真实任务入队 |
| P2 | MEM-5 语义记忆（pgvector + Redis）、SK-5 技能工作流文档化 | M2/M3：评测业务恢复、LightRAG 接入评审 |

P0-LG 阶段引入依赖时须同步更新 `backend/api/requirements.txt`；P1/P2 需求启动前须回写对应文档（API.md / Agent 开发文档），遵守文档闭环规范。

---

## 7. 冲突边界与红线

| 需求 | 裁决 |
| :--- | :--- |
| Orchestrator-Worker 子代理并行 | **禁止** LLM 递归子代理与 LangGraph 子图编排子代理（子图仅指图内复用节点，无独立 LLM 循环）；平台仅做进程级 Agent ↔ Worker 编排 |
| 确认卡实现路径 | **收包循环直连**（`handle_confirm_ack` 事务），不迁移 `interrupt()`；`sessions.pending_confirm` 为唯一状态源 |
| 澄清卡实现路径 | `interrupt()` + `Command(resume)`，仅限澄清（不建任务、不写 pending_confirm）；不占 180s 回合预算 |
| `/stop` 与 `interrupt` | `/stop` 即时中断走 `asyncio` 取消（不可恢复）；`interrupt()` 仅用于澄清卡暂停，二者语义分离 |
| 预构建 Agent | **排除 `create_react_agent`**（tool-calling 直传参数绕过绑定/门禁）；只允许自建 `StateGraph` |
| 检查点边界 | `PostgresSaver` 只存图内部执行状态；对外事件与断线重放仍由 `ws_events` + `last_event_id` 承担 |
| 检查点表治理 | 检查点表**经 Alembic 迁移建表**（红线 4），保留策略 TTL + 会话删除联动，后台任务清理 |
| 事件桥接 | 图节点只返回纯数据；事件由收包循环统一 emit，节点内禁止持有 WS 连接/emit 回调 |
| LangGraph 依赖范围 | 仅 `langgraph` 运行时包进 `backend/api` 并写入 `requirements.txt`；禁止 langchain 全家桶、LangGraph 云服务、外部 MCP |
| 外部 MCP / 用户自定义系统提示词 | 明确不做，防越权与提示词污染 |
| RAG 语义记忆 | 未接入前 `kind=rag` 必须失败；pgvector/LightRAG 为演进项 |
| 记忆文件 / 向量长期记忆 | 当前只有受限摘要与偏好记忆，不得误读为已接入 |
| GraphState 可序列化 | 状态只放 JSON 可序列化值；DB Session / WS 连接不得入 State |
| 新 REST/WS 字段 | 必须先改 API.md，禁止私自扩充 |
| 错误码 | 对外只暴露 10 大 `ErrorCode`；observation 级内部枚举不对外 |

---

## 8. 验收与测试策略

- 需求验收以 `backend/api/tests/` 现有单测为基线：`test_harness.py`、`test_ws_agent.py`、`test_agent_llm.py`、`test_agent_stubs.py`、`test_session_context_persistence.py`。
- **LangGraph 专项**：用 `graph.invoke` / `graph.astream` 断言图拓扑与状态转移；用 Memory 版 Checkpointer 验证 `thread_id` 状态恢复；检查点表建表/清理用 Alembic 迁移测试 + TTL 用例验证。
- **行为对齐双跑**（§2.3）：迁移阶段新旧实现并存期间，同一输入分别走"自研循环"与"LangGraph 图"，断言输出事件与状态转移一致；迁移完成后删旧路径并保留对齐用例作为回归基线。
- **事件桥接验收**：图节点返回纯数据，收包循环统一 emit（§2.5）——断言节点内不持有 WS 连接、事件均经 `emit_factory` 发出。
- **确认卡回归**：确认回执仍走收包循环直连，`test_ws_agent.py` 中 `confirm_ack` 路径保持绿色。
- **澄清卡专项**：`interrupt()` 触发澄清卡 → 暂停写检查点 → 用户回复 → `Command(resume)` 恢复，断言不建任务、不占回合墙钟。
- 新增能力必须配套：模式路由单测、门禁用例、WS 事件回放用例、预算/超时/脱敏用例。
- 本地自检：`cd backend/api && ruff check . ../shared && pytest`；`cd backend/worker && PYTHONPATH=.:.. pytest`。

---

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness需求文档.md` | 新增（V1.0）→ 修订（V1.1）→ 修订（V1.2）→ 修订（V1.3） | V1.0 定义 Harness 六层职责与七种模式组合的需求条目、现状差距与验收标准；V1.1 新增第二章 LangGraph 框架选型；V1.2 按评审结论收敛（确认卡直连、排除预构建 Agent、Checkpointer 边界等）；V1.3 落实第二轮评审四项裁决：LangGraph 覆盖六层（六层架构文档需改版）、`interrupt()` 用于澄清卡、检查点表 Alembic 治理、图节点纯数据 + WS 层统一 emit。 |

本次仅修订需求文档，不改变任何 API、数据库、前端或 Agent 运行代码。
