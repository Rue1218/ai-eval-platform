# AI 测试与评估平台 — API 契约

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.49 |
| 对应 PRD | V1.13（功能唯一权威） |
| 对应设计规范 | V1.10（错误码文案、确认卡字段名、调度中心规范） |
| 对应 Agent 说明书 | `AI测试与评估平台-Agent开发文档.md` V1.5.15（LangGraph 单轮 Agent 与 WS 桥接；JSON 仍以本文为准） |
| 对应前端计划 | V1.5 |
| 对应后端计划 | V1.5 |
| 撰写日期 | 2026-08-18 |
| 本轮修订 | 2026-08-27：V1.49 协议档新增 `max_output_tokens`（Agent 单回合模型输出上限，默认 8192），WS Agent 模型调用不再硬编码输出上限。 |
| 最近修订 | 2026-08-27：V1.49 协议档新增 `max_output_tokens`（256–131072，默认 8192），创建/更新/列表/详情均支持；Agent 模型调用从协议档读取输出上限，长文档总结/导出类任务可调大避免回答被截断。2026-08-26：V1.48 同轮多调用默认串行，灰度开启后仅 `read`/`web_search`/`web_fetch` 可并行，回填按原始 `call_id`。V1.47 新增 `GET /api/agent/metrics`，不含正文/参数，不新增 WS 事件。V1.46 明确 native 一次 ToolCall 结束当前上游响应，结果回填后再请求，不新增事件名。V1.45 思考链只下发可展示摘要，隐藏 CoT（`Here's a thinking process` / `Analyze User Input`）由服务端替换，不原样推给前端。V1.44 ToolCall 在执行前持久化，新增瞬态 `tool_progress` / `tool_output_delta`，并冻结原生工具的输出 Schema、权限边界和失败恢复字段。V1.43 思考增量允许合并下发；有思考链时 `think_final` 在 `response.completed` 之前。V1.42 Direct `/help`、未知斜杠与图内防御提示在业务事件后必须再发 `response.completed`（成功 `stop`，校验/防御 `error`），结束整轮生成态。V1.41 确认卡预填与 `confirm_ack` 入队前丢掉已删除的协议档/数据集/知识库 ID，避免 Worker 再报「协议档不存在或已删除」。V1.40 `/cancel` 与 `/stress` 按 §4.4 解禁（仍走 `user_message`）：`/cancel` 取消本会话非终态任务，`/stress` 发出质量任务确认卡且 `with_stress=true`，禁止 `kind=stress`。V1.39 原生工具卡片收起态副标题统一为 `ToolCall`，不在卡片摘要区回显文件路径、命令或写入内容；详细参数仍在展开区展示。V1.38 明确原生基础 ToolCall 卡片使用英文工具名，展开区统一显示 `ToolCall` 与 `输出`，文件、命令和代码/文档结果使用行号展示；MCP/平台短工具仍按下方中文名映射。2026-08-24：V1.24 修复 Agent 附件上下文链路：服务端校验文件归属并在模型窗口解析文本、PDF、DOCX、XLSX，图片按三协议图文内容块发送；历史消息附件补齐安全元数据，前端可在刷新后继续预览。同步调整输入框内附件按钮与用户消息附件位序。V1.23 扩展 Agent 附件契约，支持图片、Word 文档与多附件拖拽上传；保留 `POST /api/files` 后再以既有 `file_id` 引用的消息链路，补充图片缩略图、PDF/文本预览与 Office 文件打开/下载说明。V1.22 修复 V1.21 遗留：§4.4 标题「仅此三条」改「仅此四条」、§9 禁止清单「第四种」改「第五种」并补四类上行事件枚举、§4.3 `tool_result.source` 语义对齐 M7 `Observation.source`（溯源标识字符串，非 short\|long 枚举）、§4.3 共享流规则补 clarify/plan/confirm 持久化广播说明、§4.4 clarify 多副本限制注明、§9 Ask/Plan 补注非 Harness plan 事件；V1.21 配合 Harness 阶段 3/4 前端联调回写契约：§3.4 `context_meter` 加 `compacted` bool；§4.4 新增 `clarify_reply` 上行事件并明确四类上行事件边界。V1.20 及更早版本沿用历史修订记录。 |
| 适用范围 | V1.0：浏览器 `web/` ↔ `api`；全域 REST + WS 接口规范 |

> V1.48（2026-08-26）：§4.3 同轮多个调用默认串行；仅当并行总开关与协议档白名单命中且脚踢线未触发时，`read` / `web_search` / `web_fetch` 可同波并行。`write` / `edit` / `bash` / `task.create` / `task.cancel` 始终串行。模型回填仍按原始 `call_id` 顺序。不新增 WS 字段。
>
> V1.47（2026-08-26）：§3.4 新增 `GET /api/agent/metrics`（进程内交错流/批次度量，不含正文与参数）；不新增 WS 字段，`segment_id` 仍不进入公共契约。
>
> V1.25（2026-08-25）：细化 ReAct `read` 的 `tool_result.data`，新增受控行范围、文件统计与短预览投影。完整 `content` 仅供服务端下一模型回合使用，禁止写入 WebSocket 事件或 ToolCard。
>
> V1.26（2026-08-25）：原生 ToolCall 为既有 `tool_call` / `tool_result` 增加必填 `call_id`，前端必须以该值关联卡片；不新增事件名，不向浏览器暴露上游协议字段或 MCP 连接信息。
>
> V1.27（2026-08-25）：协议档新增 `tool_call_mode`。仅显式选择 `native` 的 Agent 协议档向上游发送 `tools`；`legacy` 固定走严格 JSON-ReAct，禁止根据一次上游 4xx 静默猜测降级。
>
> V1.28（2026-08-25）：工具调用模式默认改为 `legacy`，存量协议档也以兼容模式迁移；只有人工验证支持 Function Calling 后才可显式切换为 `native`。原生 ToolCall 的空/重复 `call_id` 一律归一为 `UPSTREAM`，不进入工具队列。
>
> V1.29（2026-08-25）：§3.6.1 `GET /api/mcp/tools` 从音频/图像占位清单改为**平台 allowlist 内部短工具目录**（6 项：read/write/edit/web_search/web_fetch/bash），`name` 使用唯一 `tool_id`，新增可选 `tool_id`/`server_id`/`short_name`/`display_name`/`risk_level`/`execution_mode`/`timeout_s`/`requires_confirmation`/`supports_streaming` 字段；仅只读展示，不含任何连接命令或凭据。
>
> V1.30（2026-08-25）：§3.6.1 新增 `platform.tasks` 长任务桥接三工具（`task.create`/`task.status`/`task.cancel`），目录 6→9 项、server 4 组。三工具只入 PG 队列或查询，不等待 Worker 终态；`task.create` 直接入队返回 `queued` + `task_id`，会话/用户归属由平台注入（模型不可传）。
>
> V1.31（2026-08-25）：§3.6.1 新增 `GET /api/mcp/metrics`（admin 只读）——内部 MCP Host 的调用度量（按 tool_id 计数/耗时）与服务器熔断状态（按 server_id，INTERNAL/TIMEOUT/UPSTREAM 连续失败超阈值即 open，冷却自动恢复）。任务创建新增每用户活动任务配额 `max_active_tasks_per_user`（默认 5），MCP 与 REST 同一规则，超限返回 `CONCURRENCY` 并写 `task_quota_rejected` 审计。
>
> V1.32（2026-08-25）：基础 `read`、`write`、`edit`、`bash`、`web_search`、`web_fetch` 与对话拆解 `task` 改为模型原生 Function Calling 直连；仅评测任务桥 `platform.tasks` 继续作为 MCP 扩展。新增 Firecrawl 服务端配置、网页抓取安全投影和原子文件写入边界。
>
> V1.33（2026-08-25）：单回合允许多条 `assistant_message`；`response.completed` 仍为整轮结束。可选 `interim=true` 表示阶段叙述（计划/下一步），不是 Observation 原文，不得结束生成态。清单复用 `plan.slots.steps` 与 `task` 的 `tool_result`，不新事件。
>
> V1.37（2026-08-26）：`read` 预览按完整行截取（最多 4000 字符），禁止半行截断；`next_offset` 可作为 `offset` 别名。相同窗口重复 read 只执行一次。
>
> V1.36（2026-08-25）：`GET /api/sessions/{id}/messages.context_meter` 由服务端按窗口消息计算，不再返回 `null`。字段仍为 §3.4 既有形状（`messages`/`window`/`total_tokens`/`max_tokens`/`compacted` 等）；前端只读，禁止按条数自算。
>
> V1.35（2026-08-25）：对话确认卡由 LangGraph `reflect` 在 `delivery=confirm` 时发出（TaskSpec，`kind` 不得为 `stress`）；WS 短票 jti 用 Redis 单次消费；压测由 Worker 下发 stress 容器，曲线仍只走 `GET /api/tasks/{id}/stress-series`。
>
> V1.34（2026-08-25）：原生工具回传模型的单条结果上限统一为 8,000 字符（`read`/`bash`/`web_*` 对齐）；未读完时模型正文携带 `next_offset`。ToolCard 预览与 WS 投影不变。
>
> V1.44（2026-08-26）：ToolCall 在执行前落库，新增 `tool_progress` 与 `tool_output_delta` 瞬态帧；前者表达校验/执行/收尾阶段，后者仅传输服务端受控窗口内的行级输出。它们不落库、不占 `event_id`、不参与断线补发；`tool_result` 仍是唯一持久化终态。原生工具的输出 Schema、权限边界与恢复策略以 §4.3.1 为唯一契约。

---

## 0. 文档地位

| 层级 | 文档 | 管什么 |
| --- | --- | --- |
| L0 | PRD V1.6.5 | 做不做、字段语义、状态机、事件名、错误码枚举 |
| L1 | **本文** | 路径、方法、请求/响应 JSON、鉴权、前后端谁调用 |
| L2 | 前端/后端开发计划 | 哪一周实现本文哪一节 |

**冲突裁决**

1. 与 PRD **功能/字段名/事件名** 冲突 → **改本文**，不改 PRD。  
2. PRD 5.9 是摘要：正文已有、5.9 未列的路径，由本文补全，**不算新产品**。  
3. 与前端/后端计划冲突 → **改计划对齐本文**。  
4. 内部 MCP、stress `/metrics` 浏览器 **不得** 直连；仅列在第 7、8 节给后端。

本文冻结此前计划中的「周三待定」：

| 待定项 | 本文裁决 |
| --- | --- |
| 会话 REST | **方案 A**：`/api/sessions` |
| Hit@K 的 K | `run.k`，默认 5，范围 1–20；**不**新增确认卡必填列 |
| Judge 开关 | `run.use_judge`，默认 `false`；裁判档来自协议档用途=`judge` |
| 心跳 | 传输层 WebSocket ping/pong；应用层仅服务端 JSON `pong`。客户端 **不** 发明 JSON `ping` 事件 |

---

## 1. 通用约定

### 1.1 传输

| 项 | 约定 |
| --- | --- |
| REST 前缀 | `/api` |
| WS | `GET /ws/agent?ticket=`（**无** `/api` 前缀，与 PRD 5.9 一致） |
| 协议 | HTTPS/WSS 生产；开发 HTTP + 同域反代 |
| Content-Type | JSON `application/json`；上传 `multipart/form-data` |
| 时间 | ISO-8601 UTC，字段名 `*_at` / `ts` |
| ID | UUID 字符串 |
| 分页 | `offset` 默认 0，`limit` 默认 50、最大 200；列表 `{ "items": [], "total": n }` |

### 1.2 鉴权

- 浏览器会话：登录成功后下发 **HttpOnly** Cookie `aieval_session`，12h，可续（滑动或显式续期由实现决定，对外表现为 12h 内活跃不掉）。  
- **禁止** 把长期 JWT 写入 `localStorage`，**禁止** 长期 token 进 WS query。  
- WS：先 `POST /api/auth/ws-ticket` 得 5 分钟短票，再升级。  
- 除注明外，REST 均需已登录 Cookie。  
- 分享报告：`GET /api/reports/{id}?share={token}` **免登录**，只读。  
- `GET /api/health` 免登录。  
- 角色：单一角色 `member`（全员同权）。未登录 401，body `code=UNAUTHORIZED`。敏感操作（如停用账号、删除基线）记录审计日志。

刷新页面后前端必须能恢复身份 → `GET /api/auth/me`（PRD 2.1 / F-CM-03 补全，5.9 未列）。

### 1.3 成功与错误

成功：HTTP 2xx，body 为资源或 `{ "items", "total" }` 或 `{ "ok": true }`。  
错误：

```json
{
  "code": "VALIDATION",
  "message": "请检查标红字段",
  "fields": { "dataset_id": "必填" }
}
```

| HTTP | code | 前端文案（设计规范 §7.3） |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | 没有权限做这件事（未登录时跳转 `/login`，可不用此句） |
| 403 | `UNAUTHORIZED` | 没有权限做这件事 |
| 400 | `VALIDATION` | 请检查标红字段 |
| 404 | `NOT_FOUND` | 资源不存在或已删除 |
| 409 | `BUDGET_EXCEEDED` | 已达本任务预算上限 |
| 409 | `CONCURRENCY` | 平台并发已满，任务保持排队（**仍 200 创建 queued 时不要用此码**；仅当实现拒绝创建时才 409。默认超限仍创建 queued，前端用 warning Toast） |
| 403 | `WHITELIST` | 目标不在压测白名单 |
| 403 | `NEED_APPROVAL` | 等待会签后才能发压 |
| 502 | `UPSTREAM` | 被测接口失败，详见样本错误 |
| 504 | `TIMEOUT` | 超时 |
| 500 | `INTERNAL` | 内部错误，请重试或联系平台维护者 |

确认卡 / 表单校验失败：`VALIDATION`，`fields` 给前端卡内红字，**不要**只靠 Toast。  
错误 body **不得** 含 Key、Cookie、stack。  
WS `error` 事件 payload 与上表同一套 `code` + `message`（可带 `fields`），HTTP 状态码只用于 REST。  
**能力未启用**（自定义斜杠、RAG、外部 MCP、页面 AI 未交付等）：一律 `VALIDATION` + HTTP **400**，禁止用 409 冒充（409 只给 `BUDGET_EXCEEDED` / `CONCURRENCY`）。  
业务代码只抛 `AppError`；禁止把未捕获异常的 `str(exc)` 或堆栈写入响应或 WS（见 AGENTS.md §5.2.1）。

### 1.4 枚举

| 名 | 值 |
| --- | --- |
| `role` | `member`（PRD 2.1 单一角色；历史三角色字段不再作为 V1.0 契约） |
| `kind` | `benchmark` `rag` `testcase` `stress` |
| `task_status` | `queued` `running` `succeeded` `failed` `cancelled` `awaiting_case_confirm` |
| `protocol` | `openai_chat` `openai_responses` `anthropic_messages` |
| `profile_usage` | `target` `agent` `judge`（被测 / Agent 后端 / 裁判；同一档可多用途，**Agent 后端全局仅一个**，见 settings） |
| `metric` | `exact` `contain` `regex` `rouge_l` `bleu` |
| `rag_mode` | `naive` `local` `global` `hybrid` |
| `stress_env` | `dev` `test` `staging` `prod` |
| `file_kind` 扩展名 | `.md` `.txt` `.html` `.pdf` `.json` `.yaml` `.yml` `.xlsx` `.xls` `.csv` `.jsonl` `.doc` `.docx` `.wav` `.mp3` `.png` `.jpg` `.jpeg` `.webp` `.gif` |

---

## 2. 前后端对应总表

目标态：浏览器前端所有业务图、表与表单均统一经由 API service 调用对应 REST/WS 接口，完成动态拉取与实时落盘。当前原型的真实接入现状与剩余静态视觉资产见 §12；不得把本表当作“后端已实现”清单。

| 模块 / 页面 | 前端功能与图表 | 调用的后端 API 接口 | 请求方法 | 权限口径 |
| --- | --- | --- | --- | --- |
| **登录 (login.html)** | 账号登录 / 首次强制改密 | `/api/auth/login`, `/api/auth/change-password` | POST | 免登录 / 成员 |
| **智能体 (agent.html)** | 会话列表 / 意图识别 / TaskSpec 下单 / 迷你拓扑坞 / 斜杠面板 / 上下文仪表 | `/api/sessions`, `/api/sessions/{id}/messages`, `/api/agent/prefs`, `/api/slash-commands`, `/ws/agent`, `/api/profiles`, `/api/datasets`, `/api/kb`, `/api/tasks`, `/api/dispatch/overview` | GET/POST/DELETE/WS | 成员 · 全员同权 |
| **调度中心 (dispatch.html)** | 调度大盘 / Worker 节点池 / 策略治理 / 分配日志流 | `/api/dispatch/overview`, `/api/dispatch/workers`, `/api/dispatch/workers/{id}`, `/api/dispatch/events`, `/api/dispatch/config`, `/api/tasks?status=queued` | GET/POST/PUT | 成员 · 全员同权 |
| **任务中心 (tasks.html)** | 24h 状态趋势 / 六态过滤表格 / 抽屉详情 / 取消与重跑 | `/api/tasks`, `/api/tasks/summary`, `/api/tasks/{id}`, `/api/tasks/{id}/cancel`, `/api/tasks/{id}/rerun` | GET/POST | 成员 · 全员同权 |
| **报告中心 (report.html)** | 报告列表 / 3合1详情 (Benchmark雷达/RAG水平柱状/压测多轴曲线) / Markdown导出 / 7天免登分享 / 冻结基线 | `/api/reports`, `/api/reports/{id}`, `/api/reports/{id}/samples`, `/api/reports/{id}/share`, `/api/reports/{id}/baseline` | GET/POST | 成员 · 全员同权 |
| **数据集工作台 (datasets.html)** | 数据集目录树 / 行内即点即改网格 / 自定义列扩展 / AI 数据集生成 | `/api/dataset-folders`, `/api/datasets`, `/api/datasets/{id}`, `/api/datasets/{id}/rows`, `/api/datasets/ai-generate`, `/api/kb` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **用例工作台 (cases.html)** | 6大策略分布图 / 用例表格编辑 / 72h倒计时 / Excel 导入导出 / 批量映射入库 / AI PRD 用例抽取 | `/api/case-folders`, `/api/case-sets`, `/api/case-sets/{id}`, `/api/case-sets/{id}/cases`, `/api/case-sets/{id}/confirm`, `/api/case-sets/{id}/cancel`, `/api/case-sets/{id}/map`, `/api/case-sets/ai-generate`, `/api/case-sets/import-template`, `/api/case-sets/{id}/import`, `/api/case-sets/{id}/export` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **知识库 (kb.html)** | 3栏工作台 / 文档与切块预览 / 4模式检索 Playground / 黄金 QA | `/api/kb`, `/api/kb/{id}`, `/api/kb/{id}/documents`, `/api/kb/{id}/documents/{doc_id}/chunks`, `/api/kb/{id}/query`, `/api/kb/{id}/gold-qa` | GET/POST/DELETE | 成员 · 全员同权 |
| **协议档与智能体 (admin-profiles.html)** | 4 Tab 架构（协议档、MCP 工具只读、技能受控说明、运行时治理）/ 连通性探活 Ping | `/api/profiles`, `/api/profiles/{id}/check`, `/api/mcp/tools`, `/api/admin/settings` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **压测治理 (admin-stress.html)** | 7天峰值 QPS 面积图 / Host 白名单表格 / 安全阈值 / 成本预算 / Prometheus `/metrics` | `/api/admin/stress/settings`, `/api/admin/stress/whitelist`, `/api/admin/stress/usage`, `/metrics` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **成员与账号 (admin-users.html)** | 4 维 KPI 卡片 / 成员搜索表格 / 24h 登录活动柱状图 / 改密与停用 | `/api/users`, `/api/users/activity-summary`, `/api/users/{id}/status`, `/api/users/{id}/reset-password`, `/api/users/{id}/audit-logs` | GET/POST/PUT | 成员 · 全员同权 |

---

## 3. REST 明细

以下请求/响应为契约。未写的字段前端不得依赖，后端不得当必填。

### 3.1 健康检查

`GET /api/health`  
免登录。

```json
{ "status": "ok", "version": "0.0.0" }
```

---

### 3.2 认证

#### `POST /api/auth/login`

```json
{ "username": "admin", "password": "********" }
```

成功 200，Set-Cookie `aieval_session`，body 与 `GET /api/auth/me` 相同。  
失败 401，**不**区分用户不存在 / 密码错误；写 `audit_logs`。  
若 `must_change_password=true`，前端立刻开改密 Modal，不可点遮罩关闭。

#### `POST /api/auth/logout`

成功 204 或 `{ "ok": true }`，清除 Cookie。进行中的任务 **不停**。

#### `POST /api/auth/change-password`

```json
{ "old_password": "********", "new_password": "********" }
```

规则：≥8 位，含字母和数字。引导初始成员首次改密时 `old_password` 为初始密。成功后 `must_change_password=false`。

#### `GET /api/auth/me`

```json
{
  "id": "uuid",
  "username": "alice",
  "role": "member",
  "must_change_password": false
}
```

#### `POST /api/auth/ws-ticket`

已登录成员可调用。5 分钟有效，一次性或短期内可重复升级（实现可允许多张未过期票，过期即废）。

```json
{ "ticket": "opaque", "expires_in": 300 }
```

未登录 401。

---

### 3.3 成员与账号管理（全员同权）

平台采用单一角色「成员（Member）」，全员同权。

#### `GET /api/users`

获取全部成员账号列表。

```json
{
  "items": [
    {
      "id": "u-01",
      "username": "alice",
      "display_name": "爱丽丝",
      "email": "alice@company.com",
      "role": "member",
      "disabled": false,
      "last_login_at": "2026-08-18T09:40:00Z",
      "last_login_ip": "10.0.0.12",
      "created_at": "2026-08-01T00:00:00Z"
    }
  ],
  "total": 1
}
```

#### `POST /api/users`

邀请 / 开户。

```json
{
  "username": "bob",
  "display_name": "鲍勃",
  "email": "bob@company.com",
  "password": "********",
  "must_change_password": true
}
```

#### `PUT /api/users/{id}` / `PUT /api/users/{id}/status`

更新成员资料或切换账号启用/停用状态（禁止停用系统中最后一名正常账号，写审计）。

```json
{ "disabled": true }
```

#### `POST /api/users/{id}/reset-password`

重置指定成员的登录密码（写入安全审计日志）。

```json
{ "password": "********" }
```

#### `GET /api/users/{id}/audit-logs`

获取指定成员近期的操作审计轨迹（开户、改密、登录、建单等）。

#### `GET /api/users/activity-summary?from=&to=`

成员与账号页的 KPI 与登录活动柱状图。数据由 `users`、`audit_logs` 聚合，不能由浏览器用示例日期计算；V1.0 不含异地登录的 AI 风险判定。

```json
{
  "range": { "from": "2026-08-17T00:00:00Z", "to": "2026-08-18T00:00:00Z" },
  "kpis": { "active_members": 8, "new_members": 1, "login_count": 24, "disabled_members": 0 },
  "login_buckets": [{ "ts": "2026-08-17T09:00:00Z", "count": 3 }]
}
```

---

### 3.4 会话（方案 A，M1 团队协作增量）

新会话默认 `visibility="private"`，仅 `owner_id` 可访问。创建者可切为
`team`，表示当前单一内部团队的正常成员均可读写；本期不是邀请制成员表。
`owner_id` 不因协作者发言而改变。会话删除是**软删除**：会话列表、历史和
WS 不再可访问，但 `messages`、`ws_events`、tasks、reports 均保留审计记录。

- `private`：只有 owner 可读写；
- `team`：所有正常成员可浏览、发送消息和连接同一会话；
- 分享设置、取消分享和软删除：只有 owner；
- 确认卡：只有 `pending_confirm_author_id` 对应成员可确认、拒绝或提交 patch；任务
  仍归确认卡作者创建；
- 带 `session_id` 的 `POST /api/tasks` 会锁住会话；存在待确认卡时统一返回
  `CONCURRENCY`，不得绕过该卡抢占活动任务；
- `DELETE` 遇到生成中的 Harness、待确认卡、`queued`/`running`/
  `awaiting_case_confirm` 任务时返回 `VALIDATION`，要求先停止、确认/取消或等待终态。

#### `GET /api/sessions`

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "帮我下一单 Benchmark",
      "owner_id": "uuid",
      "visibility": "team",
      "can_manage": false,
      "can_delete": false,
      "updated_at": "2026-09-21T12:00:00Z",
      "active_task": { "id": "uuid", "kind": "benchmark", "status": "running" }
    }
  ],
  "total": 3
}
```

`active_task`：该会话当前非终态任务（含压测子任务），无则 `null`。
`can_manage` / `can_delete` 只在当前成员为 owner 时为 `true`。

#### `POST /api/sessions`

请求：`{ "title": "新会话", "visibility": "private" }`；`visibility` 省略时为
`private`。响应包含 GET 列表项的 `owner_id`、`visibility`、权限字段和时间。

空会话，不创建 task。

#### `PUT /api/sessions/{id}/sharing`

仅 owner。请求和响应：

```json
{ "visibility": "team" }
```

将 `team` 改回 `private` 后，服务端立即以关闭码 `4404` 关闭协作者 WS，避免继续接收
瞬态正文流。正在执行的任务不因分享设置变化而取消。

#### `DELETE /api/sessions/{id}`

仅 owner，成功 `204 No Content`。这是软删除，不级联物理删除历史消息、事件、任务或
报告；已删除或无权访问均返回 `404 NOT_FOUND`，禁止返回“删除成功”的假响应。

#### `GET /api/sessions/{id}/messages`

历史回放（REST）。实时增量只走 WS。  
`messages` item：`id, role: user|assistant|system, content, attachments[], author_id?, author?, client_message_id?, latency_ms?, created_at`。
`attachments[]` 新消息为 `{file_id, filename, size, content_type?, content_url}`；历史存量若文件元数据不可恢复则保留原始 `file_id`，不回传内部存储路径。
其中 `author` 为 `{id,username,display_name?}`；用户消息必填，assistant/system 为 `null`。  
`latency_ms` 仅 `role=assistant` 非空：该交付句从本轮 `user_message` 入 Harness 到交付的墙钟耗时（毫秒），
前端在气泡下方展示「耗时 x 秒」；`user`/`system` 与无耗时历史消息为 `null`。
`events` **必带**（否则刷新丢工具卡 / 思考卡）。  
`pending_confirm`：当前未 ack 的确认卡（TaskSpec）或 `null`；
`pending_confirm_author_id` / `pending_confirm_author` 标识唯一可操作者；前端优先该字段做成可编辑卡，`events` 里的 `confirm` 只作只读回放。
`context_meter`：模型窗口仪表，刷新必须用服务端数字，禁止按 messages 表总条数自己减。`window` 固定 20；`/20` 只约束 `messages` 段；`skills` / `summary` 为 0/1 标志；`compacted` 为 bool 标志当前会话是否已执行 `/compact` 压缩（前端据此展示压缩徽标，与 `compact_summary` 文本字段互补）。

```json
{
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "/benchmark 对比两模型",
      "attachments": [],
      "author_id": "uuid",
      "author": { "id": "uuid", "username": "alice", "display_name": "Alice" },
      "client_message_id": "browser-uuid",
      "created_at": "2026-08-19T12:00:00Z"
    }
  ],
  "events": [
    {
      "event_id": 1,
      "event": "thought",
      "task_id": null,
      "payload": { "text": "规划：基准评测", "stage": "plan", "skill_id": "skill-benchmark" },
      "ts": "2026-08-19T12:00:01Z"
    }
  ],
  "pending_confirm": null,
  "pending_confirm_author_id": null,
  "pending_confirm_author": null,
  "compact_summary": null,
  "context_meter": {
    "messages": 8,
    "skills": 0,
    "summary": 0,
    "headroom": 12,
    "window": 20,
    "total_tokens": 6720,
    "max_tokens": 200000,
    "messages_tokens": 5520,
    "skills_tokens": 0,
    "free_tokens": 193280,
    "used_percent": 3.4,
    "mcp_tools_count": 2,
    "mcp_tools_max": 28,
    "compacted": false
  }
}
```

实现列（Alembic，不单独 GET 摘要原文，避免把压缩提示词泄漏到浏览器）：
`sessions.visibility`、`sessions.deleted_at`、`sessions.pending_confirm` JSONB、
`sessions.pending_confirm_author_id`、`sessions.compact_summary` TEXT、
`sessions.compact_keep_from`（messages.id），以及 `messages.author_id` /
`messages.client_message_id`。算法见 Agent 说明书 §16.6。

`messages.role=assistant` 只存**交付句**（澄清、闲聊、「已入队」、「已压缩」、「已停止生成」、只读摘要）。规划 / 复核 thought、工具观察、`progress` 只在 `events`。

---

#### `GET /api/agent/prefs`

当前成员的跨会话下单偏好。只读；无 PUT。写入仅发生在 `confirm_ack.ok=true` 且任务已入队之后（服务端写 `settings` 键 `agent_prefs:{user_id}`）。

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

无记录时各字段 `null`（`last_profile_ids` 为 `[]` 或 `null` 均可，前端当缺失）。失效资产 ID 规划侧当 missing，不得编造。闲聊、取消确认、`/compact` 不写。

---

#### `GET /api/agent/metrics`

进程内只读快照：native 交错流与 ToolBatch 调度度量（登录成员可读，与 `GET /api/mcp/metrics` 同鉴权）。**不含**助手正文、工具参数、Observation、API Key。不落库；多副本各自独立。不新增 WebSocket 字段，`segment_id` 仍不进入公共契约。

```json
{
  "stream": {
    "rounds": 12,
    "invoke_fallbacks": 1,
    "first_delta_avg_ms": 180,
    "tool_call_parse_avg_ms": 420,
    "incomplete": 0,
    "incomplete_ratio": 0.0,
    "cancelled": 1,
    "upstream": 0,
    "associate_errors": 0
  },
  "batch": {
    "count": 4,
    "duration_avg_ms": 90,
    "parallel_waves": 1,
    "wave_size_avg": 2,
    "max_wave_size": 3
  },
  "rollout": {
    "native_stream_enabled": true,
    "parallel_enabled": false,
    "parallel_profile_allowlist": [],
    "parallel_disabled": false,
    "parallel_disable_reason": null,
    "consecutive_incidents": 0,
    "failure_threshold": 5,
    "cooldown_s": 30.0
  }
}
```

`rollout.parallel_disabled=true` 表示进程内脚踢线暂时关闭只读并行（连续 `UPSTREAM` / 关联错乱达阈值）；冷却后自动恢复。运维回滚并行仍关 `AGENT_PARALLEL_TOOL_BATCH_ENABLED` 或清空 `AGENT_PARALLEL_TOOL_BATCH_PROFILE_IDS`；回滚 P1 流式关 `AGENT_NATIVE_STREAM_ENABLED`。关闭开关**不得**改写已落库事件。

---

#### `GET /api/slash-commands`

自定义斜杠（下区「我的命令」）。**系统 15 条命令不走本接口**，前端本地注册表即可。

M2 已交付：成功 200。无命令时返回 `items=[]`（能力已启用，不是未启用桩）。禁止 localStorage 冒充已保存。

```json
{
  "items": [
    {
      "id": "uuid",
      "name": "smoke",
      "hint": "冒烟评测",
      "template": "帮我下一单基准评测，抽样 20 条",
      "created_by": "uuid",
      "created_at": "2026-08-19T12:00:00Z"
    }
  ],
  "total": 1
}
```

#### `POST /api/slash-commands`

body：`{ "name", "hint", "template" }`。  
`name`：`^[A-Za-z][A-Za-z0-9_-]{0,31}$`，且不与系统 15 条重名（禁止中文 name）。  
`template`：1–2000 字符，仅预填用户输入框，永远不当 system。含「跳过确认」「改系统提示词」或去空白后等于 `/bypass` → `VALIDATION`，不保存。  
成功 201，返回创建对象。改删仅 `created_by` 为当前用户。

#### `DELETE /api/slash-commands/{id}`

仅创建者；否则 `UNAUTHORIZED`。系统命令无 id，不可删。

选中自定义命令后展开 `template` 进输入框，发送仍是 WS `user_message`，不能加新工具、不能跳过确认卡。

---

### 3.5 文件

#### `POST /api/files`  multipart

字段 `file`。单文件 ≤20MB；扩展名见 §1.4。磁盘 `./data/files/{id}`，PG 存路径与 sha256。

```json
{
  "id": "uuid",
  "filename": "cases.xlsx",
  "size": 12345,
  "sha256": "...",
  "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}
```

超限 `VALIDATION`。Agent 附件：先本接口，再把 `id` 放进 `user_message.attachments[]`。

Agent 收到 `user_message` 后会校验每个 `file_id` 属于当前发言人，再将可解析的 Markdown、文本、PDF、DOCX、XLSX 正文以受限长度注入本轮模型上下文；图片按视觉内容块注入。数据库保存的用户 `content` 保持原文，附件解析内容只存在于模型请求中，不回显到用户消息气泡。

#### `GET /api/files/{id}`

元数据，同 POST 响应。不回文件二进制。

#### `GET /api/files/{id}/content`

登录后返回文件二进制（`Content-Disposition: inline`），供浏览器图片、PDF、文本预览，以及 Office/表格/音频打开或下载。未登录 `UNAUTHORIZED`；不存在 `NOT_FOUND`。路径不回显内部存储位置。Agent 音色克隆短工具的 `content_url` 指向本接口。

---

### 3.6 协议档

响应 **永不** 含 Key，即使 PUT 刚写入。空字符串 Key = 不修改。

协议档的 `base_url`、`model` 和 `api_key` 由 API 后端脚本写入服务器受控环境文件，数据库只保留
协议档 ID、名称、协议、用途和上下文窗口等元数据。每个协议档使用独立变量，变量名为：

```text
AI_PROFILE_<PROFILE_ID_NORMALIZED>_BASE_URL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_MODEL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_API_KEY
AI_PROFILE_<PROFILE_ID_NORMALIZED>_EMBEDDING_BASE_URL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_EMBEDDING_MODEL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_EMBEDDING_API_KEY
AI_PROFILE_<PROFILE_ID_NORMALIZED>_RERANKER_BASE_URL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_RERANKER_MODEL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_RERANKER_API_KEY
```

其中 `PROFILE_ID_NORMALIZED` 将非字母数字字符替换为下划线并转为大写，因此多个供应商可以同时存在，
不会互相覆盖。服务器既有的 `LLM_API_KEY`、`LLM_MODEL`、`OPENAI_BASE_URL`、`ANTHROPIC_BASE_URL`
仅作为旧单模型环境配置兼容别名；切换 Agent 协议档时由后端同步。环境文件由 Compose 挂载给 `api`（可写）
和 `worker`（只读），后端在文件锁保护下原位刷新并 `fsync`，失败时按快照回滚。

#### `GET /api/profiles`

全员可列（无 Key），供确认卡和 RAG 上下文工程使用。除主模型外，Embedding 与 Reranker
端点均为可选；响应只返回 URL、模型标识和 `has_*_api_key` 布尔值，不返回任何 Key。
item：`id, name, protocol, base_url, model, usages[], context_window, max_output_tokens, tool_call_mode,
embedding_base_url, embedding_model, has_embedding_api_key, reranker_base_url, reranker_model,
has_reranker_api_key, created_at`

#### `POST /api/profiles`  已登录成员

```json
{
  "name": "gpt-test",
  "protocol": "openai_chat",
  "base_url": "https://api.example.com",
  "model": "gpt-4.1",
  "api_key": "sk-...",
  "embedding_base_url": "https://embedding.example.com/v1",
  "embedding_model": "text-embedding-3-large",
  "embedding_api_key": "ek-...",
  "reranker_base_url": "https://reranker.example.com/v1",
  "reranker_model": "bge-reranker-v2-m3",
  "reranker_api_key": "rk-...",
  "usages": ["target"],
  "tool_call_mode": "legacy",
  "max_output_tokens": 8192
}
```

`anthropic_messages` 可另存 `anthropic_version`（默认 `2023-06-01`）。变更写审计；API Key 不进入数据库，
`has_api_key`、`has_embedding_api_key`、`has_reranker_api_key` 仅表示环境文件中是否存在对应 Key。
Embedding 与 Reranker 的 URL、模型和 Key 与主模型使用相同的“按协议档隔离、受控环境文件写入、空 Key 保留旧值”规则；
更新时只提交需要修改的字段，三类 Key 留空均表示不修改既有密文。

`max_output_tokens` 为 Agent 单回合模型输出上限（映射到上游 `max_tokens` / `max_output_tokens`），取值 256–131072，默认 `8192`；仅影响 `usages` 含 `agent` 的对话调用，不影响 benchmark、judge、用例生成等离线调用。

`tool_call_mode` 仅允许 `native` / `legacy`，默认 `legacy`：

- `native`：仅在管理员已验证目标网关支持 Function Calling 后显式选择。API 按 `protocol` 映射并发送原生 `tools`，流式接收正文增量与完整 ToolCall；**一次上游响应在发出 ToolCall 后即结束**，平台执行工具并回填 `tool_result` 后才会发起下一次模型请求。工具结果依赖的正文不可能出现在同一条上游响应中。参数不完整不得进入 ToolNode；
- `legacy`：默认模式。API 不向上游发送 `tools`，仅使用严格 `react.v1` JSON 兼容分支；适用于尚未验证 Function Calling 的兼容网关；
- 切换模式只影响 Agent ReAct 工具路径，不影响 benchmark、judge、Embedding 或 Reranker 调用。

#### `PUT /api/profiles/{id}` / `DELETE /api/profiles/{id}`

修改或删除协议档（正在被 Agent 后端引用的协议档禁止删除，写审计）。

#### `POST /api/profiles/{id}/check`

向被测模型或裁判端点发送轻量探活 ping 请求。响应：

```json
{ "ok": true, "latency_ms": 120 }
```
或 `{ "ok": false, "code": "UPSTREAM", "message": "401 from upstream" }`（日志与响应严禁携带 API Key）。

环境文件不存在、不可写、格式错误或调用时缺少对应 Key，统一返回 `VALIDATION` / `INTERNAL`，不得把文件内容
或凭据原文返回浏览器。

---

### 3.6.1 原生基础工具与 MCP 扩展目录（只读）

#### `GET /api/mcp/tools`

获取当前智能体环境中平台 allowlist 的**MCP 扩展目录**（只读）。`read`、`write`、`edit`、`bash`、`web_search`、`web_fetch` 与对话拆解 `task` 不属于目录：模型以原生 Function Calling 生成 ToolCall，ToolNode 完成 Schema、权限、附件门禁后，直接交 `NativeToolExecutor` 在线程池执行，不产生 MCP catalog/provider 路由开销。

当前已挂载的 MCP 扩展仅为评测任务桥 `platform.tasks`；RAG、报告等其它扩展仍须按 allowlist 和契约另行登记。目录只展示元数据，**不展示任何 MCP Server 连接命令、环境变量、工作目录或凭据**，也不展示内部 handler 细节。

`platform.tasks` 三工具只入 PG 队列或查询，**不等待 Worker 终态**：`task.create` 校验通过后直接入队返回 `queued` + `task_id`；`task.status` 只读当前状态不轮询；`task.cancel` 行锁取消非终态任务。真实进度/报告/错误由 Worker 写入 `task_events`/`ws_events` 转发。

```json
{
  "items": [
    { "name": "platform.tasks.task.create", "short_name": "task.create", "permission": "write" },
    { "name": "platform.tasks.task.status", "short_name": "task.status", "permission": "read" },
    { "name": "platform.tasks.task.cancel", "short_name": "task.cancel", "permission": "write" }
  ],
  "total": 3
}
```

未来扩展项的 `name` 为唯一 `tool_id`（`{server_id}.{short_name}`）；必填字段为 `name`、`desc`、`permission`（`read`/`write`）、`enabled`、`source`，可选 `tool_id`、`server_id`、`short_name`、`display_name`、`risk_level`、`execution_mode`、`timeout_s`、`requires_confirmation`、`supports_streaming`。MCP 扩展只能由平台部署和 allowlist 注册，浏览器与模型均不得提供 Server 命令、连接串或凭据。

原生基础函数定义（随 Agent 模型请求的 `tools` 字段下发，不提供浏览器 REST 调用）：

| 函数 | 用途与上限 | 执行/结果边界 |
| --- | --- | --- |
| `read(path, offset?, limit?)` | workspace 相对路径；0-based 分页；最多 2,000 行、8,000 字符、10MB 文件 | 单次流式扫描；模型可见片段 ≤8,000 字符，未读完带 `next_offset`（可回填为下次 `offset`）；ToolCard 显示行号与 ≤4000 字符完整行预览 |
| `write(path, content)` / `edit(path, old, new)` | 新建最多 2MB UTF-8 文件 / 精确单次替换 | `write` 使用 O_EXCL 防覆盖竞争；`edit` fsync 后 `os.replace` 原子提交；不回显写入正文 |
| `bash(command)` | 会话 workspace 内的短命令 | 始终经 bwrap：无网络、唯一可写目录、资源上限、超时整树清理；引擎不可用 fail-closed |
| `web_search(query, limit?)` | 关键词 ≤500 字符、1–10 条 | API 容器用环境变量中的 Firecrawl REST Key；未配置返回 `VALIDATION`，不伪造结果；结果结构化并脱敏 |
| `web_fetch(url, format?)` | 仅公开 http/https 文本页 | 首次和每次重定向均执行 DNS/IP SSRF 校验；优先 Firecrawl Markdown，未配置时降级为安全直接文本抓取；正文不进 WS 持久事件 |
| `task(goal, steps)` | 1–12 个 `pending/in_progress/completed` 步骤 | 只生成当前回合任务清单和 ToolCard；**不创建 `Task` 行、不入队、不调用 Worker、不替代 `confirm_ack`** |

V1.0 不接入外部 MCP Server，也不让浏览器创建、删除、探活或动态发现外部工具。原型中的 MCP Server 管理按钮须显示“能力未启用”说明；不得请求或假装成功调用 `/api/mcp/servers*`。

#### `GET /api/mcp/metrics`

获取内部 MCP Host 的**调用度量与服务器熔断状态**（只读，进程内快照）。按 `tool_id` 记录调用计数与耗时，按 `server_id` 维护失败熔断：`INTERNAL`/`TIMEOUT`/`UPSTREAM` 连续失败 ≥ 阈值（默认 5）即 `open`，冷却期（默认 30s）后自动恢复 `closed`；熔断 open 期间 `tool_call` 以 `VALIDATION`（「服务器工具暂时不可用（熔断）」）快速拒绝，不进入执行器。

```json
{
  "tools": [
    { "tool_id": "platform.tasks.task.status", "total": 12, "success": 11, "failure": 1, "timeout": 0,
      "avg_latency_ms": 8, "last_latency_ms": 6, "last_error_code": null }
  ],
  "circuits": [
    { "server_id": "platform.tasks", "state": "open", "consecutive_failures": 5,
      "failure_threshold": 5, "cooldown_s": 30.0, "opened_at": 1756080000.0 }
  ],
  "summary": { "total_calls": 12, "total_failures": 1, "total_timeouts": 0, "open_servers": ["platform.tasks"] }
}
```

只读展示，不含任何请求参数、工具结果原文或凭据。任务创建（MCP `task.create` 与 REST `POST /api/tasks` 共用）受每用户活动任务配额 `max_active_tasks_per_user`（默认 5）约束，超限返回 `CONCURRENCY` 并写 `AuditLog(action="task_quota_rejected")`。

---

### 3.6.2 Agent 技能与 Prompt 编排（V1.0 受控）

V1.0 使用服务端固定系统提示词和固定短工具绑定（见 §4、§6），不暴露 `/api/skills*` 读写接口，也不返回/回显 System Prompt。原型的技能 Tab 只展示这一受控边界；如 PRD 后续批准可配置技能，须另起 API 版本并补安全审计、版本化和回滚契约。

---

### 3.7 数据集工作台

#### `GET /api/datasets` / `GET /api/datasets/{id}`

```json
{
  "id": "uuid",
  "name": "smoke-20",
  "version": 3,
  "folder_id": "uuid?",
  "row_count": 20,
  "pending_complete_count": 2,
  "metric": "contain",
  "column_schema": [{ "key": "difficulty", "name": "难度", "type": "string", "sort_order": 1 }],
  "owner_id": "uuid",
  "created_at": "..."
}
```

#### `POST /api/datasets`

```json
{ "name": "smoke-20", "metric": "contain" }
```

#### `GET /api/dataset-folders` / `POST /api/dataset-folders` / `PUT /api/dataset-folders/{id}` / `DELETE /api/dataset-folders/{id}`

数据集目录树是业务数据而非前端偏好。folder item：`id, name, parent_id?, sort_order, created_at`；删除非空目录返回 `VALIDATION`，前端必须先移动或删除其中数据集。

#### `PUT /api/datasets/{id}`

可改 `name`、`metric`、`folder_id`、`column_schema`。`column_schema` 为自定义列定义数组（每项 `key,name,type,required?,sort_order`），数据行扩展值保存到对应 key；已有报告不受影响，对比仍看任务快照。

#### `DELETE /api/datasets/{id}`

删除数据集（全员同权，进行中的历史任务快照不受影响）。

#### `POST /api/datasets/{id}/upload`  multipart `file`

JSONL 或 CSV UTF-8；列 `question,reference,context?`；≤50MB、≤2 万行。覆盖后 `version += 1`。非法行可拒整文件 `VALIDATION`。

#### `GET /api/datasets/{id}/rows?pending_complete=true`

```json
{
  "items": [
    { "row_no": 3, "question": "", "reference": "x", "context": null, "pending_complete": true, "source_case_id": "uuid" }
  ],
  "total": 2
}
```

`pending_complete=true` 的行 **不进评分分母**。

#### `PUT /api/datasets/{id}/rows`

批量保存表格行与自定义扩展列（如 `tags`、`difficulty`、`precondition` 等）。

```json
{
  "rows": [
    { "row_no": 1, "q": "如何修改结算账户？", "r": "进入设置完成短信验证...", "c": "已绑定手机", "tags": "账户", "difficulty": "中等" }
  ]
}
```

#### `POST /api/datasets/ai-generate`

根据场景描述、种子样本扩写、PRD 文档提取或缺失字段补全，返回**未落库候选行**；前端允许人工删改后，必须再走 `PUT /api/datasets/{id}/rows` 保存。该接口不得暗中写入数据集版本。

```json
{
  "dataset_id": "uuid",
  "mode": "scene | seed | doc | fill_missing",
  "instruction": "生成跨境支付高频问答与边界风控问答",
  "source_text": "可选的 PRD / OpenAPI 文本",
  "seed": "可选的种子样本摘要",
  "rows": [],
  "max_count": 10,
  "model": "gpt-4.1",
  "temperature": 0.5
}
```

`fill_missing` 时 `dataset_id` 和待补全 `rows[]` 必填；其余模式至少提供 `instruction`、`source_text` 或 `seed` 之一。响应固定为：

```json
{
  "items": [
    { "row_no": 1, "q": "问题", "r": "标准答案", "c": "上下文", "tags": "支付", "difficulty": "中等" }
  ]
}
```

---

### 3.8 用例工作台

#### `GET /api/case-sets` / `GET /api/case-sets/{id}`

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "status": "generated | confirmed | cancelled",
  "generated_count": 40,
  "confirmed_count": 0,
  "folder_id": "uuid?",
  "column_schema": [{ "key": "owner", "name": "负责人", "type": "string", "sort_order": 1 }],
  "checks": [
    { "level": "error", "code": "no_core_positive", "message": "无核心正向用例" }
  ],
  "expires_at": "2026-09-24T12:00:00Z",
  "cases": []
}
```

`checks` 给确认页红字。`expires_at` = 进入 `awaiting_case_confirm` + 72h。

case item 包含：`id, strategy, priority, module, name, precondition, steps, expected, test_type, mapped, pending_complete` 及自定义扩展列。

#### `POST /api/case-sets`

创建新用例集。请求可含 `name, folder_id?, column_schema?`；`column_schema` 规则同数据集自定义列。

#### `GET /api/case-folders` / `POST /api/case-folders` / `PUT /api/case-folders/{id}` / `DELETE /api/case-folders/{id}`

用例目录树是业务数据而非前端偏好。folder item：`id, name, parent_id?, sort_order, created_at`；删除非空目录返回 `VALIDATION`。

#### `PUT /api/case-sets/{id}`

更新 `name`、`folder_id`、`column_schema`。已确认的用例集不可修改其策略、检查结果或目标映射，只允许返回 `VALIDATION`，避免破坏版本快照。

#### `PUT /api/case-sets/{id}/cases`

批量保存表格用例项与自定义列数据（即点即改后实时持久化）。

```json
{
  "cases": [
    { "id": "c-001", "strategy": "正向", "priority": "P0", "module": "登录", "name": "账密正确登录", "expected": "进入工作台", "precondition": "账号正常" }
  ]
}
```

#### `POST /api/case-sets/{id}/confirm`

确认用例入库，生成正式数据集版本快照。任务状态由 `awaiting_case_confirm` 转换为 `succeeded`。

```json
{ "ok": true, "mapping_target": "dataset | gold_qa", "target_id": "uuid" }
```

采纳率口径：`confirmed_count / generated_count`。

#### `POST /api/case-sets/{id}/cancel`

废弃用例集，任务置为 `cancelled`。

#### `POST /api/case-sets/{id}/map`

批量映射用例到目标基准数据集或知识库黄金问答。

```json
{ "target": "dataset | gold_qa", "target_id": "uuid", "case_ids": ["c-001", "c-002"] }
```

`target=dataset` 时：问句←用例名称、预期←expected、前置←context；缺 `question` 或 `reference` 的行进入目标集 `pending_complete`（不进评分分母）；**全部**映射行写 `source_case_id`，并在 `extras.source_case_set_id` 记录用例集 ID。`target=gold_qa` 时缺 `expected_doc_ids` 的项仅参与答案侧评分（M3；当前返回 `VALIDATION`）。目标 ID 类型不匹配返回 `VALIDATION`。

#### `POST /api/case-sets/ai-generate`

根据 PRD / OpenAPI / Excel 文档，按 6 大策略精细配比（正向 40% / 反向 25% / 边界 15% / 等价类 10% / 状态迁移 5% / 场景 5%）智能生成候选用例集。

```json
{
  "source_doc_id": "可选，已上传文件 ID",
  "source_text": "可选，PRD / OpenAPI 原文；与 source_doc_id 至少填一项",
  "strategy_weights": { "positive": 40, "negative": 25, "boundary": 15, "equivalence": 10, "state": 5, "scenario": 5 },
  "complexity": "medium",
  "max_count": 45
}
```

该接口只返回候选，不创建用例集：

```json
{
  "items": [
    { "strategy": "正向", "priority": "P0", "module": "收银台", "name": "余额支付成功", "expected": "订单核销成功", "precondition": "账户余额充足", "test_type": "核心业务" }
  ]
}
```

前端采纳后按 `POST /api/case-sets` → `PUT /api/case-sets/{id}/cases` 两步落库；任何一步失败都不得显示“创建成功”。

#### `POST /api/case-sets/{id}/ai-fill`

行级 AI 补全（原型用例工作台「AI 补全断言 / 补全属性」的落地路径补全，非新产品）。对用例集中**已存在**的用例行补全缺失字段（`expected` 断言、`precondition`、`test_type` 及已声明的自定义扩展列），返回**未落库候选值**；前端人工确认后必须再走 `PUT /api/case-sets/{id}/cases` 保存。已确认（`confirmed`）的用例集拒绝补全，返回 `VALIDATION`。

```json
{
  "case_ids": ["c-001", "c-002"],
  "instruction": "可选，补全侧重点说明",
  "fields": ["expected", "precondition"]
}
```

`case_ids` 必填且必须全部属于该用例集，否则 `VALIDATION`；`fields` 缺省时补全所有缺失字段。响应固定为：

```json
{
  "items": [
    { "id": "c-001", "expected": "进入工作台首页", "precondition": "账号已完成实名认证", "test_type": "核心业务" }
  ]
}
```

#### `GET /api/case-sets/import-template`

下载平台标准列 Excel 模板（`用例集` + `填写说明` 两个工作表）。响应文件流。登录后可用。

#### `POST /api/case-sets/{id}/import?mode=append|replace`

`multipart/form-data`，字段名 `file`。仅 `.xlsx` / `.xlsm`；`.xls` 返回 `VALIDATION` 提示另存。单文件 ≤10MB，有效用例 ≤2000 条。已确认或已废弃的用例集拒绝导入。

`mode` 缺省 `append`：追加写入，Excel「用例编号」若属于本集则更新该行，否则插入；`replace` 先清空本集全部用例再写入。

表头识别（列顺序不限，可出现在前 20 行）：

1. **platform**：平台导出列（用例编号、策略、优先级、模块、用例名称、前置条件、步骤、预期结果、测试类型）
2. **standard**：testcase-tools 标准列（用例编号、所属模块、用例标题、优先级、用例类型、前置条件、测试步骤、预期结果）
3. **simple**：简化列（模块、名称、步骤、预期）；缺策略默认「正向」，缺优先级默认 P1

无用例名称的数据行计入 `skipped_count`。「已映射」「待补全」列忽略。未识别的额外列写入扩展字段并并入 `column_schema`。

```json
{
  "ok": true,
  "format": "platform | standard | simple",
  "mode": "append | replace",
  "imported_count": 12,
  "skipped_count": 1,
  "generated_count": 13,
  "checks": []
}
```

#### `GET /api/case-sets/{id}/export?fmt=xlsx|xmind`

`fmt` 必填。响应文件流。Excel 8+。xlsx 固定列含用例编号，可再导入做往返。

---

### 3.9 知识库与黄金 QA 工作台

#### `GET /api/kb` / `POST /api/kb` / `GET /api/kb/{id}` / `PUT /api/kb/{id}` / `DELETE /api/kb/{id}`

```json
{
  "id": "uuid",
  "name": "default",
  "kind": "lightrag",
  "doc_count": 12,
  "is_core": false,
  "capabilities": { "projection": false, "rerank_compare": false },
  "owner_id": "uuid"
}
```

`kind`：`lightrag`（原生 query，支持切块）| `external_chat`（外部 RAG 服务本身挂在 profile，仅 `chat/completions`）。
`capabilities` 必含 `projection`、`rerank_compare` 两个布尔值；V1.0 都为 `false`。前端在 `false` 时保留原型区域但展示能力未启用，不可画示例投影或重排结果。`PUT` `{ "is_core": true }` 标为核心库写审计。

#### `POST /api/kb/{id}/documents`  multipart `file`

上传文档建索引；后端生成 `doc_id` UUID 写入 LightRAG metadata，自动执行分块与向量化。响应 `{ "doc_id", "filename", "status": "indexed" }`。

#### `GET /api/kb/{id}/documents`

返回当前知识库文档及索引状态：`{ "items": [{ "doc_id", "filename", "size", "status" }] }`。`status` 为 `indexing | indexed | failed`；列表不内嵌文本或切块。

#### `GET /api/kb/{id}/documents/{doc_id}/chunks?chunk_size=512&overlap=64`

返回服务端按请求参数生成的切块预览，供原型的切块流使用：

```json
{ "items": [{ "chunk_id": "uuid#c01", "tokens": 486, "text": "..." }] }
```

该接口只读；调整 `chunk_size` / `overlap` 不得在浏览器用样本文本伪造预览。

#### `DELETE /api/kb/{id}/documents/{doc_id}`

删除指定文档及其向量切块索引。

#### `POST /api/kb/{id}/query`

执行 LightRAG 原生 4 模式检索测试（Playground），返回 Top-K 切块、相似度得分与评测指标。V1.0 不返回实验性的投影或 rerank 比对结果。

```json
{
  "query": "退款多久到账？",
  "mode": "hybrid | local | global | naive",
  "k": 5
}
```

响应：

```json
{
  "items": [
    { "chunk_id": "d-01#c03", "doc_name": "product-manual.pdf", "similarity": 0.87, "text": "...", "hit": true }
  ],
  "metrics": { "hit_rate": 0.80, "mrr": 0.74, "recall": 0.85, "contain": 0.83 }
}
```

#### `GET /api/kb/{id}/gold-qa` / `POST /api/kb/{id}/gold-qa`

黄金 QA 上传与维护。列 `question, reference, expected_doc_ids[]?`；覆盖上传后 `version += 1`。无 expected_doc_ids 的样本不进 Hit Rate 评估分母。支持通过大模型自动从已索引文档中抽取问答对并自动关联切块。

---

### 3.10 任务

`POST /api/tasks` 的 JSON **等于** 确认卡 payload（§6），再加可选 `session_id`。

```json
{
  "session_id": "uuid",
  "kind": "benchmark",
  "profile_ids": ["uuid"],
  "dataset_id": "uuid",
  "run": {},
  "with_stress": false
}
```

成功：

```json
{
  "id": "uuid",
  "status": "queued",
  "kind": "benchmark",
  "parent_task_id": null
}
```

规则：

- 未通过字段校验 → 400 `VALIDATION`，**不入队**（与确认卡未 ack 同等）。  
- 会话存在待确认卡 → 409 `CONCURRENCY`，必须由确认卡作者确认或取消后再创建。
- 会话已有非终态任务（含压测子任务）→ 400 `VALIDATION`（占槽），前端应已禁用按钮。  
- 平台 `max_running_tasks` 满 → **仍** `queued`（3.4），可附 `warning: "CONCURRENCY"` 字段（可选）。  
- `kind=stress` 一般由 worker 在质量 `succeeded` 且 `with_stress=true` 时创建；人手 POST 须带 `parent_task_id`，且父任务必须 succeeded。  
- 一任务一种 `kind`。V1 禁止 Benchmark+RAG 混单。

#### `GET /api/tasks?status=&kind=&offset=&limit=`

全员。item：`id, kind, status, progress, dataset_id, kb_id, parent_task_id, creator_id, created_at, report_id?`

`progress`：`{ percent?, done, total, message }`

#### `GET /api/tasks/summary?from=&to=`

任务中心 24h 趋势、六态计数与可追溯诊断摘要。`from/to` 均为 ISO 8601；未传时返回最近 24h。服务端从 `tasks/task_events` 聚合，前端不得自行合成趋势或“AI 诊断”。

```json
{
  "range": { "from": "2026-08-17T00:00:00Z", "to": "2026-08-18T00:00:00Z" },
  "status_counts": { "queued": 2, "running": 1, "succeeded": 8, "failed": 1, "cancelled": 0, "awaiting_case_confirm": 0 },
  "series": [{ "ts": "2026-08-18T09:00:00Z", "queued": 1, "running": 1, "succeeded": 2, "failed": 0 }],
  "diagnosis": [{ "code": "UPSTREAM_SPIKE", "message": "上游 5xx 在 10 分钟内升高", "task_ids": ["uuid"] }]
}
```

#### `GET /api/tasks/{id}`

详情 + `config` 快照（确认卡 JSON）+ `events`（`task_events` 时间线：`at, level, message`）。

#### `POST /api/tasks/{id}/cancel`

```json
{ "ok": true, "status": "cancelled" }
```

权限：任务创建者。
评测/RAG/用例：当前样本结束后停。  
压测：**立即**停发。  
前端 Dialog 文案必须按 kind 分流，接口本身一个。

#### `POST /api/tasks/{id}/rerun`

新任务拷 `config`，新 `id`，`queued`。不复活旧行。

#### `POST /api/tasks/{id}/approve-stress`  M4

`{id}` 为 **压测子任务** 或质量任务（实现须能解析到对应 `kind=stress` 子任务）。  
会签人 ≠ 创建者（`prod` 发压须另一名正常成员确认）。
未会签：子任务保持 `queued`，`NEED_APPROVAL`；质量报告仍保留。写审计。

#### `GET /api/tasks/{id}/stress-series`  M4

`{id}` 为压测任务。

```json
{
  "task_id": "uuid",
  "points": [
    { "ts": "2026-11-20T08:01:00Z", "qps": 12.3, "rt_ms": 210, "error_rate": 0.01 }
  ]
}
```

供 Chart.js。**禁止**把本数组塞进 WS `progress`。Grafana 用同一 `task_id` 对 `job=ai-eval-stress`。

---

### 3.11 报告中心

#### `GET /api/reports?kind=&task_id=&offset=&limit=`

获取评测报告列表（支持根据评测类型 kind 过滤）。

```json
{
  "items": [
    {
      "id": "r-bm-1",
      "title": "Benchmark 报告 · smoke-20 v3",
      "kind": "benchmark",
      "task_id": "e5f2b8",
      "child_stress_report_id": "r-st-1",
      "created_at": "2026-08-15T06:02:00Z"
    }
  ],
  "total": 1
}
```

#### `GET /api/reports/{id}`

登录 Cookie 或 `?share=` 未过期免登访问。  
`?fmt=md` → `text/markdown` 导出 Markdown 报表。

JSON 公共头：

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "child_stress_report_id": "uuid?",
  "parent_report_id": "uuid?",
  "kind": "benchmark",
  "created_at": "...",
  "snapshot": { "dataset_version": 3, "metric": "contain", "profile_ids": [] },
  "baseline_id": null,
  "degraded": false
}
```

**benchmark** 另含：`scores[]`（每 profile 主指标、exact、rouge_l、fail_rate、latency、judge 得分及分维度 breakdown）、`judge_info`（裁判模型与评语归因）、`sample_items[]`。  
**rag** 另含：`hit_rate_at_k`、`mrr`、`recall_at_k`、`k`、`answer_contain`、`modes[]`、`hit_denominator_note`（无 expected_doc_ids 样本不进分母）、`degraded`（≥5pp 相对基线）。  
**stress** 另含：`qps` `rt` `error_rate` `ttft_ms?` `tpot_ms?` `tokens_per_s?` `sla_p99_ms?` `sla_met?`（未填 SLA 则不出现 `sla_met`）`knee?` `est_cost_usd`、`time_series[]`。

#### `GET /api/reports/{id}/samples?filter=all|diff|fail&offset=&limit=`

获取样本级逐题比对与 Bad Case 归因列表，含 `p1/p2` 模型预测内容、相似度切块、Judge 裁判评语与 Raw 请求/响应报文。

#### `POST /api/reports/{id}/share`

```json
{ "url": "https://.../reports/{id}?share=token", "expires_at": "..." }
```

生成公开只读链接，有效期 7 天，免登录访问。

#### `POST /api/reports/{id}/baseline`

冻结当前任务为基线版本（写操作审计）。

```json
{ "frozen": true, "task_id": "uuid" }
```

Benchmark：同 dataset 版本 + 主指标才能对比 Δ 差值。  
RAG：同 kb + gold 版本。  
解冻 `{ "frozen": false }` 同样写审计。

---

### 3.12 设置与审计

#### `GET /api/admin/settings`

已登录成员可 GET；敏感密钥不回显。

```json
{
  "agent_profile_id": "uuid",
  "agent_reasoning": {
    "enabled": true,
    "effort": "medium"
  },
  "max_running_tasks": 3,
  "max_inflight_model_calls": 8,
  "default_max_usd": 5,
  "stress": {
    "host_whitelist": ["10.0.0.8"],
    "max_qps": 500,
    "max_duration_s": 1800,
    "price_per_1k_tokens": 0.002
  },
  "notify": {
    "wecom": false,
    "email": false,
    "webhook": false
  }
}
```

`agent_reasoning` 由 Agent 新回合读取。`enabled=true` 时请求模型生成并流式返回可展示的 reasoning summary；前端以 `thought` 折叠卡显示，助手正文仍只走 `assistant_delta` / `assistant_message`。若上游返回英文隐藏思维链（如 `Here's a thinking process` / `Analyze User Input`），服务端替换为短摘要后再下发 `thought.stream=think` 与 `think_final`，中文思考原文保留。`effort` 支持 `low`、`medium`、`high`、`xhigh`、`max`，具体可用值由上游模型决定；普通不支持推理控制的模型不会发送未知专用字段。Gemini 3.x 通过 OpenAI 兼容接口时，适配器发送 `extra_body.google.thinking_config.thinking_level` 与 `include_thoughts=true`，`xhigh/max` 映射为 Gemini 的 `high`；返回的 `reasoning_content`、`reasoning`、`thought` 或 `thinking` 增量统一归入 `thought`。关闭时网关过滤 reasoning 增量，支持显式关闭的模型同时发送关闭参数；Gemini 3.x 即使关闭展示，也不额外请求 thought summary。该配置不暴露隐藏思维链，不改变公共事件头中的 `session_id` / `task_id`。

`notify` 的 URL/Token 仅 PUT 写入、GET 只给布尔或掩码。M1 可只返回 `agent_profile_id` 与并发默认；其余 M4 补齐。

#### `PUT /api/admin/settings`

全员同权（部分配置字段）。白名单 / 单价 / 密钥相关变更写入审计日志。

#### `GET /api/admin/audit-logs?from=&to=&offset=&limit=`

查询平台合规审计日志。item：`at, actor_id, action, target, detail`（无 Key）。  
action 至少包含：`login_failed` `role_change` `key_change` `baseline_freeze` `baseline_unfreeze` `whitelist_change` `prod_approve` `prod_stress`。

---

### 3.12.1 压测安全治理与白名单

#### `GET /api/admin/stress/settings` / `PUT /api/admin/stress/settings`

维护压测全局安全阈值（默认 QPS 上限、最大发压时长、60s 错误率 ≥ 50% 熔断阈值、Token 计费单价）。

#### `GET /api/admin/stress/whitelist` / `POST /api/admin/stress/whitelist` / `DELETE /api/admin/stress/whitelist/{id}`

维护目标发压 Host 白名单（支持 IP、域名、Port 以及 scope 环境范围匹配：`test / staging / prod`）。

```json
{
  "id": "wl-01",
  "host": "model-gateway.internal",
  "scope": "test,staging,prod",
  "creator": "admin",
  "created_at": "2026-08-14"
}
```

未在白名单中的目标禁止发压，直接返回 `WHITELIST` 阻断错误码。

#### `GET /api/admin/stress/usage`

获取近 7 天峰值 QPS 时序数据、阈值触碰率及月度累计开销。

#### `GET /metrics`

Prometheus 内置可观测性指标端点（内网 HTTP GET），输出前缀为 `ai_eval_stress_`，携带 `env, model, task_id` 标签。

---

### 3.13 调度内核与 Worker 节点管理

#### `GET /api/dispatch/overview`

获取调度中心大盘指标与内核雷达状态。

```json
{
  "online_workers": 8,
  "total_workers": 10,
  "queue_depth": 3,
  "avg_dispatch_cost_ms": 81,
  "assigned_today": 126,
  "strategy": "负载均衡",
  "max_running_tasks": 4,
  "heartbeat_interval_ms": 500
}
```

#### `GET /api/dispatch/workers`

获取全部 Worker 执行节点池状态列表。

```json
{
  "items": [
    {
      "id": "worker-01",
      "name": "GPU-Node-A1",
      "caps": ["benchmark", "judge"],
      "state": "busy",
      "load_percent": 62,
      "ram_usage": "4.8GB/16GB",
      "current_task": "a1f3c2 · smoke-20 v3 (shard 2/5)",
      "weight": 100
    }
  ]
}
```

#### `POST /api/dispatch/workers`

注册新 Worker 执行节点：`{ "id", "name", "caps": [], "weight": 100 }`。

#### `PUT /api/dispatch/workers/{id}`

修改节点状态或权重（如维护下线、排空 `draining`、更新能力标签）：`{ "state", "weight", "caps" }`。

#### `PUT /api/dispatch/config`

更新分发策略与全局并发容量：`{ "strategy": "负载均衡" | "优先级抢占" | "亲和性", "max_running_tasks": 4 }`。

#### `GET /api/dispatch/events?after_id=&limit=`

调度中心的分配日志流。按单调 `id` 升序返回，`after_id` 缺省时返回最近记录；轮询只拉增量。日志由调度器/worker 写入，浏览器不得生成或改写。

```json
{
  "items": [
    {
      "id": 1042,
      "at": "2026-08-18T10:22:00Z",
      "event": "assigned | started | draining | succeeded | failed",
      "task_id": "uuid?",
      "worker_id": "worker-01?",
      "message": "任务已分配至 GPU-Node-A1"
    }
  ],
  "next_after_id": 1042
}
```

---

## 4. WebSocket（F-AGT-01 / 02）

### 4.1 连接

1. `POST /api/auth/ws-ticket`  
2. `GET /ws/agent?ticket={ticket}&session_id={uuid}&last_event_id={n}`  
   - 首次：前端**先** `POST /api/sessions` 再带 `session_id`；可无 `last_event_id`。无 `session_id` 时服务端可建空会话（兼容），会话列表与 `/new` 仍以 REST 为准。  
   - 重连：必须带 `session_id` + `last_event_id`，服务端从 `ws_events` **补发** `event_id > last_event_id` 的事件。  
3. 关闭码：短票非法/过期 **4401**；会话不存在、已软删除或当前成员无权访问 **4404**；正常断开 **1000**。前端 4401 重新领票，4404 停止重连旧会话并回到会话列表。
4. **禁止** `?token=` 长期 JWT。

心跳：30s；传输层 ping/pong。应用层服务端可发 JSON `pong`。前端不发 JSON `ping`。

Harness 回合必须丢到后台 Task，**不得**在 `receive` 循环里 `await` 整轮规划（否则 `/stop` 进不来）。长任务只入队，由 Worker 写 `progress` / `report` / `error`。

### 4.2 公共头（服务 → 前端）

```json
{
  "event": "thought",
  "session_id": "uuid",
  "task_id": null,
  "event_id": 42,
  "ts": "2026-09-21T12:00:00Z",
  "payload": {}
}
```

`event_id` 在会话内单调递增。`task_id` 在入队后才有。

### 4.3 服务 → 前端（事件名冻结，V1.18 对齐 response 生命周期）

| event | payload | 前端渲染 |
| --- | --- | --- |
| `thought` | 思考摘要或阶段状态 `{ "text": "..." }`；可选 `latency_ms`、`stage`（`plan\|react\|reflect`）、`skill_id`。推理增量使用 `stream="think"`，思考快照使用 `stream="think_final"`；仅承载思考信息，不承载助手正文 | ThoughtCard |
| `user_message` | `{ "id", "role":"user", "content", "attachments", "author_id", "author":{id,username,display_name?}, "client_message_id?", "created_at" }`；落库、占 event_id，用于协作者实时补用户气泡；不使用 `message` 避免与助手正文歧义 | UserBubble |
| `assistant_delta` | `{ "role":"assistant", "text":"增量" }`；助手正文瞬态增量，不落库、不占事件号，仅用于在线连接的流式气泡 | AssistantBubble |
| `assistant_message` | `{ "id", "role":"assistant", "text":"完整回答", "reply_latency_ms?", "created_at", "interim"? }`；落库、占 event_id，可通过历史回放。**同一回合可多条**：工具前后的阶段叙述与最终交付句按事件序各成一段，前端不得把后续叙述并进第一条。`interim=true` 为阶段叙述（建议 ≤200 字），不结束本轮生成态；缺省或 `false` 为可展示交付句。`text` 禁止是 Observation / `read` 全文。`response.completed` 仍是整轮结束 | AssistantBubble |
| `response.completed` | `{ "finish_reason":"stop\|cancelled\|error", "role":"assistant" }`；本轮生成结束，落库、占 event_id | 结束流式状态 |
| `tool_call` | `{ "call_id":"toolcall_xxx", "name": "model.list", "arguments": {} }`；`call_id` 为本轮模型生成或平台补齐的稳定非空字符串 | ToolCard pending；原生基础工具标题直接使用英文 `name`；MCP/平台短工具按下方中文名映射；展开区显示 `ToolCall` |
| `tool_progress` | `{ "call_id", "name", "stage":"validating\|executing\|finalizing", "message" }`；仅在对应 `tool_call` 已落库后下发；不落库、不占 event_id、不补发 | ToolCard 保持 pending，更新加载文案与阶段状态 |
| `tool_output_delta` | `{ "call_id", "name", "seq", "channel":"document\|stdout\|result", "text", "start_line" }`；仅服务端安全预览块可发送，单 ToolCall 累计最多 4000 字符；不落库、不占 event_id、不补发 | ToolCard 按 `call_id`、`seq` 追加带行号输出；最终由 `tool_result` 替换成功态内容 |
| `tool_result` | `{ "call_id":"toolcall_xxx", "name": "model.list", "ok": true, "data": {} }` 或 `{ "call_id":"toolcall_xxx", "name":"model.list", "ok": false, "error": "...", "recovery": {"retryable", "suggested_action", "repair_hint", "max_auto_repairs"} }`；`call_id` 必须与对应 `tool_call` 相同。可选 `latency_ms`、`truncated`(bool，结果是否被截断)、`source`(溯源标识字符串，对齐 M7 `Observation.source`，如 `"file:uuid"`，可选)、`redacted`(bool，是否已脱敏)。`name="read"` 成功时 `data` 使用本节下方的受控投影 | ToolCard done；按 `call_id` 原地更新；失败显示脱敏恢复建议；`truncated`/`redacted` 为 true 时展示截断/脱敏徽标 |
| `clarify` | `{ "id":"uuid", "question":"...", "options":["..."]?, "context":"..."? }`；落库、占 event_id；澄清卡不建任务、不写 `sessions.pending_confirm`，仅暂停图等待用户回复 | ClarifyCard（独立组件，区别于 ConfirmCard）；用户回复后上行 `clarify_reply` 恢复图 |
| `plan` | PlanArtifact `{ "intent":"...", "skill_id":"skill-benchmark", "slots":{...}, "tools_needed":["..."], "delivery":"...", "budget":{...}, "allows_replan":bool, "notes":"..."? }`；落库、占 event_id；Plan-Solve 规划产物对用户完全可见 | PlanCard（展示规划意图/技能/工具/预算/交付物）；用户可查看但无需 ack |
| `confirm` | TaskSpec（§5 / §6）+ 非 TaskSpec 元数据 `confirm_author:{id,username,display_name?}` | ConfirmCard，等 `confirm_ack`；仅 `confirm_author.id` 可操作 |
| `confirm_ack` | `{ "ok": true, "task_id": "uuid" }` 或 `{ "ok": false }` | 更新最近一张 ConfirmCard 的确认/取消状态；落库、可回放 |
| `progress` | `{ "percent": 40, "done": 40, "total": 100, "message": "..." }` | ProgressDock。**仅这四字段**（percent 可选），不写入 `messages` |
| `report` | `{ "report_id": "uuid" }` | ReportCard |
| `error` | `{ "code": "UPSTREAM", "message": "..." }` | ErrorStrip + Toast |
| `pong` | `{}` | 不渲染 |

禁止：`thinking` `token` `chat:send` `tool_call_start` 及任何参考文档旧名。

`call_id` 规则：

- 仅在模型 ToolCall 参数完整、通过平台解析后发出 `tool_call`；参数增量不向浏览器新增事件；
- `native` 下一次上游模型响应可交错输出正文块与多个完整 ToolCall，但该响应对运行时而言在 ToolCall 处结束；回填全部 `tool_result` 后才发起下一次请求。`legacy` 不得把半截 JSON 当作正文或参数执行；
- 同一回合可有多个不同 `call_id`，禁止按工具名匹配，否则并行或连续同名调用会串卡；浏览器按 `call_id` 各更新一张卡；
- 同轮多个调用**默认串行**。仅当 `AGENT_PARALLEL_TOOL_BATCH_ENABLED=true`、当前协议档命中 `AGENT_PARALLEL_TOOL_BATCH_PROFILE_IDS`（空名单不开，`*` 表示全部）且进程内脚踢线未触发时，白名单只读工具 `read` / `web_search` / `web_fetch` 可同波并行；`write` / `edit` / `bash` / `task.create` / `task.cancel` 始终串行。模型回填仍按原始 `call_id` 顺序，与完成顺序无关；
- 上游未提供 ID 时由 API 进程生成 `toolcall_<uuid>`；该 ID 只在当前回合内稳定，不等同于 MCP Server、任务或数据库资源 ID；
- 上游返回空、空白或同一模型响应内重复的 `call_id` 时，API 以 `UPSTREAM` 结束该轮，禁止发送任何 `tool_call` 或进入 ToolNode；
- 策略拒绝、工具超时和执行失败也必须发出带原 `call_id` 的 `tool_result`，不得把异常转换为无关联的助手正文。

`read` 的成功 `tool_result.data` 契约：

```json
{
  "summary": "已读取 attachments/requirements.md 第 1–2000 行（共 3560 行，未读完）",
  "read": {
    "path": "attachments/requirements.md",
    "total_lines": 3560,
    "total_chars": 180423,
    "start_line": 0,
    "end_line": 2000,
    "lines_read": 2000,
    "is_complete": false,
    "next_offset": 2000,
    "content_truncated": false,
    "preview": "按完整行截取的受控预览，最多 4000 字符",
    "preview_truncated": true
  }
}
```

- `offset` / `limit` 的单位为行，均为 0-based；`end_line` 为排他上界，故示例表示第 1–2000 行；
- `preview` 最多 4000 字符且停在完整行，仅用于 ToolCard；**完整 `content` 只作为服务端 Observation 供下一模型回合使用，禁止出现在 `tool_result`、`ws_events`、历史回放或日志中**；
- `truncated=true` 表示本次未读完整文件或受服务端内容预算限制；`content_truncated=true` 仅表示完整内容被截断，首期按整行裁剪，禁止截断半行；
- `source` 使用不暴露宿主绝对路径的 `workspace:<相对路径>` 标识。

#### 4.3.1 原生工具规格、权限与恢复（V1.44）

工具注册表是 `description`、输入 Schema、浏览器安全输出 Schema、权限与恢复策略的唯一来源。模型只接收描述和输入 Schema；`output_schema` 不包含完整 Observation。所有对象参数默认 `additionalProperties=false`，未知字段在执行器前以 `VALIDATION` 拒绝。

| 工具 | 输入 Schema（必填；可选） | 成功 `tool_result.data` 安全投影 | 执行权限边界 | 失败恢复 |
| --- | --- | --- | --- | --- |
| `read` | `path`；`offset?`/`next_offset?`、`limit?≤2000` | `read.path/total_lines/start_line/end_line/next_offset/preview` | 仅会话工作区相对路径；≤10MB；模型正文≤8000 字符、浏览器预览≤4000 字符 | 仅 `TIMEOUT` 可修复重试；路径/分页错误提示相对路径或 `next_offset` |
| `write` | `path`、`content` | `write.path/bytes_written/lines_written/preview` | 仅会话工作区；≤2MB；排他新建 + fsync，绝不覆盖已有文件 | 不自动重试；文件存在时改用新路径或先 `read` 后 `edit` |
| `edit` | `path`、`old`、`new` | `edit.path/replacements=1/old_length/new_length` | 仅会话工作区；原子替换；`old` 必须匹配 | 不自动重跑；不匹配时返回邻近行脱敏建议，先 `read` 再调整 |
| `bash` | `command` | `bash.exit_code/preview/preview_truncated` | 独立 Runner 的一次性 bwrap：无网络、唯一可写工作区、CPU/内存/进程/墙钟限制；黑名单纵深防御；不可用即 fail-closed | 仅 `TIMEOUT` 表示可缩小范围后再试；黑名单、沙箱不可用与策略拒绝绝不降级或自动重跑 |
| `web_search` | `query`；`limit?≤10` | `search.query/results` | 仅服务端配置搜索服务；Key 不入事件/日志 | `TIMEOUT`/`UPSTREAM` 可调整关键词后重试一次 |
| `web_fetch` | `url`；`format?=markdown\|text` | `web.title/final_url/content_type/preview` | 仅公开 HTTP(S)；每次 DNS 与重定向都做 SSRF 校验；禁止凭据、内网、回环和保留地址 | 仅 `TIMEOUT`/`UPSTREAM` 可重试；SSRF/非法 URL 不重试 |
| `task` | `goal`、`steps[]` | `task.goal/steps[]` | 仅内存清单，不写库、不入队、不绕过确认卡 | 补齐目标/有限步骤后重试 |

`task.create/status/cancel` 仍是 MCP 长任务桥：会话/用户/任务归属由平台注入，`task.create` 受活动任务占槽和“先评后压”门禁，且只入队/查询/取消，绝不在对话回合等待 Worker 终态。

实时输出规则：`bash` 由 Runner 在 bwrap stdout 产生完整行时逐行转发；`read` 读取时按完整行块转发；`write` 仅在原子写入成功后转发与最终结果相同的受控内容预览。所有瞬态输出按 `call_id` 关联，累计最多 4000 字符；浏览器不得把它写入本地历史、持久事件或日志。断线期间的增量不补发，客户端继续等待同一 `call_id` 的最终 `tool_result`。

失败恢复字段：`recovery.retryable` 只表示可在修复参数后再次发起调用，**不代表平台自动重试副作用工具**；`max_auto_repairs` 是 Agent reflect 的有界修复上限；`repair_hint` 必须脱敏，禁止出现堆栈、SQL、密钥、绝对路径或上游原文。

共享流规则：`assistant_delta`、`tool_progress` 与 `tool_output_delta` 仅向同一 `team` 会话内的**在线**成员广播；
`thought.stream="think"` 只发送给本轮发起连接，不向协作者广播。思考、工具进度与工具输出增量允许按间隔或完整行合并后再发，避免一字一帧；这些瞬态增量不落库、
不占单调事件号；中途加入/断线重连者从后续增量继续看。有思考链时持久事件顺序为交付句 → `thought.stream="think_final"` → `response.completed`；`response.completed` 仍是整轮结束。
`clarify`、`plan`、`confirm` 为持久化事件（落库 `ws_events`、占 event_id），向同一会话所有在线成员广播，断线重连按 `last_event_id` 补发。
旧客户端可继续识别 `message` / `done`，但服务端不再发送这两个含义不明确的事件名。
当前 Compose 只有单 API 副本，assistant_delta 广播为进程内 Hub；多 API 副本时必须改为进程外
Pub/Sub，不能假定跨进程实时可见。

MCP/平台短工具中文名（ToolCard 标题；原生基础工具 `read` / `write` / `edit` / `bash` / `web_search` / `web_fetch` / `task` 直接显示英文 `name`）：

| name | 标题 |
| --- | --- |
| `model.list` | 列出协议档 |
| `dataset.list` | 列出数据集 |
| `kb.list` | 列出知识库 |
| `task.get` | 查询任务 |
| `report.get` | 读取报告 |
| `task.create` | 创建评测任务 |
| `task.status` | 查询任务状态 |
| `task.cancel` | 取消评测任务 |
| `testcase.confirm` | 确认用例入库 |
| `dispatch.overview` | 调度概览 |
| `audio.speech_recognition` | 语音识别转写 |
| `audio.speech_synthesis` | 语音合成 |
| `audio.voiceclone` | 音色克隆配音 |
| `image.generate` | Qwen Image 生图 |

长工具不由 Agent 进程跑完；前端只收 `progress` / `report` / `error`。

### 4.4 前端 → 服务（仅此四条 JSON）

```json
{ "event": "user_message", "payload": { "text": "帮我下一单 Benchmark", "attachments": [ { "file_id": "uuid" } ], "client_message_id": "browser-uuid" } }
```

```json
{ "event": "confirm_ack", "payload": { "ok": true, "patch": { "with_stress": false } } }
```

```json
{ "event": "cancel_task", "payload": { "task_id": "uuid" } }
```

```json
{ "event": "clarify_reply", "payload": { "id": "uuid", "answer": "用户回复文本或所选 option" } }
```

规则：

- `confirm_ack.ok=false`：不入队，卡标已取消。  
- `ok=true`：`patch` 与原 confirm 深合并后按 §5 校验，通过才 `task.create`。  
- `client_message_id` 可选，非空时最长 128 字符；同一会话同一键重复发送只回显已保存消息，不会启动第二轮 Harness。
- 同一会话同一时刻最多一张待确认卡（落库 `sessions.pending_confirm`，禁止只靠进程内字典）；仅 `confirm_author` 可以确认、拒绝或提交 patch，前端提交 patch 必须剥离该元数据。
- `clarify` 与 `confirm` 互斥语义：澄清卡不建任务、不占回合预算、不写 `pending_confirm`；同一会话同一时刻最多一张待回复澄清卡（进程内追踪，断线重连后由 `ws_events` 回放重建 UI 状态；多 API 副本时需网关按 `session_id` 粘性路由，与 §1.2 单副本前提一致）。`clarify_reply.id` 必须匹配最近一张待回复澄清卡，否则忽略并返回 `error`(`VALIDATION`)。
- `cancel_task` 权限与 REST cancel 相同；斜杠 `/cancel` 只取消**本会话**非终态任务。  
- 斜杠（含 `/stop` `/compact` `/help`）全部走 `user_message`，**没有第五种上行事件**（上行事件仅 `user_message` / `confirm_ack` / `cancel_task` / `clarify_reply` 四类）。  
- Direct 路径（`/help`、未知斜杠、图内防御提示）在业务事件后必须再发 `response.completed`：`/help` 为 `finish_reason=stop`，校验/防御为 `error`。`/cancel` `/stress` `/stop` `/compact` 由 `ws.py` 拦截的真实入口按各自事件收尾，不走 Direct。
- `/stop`：中止本轮 Harness 生成，不取消已 queued/running 任务；abort 为**会话级**（双标签同停）。共享会话仅本轮发起成员可执行。
- `/compact`：会话级上下文副作用，仅会话 owner 可执行。
- 会话已有非终态任务（含压测子任务）：新回合**不得**再发 `confirm`；未 ack 的旧卡确认按钮禁用。  
- 对话路径**不得**发出 `kind=stress` 确认卡。`/stress` = 质量任务卡且 `with_stress=true`。  
- Agent 进程禁止同步执行 `benchmark.run` / `rag.evaluate` / `testcase.generate` / `stress.run`。

---

## 5. 任务规格 TaskSpec（确认卡 = `POST /api/tasks`）

字段名不得改。必填语义随 `kind` 变化（PRD 5.1.2）。

```json
{
  "kind": "benchmark",
  "profile_ids": ["uuid"],
  "dataset_id": "uuid",
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
  "stress": {
    "env": "test",
    "qps": 10,
    "duration_s": 120,
    "sla_p99_ms": null
  },
  "case_source": { "file_id": "uuid" }
}
```

| 字段 | 必填 | 校验 |
| --- | --- | --- |
| `kind` | 是 | 四选一；前端只读展示 |
| `profile_ids` | benchmark：1–5；rag 外部 Chat：恰好 1 | 内置 LightRAG 评测可不填 profile |
| `dataset_id` | benchmark | |
| `kb_id` + `gold_qa_id` | rag | 内置或外挂都要黄金 QA |
| `rag_mode` | rag 且 LightRAG | 1–4 个，默认 `["hybrid"]` |
| `run` | benchmark / rag | 默认见 PRD 5.2.2；`concurrency` ≤ 平台 inflight |
| `run.k` | 否 | 仅 rag 有意义，默认 5，1–20 |
| `run.use_judge` | 否 | 默认 false；true 时用用途含 `judge` 的协议档 |
| `with_stress` | benchmark / rag | 默认 false |
| `stress` | `with_stress=true` | `env,qps,duration_s`；`sla_p99_ms` 可选 |
| `case_source` | testcase | `{file_id}` 或 `{text}`，二选一 |
| `parent_task_id` | 人手创建 stress 时 | 父任务须 succeeded |

`prod` + 压测：响应或 confirm payload 可带只读 `approvers: [{id,name}]` 供卡上展示；未会签不得 running。

`stress.qps` ≤ settings.max_qps（默认 500），`duration_s` ≤ max_duration_s（默认 1800）。未填 `sla_p99_ms` 时报告不出「是否达标」。

对话 Agent **不得**把 `kind` 设为 `stress` 发给确认卡；压测由质量任务 `succeeded` 且 `with_stress=true` 时 Worker 派生。人手 `POST /api/tasks` `kind=stress` 仍须 `parent_task_id`。

`frontend/src/schemas/confirmCard.ts` 与 `ws.py` 预填必须与上表默认值一致（`sample_size=1000`、`temperature=0`、`max_tokens=1024`、`qps=10`、`duration_s=120`、`sla_p99_ms=null`）。Worker 夹紧：`sample_size = min(请求值, 1000, 行数)`。

---

## 6. 内部 MCP 扩展（浏览器不调用）

MCP 预留给评测、RAG 和 Worker 协作扩展；基础工具清单与直连边界以 §3.6.1 为准。入参/出参与 PRD 5.5 一致，错误码同 §1.3；当前只挂载 `platform.tasks`，其余条目均为未来能力，不得伪装为可调用。

| 工具 | 类型 | 入参 | 出参 | 阶段 |
| --- | --- | --- | --- | --- |
| `model.list` | 短 | — | `{items:[{id,name,protocol,model}]}` 无 Key（`model` 仅供展示） | M1 |
| `dataset.list` | 短 | — | `{items:[{id,name,version,row_count}]}` | M2 |
| `kb.list` | 短 | — | `{items:[{id,name,doc_count}]}` | M3 |
| `task.status` | 短 | `task_id` | 当前 `status`、`progress`、`report_id`（只读，不等待终态） | M1 |
| `report.get` | 短 | `report_id` | 摘要 + 下载路径 | M2 |
| `task.create` | 短 | TaskSpec（`kind` 必填） | `{status: queued, task_id, kind}`；经门禁直接入队，会话/用户归属平台注入 | M1 |
| `task.cancel` | 短 | `task_id` | 取消非终态；终态幂等返回现状 | M1 |
| `dispatch.overview` | 短 | — | Worker 数 / 队列 / 策略（与 `GET /api/dispatch/overview` 同源摘要） | M1 迷你轨 |
| `audio.speech_recognition` | 短 | `file_id`（本轮 wav/mp3 音频，由系统绑定）；`language?`（`auto|zh|en`，默认 `auto`） | `{transcript, language, model, file_id, filename, content_type, size}`；禁止回传音频 Base64 | 对话同步 |
| `audio.speech_synthesis` | 短 | `text`（必填；模型未给时从用户原话剥离「帮我输出音频」等命令前缀/引号/冒号后抽取朗读稿）；`mode?`（`preset|voicedesign`）；`style?`；`model?`；`voice?` | `{file_id, filename, content_type, size, model, mode, content_url}`；`content_url` 为 `/api/files/{id}/content`，禁止回传音频 Base64 | 对话同步 |
| `audio.voiceclone` | 短 | `text`（朗读稿，必填）；`file_id`（本轮 wav/mp3 参考音，缺省取本轮最后一段音频附件）；`style?`（可选语气） | `{file_id, filename, content_type, size, content_url}`；禁止把音频 Base64 写入 `tool_result` | 对话同步 |
| `image.generate` | 短 | `prompt`（文本或本轮图片附件） | `{file_id, filename, content_type, size, content_url}`；禁止回传图片 Base64 | 对话同步 |
| `testcase.generate` | 长 | `file_id` 或 `text` | `case_set_id` | M2 |
| `testcase.confirm` | 短 | `case_set_id, edits?` | 状态 succeeded | M2 |
| `benchmark.run` | 长 | TaskSpec 评测段 | `report_id` | M2（M1 mock） |
| `rag.evaluate` | 长 | TaskSpec RAG 段 | `report_id` | M3 |
| `stress.run` | 长 | `parent_task_id` + `stress` | `report_id` | M4 |

Agent **只**调短工具：原生 `task` 仅用于对话内拆解；MCP `task.create` 经 kind、数据集、占槽和先评后压门禁后直接入队返回 `queued`，确认卡路径仍由 `confirm_ack` 驱动，二者复用 `enqueue_long_task`。长工具（`benchmark.run`、`rag.evaluate`、`testcase.generate`、`stress.run`）由 Worker 执行，Agent 进程同步调用必须 `VALIDATION`。`stress.run` 只下发 stress 容器。LightRAG 未接入时 `kind=rag` **不得** mock succeeded。

JSON Schema 冻结点：短工具 M1 W4；音频工具输入以本节为准，结果只回安全文本/文件元数据；评测长工具 M2 W6；RAG M3 W10；stress M4 W13。禁止新增 REST 代理或浏览器直连上游音频服务。

---

## 7. 压测进程指标（浏览器不调用）

`GET {stress}/metrics`  
内网；Basic 或 IP 白名单；**不**暴露公网；**不**走 Cookie。

- 前缀 `ai_eval_stress_`  
- label：`env,model,task_id`  
- Prometheus `job=ai-eval-stress`  
- 任务结束后 10min 停止该 `task_id` 序列  

前端曲线只用 `GET /api/tasks/{id}/stress-series`。

---

## 8. 按里程碑必须可联调的接口

| 阶段 | 必须就绪 | 门禁相关 |
| --- | --- | --- |
| M0 | `GET /api/health` | Compose |
| M1 | 认证、me、users、files、profiles、check、sessions（含 messages+events+pending_confirm+context_meter）、tasks CRUD/cancel/rerun、WS 全事件、settings（agent_profile_id）、`GET /api/agent/prefs` | 对话下单 mock；断线补发；协议档 |
| M2 | datasets、rows、case-sets confirm/export/map(dataset)、reports、share、baseline、budget 停、slash-commands 完整 CRUD | 对比报告；待补全；表单 POST /tasks；自定义斜杠 |
| M3 | kb、docs、gold-qa、map(gold_qa)、RAG 报告字段、Judge 可选 | Hit Rate@5 |
| M4 | settings.stress/notify、approve-stress、stress-series、解读只读 report_id | 先评后压；Grafana 同 task_id |

---

## 9. 明确不提供的接口（V1.0）

| 不要做 | 原因 |
| --- | --- |
| 对外 Open API / 长期 API Token | F-CM-08 V1.1 |
| `/api/chat/completions`、把 LightRAG 伪装成 Chat | F-RAG-01 |
| 改系统提示词、外部 MCP 管理、Ask/Plan（指产品级 Ask/Plan 功能，非 Harness 内部 `plan` 事件/PlanArtifact 下发） | PRD 4.2 |
| 第五种 WS 上行事件（斜杠必须走 `user_message`；上行事件仅 `user_message` / `confirm_ack` / `cancel_task` / `clarify_reply` 四类） | F-AGT-02 |
| 删除会话 | PRD 未要求 |
| 独立审计页对应的写操作以外的产品 UI | 仅 `GET /api/admin/audit-logs` |
| 浏览器直连 MCP 或 `/metrics` | 安全边界 |
| Postman / Markdown 接口解析专用上传类型 | 用例输入 P1 |

---

## 10. 前端实现约束（对应设计规范）

1. `frontend/src/api/http.ts` 只封装本文 §3 路径；`ws.ts` 只封装 §4。  
2. `schemas/confirmCard.ts` 与 §5 同一份类型与默认值，供 ConfirmCard 与 `/datasets` `/kb` 抽屉。  
3. 错误码文案用 §1.3，不硬编码第二套。  
4. 不发明本文没有的 query 参数来「先用着」。缺字段提 PR 改本文。  
5. ContextMeter 只读 `GET .../messages` 的 `context_meter`；自定义斜杠只打 `/api/slash-commands`，禁止 localStorage / admin settings 冒充。

## 11. 后端实现约束

1. OpenAPI（内部）从本文生成或手写，但 **对外不发布**（非 F-CM-08）。  
2. Worker 与 Agent 调同一 MCP，不另做一套 REST 给 worker 跑评测（worker 可进程内调）。  
3. 协议档 URL、模型 ID、API Key 写入按 profile 隔离的受控环境文件；GET 不回显；日志与 `agent_trace` 不落 Key / Cookie / 密码。
4. 状态机与取消语义见 PRD 3.3；先评后压由 worker 创建子任务，不要求前端二次 `POST /api/tasks` kind=stress（`prod` 除外走会签）。  
5. 业务失败只抛 `AppError`（十码）；WS 与 REST 同一错误体。未捕获异常归一 `INTERNAL`，堆栈只进日志。  
6. `api` 进程禁止 `time.sleep` 评测、禁止同步跑长 MCP、禁止在 `confirm_ack` 里等到 Worker 终态；Harness 不得阻塞 WS `receive` 循环。  
7. 待确认卡落 `sessions.pending_confirm`，禁止只靠进程内 `_PENDING_CARDS`。

---

## 附录 A  一致性检查记录（V1.3）

检查对象：PRD V1.6.3、设计规范 V1.2、总计划 V1.0、前端计划 V1.3、后端计划 V1.3、本文。

### A.1 PRD 5.9 摘要 vs 本文

| 5.9 原文 | 本文 | 一致？ |
| --- | --- | --- |
| login/logout | §3.2 | 是 |
| GET/POST users | + PUT、status、reset-password、activity summary | 补全（F-CM-03 停用/重置密/活动聚合） |
| GET/POST files | + GET `{id}` | 补全 |
| CRUD profiles | + check | 补全（规范连通性） |
| CRUD datasets / case-sets / confirm | + upload/rows/map/export | export 在 5.4.1；map 在 5.4.2 |
| CRUD kb / documents / gold-qa | + 删文档、gold upload、is_core | 补全（PRD 2.1） |
| tasks POST/GET/cancel/rerun | + approve-stress、stress-series | 补全（F-ST） |
| reports GET/share | + fmt=md、baseline、share query | md/基线在功能表 |
| admin settings GET/PUT | 字段分 M1/M4 | 是 |
| ws-ticket + GET /ws/agent | §4 | 是 |

5.9 **未列**、本文有、且计划已承认的补全：`/api/health`、`change-password`、`/api/auth/me`、`/api/sessions*`、`audit-logs`。均为正文已有能力的落地路径，不是新产品。

### A.2 WebSocket vs PRD 5.1.3 / 规范 §7

事件名集合完全一致。上行仅三条。`progress` 四字段，不扩展曲线。心跳 30s、短票、`last_event_id` 补发：一致。

### A.3 TaskSpec vs PRD 5.1.2 / 规范 §6

必填列一致。本文仅 **增加可选** `run.k`、`run.use_judge`（计划已声明冻结方式），不改必填语义。

### A.4 错误码 vs PRD 5.5 / 规范 §7.3

十个 code 一致；文案与规范一字对齐。

### A.5 前端计划 §3.1 vs 本文 §2

原前端表有、本文保留。本文多出并需回写计划的：

- `GET /api/auth/me`  
- `PUT /api/users/{id}`、`POST /api/users/{id}/reset-password`（计划写“停用/重置密”未写路径）
- 会话方案 A 从「周三二选一」改为冻结  
- `POST /api/datasets/{id}/upload`、`GET .../rows`  
- `POST /api/case-sets/{id}/map`  
- `POST /api/kb/{id}/gold-qa`
- `DELETE /api/kb/{id}/documents/{doc_id}`
- `GET /api/files/{id}`  
- `GET /api/files/{id}/content`  

后端计划多出的 `GET /api/admin/audit-logs`、`GET /api/health`：前端不强制调用，一致。

### A.6 角色 vs PRD 2.1

单一 `member` 可访问 V1.0 工作台与配置；分享免登录仅只读报告；`prod` 须非创建者会签；任务取消限创建者：一致。

### A.7 内部边界

MCP 浏览器不调：与 PRD 3.1、前端计划「禁止把 MCP 当 REST」一致。  
`/metrics` 浏览器不调：与 F-ST-04、前端 F-ST-04「正确不排」一致。

### A.8 发现的文档间隙（检查时已在本文冻结，计划需回写）

1. 登录后刷新身份：PRD 未写 `GET /api/auth/me`，SPA + Cookie 必需 → 本文补全。  
2. 用户停用/重置密：5.9 只有 GET/POST users → 拆 PUT 与 reset-password。
3. 会话 REST：计划二选一 → 冻结方案 A。  
4. 数据集覆盖上传、待补全行、用例映射：功能有、5.9 无独立路径 → 本文给出。  
5. `CONCURRENCY`：PRD 超限保持 queued，与「错误码」并存 → 本文规定默认仍创建 queued，不把该码当创建失败。

检查结论：本文与 PRD 功能无冲突；与 5.9 的差异均为已声明补全。前端计划 / 后端计划已回写为「以 API V1.3 为准」（会话方案 A、`run.k`、`run.use_judge`、`GET /api/auth/me`、目录/摘要/调度事件）。

### A.9 V1.4 Agent 增量（相对 V1.3）

自 Agent 说明书 V1.1 回写，**不是**新产品范围（仍是 F-AGT-01/02/03/04/06 的落地路径与可选 payload）：

| 增量 | 本文位置 |
| --- | --- |
| `GET .../messages` 必带 `events`，增 `pending_confirm` `context_meter` | §3.4 |
| `GET /api/agent/prefs`（只读，ack 后服务端写） | §3.4 |
| `GET/POST/DELETE /api/slash-commands`（M2 CRUD） | §3.4 |
| `thought`/`tool_result` 可选 `latency_ms`；`thought` 可选 `stage` `skill_id` | §4.3 |
| WS 关闭码 4401/4404；`/stop` 走 `user_message` | §4.1 / §4.4 |
| 对话不得发 `kind=stress` 确认卡；短工具含 `dispatch.overview` | §5 / §6 |
| 能力未启用 = `VALIDATION` 400，禁止 409 冒充 | §1.3 |

---

## 12. 原型数据源与真实联调约定（V1.3，开发前必读）

本节以 `Web-Prototype/` 现状为准，解决原型中“页面看起来有数据”与“浏览器确实调到了 API”混在一起的问题。它不改变 PRD 功能范围，也不要求本次修改业务项目代码。

### 12.1 三类数据必须分开

| 类型 | 可以包含 | 存放/使用规则 | 不可以包含 |
| --- | --- | --- | --- |
| 静态 UI 配置 | 路由、导航、状态/指标枚举、文案、颜色令牌、表头、表单默认约束 | `assets/app.js` 的枚举和页面布局；随前端包发布 | 业务实体、KPI、任务、报告、用户、协议档、白名单 |
| 显式 Mock | `MOCK_SEED` 中的示例业务实体和 Mock 响应 | 仅 URL `?data=mock` 或 `localStorage.ae_data_mode=mock` 时载入；仅用于走查/视觉验收 | 作为 API 失败后的自动回退；用于演示“已联调” |
| 实时 API 数据 | 所有业务实体、列表、详情、图表序列和可写表单 | 默认模式；统一经 `assets/api.js` → `/api`；响应写入页面缓存后渲染 | `localStorage` 长期 token、将失败替换为假成功 |

`Web-Prototype/assets/api.js` 的默认模式是 `live`。网络失败、非 2xx、未登录均向调用页抛出结构化错误；不得退回 `MOCK_SEED`。顶栏的“实时 API / 示例 Mock”标识是验收证据，不是可随意隐藏的装饰。

### 12.2 原型启动与接口地址

| 场景 | 地址/操作 | 预期 |
| --- | --- | --- |
| 同域开发 | `http://<web-host>/...`，反代 `/api` 到 API 服务 | 默认实时调用，Cookie 使用 `credentials: include` |
| 分离开发 | 页面 URL 加 `?apiBase=http://localhost:8000/api`（或启动前设置 `window.AE_CONFIG.apiBase`） | REST 指向该服务；后端须允许准确 Origin 和凭据 CORS |
| 视觉走查 | 页面 URL 加 `?data=mock` | 仅加载 `MOCK_SEED`；顶栏显示“示例 Mock” |
| 不可接受 | 直接双击 `file://` 后把异常吞掉 | 页面必须显示加载失败；不能声称已接 API |

临时兼容说明：当前后端已有的 `GET` 列表有些直接返回数组，而本契约冻结 `{items,total}`。原型客户端会把“顶层数组”归一为列表对象，避免阻塞本轮走查；这不是后端长期豁免。M1 完成后所有列表必须按 §1.1 返回分页对象。

### 12.3 当前实现审计（2026-08-18，只读检查）

下表是对当前 `backend/api/app/routers/` 的实现覆盖检查，不代表目标契约已经完成；本次未修改这些项目代码。

| 域 | 已有实现 | 与 V1.3 的关键缺口 | 首个阻塞里程碑 |
| --- | --- | --- | --- |
| 健康、认证 | health；login/logout/me/ws-ticket | 改密接口、Cookie 名/12h 口径、续期与统一错误体未对齐 | M1 |
| 成员 | 无 `users` router | 成员列表、状态、重置密码、审计查询全部缺失 | M1 |
| 会话/Agent | WS 会建立会话并发最小确认卡 | `/api/sessions` 及消息回放缺失；WS 事件/重放/上行协议未完整对齐 | M1 |
| 协议档 | profiles 的 list/create/delete | get/update/check、用途/密钥不回显、审计与统一列表响应缺失 | M1 |
| 任务 | create/list/get/cancel/rerun | TaskSpec 校验、分页对象、events、worker 状态机与权限口径未完整对齐 | M1–M2 |
| 数据集 | list/create/delete | 详情、版本上传、行 CRUD、AI 生成、统一响应缺失 | M2 |
| 用例、报告 | 无对应 router | 全部接口与实体缺失（2026-08-18 起用例域按 §3.8 落地，含行级 `ai-fill` 补全） | M2 |
| KB/RAG | 独立 LightRAG `/health`、`/query` 骨架 | 平台 `/api/kb*`、文档、黄金 QA、报告关联缺失 | M3 |
| 调度 | `dispatch` router（overview/workers/config/events）已按 §3.13 落地 | 调度事件由 worker 执行侧写入；压测治理白名单/会签/曲线缺失 | M1/M4 |
| MCP、Skills | `GET /api/mcp/tools` 只读清单已落地 | 外部 MCP 与自定义技能按 §3.6.1/§3.6.2 保持能力未启用 | M1 |

结论：原型的接口名称此前大部分已列出，但不能视为“已接入”。本节与后端计划的 M0–M4 清单共同作为实现差距清单。

### 12.4 原型 API 客户端冻结项

| 项 | 冻结处理 | 后端配合 |
| --- | --- | --- |
| 任务重跑 | `tasks.rerun(id)` → `POST /api/tasks/{id}/rerun`；不得在浏览器拼造旧任务配置 | 后端从旧任务快照复制并生成新 ID |
| 会话删除 | owner 调 `DELETE /api/sessions/{id}`，成功 204；只软删除 | 有生成、待确认卡或非终态任务时返回 `VALIDATION`，历史任务/报告仍在任务中心保留 |
| 上传 | `FormData` 不设置 JSON Content-Type；数据集走 `/datasets/{id}/upload`，KB 走 `/kb/{id}/documents` | 返回文件/版本/异步处理状态，不能只返回 `{ok:true}` |
| WS | 从 REST 短票换取连接；支持 `session_id` 与 `last_event_id` | 不接受长期 token；按 §4 补发事件 |
| 缓存 | `AE.DB` 只是一页内响应缓存，实时模式初始为空 | 写操作成功后返回资源或前端重新拉取；禁止依赖原型样本 ID |

### 12.5 页面联调最小验收

| 页面 | 首次真实读 | 最小真实写 | 通过条件 |
| --- | --- | --- | --- |
| login | `GET /auth/me`（刷新后） | login / change-password | Cookie 生效，刷新仍能识别身份 |
| agent | sessions、profiles、datasets/KB | 创建会话、确认卡 `POST /tasks` | 断线重连后按 event_id 补发，不伪造任务成功 |
| tasks | `GET /tasks` | cancel / rerun | 筛选、详情、状态均来自服务器；重跑 ID 改变 |
| datasets / cases | 各自列表和详情/行 | 上传、保存、确认/映射 | 刷新后版本和编辑结果仍存在 |
| report | reports、samples、stress-series | share / baseline | 无报告时显示空/错误态，不能用静态报告顶替 |
| kb | KB、文档、黄金 QA | 上传、查询、黄金 QA 覆盖 | 检索结果中的 doc ID 可追溯 |
| 管理与调度 | profiles/settings/workers/whitelist | check、更新治理、白名单 | 敏感字段不回显；变更可审计 |

### 12.6 原型逐页还原新增契约（V1.3）

以下接口和字段补齐的是原型已经可见、但此前未被明确为真实数据的状态。它们的实现批次、表和测试以两份开发计划的 §11.7 / §12.7 为准。

| 页面状态 | 冻结契约 | 实时模式规则 |
| --- | --- | --- |
| 调度分配日志 | `GET /api/dispatch/events?after_id=&limit=` | 只增量读取调度器写入的事件；无事件即空日志，不显示示例流 |
| 任务趋势与诊断 | `GET /api/tasks/summary?from=&to=` | 后端聚合状态趋势与可追溯规则诊断；不返回无来源的生成式文案 |
| 数据集目录/扩展列 | `/api/dataset-folders*`；dataset `folder_id,column_schema` | 目录、列和行值写后必须刷新仍存在；候选生成结果不属于资源 |
| 用例目录/扩展列 | `/api/case-folders*`；case set `folder_id,column_schema` | 目录、列、72h 与确认状态由服务端返回；不得用前端倒计时决定终态 |
| KB 实验区 | KB item `capabilities.projection/rerank_compare` | V1.0 返回 `false`；前端展示能力说明，不能用 Mock 散点或重排对照补位 |
| 协议档四 Tab | `GET /api/mcp/tools`；profiles/settings | 仅内置工具清单可读；外部 MCP 和自定义技能/Prompt 的写操作在 V1.0 返回 `VALIDATION` 的能力未启用说明 |
| 成员活动 | `GET /api/users/activity-summary?from=&to=` | KPI/活动由审计聚合；异地登录 AI 风险不在 V1.0 返回范围 |

能力未启用使用 HTTP **400**，错误体遵循 §1.3：`{ "code": "VALIDATION", "message": "该能力未纳入 PRD V1.0", "fields": { "feature": "disabled" } }`。禁止用 409。前端将其渲染为页面内受控说明，不显示为成功 Toast，也不回退 Mock。

---

## 13. 本次修订代码文件与作用清单（2026-08-21）

**V1.14（2026-08-21）— 语音合成朗读稿抽取与 TTS 意图词表扩充**

`audio.speech_synthesis` 当模型未显式给出朗读稿时，从用户原话剥离「帮我输出音频 / 朗读一下」等命令前缀与引号、冒号后抽取播报文本，避免把整句命令当朗读稿；`SPEECH_SYNTHESIS_HINTS` 扩充「输出音频 / 生成音频 / 读出来 / 念出来 / 帮我朗读」等中文表达。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/mimo_audio.py` | 新增 `extract_tts_text` 朗读稿抽取（引号/冒号/命令前缀剥离）；`arguments_for_speech_synthesis` 模型未给朗读稿时从原文抽取 |
| `backend/api/app/agent/plan.py` | `SPEECH_SYNTHESIS_HINTS` 扩充「输出音频/生成音频/输出语音/转成音频/读出来/念出来/帮我朗读」等词 |
| `backend/api/tests/test_mimo_audio.py` | 新增朗读稿抽取与参数绑定单测 |

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/agent/harness.py` | 保存完整 `think_final` 思考快照；确认/取消确认卡写入 `confirm_ack` 事件 |
| `backend/api/app/agent/context.py` | 从持久化事件恢复技能与短 MCP 工具计数，刷新 ContextMeter 不归零 |
| `backend/api/app/routers/sessions.py` | 历史接口返回 `compact_summary`，恢复压缩后的模型上下文 |
| `frontend/src/views/Agent.vue` | 回放思考快照、确认回执与历史工具资产，并修正确认卡状态 |
| `frontend/src/api/types.ts` | 补齐 `confirm_ack` 事件和 ContextMeter 扩展字段类型 |
| `backend/api/app/profile_env.py` | 按 profile 生成环境变量名，在 bind mount 文件上加锁刷新/删除/回滚 URL、模型 ID、API Key |
| `backend/api/app/routers/profiles.py` | 协议档 CRUD 改为环境文件存储，旧密文迁移，连通性检查读取环境参数 |
| `backend/api/app/routers/admin.py` | 切换 Agent 协议档时同步兼容 `LLM_*` 环境别名 |
| `backend/api/app/llm/` | Agent 调用优先读取 profile 环境变量，兼容旧全局 LLM 环境变量 |
| `backend/worker/app/profile_env.py` | Worker 只读共享环境文件并隔离多供应商配置 |
| `backend/worker/app/benchmark.py` / `backend/worker/app/testcase.py` | 评测与用例生成调用改读环境文件参数 |
| `docker-compose.yml` / `.env.example` | API 可写、Worker 只读挂载服务器 `.env`，新增 `PROFILE_ENV_FILE` |

**V1.8（2026-08-20）— 助手回复耗时展示**

| 文件 | 作用 |
| --- | --- |
| `backend/shared/models.py` | `messages.latency_ms` 字段：assistant 交付句回复耗时（毫秒） |
| `backend/api/migrations/versions/cf9e2d5b7a01_助手消息增加回复耗时字段.py` | Alembic 迁移：新增 `messages.latency_ms` 列 |
| `backend/api/app/agent/harness.py` | 回合计时：`_ROUND_STARTED_AT` contextvar 记录回合起点，`_deliver_sentence` 计算耗时并写入 Message，交付 thought 终帧带 `reply_latency_ms` |
| `backend/api/app/routers/sessions.py` | `GET /sessions/{id}/messages` 返回 `messages[].latency_ms` |
| `frontend/src/api/types.ts` | `SessionMessage` 补 `latency_ms` 字段 |
| `frontend/src/views/Agent.vue` | 历史回放/实时交付帧把 `latency_ms` 落到助手气泡，气泡下方展示「耗时 x 秒」 |
| `frontend/src/styles/base.css` | 新增 `.reply-latency` 耗时角标样式 |

**V1.8（2026-08-20）— 用例 Excel 导入导出**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/case_excel.py` | Excel 三种表头解析与模板生成 |
| `backend/api/app/routers/cases.py` | `import-template` / `import`；映射回写 context 与 source_case_id |
| `backend/api/tests/test_case_excel.py` | 导入解析与模板往返单测 |
| `frontend/src/components/modals/ImportCasesExcelModal.vue` | 用例工作台 Excel 导入弹窗 |
| `frontend/src/views/Cases.vue` | 导入导出入口、目录持久化、72h 按 expires_at 展示 |
| `frontend/src/api/http.ts` / `frontend/src/api/types.ts` | 导入、模板、目录树客户端 |

**V1.9（2026-08-20）— 音色克隆短工具**

对话附件上传 wav/mp3 后，Agent 调用内部短工具 `audio.voiceclone`（MIMO `mimo-v2.5-tts-voiceclone`，OpenAI `chat/completions` 兼容）。合成音频落盘，`tool_result` 只回 `file_id` 与 `content_url`，浏览器经 `GET /api/files/{id}/content` 播放。环境变量 `MIMO_TTS_BASE_URL` / `MIMO_TTS_API_KEY` / `MIMO_TTS_MODEL` 注入 API 容器，禁止把 Key 写入仓库或日志。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/voiceclone.py` | MIMO 调用、参考音校验、规划注入 |
| `backend/api/app/agent/mcp_tools.py` / `defaults.py` / `routers/mcp.py` | 短工具名单与执行 |
| `backend/api/app/agent/plan.py` / `react.py` / `harness.py` | 注入工具、传入本轮附件、独立线程执行、交付句 |
| `backend/api/app/routers/files.py` | 允许 wav/mp3；实现 `GET /{id}/content` |
| `backend/api/app/config.py` / `.env.example` / `docker-compose.yml` | MIMO TTS 环境变量 |
| `backend/api/tests/test_voiceclone.py` | 规划注入与假上游落盘单测 |
| `frontend/src/views/Agent.vue` | 附件白名单、工具卡播放器 |

**V1.10（2026-08-20）— 独立 Qwen Image MCP 工具中心可见性**

独立 Qwen Image stdio MCP 曾作为 `/api/mcp/tools` 注册项展示；V1.11 起，平台改为直接在 API Agent Host 的内部 `mcp_tools` 中执行 `image.generate`，不再依赖额外 stdio MCP 进程。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/mcp.py` / `backend/api/tests/test_dispatch.py` | 注册并校验 `image.generate` 的工具中心可见性 |
| `frontend/src/api/mockData.ts` / `frontend/src/views/AdminProfiles.vue` | 增加图像生成领域与工具中心展示 |
| `frontend/src/components/modals/McpToolModal.vue` | 增加图像生成工具契约详情 |

**V1.11（2026-08-20）— Qwen Image 内部短工具接入**

Qwen Image 通过与 `audio.voiceclone` 相同的 Agent 内部短工具链路执行：规划阶段识别图像生成意图，React 阶段在独立线程中调用上游，参考图只从本轮图片附件选择，生成结果落盘到 `files` 表并通过同源 `content_url` 返回。URL、Key、模型 ID 和超时从环境变量 `QWEN_IMAGE_API_URL`、`QWEN_IMAGE_API_KEY`、`QWEN_IMAGE_MODEL`、`QWEN_IMAGE_TIMEOUT_SECONDS` 注入。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/imagegen.py` | Qwen Image 请求、图文 content 组装、响应解析、图片落盘与规划注入 |
| `backend/api/app/agent/defaults.py` / `mcp_tools.py` / `react.py` / `plan.py` / `harness.py` | 注册、线程隔离执行、自然语言规划注入和交付句 |
| `backend/api/app/config.py` / `docker-compose.yml` / `backend/api/app/routers/files.py` | 环境变量注入和图片附件白名单 |
| `frontend/src/views/Agent.vue` / `frontend/src/styles/base.css` | 图片附件上传、工具结果预览与下载 |
| `backend/api/tests/test_imagegen.py` | 图文请求、规划注入、落盘和线程执行单测 |

**V1.12（2026-08-21）— 协议档 Embedding / Reranker 配置**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/schemas.py` | 增加 Embedding / Reranker 的 URL、模型标识与 API Key 输入字段；响应只返回配置公开值和密钥存在性布尔值 |
| `backend/api/app/profile_env.py` | 为两类附加模型生成隔离环境变量，沿用加锁、fsync、回滚和只写不回显规则 |
| `backend/api/app/routers/profiles.py` | CRUD 写入和读取两类附加端点配置，更新时保留未提交的既有密钥 |
| `backend/worker/app/profile_env.py` | Worker 只读解析 Embedding / Reranker 环境变量 |
| `frontend/src/api/http.ts` / `frontend/src/components/modals/ProfileModal.vue` / `frontend/src/views/AdminProfiles.vue` | 协议档新增 Embedding / Reranker 可选配置表单、列表标识，并按空值保留规则提交；客户端请求类型同步收紧 |
| `frontend/src/api/types.ts` | 补齐协议档附加模型配置与脱敏状态字段 |
| `backend/api/tests/test_profile_env.py` / `backend/api/tests/test_profile_schemas.py` | 覆盖多端点环境变量隔离、删除回滚及请求校验 |

**V1.15（2026-08-22）— Agent 骨架重置**

旧 Agent、Harness、模型调用层和 Runtime 实现已清空，避免旧实现与新设计并存。`/ws/agent`、Agent 偏好、MCP 工具清单以及数据集/用例 AI 候选入口暂由 API 保留路径但返回统一的 `VALIDATION` 能力未启用错误；核心 CRUD、Worker、数据库模型与迁移不受本次重置影响。后续实现边界以 [`AI测试与评估平台-Agent重设计工作区.md`](AI测试与评估平台-Agent重设计工作区.md) 为准。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/`、`harness/`、`llm/`、`runtime/` | 仅保留包边界文件，等待模型调用层、Harness 与 Agent 范式重新评审 |
| `backend/api/app/routers/ws.py` | 拒绝旧 Agent WebSocket 会话，防止新旧运行时并存 |
| `backend/api/app/routers/agent_prefs.py` / `mcp.py` | 保留路由形状，返回重建设计占位 |
| `backend/api/app/routers/datasets.py` / `cases.py` | 暂停模型生成入口，不调用旧模型客户端 |
| `backend/api/tests/` | 移除依赖旧 Agent/Harness/MCP 实现的测试，保留平台核心测试 |

**V1.16（2026-08-23）— LangGraph Agent 与 WebSocket 最小链路**

在 V1.15 清空旧运行时的基础上，新增唯一的 LangGraph 单轮 Agent 图和 WebSocket 桥接。`/ws/agent` 重新支持短票鉴权、会话创建/可见性校验、`last_event_id` 事件补发、`user_message` 后台回合、`message` / `thought` / `error` / `pong` 事件；正文与推理增量分别使用 `thought.stream=chunk|think`，回合结束保存 `think_final` 和助手交付句。`confirm_ack`、`cancel_task`、MCP、人工确认和长任务仍返回 `VALIDATION` 能力未启用错误，不在本期恢复。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/graph.py` | LangGraph 单轮 Agent 图，仅组合 `ModelGateway` |
| `backend/api/app/routers/ws.py` | WebSocket 短票、会话事件、后台 Agent 回合和流式投影 |
| `backend/api/app/session_connections.py` | 单 API 副本下的持久化事件与正文增量广播 |
| `backend/api/app/llm/gateway.py` | 保持流式取消异常的受控传播 |
| `backend/api/tests/test_agent_graph.py` | Agent 图非流式与流式回归测试 |

**V1.18（2026-08-23）— 标准 response 生命周期事件**

用户回显不再复用 `message`，回合结束不再使用语义模糊的 `done`。服务端统一发送
`user_message`、`thought`、`assistant_delta`、`assistant_message`、`response.completed`、
`error`、`pong`；旧 `message` / `done` 仅由前端兼容历史事件，不再由服务端新写入。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | 发送独立用户回显和 `response.completed`，保留公共头中的 `session_id` / `task_id` |
| `frontend/src/api/types.ts` | 增加新事件类型并保留历史事件兼容 |
| `frontend/src/views/Agent.vue` | 分离用户、思考、助手增量、最终消息和完成状态 |
| `backend/api/tests/test_ws_protocol.py` | 回归验证用户回显事件与完成事件公共头 |

**V1.20（2026-08-23）— Gemini 思考摘要兼容**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/adapters.py` | 为 Gemini OpenAI 兼容流式请求发送 `thinking_config.include_thoughts`，映射思考强度，并归一化 `thinking` 思考增量 |
| `backend/api/tests/test_adapters.py` | 回归验证 Gemini 思考参数与思考增量分类 |

**V1.19（2026-08-23）— Agent 思考摘要与强度设置**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/admin.py` | 增加 `agent_reasoning.enabled/effort` 默认值与校验；不涉及数据库迁移 |
| `backend/api/app/routers/ws.py` | 每个 Agent 回合读取思考设置并写入 `ModelConfig` |
| `backend/api/app/llm/contracts.py` / `gateway.py` | 扩展模型调用契约，并在关闭时过滤 reasoning 流 |
| `backend/api/app/adapters.py` | 映射 OpenAI Chat/Responses、Mimo 和 Anthropic 的思考参数 |
| `frontend/src/views/AdminProfiles.vue` / `frontend/src/api/types.ts` / `frontend/src/api/mockData.ts` | 增加管理页思考开关、强度选择和类型夹具 |
| `backend/api/tests/test_adapters.py` / `backend/api/tests/test_llm_graph.py` | 回归验证思考参数映射与关闭过滤 |

**V1.23（2026-08-24）— Agent 多附件上传与预览**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/files.py` | 扩展 Agent 附件白名单，允许图片与 DOC/DOCX 文件；沿用 20MB 限制和同源内容接口 |
| `backend/api/tests/test_files.py` | 覆盖图片、Markdown、PDF、Word、Excel 扩展名校验及非法格式拒绝 |
| `frontend/src/api/http.ts` | 文件上传响应类型补充可选 `content_type`，用于本地预览识别 |
| `frontend/src/components/agent/AttachmentPreview.vue` | 新增图片缩略图、PDF/文本预览、Office 类型卡片和打开/下载入口 |
| `frontend/src/views/Agent.vue` | Agent 输入区支持多附件选择、拖拽上传、上传状态、附件移除与消息内预览卡片 |

**V1.24（2026-08-24）— Agent 附件上下文与历史预览修复**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/attachments.py` | 校验附件归属、补齐历史预览元数据，并解析文本、PDF、DOCX、XLSX 与图片模型内容块 |
| `backend/api/app/routers/ws.py` / `backend/api/app/routers/sessions.py` | 将附件注入模型窗口，用户消息保存安全元数据，历史回放返回可预览字段；支持附件-only 用户消息 |
| `backend/api/app/adapters.py` | 将内部图文内容块分别转换为 OpenAI Chat、Responses 与 Anthropic Messages 格式 |
| `frontend/src/views/Agent.vue` / `frontend/src/components/agent/AttachmentPreview.vue` | 将附件按钮与待发送预览放入输入框，用户气泡中把附件置于提示词上方并保持紧凑预览 |
| `frontend/src/components/ProviderLogo.vue` / `frontend/src/api/types.ts` | StepFun 图标对齐图二，历史附件类型支持安全元数据 |
| `backend/api/tests/test_agent_attachments.py` | 覆盖文档正文注入、图片内容块和三协议图文转换 |

**V1.32（2026-08-25）— 原生基础工具直连与 MCP 扩展收敛**

基础工具从内部 MCP Host 迁回模型原生 Function Calling 的受控直连路径：
`read`、`write`、`edit`、`bash`、`web_search`、`web_fetch`、`task` 均不经 MCP
catalog/provider；`GET /api/mcp/tools` 只保留评测/RAG 扩展目录，当前展示
`platform.tasks.task.create/status/cancel`。既有 WebSocket `tool_call`、`tool_result`、`call_id` 与错误码不变。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/context.py` / `native.py` | 抽离运行时上下文，新增基础工具直连的异步、超时与取消边界。 |
| `backend/api/app/harness/execution/registry.py` / `toolnode.py` / `agent/graph.py` | 以 `transport=native|mcp` 分流；默认图不再构建基础工具 MCP Host。 |
| `backend/api/app/harness/execution/dispatch.py` | 流式 read、排他/原子写入、Runner/bwrap 命令链检查、Firecrawl 搜索、安全网页抓取和会话内 task 清单。 |
| `backend/api/app/config.py` / `.env.example` / `docker-compose.yml` | 新增仅 API 容器可见的 `FIRECRAWL_API_URL` / `FIRECRAWL_API_KEY`。 |
| `backend/api/app/routers/mcp.py` / `frontend/src/views/AdminProfiles.vue` | MCP 清单只展示 `platform.tasks` 与未来扩展，不混入原生基础工具。 |
| `frontend/src/components/agent/ToolCard.vue` | 基础工具中文标题与 read/web/task 的受控结果投影。 |
| `backend/api/tests/test_harness_execution.py` / `test_harness_mcp.py` | 覆盖基础直连不进 MCP、Firecrawl、SSRF、任务拆解、原子读写和扩展 MCP 回归。 |

**V1.33（2026-08-25）— 单回合多条 assistant_message**

同一回合可落多条阶段叙述与最终交付句；`response.completed` 仍为整轮结束。
可选 `interim=true` 不结束生成态。清单复用 `plan.slots.steps`，不新增事件名。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3 `assistant_message` 允许多条 + `interim` |
| `backend/api/app/agent/react.py` | native 同轮正文+ToolCall 先发阶段叙述 |
| `frontend/src/views/Agent.vue` | 按事件序另开助手气泡；渲染 plan 步骤清单 |

**V1.34（2026-08-25）— 原生工具模型可见结果上限**

所有原生 ToolCall 回传模型的单条正文统一 ≤8,000 字符，避免大文档/长 bash/网页正文拖垮下一轮预填充。`read` 字符窗口与该上限对齐；未读完时 `model_text` 携带 `next_offset`。浏览器 `tool_result.data` 预览仍 ≤500 字符。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/context/observation.py` | 冻结 `MODEL_TOOL_RESULT_MAX_CHARS=8000` |
| `backend/api/app/harness/execution/dispatch.py` / `sandbox.py` / `registry.py` | read/web/bash 窗口对齐；read 大文件按块统计剩余行 |
| `backend/api/app/agent/react.py` / `toolnode.py` | 回传截断 + 工具/模型耗时与 payload 字符数追踪 |

**V1.35（2026-08-25）— 确认卡、短票 Redis、真实压测下发**

LangGraph `reflect` 在规划 `delivery=confirm` 且复核通过后发出确认卡（默认 `sample_size=1000` / `temperature=0` / `max_tokens=1024`），对话路径不得 `kind=stress`。WS 短票 `jti` 使用 Redis `SET NX` + JWT 剩余 TTL，进程重启后未过期票据不可复用；Redis 不可用时回退进程内存。压测由 Worker HTTP 下发 `stress` 容器，取消立即停发，报告 `time_series` 供 `GET /api/tasks/{id}/stress-series`。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/confirm_spec.py` / `app/agent/reflect.py` | 从规划拼装 TaskSpec 并在 reflect 发出 `confirm` |
| `backend/api/app/ws_tickets.py` / `app/routers/ws.py` | 短票单次消费与确认卡作者元数据 |
| `backend/worker/app/stress.py` / `backend/stress/main.go` | Worker 下发真实发压、可取消、写曲线 |
| `docker-compose.yml` | Worker `STRESS_URL=http://stress:19090` |

**V1.36（2026-08-25）— ContextMeter 服务端计算**

`GET /api/sessions/{id}/messages` 的 `context_meter` 按 `recent_window`（末尾 20 条 user/assistant）+ 协议档 `context_window` + 常驻 Skill Hint + `compact_summary` 计算 token 与窗口占比。不再返回 `null`；前端圆环只读该对象。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/context/meter.py` | `compute_meter` / `estimate_tokens` |
| `backend/api/app/routers/sessions.py` | 历史接口下发真实 `context_meter` |
| `frontend/src/components/agent/ContextMeter.vue` | 已压缩徽标；圆环底色略加深 |
| `docs/AI测试与评估平台-Harness-上下文工程层.md` | V0.4.2 校准计量已接线 |

**V1.37（2026-08-26）— read 防重复与 ToolCard 行级预览**

相同 `path+offset` 的 `read` 只执行一次（JSON ReAct 与原生 ToolCall 同一守卫）。预览按完整行截取，最多 4000 字符；`next_offset` 可作为下次 `offset` 别名。ToolCard 展示输入字段、行号与 Markdown 渲染。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/react.py` | 原生路径 OR-4；`READONLY_REPEAT_LIMIT=1`；`next_offset` 归一 |
| `backend/api/app/harness/execution/dispatch.py` / `registry.py` | 完整行预览、内容预算预留、`next_offset` 别名 |
| `frontend/src/components/agent/ToolCard.vue` | 字段/行号/命令/文件内容 + MarkdownView |
| `frontend/src/utils/toolCard.ts` | 成功后默认展开的工具名单 |
| `docs/AI测试与评估平台-API.md` | §4.3 `read` 预览契约 |

**V1.39（2026-08-26）— 下单偏好与自定义斜杠落地**

`GET /api/agent/prefs` 改为读取 `settings.agent_prefs:{user_id}`；仅 `confirm_ack.ok=true` 且任务已入队后写入。`GET/POST/DELETE /api/slash-commands` 完成 M2 CRUD（按用户存 `settings.slash_commands:{user_id}`），空列表表示已启用无命令。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/memory/preference.py` | 偏好投影、入队后抽取允许字段 |
| `backend/api/app/harness/memory/slash_store.py` | 自定义斜杠校验与存取 |
| `backend/api/app/routers/agent_prefs.py` / `slash_commands.py` | REST 入口 |
| `backend/api/app/harness/orchestration/confirm.py` | 入队成功写偏好 |
| `frontend/src/components/agent/SlashPalette.vue` | 添加/删除我的命令 |

**V1.40（2026-08-26）— `/cancel` / `/stress` 解禁**

斜杠仍全部走 `user_message`，没有第五种上行事件。`/cancel` 由 `ws.py` 拦截后取消本会话非终态任务（权限同 REST cancel），下发 `task.cancel` 的 `tool_result`。`/stress` 发出质量任务确认卡且 `with_stress=true`，`kind` 不得为 `stress`；空槽用偏好预填。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | `/cancel` `/stress` 收包循环拦截 |
| `backend/api/app/harness/orchestration/confirm_spec.py` | `build_slash_stress_spec` |
| `backend/api/app/agent/routing.py` | HELP_TEXT 与图内防御提示 |
| `frontend/src/agent/slashRegistry.ts` | 解禁 `/cancel` `/stress` |
| `frontend/src/components/agent/ConfirmCard.vue` | 以内联卡为事实源合并确认卡 |

**V1.41（2026-08-26）— 确认卡丢掉已删除资产 ID**

`/stress` 与偏好预填可能带上已硬删除的协议档 ID，chip 列表没有对应项，用户点不掉；`confirm_ack` 入队后 Worker 报「协议档不存在或已删除」。发卡与入队前按现网表过滤；前端选项加载后再滤一遍未 ack 卡。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/confirm.py` | `drop_stale_asset_ids`：入队前丢掉已删除资产 |
| `backend/api/app/routers/ws.py` | `/stress` 发卡前同样过滤 |
| `frontend/src/views/Agent.vue` | 现网列表过滤偏好/规划预填的失效 ID |

**V1.42（2026-08-26）— Direct `/help` 补 `response.completed`**

`response.completed` 仍是整轮结束（§4.3）。Direct 不经 reflect，此前 `/help` 只发 `assistant_message`，协议探针与等待 completed 的客户端会超时。Direct 所有出口在业务事件后追加本轮唯一 completed：`/help` 为 `stop`，未知斜杠与图内防御提示为 `error`。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/routing.py` | Direct 出口追加 `response.completed` |
| `backend/api/tests/test_agent_routing.py` | `/help` / 未知斜杠 / 图内防御断言末帧 completed |
| `docs/AI测试与评估平台-Harness-编排层.md` | V0.4.6：Direct 收尾对齐 Chat/ReAct |

**V1.43（2026-08-26）— 思考链合并与 completed 收尾顺序**

上游 reasoning 按字增量时，`thought.stream=think` 允许按间隔合并后再发。有思考链时持久事件顺序为交付句 → `think_final` → `response.completed`。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/think_stream.py` | 思考增量合并器 |
| `backend/api/app/routers/ws.py` | 合并下发 think；think_final 插入 completed 之前 |
| `backend/api/tests/test_think_stream.py` | 首帧立即下发、后续按间隔合并 |

**V1.44（2026-08-26）— ToolCall 真实流式、权限与恢复契约**

`tool_call` 必须先持久化，随后才允许同 `call_id` 的 `tool_progress`、`tool_output_delta` 出现；两个增量事件只给在线会话成员，不落库、不补发。`tool_result` 保持唯一持久化终态，失败结果携带脱敏 `recovery`。浏览器输出只来自注册表定义的安全投影，单次调用最多 4,000 字符，禁止回传完整 Observation。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/registry.py` / `policy.py` | 声明并校验工具描述、输入/输出 Schema、权限边界与恢复策略。 |
| `backend/api/app/agent/react.py` / `harness/execution/toolnode.py` | 先创建 ToolCall，再经 custom 通道下发进度与安全输出，最终写入 ToolResult。 |
| `backend/api/app/routers/ws.py` | 将工具瞬态帧仅广播给在线同会话成员。 |
| `backend/api/app/harness/execution/dispatch.py` / `sandbox.py` / `backend/runner/main.py` / `backend/shared/sandbox_kernel.py` | read/write/bash 的安全投影及 bash Runner NDJSON 转发。 |
| `frontend/src/views/Agent.vue` / `components/agent/ToolCard.vue` / `api/types.ts` | ToolCard 阶段加载、行级实时输出、恢复建议和 `call_id`/`seq` 关联。 |
| `backend/api/tests/test_harness_execution.py` / `test_sandbox_runner_client.py` / `backend/runner/tests/test_runner.py` | 覆盖契约登记、ToolNode 流、Runner NDJSON 转发。 |

**V1.45（2026-08-26）— 思考链不暴露隐藏 CoT**

`thought.stream=think` / `think_final` 只承载可展示摘要。上游英文隐藏思维链由服务端替换为短中文摘要；中文思考原文保留。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/think_stream.py` | `sanitize_reasoning` / `ReasoningDisplayFilter` |
| `backend/api/app/routers/ws.py` | 流式与 think_final 走摘要过滤 |
| `backend/api/tests/test_think_stream.py` / `test_harness_probe_l2.py` | 隐藏 CoT 替换与探针拒绝原文 |

**V1.46（2026-08-26）— native 内容块交错流：ToolCall 结束当前上游响应**

不新增事件名或字段。`native` 首轮与回填后回合均流式推送 `assistant_delta`；完整 `tool_call` 只在该次上游响应结束后持久化。一次 ToolCall 终止当前上游响应，结果回填后才发起下一请求。同轮多调用仍串行；`legacy` 行为不变。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §3.5 `tool_call_mode`、§4.3 `call_id` 规则补充响应结束语义 |
| `backend/api/app/agent/react.py` | native 首轮改走 `gateway.stream()` |
| `backend/api/tests/test_agent_react.py` / `test_llm_graph.py` / `test_adapters.py` | 首轮交错流与三协议 text→tool_call 夹具 |

**V1.47（2026-08-26）— Agent 交错流灰度度量**

新增 `GET /api/agent/metrics`：进程内首 delta / ToolCall 解析延迟、批次并发、取消与不完整流比例。不含正文与参数。不新增 WS 事件或 `segment_id`。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §3.4 `GET /api/agent/metrics` |
| `backend/api/app/harness/execution/stream_metrics.py` / `stream_policy.py` | 脱敏计数、协议档白名单、并行脚踢线 |
| `backend/api/app/routers/agent_prefs.py` | 只读度量入口 |
| `backend/api/tests/test_stream_rollout.py` | 白名单、脚踢冷却、快照不含载荷 |

**V1.48（2026-08-26）— 同轮多调用默认串行，灰度只读并行**

覆盖 V1.46「同轮多调用仍串行」的绝对表述。默认仍串行；灰度开启后仅 `read` / `web_search` / `web_fetch` 可同波并行。模型 `role=tool` 回填始终按原始 `call_id` 顺序。关联错乱与 `UPSTREAM` 每模型回合只记一笔终态，避免成功流把脚踢计数清零。不新增 WS 事件。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3 `call_id` 规则：默认串行 + 灰度只读并行 |
| `backend/api/app/agent/react.py` | 每回合只记一笔流式终态；关联错乱可累计脚踢 |
| `backend/api/tests/test_stream_rollout.py` / `test_agent_react.py` | 连续 associate_error 触发脚踢；流式空 call_id 两轮 rounds=2 |

**V1.49（2026-08-27）— 协议档新增 max_output_tokens 输出上限**

协议档新增 `max_output_tokens`（256–131072，默认 `8192`，存量数据回填 8192 保持既有行为）。WS Agent 模型调用从当前 Agent 协议档读取该值作为 `max_tokens`，不再硬编码 8192；长文档总结/导出类任务可调大，避免回答在输出上限处被上游截断。不影响离线评测、裁判与用例生成调用。不新增 WS 事件。

| 文件 | 作用 |
| :--- | :--- |
| `backend/shared/models.py` / `migrations/versions/e7a1c3f52b48_*.py` | `protocol_profiles.max_output_tokens` 列与迁移 |
| `backend/api/app/schemas.py` / `app/routers/profiles.py` | 创建/更新/响应支持新字段 |
| `backend/api/app/routers/ws.py` | Agent 模型配置从协议档读取输出上限 |
| `frontend/src/components/modals/ProfileModal.vue` / `src/api/types.ts` | 协议档表单与类型支持新字段 |

