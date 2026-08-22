# AI 测试与评估平台 — Agent 独立开发说明书

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Agent 独立开发说明书 |
| 版本 | V1.14 |
| 日期 | 2026-08-22 |
| 最近修订 | 2026-08-22：V1.14 删除旧 Agent Context 入口，规划历史、计量、会话存储和模型压缩按六层唯一归属；V1.13 删除旧 Agent Plan 入口，规划能力迁入六层编排；V1.12 删除旧 Agent Harness / ReAct 入口，WS 直连六层编排总控；自然语言按 CoT 同一轮逐步推理再出结果；不再先打规划 JSON 判定 loop。断线取消只停本轮生成。 |
| 用法 | **实现 `/agent` 以本文为准（Harness / 斜杠 / 窗口算法）。** REST/WS JSON 以 API.md V1.6 为准。完成某项后勾选文末 Task，并在「最近修订」追加一行。 |

本文是评测平台 **Agent 子系统** 的完整开发说明书：目标、边界、运行时骨架、协议、模块、代码落点与验收任务都写在这里。与 PRD / API.md 冲突时，字段名与事件名以那两份为准；Harness、斜杠、上下文算法以本文 §16 为准。§4.6 所列增量已收入 **API.md V1.6**。

---

## 1. 这份文档解决什么

平台主入口是对话智能体：成员用自然语言或 `/` 命令说明要评什么，Agent 澄清并组出确认卡，用户确认后任务入队，由 Worker 异步执行评测 / 用例 / RAG / 压测。Agent **不在对话进程里跑完长任务**。

要做成的体验：

1. 接入平台指定的大模型；思考过程可见；回复渲染 Markdown；Mermaid 与数学公式为明确后补渲染层。思考强度无滑杆，由 Harness 内部档位决定。  
2. 会话可刷新、可断线续上；思考、工具、技能徽标、ToolCall 卡、确认卡都能回放；V1.6 增加思考快照、确认回执、压缩摘要与持久化 `message` 事件。
3. 只能调内部短工具；四种评测技能内置。Subagent / 通用工作流不做产品，但预留调用边界。  
4. 每个会话有上下文窗口、可压缩（`/compact`）；界面实时拆开 **消息 / 技能 / 摘要 / 余量**；本产品无记忆文件段。  
5. **自然语言走 CoT**：同一轮流式先逐步推理（`reasoning_content` → 思考卡），再给出 reply 或调用短工具。禁止先打规划 JSON 分类、再二次闲聊生成。斜杠会话控制仍 0 次模型。  
6. 工作方式对齐「先评后压」；其它页面 AI 逐页预留（数据集、用例、任务诊断、报告解读、压测建议）。  
7. 输入框 `/`：上区系统 15 条，下区团队自定义模板（可添加，不能改人设、不能跳过确认卡）。  
8. 思考卡 / 工具卡展示模型与工具耗时；生成中提示当前阶段（规划中 / 调用工具 / 复核中）。  
9. 长任务只入队给 Worker：不阻塞对话、占槽可聊不可再下单、进度节流、`/stop` 与 `/cancel` 分流。

---

## 2. 产品边界（做 / 不做）

| 做 | 不做 |
| :--- | :--- |
| 多会话；会话内长任务串行（含压测子任务占同一槽） | 用户自选 Ask/Plan/Bypass、思考强度滑杆、切模型 |
| 管理员指定 **一个** Agent 协议档 | 外部 MCP、用户改系统提示词、上传自定义 Skill |
| 确认卡未确认不得入队 | 跳过确认卡直接 `task.create` |
| 内部短工具 + 四技能包 | Subagent 产品、通用工作流引擎、任意代码执行 |
| 窗口 20 条 + 手动 `/compact` + `n/20` | Cursor 式记忆文件 / 记忆面板 |
| 斜杠 15 条系统命令 | `/prompt` `/mcp` `/bash` `/bypass` |
| 其它页 REST 短调用同一模型 | 页面失败时用假数据冒充成功 |

一单任务只能是 `benchmark` / `rag` / `testcase` / `stress` 之一。Benchmark 与 RAG 要两份报告就下两单。质量失败或取消不派生压测。

---

## 3. 架构总览

```text
成员浏览器  /agent
  会话列表 | 对话流 | 斜杠面板 | 上下文 n/20 | 进度坞
        │
        │  Cookie 登录
        │  POST /api/sessions
        │  POST /api/files          → file_id
        │  POST /api/auth/ws-ticket → 5 分钟短票
        │  GET  /ws/agent?ticket=&session_id=&last_event_id=
        ▼
API 容器（Agent Host）
  传输层     短票、心跳、事件落库、断线补发
  Harness    规划 → ReAct（短工具）→ Reflection
  人设/窗口  系统提示词不可变；最近 20 条 + 压缩摘要
  短 MCP     model.list / task.get / task.create / task.cancel …
        │
        │  仅当用户 confirm_ack.ok = true
        ▼
PostgreSQL   tasks.status = queued
        ▼
Worker 容器  长任务（评测、用例、RAG、下发压测）
        │  回写 progress / report / error 到同一会话事件表
        ▼
浏览器       进度坞、报告卡
```

其它页面（数据集 AI 生成、用例 AI 生成 / 补全）走 REST，调用同一套 Agent 协议档，**不走 WebSocket**。生成结果只是候选，用户采纳后才写库。

---

## 4. 对外协议（写进本文，实现按此）

### 4.1 WebSocket

1. 登录后 `POST /api/auth/ws-ticket`，再用短票升级 `GET /ws/agent?ticket=`。禁止长期 JWT 放进 query。  
2. 心跳 30s（传输层 ping/pong）。应用层服务端可发 `pong`。前端不发 JSON `ping`。  
3. 重连必须带 `session_id` + `last_event_id`，服务端补发 `event_id` 更大的事件。  
4. 前端**先** `POST /api/sessions` 再带 `session_id` 连接。无 `session_id` 时服务端可建空会话（兼容），`/new` 与会话列表仍以 REST 为准。  
5. 关闭码冻结：短票非法/过期 `4401`；会话不存在、已软删除或当前成员无权访问 `4404`；正常断开 `1000`。收到 `4404` 后前端停止重连旧会话并回到列表。

**服务端 → 前端（事件名冻结；V1.6 允许 `message`、`confirm_ack` 与 `think_final` 快照）**

公共头：`event` `session_id` `task_id?` `event_id` `ts` `payload`。

| event | payload | 界面 |
| :--- | :--- | :--- |
| `thought` | `{ text, latency_ms?, stage?, skill_id? }`；流式 `chunk`/`think` 为瞬态，成功结束补 `stream=think_final` 快照 | 思考卡；阶段/技能和完整推理快照可历史回放 |
| `message` | `{ id, role:"user", content, attachments, author_id, author, client_message_id?, created_at }` | 用户气泡；落库并占 event_id，协作者按 id/幂等键去重 |
| `tool_call` | `{ name, arguments }` | 工具卡 pending |
| `tool_result` | `{ name, ok, data\|error, latency_ms? }` | 工具卡完成 |
| `confirm` | 确认卡 JSON（§4.2）+ `confirm_author` 元数据 | 确认卡，只有发起人可 ack |
| `confirm_ack` | `{ ok, task_id? }` | 确认/取消结果；落库并供协作者回放 |
| `progress` | `{ percent?, done, total, message }` | 进度坞，仅这四字段 |
| `report` | `{ report_id }` | 报告卡 |
| `error` | `{ code, message }` | 错误条 + Toast |
| `pong` | `{}` | 不渲染 |

禁止发明 `thinking` `token` `plan` `reflect` `assistant` 等事件。规划句、复核句都放进 `thought.text`（可用「规划」「复核」作正文前缀）。

共享会话中，`thought.stream="chunk"` 只向同会话在线成员广播，`think` 原始推理流只给本轮发起连接；两类增量均不落库、不占 event_id，成功结束的 `think_final` 快照落库，断线可恢复完整思考卡。当前是单 API 副本的进程内 Hub，扩为多副本必须换成 Redis Pub/Sub 等进程外广播。

**前端 → 服务端（仅三条）**

```json
{ "event": "user_message", "payload": { "text": "/benchmark 对比两模型", "attachments": [{ "file_id": "uuid" }], "client_message_id": "browser-uuid" } }
{ "event": "confirm_ack", "payload": { "ok": true, "patch": { "with_stress": false } } }
{ "event": "cancel_task", "payload": { "task_id": "uuid" } }
```

斜杠、芯片、普通打字全部走 `user_message`。`ok=false` 不入队。`ok=true` 时 `patch` 与原卡深合并，校验通过才创建任务。同一会话同一时刻最多一张待确认卡。`client_message_id` 用于浏览器重连重发幂等和本地乐观气泡去重。

### 4.2 确认卡（= `POST /api/tasks` 的 body）

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| `kind` | 是 | `benchmark` / `rag` / `testcase` / `stress` |
| `profile_ids[]` | benchmark | 1–5 个被测协议档 |
| `dataset_id` | benchmark | 数据集 |
| `kb_id` + `gold_qa_id` | rag | 内置或外挂都要黄金 QA |
| `rag_mode` | rag 且 LightRAG | 1–4 个，默认 `["hybrid"]` |
| `run` | 评测 | sample_size / concurrency / timeout_s / retry / temperature / max_tokens / system_prompt / k / use_judge；默认见 §16.1 |
| `with_stress` | benchmark、rag | 默认 false；true 则质量成功后自动压测 |
| `stress` | with_stress 时 | env、qps、duration_s；`sla_p99_ms` 默认 `null`（未填不出达标） |
| `case_source` | testcase | `{file_id}` 或 `{text}` |
| `parent_task_id` | 仅人手 `kind=stress` | Agent **不**走这条；`/stress` 仍出质量任务卡 |

Agent 对话不得发出 `kind=stress` 确认卡。压测由质量任务 `succeeded` 且 `with_stress=true` 时 Worker 派生。`prod` + 压测需会签后才能 running。

### 4.3 短工具（Agent 只调这些；长任务给 Worker）

| 名称 | 工具卡标题 | 阶段 |
| :--- | :--- | :--- |
| `model.list` | 列出协议档 | 先做 |
| `task.get` | 查询任务 | 先做 |
| `task.create` | 创建任务 | 仅 ack 后 |
| `task.cancel` | 取消任务 | 先做 |
| `dispatch.overview` | 调度概览 | 迷你轨只读 |
| `dataset.list` | 列出数据集 | 数据集页打通后 |
| `report.get` | 读取报告 | 报告打通后 |
| `kb.list` | 列出知识库 | RAG 阶段 |
| `testcase.confirm` | 确认用例入库 | 用例阶段 |
| `audio.speech_recognition` | 语音识别转写 | 对话同步 |
| `audio.speech_synthesis` | 语音合成 | 对话同步 |
| `audio.voiceclone` | 音色克隆配音 | 对话同步 |
| `image.generate` | Qwen Image 文本或参考图生图 | 对话同步 |

Worker 专用（Agent 进程禁止跑完）：`benchmark.run` `rag.evaluate` `testcase.generate` `stress.run`。

### 4.4 错误码（对外只这十个）

`UNAUTHORIZED` `VALIDATION` `NOT_FOUND` `BUDGET_EXCEEDED` `CONCURRENCY` `WHITELIST` `NEED_APPROVAL` `UPSTREAM` `TIMEOUT` `INTERNAL`。  
`INTERNAL` 不把堆栈给浏览器。未到阶段的能力：明确「未启用」，禁止假成功。

### 4.5 会话 REST

- `GET/POST /api/sessions`：新会话默认 `private`；`team` 表示当前内部团队的正常成员均可读写；
- `PUT /api/sessions/{id}/sharing`：仅 owner，在 `private` / `team` 间切换；收回共享时立即关闭协作者 WS；
- `DELETE /api/sessions/{id}`：仅 owner，软删除；存在生成、待确认卡或非终态任务时返回 `VALIDATION`；
- `GET /api/sessions/{id}/messages` 返回 `messages`、`events`，以及增量字段 `pending_confirm`、`pending_confirm_author_id`、`compact_summary`、`context_meter`（§4.6）。

`messages`：用户原文及其 `author_id` / `client_message_id`，以及 **交付句**（见下）。`ws_events`：用户 `message`、思考、工具、确认、进度、报告（规划/复核 thought 也在这里）。会话 owner 不因协作者发言改变。

**哪些 thought 写入 `messages.role=assistant`（冻结）**

| 写入 messages | 只发 `thought` 事件、不落 messages |
| :--- | :--- |
| 澄清问句、闲聊回复 | 规划短句（`notes`，可带「规划」前缀） |
| 「已入队」 | 复核短句（可带「复核」前缀） |
| 「已压缩 n→m」/「无需压缩」 | 阶段提示、技能徽标所在 thought |
| 「已停止生成」及 `/status` `/help` 等只读摘要 | 工具观察（工具卡走 events） |
| 用户可见的错误说明（可同时发 `error`） | `progress`（永不进 messages） |

同一句交付文本：先 `_emit thought`，再 `INSERT messages`，正文相同。刷新：对话气泡来自 `messages`，思考/工具/确认卡来自 `events`。禁止把规划+复核+已入队三条都当 assistant 消息（否则约 5 个下单回合就满 20）。

### 4.6 相对 API.md 的增量（**已回写 API.md V1.6**）

下列内容以 **API.md V1.6** 为接口真理；本文保留摘要便于实现 Harness。禁止另搞第二套路径。

| 增量 | 形状 |
| :--- | :--- |
| `thought.payload` 可选 | `latency_ms` `stage` `skill_id`（旧前端忽略） |
| `tool_result.payload` 可选 | `latency_ms` |
| `GET /api/agent/prefs` | 只读；ack 成功后服务端写；无 PUT |
| `GET/POST/DELETE /api/slash-commands` | 自定义斜杠；M1 未做完则 `VALIDATION`「自定义命令未启用」 |
| 列 `sessions.compact_summary` | TEXT 可空 |
| 列 `sessions.compact_keep_from` | 消息 id 可空，窗口游标，见 §16.6 |
| 列 `sessions.pending_confirm` | JSONB 可空 |
| 列 `sessions.pending_confirm_author_id` | 确认卡作者；团队协作时只允许该成员 ack |
| 列 `sessions.visibility` / `deleted_at` | 默认私有、可团队共享、软删除不物理清历史 |
| 列 `messages.author_id` / `client_message_id` | 用户发言人、浏览器幂等与协作者实时去重 |
| `GET .../messages` 增补 | `author`、`pending_confirm_author_id`、`context_meter` |
| `GET .../messages` 历史恢复 | `compact_summary`；events 中的 `think_final`、`confirm_ack` 与 tool/skill 事件均可回放 |

`context_meter`：`{ "messages", "skills", "summary", "headroom", "window": 20, "mcp_tools_count", "mcp_tools_max" }`，并可带 token 级扩展字段。`skills` 与 MCP 计数从持久化事件恢复；刷新必须用服务端数字，禁止前端按 messages 表总条数自己减。

---

## 5. Harness Engineering（自然语言 CoT 一步一步出结果）

这是运行时骨架，不是界面上的三种模式。模型只负责填结构化产物；**能不能出确认卡、能不能建任务，由门禁决定**。

ReAct（Yao 2022）与 Plan-and-Solve（Wang 2023）是同一根轴：下一步依赖观察 → 偏 ReAct；步骤结构事先清楚 → 偏 Plan-and-Solve（失败再补规划）。Reflection（Shinn 2023）是外层，只在有可验证信号时启用；本产品的真信号是确认卡门禁，不是每回合都调核对模型。

**自然语言（CoT）**：不调用独立规划模型。`run_plan` 只给 ReAct 种子（`intent=chat`、`loop=react`），生图/配音仍可由 inject 挂工具。随后同一轮 `stream_mcp_step` 把思考链增量推到 `thought.stream=think`，步骤完成后再解析 JSON 的 `reply`/`tool`。`loop`/`complexity` 不进冻结 `PlanArtifact.as_dict()`。

**斜杠**：仍 0 次模型，由产品绑定循环（`/help`→DIRECT，`/profiles`→REACT_ONLY，`/benchmark`→PLAN_SOLVE）。

**L0 回退**：仅当规划失败或模型没给合法 `loop` 时，才用关键词表。

**安全网**：inject 之后若 `tools_needed` 含 `audio.speech_recognition` / `audio.speech_synthesis` / `audio.voiceclone` / `image.generate`，强制 `REACT_ONLY`（覆盖模型误选的 plan_solve）。

WS 事件名仍冻结为 `thought` / `tool_call` / `tool_result` / `confirm` / `error`。长任务不得在对话循环执行。

### 5.1 产物形状（路径可跳，字段不可乱编）

**规划**

- `intent`：`benchmark | rag | testcase | report | cancel | rerun | inspect | compact | chat`（**无**独立 `stress` intent）  
- `skill_id`：四技能之一或空；`/stress` 用 `skill-stress` 但 `intent` 仍是 `benchmark` 或 `rag`  
- `slots.filled` / `slots.missing`：键名必须是确认卡字段  
- `tools_needed[]`：只能是 §4.3 短工具  
- `delivery`：`confirm | clarify | text | action`  
- `budget.max_tool_rounds`：默认 4，硬顶 5  
- `notes`：写入思考卡的规划短句  

**行动**：每轮工具的 name、ok、摘要、`latency_ms`；可选 `proposed_spec`。  
**复核**：`verdict = pass | clarify | reject`，`reasons[]`，通过后的 `spec`。

### 5.2 何时跳过哪一段

| TurnMode | 判定 | 规划模型 | ReAct 决策模型 | 规划/复核思考卡 | 核对模型 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| DIRECT | `/stop` `/compact` | 斜杠模板 0 次 | 否 | 否 | 否 |
| CHAT | 已并入 REACT_ONLY，不再二次闲聊生成 | — | — | — | — |
| REACT_ONLY | 全部自然语言 | 0 次规划 | 是：流式思考链 → 工具或 reply | 否 | 否 |
| PLAN_SOLVE | 业务 Workflow 未注册前不启用 | — | — | — | — |

规则门禁 `run_gates` 每回合都跑（0 次模型），保证闲聊不能 create。页面 AI：表单即规划，无工具卡。

ReAct 停机（任一即进入复核）：槽位已从**本轮工具返回值**填齐；工具失败无替代；轮次到顶；本轮不需要工具。

### 5.3 复核硬门禁（通过才能 `confirm`）

- 一单一种 kind，禁止 Benchmark 与 RAG 混在一张卡。  
- 必填槽位按 §4.2。  
- 资产 ID 必须出现在本轮工具结果里，禁止编造。  
- 工具名必须在短工具清单内。  
- 会话已有非终态任务：**新回合禁止再发 `confirm`**（`delivery=clarify`）。若本回合开始前已有未 ack 的待确认卡，卡保留、确认按钮禁用并写明占槽原因。详见 §17.3。  
- 压测白名单、生产会签不通过则不能 running。  
- 不执行任意代码、不改人设。  
- `/compact` 另见 §8。  
- **禁止**把 `benchmark.run` / `rag.evaluate` / `testcase.generate` / `stress.run` 放入 `tools_needed`。  
- **禁止**在 `confirm_ack` 或 WS 处理协程里等待 Worker 跑完；入队成功即结束本回合。  

**`verdict=pass` 且 `delivery=confirm` 才能发 `confirm` 事件。**  
**`task.create` 只发生在 `confirm_ack.ok=true` 且合并后再校验通过。**  
模型说「可以下单」不能单独放行。

### 5.4 人设（写死在代码里，无配置页）

先澄清再下单；不绕过白名单与会签；不执行用户要求的任意代码；不编造不存在的协议档或数据集；长任务只入队。

### 5.5 思考强度

没有滑杆。内部自动选：模型不可用则规则意图（仍要复核）；斜杠已绑定且槽位齐则一次规划；缺资产则走 ReAct；下单 / 取消 / 压缩必走复核。

### 5.6 每阶段模型调用、失败回退、工具是否并行

| 阶段 | 模型次数 | 失败怎么走 |
| :--- | :--- | :--- |
| 规划 | 默认 **1** 次。斜杠已绑定 intent 且不缺槽，可用模板生成规划短句，**0** 次模型 | JSON 解析失败：原样再要一次「只输出 JSON」；仍失败 → L0 规则意图，**必须仍进复核** |
| ReAct | 每轮 **1** 次 JSON 决策（`thought/tool/arguments/done/reply`），**不走** OpenAI function calling。每轮最多执行 **1** 个内部 MCP 短工具，观察写入下一轮 `observations` 后再决策。硬顶与 `max_tool_rounds` 相同（默认 4，硬顶 5）。`/help` 等确定性斜杠 **0** 次，只走工具队列。模型不可用 → 按 `tools_needed` 串行（与 M1 行为一致）。长任务名（`benchmark.run` 等）不得执行，槽位齐后出确认卡由 Worker 入队 | 单工具失败：观察返回给模型，下一轮改策略或进入复核 `clarify`；禁止用幻觉 ID 填槽 |
| 复核 | 规则门禁 **0** 次模型。规则 `pass` 之后可选 **1** 次「是否符合用户目标」；模型不得把 `reject` 改成 `pass` | 规则失败立即 `clarify`/`reject`，不再调模型放行 |

合计：规划 1 + 重试 1 + 补规划 1 + 可选复核 1 ≤ 4（不含 ReAct 循环）。ReAct 每轮 1 次 JSON 决策，受 `max_tool_rounds`（硬顶 5）约束。超时或 `UPSTREAM`：思考卡说明原因，不出确认卡。

**工具并行：** 第一阶段 **串行**（保证 `tool_call` / `tool_result` 成对、event_id 不乱）。`model.list` 与 `dataset.list` 互相无依赖时，预留并行开关 `harness.parallel_readonly_tools`，默认关。写工具（`task.create` / `task.cancel`）永远串行，且 create 只在 ack 后。

### 5.7 进行中的阶段提示（前端）

生成中 pill / 状态条只反映 Harness 当前阶段，不新开 WS 事件。由已收到的卡片推断，或 `thought.payload.stage` 可选字段（`plan | react | reflect`，旧前端忽略）：

| 阶段 | 文案 |
| :--- | :--- |
| 规划 | 规划中 |
| ReAct | 调用「列出协议档」等中文名 |
| 复核 | 复核中 |
| 已交付确认卡 | 等待确认 |
| 已入队 | 沿用进度坞 |

### 5.8 Subagent 与工作流的预留边界

| 概念 | 本产品落地 | 预留、禁止写成产品的 |
| :--- | :--- | :--- |
| Subagent | 页面 AI = 同进程 `call_agent_model`，**不**新建 session、不挂 WS | 禁止对话里再开子会话、禁止递归 Harness |
| Workflow | Harness 三阶段 + 确认卡 + Worker 队列就是工作流 | 禁止引入独立工作流引擎；预留钩子名：`after_reflect`、`after_ack`（代码注释级，无 UI） |

---

## 6. 大模型接入与耗时

- 设置项 `agent_profile_id` 指向唯一协议档（OpenAI Chat / Responses / Anthropic Messages）。  
- Key 加密存储，接口不回显。未配置时思考卡说明去协议档页，不出确认卡。  
- 输入栏只读：`Agent · {模型名}`。  
- 同步短调用，超时约 90s（含思考链）；失败归为 `UPSTREAM` / `TIMEOUT`。  
- 对话走 ReAct 同一轮流式 CoT：推理链 `thought.stream=think`（瞬态），成功结束补 `think_final` 落库。不再先打规划 JSON。核对 JSON 仍非流式，mimo 关闭思考以免正文被挤空。

**耗时三层（payload 可选字段，旧前端忽略即可）：**

| 层 | 显示 | 来源 |
| :--- | :--- | :--- |
| 模型 | 思考卡旁 `1.2s` | 协议档调用耗时 |
| 工具 | 工具卡旁 | 该次短工具 |
| 本轮 | 生成中提示 / 回合结束 | 从发出用户消息到本次交付 |

长任务进度只走 `progress`，不要和模型耗时混在一张卡。

---

## 7. 界面：卡片、Markdown、斜杠

页面结构：左会话列表（可折叠）→ 对话列（最大约 760px）→ 可选调度侧轨。底部：进度坞贴在输入框上方。

| 元素 | 来源 | 要点 |
| :--- | :--- | :--- |
| 用户气泡 | messages / 本地发送 | 附件芯片 |
| 思考卡 | `thought` | 标题「思考」；结束收起；可显示耗时；规划阶段在卡头加 **技能徽标** |
| 技能徽标 | `thought.skill_id` 或规划结果 | 文案如「技能 · 基准对比」。**不单开事件、不单独一张大卡**。无 skill 时不显示 |
| 工具卡 | tool_call / tool_result | 第一行中文名；副标题固定 **「MCP · 短工具」**；默认折叠 JSON |
| 确认卡 | `confirm` | 在对话流内，不是弹窗 |
| 报告卡 | `report` | 跳转报告页 |
| 错误条 | `error` | 十码中文 |
| 进度坞 | `progress` | 评测取消 vs 压测立即停，文案不同 |
| 阶段 pill | 由 thought.stage / 工具卡推断 | 规划中 / 调用某某 / 复核中 |
| Markdown | 助手较长文本与较长 thought | 消毒 XSS；围栏代码 |
| Mermaid | ` ```mermaid ` | **明确后补**：报告结构、先评后压示意；失败显示源码，不阻塞对话 |
| 数学公式 | `$...$` / `$$...$$`（KaTeX） | **明确后补**：报告解读、指标说明；未加载库时原文显示 |

回放：`events` 里的 thought 带 `skill_id` 则技能徽标仍在；工具卡仍标 MCP。没有独立 `skill` / `mcp` 事件名。

**不要：** 欢迎页套其它产品名、Ask/Plan/Bypass、模型下拉、外部 MCP 齿轮、每条工具再弹「是否允许执行」、把技能做成用户可编辑 SKILL.md。危险下单只靠确认卡 + 白名单 + 会签。

空会话一句说明 + 最多 4 个芯片。芯片与斜杠共用命令表：生成用例、基准评测、RAG 评测、先评后压。点击只预填，仍要澄清和确认卡。

live 环境禁止「模拟失败 / 模拟断线」和写死的种子协议档、数据集。断线只反映真实 WebSocket 状态。

---

## 8. 上下文、压缩、跨会话记忆

**送给模型的窗口（最多 20 条消息，人设始终在、不占这 20 条）：**

| 段 | 计入 20 条？ | 说明 |
| :--- | :--- | :--- |
| 人设 | 否 | `persona.py`，不可变 |
| 技能说明 Skills | 否 | 当前 `skill_id` 的短说明，系统注入 |
| 压缩摘要 | 否（整段当 1 条系统侧记忆） | `sessions.compact_summary` |
| 消息 Messages | 是 | 仅窗口内的 user + **交付句** assistant；算法见 §16.6，不是表内全部历史 |
| 本轮工具观察 | 否（拼在本轮 user 后） | ReAct 摘要，避免把整份 list 结果塞满窗口 |
| 余量 | — | `headroom = 20 − M`。**`/20` 只约束消息窗口**；技能、摘要是 0/1 标志，不占这 20，四段加总不必等于 20 |
| 记忆文件 | **不使用** | 界面该段固定文案「本产品无记忆文件」 |

### 8.1 实时显示（ContextMeter）

ChatHead 右侧（或输入框上方）常驻，压缩或新消息后立刻更新：

```text
上下文  消息 8  · 技能 1  · 摘要 0  · 余量 12  / 20
记忆文件  未启用
```

- 点击展开四段字数/条数，便于核对「模型实际吃到什么」。  
- 无 compact 时摘要显示 0。  
- 无当前技能时技能显示 0（刷新后无进行中规划，技能为 0；历史徽标看 events）。  
- `/20` 只表示消息窗口容量，不要把技能+摘要加进分母。  
- **不要**做成可编辑的记忆面板。  
- 数字以 `GET .../messages` 的 `context_meter` 为准。

### `/compact`

主动把较旧对话收成摘要，避免只能丢掉最旧消息。

复核（压缩也必须过）：

- 不覆盖人设  
- 不丢待确认卡、活动任务、事件游标  
- 最近 **6** 条原文保留（`KEEP_RECENT`，见 §16.6）  
- 摘要不含 Key / Cookie  
- **不删除**历史消息和事件（刷新仍能看见当时的卡）  
- 写入 `compact_keep_from`，之后 `M` 只从该游标算起（再 cap 20）  

交付：一条思考「已压缩，窗口 n → m」，ContextMeter 四段数字一起更新。可用同一函数做「窗口将满自动压缩」，自动时也要出思考卡，禁止静默丢掉。

### 8.2 跨会话偏好记忆（不是记忆文件）

长期「记得上次评什么」用偏好 JSON，平台事实仍用短工具现查。

**存储：** `settings` 键 `agent_prefs:{user_id}`（单团队、全员同权；不要做记忆编辑器）。值：

```json
{
  "last_kind": "benchmark",
  "last_profile_ids": ["uuid"],
  "last_dataset_id": "uuid",
  "last_kb_id": null,
  "last_gold_qa_id": null,
  "last_with_stress": false,
  "updated_at": "2026-08-19T12:00:00Z"
}
```

**写入时机：** `confirm_ack.ok=true` 且任务已入队之后。取消确认、闲聊、`/compact` 不写。

**规划如何用：** `slots.missing` 且用户没点名资产时，用偏好当**建议值**填进确认卡，思考卡写一句「沿用你上次的协议档，可在卡上改」。用户改卡以卡为准。资产已删除则当缺失，走 ReAct 再 list。

**预留（不进第一阶段）：** 新会话注入「最近一次成功任务的确认卡摘要」只读一行。仍禁止用户编辑记忆文件、禁止用偏好覆盖人设或绕过白名单。

---

## 9. 斜杠命令（系统必带 15 条）

输入 `/` 弹出面板：分组、可搜索；未交付的命令可见但灰置并写原因。发送仍是 `user_message`，例如 `/benchmark smoke-20`。参数只作规划提示，前端不直接拼确认卡 JSON。

不内置（与其它命令重复或越权）：`/compare` `/modes` `/judge` `/commands` `/dispatch` `/prompt` `/memory` `/mcp` `/bash` `/bypass`。

### 9.1 下单（必须出确认卡）

| 命令 | 含义 |
| :--- | :--- |
| `/benchmark` | 基准评测 |
| `/rag` | RAG 评测（阶段未到则灰置） |
| `/testcase` | 生成用例，可带附件 |
| `/stress` | 先评后压：`with_stress=true` 的 **benchmark 或 rag** 确认卡；`skill_id=skill-stress`；**禁止** `kind=stress` |

### 9.2 控制

| 命令 | 含义 |
| :--- | :--- |
| `/cancel` | 取消本会话非终态任务（界面仍先确认对话框） |
| `/rerun` | 拷贝最近任务配置 → **新确认卡**，不直接入队 |
| `/stop` | 只停本轮生成，不动已入队任务 |
| `/new` | 新建空会话 |
| `/compact` | 压缩本会话模型窗口 |

### 9.3 只读（不出确认卡）

| 命令 | 含义 |
| :--- | :--- |
| `/status` | 当前占槽 / 活动任务 |
| `/profiles` | 列出协议档 |
| `/datasets` | 列出数据集（未打通则提示去数据集页） |
| `/kb` | 列出知识库（未打通则灰置） |
| `/report` | 读取已有报告；对话解读后补 |

### 9.4 系统

| 命令 | 含义 |
| :--- | :--- |
| `/help` | 只列出**当前已启用**的命令 |

日后自定义命令：仅模板展开成自然语言，然后走同一 Harness。不能加新工具、不能改人设、不能跳过确认卡。

### 9.5 自定义斜杠（系统区分、可添加）

输入 `/` 面板：**上区系统必带（只读、不可删）**，**下区「我的命令」**。

| 项 | 规定 |
| :--- | :--- |
| 谁可添加 | 任一成员（全员同权）；改删仅创建者可操作，系统命令不可改 |
| 存在哪 | 只经 §16.5 REST；服务端可落在 settings 内部键，浏览器不直接 PUT settings |
| 字段 | `{ id, name, hint, template, created_by, created_at }`；`name` 仅 `^[A-Za-z][A-Za-z0-9_-]{0,31}$`，禁止中文命令名、禁止与系统命令重名。选中后展开的是 `template` 自然语言，不会变成 `/中文` |
| 添加 UI | 面板底部「添加命令」。**冻结接口**见 §16.5，只用 `GET/POST/DELETE /api/slash-commands`，不再写入整份 admin settings |
| 展开 | 用户选中后把 `template` 填进输入框，可再改，发送仍是 `user_message` |
| 禁用 | `name` 与系统冲突、`template` 含改人设/跳过确认的指令 → `VALIDATION`，不保存 |

未做自定义接口前：下区显示「自定义命令未启用」，禁止用本地 localStorage 冒充已保存。

---

## 10. 四技能、平台工作流、其它页 AI

| 技能 | 对应 kind | 规划时要齐的要点 | 技能徽标文案 |
| :--- | :--- | :--- | :--- |
| 基准对比 | `benchmark` | 1–5 协议档、数据集、运行参数、是否压测 | 技能 · 基准对比 |
| RAG 评估 | `rag` | 知识库、黄金 QA、检索模式 | 技能 · RAG 评估 |
| 用例生成 | `testcase` | 附件或粘贴文本；六策略由 Worker 做 | 技能 · 用例生成 |
| 共享压测 | 质量任务勾选压测 | 继承父任务目标；生产会签 | 技能 · 先评后压 |

典型路径：说话或斜杠 → 规划思考（带技能徽标）→ MCP 工具卡 → 复核思考 → 确认卡 → 用户确认 → 入队 → 进度 → 报告。勾选压测且质量成功后，系统建压测子任务并占用该会话槽。

### 10.1 页面智能生成（逐页预留，同一人设、同一协议档）

原则：**只返回候选；用户采纳后才写库。禁止页面自己编造成功数据。不走 WS、不开 Subagent。**

| 页面 | 前端 | 后端 | 行为 |
| :--- | :--- | :--- | :--- |
| 数据集 | `Datasets.vue` | `POST /api/datasets/ai-generate`（`datasets.py` + `llm.py`） | 合成/补全行；采纳后再 PUT rows |
| 用例 | `Cases.vue` | `POST /api/case-sets/ai-generate`、`/{id}/ai-fill`（`cases.py`） | 候选用例/字段；已 `confirmed` 拒绝补全 |
| 用例映射 | `Cases.vue` | `POST .../map` | **不是**模型生成；规则映射，缺字段进待补全 |
| 任务中心 | `Tasks.vue` | `GET /api/tasks/summary` 的 `diagnosis[]` | **只展示服务端聚合**。前端禁止「AI 诊断」本地编造 |
| 报告 | `Report.vue` / 对话 `/report` | 解读走 Agent `report.get` + 评测技能；F-AGT-08 | 只读已有 `report_id`，不重跑 |
| 压测治理 | `AdminStress.vue` | 预留建议接口；无则能力未启用 | 「采纳推荐」只回填表单，点保存才落库 |
| 调度 | `Dispatch.vue` | `dispatch.overview` | 只读观测，无生成 |
| 协议档 | `AdminProfiles.vue` | `POST .../check` | 连通性，不是生成 |

页面调用与对话规划共用 `persona.py` 约束（不执行任意代码、不泄 Key）。超时与错误码同 §4.4。  

---

## 11. 代码落点

在现有文件上改，抽模块，不要整文件推倒重写。

**现有**

| 路径 | 负责 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | 连接、落库、发事件；业务应逐步交给 Harness |
| `backend/api/app/llm.py` | 三协议调用；已返回 `latency_ms`（WS 事件与卡片展示仍见 AGT-LLM-02） |
| `backend/api/app/routers/sessions.py` | 会话与回放 |
| `backend/api/app/routers/mcp.py` | 短工具清单 |
| `backend/api/app/routers/tasks.py` | REST 下单 / 取消 / 重跑 |
| `backend/api/app/models.py` | 会话、消息、事件、任务 |
| `backend/worker/app/main.py` | 长任务；第一阶段可空跑但必须写进度事件 |
| `frontend/src/views/Agent.vue` | 页面；去掉 live 演示按钮与种子数据 |
| `frontend/src/api/ws.ts` | 短票、重连、按 event_id 去重 |
| `frontend/src/components/agent/*` | 思考 / 工具 / 确认 / 进度 / 报告 / 输入框 |
| `frontend/src/schemas/confirmCard.ts` | 确认卡字段 |

**建议新增**

| 路径 | 负责 |
| :--- | :--- |
| `backend/api/app/agent/persona.py` | 人设 |
| `backend/api/app/agent/slash.py` | 15 条命令解析 |
| `backend/api/app/harness/context/history.py`、`meter.py` | 规划历史经 MemoryPort 编译；ContextMeter 纯计量 |
| `backend/api/app/harness/memory/session_context_store.py`、`orchestration/compaction_runtime.py` | 会话窗口/压缩游标/事件读取；模型 `/compact` 编排 |
| `backend/api/app/agent/mcp_tools.py` | 短工具实现（与清单同源） |
| `backend/api/app/agent/plan.py` | 规划产物 |
| `backend/api/app/agent/react.py` | 工具循环 |
| `backend/api/app/agent/reflect.py` | 规则门禁 |
| `backend/api/app/agent/harness.py` | 串联与分阶段耗时 |
| `backend/api/app/agent/skills/` | 四技能默认模板 |
| `frontend/src/components/agent/SlashPalette.vue` | `/` 面板：上区系统、下区自定义 |
| `frontend/src/components/agent/MarkdownView.vue` | Markdown；后接 Mermaid/KaTeX 插件位 |
| `frontend/src/components/agent/ContextMeter.vue` | 消息/技能/摘要/余量 |
| `frontend/src/components/agent/SkillBadge.vue` | 思考卡头技能徽标 |
| `frontend/src/agent/slashRegistry.ts` | 系统 15 条本地表；自定义只请求 `/api/slash-commands`，禁止从 admin settings 或 localStorage 合并 |
| `backend/api/app/routers/datasets.py` | 页面 AI 生成候选 |
| `backend/api/app/routers/cases.py` | 用例 AI 生成/补全 |
| `frontend/src/views/Datasets.vue` `Cases.vue` `Tasks.vue` `AdminStress.vue` | 各页 AI 入口，遵守 §10.1 |

压缩摘要：`sessions.compact_summary`。窗口游标：`sessions.compact_keep_from`。待确认卡：`sessions.pending_confirm` + `pending_confirm_author_id`。共享范围：`sessions.visibility` + `deleted_at`。偏好：`GET /api/agent/prefs`（ack 时服务端写）。自定义斜杠：仅 `/api/slash-commands`。凡改表结构用 Alembic。上述 REST/列已收入 **API.md V1.6**。

当前已知缺口（开工时对着改）：`ws.py` 仍一次 JSON 规划且同步阻塞收包循环、上下文只取 8 条、**交付句助手消息常不落库**、工具卡仍有旧英文名、`llm.py` 已返回耗时但 thought/tool_result **尚未带 `latency_ms`**、live 页仍有模拟按钮、无 ContextMeter 四段、无技能徽标、无 `/compact`、待确认卡仍是进程内 `_PENDING_CARDS`。

---

## 12. 关键时序

**下单**

```text
/benchmark 对比两模型
  thought 规划 + 耗时 + 技能徽标「基准对比」
  tool_call / tool_result  （MCP · 列出协议档 / 数据集）
  thought 复核
  confirm
用户 confirm_ack ok=true  → 写入 agent_prefs
  任务 queued
  thought 已入队
  progress …
  report 或 error
```

**压缩**

```text
/compact
  thought 规划：压缩窗口
  thought 复核：保留近几条、不删历史
  thought 已压缩 {old_M}→{new_M}
  上下文计数更新
  无确认卡
```

**断线**：提示重连 → 按 last_event_id 补事件。任务继续在 Worker 跑，不丢。

---

## 13. 验收脚本（第一阶段）

1. 登录，指定 Agent 协议档（密钥不回显）。  
2. `/help` 与输入 `/` 能看到已启用命令。  
3. `/benchmark` 或芯片 → 规划思考 → 工具卡 → 复核思考 → 确认卡。  
4. 确认后进度 queued → running → succeeded（允许 Worker 空跑，但必须走真实事件）。思考卡能看到耗时。  
5. 断网再连，对话和进度还在。  
6. `/compact` 后 ContextMeter 四段数字变化，刷新历史卡片还在。  
7. 取消确认卡，库中没有新任务。思考卡有技能徽标，工具卡标「MCP · 短工具」。  
8. 不把任务中心、数据集网格、调度星图当作本阶段必过项。

---

## 14. Task（做完就勾选，并改文首修订）

勾选规则：把 `[ ]` 改成 `[x]`，后面写日期。未勾选不得说该能力已完成。

### 14.1 第一阶段（对话闭环）

| ID | 内容 | 主要文件 | 完成标准 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| AGT-STB-01 | LightRAG stub：拒绝假成功 | `lightrag_stub.py` worker | `kind=rag` 不得 mock succeeded | [x] 2026-08-19 |
| AGT-STB-02 | 长工具门禁 | `long_tasks.py` | Agent 调 `benchmark.run` 等抛 VALIDATION | [x] 2026-08-19 |
| AGT-STB-03 | 模型调用 AppError + agent_trace + 返回 latency_ms | `llm.py` | 控制台有耗时，不泄 Key | [x] 2026-08-19 |
| AGT-WS-01 | 短票、心跳、断线补发 | `ws.py` `ws.ts` | 重连不丢卡；关闭码 4401/4404 | [ ] |
| AGT-WS-02 | 上行只有三条；斜杠走 user_message | `ws.py` | 无第四种上行 | [ ] |
| AGT-SES-01 | 会话列表与 messages+events 回放 | `sessions.py` `Agent.vue` | 刷新不丢工具卡；切换会话不丢历史、生成中不 abort | [x] 2026-08-20 |
| AGT-SES-02 | 交付句写入 messages；规划/复核只走 events | `ws.py` | 刷新气泡与思考卡不重复三倍灌窗口 | [ ] |
| AGT-SES-03 | sessions.pending_confirm 迁移与回放 | models + Alembic sessions.py | 刷新后确认卡仍可编辑 | [x] 2026-08-19 |
| AGT-SLH-03 | slash-commands M1 桩 | 新 router 或现路由 | GET 返回 VALIDATION「自定义命令未启用」，禁止 200 空列表冒充已启用 | [x] 2026-08-19 |
| AGT-LLM-01 | 指定唯一 Agent 协议档 | `llm.py` 设置项 | 无档时明确报错、不泄 Key | [x] 2026-08-19 |
| AGT-LLM-02 | thought/tool_result 带 latency_ms 并展示 | `ws.py` 卡片 | 能看到秒或毫秒 | [x] 2026-08-19 |
| AGT-HRS-01 | 抽出人设、斜杠、短工具模块 | `agent/*` | 清单与实现同一份 | [x] 2026-08-19 |
| AGT-HRS-02 | 规划→行动→复核串联 | `harness.py` | 复核未过不出确认卡 | [x] 2026-08-19 |
| AGT-HRS-03 | 占槽、kind、幻觉 ID、工具白名单 | `reflect.py` | 有测试；`/stress` 不出 kind=stress | [x] 2026-08-19 |
| AGT-HRS-04 | 工具成对事件，最多 5 轮；只读工具默认串行 | `react.py` | 无事件不造卡 | [x] 2026-08-19 |
| AGT-HRS-05 | 阶段 pill：规划中/调用中/复核中 | Agent.vue | 与 thought.stage 或卡片推断一致 | [x] 2026-08-19 |
| AGT-HRS-06 | 规划 JSON 失败重试一次再降级规则 | `plan.py` | 降级后仍进复核、不出假确认卡 | [x] 2026-08-19 |
| AGT-HRS-07 | Harness 丢到 asyncio.Task；收包循环不阻塞 | `ws.py` harness.py | `/stop` 能打断本轮；会话级 abort | [x] 2026-08-19 |
| AGT-SLH-01 | 15 条命令；芯片同源 | slash 注册表 面板 | `/help` 与面板一致 | [x] 2026-08-19 |
| AGT-SLH-02 | `/compact` | `compaction_runtime.py` + `SessionContextStore` | 四段计数更新且历史仍在 | [x] 2026-08-19 |
| AGT-CTX-01 | 模型窗口 20 条 | `SessionContextStore` + `meter.py` | 人设始终带上 | [x] 2026-08-19 |
| AGT-CTX-02 | ContextMeter 消息/技能/摘要/余量 | ContextMeter.vue | `/20` 只约束消息；无记忆文件文案正确 | [x] 2026-08-20 |
| AGT-CTX-03 | compact_keep_from 迁移与 REST context_meter | models Alembic sessions.py | 刷新数字与压缩后 M 一致 | [x] 2026-08-19 |
| AGT-MEM-01 | ack 成功后写 agent_prefs；规划可沿用 | settings + plan.py | 资产已删则不当作有效 ID；须发「沿用你上次的协议档」thought | [x] 2026-08-20 |
| AGT-UI-01 | live 去掉模拟按钮与种子数据 | `Agent.vue` | 仅 mock 模式可演示 | [x] 2026-08-20 |
| AGT-UI-02 | 工具卡中文名 +「MCP · 短工具」 | `ToolCard.vue` | 无旧名 list_profiles | [x] 2026-08-20 |
| AGT-UI-03 | 确认卡 ack；未确认不入队 | ConfirmCard `ws.py` | 取消无任务 | [ ] |
| AGT-UI-04 | 进度坞与报告卡走真事件 | 组件、worker | 空跑也发 progress/report | [ ] |
| AGT-UI-05 | 基础 Markdown 渲染 | MarkdownView | 防 XSS | [x] 2026-08-20 |
| AGT-UI-08 | 思考卡技能徽标 | SkillBadge.vue | 无 skill 不显示；回放仍在 | [x] 2026-08-20 |
| AGT-MCP-01 | 短工具实现与清单同源 | `mcp_tools.py` | 名称冻结 | [x] 2026-08-19 |
| AGT-TSK-01 | ack 合并后再按确认卡校验 | `ws.py` `tasks.py` | 与 REST 下单同一套字段 | [x] 2026-08-19 |
| AGT-TSK-02 | 取消对话框；重跑出新卡 | `Agent.vue` | 重跑新 ID | [ ] |
| AGT-WRK-01 | Worker 空跑写事件 | worker | 对话里能走完进度 | [ ] |
| AGT-LNG-01 | 占槽可聊；新回合不再发 confirm；未 ack 卡按钮禁用 | harness ConfirmCard | CONCURRENCY 文案；/status 能看到活动任务 | [ ] |
| AGT-LNG-02 | progress 节流且不写入 messages、不进 20 条窗口 | worker + `SessionContextStore` | 重连仍能看到最后进度 | [ ] |
| AGT-LNG-03 | /stop 与 /cancel 分流；评测协作停、压测立即停 | Agent.vue ws.py worker | Dialog 文案不同 | [ ] |
| AGT-LNG-04 | Worker 无进度超时与 claim 过期对 Agent 可见 | worker + error/progress | 不假造成功 | [ ] |

### 14.2 后续（工作台 / RAG / 压测，随页面打通再勾）

| ID | 内容 | 状态 |
| :--- | :--- | :--- |
| AGT-M2-01 | `/datasets`、dataset.list、报告短读 | [ ] |
| AGT-M2-02 | 表单下单与确认卡同一套字段 | [ ] |
| AGT-M2-03 | 数据集/用例页 AI 候选走同一模型与人设 | [ ] |
| AGT-M2-04 | 自定义斜杠：下区列表 + 添加 UI + 完整 GET/POST/DELETE `/api/slash-commands` | [ ] |
| AGT-M2-05 | Mermaid 围栏渲染，失败回退源码 | [ ] |
| AGT-M2-06 | 任务中心 diagnosis 只读服务端，禁止前端编造 | [ ] |
| AGT-M2-07 | KaTeX 公式渲染，未加载时原文 | [ ] |
| AGT-M3-01 | `/rag` `/kb` 与确认卡 rag 段 | [ ] |
| AGT-M4-01 | `/report` 解读，不重跑 | [ ] |
| AGT-M4-02 | 压测进度曲线与会签 | [ ] |
| AGT-M4-03 | 窗口将满自动 compact（可选） | [ ] |
| AGT-M4-04 | 压测治理 AI 建议：未启用则明示；采纳只回填表单 | [ ] |

---

## 15. 审查清单（合并前看一遍）

- [ ] 没有新的 WS 事件名，没有第四条上行  
- [ ] 没有跳过确认卡的下单  
- [ ] 没有用户改提示词、切模型、思考强度滑杆、外部 MCP、可编辑记忆文件  
- [ ] Skill 只做徽标、MCP 只做工具卡副标题，没有伪造 skill/mcp 事件  
- [ ] ContextMeter 含消息/技能/摘要/余量；`/20` 只约束消息；记忆文件段为未启用  
- [ ] live 没有模拟成功/失败和假资产  
- [ ] 长任务不在 WS 进程里跑完；Harness 不阻塞收包循环；页面 AI 不开 Subagent；进度不塞进 20 条模型窗口  
- [ ] `/stress` 确认卡 kind 为 benchmark 或 rag，从不出 `kind=stress`  
- [ ] 十个错误码以外没有把堆栈丢给浏览器  
- [ ] 改了表结构就有迁移  
- [ ] 对应 Task 已勾选，文首修订已更新  
- [ ] 实现与 §16 冻结 JSON / 接口 / 公式一致  
- [ ] §4.6 增量与 API.md V1.6 一致（路径、payload、错误码）

---

## 16. 编码规格（对着写代码）

文中「约 / 或」与本节冲突时，**以本节为准**。确认卡数字默认对齐 **PRD 5.2.2** 与 API.md TaskSpec（`sla_p99_ms` 默认 null）。`frontend/src/schemas/confirmCard.ts` 与 `ws.py` 里现行预填（sample_size=20、temperature=0.2 等）**必须改到与本节一致**，不得另备一套。Harness 行为跟本节。

### 16.1 确认卡默认值与三份 Artifact

```json
{
  "run": {
    "sample_size": 1000,
    "concurrency": 4,
    "timeout_s": 60,
    "retry": 1,
    "temperature": 0,
    "max_tokens": 1024,
    "system_prompt": "",
    "k": 5,
    "use_judge": false
  },
  "stress": {
    "env": "test",
    "qps": 10,
    "duration_s": 120,
    "sla_p99_ms": null
  }
}
```

Worker 夹紧：`sample_size = min(请求值, 1000, 行数)`；`concurrency` ≤ 平台 inflight；`stress.qps` ≤ settings.max_qps（默认 500）；`duration_s` ≤ max_duration_s（默认 1800）。未填 `sla_p99_ms` 时报告不出「是否达标」。

**`skill_id` 只准：** `skill-benchmark` | `skill-rag` | `skill-testcase` | `skill-stress` | `null`。

**benchmark 确认卡**

```json
{
  "kind": "benchmark",
  "profile_ids": ["11111111-1111-1111-1111-111111111111"],
  "dataset_id": "22222222-2222-2222-2222-222222222222",
  "kb_id": null,
  "gold_qa_id": null,
  "rag_mode": ["hybrid"],
  "run": {
    "sample_size": 1000,
    "concurrency": 4,
    "timeout_s": 60,
    "retry": 1,
    "temperature": 0,
    "max_tokens": 1024,
    "system_prompt": "",
    "k": 5,
    "use_judge": false
  },
  "with_stress": false,
  "stress": { "env": "test", "qps": 10, "duration_s": 120, "sla_p99_ms": null },
  "case_source": null
}
```

**PlanArtifact（数据集还没 list）**

```json
{
  "intent": "benchmark",
  "skill_id": "skill-benchmark",
  "slots": {
    "filled": { "kind": "benchmark", "with_stress": false },
    "missing": ["profile_ids", "dataset_id"]
  },
  "tools_needed": ["model.list", "dataset.list"],
  "delivery": "confirm",
  "budget": { "max_tool_rounds": 4 },
  "notes": "规划：基准评测。先列出协议档和数据集，再组确认卡。"
}
```

- testcase：`filled.kind=testcase`；无附件且无粘贴则 `missing=["case_source"]`；`tools_needed=[]`。  
- `/stress`：`intent` 为 `benchmark`（若 prefs.last_kind 为 rag 则 `rag`），`filled.with_stress=true`，`skill_id=skill-stress`，确认卡 `kind` 仍是质量任务。  
- compact：`intent=compact`，`skill_id=null`，`missing=[]`，`tools_needed=[]`，`delivery=action`。  
- inspect（`/profiles` 等）：`delivery=text`，`tools_needed` 为对应 list。

**ReactArtifact**

```json
{
  "observations": [
    {
      "name": "model.list",
      "ok": true,
      "latency_ms": 12,
      "data_summary": { "count": 2, "ids": ["11111111-1111-1111-1111-111111111111"] }
    }
  ],
  "proposed_spec": {
    "kind": "benchmark",
    "profile_ids": ["11111111-1111-1111-1111-111111111111"],
    "dataset_id": "22222222-2222-2222-2222-222222222222",
    "with_stress": false
  }
}
```

`ids` 供复核：确认卡里的资产 ID 必须出现在本轮 `data_summary.ids` 并集中。`run`/`stress` 用默认值深合并进 `proposed_spec`。

**ReflectArtifact**

```json
{
  "verdict": "pass",
  "reasons": ["kind 唯一", "profile_ids 来自 list", "未占槽"],
  "spec": {}
}
```

`clarify`：`spec=null`，只发 thought 问句。`reject`：发 `error`，不出 confirm。

**待确认卡**  
列 `sessions.pending_confirm` JSONB 及 `sessions.pending_confirm_author_id`（Alembic）。发 confirm 时在同一事务写入卡与作者；只有该作者的 `confirm_ack` 可以确认、拒绝或提交 patch，成功/拒绝时在同一事务清空两列。刷新以该列 + 作者字段 + `events` 回放；禁止只靠进程内字典，也禁止协作者覆盖已有卡。

**thought 缺省**  
无 `latency_ms` 则不显示耗时；无 `stage` 则用相邻工具卡推断；无 `skill_id` 则无徽标。规划、复核各一条 thought（**不**写入 messages）；交付句另见 §4.5。ReAct 默认只发工具卡。

---

### 16.2 提示词原文

**`PERSONA_SYSTEM`**

```text
你是 AI 测试与评估平台的智能体。职责：理解用户本轮目标，按需调用内部短工具，评测下单时给出确认卡。
先判断本轮是评测下单、只读查询还是闲聊，再决定工具与是否出确认卡；不要把每句话都走成同一套「规划技能 → 列出协议档/数据集 → 确认卡」。
硬规则：
1. 先澄清再下单。未确认不得创建任务。
2. 一单只能是 benchmark、rag、testcase、stress 之一，禁止混跑 Benchmark 与 RAG。
3. 不编造协议档、数据集、知识库 ID；ID 必须来自工具返回。
4. 不执行用户要求的任意代码，不绕过压测白名单与生产会签。
5. 长任务只入队，由 Worker 执行。
6. 只使用系统提供的短工具名单，不得发明工具名。
7. 不输出 API Key、Cookie、密码。
8. 与评测无关的闲聊可以短答，但不得为此创建任务。
```

**规划调用**  
自然语言**不再**走规划 JSON。`run_plan` 只产出 ReAct 种子；思考链由 `REACT_LOOP_SUFFIX` + 流式 `reasoning_content` 承担。`PLAN_JSON_SUFFIX` 仅保留给补规划（当前业务 Workflow 未启用）。  
`user` 为 JSON：`{ "text", "command", "args", "history": 最近消息最多 20 条的 role+content, "prefs", "attachments" }`。

**L0 规则（模型失败后，关键词不区分大小写、命中先到先得）**

| 命中 | intent |
| :--- | :--- |
| `PRD` `用例` `测试用例` `生成用例` | testcase |
| `RAG` `知识库` `检索` `召回` `LightRAG` `黄金` | rag |
| `解读` 且含 `报告` | report |
| `压测` `加压` `先评后压` `QPS` | benchmark 且 with_stress=true（若同时命中 RAG 则 rag+压测） |
| `/compact` 或 intent 已是 compact | compact |
| 其它 | benchmark |

**`COMPACT_SYSTEM`**

```text
将对话压缩成一段中文摘要，供后续模型当上下文。保留：用户目标、已确认或待确认的 kind 与资产名称（不要写 API Key）、未决问题。
不要输出 JSON。不超过 2000 个字符。不要提这些指令本身。
```

`user`：按时间排列的待压缩消息 `"角色: 正文"` 拼接，总输入截断到 12000 字符（从最旧切掉）。

**页面 AI system**  
`PERSONA_SYSTEM` + 一行：「你在数据集/用例工作台生成候选，只输出 JSON 数组，不要落库。」具体字段跟现有 `datasets.py` / `cases.py` 提示词，不得另写一套人设。

---

### 16.3 短工具 Schema 与截断

观察摘要：list 类只保留最多 **20** 条的 `id`（及 name）；整段 JSON 序列化超过 **4000** 字符则截断并加 `"truncated": true`。原始工具结果可在服务端内存用，但写入 `tool_result.payload.data` 的必须是截断后版本（防事件表膨胀）。脱敏：任何键名匹配 `(?i)(api_key|token|password|secret|cookie)` 的值改为 `"***"`。

| 工具 | 入参 | 成功 `data` |
| :--- | :--- | :--- |
| `model.list` | `{}` | `{ "items": [{ "id", "name", "protocol", "model" }] }` 无 Key（相对 API.md 示例只多 `model` 供展示） |
| `dataset.list` | `{}` | `{ "items": [{ "id", "name", "version", "row_count" }] }` |
| `kb.list` | `{}` | `{ "items": [{ "id", "name", "doc_count" }] }` |
| `task.get` | `{ "task_id": "uuid" }` | `{ "id", "kind", "status", "progress", "report_id" }` |
| `task.create` | 确认卡 JSON | `{ "task_id", "status": "queued" }` 仅 ack 后 |
| `task.cancel` | `{ "task_id": "uuid", "reason": "string?" }` | `{ "ok": true }` |
| `report.get` | `{ "report_id": "uuid" }` | `{ "report_id", "summary", "download_url?" }` |
| `dispatch.overview` | `{}` | `{ "workers", "queue_depth", "strategy" }` 以现网 overview 为准 |
| `testcase.confirm` | `{ "case_set_id", "edits"? }` | `{ "status": "succeeded" }` |
| `audio.voiceclone` | `{ "text", "file_id", "style"? }`；`file_id` 必须来自本轮附件，禁止编造 | `{ "file_id", "filename", "content_type", "size", "content_url" }` 不含音频 base64 |
| `image.generate` | `{ "prompt", "file_id"?, "prompt_extend"? }`；`file_id` 必须来自本轮图片附件，禁止编造 | `{ "file_id", "filename", "content_type", "size", "content_url" }` 不含图片 base64 |

未实现的工具：`ok=false`，`error` 用用户可读中文「该能力未启用」，WS 可另发 `error` `code=VALIDATION`。

---

### 16.4 斜杠语法与灰置

解析（整段 `text` trim 后）：

```text
^/([A-Za-z][A-Za-z0-9_-]{0,31})(?:\s+(.+))?$
```

- `command` 小写后查注册表。自定义名同样匹配；系统名优先。  
- `args` 按空白切成 tokens，再尝试：完整 args 字符串对 `name`/`id` 子串匹配 list 结果（ReAct 之后）。`/report` 的第一段若像 UUID 则当 `report_id`。  
- 不是 `/` 开头：整句当自然语言。  
- `/` 后无合法命令：thought「未知命令」+ 启用中的 `/help` 列表，不出确认卡。

**灰置（里程碑未到）**

- 面板禁用，Enter 不发送。  
- 若仍发来：`error` `{ "code": "VALIDATION", "message": "「/rag」将在知识库阶段启用" }`，Harness 结束。

**各命令 args**

| 命令 | args | 无参数 / 失败 |
| :--- | :--- | :--- |
| `/benchmark` `/rag` `/testcase` | 自由文本当规划提示 | 仍走 Harness |
| `/stress` | 自由文本当规划提示 | `intent=benchmark` 或 prefs 为 rag 时 `rag`；`with_stress=true`；**禁止**组 `kind=stress` 卡 |
| `/cancel` | 忽略 args | 无非终态任务：thought「当前没有可取消的任务」 |
| `/rerun` | 可选 task_id | 默认本会话最近终态任务；没有则 clarify |
| `/stop` | 无 | 见 §16.5 |
| `/new` | 无 | `POST /api/sessions` 后前端切到新 id 并重连 WS |
| `/compact` | 无 | 见 §16.6 |
| `/status` | 无 | 读占槽；无则「无活动任务」 |
| `/profiles` `/datasets` `/kb` | 无 | 调对应 list，thought 摘要 + 工具卡 |
| `/report` | 可选 uuid | 无 id：要用户给或用本会话最近 report_id |
| `/help` | 无 | 只列已启用 |

芯片：写入输入框的是自然语言整句，**不带** `/`，避免和命令解析冲突。

---

### 16.5 `/stop`、prefs、slash 的唯一接口

**仍只有三条 WS 上行。** `/stop` 也是 `user_message`，`text` 为 `/stop`。

**Harness 不得阻塞收包循环（否则 `/stop` 无效）**

```text
ws_agent 主循环只负责 receive + 分发：
  user_message / confirm_ack / cancel_task
    → 若该 session 已有未结束的 harness_task：
         user_message 且 text 为 /stop → 置会话级 abort，立刻返回
         其它 user_message → thought「正在生成，先 /stop 或等本轮结束」
    → 否则 create_task(run_harness)；主循环继续 receive

会话级 abort（不是连接级）：
  进程内 dict session_id → { user_id, abort: Event, harness_task }
  规划、每一轮短工具、每一次模型调用之前检查 abort
  同一成员双标签：任一连接发 /stop，两边都停这一轮生成
```

- 本轮 Harness 未 ack：置 `abort`，取消未发出的工具与后续模型调用，发 thought「已停止生成」并写入 messages（交付句）；**不**清 queued 任务。已发出的 confirm 保留（用户仍可取消卡）。  
- 已入队：thought「任务已在执行，停止生成不会取消任务；需要取消请用 /cancel」（交付句）。  
- 无生成中且无排队：仅 thought「当前没有正在生成的内容」，**不**发 `error`。  
- 整回合墙钟 180s：发 `error` `TIMEOUT`「本轮超时，未出确认卡」+ thought 说明，不出卡；等价于 abort。音色克隆上游超时单独为 `TIMEOUT`「音色合成超时」。  
- 前端：本地发送 `/stop` 后可忽略本轮后续 thought/tool 直到下一条用户消息；**以服务端 thought 为准**。  
- `/cancel` 只取消本会话非终态任务（与 REST 按 `task_id` 跨会话取消不同）；权限仍按 PRD：创建者可取消自己的，管理员可取消任何人的。
- 共享会话中：只有本轮 Harness 发起成员可以 `/stop`；只有会话 owner 可以 `/compact`；其他团队成员可正常发送下一条消息、查看持久化事件和正文 chunk。

**确认卡回放**  
`GET /api/sessions/{id}/messages` 增加 `pending_confirm` 与 `pending_confirm_author_id`（与列同源）。前端只为确认卡作者显示可操作按钮；`events` 里的 `confirm` 只作只读回放，避免两张卡。

**偏好（只读给规划，写入仅 ack 成功）——§4.6 增量**

```text
GET /api/agent/prefs
200  { "last_kind", "last_profile_ids", "last_dataset_id", "last_kb_id", "last_gold_qa_id", "last_with_stress", "updated_at" }
无记录时各字段 null。无 PUT。失效 ID：规划当 missing，确认卡对应下拉为空，thought「上次的数据集已删除」。
```

**自定义斜杠（冻结，不要第二种）——§4.6 增量**

```text
GET  /api/slash-commands
     { "items": [{ "id", "name", "hint", "template", "created_by", "created_at" }], "total" }

POST /api/slash-commands
     body { "name", "hint", "template" }
     name: ^[A-Za-z][A-Za-z0-9_-]{0,31}$ 且不在系统 15 条中（禁止中文 name）
     template: 1–2000 字符；仅预填用户输入，永远不当 system
     拒绝：template 去空白后等于 /bypass、或含「跳过确认」「改系统提示词」
     201 返回创建对象

DELETE /api/slash-commands/{id}
     仅 created_by = 当前用户；否则 UNAUTHORIZED
```

M1 未实现这三条时：`GET/POST/DELETE` 一律 `AppError(VALIDATION, "自定义命令未启用")`（HTTP **400**，禁止用 409 冒充）。面板下区展示该句。完整 CRUD 在 AGT-M2-04。

**Agent 场景文案**

| 情况 | code | message |
| :--- | :--- | :--- |
| 无 Agent 协议档 | VALIDATION | 未配置 Agent 协议档，请先到协议档页指定 |
| 会话占槽仍要下单 | CONCURRENCY | 当前会话已有未完成任务，确认已禁用 |
| 能力未启用 | VALIDATION | 该能力未启用（可带命令名） |
| 压缩失败 | UPSTREAM 或 TIMEOUT | 上下文压缩失败，窗口未改动 |
| 本轮 Harness 超时 | TIMEOUT | 本轮超时，未出确认卡 |
| `/stop` 无生成 | — | 仅 thought，不发 error |

---

### 16.6 ContextMeter 与 compact 算法

常量：`WINDOW = 20`，`KEEP_RECENT = 6`，`SUMMARY_MAX_CHARS = 2000`，`COMPACT_INPUT_MAX = 12000`。

列：`sessions.compact_summary`（TEXT 可空）、`sessions.compact_keep_from`（messages.id 可空）。从未 compact 时两者皆 null。

**窗口原文（唯一的 `M` 定义）**

```text
rows = 该会话 messages 中 role∈{user, assistant}，按 (created_at, id) 升序

若 compact_keep_from 非空且能命中某条：
    rows = 从该条起（含）到最新
否则：
    rows = 全部

若 len(rows) > WINDOW：
    rows = rows 的最后 WINDOW 条     # 只从模型窗口丢掉最旧，库不删

M = len(rows)                        # 0…20
R = WINDOW - M                       # 余量，0…20
S = 1 若本会话持久化 thought 事件曾记录 skill_id，否则 0（刷新后仍可恢复）
C = 1 若 compact_summary 非空，否则 0

展示：上下文  消息 {M}  · 技能 {S}  · 摘要 {C}  · 余量 {R}  / {WINDOW}
说明：/20 只约束消息窗口。技能、摘要是 0/1 标志，四段加总不必等于 20。
```

验收「已压缩 18→7」：压缩前窗口 M=18，成功后 `compact_keep_from` 指向保留段第一条；若接着写入「已压缩」交付句则 M=7。思考卡写实际前后 M，禁止写死 18→7。

展开后的「字数」用 UTF-8 字符数，不是 token：人设、技能说明、摘要、窗口内 M 条正文、本轮工具观察。不估 token。

**组装给模型的 messages 数组顺序**  
`system=PERSONA` → 可选 `system=技能说明` → 可选 `system=压缩摘要` → 上面算出的 M 条原文 → 本轮 user（含工具观察摘要）。progress 事件一律不进入该数组。

**手动 `/compact`**

1. 先按上式算当前窗口 `rows` 与 `M`。若 `M ≤ KEEP_RECENT`：交付 thought「上下文较短，无需压缩」，不调模型，不改列。  
2. 否则 `keep = rows` 的最后 KEEP_RECENT 条，`to_summarize = rows` 去掉 keep 的前缀（只摘要当前窗口内将被挤出的原文）。  
3. 调 compact 模型 **1** 次。失败：不改两列，`error` 见 §16.5。  
4. 成功：`compact_summary` 截到 SUMMARY_MAX_CHARS；`compact_keep_from = keep[0].id`；**不删除** messages/events。新 M = len(keep)，随后若写入「已压缩」交付句则 +1，仍 cap 20。  
5. 交付 thought「已压缩 {old_M}→{new_M}」，并写入 messages。`GET .../messages` 的 `context_meter` 必须立刻反映新 M。

compact 之后继续聊天：新消息追加在 keep 之后，M 增长；再次超过 WINDOW 时，上式取最后 20 条（PRD「超出丢最旧」）。被挤出窗口、又不在摘要里的回合，M1 允许从模型上下文消失；M4 自动 compact 再收口。

**自动 compact（后补，AGT-M4-03）**  
新交付句写入前若即将 `M==WINDOW`，调用同一函数；必须发 thought「已自动压缩」，禁止静默丢掉。

**刷新恢复**

```text
GET /api/sessions/{id}/messages
{
  "messages": [...],
  "events": [...],
  "pending_confirm": {} | null,
  "compact_summary": null,
  "context_meter": { "messages": M, "skills": S, "summary": C, "headroom": R, "window": 20, "mcp_tools_count": 0, "mcp_tools_max": 28 }
}
```

前端 ContextMeter **只读** `context_meter`。对话列用全量 `messages` + `events`，不要用 `M` 去截断 UI。

---

### 16.7 其它冻结点

**耗时显示**  
`latency_ms < 1000` 显示 `320ms`，否则 `1.2s`（一位小数）。规划 thought、复核 thought、每条 tool_result 各自带 `latency_ms`。本轮合计 = 各次模型 + 各次工具之和，写在阶段 pill 旁，不单独事件。

**`/new`**  
`POST /api/sessions` `{ "title": "新会话" }` → 前端把 WS 的 `sessionId` 换成新 id，`lastEventId=0`，重新 `connect()`。

**会话标题**  
首条 user 文本 trim 后取 40 字符，超出加 `…`。`/compact` `/help` `/stop` 不改标题。

**WS 连接**  
每个浏览器标签一连接；切会话带新 `session_id` 重连（可同一短票未过期则续用，过期再领票）。切走 **不等于** `/stop`：旧会话 harness 继续跑完（未置 abort），已发出事件落库，关掉的 socket 不再推送；回看靠 REST。同一成员的双标签可共同 `/stop`；共享会话的其他成员只能看正文流，不能停止他人的回合。

**Markdown**  
`role=assistant` 的 messages 与 `thought.text` 长度 > 80 或含 `` ``` `` 时用 MarkdownView；规划短句（notes）纯文本。思考卡结束 **800ms** 后收起。无 token 流式。

**斜杠面板**  
宽 360px，挂在输入框上方；`/` 开头过滤 name+hint；↑↓ 选择，Enter 填入（系统命令填 `/name `，自定义填 template），Esc 关闭。中文 IME 合成期间不触发过滤。空输入框芯片与面板不同时：有 `/` 则只下面板。

**Worker 空跑**  
sleep 2s；至少 3 次 progress（0/1、1/1 或 0/100、50、100）；`report_id` 可为占位 UUID，报告页允许空态，禁止前端伪造指标。

**深合并**  
`confirm_ack.patch` 对嵌套对象递归覆盖；数组整段替换。合并后再按确认卡必填校验。

**技能徽标映射**  
`skill-benchmark` → 技能 · 基准对比；`skill-rag` → 技能 · RAG 评估；`skill-testcase` → 技能 · 用例生成；`skill-stress` → 技能 · 先评后压。写在 `slashRegistry.ts` 旁的 `skillLabels.ts`。

---

## 17. Agent 跑起来时必须处理的长任务问题

对话回合（秒级）和平台任务（分钟～半小时）是两条时间线。Agent **只负责入队和转述进度**；谁在 WS 里 `sleep`、谁 `await` 评测，都会把心跳、重连和二次对话打死。

### 17.1 两套时钟

| | Harness 回合 | 平台长任务 |
| :--- | :--- | :--- |
| 谁跑 | `api` 里 `harness.py` + `call_agent_model` | `worker`（压测再下发 `stress` 容器） |
| 时限 | 单次模型 30s；整回合墙钟 **180s** 必须结束（`TIMEOUT` + thought「本轮超时，未出确认卡」）；音色克隆上游默认 90s | 单样本 `run.timeout_s`；用例生成 5 分钟；压测 `duration_s`；用例待确认 72h |
| 用户看到 | 思考卡、工具卡、确认卡、阶段 pill | 进度坞 `progress`，结束 `report` / `error` |
| 断线 | 本轮可能中断生成；已落库事件仍在 | **必须继续**，与 WS 是否连接无关 |

`confirm_ack` 成功路径（冻结）：校验 → `INSERT tasks queued` → `COMMIT` → 清 `pending_confirm` → 写 prefs → `thought`「已入队」→ **结束本协程**。其后禁止再调模型等结果。

### 17.2 哪些是长任务（Agent 禁止同步跑完）

| kind | 执行方 | 占会话槽 | 取消 |
| :--- | :--- | :--- | :--- |
| `benchmark` | worker 逐条打被测 | queued / running | 当前样本结束后停 |
| `rag` | worker（LightRAG query 或外部 Chat） | 同上 | 同上 |
| `testcase` | worker 生成 → `awaiting_case_confirm` | 含等待确认 | 取消生成或过期 72h |
| `stress` | worker 只下发 stress 容器 | 父任务 succeeded 后子任务占同一槽 | **立即停发** |

长工具名（反射层直接拒绝）：`benchmark.run` `rag.evaluate` `testcase.generate` `stress.run`。页面 `ai-generate` 仍是 **30s 短调用**；真正的用例生成只能 `kind=testcase` 入队。

### 17.3 占槽时 Agent 还能干什么

会话内同时最多 1 个非终态（`queued` `running` `awaiting_case_confirm`），**含子任务压测**。

| 允许 | 禁止 |
| :--- | :--- |
| 闲聊、澄清、`/help` `/status` `/profiles` 等只读 | **新回合**再发会 `task.create` 的 `confirm`（`delivery=clarify`） |
| `/compact`、切会话、`/new` | `/rerun` 对仍在跑的任务（先取消或等终态） |
| `/stop`（只停本轮生成） | 把进度条当成「生成中 pill」 |
| `/cancel`（走 Dialog 后 `cancel_task`） | 用断开 WS 当取消 |
| 本回合开始前已有的未 ack 卡：保留在流里，**确认按钮禁用** + 卡上说明占槽 | 静默丢用户消息 |

占槽时用户又说「再评一单」：规划 `delivery=clarify`，thought 说明当前 kind/status，引导 `/status` 或 `/cancel`。不要再弹第二张确认卡。

### 17.4 进度事件：节流、落库、别污染上下文

- Worker 写 `ws_events.event=progress`，**不要**写入 `messages`。  
- 组装 20 条模型窗口时 **忽略全部 progress**。用户问进度：短工具 `task.get` 或进度坞，不要把几十条「40/100」塞进 prompt。  
- 节流：同一 `task_id` 两次 progress 间隔 **≥ 1s**，或按样本每完成 1 条一条；**第一条、最后一条、失败当条必须发**。payload 仍只有 `percent? done total message`。  
- 前端进度坞只展示 **该会话当前非终态任务** 的最新一条；历史 progress 回放可折叠，默认不刷满对话列。

### 17.5 断线、切会话、多标签

- Worker 不订阅 socket，只写库；api 转发循环把新 `event_id` 推给仍连接的客户端。  
- 关闭页面 ≠ 取消任务。重连用 `last_event_id` 补 progress/report/error。  
- 切到别的会话：旧任务继续跑；回来靠 REST + 补发。  
- 两标签同一会话：事件号行锁已有，前端按 `event_id` 去重即可。

### 17.6 `/stop`、`/cancel`、断线对照

| 动作 | 生成中（未入队） | 已 queued/running | 压测 running | awaiting_case_confirm |
| :--- | :--- | :--- | :--- | :--- |
| `/stop` | 会话级 abort，中止 Harness | 明确不取消任务 | 同左 | 同左 |
| `/cancel` + Dialog | 无任务则 thought | 评测：样本结束后停 | 立即停发 | 取消等待，任务 cancelled |
| 关掉浏览器 | 本轮生成可能停 | 任务继续 | 继续直到时长或取消 | 72h 倒计时继续 |
| Worker 进程被杀 | — | claim 过期后由其它 worker 接管或 `failed`+`error` | 停发并 failed | 保持等待，不丢用例集 |

评测 Dialog：「当前样本结束后停止」。压测 Dialog：「立即停止发压」。文案不准混用。

### 17.7 长任务中段失败（Agent 只转述）

| 情况 | 任务状态 | 对对话 |
| :--- | :--- | :--- |
| 样本超时/上游 4xx | 整任务可继续，失败率进报告 | 不必每条 error；严重连续失败可由 worker 打一条 thought 级？**否**，只用 progress.message 或最终 error |
| 超预算 | `failed` + `BUDGET_EXCEEDED` | `error` 事件 |
| 压测不在白名单 | 不得 running | 确认卡阶段就应挡住；漏网则 error `WHITELIST` |
| prod 未会签 | 子任务 queued | 进度坞「等待会签」；Agent 不代点同意 |
| 用例待确认超时 72h | cancelled | thought 可在用户下次说话时用 `/status` 告知，不主动骚扰 |
| Worker 超过 60s 无新 progress 且 status=running | 仍 running | 坞上保留最后 message + 「仍在执行」；**前端可每 15s GET `/api/tasks/{id}` 校准**，禁止本地假造 percent |

### 17.8 先评后压（长任务链）

质量任务 `succeeded` 且 `with_stress=true`：Worker **同一会话** 插入 stress 子任务并占槽。Agent：

1. 先 `report` 质量报告；  
2. 再出现压测 `progress`（新 `task_id`）；  
3. 压测子任务占槽期间：**不得再发** 新确认卡；若仍有未 ack 的父卡，确认按钮禁用；  
4. 不要自动再弹第二张确认卡（压测配置已在父卡里）。

### 17.9 实现禁令（code review 用）

```text
禁止在 routers/ws.py / harness.py 中：
  - time.sleep 大于 0.05s
  - 调用 benchmark.run / rag.evaluate / testcase.generate / stress.run
  - 轮询 tasks.status 直到终态
  - 为等进度而阻塞 confirm_ack 返回
  - 在 receive 循环里 await 整轮 Harness（必须 create_task，否则 /stop 无效）
  - 组出 kind=stress 的确认卡
```

空跑也必须走「入队 → worker 写 progress → 结束」；把 mock sleep 放在 **worker**，不要放在 api。

真实评测阶段：按样本续跑、worker 重启从 `task_events`/行号恢复，与 Agent 无关；Agent 只认事件流。

---

## 18. 已落地的异常、控制台日志与 LightRAG 占位

实现约定：业务失败一律 `raise AppError`（十码），外层 `try/except AppError` 转成 WS `error` 或 HTTP JSON。**控制台只打状态，不打 Key。**

冻结写法（内部函数）：

```python
try:
    ...
except AppError:
    raise
except Exception as exc:
    agent_trace(f"内部异常 type={type(exc).__name__}")
    raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
```

冻结写法（WS 分发）：

```python
try:
    await _handle_user_message(...)
except AppError as exc:
    agent_trace(f"user_message AppError code={exc.code.value}")
    await _emit(db, ws, session_id, "error", {"code": exc.code.value, "message": exc.message}, state=state)
```

禁止 `except Exception` 后把 `str(exc)` 或堆栈发给浏览器。

| 文件 | 行为 |
| :--- | :--- |
| `backend/api/app/agent/log.py` | `agent_trace` → stderr `[agent] ...` |
| `backend/api/app/agent/lightrag_stub.py` | `LIGHTRAG_ENABLED=False`；`assert_lightrag_ready` / `query_lightrag` 抛 `VALIDATION` |
| `backend/api/app/agent/long_tasks.py` | Agent 调 `benchmark.run` 等长工具抛 `VALIDATION` |
| `backend/api/app/llm.py` | 打印协议/模型/耗时；已返回 `latency_ms`；失败归一 UPSTREAM/TIMEOUT |
| `backend/api/app/routers/ws.py` | RAG 意图走 stub；`user_message`/`confirm_ack` 捕获 AppError |
| `backend/worker/app/main.py` | `kind=rag` **不得 mock 成功**，failed + 控制台 `[worker] skip rag` |

M3 接 LightRAG：把 `LIGHTRAG_ENABLED` 改为 True，在 `query_lightrag` 请求 `lightrag:9621/query`，再组 rag 确认卡。现在不要把 query 容器里的空实现当成评测成功。

---

## 19. 修改代码文件与作用清单（2026-08-20 Harness 与团队共享会话）

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/plan.py` | 偏好 thought 挂到 `PlanArtifact.pref_thoughts`；新增 `run_replan` / `merge_replan`（观察进 user JSON，不占 20 条窗口） |
| `backend/api/app/agent/react.py` | `run_react` 支持 `prior` + `extra_tools`，补规划后继续串行工具且计入 5 轮硬顶 |
| `backend/api/app/agent/reflect.py` | 核对调用附带 observations 摘要 |
| `backend/api/app/agent/harness.py` | 发出偏好 thought；补规划闭环；控制斜杠先 `run_gates`；**仅确认卡**再 `maybe_model_check` |
| `backend/api/app/agent/persona.py` | 增加补规划附加段 `REPLAN_JSON_SUFFIX` |
| `backend/api/tests/test_harness.py` | 补 TC-05/08/09/14/16/17/19/20b 等单测 |
| `backend/api/app/models.py` | 会话共享/软删除/确认卡作者列，以及消息作者和浏览器幂等键 |
| `backend/api/migrations/versions/*` | 由 Alembic 自动生成的团队共享会话迁移与历史作者回填 |
| `backend/api/app/session_access.py` | 会话可见性、owner 管理权的唯一权限判断 |
| `backend/api/app/session_connections.py` | 单 API 副本的在线正文 chunk 广播与撤销共享断连 |
| `backend/api/app/routers/sessions.py` | 共享设置、软删除、消息作者和会话历史权限 |
| `backend/api/app/routers/ws.py` | 用户消息事件、团队正文流、连接权限复验与幂等回显 |
| `backend/api/app/agent/harness.py` | 确认卡作者锁定、协作者 `/stop`/`/compact` 边界 |
| `backend/api/app/routers/tasks.py` | 共享会话挂载任务的可见性校验 |
| `frontend/src/api/types.ts` `http.ts` `ws.ts` | 共享会话、消息作者、客户端幂等键及新 REST/WS 契约 |
| `frontend/src/views/Agent.vue` | 团队标识、共享设置、软删除、协作者气泡与流式回显 |

---

## 20. 修改代码文件与作用清单（2026-08-20 切换会话保留历史与后台生成）

| 文件 | 作用 |
| :--- | :--- |
| `frontend/src/views/Agent.vue` | 按会话缓存对话流；生成中的 WS 不随切换拆掉；后台事件写入原会话；切回立即看到进度 |
| `docs/AI测试与评估平台-Agent开发文档.md` | 勾选 AGT-SES-01；记录切换会话不丢历史、不 abort 生成 |

---

## 21. 修改代码文件与作用清单（2026-08-20 问候延迟）

「你好」原先串行打规划模型 → 核对模型 → 闲聊流式，三次上游叠加到 30s+。问候走 L0 定位；核对只留给确认卡。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/plan.py` | `is_smalltalk`：问候关键词且无评测词时 `run_plan` 直接 L0，0 次规划模型 |
| `backend/api/app/agent/reflect.py` | `maybe_model_check` 仅 `delivery=confirm` 才调上游 |
| `backend/api/app/agent/harness.py` | 注释与核对范围对齐 |
| `backend/api/tests/test_harness.py` | 问候跳过规划模型；闲聊跳过核对 |

---

## 22. 任务取消确认与终态并发（2026-08-20）

`cancel_task` 与 `POST /api/tasks/{id}/cancel` 都只允许任务创建者操作；前端以
`creator_id` 与当前成员 ID 判定，非创建者不展示可执行按钮，避免先展示再返回
`UNAUTHORIZED`。Agent 页发起取消后只能显示「等待服务端确认」：收到
`tool_result(name="task.cancel", ok=true)` 或 REST 成功响应才关闭进度坞并显示
`cancelled`，失败必须保留任务和重试入口。

取消与 Worker 完成路径都必须先用同一任务行锁刷新状态：取消锁到任务后才可写
`cancelled`，Worker 在 Benchmark 汇总、用例生成落库和压测骨架完成前也只允许
`running` 任务继续。已经 `cancelled` 的任务不得创建报告、用例集或完成事件；已经
完成的任务也不能被取消请求以陈旧读结果反向覆盖。这避免最后一批样本完成时的双向
终态竞态。

### 修改代码文件与作用清单（2026-08-20 取消链路修复）

| 文件 | 作用 |
| :--- | :--- |
| `frontend/src/views/Agent.vue` | 取消请求进入确认态；失败不再伪报成功，WS/REST 确认后才收起进度坞 |
| `frontend/src/views/Tasks.vue` | 表格和详情抽屉按任务创建者显示取消/重跑写操作 |
| `frontend/src/components/drawers/TaskDetailDrawer.vue` | 抽屉复用父页权限判定，避免旁路越权操作入口 |
| `frontend/src/api/http.ts`、`frontend/src/api/ws.ts`、`frontend/src/api/types.ts` | 返回 REST 取消终态、识别 WS 发送失败、补齐 `creator_id` 类型 |
| `backend/api/app/agent/harness.py` | WS 取消与 REST 对齐权限、审计和 `task_events`，回传关联任务的工具确认 |
| `backend/worker/app/task_state.py` | 统一 Worker 各终态写入前的行锁与运行态校验 |
| `backend/worker/app/benchmark.py`、`testcase.py`、`main.py` | 防止 Benchmark、用例生成和压测骨架完成路径覆盖 `cancelled` |
| `backend/api/tests/test_task_permissions.py`、`backend/api/tests/test_harness.py` | 覆盖 REST/WS 非创建者拒绝、取消时间线和确认事件 |
| `backend/worker/tests/test_task_state.py`、`test_benchmark_cancel.py`、`.github/workflows/ci.yml` | 覆盖 Worker 陈旧对象竞态，并纳入 CI 执行 |

---

## 23. 修改代码文件与作用清单（2026-08-20 闲聊思考卡）

「你好」会连出三张标题都是「已思考」的卡：规划短句、复核门禁、模型推理（或交付句被误渲染）。闲聊与 /help 等不再发规划/复核 thought；交付终帧不占思考卡；卡头按 stage 区分「已规划 / 已复核 / 已思考」。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/harness.py` | `should_emit_stage_thoughts`：chat / 确定性斜杠不发规划、复核卡 |
| `frontend/src/views/Agent.vue` | 交付终帧不渲染思考卡；推理链与交付句分离 |
| `frontend/src/components/agent/ThoughtCard.vue` | 卡头按 `stage` 显示规划/复核/思考 |
| `backend/api/tests/test_harness.py` | 闲聊与 /help 跳过阶段思考卡 |

## 24. 修改代码文件与作用清单（2026-08-20 会话上下文持久化）

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/harness.py` | 完成本轮后保存 `think_final` 思考快照；确认/取消确认卡写入 `confirm_ack` |
| `backend/api/app/agent/context.py` | 从 `ws_events` 恢复 skill 与短 MCP 工具计数 |
| `backend/api/app/routers/sessions.py` | 历史接口补回 `compact_summary` |
| `frontend/src/views/Agent.vue` | 历史/实时回放思考快照、确认回执和工具资产 |
| `frontend/src/api/types.ts` | 补齐新增 WS 事件与 ContextMeter 扩展字段 |

---

## 25. 修改代码文件与作用清单（2026-08-20 审查竞态）

流式气泡按本轮用户消息隔离；切会话停打字机；确认卡 rag patch 与规划门禁对齐；WS 取消绑定当前会话。

| 文件 | 作用 |
| :--- | :--- |
| `frontend/src/views/Agent.vue` | 本轮流式气泡、切会话停 flowTimers、历史回放不覆盖生成中缓存、确认卡会话守卫、后台任务坞收口 |
| `backend/api/app/agent/harness.py` | ack 拒绝 kind=rag；取消校验 task.session_id；调度登记加锁 |
| `backend/api/tests/test_harness.py` | rag patch 拒收；跨会话取消拒收 |

## 26. 修改代码文件与作用清单（2026-08-20 音色克隆短工具）

对话里上传 wav/mp3 参考音频并给出朗读稿，Agent 调用内部短工具 `audio.voiceclone`，经 MIMO TTS 克隆后把合成 wav 落盘，工具卡可播放。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/voiceclone.py` | MIMO OpenAI 兼容调用、规划注入、参考音校验 |
| `backend/api/app/agent/defaults.py` / `mcp_tools.py` / `routers/mcp.py` | 短工具名单 |
| `backend/api/app/agent/plan.py` / `react.py` / `harness.py` | 注入、本轮附件入参、线程隔离、交付句 |
| `backend/api/app/routers/files.py` | wav/mp3 白名单；`GET /api/files/{id}/content` |
| `backend/api/tests/test_voiceclone.py` | 注入与假上游单测 |
| `frontend/src/views/Agent.vue` | 附件与工具卡播放器 |
| `docs/AI测试与评估平台-API.md` | V1.9 契约 |

## 27. 修改代码文件与作用清单（2026-08-20 Qwen Image 内部短工具）

Qwen Image 按 `audio.voiceclone` 的内部短工具方式接入：自然语言识别图像生成意图，React 独立线程调用上游，图片附件由系统绑定，生成结果落盘并在工具卡中预览。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/imagegen.py` | 图文请求组装、上游响应解析、图片落盘、规划注入与配置校验 |
| `backend/api/app/agent/defaults.py` / `mcp_tools.py` / `react.py` / `plan.py` / `harness.py` | 短工具注册、线程隔离执行、规划注入、工具结果交付句 |
| `backend/api/app/config.py` / `docker-compose.yml` / `backend/api/app/routers/files.py` | Qwen 环境变量注入、图片附件白名单 |
| `frontend/src/views/Agent.vue` / `frontend/src/styles/base.css` | 图片附件选择、生成结果预览与同源下载 |
| `backend/api/tests/test_imagegen.py` | 图文请求、规划、落盘和 React 线程隔离单测 |

---

## 28. 修改代码文件与作用清单（2026-08-20 Harness MCP ReAct 循环）

行动阶段改为 Think-Act-Observe，但工具面走本产品 **内部短工具**（`mcp_tools.execute_short_tool`），禁止 OpenAI function calling。每轮模型只输出 JSON 决策；前端按轮展示思考卡（`stage=react` + `skill_id` 技能徽标）和 **ToolCall 卡**（展开可见 `arguments` 与 `result`/`error`）。长任务（`benchmark.run` / `rag.evaluate` / `testcase.generate` / `stress.run`）不得在循环内执行，槽位齐后确认卡 → Worker 入队。WS 事件名仍冻结为 `thought` / `tool_call` / `tool_result`（不引入 `thinking`/`token`）。`/help` 等确定性斜杠仍 0 次模型。上游不可用时回退 `tools_needed` 队列，确认卡门禁不变。未预期异常经 `agent_exception` 打 traceback，并包装为 `AppError(INTERNAL)`。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/persona.py` | `REACT_LOOP_SUFFIX` 要求 MCP JSON 字段 `thought/tool/arguments/done/reply` |
| `backend/api/app/agent/defaults.py` | `MAX_REACT_ROUNDS`、`TOOL_TIMEOUTS` |
| `backend/api/app/agent/react.py` | MCP JSON 多轮循环 + tools_needed 回退队列；长工具移交 |
| `backend/api/app/agent/harness.py` | 生产路径 `use_llm`；闲聊优先交付 ReAct `reply_text`；ReAct 思考走 `stage=react` 落库 |
| `frontend/src/views/Agent.vue` | 每轮独立思考卡；ToolCall 控制台打印入参出参；协作者缓冲 `tool_call` 先收尾思考卡 |
| `frontend/src/components/agent/ThoughtCard.vue` | ReAct 标题为 ToolCall；技能徽标保留 |
| `frontend/src/components/agent/ToolCard.vue` | 副标题 `ToolCall · name`；始终展示输入 arguments / 输出 result |
| `backend/api/tests/test_harness.py` | 内部短工具多轮、长任务不执行、模型不可用回退 |
| `docs/AI测试与评估平台-Agent开发文档.md` | §5 行动阶段与预算说明 |

---

## 29. 修改代码文件与作用清单（2026-08-21 TurnMode 路由）

按任务复杂度选择范式：一两步短工具走 ReAct；评测下单走 Plan-and-Solve（斜杠执行清单，NL 可短 ReAct）；确认卡前规则门禁 + 可选核对。Reflection 不是每回合必跑的第三段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/turn_mode.py` | `select_turn_mode` / `refine_turn_mode` 与 ReAct LLM、补规划、核对开关 |
| `backend/api/app/agent/harness.py` | `_run_turn` 按模式跳过规划卡、补规划、核对模型 |
| `backend/api/app/agent/plan.py` | 只读清单 L0；生图/配音/inspect 跳过规划模型 |
| `backend/api/tests/test_harness.py` | TurnMode 路由与 inspect 规划单测 |
| `docs/AI测试与评估平台-Agent开发文档.md` | §5 改为按 TurnMode 跳过 |

---

## 30. 修改代码文件与作用清单（2026-08-21 模型选循环）

自然语言不再用关键词表猜复杂度。规划模型输出 `complexity` + `loop` 后 harness 调度对应循环；斜杠仍 0 次模型。`loop`/`complexity` 不进冻结确认卡 JSON。生图/配音 inject 后强制 ReAct。关键词表只在规划失败或模型没给合法 `loop` 时回退。问候会多一次规划调用（相对此前 L0 短路）。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/persona.py` | 规划 JSON 增加 complexity/loop 判定说明 |
| `backend/api/app/agent/plan.py` | NL 一律走规划模型；sanitize/`_stamp_loop` 收 loop |
| `backend/api/app/agent/turn_mode.py` | `resolve_turn_mode` 优先模型 loop，斜杠仍产品绑定 |
| `backend/api/app/agent/harness.py` | 规划后再调度 TurnMode |
| `backend/api/tests/test_harness.py` | 问候/inspect/人像改为 mock 规划 JSON |
| `docs/AI测试与评估平台-Agent开发文档.md` | §5 改为模型选循环 |

---

## 31. 修改代码文件与作用清单（2026-08-21 思考流式与生图预览）

根因：mimo 流式请求曾写 `thinking.disabled`，对话/ReAct 看不到 `reasoning_content`；ReAct 决策还是非流式 JSON，思考卡只能整段后出。生图预览塞在 ToolCall 卡里，刷新后只剩工具 JSON。

现：流式路径打开思考；ReAct 决策流式下发 `thought.stream=think`，成功后落 `think_final`。规划 JSON 仍关闭思考以免正文被挤空。生成图片在对话流独立预览（放大/下载），ToolCall 只保留 arguments/result；助手消息写入 `file_id` 供会话窗口回放。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/adapters.py` | 流式不再关闭 mimo 思考；`call_protocol` 仍 disabled |
| `backend/api/app/agent/react.py` | `_stream_mcp_step` 流式推理 + JSON 决策 |
| `backend/api/app/agent/harness.py` | 生图交付句带 file_id |
| `frontend/src/components/agent/ToolCard.vue` | pending/成功态；图片移出 |
| `frontend/src/components/agent/MediaPreview.vue` | 图片预览与下载 |
| `frontend/src/views/Agent.vue` | 实时/协作/历史插入 media 项 |
| `backend/api/tests/test_adapters.py` / `test_harness.py` | 思考开关与 ReAct 流式单测 |

---

## 32. 最小 MCP 工具内核（2026-08-21）

为先完成 Harness 分层重构、避免旧业务斜杠抢占模型路线，当前 Agent MCP 注册清单冻结为：

| 工具 | 用途 |
| :--- | :--- |
| `audio.voiceclone` | 使用本轮 wav/mp3 参考音频合成配音 |
| `image.generate` | 文本或参考图生成图片 |

`model.list`、`task.get`、`task.create`、`task.cancel`、`dispatch.overview`、`dataset.list`、`report.get`、`kb.list` 与 `testcase.confirm` 均不再属于 Agent MCP。任务、资产、报告及调度的业务工作流将在后续独立 Workflow 层重建；本阶段不得通过对话伪造其结果。

系统斜杠仅保留不参与模型业务路由的 `/stop` 和 `/compact`。`/benchmark`、`/stress`、`/testcase`、`/rag`、`/profiles`、`/datasets`、`/kb`、`/report`、`/status`、`/rerun`、`/cancel`、`/new`、`/help` 已移除，不能再向规划或 ReAct 阶段注入业务工具。

### 修改代码文件与作用清单

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/defaults.py` | 将 Agent 短工具白名单收缩为两项多媒体能力 |
| `backend/api/app/agent/mcp_tools.py` | 移除旧业务 MCP 的执行实现 |
| `backend/api/app/agent/slash.py` | 将系统斜杠收缩为会话控制命令 |
| `backend/api/app/agent/persona.py` | 从规划与 ReAct 提示词中移除旧业务工具 |
| `backend/api/app/routers/mcp.py` | MCP 工具中心只返回两项已挂载能力 |
| `frontend/src/agent/slashRegistry.ts` | 斜杠面板只展示 `/stop` 与 `/compact` |

---

## 33. MCP Server 与 ToolCall 注册表收敛（2026-08-21）

`agent/mcp_registry.py` 是当前最小 MCP 内核的唯一注册源。每项工具统一定义名称、中文标题、说明、权限和超时；后端白名单、MCP 工具中心响应、ToolCall 参数绑定与执行分派均从该注册表派生，禁止在路由、提示词或前端再复制工具名称。

ToolCall 的执行顺序冻结为：注册表查找 → 系统绑定本轮附件参数 → 脱敏日志 → `tool_call` 事件 → 隔离会话执行与超时控制 → 截断/脱敏结果 → `tool_result` 事件与 observation。未注册工具在执行前统一返回 `VALIDATION`，不得进入执行器。

### 修改代码文件与作用清单

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/mcp_registry.py` | MCP 元数据、参数绑定、执行分派的唯一注册表 |
| `backend/api/app/agent/defaults.py` | 从注册表派生白名单、标题和超时 |
| `backend/api/app/agent/mcp_tools.py` | 统一走注册表执行已注册工具 |
| `backend/api/app/agent/react.py` | ToolCall 统一通过注册表绑定参数与读取超时 |
| `backend/api/app/routers/mcp.py` | 从注册表转换 MCP 工具中心响应 |

## 34. MiMo 语音识别与语音合成路由（2026-08-21）

本阶段在既有音色克隆、生图短工具之外增加两项音频能力，不新增 REST 代理，也不让浏览器直连上游：

- `audio.speech_recognition`（STT）：用户明确要求转写、听写或生成字幕时优先于音色克隆；`file_id` 只能由系统从本轮 wav/mp3 附件绑定，缺少音频时交付澄清。
- `audio.speech_synthesis`（TTS）：用户明确要求文字转语音、播报或语音合成时使用；文本、模式、风格和受控模型参数由系统绑定，缺少必要文本时交付澄清。
- 以上工具与 `audio.voiceclone`、`image.generate` 均强制 `REACT_ONLY`，在隔离线程和独立数据库会话执行；既有音色克隆与生图路径不改变。
- STT 成功结果只显示安全的 transcript 与元数据；TTS/voiceclone 成功结果只显示同源文件播放地址和元数据，不展示 Base64、Key 或上游响应原文。
- `tool_call` / `tool_result` 仍按原事件名实时下发并落库，历史回放使用相同事件：STT 工具卡自动展开转写文本，TTS 工具卡自动展开播放器；助手交付句分别说明“转写文本已在工具卡中展示”和“可在工具卡中播放或下载”。

### 修改代码文件与作用清单

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/persona.py` | 增加 STT/TTS 工具名、输入绑定规则和识别优先级 |
| `backend/api/app/agent/plan.py` | 增加 STT/TTS 意图检测、附件/文本澄清与计划注入 |
| `backend/api/app/agent/turn_mode.py` | 新音频工具和既有媒体工具统一强制 ReAct |
| `backend/api/app/agent/react.py` | 将 STT/TTS 纳入隔离线程工具集合 |
| `backend/api/app/agent/harness.py` | 分别交付 STT 转写、TTS 播放与既有音色克隆结果 |
| `frontend/src/components/agent/ToolCard.vue` | 增加安全转写卡、TTS 播放器和成功自动展开 |
| `frontend/src/views/Agent.vue` | 新工具中文名、实时/历史事件回放和脱敏控制台日志 |
| `frontend/src/api/mockData.ts` | mock 工具清单与后端四项媒体能力对齐 |
| `frontend/src/components/modals/McpToolModal.vue` | 增加 STT/TTS 参数、返回和安全契约展示 |
| `docs/AI测试与评估平台-API.md` | 更新 MCP、WS 事件和安全返回契约 |
| `docs/AI测试与评估平台-Agent开发文档.md` | 记录路由优先级、交付 UX 和本次文件清单 |

## 35. 语音合成朗读稿抽取（2026-08-21）

`audio.speech_synthesis` 增加朗读稿抽取：模型未显式给出 `text` 时，从用户原话剥离「帮我输出音频 / 朗读一下」等命令前缀，以及引号、冒号后的内容作为播报文本，避免把命令整句合成语音；`SPEECH_SYNTHESIS_HINTS` 补充「输出音频 / 生成音频 / 读出来 / 念出来 / 帮我朗读」等中文意图词。有 wav/mp3 参考音频时仍优先走音色克隆，不改变既有路由。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/mimo_audio.py` | 新增 `extract_tts_text` 朗读稿抽取；`arguments_for_speech_synthesis` 接入抽取 |
| `backend/api/app/agent/plan.py` | `SPEECH_SYNTHESIS_HINTS` 扩充中文命令词 |
| `backend/api/tests/test_mimo_audio.py` | 朗读稿抽取与参数绑定单测 |

## 36. 修改代码文件与作用清单（2026-08-22 CoT 一步一步出结果）

空等约 30 秒才出思考卡的根因：自然语言先打规划 JSON（mimo `thinking.disabled`），整包返回后再二次闲聊流式。这不是 CoT。

CoT（Wei 2022 / 流式 reasoning）：**同一轮生成**里先逐步吐出中间推理步骤，再给出最终结果。实现上即 ReAct `stream_mcp_step`：`reasoning_content` 增量 → 思考卡，正文 JSON 的 `reply`/`tool` 在步骤完成后出现。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/plan.py` | 自然语言跳过 `_call_plan_model`，种子 `loop=react`，inject 仍挂生图/配音 |
| `backend/api/app/agent/turn_mode.py` | NL 一律 `REACT_ONLY`；`uses_react_llm` 为 True |
| `backend/api/app/agent/harness.py` | 去掉规划期思考回调与 `_chat_reply` 二次生成 |
| `backend/api/app/agent/persona.py` | ReAct 提示词要求一步一步思考后再给 reply |
| `backend/api/tests/test_harness.py` | 问候/离题/人像改为断言不打规划模型 |
| `backend/api/tests/test_voiceclone.py` | 问候+音频仍 inject，但不 mock 规划模型 |
| `docs/AI测试与评估平台-Agent开发文档.md` | §5 / §6 改为同一轮 CoT |

## 37. Harness 编排与上下文入口收口（2026-08-22）

旧 `app.agent.harness`、`app.agent.react`、`app.agent.plan` 和 `app.agent.context` 已删除，不保留导入兼容壳。下面映射覆盖本文早期变更记录中出现的历史路径；历史章节描述的是当时改动，当前线上代码必须以本表为准。该迁移不改变 API.md 定义的 WS/REST JSON。

| 历史路径 | 当前路径 | 职责 |
| :--- | :--- | :--- |
| `backend/api/app/agent/harness.py` | `backend/api/app/harness/orchestration/session_runtime.py` | 单回合编排、异步调度、确认卡、确认回执、`/stop` 与流式交付 |
| `backend/api/app/agent/react.py` | `backend/api/app/harness/orchestration/react_adapter.py` | ReAct 产品规格组装、循环入口和测试适配锚点 |
| `backend/api/app/agent/plan.py` | `backend/api/app/harness/orchestration/plan_runtime.py` | PlanArtifact、L0、斜杠模板、媒体工具注入与补规划 |
| `backend/api/app/agent/context.py` | `backend/api/app/harness/context/history.py`、`meter.py`；`memory/session_context_store.py`；`orchestration/compaction_runtime.py` | 历史只经 MemoryPort；计量无 I/O；会话 ORM 与压缩游标归 Memory；模型摘要归编排 |

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/session_runtime.py`、`react_adapter.py`、`react_loop.py` | 删除旧 Agent 双轨后承接运行总控、ReAct 产品适配和循环动态依赖 |
| `backend/api/app/harness/orchestration/plan_runtime.py` | 删除旧 Agent Plan 后承接规划能力唯一正文 |
| `backend/api/app/harness/context/history.py`、`meter.py`、`memory/session_context_store.py`、`orchestration/compaction_runtime.py` | 删除旧 Agent Context 后按六层职责唯一承接历史、计量、存储和压缩 |
| `backend/api/app/routers/ws.py`、`routers/sessions.py`、`agent/reflect.py` | 路由和复核模块直接依赖新编排层 |
| `backend/api/tests/harness/tracing/test_contracts.py` | 断言旧模块不存在、WS 接入新会话总控且 Context 不得越层导入 I/O |
