# AI 测试与评估平台 — 后端开发计划

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.5 |
| 对应 PRD | V1.10（功能唯一权威） |
| 对应设计规范 | V1.2（仅约束对外字段 / 错误码 / 事件名，不约束像素） |
| 对应总计划 | V1.0（日历与门禁） |
| 对应前端计划 | V1.5（契约消费者） |
| 对应 API | V1.18（路径/JSON 唯一冻结） |
| 撰写日期 | 2026-08-17 |
| 最近修订 | 2026-08-23：M1 Agent 基线切换为 LangGraph 单轮图与 WebSocket 异步桥接；Harness、MCP、确认卡和长任务暂冻结；M2 提前启动（评测域建表、benchmark 真实执行器、样本明细接口） |
| 计划起点 | 2026-08-18 |
| V1.0 目标发布 | 2026-12-04 |
| 总工期 | **16 周**（与总计划同一日历） |
| 主责角色 | Python 后端 × 1；Go/Infra × 1（压测容器与 Compose） |

---

## 1. 编制说明

本文把总计划里的「Python」与「Go/Infra」列拆成服务边界、表、REST/WS/MCP、worker 与周任务。  
**不改范围**：做不做、状态机、确认卡 JSON、MCP 工具名、错误码只认 PRD。日历与门禁认总计划。

冲突裁决：PRD > 总计划 / 本文。若本文与 PRD 冲突，改本文。

若只有 2 人（后端兼 Go）：按总计划改为 20 周，不在本文内偷偷砍 M3/M4 范围。

### 1.4 Agent 首期实现边界（V1.5）

当前后端唯一 Agent 链路为：

```text
WS 短票 -> ws.py -> LangGraphAgent -> ModelGateway -> adapters.py
```

首期 API 进程只实现单轮模型调用、会话消息/事件落库、历史补发、心跳和流式 `thought` 投影。`app/agent/` 不恢复旧 ReAct/Harness；`app/harness/`、MCP、确认卡、任务控制和记忆层保持空边界。后续长任务仍只能由 PostgreSQL 队列和 Worker 承载。

### 1.3 V1.3 权限口径校正

PRD 2.1 冻结为单一 `member`、全员同权。本文不实现 RBAC、`admin`、`engineer`、`readonly` 或角色变更；保留 `/api/admin/*` 仅为历史路径命名，不代表角色鉴权。任务取消限创建者；`prod` 会签由非创建者正常成员完成；所有敏感修改写审计。

### 1.1 范围

| 做（V1.0 后端） | 不做 |
| --- | --- |
| FastAPI REST + WS Agent Host；LangGraph Agent + ModelGateway；PG + worker（后续长任务） | 外部 MCP 连接；改系统提示词接口 |
| 三协议适配器；规则评分；用例 Skill（自研对齐，不拷源码） | HumanEval 沙箱；被测走 WS；内置公开集 |
| LightRAG 原生 `query` 适配 + 外部 OpenAI Chat RAG | 把 LightRAG 伪装成 Chat Completions |
| 先评后压：worker 下发 **stress 容器**（go-stress-testing 扩展） | api 进程内 Python 压测替代；分布式压测；评测与压测并行 |
| Compose 六件套、本地账号、Fernet Key、预算 | Open API（F-CM-08 / V1.1）；多租户 |
| 通知：企微 / 邮件 / 出站 Webhook（M4） | 报告审批流；TMS 同步 |

### 1.2 服务边界（PRD 3.1 / 6.3）

```
浏览器
  /agent  ──WS── api（WS Bridge）
                    │
                    ▼
              LangGraph Agent
                    │
                    ▼
              ModelGateway -> 三协议适配器

  其它页 ──REST─┐
                └── PostgreSQL（sessions / messages / ws_events / tasks）
                                      │
                                      ▼
              worker（后续长任务：评测 / RAG / 用例；压测只下发）
                 │         │              │
                 ▼         ▼              ▼
           三协议适配   lightrag       stress（go-stress-testing）
                         /外部 Chat        /metrics → Prometheus
```

| 进程 | 可以 | 不可以 |
| --- | --- | --- |
| **api** | 鉴权、CRUD、WS 会话、LangGraph 单轮回合、写消息/事件 | 自己跑完 Benchmark/RAG/压测；首期不执行 MCP；长期 JWT 进 WS query |
| **worker** | 调长 MCP；按样本续跑；质量 succeeded 且 `with_stress` 时入队压测子任务；向 stress 下发 | 向用户闲聊；自己打满压测连接 |
| **stress** | 发压、暴露 `/metrics`、收到取消立即停发 | 读用户 Cookie；改质量报告 |
| **lightrag** | 索引 + 原生 query | 被当成 OpenAI Chat 网关 |

一任务一种 `kind`：`benchmark` / `rag` / `testcase` / `stress`。压测用 `with_stress` 派生，`parent_task_id` 指向质量任务。

---

## 2. 技术栈与仓库

| 项 | 选型 | 来源 |
| --- | --- | --- |
| API | Python 3.12、FastAPI、Uvicorn | 总计划开工待办 |
| DB | PostgreSQL 16、Alembic | PRD 6.1 / 6.4 |
| 队列 | PG `tasks` 表 + worker 轮询 | PRD 1.6、3.1 |
| Key | Fernet，密钥来自环境变量 | PRD 8 |
| Agent | 平台配置指定 **一个** 协议档；上下文最近 20 条，系统提示词始终保留 | F-AGT-05/06 |
| RAG | LightRAG 锁 Git tag；外部仅 `POST {base}/v1/chat/completions` | F-RAG-01/02 |
| 压测 | go-stress-testing 扩展，独立容器，保留 NOTICE（Apache-2.0） | F-ST、6.5 |
| 部署 | Compose：`web` `api` `worker` `postgres` `lightrag` `stress` | PRD 1.3 |

建议目录（总计划 M0-1）：

```
backend/
├── api/       FastAPI、WS Bridge、LangGraph Agent、REST
├── worker/    长任务执行器
├── lightrag/  LightRAG 适配（M3 接入真实内核）
└── stress/    go-stress-testing 扩展（Go/Infra）
deploy/        compose、env 样例、Grafana dashboard JSON
```

接口前缀统一 `/api`。健康检查 `GET /api/health`（总计划 M0，5.9 未列但必须有）。

---

## 3. 数据模型（PRD 6.4，M0–M1 建表，后续只加列不拆库）

| 表 | 用途 | 最早写入 |
| --- | --- | --- |
| `users` | 本地账号、停用、首次改密标记 | M1 W2 |
| `sessions` `messages` | Agent 会话与历史 | M1 W5 |
| `ws_events` | 事件持久化，按 `event_id` 补发 | M1 W5 |
| `protocol_profiles` | 三协议档；Key 密文 | M1 W3 |
| `settings` | Agent 后端、并发、预算默认、白名单、单价、通知开关 | M1 W3 起，M4 补齐 |
| `files` | 路径 + sha256；磁盘 `./data/files/{id}` | M1 W2 |
| `dataset_folders` `datasets` `dataset_rows` | 目录、集版本、列定义、行、待补全标记 | M2 W6 |
| `case_folders` `case_sets` `cases` `case_maps` | 目录、用例列定义、生成、映射、`source_case_id` | M2 W8 |
| `kbs` `kb_docs` `gold_qa` | 知识库、文档、黄金 QA 版本 | M3 |
| `tasks` `task_events` | 状态机、进度、取消 | M1 W4 |
| `eval_items` | 样本级结果 / 错误 | M2 |
| `baselines` | 冻结的 succeeded 报告 | M2 / M3 |
| `reports` `share_links` | 报告与 7 天分享 | M2 |
| `audit_logs` | 登录失败、Key、基线、白名单、prod、账号状态 | M1 W2 |
| `usage_ledger` | token 费用累计 | M2 W7 |

不新增产品表去支撑未进入 V1.0 的能力；原型中目录、列定义、日志与摘要等已展示区域除外，必须按本表持久化。

---

## 4. 对外契约

### 4.1 REST（PRD 5.9 + 正文已有、须写入 OpenAPI 的补全）

均需登录，除非注明。错误体含 `code`（PRD 5.5 枚举）。

| 方法 | 路径 | PRD | 阶段 |
| --- | --- | --- | --- |
| GET | `/api/health` | 总计划 M0 | M0 |
| POST | `/api/auth/login` `/api/auth/logout` | 5.9 | M1 |
| POST | `/api/auth/change-password` | 2.1 补全 | M1 |
| GET | `/api/auth/me` | 2.1 补全 | M1 |
| POST | `/api/auth/ws-ticket` | F-AGT-01 | M1 |
| GET | `/ws/agent?ticket=` | F-AGT-01 | M1 |
| GET/POST | `/api/sessions`；GET `/api/sessions/{id}/messages` | 6.4；**方案 A 已冻结** | M1 |
| GET/POST | `/api/users`；PUT `/api/users/{id}`、`/status`；GET `/api/users/activity-summary`；POST `/api/users/{id}/reset-password` | F-CM-03 | M1 |
| GET/POST | `/api/files`；GET `/api/files/{id}` | F-CM-07 | M1 |
| CRUD | `/api/profiles`；POST `/api/profiles/{id}/check` | F-BM-01 | M1 |
| CRUD | `/api/datasets`；POST `/{id}/upload`；GET `/{id}/rows` | F-BM-03/04 | M2 |
| GET | `/api/case-sets` `/{id}`；POST `/{id}/confirm` `/{id}/map`；GET `/{id}/export` | 5.4 | M2/M3 |
| CRUD | `/api/kb`；POST `/{id}/documents`；DELETE `/{id}/documents/{doc_id}` | F-RAG-01 | M3 |
| CRUD | `/api/kb/{id}/gold-qa` | F-RAG-03 | M3 |
| POST GET | `/api/tasks`；GET `/{id}`；POST `/{id}/cancel` `/{id}/rerun` | F-AGT-07/09、F-CM-01 | M1/M2 |
| POST | `/api/tasks/{id}/approve-stress` | F-ST-05 补全 | M4 |
| GET | `/api/tasks/{id}/stress-series` | F-ST-03 补全 | M4 |
| GET | `/api/reports/{id}`；POST `/{id}/share` `/{id}/baseline` | F-CM-02 / F-BM-07 | M2 |
| GET/PUT | `/api/admin/settings` | 5.9 | M1/M4 |
| GET | `/api/admin/audit-logs` | F-CM-04 补全 | M1 |

路径、JSON、错误体以 **`AI测试与评估平台-API.md` V1.3** 为准。会话不再二选一。

**审计打点（F-CM-04，必须写库，不必做独立页）：** 登录失败、Key 变更、基线冻结/解冻、白名单变更、`prod` 会签/发压、成员账号状态变更。

禁止：长期 JWT 进 WS query；GET 回显 Key；公网暴露 stress `/metrics`。  
**不把** 压测时序塞进 WS `progress`（PRD 字段仅 `percent?`/`done`/`total`/`message`）。

### 4.2 WebSocket 事件（PRD 5.1.3）

公共头：`event`, `session_id`, `task_id?`, `event_id`（单调）, `ts`。

服务 → 客户端：`thought` `tool_call` `tool_result` `confirm` `progress` `report` `error` `pong`。  
客户端 → 服务：`user_message` `{text, attachments[]?}`，`confirm_ack` `{ok, patch?}`，`cancel_task` `{task_id}`。

**当前首期实现**：服务端已启用 `user_message`、`thought`、`assistant_delta`、`assistant_message`、
`response.completed`、`error`、`pong`；`thought` 支持 `stream=think|think_final`。`tool_call`、`tool_result`、`confirm`、`progress`、`report`
以及 `confirm_ack` / `cancel_task` 保留为后续 Harness/Worker 阶段，当前统一返回
`VALIDATION` 能力未启用，不生成伪造任务或报告。

- `confirm` 的 payload = 确认卡 JSON（5.1.2）。未 `confirm_ack.ok=true` **不得** `INSERT` queued。  
- 心跳 30s；重连用 `session_id` + `last_event_id` 从 `ws_events` 补发。  
- 附件：先 REST 得 `file_id`，再引用。单文件 ≤20MB；类型白名单同 PRD 5.1.3。

### 4.3 内部 MCP（PRD 5.5）

Agent 只调短工具并 `task.create`。长任务由 worker 调同一套工具。

| 工具 | 类型 | 阶段 | 说明 |
| --- | --- | --- | --- |
| `model.list` | 短 | M1 | 无 Key |
| `dataset.list` | 短 | M2（M1 可空列表） | id/版本/行数 |
| `kb.list` | 短 | M3 | id/文档数 |
| `task.get` `task.cancel` | 短 | M1 | 取消权限 2.1 |
| `report.get` | 短 | M2 | 摘要 + 下载路径 |
| `task.create` | 短 | M1 | 入参=确认卡 JSON |
| `testcase.generate` | 长 | M2 | 5 分钟超时 |
| `testcase.confirm` | 短 | M2 | awaiting → succeeded；worker 不续跑 |
| `benchmark.run` | 长 | M2（M1 mock） | 真调用 |
| `rag.evaluate` | 长 | M3 | LightRAG query 或外部 Chat |
| `stress.run` | 长 | M4 | worker **下发** stress，不在 worker 内打连接 |

错误码：`UNAUTHORIZED` `VALIDATION` `NOT_FOUND` `BUDGET_EXCEEDED` `CONCURRENCY` `WHITELIST` `NEED_APPROVAL` `UPSTREAM` `TIMEOUT` `INTERNAL`。

MCP JSON Schema 总计划允许「开会时出」： **M1 W4 周五前冻结短工具 schema；M2 W6 前冻结长工具评测段；M3 W10 前冻结 RAG 段；M4 W13 前冻结 stress 段。**

### 4.4 任务状态机（PRD 3.3）

```
queued → running → succeeded | failed | cancelled
                 → awaiting_case_confirm → succeeded | cancelled（拒绝或 72h）
```

| 规则 | 实现要点 |
| --- | --- |
| 取消权限 | 仅任务创建者；评测=当前样本结束后停；**压测=立即停发** |
| 用例 | 确认入库才 succeeded；worker 不再续跑同一任务 |
| 先评后压 | 父任务非 succeeded 不得创建 `kind=stress` 子任务 |
| `prod` | 未会签：质量报告保留，压测保持 queued，通知（M4） |
| 并发 | 会话内同时最多 1 个非终态（**含压测子任务**）；平台 `max_running_tasks` 默认 3，超限保持 queued；`max_inflight_model_calls` 默认 8 |
| 重跑 | `POST .../rerun` = 新任务拷配置，不复活旧行 |

---

## 5. 分周计划

Python 与 Go/Infra 分列。前端 mock 不挡后端单测。

---

### M0  工程启动（W1，08-18 ~ 08-24）

**目标**：`docker compose up` 起 api + worker 占位 + postgres；`GET /api/health`。

| 编号 | 角色 | 工作项 | 完成标准 |
| --- | --- | --- | --- |
| BE-M0-1 | Python | FastAPI 骨架、错误码枚举、CORS/Cookie 约定 | 前缀 `/api` |
| BE-M0-2 | Python | Alembic + PG；空 migration | 能连库 |
| BE-M0-3 | Python | CI：lint + pytest 空跑 | PR 必过 |
| BE-M0-4 | Go/Infra | Compose：`web` `api` `worker` `postgres`；`lightrag`/`stress` sleep 占位 | 热重载；卷 `./data/files` |
| BE-M0-5 | 全员 | 冻结版本：Python 3.12、PG 16、LightRAG tag、go-stress-testing tag | README 一条命令 |

**M0 出口**：三人能独立拉起；接口前缀统一。

---

### M1  底座 + Agent（W2–W5，08-25 ~ 09-21）

对应：F-AGT-01/02/03/04/05/06/09，F-BM-01/02，F-CM-01/03/04/07。  
**不跑真评测**：长任务 mock `succeeded` 并写 `task_events`，入口与 M2 相同。

#### W2  账号、权限、文件、审计（Python）

| 工作项 | 完成标准 |
| --- | --- |
| 环境变量创建首位成员；登录后必须改密 | `users.must_change_password`；密码 ≥8 位含字母和数字 |
| HttpOnly Cookie 12h 可续 | 前端不拿长期 JWT |
| 单一 `member` 鉴权、资源创建者校验 | 未登录 `UNAUTHORIZED`；非创建者取消任务返回 `UNAUTHORIZED` |
| 用户 CRUD、停用、重置密码 | 账号状态变更写审计；不提供改角色字段 |
| 文件：`./data/files/{id}` + sha256；≤20MB；类型白名单 | 路径存 PG |
| `audit_logs`：登录失败、账号状态变更 | `GET /api/admin/audit-logs` 可按时间查（无独立页） |

#### W3  协议档 + 三协议适配器（Python）

| 工作项 | 完成标准 |
| --- | --- |
| `protocol_profiles` CRUD；Key Fernet；GET 不回显 | 变更写审计；用途字段：被测 / Agent 后端 / 裁判 |
| 适配器：`openai_chat` / `openai_responses` / `anthropic_messages` | 入 `messages`，出 `text,usage,raw,latency_ms`；鉴权头按 PRD 6.2 |
| 每种协议 ≥2 夹具单测（成功 + 4xx） | CI 必过；`UPSTREAM` 可区分 |
| `POST /api/profiles/{id}/check` | 超时/4xx 可测；响应与日志均无 Key |
| `settings`：指定 Agent 后端协议档 | 平台仅一个；全员可见，敏感字段不回显 |

**Go/Infra**：保持占位容器健康检查；不挡 W3。

**降级**：W5 不依赖真实厂商账号，可用 mock HTTP server。某协议延期不影响另两个进 M2。

#### W4  任务状态机 + worker + 短 MCP（Python）

> 当前状态：任务状态机与 Worker 属于后续长任务阶段；首期 Agent 不调用 MCP、不创建任务。

| 工作项 | 完成标准 |
| --- | --- |
| 表 `tasks` `task_events`；状态机 3.3 | 取消权限 2.1 |
| worker 轮询 PG；会话内串行；`max_running_tasks=3` | 超限保持 queued |
| `POST /api/tasks/{id}/rerun` | 新任务拷配置，不复活旧行（F-AGT-09） |
| 短 MCP：`model.list` `task.get` `task.create` `task.cancel` | Agent 不执行长任务 |
| 长任务 mock 成功写事件 | 同一 `benchmark.run` 入口，M2 替换真执行 |
| `GET /api/tasks` 筛状态 / kind | F-CM-01 |
| 冻结短工具 JSON Schema；实现 `/api/sessions`（API 方案 A） | 以 API V1.3 为准 |

#### W5  WebSocket Agent + 确认卡（M1 门禁周）

> 当前状态：WS 短票、会话回放、后台单轮 LangGraph 调用、心跳和流式事件已交付；确认卡、短 MCP、任务下单和 Worker 事件等待 Harness/任务阶段重新评审。

| 工作项 | 完成标准 |
| --- | --- |
| `POST /api/auth/ws-ticket`（5 分钟）+ WS 升级 | **不用**长期 JWT 进 query |
| 心跳 30s；`ws_events` 持久化；重连补发 | 断线任务不丢（worker 继续） |
| 事件集与 5.1.3 一致 | 禁止旧 SSE 事件名 |
| 确认卡字段校验；未确认不入队 | `VALIDATION` 回卡 |
| 人设：固定系统提示词；先澄清再下单；不执行任意代码 | 无「改提示词」API |
| 上下文最近 20 条，超长丢最旧用户/助手消息 | 系统提示词始终保留 |
| 平台并发满时仍可 queued | `CONCURRENCY` 可提示但任务可排队（与 3.4 一致：超限保持 queued） |

**Go/Infra**：Compose 四核心稳定。

**M1 演示脚本**：同总计划（协议档 → 对话下单 mock → 断线续 → 任务日志）。

**M1 后端出口**

- [x] Cookie + 单一成员鉴权 + 文件 + 审计
- [x] 协议档 + 适配器单测
- [x] WS 短票、心跳、补发
- [x] 确认卡未确认不入队
- [x] 仅任务创建者可取消自己的任务，非创建者负例可测
- [x] 长任务 mock 与真执行同一入口（benchmark 已切真实执行器，rag/testcase/stress 仍走同一入口的 mock）

---

### M2  Benchmark + 用例 + 表单（W6–W9，09-22 ~ 10-19）

对应：F-AGT-07，F-BM-03～07，F-CM-02/06，5.4.1～5.4.2。  
本阶段达成成功指标「Agent 闭环」。

#### W6  数据集与真调用（Python）

| 工作项 | 完成标准 |
| --- | --- |
| JSONL/CSV UTF-8；列 `question,reference,context?` | ≤50MB、≤2 万行；覆盖上传版本 +1 |
| 每集一种主指标入库，默认 contain | F-BM-05 配置侧；评分算法在 W7 |
| `benchmark.run`：抽样 / 并发 / 超时 / 重试（5.2.2） | 失败样本记 `eval_items.error`，不中断整次；受 `max_inflight_model_calls` 默认 8 限制 |
| 非流式调用被测；raw ≤32KB | `UPSTREAM` |
| 按样本行号续跑；评测取消=当前样本结束后停 | worker 重启不丢进度 |

**Go/Infra**：开始 fork go-stress-testing，本周只打通本地 HTTP 压测骨架，**不接父任务**（总计划：最早 M2 开工，M4 才接）。

#### W7  规则评分、多模型、报告、预算（Python）

| 工作项 | 完成标准 |
| --- | --- |
| 主指标：exact / contain / regex / rouge_l / bleu，默认 contain | 每集一种 |
| 1–5 个 profile 并排报告；任务快照含配置 | F-BM-06 |
| Markdown 导出（`GET /api/reports/{id}?fmt=md` 或等价）；`share_links` 7 天 | 未过期可未登录 GET |
| `usage_ledger`；单任务 `max_usd` 默认 5（settings 可改，管理页 M4 才做） | 超限停，`BUDGET_EXCEEDED` |
| `POST /api/reports/{id}/baseline` 冻结；同 dataset 版本 + 主指标才能对比 | 解冻写审计 |

#### W8  用例生成 Skill + 映射（Python）

| 工作项 | 完成标准 |
| --- | --- |
| 输入 P0：PRD 文本、OpenAPI JSON/YAML、Excel | **不做** Postman/MD |
| 六策略 + P0–P3；对齐附录 A；不引入 testcase-tools 源码 | 超上限停，禁止灌水 |
| 5 分钟超时 → failed；自检结果写入 case_set | 无核心正向、缺约束反向 |
| 状态 `awaiting_case_confirm`；确认入库或 72h 扫描取消 | REST `POST .../confirm` 与 MCP `testcase.confirm` 同一实现；确认后 succeeded，worker 不续跑 |
| 映射 Benchmark：缺字段待补全，不进分母 | `source_case_id` + 用例版本；**黄金 QA 映射放到 M3 W11** |
| 导出 xlsx / xmind（Excel 8+） | 5.4.1 |

#### W9  表单双入口 + 会话槽位（Python）

| 工作项 | 完成标准 |
| --- | --- |
| `POST /api/tasks` 校验与确认卡 JSON 一致 | F-AGT-07 |
| 会话槽位：queued/running/awaiting 含「后续子任务」占位——本周实现 **父任务侧** 同时最多 1 个非终态 | 3.4；子任务占槽在 M4 闭环 |
| `dataset.list` / `report.get` 短工具可用 | Agent 可列集、读报告 |

**M2 演示**：两协议档 + ≥20 条 JSONL，对话出 contain 对比；断线仍有进度；缺 question 不进分母。

**M2 后端出口**

- [x] ≤1k 样本、被测稳定时报告页能看到结果（真实执行器就绪：批内并发 + 断点续跑；性能实测随 M2 演示验收）
- [x] 用例采纳率字段：确认入库条数 / 生成条数（`case_sets.confirmed_count` / `generated_count`）
- [x] 预算超限必停（`usage_ledger` 逐调用累计，超 `default_max_usd` 置 failed + `BUDGET_EXCEEDED`）
- [x] 基线规则生效（同数据集版本 + 主指标匹配基准，`baseline_id` / `baseline_scores` / `degraded` ≥5pp 判定已接通）
- [x] 72h 超时任务已做（Worker 主循环 60s 节流扫描，任务与用例集双取消 + WS 通知）

---

### M3  RAG（W10–W12，10-20 ~ 11-09）

对应：F-RAG-01～06，F-BM-08。通知仍不在本阶段。

#### W10  内置 LightRAG（Python + Infra）

| 角色 | 工作项 | 完成标准 |
| --- | --- | --- |
| Go/Infra | Compose 正式接入 LightRAG，锁 tag；索引卷；内网 DNS | MIT；镜像可复现 |
| Python | 上传文档建索引；`doc_id`=UUID 写入 metadata | `/api/kb`；成员可标核心、删文档，敏感修改写审计 |
| Python | 查询原生 `query` API，适配 `{text, contexts[{id,text}]}` | **不**伪装 OpenAI Chat |
| Python | 模式 naive/local/global/hybrid，一任务 1–4，默认 hybrid | 确认卡字段生效 |

#### W11  黄金 QA、指标、外部 RAG（Python）

| 工作项 | 完成标准 |
| --- | --- |
| 黄金 QA：`question,reference,expected_doc_ids[]?`；≤1 万条；版本 +1 | 覆盖上传 |
| 用例映射黄金 QA：问句→question，预期→reference；doc_ids 手补；无 id 仅答案侧 | PRD 5.4.2 |
| Hit Rate@K / MRR / Recall@K；K 默认 5、可配 1–20 | 无 id 样本不进 Hit 分母；字段名 **`run.k`**（API V1.3 已冻结） |
| 答案侧 contain；命中=返回 id 集合与 expected 相交 | 5.3.1 |
| 外部 RAG：仅 Chat Completions；content + 可选 context/contexts[] | F-RAG-02 |
| 同 kb + gold 版本对比；退化 ≥5pp 报告标红 | **不发通知** |

#### W12  Judge + RAG 基线（Python）

| 工作项 | 完成标准 |
| --- | --- |
| LLM-as-Judge：1–5 + 理由；裁判档 ≠ 被测时警告、不强制 | 只对已有输出打分，不重跑；**不新增确认卡必填列**；`run.use_judge` 默认 false（API V1.3） |
| RAG 基线冻结，权限同 Benchmark | `POST /api/reports/{id}/baseline` |
| `kb.list` 短工具 | Agent 可列库 |
| Grafana dashboard JSON 草稿；与监控对齐网段 | 总计划可并行项；指标名 M4 才暴露 |

**M3 演示**：hybrid Hit Rate@5；外部 Chat（可 mock）答案 contain。

**M3 后端出口**

- [ ] 两套路径答案侧口径一致  
- [ ] 检索侧无 id 不污染 Hit Rate  
- [ ] Judge 不重跑评测  

---

### M4  共享压测 + 解读 + 通知（W13–W15，11-10 ~ 11-30）

对应：F-ST-01～07，F-AGT-08，F-CM-05。  
内核必须是 go-stress-testing 扩展；worker 只下发。

#### W13  压测内核与继承目标

| 角色 | 工作项 | 完成标准 |
| --- | --- | --- |
| Go/Infra | 扩展 go-stress-testing；保留 NOTICE；独立容器 | api 内不用 Python 替代 |
| Python | 父任务非 succeeded 不创建子任务 | 先评后压 100% |
| Python | Benchmark / 外部 RAG：继承 URL/Header/协议；body 最多 50 条 question 轮询 | F-ST-01 |
| Python | 内置 LightRAG：压内网 `query` HTTP，按父任务 `rag_mode` 组装 | 不是 Chat Completions |
| Go | 模型指标：QPS、RT、错误率、TTFT、TPOT、tokens/s（SSE） | RAG 非流式可不记 TTFT |
| Go | 取消 = **立即停发** | 与评测协作式取消区分 |
| Python | 会话槽位含子任务：父 succeeded 后子任务占槽 | V1.6.3 |
| Python | `GET /api/tasks/{id}/stress-series` 供前端 Chart.js | 与 Grafana 同 `task_id`；不改 WS `progress` schema |

#### W14  安全、监控、SLA、费用

| 角色 | 工作项 | 完成标准 |
| --- | --- | --- |
| Python | env 必填；host 白名单；默认 QPS≤500、时长≤30min | 无白名单无法 running → `WHITELIST` |
| Python | 错误率 60s≥50% 自动停；`prod` 会签 `POST /api/tasks/{id}/approve-stress`；未会签保持 queued | `NEED_APPROVAL`；质量报告仍保留；会签写审计 |
| Go | `/metrics` 内网；Basic 或 IP 白名单；前缀 `ai_eval_stress_` | label `env,model,task_id`；结束后 10min 停该 task 序列 |
| Infra | 对齐现网 `job=ai-eval-stress` | Grafana 能按 task_id 查 |
| Python | 未填 `sla_p99_ms` 不出达标；填了则拐点=首次 P99>SLA 或错误率≥1% | F-ST-06 |
| Python | 父任务 usage × 单价估算窗口费用 | 成员配置 /1k tokens，写审计 |
| Python | `PUT /api/admin/settings`：白名单、单价、并发、预算默认 | 全员同权；白名单/单价变更写审计 |

W13 先冻结指标名；Grafana dashboard JSON 可在 W12–W14 微调。

#### W15  解读、通知、M4 门禁

| 工作项 | 完成标准 |
| --- | --- |
| 解读 Skill：仅已有 `report_id`，不重跑评测 | F-AGT-08 |
| 通知：终态、退化、会签；企微 / 邮件 / 出站 Webhook；成员开关默认关 | F-CM-05 |
| 向 api 提供压测时序（供前端 Chart.js 与 Grafana 同 task_id） | F-ST-03 |
| 进度事件持续推送 | Agent ProgressDock |

**M4 演示**：test 白名单压 2 分钟；平台与 Grafana 同 task_id；无白名单不能 running；取消立即停。

**M4 后端出口**

- [ ] 勾选压测的任务 100% 先出质量结果  
- [ ] Grafana 100% `job=ai-eval-stress`  
- [ ] `prod` 未会签不得 running  

---

### H  硬化与 V1.0 发布（W16，12-01 ~ 12-04）

不加功能。

| 角色 | 工作项 | 完成标准 |
| --- | --- | --- |
| Python | 性能：≤1k 样本、被测 ≥5 QPS → 规则评测 ≤30min | 内网 mock 或稳定测试档 |
| Python | 中等 PRD 用例生成 ≤5min | PRD 第 8 节 |
| Python | Key 不落日志；断点续跑复查 | 安全走查 |
| Infra | `/metrics` 不暴露公网；PG dump + files 卷说明 | 一页运维文档 |
| Infra | 打 `v1.0.0` tag；Compose 锁镜像 tag | 可回滚 |

---

## 6. 后端「完成」定义（DoD）

1. 有 PRD 编号，行为与文档一致。  
2. 单测或夹具；涉及协议必须含成功 + 4xx。  
3. 权限至少测过未登录、已登录成员、任务创建者与非创建者。
4. 须打点的审计已写：Key、基线、白名单、prod、账号状态、登录失败。
5. 不把 P1/后续项塞进当前里程碑冒充完成。  
6. 长任务不在 WS 进程里跑完。

---

## 7. 测试分层（后端）

| 层 | 谁写 | 覆盖 | 最早 |
| --- | --- | --- | --- |
| 适配器夹具 | Python | 三协议成功 + 4xx | M1 W3 |
| 状态机单测 | Python | 取消、72h、先评后压、会签、会话槽位含子任务 | M1 W4；M2 W8；M4 W13 |
| API 集成 | Python | 登录、任务、预算、分享未登录 | M1–M2 |
| MCP 契约 | Python | 短工具无 Key；未确认不 create | M1 W5 |
| 压测契约 | Go | `/metrics` 名、立即停止、label | M4 W13–W14 |
| 里程碑手工脚本 | 全员 | PRD 第 7 节门禁 | 每里程碑周五 |

---

## 8. 关键路径与可并行

最长链（与总计划相同，后端视角）：

```
账号/协议档 → WS LangGraph Agent → Harness/确认卡 → worker 状态机
  → 三协议真调用 + 规则评分（M2 门禁）
  → 质量 succeeded 才能派生子任务
  → stress 继承父任务 endpoint（M4 门禁）
```

| 可并行 | 最早 | 说明 |
| --- | --- | --- |
| 协议适配器夹具 | M0 末 | 不依赖 UI |
| LightRAG 锁 tag + Compose 草稿 | M2 | M3 才接评测 |
| go-stress-testing 骨架 | M2 | M4 才接父任务 |
| Grafana JSON 草稿 | M3 | `/metrics` 契约冻结后微调 |
| 通知渠道 | M4 前半 | 不挡压测内核 |

---

## 9. 风险（后端落地）

| 风险 | 爆点 | 预留 | 触发与降级 |
| --- | --- | --- | --- |
| 三协议字段差 | M1 W3–W4 | 夹具先行；W5 用 mock server | 某协议延期不影响另两个进 M2 |
| 并行打爆上游 | M2 | 默认并发 4 / inflight 8 / 预算 5 USD | 先降并发 |
| 映射大量待补全 | M2 W8 | 允许手传 JSONL | 映射不挡 Benchmark 门禁 |
| LightRAG 升级不兼容 | M3 W10 | 锁 tag；评测只适配 query | 与框架解耦 |
| Prometheus 抓不到 | M4 W14 | W13 冻指标名；W12 对网段 | 平台曲线仍可验收 |
| 压测误伤 | M4 | 白名单 + 上限 + 熔断；W14 测负例 | 无白名单不能 running |
| 用例确认悬挂 | M2 | W8 做 72h 扫描 | 定时任务 |

**进度红线**：门禁未过，下一阶段只修门禁项（例如 M2 没出对比报告就不开 LightRAG 接入）。

---

## 10. 明确不排进本周期的后端工作

- F-CM-08 Open API 对外鉴权与稳定契约发布  
- F-RAG-07 过程可视化事件  
- 用例输入：Postman、Markdown 接口解析  
- 外部 MCP Host、用户自定义系统提示词  
- 多租户、多模态、分布式压测、HumanEval  
- 在 api 内用 Python 实现压测内核  

V1.1 不占本周期人力，除非 V1.0 门禁已全绿且产品改 PRD。

---

## 11. 开工当天（08-18）后端待办

1. 建仓结构 `frontend/` 与 `backend/{api,worker,lightrag,stress}` + `deploy/`；分支保护 main + `m1`/`m2`/`m3`/`m4`。  
2. 冻结 Python 3.12、PG 16、LightRAG tag、go-stress-testing tag。  
3. 向监控同学发指标前缀 `ai_eval_stress_` 与 `job=ai-eval-stress`（M4 才接，网段早约）。  
4. 准备至少两套测试协议档（兼容 OpenAI 的本地 mock）。  
5. 错误码枚举落地，与前端共享名单。  
6. 周五只验收健康检查与 Compose。

本文与 PRD 冲突时 **以 PRD V1.6.3 为准**；改计划不改范围。

---

## 附录 A  对照检查记录（V1.3）

检查对象：PRD V1.6.3、设计规范 V1.2、总计划 V1.0、前端计划 V1.3、本文。

### A.1 功能编号

| 编号 | 后端落点 | 结论 |
| --- | --- | --- |
| F-AGT-01～06、09 | M1 WS / MCP Host / 确认校验 / rerun | 覆盖 |
| F-AGT-07 | M2 `POST /api/tasks` 同 schema | 覆盖 |
| F-AGT-08 | M4 解读 Skill | 覆盖 |
| F-BM-01/02 | M1 协议档 + 适配器夹具 | 覆盖 |
| F-BM-03～07 | M2 数据集/评分/多模型/基线 | 覆盖 |
| F-BM-08 | M3 Judge | 覆盖；不扩确认卡必填列 |
| F-BM-09 | 不做 | 未排 |
| F-RAG-01～06 | M3 query 适配 / 外部 Chat / 黄金 QA / 指标 / 模式 / 基线 | 覆盖 |
| F-RAG-07 | 后续 | 未排 |
| F-ST-01～07 | M4 worker 下发 + stress 容器 | 覆盖；内核非 Python |
| F-CM-01/03/04/07 | M1 | 覆盖（审计有 API 无独立页） |
| F-CM-02/06 | M2 | 覆盖 |
| F-CM-05 | M4 通知 | 覆盖 |
| F-CM-08 | V1.1 | 未排 |

### A.2 表 / MCP / 事件

PRD 6.4 全部表在 §3。PRD 5.5 全部工具在 §4.3（含阶段）。PRD 5.1.3 事件名在 §4.2，禁止扩展 `progress` 字段塞曲线。

### A.3 检查中发现并已修

1. 5.9 摘要不全：改密、连通性、基线、会签、压测时序、审计查询、会话 REST —— 已写入 §4.1。  
2. F-AGT-09 重跑未进 W4 周任务 → 已补。  
3. `max_inflight_model_calls=8` 应在真调用周（W6）生效，不只 M4 管理页。  
4. 黄金 QA 映射从 M2 挪到 M3，避免无 KB 时空做。  
5. Hit@K 的 `k`、`run.use_judge` 不在 PRD 5.1.2 → API V1.3 冻结为可选字段。
6. 知识库标核心、删文档与敏感修改审计补进 W10。
7. 审计打点清单写全（登录失败、Key、基线、白名单、prod、账号状态）。
8. Grafana JSON 草稿按总计划放到 M3 W12。

### A.4 与总计划 / 前端计划

日历、门禁脚本、关键路径、可并行项、红线与总计划一致。  
REST/WS 以 **API V1.3** 为准，与前端计划路径表对齐（含 `GET /api/auth/me`、会话方案 A、check / baseline / approve-stress / stress-series）。

---

## 12. API 缺口收敛与真实联调实施计划（V1.3）

本节以 2026-08-18 的只读代码检查为基线。当前 FastAPI 骨架已有 health、认证、profiles 的部分 CRUD、datasets 的部分 CRUD、tasks 的部分 CRUD、admin settings 和最小 WS；它们不足以满足 API V1.3。以下任务必须按批次完成，不能因原型能够显示 Mock 而跳过。

**2026-08-19 实施状态（V1.4 修订）**：B0–B2 批次（契约底座、身份与配置、会话与任务控制面）与调度域已全部落地并通过 135 项测试；B3 批次的核心链路已提前交付——

| 交付项 | 落点 | 状态 |
| --- | --- | --- |
| 数据集域（目录树/数据行/扩展列/AI 候选） | 迁移 `b3e71a9c42f6` + `routers/datasets.py` | ✅ |
| 用例域（用例集/用例行/目录树/确认/映射） | 迁移 `d4a81c6e93f2` + `routers/cases.py` | ✅ |
| 报告分享与基线冻结 | 迁移 `e5f92b7d31a8` + `routers/reports.py` | ✅ |
| 评测域建表（`eval_items` / `usage_ledger`） | 迁移 `c2f5a9b41d07` | ✅ |
| Benchmark 真实执行器（三协议真调用 + 五种规则评分 + 预算熔断 + 断点续跑 + 批内并发） | `worker/app/benchmark.py` + `worker/app/protocol.py` + `worker/app/scoring.py` | ✅ |
| 样本级逐题比对 `GET /api/reports/{id}/samples`（all/diff/fail 过滤） | `routers/reports.py` | ✅ |
| 评分器口径单测（CI 内按文件路径加载 worker 正本） | `api/tests/test_scoring.py` | ✅ |
| 用例生成 Skill 真实执行器（六策略 LLM 生成 + 规模闸门 20/45/80 + 自检红字 + awaiting_case_confirm 流转） | `worker/app/testcase.py` + `worker/app/casegen.py` | ✅ |
| 72h 用例确认超时扫描器（主循环 60s 节流，联动任务/用例集双取消） | `worker/app/main.py` | ✅ |
| 报告基线 Δ 对比（同数据集版本 + 主指标匹配，`baseline_id`/`baseline_scores`/`degraded`） | `routers/reports.py` | ✅ |

剩余 B3 项：表单双入口联调（W9）、Markdown 导出富化；B4/B5 批次未动工。

### 12.1 所有批次的横向契约要求

| 编号 | 后端要求 | 完成标准 |
| --- | --- | --- |
| BE-API-01 | 所有列表统一 `{items,total}`，支持 `offset/limit`；单资源返回资源对象；204 只用于无 body 的删除 | OpenAPI、集成测试与原型请求结果一致；不再依赖前端数组兼容器 |
| BE-API-02 | 统一错误体 `{code,message,fields?}`，异常处理不泄漏 stack、SQL、Key 或 Cookie | 400/401/403/404/409/502/504 每类有一例集成测试 |
| BE-API-03 | Cookie 名、12h 生命周期、SameSite/Secure、CORS Origin/credentials 固化为配置 | 跨端口 web→api 开发联调成功；浏览器不读长期 token |
| BE-API-04 | Pydantic 请求/响应模型与迁移同时提交；`extra=forbid` 用于 TaskSpec/安全配置 | 不接受浏览器临时字段；字段变更先修改 API.md 与前端类型 |
| BE-API-05 | 写操作使用事务、审计和 resource/version 回读 | 重复点击不产生不可解释重复资源；刷新后数据不丢 |
| BE-API-06 | 真实上游调用、worker、压测隔离；API/WS 进程只负责控制面 | 长任务不依赖浏览器连接，取消语义按 kind 可测 |

### 12.2 接口实现批次与依赖

| 批次 | 周次 | 必须完成的 router/服务 | 依赖 | 联调出口 |
| --- | --- | --- | --- |
| B0 契约底座 | W1 | exception handler、pagination、CORS/Cookie、OpenAPI tag、health | DB/Compose | `GET /health`、错误体、带 Cookie 的跨端口 smoke test |
| B1 身份与配置 | W2–W3 | auth/change-password；users/status/reset/audit/activity-summary；files；profiles get/update/check；settings；mcp tools inventory | users/audit/files/profiles 表、Fernet | 原型 login/profiles/users 页面实时模式可读写且 Key 不回显 |
| B2 会话与任务控制面 | W4–W5 | sessions/messages、task events/summary、dispatch overview/workers/events/config、WS 短票/补发 | tasks/task_events/ws_events/dispatch_events、worker poller | 确认卡提交 queued，刷新/断线后状态与事件一致 |
| B3 Benchmark 与用例 | W6–W9 | dataset folders/detail/upload/rows/AI generate；case folders/case-sets/cases/confirm/map/export；reports/samples/share/baseline | files、目录/列定义、dataset versions、eval items、case sets、usage ledger | 上传→TaskSpec→结果报告完整回读；目录/列/待补全负例可验证 |
| B4 KB/RAG | W10–W12 | KB CRUD、documents、gold QA、query adapter、capabilities、RAG reports | LightRAG service、KB/doc/QA 版本表 | 文档→索引→query→Hit@K/答案报告可追溯；无实验能力时明确返回 false |
| B5 压测和治理 | W13–W15 | stress settings/whitelist/usage、approve-stress、stress-series、notify | stress container、Prometheus、audit | 无白名单/无会签均不能 running；曲线同 `task_id` |

### 12.3 B0–B2 详细拆分（先解除当前原型阻塞）

| 子项 | 实施内容 | 测试/验收 |
| --- | --- | --- |
| 认证收敛 | 对齐 `/auth/login/logout/me/change-password/ws-ticket`；登录失败写审计；改密使旧会话失效策略明确 | cookie flags、错误码、短票过期和禁用用户 WS 连接测试 |
| 用户和审计 | 实现 `/users`、`/{id}`、`/{id}/status`、`/{id}/reset-password`、`/{id}/audit-logs` 和全局审计查询 | 账号停用后 login/me/WS 均拒绝；审计记录不含密文 |
| 协议档 | list/get/create/update/delete/check；API key 仅写入加密列，GET 仅回 `has_api_key` | 三协议校验成功+4xx fixture；日志脱敏扫描 |
| 会话 | `GET/POST /sessions`、messages 只读回放；会话归属校验 | 新建返回服务端 UUID；重连后的 `last_event_id` 不重复 |
| 任务 | TaskSpec schema、list/detail/cancel/rerun/events；排队/运行容量控制 | 创建、过滤、终态重跑、权限、协作式取消；API 不伪造 succeeded |
| 调度 | overview/workers/events/config 只暴露允许字段 | 无 worker/满队列/worker down 三种响应均被原型正确呈现；事件与拓扑同 task/worker ID |

### 12.4 B3–B5 的数据与异步边界

| 域 | 写入的事实数据 | 异步状态 | 不能做的捷径 |
| --- | --- | --- | --- |
| 数据集/用例 | 文件 hash、目录、列定义、dataset/case-set 版本、行/映射、确认时间 | 上传/生成可 `processing`，完成后生成可读版本 | 用原型数组保存编辑结果，或以文件名代替版本 ID |
| 评测/报告 | TaskSpec 快照、eval item、指标、样本错误、share token、baseline | worker 只推进状态/事件；报告终态可读 | 报告由浏览器计算/拼接；任务失败仍生成成功报告 |
| KB/RAG | kb/doc/chunk/golden QA 版本、expected_doc_ids | 索引状态和 query results 可轮询/订阅 | 伪装 LightRAG 为 Chat；无 doc ID 仍计入 Hit 分母 |
| 压测 | 父任务快照、whitelist、approval、time series、usage | stress 子进程启动/停止由 worker 协调 | 在 API 进程压测；从 WS progress 补造曲线 |

### 12.5 后端 API 完成门禁

| 门禁 | 必须通过 |
| --- | --- |
| 接口级 | 每个新增 endpoint 至少有成功、认证失败、校验失败测试；列表契约和错误体有 schema test |
| M1 | 原型 `?data=live` 下登录、协议档、会话、确认卡、任务列表和 WS 可用；断掉 API 时页面报错而不转样例数据 |
| M2 | 数据集行编辑/上传、case confirm、报告/样本/分享/基线均经真实 PG 读回 |
| M3 | LightRAG 和外部 RAG 均以平台 KB/报告接口返回；版本和指标分母可核对 |
| M4 | 白名单、会签、立即停发、series、审计和 Prometheus label 同时验证 |

实现顺序遵循本节，不以当前 router 是否能返回 200 判定完成；必须满足 API V1.3 字段、权限、状态机和持久化语义。

### 12.6 复查后补齐的 API 交付拆分

| 编号 | 批次 | 后端交付 | 契约与测试 |
| --- | --- | --- | --- |
| BE-API-07 | B2 | `POST /files`、`GET /sessions/{id}/messages` 与 WS 历史补发 | 文件返回 UUID；messages 含文本与可选 events；`last_event_id` 重连不漏不重；禁止客户端伪造事件完成态 |
| BE-API-08 | B3 | `POST /datasets/ai-generate` 支持 scene/seed/doc/fill_missing，返回候选 `items[]` | 不写入数据集；采纳后才由 rows PUT 落库；补全时输入/输出行都有 schema 与限额测试 |
| BE-API-09 | B3 | `POST /case-sets/ai-generate` 支持 `source_doc_id` 或 `source_text`，返回候选用例 | 不能隐式创建 case set；`POST case-sets` + `PUT cases` 分别事务化，第二步失败可识别并回滚/清理 |
| BE-API-10 | B4 | `GET /kb/{id}/documents`、`GET /kb/{id}/documents/{doc_id}/chunks` | 文档状态、chunk_size/overlap、chunk ID/text/token 都从 LightRAG/索引版本读取；无数据返回空集合，不下发样本切块 |
| BE-API-11 | B2 | Worker 注册/治理 `POST /dispatch/workers`、`PUT /dispatch/workers/{id}` 与 overview 聚合字段 | 注册、draining、offline、caps/weight 的权限/校验/审计测试；任务分配仅 worker 服务执行，HTTP 页面不改变队列状态 |

本批补齐后，前端实时模式可以把“无响应/无实体”直接呈现为空态或错误态；后端不得用演示数据填充这些响应。

### 12.7 原型逐页还原的后端实施矩阵（V1.3）

前端只有在下表的“事实数据”被服务端持久化、接口可回读、异步所有权明确后，才可以将原型页面标为真实联调。`Web-Prototype/` 中的图、树、卡片和倒计时均不是后端返回示例数据的理由。

| 原型页面 | 后端必须提供的事实数据 / 契约 | 持久化与异步边界 | 批次 / 验收 |
| --- | --- | --- | --- |
| Agent | sessions/messages、`ws_events`、files、固定 Agent WS 事件；会话迷你调度只读使用 dispatch 汇总 | `messages` 与 `ws_events` 按 session 保存；worker 推进 task，WS 只转发/补发 | B2；重连不漏不重，服务端无事件时没有客户端伪造的进度或报告 |
| 调度中心 | overview、workers、queued task 摘要、`GET /dispatch/events?after_id=&limit=`、config | 新增 `dispatch_events`（分配、开始、draining、完成/失败）；仅 worker/调度器写入，不由 HTTP 操作队列 | B2；拓扑、日志与 KPI 使用同一 `task_id`/`worker_id`；空池、离线、满队列可测 |
| 任务中心 | tasks/list/detail/events 与 `GET /tasks/summary?from=&to=`（24h 状态计数、趋势、失败归因摘要） | summary 可由 tasks/task_events 聚合，不保存浏览器统计；诊断仅返回可追溯规则/事件 ID，不冒充生成式结论 | B2；筛选、详情、summary 的总数一致；取消仅创建者可成功 |
| 数据集 | dataset folder CRUD；dataset 的 `folder_id`、`column_schema`、版本；rows 批量写回；候选生成 | `dataset_folders`、`datasets.column_schema JSONB`、`dataset_rows.data JSONB`；AI 候选不写库，采纳后的 rows PUT 在事务中落库并递增版本 | B3；刷新后树、列、编辑值和待补全计数一致；候选未保存前不得出现在 GET rows |
| 用例 | case folder CRUD；case set 的 `folder_id`、`column_schema`、cases、检查项、expires_at、mapping target；候选生成/确认/导出 | `case_folders`、`case_sets.column_schema JSONB`、`cases.data JSONB`；72h 扫描器只改变 case set/task 状态；confirm/map 分别事务化并记录目标版本 | B3；刷新后策略计数与行数一致；超时不可再确认；映射失败不制造半完成结果 |
| 报告 | `GET /reports/{id}` 以 `kind` 返回 Benchmark/RAG/stress 对应段；samples、share、baseline、stress series | report/eval item/usage/baseline 均由 worker 写；图表计算可在服务端聚合，但不在浏览器拼成功报告 | B3–B5；任一段缺失返回空/不可用说明；基线差异可用任务快照复算 |
| KB | KB/documents/chunks/query/gold QA；query 返回 doc/chunk ID、score、mode、metric；metadata capabilities | kb/doc/chunk/QA 均与索引版本关联；LightRAG 索引任务异步更新状态 | B4；文档、切块、召回 ID 可逐项追溯。向量投影和 rerank 实验是 F-RAG-07 后续能力，V1.0 仅返回 `capabilities.projection=false`/`rerank_compare=false` |
| 协议档与运行时 | profiles/check、admin settings、`GET /mcp/tools` 的内置短工具清单 | profiles/settings/audit logs；密钥只写加密列。V1.0 不提供外部 MCP 节点接入或自定义技能/Prompt 写入 | B1；工具清单由服务端配置；原型对应写入口返回明确能力未启用，而非成功空响应 |
| 压测治理 | admin stress settings/whitelist/usage、approve-stress、stress-series、通知状态 | settings/whitelist/usage ledger/task series/audit；stress 容器独占时序写入 | B5；7日曲线来自 usage，任务曲线来自 task series；浏览器不请求 `/metrics` |
| 成员与账号 | users、member audit logs、`GET /users/activity-summary?from=&to=` | users/audit logs；登录活动和 KPI 从审计聚合，异地登录 AI 识别不在 V1.0 数据范围 | B1；停用后 login/me/WS 一致拒绝；V1.0 不出现角色字段或改角色审计 |

### 12.8 还原门禁与契约测试

1. 每个矩阵行须有：router 集成测试、迁移测试、至少一条“写入后重新 GET”的测试和前端 live 走查 HAR。
2. `GET /dispatch/events`、`GET /tasks/summary`、目录 CRUD 与列定义是原型可见状态的新增冻结契约；先更新 API V1.3 和生成的 OpenAPI，再写 router。
3. 能力暂不进入 V1.0 时，服务端返回 `capabilities` 或 HTTP 409 的 `VALIDATION` 能力未启用错误；不得返回随机数据、空成功对象或示例实体。
4. B2、B3、B4、B5 的出口分别签署一次矩阵回归。任意页面的持久化、事件来源或空态缺失，不能跨阶段宣称“原型已还原”。

