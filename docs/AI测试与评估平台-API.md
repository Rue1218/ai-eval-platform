# AI 测试与评估平台 — API 契约

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.0 |
| 对应 PRD | V1.6.3（功能唯一权威） |
| 对应设计规范 | V1.2（错误码文案、确认卡字段名） |
| 对应前端计划 | V1.1 |
| 对应后端计划 | V1.1 |
| 撰写日期 | 2026-08-17 |
| 适用范围 | V1.0：浏览器 `web/` ↔ `api`；不含 Open API（F-CM-08 / V1.1） |

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
- 角色：`admin` / `engineer` / `readonly`。越权 HTTP 403，body `code=UNAUTHORIZED`。未登录 401。

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

浏览器只走「前端调用」列。MCP 与 `/metrics` 不在此表。

| 方法 | 路径 | 前端页面 / 组件 | 后端 | 角色 | 阶段 | PRD |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/api/health` | 无（Compose 探活） | api | 免登录 | M0 | 总计划 |
| POST | `/api/auth/login` | Login | api | 免登录 | M1 | 5.9 |
| POST | `/api/auth/logout` | 退出 Dialog | api | 已登录 | M1 | 5.9 |
| POST | `/api/auth/change-password` | 首次改密 Modal | api | 已登录 | M1 | 2.1 补全 |
| GET | `/api/auth/me` | `auth` store 启动 | api | 已登录 | M1 | 2.1 补全 |
| POST | `/api/auth/ws-ticket` | `ws.ts` | api | 工程师+ | M1 | F-AGT-01 |
| GET | `/ws/agent` | `/agent` | api | 工程师+ 短票 | M1 | F-AGT-01 |
| GET | `/api/sessions` | SessionList | api | 工程师+ | M1 | 6.4 补全 |
| POST | `/api/sessions` | 新建会话 | api | 工程师+ | M1 | 6.4 补全 |
| GET | `/api/sessions/{id}/messages` | 切换会话回放 | api | 工程师+ | M1 | 6.4 补全 |
| GET | `/api/users` | `/admin/users` | api | admin | M1 | F-CM-03 |
| POST | `/api/users` | 开户 Modal | api | admin | M1 | F-CM-03 |
| PATCH | `/api/users/{id}` | 停用 / 改角色 | api | admin | M1 | F-CM-03 补全 |
| POST | `/api/users/{id}/reset-password` | 重置密 Modal | api | admin | M1 | F-CM-03 补全 |
| GET/POST | `/api/files` | Composer / 各上传 | api | 工程师+ | M1 | F-CM-07 |
| GET | `/api/files/{id}` | 附件芯片元数据 | api | 登录 | M1 | F-CM-07 |
| GET | `/api/profiles` | 确认卡下拉 / 管理页 | api | 登录（无 Key） | M1 | F-BM-01 |
| POST/PATCH/DELETE | `/api/profiles` `/api/profiles/{id}` | `/admin/profiles` | api | admin | M1 | F-BM-01 |
| POST | `/api/profiles/{id}/check` | 连通性 Modal | api | admin | M1 | 规范 14.4 补全 |
| GET/POST/PATCH/DELETE | `/api/datasets` … | `/datasets` | api | 工程师+；删他人=admin | M2 | F-BM-03 |
| POST | `/api/datasets/{id}/upload` | 覆盖上传 Dialog | api | 工程师+（自己的） | M2 | F-BM-03 |
| GET | `/api/datasets/{id}/rows` | 待补全 Tab | api | 工程师+ | M2 | F-BM-04 |
| GET | `/api/case-sets` `/api/case-sets/{id}` | `/cases` | api | 工程师+ | M2 | 5.4 |
| POST | `/api/case-sets/{id}/confirm` | 确认 / 拒绝 | api | 创建者 | M2 | 5.9 |
| POST | `/api/case-sets/{id}/map` | 映射到集 / 黄金 QA | api | 工程师+ | M2/M3 | 5.4.2 补全 |
| GET | `/api/case-sets/{id}/export` | 导出按钮 | api | 工程师+ | M2 | 5.4.1 |
| CRUD | `/api/kb` | `/kb` | api | 工程师+；标核心/删他人=admin | M3 | F-RAG-01 |
| POST | `/api/kb/{id}/docs` | 文档上传 | api | 工程师+ | M3 | 5.9 |
| DELETE | `/api/kb/{id}/docs/{doc_id}` | 删文档 Dialog | api | 自己或 admin | M3 | 2.1 补全 |
| CRUD | `/api/gold-qa` | `/kb` 黄金 QA | api | 工程师+ | M3 | F-RAG-03 |
| POST | `/api/gold-qa/{id}/upload` | 覆盖上传 | api | 工程师+ | M3 | F-RAG-03 |
| POST | `/api/tasks` | ConfirmCard / 抽屉 | api | 工程师+ | M1 起 | F-AGT-07 |
| GET | `/api/tasks` | `/tasks` | api | 全员（只读看） | M1 | F-CM-01 |
| GET | `/api/tasks/{id}` | 任务抽屉 | api | 全员 | M1 | F-CM-01 |
| POST | `/api/tasks/{id}/cancel` | Dialog / `cancel_task` | api | 创建者或 admin | M1 | F-AGT-09 |
| POST | `/api/tasks/{id}/rerun` | 复制为新任务 | api | 工程师+ | M1 | F-AGT-09 |
| POST | `/api/tasks/{id}/approve-stress` | `prod` 会签 | api | 另一名 admin/engineer | M4 | F-ST-05 补全 |
| GET | `/api/tasks/{id}/stress-series` | ProgressDock / Chart.js | api | 全员 | M4 | F-ST-03 补全 |
| GET | `/api/reports/{id}` | `/reports/:id` | api | 全员或 share | M2 | F-CM-02 |
| POST | `/api/reports/{id}/share` | 分享 Modal | api | 登录 | M2 | 5.9 |
| POST | `/api/reports/{id}/baseline` | 冻结 Dialog | api | admin | M2/M3 | F-BM-07 补全 |
| GET/PUT | `/api/admin/settings` | profiles / stress 治理 | api | GET 登录；PUT admin | M1/M4 | 5.9 |
| GET | `/api/admin/audit-logs` | **无页面**（排障） | api | admin | M1 | F-CM-04 补全 |

只读角色：可 GET 任务/报告/分享；不可 Agent、不可写集/KB、不可管理接口。

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

### 3.3 用户（管理员）

#### `GET /api/users`

`{ "items": [UserPublic], "total": n }`  
`UserPublic`：`id, username, role, disabled, created_at`。无密码。

#### `POST /api/users`

```json
{ "username": "bob", "password": "********", "role": "engineer" }
```

#### `PATCH /api/users/{id}`

```json
{ "role": "readonly", "disabled": true }
```

改角色 / 停用写审计。不可停用最后一个管理员。

#### `POST /api/users/{id}/reset-password`

```json
{ "password": "********" }
```

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

#### `PATCH /api/profiles/{id}` / `DELETE /api/profiles/{id}`

仅 admin。正在被 Agent 后端引用的档不可删（`VALIDATION`）。

#### `POST /api/profiles/{id}/check`

用库存 Key 打一发最小请求。响应：

```json
{ "ok": true, "latency_ms": 120 }
```
或 `{ "ok": false, "code": "UPSTREAM", "message": "401 from upstream" }`  
message 不得含 Key。

---

### 3.7 数据集  M2

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

#### `PATCH /api/datasets/{id}`

可改 `name` `metric`（已有报告不受影响，对比仍看任务快照）。

#### `DELETE /api/datasets/{id}`

自己的：工程师+；他人的：仅 admin。进行中任务不取消。

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

---

### 3.8 用例集  M2

#### `GET /api/case-sets` / `GET /api/case-sets/{id}`

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "status": "generated",
  "generated_count": 40,
  "confirmed_count": 0,
  "checks": [
    { "level": "error", "code": "no_core_positive", "message": "无核心正向" }
  ],
  "expires_at": "2026-09-24T12:00:00Z",
  "cases": []
}
```

`checks` 给确认页红字。`expires_at` = 进入 `awaiting_case_confirm` + 72h。

case item：`id, strategy, priority, module, name, steps, expected, mapped, pending_complete`

#### `POST /api/case-sets/{id}/confirm`

创建者。任务须为 `awaiting_case_confirm`。

```json
{ "ok": true, "edits": [ { "id": "case-uuid", "name": "新名称" } ] }
```

- `ok: true` → 入库，任务 `succeeded`；worker **不得**再续跑该任务。  
- `ok: false` → 任务 `cancelled`，不入库。  
采纳率口径：`confirmed_count / generated_count`。

#### `POST /api/case-sets/{id}/map`  M2 映射数据集；M3 可映射黄金 QA

```json
{ "target": "dataset", "dataset_id": "uuid" }
```
或 `{ "target": "gold_qa", "gold_qa_id": "uuid" }`（M3）

缺字段行进入目标集 `pending_complete`，写 `source_case_id` + 用例版本。

#### `GET /api/case-sets/{id}/export?fmt=xlsx|xmind`

`fmt` 必填。响应文件流。Excel 8+。

---

### 3.9 知识库与黄金 QA  M3

#### `GET/POST /api/kb`  `GET/PATCH/DELETE /api/kb/{id}`

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

`kind`：`lightrag` | `external_chat`（外部 RAG 服务本身挂在 profile，KB 仍要黄金 QA）。  
`PATCH` `{ "is_core": true }` 仅 admin。

#### `POST /api/kb/{id}/docs`  multipart

建索引；后端生成 `doc_id` UUID 写入 LightRAG metadata。响应 `{ "doc_id", "filename" }`。  
查询走 LightRAG **原生 query**，本平台 **无** `/api/lightrag/chat` 之类接口。

#### `DELETE /api/kb/{id}/docs/{doc_id}`

#### `GET/POST /api/gold-qa`  `GET/DELETE /api/gold-qa/{id}`

```json
{
  "id": "uuid",
  "kb_id": "uuid",
  "name": "qa-v1",
  "version": 1,
  "row_count": 20
}
```

`POST` 创建元数据：`{ "kb_id", "name" }`。

#### `POST /api/gold-qa/{id}/upload`

列 `question,reference,expected_doc_ids[]?`；≤1 万条；覆盖 `version += 1`。JSONL/CSV。无 id 的样本不进 Hit Rate 分母。

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

### 3.11 报告  M2 起

#### `GET /api/reports/{id}`

登录 Cookie 或 `?share=` 未过期。  
`?fmt=md` → `text/markdown` 下载。

JSON 公共头：

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "kind": "benchmark",
  "created_at": "...",
  "snapshot": { "dataset_version": 3, "metric": "contain", "profile_ids": [] },
  "baseline_id": null,
  "degraded": false
}
```

**benchmark** 另含：`scores[]`（每 profile 主指标）、`fail_rate`、`failed_items[]`、`judge?`（M3）。  
**rag** 另含：`hit_rate_at_k`、`mrr`、`recall_at_k`、`k`、`answer_contain`、`modes[]`、`hit_denominator_note`（无 id 样本不进分母）、`degraded`（≥5pp 相对基线）。  
**stress** 另含：`qps` `rt` `error_rate` `ttft_ms?` `tpot_ms?` `tokens_per_s?` `sla_p99_ms?` `sla_met?`（未填 SLA 则 **不出现** `sla_met`）`knee?` `est_cost_usd`。

#### `POST /api/reports/{id}/share`

```json
{ "url": "https://.../reports/{id}?share=token", "expires_at": "..." }
```

有效期 7 天。

#### `POST /api/reports/{id}/baseline`

仅 admin。

```json
{ "frozen": true }
```

Benchmark：同 dataset 版本 + 主指标才能对比。  
RAG：同 kb + gold 版本。  
解冻 `{ "frozen": false }` 写审计。

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

仅 admin。部分更新。白名单 / 单价 / 角色相关变更写审计。

#### `GET /api/admin/audit-logs?from=&to=&offset=&limit=`

仅 admin。无前端页面。item：`at, actor_id, action, target, detail`（无 Key）。  
action 至少：`login_failed` `role_change` `key_change` `baseline_freeze` `baseline_unfreeze` `whitelist_change` `prod_approve` `prod_stress`。

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
