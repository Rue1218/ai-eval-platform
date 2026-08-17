# AI 测试与评估平台 — 设计规范

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.2 |
| 对应 PRD | V1.6.3（唯一产品权威） |
| 对应开发计划 | V1.0 |
| 撰写日期 | 2026-08-17 |
| 最近修订 | 2026-08-17：补齐浮层（Toast/对话框/抽屉）与 Agent 对话组件 |
| 技术栈（PRD） | Vue3 + Naive UI、Python FastAPI、PostgreSQL、WebSocket、Docker Compose、go-stress-testing |
| 适用范围 | V1.0 前端 `web/` |

---

## 0. 文档地位（先读）

| 层级 | 文档 | 管什么 | 不管什么 |
| --- | --- | --- | --- |
| **L0 产品** | `AI测试与评估平台-PRD.md` V1.6.3 | 范围、模块、角色、状态机、确认卡字段、WS 事件、MCP 工具、REST、路由表、验收 | 像素、配色、动画曲线 |
| **L1 视觉参考** | `VUE-PROTOTYPE-DESIGN.md`、`DESIGN-SPEC.md`、`AGENT-TOOL-DESIGN.md` | 薄荷绿毛玻璃、深空蓝暗色、对话气泡/思考卡/工具卡形态、侧栏骨架、令牌与动画节奏 | 不得引入其产品能力 |
| **L2 本文** | 本设计规范 | 把 L0 的页面画成 L1 的样子；Naive 主题；确认卡与表单同一套字段 | 不得扩范围、不得改字段名 |

**冲突裁决**

1. 和 PRD 不一致 → **改本文，不改 PRD**。要改范围先改 PRD。  
2. 视觉参考与 PRD 功能冲突 → **丢掉参考文档里的功能，只留观感**。  
3. Naive UI 默认皮肤与令牌冲突 → **覆盖 Naive 主题，令牌优先**。

### 0.1 视觉参考允许带走的

- 设计令牌、明暗 `data-theme`、body 薄荷绿波谷渐变、侧栏毛玻璃与深色右侧大圆角  
- 260px ↔ 72px 侧栏、主区 18px 圆角悬浮  
- `/agent` 对话列最大 760px、气泡尖角、思考卡、工具卡 pending→done、进度条吸附输入区上方  
- 字号阶梯、等宽数字、聚焦环、黑底白字发送/确认钮  
- 工具卡「输入 / 输出 / 结果」折叠形态（用来展示本产品的 `tool_call` / `tool_result`）

### 0.2 视觉参考禁止带进本项目的（PRD 4.2 / 非本产品）

| 参考文档里的东西 | 原因 |
| --- | --- |
| Ask / Plan / Bypass、改系统提示词、记忆面板 | PRD：固定人设；无改系统提示词页 |
| 外部 MCP、read/write/bash/web_search 工具集、SSE、socket.io 事件名 | PRD：仅内部 MCP；WS + `ws_ticket` |
| 冒烟 / 接口 / UI / 移动 / 兼容等胶囊与模块色 | 本产品模块是 Agent / Benchmark / RAG + 共享压测 |
| 多项目选择器、ForgeModal 五面板当产品功能 | V1 单团队；协议档在 `/admin/profiles` |
| 旧仓路由 `/targets` `/recordings` `/execute` 等 | 不是 PRD 5.8 |

---

## 1. 产品结构（摘自 PRD，UI 必须长这样）

面向单一团队。主入口 **WebSocket Agent**，表单为辅。三个模块 + 共享压测：

| 模块 | 职责 | 对应页面 |
| --- | --- | --- |
| A. Agent | 会话、拆解、确认卡、进度；**不执行长任务** | `/agent` |
| B. Benchmark | 自定义文本集、三协议、规则分 / Judge、对比与基线 | `/datasets` + 确认卡/`POST /api/tasks` + `/reports/:id` |
| C. RAG | 内置 LightRAG 或外部 OpenAI Chat RAG | `/kb` + 同上 |
| 共享压测 | 质量 `succeeded` 后压同一推理 / query | 任务页 + Agent 进度区；配置在 `/admin/stress` |

Compose：`web` `api` `worker` `postgres` `lightrag` `stress`。

V1 **不允许**一个任务同时跑 Benchmark 和 RAG。要两份报告就下两单。

---

## 2. 角色与壳层权限（PRD 2.1）

| 能力 | 管理员 | 工程师 | 只读 |
| --- | --- | --- | --- |
| 登录、看报告、打开未过期分享链接 | ✓ | ✓ | ✓ |
| Agent 对话、创建任务；取消自己的非终态任务 | ✓ | ✓ | |
| 取消他人任务 | ✓ | | |
| 上传/删除自己的集与知识库文档、确认用例 | ✓ | ✓ | |
| 配置协议档、Key、Agent 后端、裁判、白名单、预算、并发 | ✓ | | |
| 冻结/解冻基线、知识库标核心、删他人资产 | ✓ | | |
| `dev`/`test`/`staging` 压测 | ✓ | ✓ | |
| `prod` 压测 | 二次确认 | 另一名管理员或工程师会签 | |
| 开户、停用、改角色、重置密码 | ✓ | | |

侧栏按上表 **不渲染** 无权限入口。误入路由守卫回 `/tasks`（只读）或 `/agent`（其余），Toast 用 `UNAUTHORIZED` 文案，不整页 403。

登录：HttpOnly Cookie 12h 可续；密码 ≥8 位含字母和数字；首次引导管理员必须改密。WebSocket 只用短票，见 §6。

---

## 3. 信息架构（PRD 5.8，路由不得增减）

技术栈：**Vue3 + Naive UI**。全站在 `n-config-provider` 下；对话流没有 Naive 控件的部分用自定义组件，**确认卡字段必须用 Naive 表单控件**，以便和 `POST /api/tasks` 双入口同一套（F-AGT-07）。

| 路由 | 页（PRD 原文） | 角色 | 侧栏是否出现 |
| --- | --- | --- | --- |
| `/login` | 登录 | 全员 | 否 |
| `/agent` | 会话列表 + 对话 + 确认卡 + 进度 | 管理 / 工程师 | 是，名「智能体」 |
| `/tasks` | 任务表 | 全员（只读看） | 是 |
| `/reports/:id` | 报告与对比 | 全员 | 否（从任务行、`report` 事件进入） |
| `/datasets` | 集 | 管理 / 工程师 | 是 |
| `/cases` | 用例确认 | 管理 / 工程师 | 是 |
| `/kb` | 知识库与黄金 QA | 管理 / 工程师 | 是 |
| `/admin/profiles` | 协议档 / Key / Agent / 裁判 | 管理员 | 是 |
| `/admin/stress` | 白名单、单价、并发、预算默认 | 管理员 | 是 |
| `/admin/users` | 开户 | 管理员 | 是 |

无独立「改系统提示词」页。  
**不新增** `/reports` 列表路由：报告入口是任务表「查看报告」和 Agent 的 `report` 事件。分享 7 天链接可未登录只读打开 `/reports/:id?share=`。

登录后落地：工程师/管理员 → `/agent`；只读 → `/tasks`。

侧栏分组建议（仅导航分组，不是产品模块）：

```
评测
  智能体      /agent
  任务中心    /tasks
  数据集      /datasets
  用例        /cases
  知识库      /kb
管理          （仅管理员）
  协议档      /admin/profiles
  压测治理    /admin/stress
  账号        /admin/users
```

---

## 4. 任务状态机（PRD 3.3，全站同一套徽章）

```
queued → running → succeeded
                 → failed
                 → cancelled
                 → awaiting_case_confirm → succeeded（确认入库）
                                         → cancelled（拒绝或 72h）
```

| 状态 | 含义 | 谁能改 | 徽章 |
| --- | --- | --- | --- |
| `queued` | 等待 worker | 创建者/管理员可取消 | 灰 |
| `running` | worker 或 stress 占用 | 同上。评测：当前样本结束后停。压测：**立即停** | 靛蓝 + 转圈 |
| `awaiting_case_confirm` | 用例已生成未确认 | 创建者确认 → succeeded；取消或 72h → cancelled | 琥珀 |
| `succeeded` / `failed` / `cancelled` | 终态 | 可「复制为新任务」（重跑=新任务拷配置） | 绿 / 红 / 灰 |

压测子任务 `parent_task_id` 指向质量任务。质量成功且 `with_stress=true` 时 **自动入队**，不弹第二张确认卡。`prod` 除外：未会签则质量报告保留、压测保持 `queued` 并通知（M4）。

会话内同时最多 1 个 `queued` / `running` / `awaiting_case_confirm`（**含压测子任务**）。父任务 succeeded 后子任务占槽。平台 `max_running_tasks` 默认 3，超限新任务保持 queued。

`kind` 仅四选一：`benchmark` / `rag` / `testcase` / `stress`。

---

## 5. 页面设计（按 PRD 功能编号）

视觉：工作台用 Naive 表格/表单/卡片，外层 AppShell 用参考文档的侧栏+悬浮主区。页内不要第二套 H1（标题在顶栏）。

### 5.1 `/login`（F-CM-03）

居中登录卡。产品全称「AI 测试与评估平台」。用户名 + 密码。失败不区分「用户不存在 / 密码错误」。引导管理员强制改密。Cookie 会话，前端不把长期 token 写入 `localStorage`。

### 5.2 `/agent`（F-AGT-01～06、09）

PRD 规定本页四块：**会话列表 + 对话 + 确认卡 + 进度**。布局可参考原型「左会话 / 右对话」，不是再造 TestPilot 工坊产品。

```
┌─────────────┬──────────────────────────────────┐
│ 会话列表     │ 对话流（thought / tool_* / 气泡） │
│             │ 确认卡（confirm → confirm_ack）   │
│             │ 进度区（progress；压测为曲线）     │
│             │ 输入：文本 + 附件                  │
└─────────────┴──────────────────────────────────┘
```

**会话列表**：每用户可多开；当前会话若已有非终态长任务，列表项显示状态徽章。点击切换 `session_id`。

**对话**：

- Agent 人设固定为资深评测工程师：先澄清再下单；不绕过白名单与会签；不执行用户要求的任意代码（F-AGT-05）。  
- 管理员指定 **一个** Agent 后端协议档（F-AGT-06）。输入栏只读展示该模型名，**无**用户切模型、无思考强度、无 Ask/Plan/Bypass。  
- 上下文最近 20 条，超出丢最旧；系统提示词始终保留（无 UI 可改）。  
- 短工具同步调用，长任务只通过确认卡 → `task.create`。工具卡标题用中文（见 §6.2），不要把 MCP 函数名直接给用户。

**确认卡**：见 §6，未确认不入队。

**进度**：`progress` 的 `done/total`、`percent?`、`message`。长任务同时在进度区可见。压测（M4）在此展示 QPS/RT/错误率曲线（F-ST-03）。取消按钮文案：评测「当前样本结束后停止」；压测「立即停止发压」。

**附件**（PRD 5.1.3）：先 `POST /api/files` 得 `file_id`，再放进 `user_message.attachments[]`。单文件 ≤20MB；类型仅 PRD/OpenAPI/Excel/JSONL/CSV/PDF/MD/TXT/HTML。

**快捷提示**（可选，非 PRD 功能）：输入区上方最多 4 个芯片，文案只能对应本产品 `kind`——「生成用例」「基准评测」「RAG 评测」「先评后压」。点击只预填一句话，仍须走澄清 + 确认卡。禁止冒烟/接口/UI 等旧胶囊。

**解读**（F-AGT-08，P1/M4）：仅当已有 `report_id`（从报告页「在对话中解读」带来）时，Agent 调评测 Skill，不重跑。

### 5.3 `/tasks`（F-CM-01）

任务表。筛状态、kind。列：id、kind、状态、进度、关联集/KB、创建者、时间。行操作：详情（`task_events` 时间线）、取消（权限按 2.1）、复制为新任务、打开 `/reports/:id`。只读无写操作。压测行显示 `parent_task_id`；running 时可看 QPS（M4）。

### 5.4 `/reports/:id`（F-CM-02，M2 起）

对比：profile + dataset/kb 版本 + 时间。1–5 个协议档并排。导出 Markdown。分享 7 天。KPI 用等宽数字。

- Benchmark：主指标 exact/contain/regex/rouge_l/bleu（每集一种，默认 contain）；失败率；失败样本表。基线：管理员冻结某次 succeeded；同 dataset 版本 + 主指标才能对比（F-BM-07）。  
- RAG：Hit Rate@K / MRR / Recall@K（K 默认 5，可配 1–20）；答案 contain；无 id 样本不进 Hit 分母，页脚必须写明。退化 ≥5pp 报告内标红（F-RAG-06，M3 不发通知）。  
- Judge（F-BM-08，P1/M3）：1–5 分 + 理由；裁判档 = 被测时警告、不拦截。  
- 压测报告（M4）：QPS、RT、错误率、TTFT/TPOT/tokens/s（模型 SSE）；未填 `sla_p99_ms` 不出「是否达标」；填了则拐点=首次 P99>SLA 或错误率≥1%。费用按父任务 usage 单价估算。

### 5.5 `/datasets`（F-BM-03/04/05）

JSONL/CSV UTF-8；列 `question,reference,context?`；覆盖上传版本 +1；≤50MB、≤2 万行。每集一种主指标，默认 contain。表单「发起评测」字段 = 确认卡 `benchmark` 段（F-AGT-07）。待补全行单独可见，**不进评分分母**。

### 5.6 `/cases`（5.4.1 / 5.4.2）

用例生成结果：状态 `generated` → 确认页。自检红字：无核心正向、缺约束反向。规模上限提示拆分，禁止灌水。确认入库 → 任务 `succeeded`；拒绝或 72h → `cancelled`。导出 `xlsx|xmind`。映射缺口进待补全。P1 的 Postman/MD 输入本周期不做。

### 5.7 `/kb`（F-RAG-01～05）

内置 LightRAG：上传建索引，`doc_id`=UUID。查询走原生 `query`，**不伪装成 OpenAI Chat**。模式 naive/local/global/hybrid，任务内 1–4 个，默认 hybrid。外部 RAG：仅 Chat Completions。黄金 QA：`question,reference,expected_doc_ids[]?`，≤1 万条，版本 +1。表单「发起 RAG 评测」= 确认卡 `rag` 段。过程可视化（F-RAG-07）V1 不做。

### 5.8 `/admin/profiles`（F-BM-01，F-AGT-06）

协议档 CRUD：`openai_chat` / `openai_responses` / `anthropic_messages` + base_url + 模型名 + 加密 Key。Key **只写不回显**，变更写审计。指定唯一 Agent 后端。可标裁判档。连通性检查不把 Key 打进前端日志。

### 5.9 `/admin/stress`（F-ST-05、F-CM-06、3.4）

host 白名单；默认 QPS≤500、时长≤30min；单价 /1k tokens；`max_running_tasks`（默认 3）、`max_inflight_model_calls`（默认 8）；任务默认 `max_usd`（默认 5）；`prod` 会签人。无白名单的压测不得进入 running。通知开关（企微/邮件/Webhook）M4 可放本页，默认关（F-CM-05）。

### 5.10 `/admin/users`（F-CM-03）

开户、停用、改角色、重置密码。角色仅管理员 / 工程师 / 只读。

---

## 6. 确认卡（F-AGT-04，字段以 PRD 5.1.2 为准）

未确认不入队。`confirm` 事件 payload 即确认卡 JSON；用户 `confirm_ack { ok, patch? }`。

视觉可参考原型 AskCard（760px、圆角 14px、上滑入场），**控件用 Naive**，与 `/datasets` `/kb` 抽屉同一 field schema。

### 6.1 字段（不得改名、不得增减必填语义）

| 字段 | 必填 | UI |
| --- | --- | --- |
| `kind` | 是 | 只读展示。四选一：`benchmark` / `rag` / `testcase` / `stress`（`stress` 一般不手选） |
| `profile_ids[]` | `benchmark` 必填 | 多选 1–5 个被测协议档（无 Key）。`rag` 打外部 Chat 时 1 个「RAG 服务」档 |
| `dataset_id` | `benchmark` 必填 | 下拉，含版本与行数 |
| `kb_id` + `gold_qa_id` | `rag` 必填 | 双下拉（内置或外挂都要黄金 QA） |
| `rag_mode` | `rag` 且目标为 LightRAG | 多选 1–4，默认 `["hybrid"]` |
| `run` | 评测必填 | 折叠：`sample_size` 默认 min(1000,全集)、`concurrency` 4、`timeout_s` 60、`retry` 1、`temperature` 0、`max_tokens` 1024、`system_prompt` 可选空 |
| `with_stress` | `benchmark`/`rag` 必填 | 开关，默认 false |
| `stress` | `with_stress` 时必填 | `env`, `qps`, `duration_s`, `sla_p99_ms?` |
| `case_source` | `testcase` 必填 | `file_id` 或粘贴文本 |

`prod` + 压测：卡上展示会签人；未会签不得把压测设为 running。  
本会话已有非终态任务（含压测子任务）时，确认按钮禁用并说明占槽。

标题：确认基准评测 / 确认 RAG 评测 / 确认生成用例 / 确认压测。  
主按钮「确认并开始」用参考文档的黑底白字；次按钮「取消」→ `{ ok: false }`。

校验错误留在卡内：`VALIDATION` `WHITELIST` `NEED_APPROVAL` `CONCURRENCY` `BUDGET_EXCEEDED`。

---

## 7. WebSocket（F-AGT-01/02，事件名以 PRD 5.1.3 为准）

登录后 `POST /api/auth/ws-ticket`（5 分钟）→ `GET /ws/agent?ticket=` 升级。**不用长期 JWT 进 query**。心跳 30s；重连带 `session_id` + `last_event_id` 补发。

公共头：`event`, `session_id`, `task_id?`, `event_id`（单调）, `ts`。

### 7.1 服务 → 前端

| event | payload | 渲染（观感可参考原型，事件名不可改） |
| --- | --- | --- |
| `thought` | 短文本 | 思考卡追加 |
| `tool_call` | `name`, `arguments` | 工具卡 pending |
| `tool_result` | `name`, `ok`, `data` 或 `error` | 工具卡 done |
| `confirm` | 确认卡 JSON | 确认卡，等 `confirm_ack` |
| `progress` | `percent?`, `done`, `total`, `message` | 进度区 |
| `report` | `report_id` | 报告入口 → `/reports/{id}` |
| `error` | `code`, `message`（可给用户看） | 错误条 + Toast |
| `pong` | 心跳 | 不渲染 |

### 7.2 前端 → 服务

| 消息 | 体 |
| --- | --- |
| `user_message` | `{ text, attachments[]? }` |
| `confirm_ack` | `{ ok, patch? }` |
| `cancel_task` | `{ task_id }` |

禁止使用参考文档的 `thinking` / `token` / `chat:send` / `tool_call_start` 等旧事件名。

### 7.3 短工具中文名（内部 MCP 5.5）

| name | 卡片标题 |
| --- | --- |
| `model.list` | 列出协议档 |
| `dataset.list` | 列出数据集 |
| `kb.list` | 列出知识库 |
| `task.get` | 查询任务 |
| `report.get` | 读取报告 |
| `task.create` | 创建任务 |
| `task.cancel` | 取消任务 |
| `testcase.confirm` | 确认用例入库 |

长工具 `testcase.generate` / `benchmark.run` / `rag.evaluate` / `stress.run` 由 worker（压测再下发 stress 容器）执行，前端只收 `progress` / `report` / `error`。

错误码用户文案：

| code | 文案 |
| --- | --- |
| `UNAUTHORIZED` | 没有权限做这件事 |
| `VALIDATION` | 请检查标红字段 |
| `NOT_FOUND` | 资源不存在或已删除 |
| `BUDGET_EXCEEDED` | 已达本任务预算上限 |
| `CONCURRENCY` | 平台并发已满，任务保持排队 |
| `WHITELIST` | 目标不在压测白名单 |
| `NEED_APPROVAL` | 等待会签后才能发压 |
| `UPSTREAM` | 被测接口失败，详见样本错误 |
| `TIMEOUT` | 超时 |
| `INTERNAL` | 内部错误，请重试或联系管理员 |

---

## 8. 视觉令牌（参考三文档，服务于上面的页面）

文件：`web/src/styles/tokens.css`。主题：`document.documentElement.setAttribute('data-theme', 'light'|'dark')`，禁止用 Vue 响应式改写 CSS 变量。

### 8.1 浅色 / 深色（从参考文档 1:1 拷贝键名）

浅色：`--bg-main #FFFFFF`，`--bg-elevated #F4F8F8`，`--text-primary #111827`，`--accent-ai #6366F1`，成功/警告/错误/信息 `#10B981 / #F59E0B / #EF4444 / #3B82F6`。  
深色：`--bg-main #020617`，`--accent-ai #818CF8`。完整表见参考 `DESIGN-SPEC.md` / `VUE-PROTOTYPE-DESIGN.md` §2，实现时整段迁移，不要手改色值。

body 薄荷绿波谷渐变 + 径向光晕 + 9s 饱和度呼吸；侧栏与 body 同一段渐变。深色侧栏右侧 `border-radius: 0 24px 24px 0`。`prefers-reduced-motion` 下关闭装饰动画。

全局隐藏滚动条；工具卡代码块保留 6px 条。数字加 `.mono` / `.num`。

### 8.2 本产品模块色（替换参考文档的 smoke/api/ui）

`--t-*` 淡底 / `--c-*` 深字。禁止在新代码使用 smoke、api、ui、perf、compat、mobile、load。

| 页面 | 淡底 | 深字 | 浅色建议 |
| --- | --- | --- | --- |
| `/agent` | `--t-agent` | `--c-agent` | `#DDD6FE` / `#7C3AED` |
| `/tasks` | `--t-tasks` | `--c-tasks` | `#E0E7FF` / `#4F46E5` |
| `/reports/:id` | `--t-reports` | `--c-reports` | `#EDE9FE` / `#6D28D9` |
| `/datasets` | `--t-datasets` | `--c-datasets` | `#DBEAFE` / `#1D4ED8` |
| `/cases` | `--t-cases` | `--c-cases` | `#D1FAE5` / `#047857` |
| `/kb` | `--t-kb` | `--c-kb` | `#CFFAFE` / `#0E7490` |
| `/admin/profiles` | `--t-profiles` | `--c-profiles` | `#FEF3C7` / `#B45309` |
| `/admin/stress` | `--t-stress` | `--c-stress` | `#FCE7F3` / `#BE185D` |
| `/admin/users` | `--t-users` | `--c-users` | `#F3F4F6` / `#4B5563` |

kind 色：`benchmark`→datasets，`rag`→kb，`testcase`→cases，`stress`→stress。

### 8.3 骨架尺寸（参考原型，可整段抄 CSS）

```
.app: 260px 1fr；折叠 72px；过渡 .28s cubic-bezier(.4,0,.2,1)
.main: margin 10px 10px 10px 14px；圆角 18px
.topbar: 高 64px；页标题 20px/600
nav-item: 高 44px，圆角 16px
/agent 内容区 padding 0
对话列 max-width 760px
```

聚焦环：`border-color: var(--accent-ai); box-shadow: 0 0 0 3px rgba(99,102,241,.15)`。  
发送/确认主按钮：浅色黑底白字，深色反相（参考签名色，不要改成靛蓝）。工作台普通主按钮可用 `--accent-ai`。

Agent 导航状态点（可选）：任务 `running` 蓝呼吸 / `succeeded` 绿 / `failed` 红 / `cancelled` 或断线 橙。语义对齐本产品任务状态，不要用原型的「生成中」冒充评测 running。

字体：Inter + Noto Sans SC + Noto Serif SC + JetBrains Mono。欢迎句可用衬线大标题，文案必须是本产品名，禁止「TestPilot」。

### 8.4 Naive UI 主题

`NConfigProvider` 包住整站（含 `/agent` 里的表单）。从 CSS 变量生成 overrides：

| Naive 键 | 令牌 |
| --- | --- |
| `primaryColor` | `--accent-ai` |
| `successColor` / `warningColor` / `errorColor` / `infoColor` | `--accent-*` |
| `textColorBase` / `2` / `3` | `--text-primary/secondary/tertiary` |
| `bodyColor` / `cardColor` | `--bg-main` / `--bg-elevated` |
| `borderColor` | `--border-subtle` |
| `borderRadius` | 10px（卡片 16px 单独覆盖） |
| `fontFamily` / `fontFamilyMono` | Inter / JetBrains Mono |

`n-data-table` 表头 11px 大写、行悬停 `--row-hover`。不要引入 Tailwind / UnoCSS / Element Plus。

图表用 Chart.js，颜色取令牌；压测三曲线（QPS/RT/错误率）须能与 Grafana 用同一 `task_id` 对上（M4）。不要 ECharts。

---

## 9. 品牌文案

| 用途 | 文案 |
| --- | --- |
| 产品全称 | AI 测试与评估平台 |
| 短名（侧栏） | AI Eval |
| 副标 | TEST & EVAL |
| Logo | 字母 **A**（不要 T） |
| 登录副文案 | 对话完成：用例（可选）→ Benchmark 和 / 或 RAG →（可选）压测 → 报告 |
| 人设 | 资深评测工程师（固定，无设置项） |

浏览器标题：`{页名} · AI 测试与评估平台`。

---

## 10. Vue 落地（目录对齐开发计划）

```
web/src/
├── styles/     tokens.css  base.css  animations.css  layout.css  agent.css  platform.css
├── naive-theme.ts
├── stores/     theme  auth  agent  nav
├── api/        http.ts  ws.ts          # REST 仅 PRD 5.9；WS 仅 5.1.3
├── components/layout/  agent/          # agent: SessionList ChatStream ConfirmCard ProgressDock
└── views/      Login Agent Tasks Report Datasets Cases Kb AdminProfiles AdminStress AdminUsers
```

Store：`theme`（data-theme、侧栏折叠）、`auth`（角色，无 JWT 明文）、`agent`（session_id、last_event_id、确认卡、进度）。无多项目 store，无用户可选模型 store。

REST 只实现 PRD 5.9 列出的路径，不发明 `/api/chat/completions` 等旧接口。

---

## 11. 按里程碑的 UI（开发计划，范围仍是 PRD 第 7 节）

| 阶段 | 可演示（PRD 门禁） |
| --- | --- |
| M0 | Compose 起 web+api+postgres；登录页能开 |
| M1 | 登录后对话下单空跑（kind 可 mock succeeded）；断线按 event_id 续；管理员加协议档；确认卡未确认不入队 |
| M2 | 两协议档 + ≥20 条 JSONL，对话出 contain 对比报告；待补全不进分母；表单双入口；预算超限停 |
| M3 | LightRAG hybrid Hit Rate@5；外部 Chat RAG 出 contain |
| M4 | test 白名单压 2 分钟；平台曲线与 Grafana 同 task_id；解读；通知 |
| H | 不加功能 |

门禁未过禁止做下一阶段页面。

---

## 12. 验收清单

### 产品（相对 PRD）

- [ ] 路由表与 5.8 一致，无多余业务页，无改系统提示词  
- [ ] 确认卡字段与 5.1.2 一致，并与 `POST /api/tasks` 同 schema  
- [ ] WS 事件名与 5.1.3 一致；短票；重连补发  
- [ ] 一任务一种 kind；会话槽位含子任务  
- [ ] 先评后压；质量失败/取消无压测 running  
- [ ] Key 只写不回显；只读看不到 Agent 与写入口  
- [ ] LightRAG 走 query，UI 不展示成 Chat Completions  

### 视觉（相对参考文档）

- [ ] 明暗令牌、侧栏渐变、主区悬浮、760px 对话列  
- [ ] 思考卡 / 工具卡 / 确认卡形态可认出参考原型，但无 Ask/Plan/Bypass  
- [ ] 无 TestPilot 字样、无 T logo、无旧模块胶囊  
- [ ] Naive 主色 = `--accent-ai`；确认主按钮黑白签名色  
- [ ] `prefers-reduced-motion` 关闭呼吸/glow  

---

## 13. 实现时怎么查文档

1. **这个功能做不做、字段叫什么** → PRD。  
2. **这个按钮多大、什么颜色** → `VUE-PROTOTYPE-DESIGN.md` / `DESIGN-SPEC.md`。  
3. **工具卡怎样展开、失败怎样露出来** → `AGENT-TOOL-DESIGN.md` 的卡片形态；工具清单仍以 PRD 5.5 为准。  
4. **对不上** → 改 UI 去对齐 PRD，不要改 PRD 去迁就参考稿。

---

---

## 14. 浮层体系（对话框 / 弹窗提示 / 抽屉）

PRD 没有单独开「弹窗」章节，但登录改密、删除、取消任务、`prod` 二次确认、分享链接都需要浮层。**下单确认不是弹窗**：确认卡嵌在 Agent 对话流里（F-AGT-04），不要做成 `n-modal`。

禁止 `window.alert` / `window.confirm`。统一用 Naive：`n-message`、`n-dialog`、`n-modal`、`n-drawer`。

### 14.1 用哪种浮层

| 类型 | 组件 | 何时用 | 何时不用 |
| --- | --- | --- | --- |
| **Toast** | `n-message` | 短结果：保存成功、复制链接、权限不足、断线重连 | 要用户做选择；长表单；下单确认 |
| **确认对话框** | `n-dialog` | 破坏性、不可轻易撤销：删除、停用、取消运行中任务、冻结基线、`prod` 二次确认 | 创建/编辑表单；Agent 下单 |
| **表单弹窗** | `n-modal` | 需要打断当前页的短表单：开户、重置密码、首次改密、分享报告、新增协议档 | 字段与确认卡相同的「发起评测」（用抽屉，避免和对话确认卡两套模态） |
| **抽屉** | `n-drawer` 右滑 480–560px | 任务详情/事件时间线；数据集/KB 页「发起评测」（字段 = 确认卡） | Agent 页内下单（必须用对话确认卡） |
| **确认卡** | 自定义，对话流内 | 唯一的 Agent 下单 UI | 不要再套一层 Dialog |

层级（同时只开一层模态；Toast 可叠在上面）：

```
Toast / n-message     z-index 3000
n-dialog / n-modal    2000
n-drawer              1500
Agent 确认卡          在文档流内，不抢 z-index
顶栏 / 侧栏           低于浮层
```

遮罩：`rgba(0,0,0,.45)` + `backdrop-filter: blur(6px)`（参考原型 ForgeModal）。抽屉无全屏遮罩或半透明即可。`Esc` 关闭 Modal/Drawer；确认对话框必须点按钮。`prod` 会签 Dialog 点遮罩不关闭。

### 14.2 Toast（弹窗提示）

位置：视口右上，距顶 16px、距右 16px。单条最多约 3 条堆叠。默认 3s 自动关；`error` 5s 且可手动关。不要带 Key、token、stack。

| 语义 | 色 | 典型文案 |
| --- | --- | --- |
| success | `--accent-success` | 已保存；已复制分享链接；用例已入库 |
| error | `--accent-error` | 用 §7.3 错误码文案 |
| warning | `--accent-warning` | 平台并发已满，任务保持排队；裁判档与被测相同 |
| info | `--accent-info` | 正在重连会话…；压测已提交会签 |

**必须 Toast 的点**：登录失败、保存协议档、Key 变更（只说「已更新」，不回显）、复制分享链、上传成功/超 20MB、预算超限停、WS 断线/已续上、无权限、会签待处理。  
**不要 Toast 的点**：确认卡校验（红字留在卡内）；评测样本级失败（进报告失败表）；`thought` / `progress`（走对话区）。

### 14.3 确认对话框清单（`n-dialog`）

| 场景 | 标题 | 说明文案 | 主按钮 | 次按钮 |
| --- | --- | --- | --- | --- |
| 取消评测/RAG/用例生成 | 取消任务？ | 将在**当前样本结束后**停止，已完成部分保留。 | 取消任务（error） | 返回 |
| 取消压测 | 立即停止发压？ | 与评测不同，确认后**立刻**停发。 | 立即停止（error） | 返回 |
| 删除自己的数据集/文档/用例集 | 删除「{名}」？ | 不可恢复。进行中的任务不受影响，但无法再选此集。 | 删除 | 返回 |
| 管理员删他人资产 / 停用用户 | 同上 + 权限说明 | 写审计。 | 删除/停用 | 返回 |
| 冻结基线 | 冻结为基线？ | 仅同 dataset/kb 版本 + 主指标可对比。 | 冻结 | 返回 |
| 覆盖上传（版本 +1） | 覆盖上传？ | 版本将 +1，旧版本仍可用于已跑任务快照。 | 覆盖上传 | 返回 |
| `prod` 压测二次确认 | 确认对生产发压？ | 展示 env、host、QPS、时长、会签人。工程师需另一人会签。 | 提交会签 / 确认发压 | 取消 |
| 拒绝用例（→ cancelled） | 拒绝这批用例？ | 任务变为 cancelled，不入库。 | 拒绝 | 返回 |
| 退出登录 | 退出登录？ | 进行中的任务**不会**停止。 | 退出 | 返回 |

主按钮破坏性操作用 `--accent-error`；`prod` 用警告色 + 必须勾选「我确认目标在白名单」。无权限时按钮不出现，不要弹窗后再 Toast。

### 14.4 表单弹窗清单（`n-modal`）

宽度 480px（分享/改密）或 640px（协议档）。圆角 16px，标题 16px/600，底栏右对齐。

| 场景 | 字段 | 备注 |
| --- | --- | --- |
| 首次引导改密 | 新密码、确认 | 不可点遮罩关闭，直到成功（PRD 2.1） |
| 开户 | 用户名、初始密码、角色 | 仅管理员 |
| 重置密码 | 新密码 | 仅管理员；不回显旧密 |
| 新增/编辑协议档 | 名称、协议类型、base_url、模型名、Key、用途（被测/Agent 后端/裁判） | Key 空=不修改；只写不回显 |
| 分享报告 | 只读链接 + 复制；有效期 7 天 | 未登录可打开 |
| 连通性检查结果 | 成功/失败摘要 | 失败不展示 Key |

「发起 Benchmark/RAG」**不用 Modal**，用抽屉或跳转 Agent，字段与确认卡一致（F-AGT-07）。

### 14.5 抽屉

从右侧滑入，宽 520px（任务详情）或 560px（发起评测）。

- 任务详情：状态、kind、配置快照、`task_events` 时间线、报告入口、取消/复制  
- 发起评测：确认卡同款 Naive 表单，提交 `POST /api/tasks`

---

## 15. Agent 对话设计（`/agent`）

PRD：会话列表 + 对话 + 确认卡 + 进度。观感参考 `VUE-PROTOTYPE-DESIGN.md` 气泡/思考卡/工具卡，**交互与事件只认 PRD 5.1**。

### 15.1 页面结构

```
AgentView
├── SessionList          左 264px（可折叠到 0）
│     ├── 新建会话
│     └── 会话项（标题、相对时间、非终态徽章）
└── ChatMain
      ├── ChatHead       56px：会话标题 · 只读模型名 · 生成中 pill
      ├── ChatStream     消息列 max-width 760px
      │     ├── UserBubble
      │     ├── AssistantText        最终/中间自然语言
      │     ├── ThoughtCard          event=thought
      │     ├── ToolCard             tool_call → tool_result
      │     ├── ConfirmCard          event=confirm（§6）
      │     ├── ReportCard           event=report
      │     └── ErrorStrip           event=error
      ├── ProgressDock               吸附输入框上方；event=progress；M4 含压测曲线
      └── Composer                   textarea + 附件 + 发送
```

无欢迎页大标题「TestPilot」、无模式选择、无模型下拉、无外部 MCP 齿轮。空会话：一句「说明要评什么（模型 / RAG / 生成用例），我会澄清后给你确认卡。」+ 可选 4 个预填芯片。

### 15.2 对话流里有什么、没有什么

| 有 | 没有 |
| --- | --- |
| 用户气泡、Agent 文本、思考卡、工具卡、确认卡、进度坞、报告卡 | Ask/Plan/Bypass、思考强度、改系统提示词、记忆、任意代码执行 |
| 短工具同步结果 | Agent 进程里跑完 Benchmark（长任务在 worker，只推 progress） |
| 断线按 `last_event_id` 补消息 | 长期 JWT 进 WS URL |

### 15.3 消息组件规格

**用户气泡**：右对齐；背景 `--accent-ai`，白字；圆角 20px，右下 6px。字号 15px，`--font-chat`。附件以文件名芯片挂在气泡下。

**Agent 文本**：左对齐，无大色块也可；字号 16px / 行高 1.9。Markdown 可用（报告摘要）。

**思考卡**（`thought`）：参考原型 ThinkCard。标题「思考」；流式追加短文本；结束后 800ms 收起 `opacity:.55`。不是系统提示词，用户不能编辑。

**工具卡**（`tool_call` / `tool_result`）：参考原型 ToolCall。pending 旋转 +「调用中」→ done 绿/红。默认折叠，展开见 arguments / data。标题用 §7.3 中文。失败：`ok=false` 红徽章，error 给 Agent 下一轮，用户也能看见。

**确认卡**：对话流内，不是 Dialog。规格 §6。未 `confirm_ack` 前可改 `patch`；确认后变只读灰底。同一时刻每会话最多一张待确认卡。

**报告卡**（`report`）：指标 3～4 个等宽数字 + 按钮「查看报告」→ `/reports/:id`。M4 可加「在对话中解读」（F-AGT-08）。

**错误条**（`error`）：对话内红条（用户可读 `message`）+ Toast。`INTERNAL` 不展示堆栈。

**进度坞**（`progress`）：贴在输入框上方（参考原型 TaskFloat 的位置，不是其「定时任务」产品）。显示 kind 徽章、`done/total` 或 `percent`、`message`。  
- `awaiting_case_confirm`：链到 `/cases`，倒计时 72h  
- 压测 running：迷你 QPS/RT/错误率；按钮「立即停止」→ 先 `n-dialog` 再 `cancel_task`  
- 评测 running：「取消」→ 另一套 Dialog 文案（样本结束后停）

### 15.4 输入区

- 圆角 20px（对话页）/ 28px（空会话居中时可更大）；`focus-within` 用聚焦环  
- textarea 最小 44px，`--font-chat` 15px  
- 左：附件 36×36 圆钮；右：只读「Agent · {模型名}」+ 发送 40×40 圆  
- 发送：无字灰色；有字黑底白字；Agent 正在生成 thought 时可改为暂停**仅停生成**，不取消已入队任务  
- 会话占槽时：仍可聊天澄清；再触发会入队的确认卡则卡上按钮禁用并说明原因  
- 只读角色进不了本页

### 15.5 会话列表

- 新建：空会话，不调 `task.create`  
- 项：自动标题（首句截断）+ 相对时间；非终态 kind 小点  
- 切换会话：带上该会话 `session_id`，WS 不拆连接或按 PRD 重连补事件  
- 删除会话：V1 不做（PRD 未要求）；清空展示用「新建」

### 15.6 时序（实现必须按此画）

```
用户发 user_message
  → thought（思考卡）
  → tool_call / tool_result（可多轮短工具）
  → confirm（确认卡）          ※ 未 ack 不入队
  → 用户 confirm_ack
       ok=false → 卡标已取消，无任务
       ok=true  → queued，ProgressDock 出现
  → progress…（worker）
  → report 或 error
  → 若 with_stress 且质量 succeeded → 自动压测子任务占槽（prod 先会签 Dialog/通知）
```

断线：顶栏或进度坞 info 条「已断线，正在重连」，成功后按 `last_event_id` 补；任务不丢。

### 15.7 Agent 页不用的弹窗

| 不要 | 原因 |
| --- | --- |
| 用 Modal 收集确认卡字段 | PRD 确认卡在对话里 |
| 每条 tool_call 弹「是否允许执行」 | 短工具自动执行；危险下单靠确认卡 + 白名单 + 会签 |
| ForgeModal（模型/记忆/MCP/提示词） | 协议档在 `/admin/profiles` |

Agent 页允许的 Dialog **只有**：取消当前长任务、退出登录。首次改密在登录后全局 Modal，不嵌在对话里。

---

## 16. 组件对照（给前端）

| 产品名 | 实现 | 参考视觉 |
| --- | --- | --- |
| Toast | `n-message` | 右上，勿用原型自定义 toast 另搞一套 |
| 确认对话框 | `n-dialog` | 原型无，按 §14.3 |
| 表单弹窗 | `n-modal` | 尺寸/遮罩可参考 ForgeModal 容器，内容按 PRD 字段 |
| 抽屉 | `n-drawer` | — |
| 用户气泡 | `UserBubble.vue` | 原型 `.msg.user .bubble` |
| 思考卡 | `ThoughtCard.vue` | 原型 ThinkCard |
| 工具卡 | `ToolCard.vue` | 原型 ToolCall |
| 确认卡 | `ConfirmCard.vue` + Naive 表单 | 原型 AskCard 外壳 |
| 进度坞 | `ProgressDock.vue` | 原型 TaskFloat 位置 |
| 报告卡 | `ReportCard.vue` | 工作台 KPI 缩小版 |

---

*V1.2：补齐浮层与 Agent 对话组件。产品仍以 PRD V1.6.3 为准；三份参考文档只提供视觉。*
