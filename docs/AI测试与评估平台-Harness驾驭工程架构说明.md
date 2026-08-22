# AI 测试与评估平台 — Harness 驾驭工程架构说明

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 驾驭工程架构说明 |
| 版本 | V1.2（历史目标架构，已同步当前入口） |
| 审查日期 | 2026-08-22 |
| 适用范围 | `/agent` 对话智能体、内部 MCP、任务队列与 Worker 回写闭环 |
| 事实来源 | Agent 开发文档、PRD、API 契约及 `backend/api/app/agent/`、`backend/worker/app/` 的现行实现 |

> **阅读状态（2026-08-21）**：本文 V1.0 的主体保留了“评测 Workflow 完整开放”时的目标架构和历史实现细节，其中列出的 `model.list`、`task.get`、`task.create` 等业务 MCP 已不属于当前最小内核。当前运行行为、能力边界和术语校正以《AI测试与评估平台-Harness运行逻辑与架构校正说明.md》及《AI测试与评估平台-Agent开发文档.md》§32–§33 为准；接口字段与路径仍以 `AI测试与评估平台-API.md` 为准，产品范围与状态机以 PRD 为准。

---

## 1. 结论与设计定位

本平台不是允许模型自由调用任意工具的通用自治 Agent，而是一套面向评测任务的、受控的 Agent Harness：

```text
理解目标 → 选择合适循环 → 查询可信资产 → 规则复核 → 人工确认 → 异步执行 → 事件回写 → 下一轮决策
```

其中心原则是：

1. **模型负责结构化判断，不负责最终授权。** 模型可输出计划、选择循环、选择下一项短工具；是否能发确认卡、是否能创建任务必须由确定性门禁决定。
2. **短交互与长执行分离。** Agent WebSocket 进程只完成规划、内部短 MCP 和确认卡；Benchmark、RAG、用例生成和压测等长任务必须经 PostgreSQL 队列交给 Worker。
3. **人工确认是写操作边界。** 即便模型、工具与规则都通过，`task.create` 也只能发生在用户 `confirm_ack.ok=true` 后。
4. **可追溯性优先于模型猜测。** 协议档、数据集、知识库等资产 ID 必须来自本轮工具观察；模型不能编造 ID。
5. **持久化事件优先于连接状态。** 对话、思考卡、工具卡、确认卡及 Worker 进度写入会话事件表，断线后按 `last_event_id` 重放。

---

## 2. 总体结构架构

### 2.1 服务与控制面/执行面边界

```text
┌────────────────────────────────────────────────────────────────────┐
│ 浏览器 Vue 3 / Naive UI                                              │
│ 会话、消息流、思考卡、MCP 工具卡、确认卡、进度坞、报告卡              │
└───────────────────────┬────────────────────────────────────────────┘
                        │ Cookie + REST / ws-ticket + WebSocket
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│ API：Agent Host（控制面，短生命周期）                                │
│                                                                    │
│  传输层  → 事件落库、心跳、重放、会话级 /stop                        │
│  Harness → Plan → ReAct / Plan-and-Solve → Reflection              │
│  记忆层  → Persona + Skill Hint + Summary + Window + Preferences    │
│  工具层  → 内部短 MCP 白名单                                        │
│  确认层  → pending_confirm，等待 confirm_ack                        │
└───────────────────────┬────────────────────────────────────────────┘
                        │ 仅确认成功时创建 queued Task
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│ PostgreSQL（持久化状态与事件总线）                                   │
│ sessions / messages / ws_events / tasks / task_events / reports     │
│ settings(agent_prefs)                                                │
└───────────────────────┬────────────────────────────────────────────┘
                        │ Worker 轮询 queued Task，受并发闸门约束
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│ Worker（执行面，长生命周期）                                         │
│ benchmark.run / testcase.generate / rag.evaluate / stress.run       │
│ 进度、报告、错误 → 追加 ws_events                                   │
└───────────────────────┬────────────────────────────────────────────┘
                        ▼
               API 后台转发与重连回放 → 浏览器
```

### 2.2 两个循环、两套时钟

系统故意分为两种不同的闭环，避免把长任务绑死在对话连接上：

| 循环 | 责任主体 | 典型时长 | 结束条件 | 用户控制 |
| :--- | :--- | :--- | :--- | :--- |
| Harness 回合 | API 中的异步 `asyncio.Task` | 秒级，墙钟上限 180 秒 | 交付文本、澄清、确认卡或错误 | `/stop` 仅中断本轮生成 |
| 平台任务 | Worker + 队列 | 分钟到更长 | `succeeded` / `failed` / `cancelled` | `/cancel` 取消已入队任务 |

浏览器断线不会取消已入队任务。Agent 回合也不等待 Worker 完成；创建任务成功即完成当前回合，后续进度由事件流异步回写。

---

## 3. Harness 的分层体系

### 3.1 记忆层：提示词工程与上下文工程

#### 3.1.1 固定提示词与系统侧上下文

`persona.py` 中的提示词属于产品策略，不提供用户编辑入口：

| 组成 | 作用 | 是否可由用户修改 |
| :--- | :--- | :--- |
| `PERSONA_SYSTEM` | 职责、安全红线、确认卡、长任务分离、密钥保护 | 否 |
| `PLAN_JSON_SUFFIX` | 约束规划 JSON、复杂度与 `loop` 选择 | 否 |
| `REACT_LOOP_SUFFIX` | 约束 Think-Act-Observe JSON、工具清单和单轮动作 | 否 |
| `REFLECT_CHECK_SUFFIX` | 约束可选核对只能 `pass` 或 `clarify` | 否 |
| `COMPACT_SYSTEM` | 约束旧对话摘要必须保留目标、资产和未决问题，且不得带敏感信息 | 否 |
| `SKILL_HINTS` | 评测技能的短说明 | 否 |

送入模型的系统上下文通过以下顺序组成：

```text
固定 Persona / 当前阶段后缀
  + 当前 skill_id 对应的 Skill Hint（如有）
  + sessions.compact_summary（如有）
```

这三段不计入“最近 20 条消息”的窗口容量。技能说明只用于当前回合，不把历史技能卡逐一重复注入。

#### 3.1.2 会话记忆与窗口算法

`context.py` 中的 `window_rows()` 是模型窗口唯一算法：

```text
全部 user + assistant 消息（按时间排序）
  → 若存在 compact_keep_from，从该消息起截取
  → 最多保留末尾 20 条
  → 规划与闲聊模型取得 role + content 历史
```

进入该 20 条窗口的只有用户消息和助手“交付句”。规划、复核、工具观察、进度和报告事件不会污染消息窗口；它们保存在 `ws_events`，供前端回放和审计。

`/compact` 的行为如下：

```text
当前窗口 > 6 条
  → 旧消息（不含最近 6 条）调用 COMPACT_SYSTEM 生成 <= 2000 字符摘要
  → 写 sessions.compact_summary
  → compact_keep_from 指向最近 6 条的第一条
  → 历史 messages 与 ws_events 均不删除
```

因此，压缩是“为模型缩短可见上下文”，不是物理删除聊天记录。当前手动 `/compact` 已实现；窗口溢出时的自动压缩仍属后续收口能力，现行算法会保留最后 20 条。

#### 3.1.3 跨会话偏好记忆

跨会话不是自由文本长期记忆，而是受限的用户偏好 JSON：

```json
{
  "last_kind": "benchmark",
  "last_profile_ids": ["..."],
  "last_dataset_id": "...",
  "last_kb_id": null,
  "last_gold_qa_id": null,
  "last_with_stress": false,
  "updated_at": "..."
}
```

其存储键为 `settings.agent_prefs:{user_id}`，仅在确认成功、任务实际入队之后写入。下一轮规划可以将它们作为“可在确认卡中修改”的建议，但仍必须通过本轮 `list` 工具复查资产存在性，不能以偏好绕过 ID 溯源。

#### 3.1.4 临时工作记忆、脱敏与容量度量

ReAct 工具返回会转换为 observation 摘要，进入下一轮的临时输入：工具名、是否成功、耗时、最多 20 个 ID、列表数量/名称或用户可读错误。原始工具数据会：

1. 对 `api_key`、`token`、`password`、`secret`、`cookie` 等键名递归脱敏；
2. 列表最多保留 20 条；
3. 超过 4000 个字符时截为带 `truncated=true` 的预览；
4. 不写入长期消息窗口。

`ContextMeter` 同时展示消息数量、技能标记、摘要标记、窗口余量及估算 Token 用量。项目明确不使用“记忆文件”或向量数据库；对应计数当前固定为零，不能误解为已接入的长期知识记忆。

### 3.2 编排层：Plan-and-Execute

#### 3.2.1 规划产物

规划阶段输出 `PlanArtifact`，其冻结字段如下：

```text
intent       benchmark | rag | testcase | report | cancel | rerun | inspect | compact | chat
skill_id     skill-benchmark | skill-rag | skill-testcase | skill-stress | null
slots        { filled, missing }
tools_needed 内部短工具名单
delivery     confirm | clarify | text | action
budget       { max_tool_rounds }
notes        供思考卡显示的短说明
```

运行时附加、但不进入确认卡 JSON 的字段为：

```text
complexity = low | medium | high
loop       = chat | react | plan_solve
```

自然语言默认先由规划模型产生 `complexity` 与 `loop`；斜杠命令不为此消耗模型调用，而是按产品规则绑定路径。规划 JSON 解析失败会重试一次；上游不可用、超时或再次解析失败时才使用 L0 规则降级，且降级后仍必须经过复核。

#### 3.2.2 TurnMode 路由

```text
自然语言
  Planner loop=chat        → CHAT
  Planner loop=react       → REACT_ONLY
  Planner loop=plan_solve  → PLAN_SOLVE
  Planner 不可用/非法      → 启发式与 L0 回退

斜杠命令
  /help /status /compact /cancel 等     → DIRECT
  /profiles /datasets /kb /report        → REACT_ONLY
  /benchmark /testcase /stress /rerun    → PLAN_SOLVE
```

生图和音色克隆在规划后会被注入对应短工具，并强制使用 `REACT_ONLY`，避免被错误套入评测下单流程。

#### 3.2.3 Plan-and-Solve 的实际流程

评测下单路径不是“模型一口气生成任务 JSON”，而是如下受控编排：

```text
Plan
  → 根据缺失槽位确定工具需求
  → ReAct / 顺序工具队列获取真实资产
  → 将观察结果组装为 proposed_spec
  → 若仍缺槽，最多补规划一次
  → Reflection 规则门禁
  → 规则通过后，可选一次模型目标核对
  → confirm 卡，而非直接创建任务
```

模型调用预算为最多 4 次：首次规划、JSON 重试、补规划、可选核对；ReAct 的工具决策调用独立受工具轮次约束。默认工具轮次为 4，硬上限为 5。

### 3.3 执行层：ReAct、内部 MCP 与 Worker

#### 3.3.1 ReAct 回路

`react.py` 实现的行动阶段遵循以下循环：

```text
输入：用户原文 + PlanArtifact + 临时 observations
  ↓
模型输出 JSON：thought / tool / arguments / done / reply
  ↓
每轮仅执行一个内部短 MCP 工具
  ↓
工具结果写成 ToolCall / ToolResult 事件与 observation
  ↓
下一轮模型依据 observation 决定继续、调整或结束
```

它不使用 OpenAI function calling。模型只能通过受解析器和白名单约束的点分工具名提出动作；每轮至多一个工具，重复调用会被抑制，工具失败会作为观察反馈给下一轮，而不是由模型猜测成功结果。

#### 3.3.2 工具分层

| 类别 | 工具/能力 | 调用主体 | 说明 |
| :--- | :--- | :--- | :--- |
| 内部短 MCP | `model.list`、`dataset.list`、`task.get`、`dispatch.overview`、`report.get` 等 | Agent | 读取、查找、组织确认卡；默认串行 |
| 对话短生成能力 | `image.generate`、`audio.voiceclone` | Agent | 同步受控调用，依然会脱敏、超时和写观察 |
| 写入工具 | `task.create` | Harness 的确认回执路径 | 仅 `confirm_ack.ok=true` 后允许 |
| Worker 长工具 | `benchmark.run`、`rag.evaluate`、`testcase.generate`、`stress.run` | Worker | Agent 进程禁止同步运行 |

`task.create` 在 ReAct 阶段被明确拒绝。Harness 仅创建 `pending_confirm`；确认回执会对卡片 patch 深合并、重新校验、检查会话占槽，并在同一事务中创建 `queued` 任务、清空待确认卡、写审计记录。

#### 3.3.3 任务执行与状态回写

```text
confirm_ack.ok=true
  → tasks.status = queued
  → Worker 以行锁领取 queued 任务，置为 running
  → 执行器更新 task.progress / task_events
  → push_ws 写 progress / report / error 到 ws_events
  → API 连接的后台转发协程增量下发
  → 浏览器按 event_id 展示；重连时补发
```

任务终态受锁保护，避免取消与完成互相覆盖。会话存在 `queued`、`running` 或 `awaiting_case_confirm` 任务时，Harness 不会再发新的确认卡。

### 3.4 反馈层：Reflection（反思/复核）

本项目的 Reflection 不是让模型自由写“经验教训”再注入下一回合，而是以可验证信号为中心的受控复核：

```text
PlanArtifact + ReactArtifact.proposed_spec + known_ids
  ↓
确定性 run_gates（必须先过）
  ↓
可选 maybe_model_check（只能降级为 clarify）
  ↓
pass → confirm；clarify → 追问；reject → 标准错误
```

主要硬门禁包括：

1. 工具只能来自内部短工具白名单，禁止长工具出现在对话执行路径；
2. 禁止执行任意代码、改人设或跳过确认；
3. 一张确认卡只能有一种任务 `kind`，禁止混合 Benchmark 与 RAG；
4. 必填槽位必须完整；Benchmark 的 `profile_ids` 数量必须在 1–5；
5. 资产 ID 必须出现在本轮工具观察的 `known_ids` 中；
6. 会话已有活动任务时，禁止再发确认卡；
7. Agent 对话不能产生 `kind=stress` 确认卡；“先评后压”必须是质量任务的 `with_stress=true`；
8. RAG、报告等未启用路径必须明确返回 `VALIDATION`，不得伪造成功。

规则通过后，`maybe_model_check()` 可调用一次模型确认“任务规格是否真正符合用户目标”。该模型没有放行权：它最多将结果从 `pass` 变成 `clarify`；规则 `reject` 永远不能被模型改写为通过。

---

## 4. 端到端 Loop（闭环链路）

### 4.1 对话到任务的主闭环

```text
┌───────────────┐
│ 用户输入目标   │
└───────┬───────┘
        ▼
┌──────────────────────────────────────────┐
│ 读取：Persona + Skill + Summary + Window  │
│       + 用户偏好 + 本轮附件                │
└───────┬──────────────────────────────────┘
        ▼
┌──────────────────────────────────────────┐
│ Planner：结构化 PlanArtifact              │
│ loop = chat / react / plan_solve          │
└───────┬──────────────────────────────────┘
        ├──────── chat ──────────────────→ 交付句 → 下一轮
        │
        ├──────── react ─────────────────┐
        │                                 │
        └──── plan_solve ───────────────┐ │
                                        ▼ ▼
                             ┌─────────────────────┐
                             │ ReAct: Think-Act-    │
                             │ Observe（≤5 工具轮） │
                             └────────┬────────────┘
                                      ▼
                             ┌─────────────────────┐
                             │ Reflection / Gates   │
                             └───┬────────┬────────┘
                          reject │        │ clarify
                                 ▼        ▼
                               错误     澄清问题 ───→ 用户输入

                                      pass
                                       ▼
                             ┌─────────────────────┐
                             │ pending_confirm 卡   │
                             └────────┬────────────┘
                              cancel  │  confirm_ack
                                     ▼ ▼
                             取消    queued Task
                                          ▼
                                     Worker 执行
                                          ▼
                        progress / report / error 持久化事件
                                          ▼
                              UI 展示、断线重放、后续决策
```

### 4.2 Worker 反馈的外层闭环

Worker 不会反向启动另一轮 Harness。它只改变任务状态并写入可重放事件；用户收到报告或错误后，再发下一条消息，Harness 才开始新的回合：

```text
Worker 结果
  → task.progress / task.status / report
  → task_events + ws_events
  → API 后台转发或重连重放
  → 用户看到进度、报告或错误
  → 用户提出追问、重跑或新任务
  → 新 Harness 回合读取会话窗口与确认成功后的偏好
```

这意味着“执行反馈”是业务闭环的一部分，但不把 Worker 产生的全部进度文本自动塞进模型上下文，避免长任务噪声挤占 20 条对话窗口。

### 4.3 先评后压的任务链

```text
质量评测确认卡（Benchmark；RAG 接入后亦适用）（with_stress=true）
  → 质量评测 queued / running
  → 质量任务 succeeded
  → Worker 派生同会话 stress 子任务
  → stress 执行并产出独立报告
```

质量失败或取消时不派生压测。Agent 对话从不直接构造 `kind=stress` 确认卡，以防绕过“先评后压”的产品约束。

---

## 5. 持久化对象与责任边界

| 对象 | 用途 | 是否进入模型 20 条窗口 |
| :--- | :--- | :--- |
| `sessions` | 会话权限、摘要、窗口游标、待确认卡、可见性 | 摘要按系统侧注入；其余否 |
| `messages` | 用户原文与助手最终交付句 | 是 |
| `ws_events` | 思考、工具、确认、进度、报告、错误的回放与重连 | 否，除本轮 observation 摘要 |
| `tasks` | 排队、执行、状态、配置快照、进度、报告关联 | 否 |
| `task_events` | Worker 生命周期与错误审计 | 否 |
| `reports` | 指标与样本结果 | 否，需通过短工具按需读取 |
| `settings.agent_prefs:{user_id}` | 成功入队后的有限偏好 | 仅作为规划建议 |

会话中的 `pending_confirm` 与 `pending_confirm_author_id` 被持久化，并与确认回执使用行锁处理。这样既支持刷新恢复确认卡，也避免共享会话中协作者替换或确认他人生成的卡片。

---

## 6. 可观测性、可靠性与安全约束

### 6.1 可观测性

- 每次工具调用生成成对的 `tool_call`、`tool_result` 事件，并记录工具耗时。
- 规划、ReAct、复核可通过 `thought.stage` 标识为 `plan`、`react`、`reflect`。
- 模型思考流增量仅实时发送；成功结束后才落 `think_final` 快照，避免事件表无限膨胀。
- Agent 使用 `agent_trace` 记录协议、模型、工具、耗时、错误码；禁止日志中输出密钥、Cookie、密码或完整提示词。
- Worker 通过 `[worker] start/succeeded/failed` 输出最小化运行日志，任务详情与进度在数据库中持久化。

### 6.2 可靠性

- WS 使用短票鉴权，断线通过 `session_id + last_event_id` 补发事件。
- Harness 运行在独立 `asyncio.Task`；收包循环不等待整轮，因此 `/stop` 可以中断回合。
- 每会话通过进程内 registry 防止同时启动多个 Harness 回合；任务表的活动状态约束避免同会话重复占槽。
- Worker 使用 `FOR UPDATE SKIP LOCKED` 领取队列任务，并对终态写入加锁，降低竞争条件。

### 6.3 当前部署前提

Harness 的会话级 abort registry 存在 API 进程内。因此当前实现要求 API 单副本，或网关按 `session_id` 使用粘性路由；若扩为多副本，需要将该状态迁到 Redis 等进程外协调设施。任务、消息和事件本身已持久化在 PostgreSQL，可跨连接恢复。

---

## 7. 当前能力状态与不能误读的边界

| 能力 | 当前状态 | 架构含义 |
| :--- | :--- | :--- |
| Harness 三阶段 | 已实现 | Plan、ReAct、Reflection 均有代码落点与测试 |
| 会话窗口与 `/compact` | 已实现 | 20 条窗口、保留 6 条、摘要与偏好持久化 |
| 内部短 MCP | 部分实现 | 未完成工具必须返回 `VALIDATION`，不允许假成功 |
| Benchmark | Worker 真实执行路径 | 支持异步进度、报告与状态回写 |
| 用例生成 | Worker 真实执行路径 | 生成后可进入 `awaiting_case_confirm` |
| RAG | 对话路径未启用；Worker 防御性失败 | 不 mock `succeeded`，等待 LightRAG 阶段接入 |
| Stress | Worker 骨架 Mock | 入口与任务链存在，真实发压引擎替换属于后续工作 |
| 外部 MCP / 用户自定义系统提示词 | 明确不做 | 防止越权调用与提示词污染 |
| Subagent / 递归 Harness | 明确不做 | 页面 AI 仅同进程调用同一模型，不新建子会话 |
| 记忆文件 / 向量长期记忆 | 明确不做 | 当前只有受限摘要和偏好记忆 |

---

## 8. 关键代码映射

| 文件 | 在 Harness 架构中的职责 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | WS 短票、收包、事件落库、重放、Worker 事件后台转发 |
| `backend/api/app/harness/orchestration/session_runtime.py` | 单回合编排、异步调度、确认卡、确认回执、`/stop` |
| `backend/api/app/agent/persona.py` | 固定 Persona、规划/ReAct/复核/压缩提示词与 Skill Hint |
| `backend/api/app/agent/context.py` | 20 条窗口、摘要压缩、ContextMeter |
| `backend/api/app/agent/plan.py` | PlanArtifact、模型规划、JSON 重试、L0 回退、偏好建议 |
| `backend/api/app/agent/turn_mode.py` | `chat/react/plan_solve` 到 TurnMode 的路由 |
| `backend/api/app/harness/orchestration/react_adapter.py` / `react_loop.py` | 多轮 Think-Act-Observe、工具观察、proposed spec 组装 |
| `backend/api/app/agent/mcp_tools.py` | 短 MCP 白名单、结果截断、敏感信息脱敏、工具执行 |
| `backend/api/app/agent/reflect.py` | 确定性 Gate、可选模型核对、确认卡放行判定 |
| `backend/worker/app/main.py` | 队列轮询、任务领取、执行器分发、状态终结 |
| `backend/worker/app/events.py` | Worker 向会话 `ws_events` 追加进度、报告和错误 |

---

## 9. 架构审查要点

后续修改 Harness 时，应持续验证以下不变量：

1. 任何长任务都不能在 `ws.py` 收包循环或 Harness 线程中同步跑完。
2. `task.create` 只能在 `confirm_ack.ok=true`、卡片 patch 合并后再次校验通过时发生。
3. 模型输出的计划、工具名、资产 ID 都必须经过白名单、解析器和确定性门禁；模型没有最终授权权。
4. Worker 的 `progress`、`report`、`error` 只进入任务/事件链路，不应无节制进入 20 条模型窗口。
5. RAG、压测和未启用短工具不能以 mock 成功掩盖能力缺失。
6. 日志、工具观察、摘要与偏好均不得泄露 API Key、Cookie、密码或令牌。
7. 扩展 API 副本前，必须先将会话级 abort/并发协调从进程内字典迁移到进程外存储。

---

## 10. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness驾驭工程架构说明.md` | 新增 | 汇总项目现行 Harness Engineering 的记忆、编排、执行、反馈与闭环架构；标识真实能力和预留边界 |

---

## 11. V1.1 文档状态校正（2026-08-21）

当前 Agent 已收缩为两项多媒体 MCP，原 V1.0 中涉及资产查询、任务创建、报告读取和评测 Workflow 的“当前实现”描述不再适用。为避免读者将目标架构当成现行能力，本文件头部已增加历史状态提示；运行时事实、术语边界与实现/目标差异请阅读：

- `docs/AI测试与评估平台-Harness运行逻辑与架构校正说明.md`
- `docs/AI测试与评估平台-Agent开发文档.md` §32「最小 MCP 工具内核」与 §33「MCP Server 与 ToolCall 注册表收敛」

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness驾驭工程架构说明.md` | 更新 | 标记 V1.0 为历史目标架构，给出当前能力文档的阅读入口。 |
| `docs/AI测试与评估平台-Harness运行逻辑与架构校正说明.md` | 新增 | 以现行最小内核校正提示词、上下文、记忆、ReAct 与反馈层概念。 |

## 12. V1.2 当前入口同步（2026-08-22）

旧 `agent/harness.py` 与 `agent/react.py` 已删除，当前 WS 路由直接使用 `harness/orchestration/session_runtime.py`，ReAct 产品适配位于 `react_adapter.py`。该项只收口内部双轨，不恢复本文 V1.0 中已标记为历史目标的业务 MCP，也不改变 API 契约。

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness驾驭工程架构说明.md` | 更新 | 将代码映射同步为当前新 Harness 编排入口。 |
