# AI 测试与评估平台 开发周期与计划

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.5 |
| 对应 PRD | V1.10（功能唯一权威） |
| 对应 API | V1.18（路径与 JSON 契约唯一权威） |
| 对应规范 | AGENTS.md V1.0（AI 行为准则、全中文注释与提交门禁） |
| 撰写日期 | 2026-08-17 |
| 最近修订 | 2026-08-23：M1 Agent 运行基线切换为 LangGraph 单轮图与 WebSocket 异步桥接；2026-08-19：M1 核心交付验收与 M2 提前启动（benchmark 真实执行器、评测域建表、样本明细接口落地） |
| 计划起点 | 2026-08-18 |
| V1.0 目标发布 | 2026-12-04 |
| 总工期 | **16 周**（含 1 周启动 + 1 周硬化缓冲） |

---

## 1. 编制说明

本计划严格对应 PRD 第 7 节里程碑（M1–M4）与功能表交付列，不把 V1.1 / 明确不做的能力排进 V1.0。

**V1.3 补充（2026-08-18）**：
1. **M0 阶段已圆满收官**：Docker Compose 六件套、FastAPI 核心骨架、Vue 3 + Naive UI 布局、统一错误码、自动部署流水线（`http://47.119.132.83/`）与 `AGENTS.md` 规范已全部就绪。
2. **规范与门禁**：所有开发必须遵循 `AGENTS.md` 规定的**全中文注释**、**提交前本地构建自检**（`npm run build`、`ruff check .`、`pytest`）及**中文 Conventional Commits 规范**。
3. **可演示口径**：默认请求真实 `/api` 与 `/ws` 接口；Mock 仅用于前端独立走查，禁止请求失败自动回退伪造样例数据。

**V1.4 补充（2026-08-19）**：
1. **M1 核心已交付**（实际进度领先 W1 日历）：认证/用户/审计/文件/协议档（Fernet 加密）/任务状态机/WS 短票与事件补发/会话回放/调度中心/LLM 意图识别与流式回复均已上线并通过 135 项后端测试；前端 11 个视图全部对接真实接口。
2. **M2 提前启动**：数据集域（目录树/数据行/扩展列）、用例域（用例集/用例行/目录树）、报告分享与基线冻结已建表迁移；**benchmark 真实执行器**（三协议真调用 + 五种规则评分 + 预算熔断 + 断点续跑 + 批内并发）与 `eval_items`/`usage_ledger` 评测域两张表、`GET /api/reports/{id}/samples` 样本明细接口已落地。
3. **仍按计划待做**：用例生成 Skill（W8）、表单双入口联调（W9）、RAG（M3）、压测（M4）。

**V1.5 补充（2026-08-23）**：
1. Agent 首期唯一运行链路为 `WebSocket -> LangGraph Agent -> ModelGateway -> 三协议适配器`；模型调用与 Agent 图已从旧框架迁出。
2. 当前首期只验收短票、会话回放、后台单轮调用、`user_message/thought/assistant_delta/assistant_message/response.completed/error/pong` 和正文/推理流式事件。
3. Harness、ReAct/MCP、确认卡、任务下单、Worker 长任务、记忆和并发规划不在本轮实现；相关 M1 计划项顺延到重新评审后的阶段。

### 1.1 范围边界

| 做（V1.0） | 不做（见 PRD 4.2） |
| --- | --- |
| Agent（WS + LangGraph；内部 MCP 为后续 Harness 能力） | 外部 MCP、改系统提示词 |
| Benchmark 三协议 + 规则评分 | 多租户、多模态、内置公开集 |
| 用例 Skill（自研对齐 testcase-tools） | TMS 同步、报告审批流 |
| RAG：LightRAG + 外部 OpenAI Chat | HumanEval 沙箱、被测走 WS |
| 共享压测：go-stress-testing + Grafana scrape | 分布式压测、评测与压测并行 |
| Compose 六件套、本地账号、预算 | Open API（排 V1.1） |

### 1.2 团队假设（可按人头缩放）

单团队内部产品，推荐编制：

| 角色 | 人数 | 主责 |
| --- | --- | --- |
| Python 后端 | 1 | FastAPI、LangGraph Agent、ModelGateway、worker、协议适配、评测/RAG、PG |
| Vue 前端 | 1 | Naive UI 工作台、WS 会话、确认卡、任务/报告/管理页 |
| Go / 基础设施 | 1 | go-stress-testing 扩展、Compose、Prometheus 对齐、部分联调 |

若只有 **2 人**（后端 + 前端，Go 由后端兼）：总工期改为 **20 周**，M4 后移约 4 周。  
若只有 **1 人全栈**：总工期约 **28–32 周**，不建议按本日历承诺 12 月发布。

节奏：每周一规划、周五演示；每里程碑结束做一次门禁演示（对应 PRD 第 7 节）。

### 1.3 日历总览

```text
2026-08-18                                                         2026-12-04
|--------|--------|--------|--------|--------|--------|--------|--------|
  M0 1w     M1 4w              M2 4w              M3 3w        M4 3w   H 1w
 [✅已交付] [✅核心交付]       Benchmark+用例      RAG         压测+通知 硬化
                              [🚀提前启动]
```

| 阶段 | 周次 | 日期 | 状态 | 主题 | 演示门禁（摘自 PRD） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **M0** | W1 | 08-18 ~ 08-24 | **✅ 已完成** | 工程启动 | Compose 六件套正常运行；CI/CD 自动部署就绪；AGENTS.md 规范落地 |
| **M1** | W2–W5 | 08-25 ~ 09-21 | **🔄 Agent 基础链路已交付，任务/Harness 范围冻结** | 底座 + LangGraph Agent | 登录后单轮流式对话；断线按 event_id 续；模型协议档与会话回放；任务下单待后续阶段 |
| **M2** | W6–W9 | 09-22 ~ 10-19 | **🚀 提前启动**（数据域/评测域建表、benchmark 与用例生成真实执行器、72h 扫描、基线 Δ 对比已落地） | Benchmark + 用例 + 表单 | 两协议档 + ≥20 条 JSONL，对话出 contain 对比报告 |
| **M3** | W10–W12 | 10-20 ~ 11-09 | 待启动 | RAG | LightRAG hybrid Hit Rate@5；外部 Chat RAG 出 contain |
| **M4** | W13–W15 | 11-10 ~ 11-30 | 待启动 | 先评后压 | test 白名单压 2 分钟；平台曲线与 Grafana 同 task_id |
| **H** | W16 | 12-01 ~ 12-04 | 待启动 | 硬化发布 | V1.0 验收清单全绿，打 tag 发布 |

---

## 2. 关键路径

最长依赖链（不能并行压缩）：

```text
账号/协议档 → WS LangGraph Agent 基础链路 → Harness/确认卡 → worker 状态机
    → 三协议真调用 + 规则评分（M2 门禁）
    → 质量 succeeded 才能派生子任务
    → stress 继承父任务 endpoint（M4 门禁）
```

可并行、不挡主路径的工作：

| 工作 | 最早可开工 | 状态 | 说明 |
| :--- | :--- | :--- | :--- |
| 协议适配器夹具单测 | M0 末 | ✅ 已完成 | 三协议成功 + 4xx 夹具进 CI |
| 前端页面壳与路由 | M0 | ✅ 已完成 | 11 个视图已对接真实 API |
| LightRAG 锁 tag + Compose 草稿 | M2 | 待启动 | M3 才接评测 |
| go-stress-testing 扩展骨架 | M2 | 待启动 | M4 才接父任务 |
| Grafana dashboard JSON 草稿 | M3 | 待启动 | 等 `/metrics` 契约冻结后微调 |
| 通知渠道（企微/邮件/Webhook） | M4 前半 | 待启动 | 不挡压测内核 |

---

## 3. 人员负荷（按阶段）

| 阶段 | Python | Vue | Go/Infra | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **M0** | 仓库、Compose、Alembic、鉴权骨架、AGENTS.md | Vite + Naive 壳、登录页、原型对齐 | Compose 六件套、CI/CD 自动部署、自愈脚本 | ✅ 100% 验收 |
| **M1** | LangGraph Agent（WS）、ModelGateway、协议档 CRUD、会话回放 | `/agent` 单轮会话流、思考卡、错误态；确认卡/短 MCP 暂冻结 | 容器健康检查、内存限制与构建缓存优化 | 🔄 基础链路已交付（08-23） |
| **M2** | 评测 worker、评分、报告、预算、用例 Skill | 数据集/用例确认/报告对比/表单下单 | 开始 fork go-stress-testing，先打通本地 HTTP 压测 | 🚀 提前启动（数据域/评测域建表、benchmark 真实执行器、评分器与样本明细接口已落地） |
| **M3** | LightRAG 适配、外部 RAG、黄金 QA、Judge | `/kb`、RAG 报告、退化标红 | LightRAG 服务稳定、索引卷、内网 DNS | 待启动 |
| **M4** | 先评后压编排、会签、费用估算、解读、通知 | 压测曲线、会签 UI、通知开关 | 指标、立即停、`/metrics`、Prometheus 抓取 | 待启动 |
| **H** | 性能、断点续跑、安全复查 | E2E 走查、空态/错误态 | 发布 Compose、备份与回滚说明 | 待启动 |

---

## 4. 分周计划

### M0 工程启动（W1，08-18 ~ 08-24）—— [✅ 已完成交付]

**目标**：能本地 `docker compose up` 打开登录页，全自动化 CI/CD 与规范落地，后续功能都落在同一骨架上。

| 编号 | 工作项 | 角色 | 完成标准 | 交付状态 |
| :--- | :--- | :--- | :--- | :--- |
| M0-1 | 单仓结构：`frontend/` 与 `backend/{api,worker,lightrag,stress}` + `deploy/` | 全员 | README 一条命令起开发环境 | ✅ 已完成 |
| M0-2 | FastAPI + Alembic + PostgreSQL；环境变量约定；健康检查 `GET /api/health` | Python | API 与数据库健康联通 | ✅ 已完成 |
| M0-3 | Vue3 + Vite + Naive UI + 路由壳（PRD 5.8）；薄荷绿/深空蓝主题 | Vue | `/login` 与各模块壳页面正常访问 | ✅ 已完成 |
| M0-4 | Compose 六件套：`web` `api` `worker` `postgres` `lightrag` `stress` | Go/Infra | 容器编排稳定启动并反代 | ✅ 已完成 |
| M0-5 | 编码规范、10 大错误码（PRD 5.5）、CI/CD 自动部署、AGENTS.md | 全员 | GitHub Actions 自动化流水线就绪 | ✅ 已完成 |

**M0 出口**：三人能独立拉起环境；线上端点 `http://47.119.132.83/` 部署通过；接口前缀统一 `/api`。

---

### M1 底座 + Agent（W2–W5，08-25 ~ 09-21）—— [🔄 基础链路已交付，范围重新切分]

当前 M1 门禁只验收 LangGraph 单轮 Agent 与 WebSocket 基础协议。短 MCP、确认卡、任务队列和 Worker 长任务不再作为本轮“已完成”条件，待 Harness 设计评审后重新排期。

**目标**：登录后对话下单空跑；断线按 `last_event_id` 续；协议档与数据集元数据 CRUD 全面打通。

对应：F-AGT-01/02/03/04/05/06/09，F-BM-01/02，F-CM-01/03/04/07。  
本阶段 **不跑真评测**，worker 对长任务可 mock `succeeded`。

#### W2  账号、权限、文件、审计

| 工作项 | 完成标准 |
| --- | --- |
| 引导管理员（环境变量）、改密、Cookie 12h | 首次部署可登录 |
| RBAC：管理员 / 工程师 / 只读（PRD 2.1） | 越权返回 `UNAUTHORIZED` |
| 用户 CRUD、停用、重置密码 | `/admin/users` 可用 |
| 文件：`./data/files/{id}` + sha256 | 单文件 ≤20MB，类型白名单 |
| `audit_logs`：登录失败、角色变更 | 可按时间查询 |

#### W3  协议档 + 三协议适配器

| 工作项 | 完成标准 |
| --- | --- |
| `protocol_profiles` CRUD，Key Fernet 加密、只写不回显 | 变更写审计 |
| 适配器：`openai_chat` / `openai_responses` / `anthropic_messages` | 入 `messages`，出 `text,usage,raw,latency_ms` |
| 每种协议 ≥2 个夹具单测（成功 + 4xx） | CI 必过 |
| 管理员指定 Agent 后端协议档 | 设置页可保存 |

#### W4  任务状态机 + worker + 短 MCP

| 工作项 | 完成标准 |
| --- | --- |
| 表：`tasks` `task_events`；状态 queued/running/succeeded/failed/cancelled | 取消权限符合 2.1 |
| worker 轮询 PG；会话内串行；平台 `max_running_tasks=3` | 超限保持 queued |
| 内部 MCP Server：`model.list` `task.get` `task.create` `task.cancel` | Agent 不执行长任务 |
| 长任务 mock 成功并写 `task_events` | 为 M2 替换成真执行留同一入口 |
| 任务中心列表：筛状态 / kind | `/tasks` 可用 |

#### W5  WebSocket Agent + 确认卡（M1 门禁周）

| 工作项 | 完成标准 |
| --- | --- |
| `POST /api/auth/ws-ticket`（5 分钟）+ `GET /ws/agent?ticket=` | 不用长期 JWT 进 query |
| 心跳 30s；重连 `session_id` + `last_event_id` 补发 | 断线任务不丢 |
| 事件：thought / tool_call / tool_result / confirm / progress / report / error / pong | 与 PRD 5.1.3 一致 |
| 确认卡字段校验；未确认不入队；人设：先澄清再下单 | 不绕过白名单（本阶段白名单可先空实现） |
| 上下文最近 20 条，系统提示词始终保留 | 超长丢最旧用户/助手消息 |
| `/agent` 对话 UI + 确认卡 + 进度区 | 可完成 M1 演示 |

**M1 演示脚本**

1. 管理员登录，新增一个协议档（Key 不回显）。
2. 工程师打开 Agent，说「帮我下一单 Benchmark」。
3. 弹出确认卡，确认后任务 `queued → running → succeeded`（mock）。
4. 刷新或断线重连，进度仍在；任务中心看得到日志。

**M1 出口检查表**

- [x] Compose 四核心服务稳定
- [x] WS 短票、心跳、补发
- [x] 确认卡未确认不入队
- [x] 协议档 CRUD + 适配器单测
- [x] 工程师只能取消自己的任务，管理员可取消任何人的（V1.6.3 权限口径：全员同权，取消限创建者；非创建者负例有单测）

---

### M2  Benchmark + 用例 + 表单（W6–W9，09-22 ~ 10-19）

对应：F-AGT-07，F-BM-03～07，F-CM-02/06，5.4.1～5.4.2。  
成功指标「Agent 闭环」在本阶段达成。

#### W6  数据集与真调用

| 工作项 | 完成标准 |
| --- | --- |
| JSONL/CSV 上传，列 `question,reference,context?` | ≤50MB、≤2 万行；覆盖上传版本 +1 |
| `benchmark.run`：抽样 / 并发 / 超时 / 重试（PRD 5.2.2） | 失败样本记 error，不中断整次 |
| 非流式调用被测；raw ≤32KB | `UPSTREAM` 可区分 |
| 评测按样本行号可续跑 | worker 重启不丢进度 |

#### W7  规则评分、多模型、报告、预算

| 工作项 | 完成标准 |
| --- | --- |
| 主指标：exact / contain / regex / rouge_l / bleu，默认 contain | 每集一种 |
| 1–5 个 profile 并排报告 | 任务快照含配置 |
| Markdown 导出；分享链接 7 天 | 只读可打开未过期链接 |
| `usage_ledger`；单任务 `max_usd` 默认 5 | 超限停并 `BUDGET_EXCEEDED` |
| 管理员冻结基线；同 dataset 版本 + 主指标才能对比 | 解冻写审计 |

#### W8  用例生成 Skill + 映射

| 工作项 | 完成标准 |
| --- | --- |
| 输入：PRD 文本、OpenAPI JSON/YAML、Excel | P1 的 Postman/MD 本周不做 |
| 六策略：正向/反向/边界/等价/状态/场景；P0–P3 | 对齐附录 A，不引入 testcase-tools 源码 |
| 规模上限与 5 分钟超时；自检红字 | 超上限停，禁止灌水 |
| 状态 `awaiting_case_confirm`；确认入库或 72h 取消 | 确认后任务 succeeded，worker 不续跑 |
| 映射到 Benchmark；缺字段进待补全，不进分母 | 写 `source_case_id` + 用例版本 |
| 导出 xlsx / xmind | `/cases` 确认页可用 |

#### W9  表单双入口 + M2 门禁

| 工作项 | 完成标准 |
| --- | --- |
| `POST /api/tasks` 字段与确认卡一致 | Agent 与表单进同一张任务表 |
| `/datasets` 表单发起 Benchmark | 无对话也能出报告 |
| 会话槽位：queued/running/awaiting 含后续子任务占位逻辑先实现父任务侧 | 会话内同时最多 1 个非终态 |

**M2 演示脚本（PRD 5.2.3）**

1. 上传 ≥20 条 JSONL。
2. 配两个不同协议档。
3. Agent 确认后跑真评测，出 contain 对比报告。
4. 断线重连仍能看进度。
5. 用一份缺 `question` 的用例映射，待补全行不进评分分母。

**M2 出口检查表**

- [ ] 评测周期口径可测：≤1k 样本、被测稳定时任务能在报告页看到结果
- [ ] 用例采纳率统计字段已有（确认入库 / 生成条数）
- [ ] 预算超限必停
- [ ] 基线冻结/对比规则生效

---

### M3  RAG（W10–W12，10-20 ~ 11-09）

对应：F-RAG-01～06，F-BM-08（Judge，P1）。  
通知仍不在本阶段；退化只在报告内标红。

#### W10  内置 LightRAG

| 工作项 | 完成标准 |
| --- | --- |
| Compose 正式接入 LightRAG，锁 Git tag | MIT，镜像可复现 |
| 上传文档建索引；`doc_id`=UUID 写入 metadata | `/kb` 可看文档数 |
| 查询走原生 `query` API，适配 `{text, contexts[{id,text}]}` | **不伪装成 OpenAI Chat** |
| 模式 naive/local/global/hybrid，一任务 1–4 个，默认 hybrid | 确认卡字段生效 |

#### W11  黄金 QA、指标、外部 RAG

| 工作项 | 完成标准 |
| --- | --- |
| 黄金 QA：`question,reference,expected_doc_ids[]?`；≤1 万条；版本 +1 | 覆盖上传 |
| Hit Rate@K / MRR / Recall@K，K 默认 5、可配 1–20 | 无 id 的样本不进 Hit 分母 |
| 答案侧 contain；命中=返回 id 集合与 expected 相交 | 与 PRD 5.3.1 一致 |
| 外部 RAG：仅 `POST {base}/v1/chat/completions` | content + 可选 context/contexts[] |
| 同 kb + gold 版本对比；退化 ≥5pp 报告标红 | 不发通知 |

#### W12  Judge + M3 门禁

| 工作项 | 完成标准 |
| --- | --- |
| LLM-as-Judge：1–5 分 + 理由；裁判档 ≠ 被测时警告、不强制 | Benchmark 与 RAG 答案侧可选用 |
| RAG 基线冻结（管理员） | 与 Benchmark 基线权限一致 |
| 前端 RAG 报告：模式对比、Hit@K、标红 | 只读可看 |

**M3 演示脚本（PRD 5.3.2）**

1. 默认知识库 + ≥20 条带 `expected_doc_ids` 的 QA，hybrid 出 Hit Rate@5。
2. 同一套 QA 打外部 OpenAI Chat RAG（可用 mock）出答案 contain。

**M3 出口检查表**

- [ ] LightRAG 与外部 Chat 两套路径指标口径一致（答案侧）
- [ ] 检索侧无 id 时不污染 Hit Rate
- [ ] Judge 不重跑业务评测，只对已有输出打分

---

### M4  共享压测 + 解读 + 通知（W13–W15，11-10 ~ 11-30）

对应：F-ST-01～07，F-AGT-08，F-CM-05。  
压测内核必须是 **go-stress-testing 扩展**，独立 `stress` 容器，worker 只下发。

#### W13  压测内核与继承目标

| 工作项 | 完成标准 |
| --- | --- |
| 扩展 go-stress-testing：保留 NOTICE（Apache-2.0） | 独立容器，api 内不用 Python 替代 |
| Benchmark / 外部 RAG：继承父任务 URL/Header/协议；body 抽最多 50 条 question 轮询 | 先评后压：父任务非 succeeded 不创建 |
| 内置 LightRAG：压内网 `query` HTTP，按父任务 `rag_mode` 组装 | 不是 Chat Completions |
| 模型指标：QPS、RT、错误率、TTFT、TPOT、tokens/s（SSE） | RAG 非流式可不记 TTFT |
| 取消 = **立即停发** | 与评测「当前样本结束后停」区分 |
| 会话槽位含子任务：父 succeeded 后子任务占槽 | 未完成不能再开新长任务 |

#### W14  安全、监控、SLA、费用

| 工作项 | 完成标准 |
| --- | --- |
| env 必填；host 白名单；默认 QPS≤500、时长≤30min | 无白名单无法 running |
| 错误率 60s≥50% 自动停；`prod` 会签（确认卡展示会签人） | 未会签压测保持 queued，质量报告仍保留 |
| `/metrics` 内网；Basic 或 IP 白名单；前缀 `ai_eval_stress_` | label `env,model,task_id`；结束后 10min 停该 task 序列 |
| 与现网 Prometheus 对齐 `job=ai-eval-stress` | Grafana 能按 task_id 查到 |
| 未填 `sla_p99_ms` 不出「是否达标」；填了则拐点=首次 P99>SLA 或错误率≥1% | 报告可复现 |
| 用父任务 usage 单价估算窗口费用 | 管理员配单价 /1k tokens |
| `/admin/stress`：白名单、单价、并发、预算默认 | 仅管理员 |

#### W15  解读、通知、M4 门禁

| 工作项 | 完成标准 |
| --- | --- |
| Agent 解读：仅对已有 `report_id` 调评测 Skill，不重跑 | F-AGT-08 |
| 通知：终态、退化、会签；企微 / 邮件 / 出站 Webhook | 管理员开关 |
| 任务页与 Agent 进度区：QPS/RT/错误率曲线 | 与 Grafana 同 task_id 可对上 |

**M4 演示脚本（PRD 5.6）**

1. test 环境白名单地址，质量成功后自动压 2 分钟。
2. 平台曲线与 Grafana 能用同一 `task_id` 对上。
3. 去掉白名单后压测无法进入 running。
4. 取消压测后发压立即停止。

**M4 出口检查表**

- [ ] 勾选压测的任务 100% 先出质量结果
- [ ] Grafana 压测 100% 出现 `job=ai-eval-stress`
- [ ] `prod` 未会签不得 running

---

### H  硬化与 V1.0 发布（W16，12-01 ~ 12-04）

短周，只收口，不加功能。

| 工作项 | 完成标准 |
| --- | --- |
| 性能：≤1k 样本、被测 ≥5 QPS 时规则评测 ≤30min | 用内网 mock 或稳定测试档实测 |
| 中等 PRD 用例生成 ≤5min | 对照 PRD 第 8 节 |
| Key 不落日志；`/metrics` 不暴露公网 | 安全走查 |
| 备份：PG dump + `./data/files` 卷说明 | 一页运维文档 |
| 打 `v1.0.0` tag；Compose 锁定镜像 tag | 可回滚到上一 tag |

**V1.0 发布门禁（成功指标）**

| 指标 | 验收方式 |
| --- | --- |
| Agent 闭环 | 按 M2 演示再跑一遍 |
| 用例采纳率 ≥70% | 用 3 份真实 PRD 统计 |
| 评测周期 ≤0.5 天 | ≤1k 样本、≤5 协议档，从确认到报告可看 |
| 先评后压 100% | 抽 5 次失败/取消任务，确认无压测子任务 |
| Grafana 100% | 抽 5 次压测，job 与 task_id 齐全 |

---

## 5. 迭代节奏与「完成」定义

### 5.1 每周节奏

| 日 | 活动 |
| --- | --- |
| 周一 | 站会排本周条目；阻塞升级（协议差异、Prometheus 网段、LightRAG tag） |
| 周三 | 前后端契约对一次（OpenAPI 或共享 TS 类型） |
| 周五 | 30 分钟演示；更新本里程碑检查表 |

### 5.2 完成定义（DoD）

任意功能合入主干必须同时满足：

1. 有对应 PRD 编号（如 F-BM-05），行为与文档一致。
2. 后端：单测或夹具；涉及协议的必须含成功 + 4xx。
3. 前端：主路径 + 空态 + 错误码可见提示。
4. 权限按 2.1 测过（至少工程师 vs 只读）。
5. 写 `audit_logs` 的点已打点（Key、基线、白名单、prod、角色）。
6. 不把 P1/后续项塞进当前里程碑冒充完成。

### 5.3 建议的测试分层

| 层 | 谁写 | 覆盖 |
| --- | --- | --- |
| 适配器夹具 | Python | 三协议 |
| 状态机单测 | Python | 取消、72h、先评后压、会签 |
| API 集成 | Python | 登录、任务、预算 |
| 前端关键路径 | Vue | Agent 确认卡、报告对比 |
| 压测契约 | Go | `/metrics` 名、立即停止 |
| 里程碑手工脚本 | 全员 | 第 7 节演示门禁 |

---

## 6. 风险对计划的预留

对应 PRD 第 9 节，把缓冲写进日历，而不是口头「再看看」。

| 风险 | 可能爆在 | 预留 | 触发与降级 |
| --- | --- | --- | --- |
| 三协议字段差 | M1 W3–W4 | 适配器单测先行；W5 不依赖真实厂商账号（可用 mock server） | 某协议延期不影响另两个进 M2 |
| 并行打爆上游 API | M2 | 默认并发 4 / 平台 inflight 8；预算 5 USD | 先降并发再扩能力 |
| 用例映射大量待补全 | M2 W8 | 允许手传 JSONL 走主路径 | 映射做不好不挡 Benchmark 门禁 |
| LightRAG 升级不兼容 | M3 W10 | 锁 tag；W10 前完成镜像冻结 | 评测逻辑与框架解耦，只适配 query |
| Prometheus 抓不到 | M4 W14 | W13 先冻结指标名；与监控同学在 W12 对齐网段 | 平台曲线仍可验收，Grafana 为并行门禁 |
| 压测误伤 | M4 | 白名单 + 默认上限 + 熔断，W14 必须测负例 | 无白名单不能 running |
| 用例确认悬挂 | M2 | 72h 超时在 W8 做掉 | 定时任务扫描 |

**进度红线**：任一里程碑周五门禁未过，下一阶段 **只允许修门禁项**，禁止提前拉取下一阶段功能（例如 M2 没出对比报告就不开 LightRAG 页面）。

---

## 7. 交付物清单

| 时间点 | 交付物 |
| --- | --- |
| M0 结束 | 可运行仓库、Compose 开发文档 |
| M1 结束 | Agent 空跑 Demo；协议档管理；任务中心 |
| M2 结束 | 可用的 Benchmark + 用例生成；报告导出 |
| M3 结束 | LightRAG / 外部 RAG 评测 |
| M4 结束 | 先评后压 + Grafana |
| V1.0 | `v1.0.0` 镜像、运维一页纸、已知问题列表 |

V1.0 **明确延期到 V1.1**（不占本周期人力，除非门禁已全绿）：

- Open API（F-CM-08）
- 用例输入：Postman、Markdown 接口
- RAG 过程可视化（F-RAG-07）
- 多模态、多租户、分布式压测

---

## 8. 若要压缩或拉长

| 策略 | 做法 | 代价 |
| --- | --- | --- |
| 压到 12 周发 V1.0 | 砍 M3 外部 RAG mock 即可；Judge 改 V1.1；通知只留 Webhook | 成功指标不变，体验变窄 |
| 12 月中旬才进人 | 保持 16 周，发布改为 2027-01 | 不要靠加人到 M4 救火 |
| 只要「先能评模型」 | 以 M2 为内部试用版（约 10-19），M3/M4 继续 | 对外仍不算 V1.0 |
| 2 人团队 | M1 6 周、M2 5 周、M3 4 周、M4 4 周、H 1 周 | 目标发布约 2027-01-12 |

---

## 9. 开工当天（08-18）待办

1. 建仓库与分支保护（main + 里程碑分支 `m1`/`m2`/`m3`/`m4`）。
2. 冻结技术选型版本：Python 3.12、Vue 3、Naive UI、PostgreSQL 16、LightRAG tag、go-stress-testing tag。
3. 向监控同学发指标前缀 `ai_eval_stress_` 与 `job=ai-eval-stress`（M4 才接，但网段要早约）。
4. 准备至少两套测试用协议档（可用兼容 OpenAI 的本地 mock）。
5. 按本计划 W1 清单开工，周五只验收「环境能起、登录页能开」。

本计划与 PRD 冲突时 **以 PRD V1.8 为准**，改计划不改范围；若要改范围，先改 PRD 再改本日历。
