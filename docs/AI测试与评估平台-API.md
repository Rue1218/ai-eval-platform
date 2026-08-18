# AI 测试与评估平台 — API 契约

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.1 |
| 对应 PRD | V1.6.4（功能唯一权威） |
| 对应设计规范 | V1.3（错误码文案、确认卡字段名、调度中心规范） |
| 对应前端计划 | V1.1 |
| 对应后端计划 | V1.1 |
| 撰写日期 | 2026-08-18 |
| 适用范围 | V1.0：浏览器 `web/` ↔ `api`；全域 REST + WS 接口规范 |

---

## 0. 文档地位

| 层级 | 文档 | 管什么 |
| --- | --- | --- |
| L0 | PRD V1.6.3 | 做不做、字段语义、状态机、事件名、错误码枚举 |
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
| 500 | `INTERNAL` | 内部错误，请重试或联系管理员 |

确认卡 / 表单校验失败：`VALIDATION`，`fields` 给前端卡内红字，**不要**只靠 Toast。  
错误 body **不得** 含 Key、Cookie、stack。

### 1.4 枚举

| 名 | 值 |
| --- | --- |
| `role` | `admin` `engineer` `readonly` |
| `kind` | `benchmark` `rag` `testcase` `stress` |
| `task_status` | `queued` `running` `succeeded` `failed` `cancelled` `awaiting_case_confirm` |
| `protocol` | `openai_chat` `openai_responses` `anthropic_messages` |
| `profile_usage` | `target` `agent` `judge`（被测 / Agent 后端 / 裁判；同一档可多用途，**Agent 后端全局仅一个**，见 settings） |
| `metric` | `exact` `contain` `regex` `rouge_l` `bleu` |
| `rag_mode` | `naive` `local` `global` `hybrid` |
| `stress_env` | `dev` `test` `staging` `prod` |
| `file_kind` 扩展名 | `.md` `.txt` `.html` `.pdf` `.json` `.yaml` `.yml` `.xlsx` `.xls` `.csv` `.jsonl` |

---

## 2. 前后端对应总表

浏览器前端所有图、表与表单均统一经由 `assets/api.js` 调用对应 REST/WS 接口，实现 100% 数据动态拉取与实时落盘。

| 模块 / 页面 | 前端功能与图表 | 调用的后端 API 接口 | 请求方法 | 权限口径 |
| --- | --- | --- | --- | --- |
| **登录 (login.html)** | 账号登录 / 首次强制改密 | `/api/auth/login`, `/api/auth/change-password` | POST | 免登录 / 成员 |
| **智能体 (agent.html)** | 会话列表 / 意图识别 / TaskSpec 下单 / 迷你拓扑坞 | `/api/sessions`, `/ws/agent`, `/api/profiles`, `/api/datasets`, `/api/kb`, `/api/tasks`, `/api/dispatch/overview` | GET/POST/WS | 成员 · 全员同权 |
| **调度中心 (dispatch.html)** | 调度大盘雷达 / Worker 节点池 / 贝塞尔队列连线 / 策略治理 | `/api/dispatch/overview`, `/api/dispatch/workers`, `/api/dispatch/config`, `/api/tasks?status=queued` | GET/PUT | 成员 · 全员同权 |
| **任务中心 (tasks.html)** | 任务大盘 / 六态过滤表格 / 抽屉详情 / 取消与重跑 | `/api/tasks`, `/api/tasks/{id}`, `/api/tasks/{id}/cancel`, `/api/tasks/{id}/rerun` | GET/POST | 成员 · 全员同权 |
| **报告中心 (report.html)** | 报告列表 / 3合1详情 (Benchmark雷达/RAG水平柱状/压测多轴曲线) / Markdown导出 / 7天免登分享 / 冻结基线 | `/api/reports`, `/api/reports/{id}`, `/api/reports/{id}/samples`, `/api/reports/{id}/share`, `/api/reports/{id}/baseline` | GET/POST | 成员 · 全员同权 |
| **数据集工作台 (datasets.html)** | 数据集目录树 / 行内即点即改网格 / 自定义列扩展 / AI 数据集生成 | `/api/datasets`, `/api/datasets/{id}`, `/api/datasets/{id}/rows`, `/api/datasets/ai-generate`, `/api/kb` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **用例工作台 (cases.html)** | 6大策略分布图 / 用例表格编辑 / 72h倒计时 / 批量映射入库 / AI PRD 用例抽取 | `/api/case-sets`, `/api/case-sets/{id}`, `/api/case-sets/{id}/cases`, `/api/case-sets/{id}/confirm`, `/api/case-sets/{id}/cancel`, `/api/case-sets/{id}/map`, `/api/case-sets/ai-generate` | GET/POST/PUT | 成员 · 全员同权 |
| **知识库 (kb.html)** | 3栏工作台 / 文档切块流 / 2D 向量投影散点图 / 4模式检索 Playground / 黄金 QA / ✨ AI 抽取黄金 QA | `/api/kb`, `/api/kb/{id}`, `/api/kb/{id}/documents`, `/api/kb/{id}/query`, `/api/kb/{id}/gold-qa` | GET/POST/DELETE | 成员 · 全员同权 |
| **协议档与智能体 (admin-profiles.html)** | 4 Tab 架构 (模型协议档/MCP 工具中心/Agent 技能编排/运行时治理) / 连通性探活 Ping | `/api/profiles`, `/api/profiles/{id}/check`, `/api/mcp/servers`, `/api/mcp/tools`, `/api/skills`, `/api/admin/settings` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **压测治理 (admin-stress.html)** | 7天峰值 QPS 面积图 / Host 白名单表格 / 安全阈值 / 成本预算 / Prometheus `/metrics` | `/api/admin/stress/settings`, `/api/admin/stress/whitelist`, `/api/admin/stress/usage`, `/metrics` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **成员与账号 (admin-users.html)** | 4 维 KPI 卡片 / 成员搜索表格 / AI 异地登录检测 / 24h 登录活动柱状图 / 改密与停用 | `/api/users`, `/api/users/{id}/status`, `/api/users/{id}/reset-password`, `/api/users/{id}/audit-logs` | GET/POST/PUT | 成员 · 全员同权 |

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

规则：≥8 位，含字母和数字。引导管理员首次改密时 `old_password` 为初始密。成功后 `must_change_password=false`。

#### `GET /api/auth/me`

```json
{
  "id": "uuid",
  "username": "alice",
  "role": "engineer",
  "must_change_password": false
}
```

#### `POST /api/auth/ws-ticket`

工程师或管理员。5 分钟有效，一次性或短期内可重复升级（实现可允许多张未过期票，过期即废）。

```json
{ "ticket": "opaque", "expires_in": 300 }
```

只读 403。

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

---

### 3.4 会话（方案 A，M1 冻结）

只读角色 403。V1 **无** 删除会话接口。

#### `GET /api/sessions`

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "帮我下一单 Benchmark",
      "updated_at": "2026-09-21T12:00:00Z",
      "active_task": { "id": "uuid", "kind": "benchmark", "status": "running" }
    }
  ],
  "total": 3
}
```

`active_task`：该会话当前非终态任务（含压测子任务），无则 `null`。

#### `POST /api/sessions`

```json
{ "id": "uuid", "title": "新会话", "created_at": "..." }
```

空会话，不创建 task。

#### `GET /api/sessions/{id}/messages`

历史回放（REST）。实时增量只走 WS。  
item：`id, role: user|assistant|system, content, attachments[], created_at`。  
确认卡/工具卡以 WS 事件为准；REST 历史至少能还原用户文本与助手文本。实现可将 `ws_events` 一并返回：

```json
{
  "messages": [],
  "events": [ { "event_id": 1, "event": "thought", "payload": {} } ]
}
```

`events` 建议带上，避免刷新后工具卡丢失。

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

#### `GET /api/files/{id}`

元数据，同 POST 响应。不回文件二进制。下载如需要：`GET /api/files/{id}/content`（登录，M1 可选；用例导出走 case-sets export）。

---

### 3.6 协议档

响应 **永不** 含 Key，即使 PATCH 刚写入。空字符串 Key = 不修改。

#### `GET /api/profiles`

全员可列（无 Key），供确认卡。  
item：`id, name, protocol, base_url, model, usages[], created_at`

#### `POST /api/profiles`  仅 admin

```json
{
  "name": "gpt-test",
  "protocol": "openai_chat",
  "base_url": "https://api.example.com",
  "model": "gpt-4.1",
  "api_key": "sk-...",
  "usages": ["target"]
}
```

`anthropic_messages` 可另存 `anthropic_version`（默认 `2023-06-01`）。变更写审计。

#### `PUT /api/profiles/{id}` / `DELETE /api/profiles/{id}`

修改或删除协议档（正在被 Agent 后端引用的协议档禁止删除，写审计）。

#### `POST /api/profiles/{id}/check`

向被测模型或裁判端点发送轻量探活 ping 请求。响应：

```json
{ "ok": true, "latency_ms": 120 }
```
或 `{ "ok": false, "code": "UPSTREAM", "message": "401 from upstream" }`（日志与响应严禁携带 API Key）。

---

### 3.6.1 MCP 服务器与工具中心

#### `GET /api/mcp/servers` / `POST /api/mcp/servers` / `DELETE /api/mcp/servers/{id}`

维护已挂载的 MCP 服务节点（包含内置 Eval-Core 服务与外部 SSE / Streamable HTTP 节点）。

```json
{
  "id": "uuid",
  "name": "vector-search-mcp",
  "transport": "Streamable HTTP | SSE | Stdio",
  "endpoint": "http://192.168.1.100:8080/mcp",
  "status": "online",
  "latency_ms": 32,
  "tools_count": 2
}
```

#### `POST /api/mcp/servers/{id}/check`

对指定的 MCP Server 发起探活 Ping 与工具清单动态握手发现。

#### `GET /api/mcp/tools`

获取当前智能体环境中所有受控的短工具清单（`model.list`, `dataset.list`, `kb.list`, `report.get`, `task.create`, `task.cancel`, `dispatch.overview`）及权限级别（`read / write`）。

---

### 3.6.2 Agent 技能与 Prompt 编排

#### `GET /api/skills` / `POST /api/skills` / `PUT /api/skills/{id}` / `DELETE /api/skills/{id}`

维护智能体在 Benchmark 对比、RAG 评估、用例生成与容量压测场景下的 System Prompt 模版与依赖短工具绑定。

```json
{
  "id": "skill-benchmark",
  "name": "基准对比评测",
  "desc": "自动识别被测模型数量、推荐标准评测集并构建先评后压 TaskSpec",
  "system_prompt": "你负责大模型基准测试...",
  "tools": ["model.list", "dataset.list", "task.create"],
  "temperature": 0.2,
  "max_tokens": 1024,
  "is_builtin": true
}
```

---

### 3.7 数据集工作台

#### `GET /api/datasets` / `GET /api/datasets/{id}`

```json
{
  "id": "uuid",
  "name": "smoke-20",
  "version": 3,
  "row_count": 20,
  "pending_complete_count": 2,
  "metric": "contain",
  "owner_id": "uuid",
  "created_at": "..."
}
```

#### `POST /api/datasets`

```json
{ "name": "smoke-20", "metric": "contain" }
```

#### `PUT /api/datasets/{id}`

可改 `name`、`metric` 及目录结构（已有报告不受影响，对比仍看任务快照）。

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

根据场景描述、种子样本扩写或 PRD 文档提取，通过大模型批量合成高质量评测数据集。

```json
{
  "mode": "scene | seed | doc",
  "prompt": "生成 10 条跨境支付高频问答与边界风控问答",
  "count": 10,
  "difficulty_ratio": "4:4:2",
  "adversarial_ratio": 0.2
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

创建新用例集或文件夹。

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
{ "target": "dataset", "dataset_id": "uuid", "case_ids": ["c-001", "c-002"] }
```

缺字段行进入目标集 `pending_complete`，写 `source_case_id` + 用例版本。

#### `POST /api/case-sets/ai-generate`

根据 PRD / OpenAPI / Excel 文档，按 6 大策略精细配比（正向 40% / 反向 25% / 边界 15% / 等价类 10% / 状态迁移 5% / 场景 5%）智能生成候选用例集。

```json
{
  "source_doc_id": "doc-01",
  "strategy_weights": { "positive": 40, "negative": 25, "boundary": 15, "equivalence": 10, "state": 5, "scenario": 5 },
  "complexity": "medium",
  "max_count": 45
}
```

#### `GET /api/case-sets/{id}/export?fmt=xlsx|xmind`

`fmt` 必填。响应文件流。Excel 8+。

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
  "owner_id": "uuid"
}
```

`kind`：`lightrag`（原生 query，支持切块与 2D 投影）| `external_chat`（外部 RAG 服务本身挂在 profile，仅 `chat/completions`）。  
`PUT` `{ "is_core": true }` 标为核心库写审计。

#### `POST /api/kb/{id}/documents`  multipart `file`

上传文档建索引；后端生成 `doc_id` UUID 写入 LightRAG metadata，自动执行分块与向量化。响应 `{ "doc_id", "filename", "status": "indexed" }`。

#### `DELETE /api/kb/{id}/documents/{doc_id}`

删除指定文档及其向量切块索引。

#### `POST /api/kb/{id}/query`

执行 LightRAG 原生 4 模式检索测试（Playground），返回 Top-K 切块、相似度得分与重排位移。

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
- 会话已有非终态任务（含压测子任务）→ 400 `VALIDATION`（占槽），前端应已禁用按钮。  
- 平台 `max_running_tasks` 满 → **仍** `queued`（3.4），可附 `warning: "CONCURRENCY"` 字段（可选）。  
- `kind=stress` 一般由 worker 在质量 `succeeded` 且 `with_stress=true` 时创建；人手 POST 须带 `parent_task_id`，且父任务必须 succeeded。  
- 一任务一种 `kind`。V1 禁止 Benchmark+RAG 混单。

#### `GET /api/tasks?status=&kind=&offset=&limit=`

全员。item：`id, kind, status, progress, dataset_id, kb_id, parent_task_id, creator_id, created_at, report_id?`

`progress`：`{ percent?, done, total, message }`

#### `GET /api/tasks/{id}`

详情 + `config` 快照（确认卡 JSON）+ `events`（`task_events` 时间线：`at, level, message`）。

#### `POST /api/tasks/{id}/cancel`

```json
{ "ok": true, "status": "cancelled" }
```

权限：创建者或 admin。  
评测/RAG/用例：当前样本结束后停。  
压测：**立即**停发。  
前端 Dialog 文案必须按 kind 分流，接口本身一个。

#### `POST /api/tasks/{id}/rerun`

新任务拷 `config`，新 `id`，`queued`。不复活旧行。

#### `POST /api/tasks/{id}/approve-stress`  M4

`{id}` 为 **压测子任务** 或质量任务（实现须能解析到对应 `kind=stress` 子任务）。  
会签人 ≠ 创建者（工程师发起 `prod` 时须另一名 admin 或 engineer）。管理员对自己的 `prod` 可二次确认。  
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

登录可 GET（只读角色可看并发/预算数字，看不到通知密钥）。敏感密钥不回显。

```json
{
  "agent_profile_id": "uuid",
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

---

## 4. WebSocket（F-AGT-01 / 02）

### 4.1 连接

1. `POST /api/auth/ws-ticket`  
2. `GET /ws/agent?ticket={ticket}&session_id={uuid}&last_event_id={n}`  
   - 首次：可无 `last_event_id`；`session_id` 建议已由 REST 创建。  
   - 重连：必须带 `session_id` + `last_event_id`，服务端从 `ws_events` **补发** `event_id > last_event_id` 的事件。  
3. ticket 非法/过期：关闭连接，前端重新领票。  
4. **禁止** `?token=` 长期 JWT。

心跳：30s；传输层 ping/pong。应用层服务端可发 JSON `pong`。前端不发 JSON `ping`。

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

### 4.3 服务 → 前端（事件名不可改、不可增减）

| event | payload | 前端渲染 |
| --- | --- | --- |
| `thought` | `{ "text": "..." }` | ThoughtCard |
| `tool_call` | `{ "name": "model.list", "arguments": {} }` | ToolCard pending；标题用中文名 |
| `tool_result` | `{ "name": "model.list", "ok": true, "data": {} }` 或 `{ "ok": false, "error": "..." }` | ToolCard done |
| `confirm` | TaskSpec（§6） | ConfirmCard，等 `confirm_ack` |
| `progress` | `{ "percent": 40, "done": 40, "total": 100, "message": "..." }` | ProgressDock。**仅这四字段**（percent 可选） |
| `report` | `{ "report_id": "uuid" }` | ReportCard |
| `error` | `{ "code": "UPSTREAM", "message": "..." }` | ErrorStrip + Toast |
| `pong` | `{}` | 不渲染 |

禁止：`thinking` `token` `chat:send` `tool_call_start` 及任何参考文档旧名。

短工具中文名（ToolCard 标题）：

| name | 标题 |
| --- | --- |
| `model.list` | 列出协议档 |
| `dataset.list` | 列出数据集 |
| `kb.list` | 列出知识库 |
| `task.get` | 查询任务 |
| `report.get` | 读取报告 |
| `task.create` | 创建任务 |
| `task.cancel` | 取消任务 |
| `testcase.confirm` | 确认用例入库 |

长工具不由 Agent 进程跑完；前端只收 `progress` / `report` / `error`。

### 4.4 前端 → 服务（仅此三条 JSON）

```json
{ "event": "user_message", "payload": { "text": "帮我下一单 Benchmark", "attachments": [ { "file_id": "uuid" } ] } }
```

```json
{ "event": "confirm_ack", "payload": { "ok": true, "patch": { "with_stress": false } } }
```

```json
{ "event": "cancel_task", "payload": { "task_id": "uuid" } }
```

规则：

- `confirm_ack.ok=false`：不入队，卡标已取消。  
- `ok=true`：`patch` 与原 confirm 深合并后按 §6 校验，通过才 `task.create`。  
- 同一会话同一时刻最多一张待确认卡。  
- `cancel_task` 权限与 REST cancel 相同。

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

`stress.qps` ≤ settings.max_qps（默认 500），`duration_s` ≤ max_duration_s（默认 1800）。

---

## 6. 内部 MCP（浏览器不调用）

Agent Host 与 worker 共用。入参/出参与 PRD 5.5 一致。错误码同 §1.3。

| 工具 | 类型 | 入参 | 出参 | 阶段 |
| --- | --- | --- | --- | --- |
| `model.list` | 短 | — | `{id,name,protocol}[]` 无 Key | M1 |
| `dataset.list` | 短 | — | `{id,version,row_count}[]` | M2 |
| `kb.list` | 短 | — | `{id,doc_count}[]` | M3 |
| `task.get` | 短 | `task_id` | 状态、进度 | M1 |
| `report.get` | 短 | `report_id` | 摘要 + 下载路径 | M2 |
| `task.create` | 短 | TaskSpec | `task_id` | M1 |
| `task.cancel` | 短 | `task_id` | `{ok}` | M1 |
| `testcase.generate` | 长 | `file_id` 或 `text` | `case_set_id` | M2 |
| `testcase.confirm` | 短 | `case_set_id, edits?` | 状态 succeeded | M2 |
| `benchmark.run` | 长 | TaskSpec 评测段 | `report_id` | M2（M1 mock） |
| `rag.evaluate` | 长 | TaskSpec RAG 段 | `report_id` | M3 |
| `stress.run` | 长 | `parent_task_id` + `stress` | `report_id` | M4 |

Agent **只**调短工具 + `task.create`。长任务由 worker 执行；`stress.run` 只下发 stress 容器。

JSON Schema 冻结点：短工具 M1 W4；评测长工具 M2 W6；RAG M3 W10；stress M4 W13。冻结后的 schema 文件挂 `api/mcp/schemas/`，以本文字段名为准。

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
| M1 | 认证、me、users、files、profiles、check、sessions、tasks CRUD/cancel/rerun、WS 全事件、settings（agent_profile_id） | 对话下单 mock；断线补发；协议档 |
| M2 | datasets、rows、case-sets confirm/export/map(dataset)、reports、share、baseline、budget 停 | 对比报告；待补全；表单 POST /tasks |
| M3 | kb、docs、gold-qa、map(gold_qa)、RAG 报告字段、Judge 可选 | Hit Rate@5 |
| M4 | settings.stress/notify、approve-stress、stress-series、解读只读 report_id | 先评后压；Grafana 同 task_id |

---

## 9. 明确不提供的接口（V1.0）

| 不要做 | 原因 |
| --- | --- |
| 对外 Open API / 长期 API Token | F-CM-08 V1.1 |
| `/api/chat/completions`、把 LightRAG 伪装成 Chat | F-RAG-01 |
| 改系统提示词、外部 MCP 管理、Ask/Plan | PRD 4.2 |
| 删除会话 | PRD 未要求 |
| 独立审计页对应的写操作以外的产品 UI | 仅 `GET /api/admin/audit-logs` |
| 浏览器直连 MCP 或 `/metrics` | 安全边界 |
| Postman / Markdown 接口解析专用上传类型 | 用例输入 P1 |

---

## 10. 前端实现约束（对应设计规范）

1. `frontend/src/api/http.ts` 只封装本文 §3 路径；`ws.ts` 只封装 §4。  
2. `schemas/confirmCard.ts` 与 §6 同一份类型，供 ConfirmCard 与 `/datasets` `/kb` 抽屉。  
3. 错误码文案用 §1.3，不硬编码第二套。  
4. 不发明本文没有的 query 参数来「先用着」。缺字段提 PR 改本文。

## 11. 后端实现约束

1. OpenAPI（内部）从本文生成或手写，但 **对外不发布**（非 F-CM-08）。  
2. Worker 与 Agent 调同一 MCP，不另做一套 REST 给 worker 跑评测（worker 可进程内调）。  
3. Key Fernet 加密；GET 不回显；日志不落 Key。  
4. 状态机与取消语义见 PRD 3.3；先评后压由 worker 创建子任务，不要求前端二次 `POST /api/tasks` kind=stress（`prod` 除外走会签）。

---

## 附录 A  一致性检查记录（V1.0）

检查对象：PRD V1.6.3、设计规范 V1.2、总计划 V1.0、前端计划 V1.1、后端计划 V1.1、本文。

### A.1 PRD 5.9 摘要 vs 本文

| 5.9 原文 | 本文 | 一致？ |
| --- | --- | --- |
| login/logout | §3.2 | 是 |
| GET/POST users | + PATCH、reset-password | 补全（F-CM-03 停用/改角色/重置密） |
| GET/POST files | + GET `{id}` | 补全 |
| CRUD profiles | + check | 补全（规范连通性） |
| CRUD datasets / case-sets / confirm | + upload/rows/map/export | export 在 5.4.1；map 在 5.4.2 |
| CRUD kb / docs / gold-qa | + 删文档、gold upload、is_core | 补全（PRD 2.1） |
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
- `PATCH /api/users/{id}`、`POST /api/users/{id}/reset-password`（计划写「停用/改角色/重置密」未写路径）  
- 会话方案 A 从「周三二选一」改为冻结  
- `POST /api/datasets/{id}/upload`、`GET .../rows`  
- `POST /api/case-sets/{id}/map`  
- `POST /api/gold-qa/{id}/upload`  
- `DELETE /api/kb/{id}/docs/{doc_id}`  
- `GET /api/files/{id}`  

后端计划多出的 `GET /api/admin/audit-logs`、`GET /api/health`：前端不强制调用，一致。

### A.6 角色 vs PRD 2.1

只读不可 Agent / 写资源 / 管理写；分享免登录只读报告；`prod` 会签；取消权限：一致。

### A.7 内部边界

MCP 浏览器不调：与 PRD 3.1、前端计划「禁止把 MCP 当 REST」一致。  
`/metrics` 浏览器不调：与 F-ST-04、前端 F-ST-04「正确不排」一致。

### A.8 发现的文档间隙（检查时已在本文冻结，计划需回写）

1. 登录后刷新身份：PRD 未写 `GET /api/auth/me`，SPA + Cookie 必需 → 本文补全。  
2. 用户停用/改角色/重置密：5.9 只有 GET/POST users → 拆 PATCH 与 reset-password。  
3. 会话 REST：计划二选一 → 冻结方案 A。  
4. 数据集覆盖上传、待补全行、用例映射：功能有、5.9 无独立路径 → 本文给出。  
5. `CONCURRENCY`：PRD 超限保持 queued，与「错误码」并存 → 本文规定默认仍创建 queued，不把该码当创建失败。

检查结论：本文与 PRD 功能无冲突；与 5.9 的差异均为已声明补全。前端计划 / 后端计划已回写为「以 API V1.0 为准」（会话方案 A、`run.k`、`run.use_judge`、`GET /api/auth/me`）。
