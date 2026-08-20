# AI 测试与评估平台 PRD

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.6.5 |
| 文档状态 | 已冻结基线 |
| 撰写日期 | 2026-08-17 |
| 最近修订 | 2026-08-20 |
| 适用版本 | 平台 V1.0 |
| 技术栈 | Vue3 + Naive UI、Python FastAPI、PostgreSQL、WebSocket、Docker Compose、go-stress-testing |

### 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| V1.0–V1.4 | 2026-08-17 | 能力清单与决策收口 |
| V1.5 | 2026-08-17 | 三模块 + 共享压测；Agent / MCP / 三协议 |
| V1.6 | 2026-08-17 | 补缺陷：任务状态机、Agent/Worker 分工、MCP/REST 契约、协议细节、评测/压测配置、页面与验收、预算与并发 |
| V1.6.1 | 2026-08-17 | 复查修复：一任务一种 kind、LightRAG 查询契约、会签/取消权限、指标与协议档数量对齐 |
| V1.6.2 | 2026-08-17 | 与问答复核：压测内核改回 go-stress-testing；附录 B 逐条对照 |
| V1.6.3 | 2026-08-17 | 再核：WS 用 ticket 非长期 token；压测由 stress 容器执行且取消立即停；LightRAG 压测走 query 而非 Chat；会话槽位含子任务 |
| V1.6.4 | 2026-08-18 | 全面去除静态 Mock 数据，全量接入后端 API 统一客户端；落实全员同权协作与智能体/调度/任务中心动态交互 |
| V1.6.5 | 2026-08-20 | 新增默认私有、创建者可切换团队共享的 Agent 会话；补齐软删除、多人实时正文流与确认卡作者边界 |

---

## 1. 背景与目标

### 1.1 背景

用 **Agent 自动化**做大模型基准测试和 RAG 测试，压测是两类评测的共享步骤：先质量、后对同一 endpoint 加压。

| 痛点 | 后果 |
| --- | --- |
| 评测靠脚本、协议各写一套 | 无法一句话跑完「选模型 → 跑集 → 报告 → 加压」 |
| 无统一任务与基线 | 选型不可复现 |
| LightRAG 与自建 RAG 指标不一 | 知识库更新后不敢发 |
| 质量与容量断开 | 效果好但一压就垮 |

### 1.2 产品定位

面向**单一团队**。主入口是 **WebSocket Agent**；表单为辅。Agent 作为 **MCP Host**：只调短工具并 `task.create`。三个模块 + 共享压测：

| 模块 | 职责 |
| --- | --- |
| A. Agent | 会话、拆解、确认卡、进度；**不执行长任务** |
| B. Benchmark | 自定义文本集、三协议调用、规则评分 / Judge、对比与基线 |
| C. RAG | Compose 内 LightRAG，或外部 **OpenAI Chat Completions** RAG HTTP |
| 共享压测 | 质量成功后压同一推理 / query 接口；平台面板 + Prometheus scrape |

### 1.3 目标

1. 对话完成：用例（可选）→ Benchmark 和 / 或 RAG →（可选）压测 → 报告。
2. 兼容 `openai_chat`、`openai_responses`、`anthropic_messages`；Agent / Judge / 被测均可切换。
3. 无内置公开榜单；集来自 JSONL/CSV 或用例映射。
4. 一张 Compose 拉起：`web` `api` `worker` `postgres` `lightrag` `stress`（go-stress-testing 扩展）。

### 1.4 成功指标

| 指标 | 目标 | 口径 |
| --- | --- | --- |
| Agent 闭环 | M2 对话跑通一次 Benchmark | 含确认卡；断线任务不丢 |
| 用例采纳率 | ≥ 70% | 确认入库条数 / 当次生成条数 |
| 评测周期 | ≤ 0.5 天 | ≤1k 样本、≤5 个协议档；从确认到报告可看 |
| 先评后压 | 勾选压测的任务 100% 先出质量结果 | 质量失败或取消则不加压 |
| Grafana | 压测 100% 出现 `job=ai-eval-stress` | |

### 1.5 术语

| 术语 | 含义 |
| --- | --- |
| 协议档 | `openai_chat` / `openai_responses` / `anthropic_messages` 之一 + base_url + 模型名 + 加密 Key |
| 会话 | 每成员可多开；默认仅创建者可见，也可由创建者设为团队共享；**会话内任务串行**，会话间可并行（受平台并发上限） |
| 长任务 | `benchmark.run` / `rag.evaluate` / `testcase.generate` 由 **worker 进程执行**；`stress.run` 由 worker **下发到 stress 容器**（go-stress-testing） |
| 短工具 | `*.list` / `report.get` / `task.get`，Agent 可同步调用 |
| 先评后压 | 质量任务 `succeeded` 后才创建压测子任务 |
| 待补全 | 映射缺字段，不进入评分队列 |

### 1.6 已确认决策

| 议题 | 决策 |
| --- | --- |
| 切分 | Agent / Benchmark / RAG；压测共享 |
| 交互 | Agent 主、表单辅；同一任务表 |
| MCP | 仅内部；Agent 当 Host 调短工具并下单；长任务由 worker 调同一 MCP |
| Skill | 评测 + 用例生成（对齐 testcase-tools，不拷源码） |
| 协议 | Chat Completions + Responses + Anthropic Messages |
| Key | 管理员平台级池 |
| 队列 | PG 任务表 + worker；WS 只推事件 |
| RAG | 内置 LightRAG + 外部 OpenAI Chat HTTP |
| 压测 | 先评后压；压模型推理与 RAG query；**go-stress-testing** 扩展；scrape Grafana |
| 部署 / 登录 / 文件 | Compose；本地账号；本地盘 + PG 路径 |
| 公开集 | 无 |
| 人设 | 固定资深评测工程师 |
| 合规 | 单团队；不涉密不强制私有化；报告不进审批；用例不同步 TMS |

---

## 2. 用户、权限与账号

### 2.1 角色架构（单一角色「成员」· 全员同权）

平台面向敏捷 AI 评测团队，采用**单一角色「成员」（全员同权）**架构，彻底摒弃复杂的 RBAC 三级角色阻碍：

| 权限范围 | 权限能力说明 | 审计与约束 |
| --- | --- | --- |
| **评测与任务** | Agent 交互、创建评测任务（Benchmark / RAG / 用例 / 压测）、取消与重跑任务 | 任务创建与取消均记录审计日志 |
| **资产与工作台** | 数据集与黄金 QA 管理、用例库确认与批量映射、知识库上传与切块检索 | 数据集/知识库变更记录版本快照 |
| **配置与治理** | 协议档维护与连通性检查、压测治理白名单与预算配置、调度策略与并发上限 | 敏感变更写审计；生产发压二次确认 |
| **账号与成员** | 开户、停用账号、重置密码、修改个人凭据 | 强制保护：不可停用系统中最后一名正常账号 |

首次部署：环境变量创建初始成员账号，登录后强制改密。密码 ≥8 位，含字母和数字。浏览器会话使用 HttpOnly Cookie（12h 可续）。WebSocket 连接使用 5 分钟短票（ticket），见 F-AGT-01。

### 2.2 团队协同原则

团队全员同权，通过全局顶栏「大模型 / RAG」双模式与统一任务工作台实现高效无阻碍协同。

Agent 会话采用以下更细的资产边界，不把「全员同权」误解为默认公开历史：

- 新会话默认 `private`，仅会话创建者可浏览、发送消息、连接 WS、压缩上下文、设置共享或软删除；
- 创建者可切为 `team`，表示当前单一内部团队的正常成员均可浏览历史、发送消息并看到在线协作者产生的 AI **正文**流式增量；本期不是邀请制成员表；
- 创建者可随时收回为 `private`，服务端立即断开协作者连接；已删除会话对所有成员返回“会话不存在”；
- 共享会话中的确认卡只允许提出该卡的成员确认、拒绝或提交 patch；任务仍归该成员创建，取消/重跑仍按任务创建者；
- 原始模型推理 `think` 流不对协作者广播。附件被发送到共享会话即视为授权本团队成员查看。

---

## 3. 业务流程

### 3.1 职责：谁调 MCP

| 角色 | 可调用 | 不可 |
| --- | --- | --- |
| Agent（WS 进程） | 短工具；写「待执行」任务 | 自己跑完 Benchmark/RAG/压测 |
| Worker | 评测 / RAG / 用例生成 MCP；`stress.run` 只负责向 stress 容器下发 | 向用户闲聊；自己打满压测连接 |
| 表单 REST | 直接 `POST /api/tasks`，状态与 Agent 下单相同 | — |

这样 WS 断开不影响执行；确认卡只决定「是否入队」。

### 3.2 主路径

```
打开会话 → 说话 → Agent 澄清并调短工具列选项
        → 确认卡（见 5.1.2）  ※ 一任务仅一种 kind
        → INSERT task queued
        → worker 执行该 kind
              testcase → awaiting_case_confirm → 用户确认后终态 succeeded
                    Agent 可自动再弹一张 Benchmark/RAG 确认卡（新任务）
              benchmark / rag → succeeded 且 with_stress
                    → 自动入队压测子任务
              report 落库
        → WS 推 progress / report / error（重连按 last_event_id 补发）
```

V1 **不允许**一个任务同时跑 Benchmark 和 RAG。要两份报告就下两单（可同一会话连续确认）。质量任务 `failed` / `cancelled` 不创建压测。

### 3.3 任务状态机

```
queued → running → succeeded
                 → failed
                 → cancelled
                 → awaiting_case_confirm → succeeded（确认入库）
                                         → cancelled（拒绝或 72h）
```

| 状态 | 含义 | 谁能改 |
| --- | --- | --- |
| queued | 等待 worker | 创建者/管理员可取消 |
| running | worker 或 stress 占用 | 创建者/管理员可取消。评测：当前样本结束后停。压测：立即停 |
| awaiting_case_confirm | 用例已生成未确认 | 创建者确认则 **succeeded**（入库）；取消或 72h → cancelled |
| succeeded / failed / cancelled | 终态 | 可「复制为新任务」 |

子任务（压测）`parent_task_id` 指向质量任务。质量任务成功且 `with_stress=true` 时由 worker **自动入队**压测，不需要第二次确认（`prod` 除外：压测入队前再走会签，未会签则质量报告仍保留、压测保持 `queued` 并通知）。

### 3.4 并发

- 会话内：同时最多 1 个处于 `queued` / `running` / `awaiting_case_confirm` 的任务（**含压测子任务**）。父任务 `succeeded` 后子任务占用该槽，未完成前不能再开新的长任务。
- 平台：管理员配置 `max_running_tasks`（默认 3）与 `max_inflight_model_calls`（默认 8）。超限新任务保持 queued。

---

## 4. 范围

### 4.1 内

三模块、共享压测、三协议、内部 MCP、用例/评测 Skill、Naive UI 工作台、Compose 六件套（含 stress）、Grafana scrape、预算与并发。

### 4.2 外

外部 MCP、改系统提示词、多租户、多模态、内置公开集、TMS 同步、审批流、强制私有化、压平台自己、评测与压测并行、被测走 WS、HumanEval 沙箱、分布式压测、Open API（V1.1）。

---

## 5. 功能需求

### 5.1 模块 A — Agent

#### 5.1.1 功能表

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-AGT-01 | WS 会话 | P0 | M1 | 登录后发 5 分钟 `ws_ticket`，`GET /ws/agent?ticket=` 升级（不用长期 JWT 进 query）。心跳 30s；重连带 `session_id`+`last_event_id` |
| F-AGT-02 | 事件流 | P0 | M1 | 见 5.1.3 |
| F-AGT-03 | MCP Host | P0 | M1 | 只连内部 Server；短工具同步，长任务只 `task.create` |
| F-AGT-04 | 确认卡 | P0 | M1 | 见 5.1.2；未确认不入队 |
| F-AGT-05 | 人设 | P0 | M1 | 先澄清再下单；不绕过白名单与会签；不执行用户要求的任意代码 |
| F-AGT-06 | Agent 后端 | P0 | M1 | 管理员指定一个协议档；上下文默认最近 20 条消息，超出丢最旧（系统提示词始终保留） |
| F-AGT-07 | 表单双入口 | P0 | M2 | `POST /api/tasks` 与确认卡字段一致 |
| F-AGT-08 | 解读 | P1 | M4 | 仅对已有 `report_id` 调评测 Skill，不重跑评测 |
| F-AGT-09 | 取消 / 重跑 | P0 | M1 | 工程师取消自己的非终态任务；管理员可取消任何人的。评测取消=当前样本结束后停；**压测取消=立即停发**。重跑=新任务拷配置 |
| F-AGT-10 | 团队共享与软删除会话 | P0 | M1 | 默认私有；会话创建者可切为 `team`，在线协作者实时看到用户消息与 AI 正文 chunk；删除为软删除，运行中的 Harness、待确认卡或非终态任务必须先结束 |

#### 5.1.2 确认卡字段（P0）

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `kind` | 是 | 仅四选一：`benchmark` / `rag` / `testcase` / `stress`（`stress` 一般不手选，由系统在质量成功后创建） |
| `profile_ids[]` | `benchmark` 必填 | 1–5 个被测协议档；`rag` 打外部 Chat 时填 1 个「RAG 服务」档 |
| `dataset_id` | `benchmark` 必填 | |
| `kb_id` + `gold_qa_id` | `rag` 必填 | 内置库或外挂 RAG 都要黄金 QA |
| `rag_mode` | `rag` 且目标为 LightRAG | 1–4 个模式，默认 `["hybrid"]` |
| `run` | 评测必填 | 见 5.2.2，RAG 复用 sample/concurrency/timeout |
| `with_stress` | `benchmark`/`rag` 必填 | 默认 false；true 时质量成功后自动建子任务 |
| `stress` | `with_stress` 时必填 | `env`, `qps`, `duration_s`, `sla_p99_ms?` |
| `case_source` | `testcase` 必填 | `file_id` 或粘贴文本 |

`prod` + 压测：确认卡展示会签人，未完成会签不得把压测设为 running。

#### 5.1.3 WS 事件

公共头：`event`, `session_id`, `task_id?`, `event_id`（单调）, `ts`。

| event | payload 要点 |
| --- | --- |
| `thought` | 短文本，给人看 |
| `message` | 已持久化用户消息、作者与浏览器幂等键；协作者即时补气泡 |
| `tool_call` | `name`, `arguments` |
| `tool_result` | `name`, `ok`, `data` 或 `error` |
| `confirm` | 确认卡 JSON，等前端 `confirm_ack` |
| `progress` | `percent?`, `done`, `total`, `message` |
| `report` | `report_id` |
| `error` | `code`, `message`（可给用户看） |
| `pong` | 心跳 |

前端 → 服务：`user_message` `{text, attachments[]?, client_message_id?}`，`confirm_ack` `{ok, patch?}`，`cancel_task` `{task_id}`。

`thought.stream=chunk` 只在在线时即时广播，断线不回放，随后完整交付句仍写入历史；`thought.stream=think` 仅发给本轮发起连接，不向团队协作者泄露；本轮成功结束时以 `thought.stream=think_final` 保存完整思考快照，供历史回放恢复思考卡。

附件：先 `POST /api/files` 得 `file_id`，再在消息里引用。单文件 ≤20MB；PRD/OpenAPI/Excel/JSONL/CSV/PDF/MD/TXT/HTML。

---

### 5.2 模块 B — Benchmark

#### 5.2.1 功能表

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-BM-01 | 协议档 CRUD | P0 | M1 | 见 6.2；Key 只写不回显，审计变更 |
| F-BM-02 | 统一调用 | P0 | M1 | 入 `messages`，出 `text,usage,raw,latency_ms` |
| F-BM-03 | 数据集 | P0 | M2 | JSONL/CSV UTF-8；列 `question,reference,context?`；版本号每次覆盖上传 +1；单集 ≤50MB、≤2 万行 |
| F-BM-04 | 用例入集 | P0 | M2 | 5.4.2；待补全不评分 |
| F-BM-05 | 规则评分 | P0 | M2 | 每集选一种主指标：exact / contain / regex / rouge_l / bleu；默认 contain |
| F-BM-06 | 多模型 | P0 | M2 | 1–5 个 profile；报告并排 |
| F-BM-07 | 基线 | P0 | M2 | 管理员冻结某次 succeeded；同 dataset 版本+主指标才能对比 |
| F-BM-08 | Judge | P1 | M3 | 裁判协议档 ≠ 被测（警告，不强制）；1–5 分 + 理由 |
| F-BM-09 | 代码题 | — | 不做 | |

#### 5.2.2 运行配置 `run`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `sample_size` | min(1000, 全集) | 随机抽样，种子写入任务便于复现 |
| `concurrency` | 4 | 受 `max_inflight_model_calls` 限制 |
| `timeout_s` | 60 | 单样本 |
| `retry` | 1 | 仅超时/5xx |
| `temperature` | 0 | |
| `max_tokens` | 1024 | |
| `system_prompt` | 空 | 可选，写入任务快照 |

失败样本记 `error`，不中断整次任务；失败率写入报告。

#### 5.2.3 验收（M2）

两个协议档 + 一份 ≥20 条 JSONL，对话确认后出对比报告（contain 分）；断线重连仍看得到进度；缺 question 的映射行在待补全，不进分母。

---

### 5.3 模块 C — RAG

#### 5.3.1 功能表

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-RAG-01 | 内置 LightRAG | P0 | M3 | Compose 服务；上传建索引；`doc_id`=UUID 写入 metadata。**查询走 LightRAG 原生 `query` API**（模式见 F-RAG-05），平台适配成内部 `{text, contexts[{id,text}]}`，不把 LightRAG 伪装成 OpenAI Chat |
| F-RAG-02 | 外部 RAG | P0 | M3 | 仅 `POST {base}/v1/chat/completions`；答案 `choices[0].message.content`；上下文 `message.context` 或 `message.contexts[]`（字符串或 `{id,text}`） |
| F-RAG-03 | 黄金 QA | P0 | M3 | `question,reference,expected_doc_ids[]?`；≤1 万条；整集覆盖上传版本 +1 |
| F-RAG-04 | 指标 | P0 | M3 | `expected_doc_ids` 非空：Hit Rate@K、MRR、Recall@K，**K 默认 5 可配 1–20**。答案：contain。Judge P1 |
| F-RAG-05 | LightRAG 模式 | P0 | M3 | naive/local/global/hybrid，一次任务可选 1–4 个 |
| F-RAG-06 | 基线 | P0 | M3 | 同 kb + gold 版本对比；退化 ≥5pp 标红。**通知在 M4**，M3 只在报告内标红 |
| F-RAG-07 | 过程可视化 | P1 | 后续 | |

命中判定：返回的 context.id 或可解析的 doc_id **集合相交** `expected_doc_ids` 即命中。纯文本无 id 时该样本不计入 Hit Rate 分母。

#### 5.3.2 验收（M3）

默认库 + ≥20 条带 `expected_doc_ids` 的 QA，hybrid 出 Hit Rate@5；同一套 QA 打外部 OpenAI Chat RAG（可用 mock）出答案 contain。

---

### 5.4 Skill

#### 5.4.1 用例生成

| 项 | V1 |
| --- | --- |
| 输入 P0 | PRD 文本、OpenAPI JSON/YAML、Excel（标准列或 模块/名称/步骤/预期） |
| 输入 P1 | Postman、Markdown 接口 |
| 输出 | XMind + Excel（`GET /api/case-sets/{id}/export?fmt=xlsx\|xmind`），状态 `generated` |
| 自检 P0 | 无核心正向、缺约束反向 → 确认页红字 |
| 规模 | 参考上限：PRD 简单/中/复杂 20/45/80 条；超上限停并提示拆分，禁止灌水 |
| 超时 | 5 分钟，超时 failed |

#### 5.4.2 映射

| 目标 | 自动 | 否则 |
| --- | --- | --- |
| Benchmark | 问句→question，预期→reference，前置→context | 待补全 |
| 黄金 QA | 同上；doc_ids 手补 | 无 id 仅答案侧 |
| 压测 body | 步骤中 `METHOD path` + 示例 JSON | 无 path 则压测只用评测时的默认 chat 模板 |

映射写 `source_case_id`+用例版本。

#### 5.4.3 评测 Skill

规则实现、Judge 提示词、报告解读提示词。随镜像发布，无热更新 UI。

---

### 5.5 MCP 工具中心与技能编排

平台采用 **MCP Host** 统一智能体架构。长任务由 Worker 异步执行；Agent 仅调用 MCP 短工具进行信息发现与 `task.create` 结构化建单。

#### 5.5.1 内置受控短工具清单 (Tools Manifest)

| 工具名称 | 类型 | 入参（摘要） | 出参 | 权限与用途 |
| --- | --- | --- | --- | --- |
| `model.list` | 短 | — | 协议档 id/名称/协议（无 Key） | READ · 模型资产发现 |
| `dataset.list` | 短 | — | 数据集 id/版本/行数/主指标 | READ · 评测集检索 |
| `kb.list` | 短 | — | 知识库 id/文档数/黄金 QA | READ · RAG 资产列表 |
| `report.get` | 短 | `report_id` | 指标摘要 + 下载路径 | READ · 报告在对话中解读 |
| `task.create` | 短 | 确认卡 TaskSpec JSON | `task_id`, `status` | WRITE · 下单推入调度队列 |
| `task.cancel` | 短 | `task_id`, `reason` | `ok: true` | WRITE · 任务取消分流 |
| `dispatch.overview` | 短 | — | Worker 节点数/CPU负载/策略 | READ · 调度大盘感知 |

#### 5.5.2 智能体 4 大核心内置技能 (Skills)

1. **`skill-benchmark`（基准对比）**：自动识别被测模型数量、推荐标准评测集并构建先评后压 TaskSpec；
2. **`skill-rag`（RAG 质量评估）**：自动装载知识库切块与黄金 QA，评测 LightRAG 4 模式检索表现；
3. **`skill-testcase`（PRD 用例生成）**：按 6 大策略精细配比（40/25/15/10/5/5）提炼测试用例；
4. **`skill-stress`（共享容量压测）**：继承父任务 endpoint 与抽样问答，定位 SLA 拐点与成本开销。

错误码：`UNAUTHORIZED` `VALIDATION` `NOT_FOUND` `BUDGET_EXCEEDED` `CONCURRENCY` `WHITELIST` `NEED_APPROVAL` `UPSTREAM` `TIMEOUT` `INTERNAL`。

---

### 5.6 共享压测

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-ST-01 | 继承目标 | P0 | M4 | **Benchmark / 外部 RAG**：URL、Header、协议来自父任务协议档；body 用父任务抽样最多 50 条 `question` 轮询，包成该协议请求。**内置 LightRAG**：压 Compose 内网 `query` HTTP（不是 Chat Completions），body 按父任务 `rag_mode` 组装 |
| F-ST-02 | 指标 | P0 | M4 | 模型：QPS、RT、错误率、TTFT、TPOT、tokens/s（SSE）。RAG：QPS、RT、错误率（非流式可不记 TTFT） |
| F-ST-03 | 面板与停止 | P0 | M4 | 任务页与 Agent 进度区展示 QPS/RT/错误率曲线；取消压测 **立即** 停发（与评测的协作式取消不同） |
| F-ST-04 | `/metrics` | P0 | M4 | 内网；Basic 或 IP 白名单；前缀 `ai_eval_stress_`；label `env,model,task_id`；任务结束后 10min 内停止该 task 序列 |
| F-ST-05 | 安全 | P0 | M4 | env 必填；host 白名单；默认 QPS≤500、时长≤30min；错误率 60s≥50% 停；`prod` 会签 |
| F-ST-06 | 拐点与 SLA | P0 | M4 | 未填 `sla_p99_ms` 不出「是否达标」；填了则拐点=首次 P99>SLA 或错误率≥1% |
| F-ST-07 | 费用 | P0 | M4 | 用父任务 usage 单价估算压测窗口费用（管理员配单价 /1k tokens） |

V1 压测内核：**go-stress-testing**（Apache-2.0）扩展，独立 `stress` 容器，由 worker 下发任务；指标契约见上。不在 api 进程内用 Python 替代（询问中未改内核）。

**验收（M4）**：test 白名单地址，质量成功后自动压 2 分钟；平台曲线与 Grafana 同 `task_id`；无白名单无法 running。

---

### 5.7 通用

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-CM-01 | 任务中心 | P0 | M1 | 列表筛选状态/kind；日志=task_events |
| F-CM-02 | 报告 | P0 | M2 | 对比：profile + dataset/kb 版本 + 时间；导出 Markdown；分享 7 天 |
| F-CM-03 | 账号 | P0 | M1 | 2.1 |
| F-CM-04 | 审计 | P0 | M1 | 登录失败、Key、基线、白名单、prod、角色 |
| F-CM-05 | 通知 | P1 | M4 | 终态、退化、会签；企微/邮件/出站 Webhook，管理员配开关 |
| F-CM-06 | 预算 | P0 | M2 | 单任务 `max_usd`（默认 5）；累计 usage 超限停；`BUDGET_EXCEEDED` |
| F-CM-07 | 文件 | P0 | M1 | 本地卷 `./data/files/{id}`；PG 存路径与 sha256 |
| F-CM-08 | Open API | P1 | V1.1 | |

---

### 5.8 前端信息架构（Vue3 + Naive UI / 原型工作台）

| 路由 | 页 | 功能说明 | 角色 |
| --- | --- | --- | --- |
| `/login` | 登录 | 居中登录卡、统一错误提示（不区分用户或密码）、首登强制改密 | 成员（全员） |
| `/agent` | 智能体 | 会话列表、对话流式交互、思考卡、工具卡、TaskSpec 确认卡、底部吸附进度坞、内嵌迷你调度视图 | 成员 |
| `/dispatch` | 调度中心 | 调度内核雷达、分发策略切换、并发容量滑块、Task 队列 → Worker 节点平滑三次贝塞尔连线拓扑、调度日志流 | 成员 |
| `/tasks` | 任务中心 | 六态徽章、24h 吞吐面积图与状态分布分段条、多维筛选、AI 智能编排、任务详情抽屉与事件时间线 | 成员 |
| `/reports` `/reports/:id` | 评测报告中心 | 独立一级导航；支持 Benchmark 多协议横向对比/基线Δ/Judge裁判分、RAG LightRAG 4模式召回对比、压测多轴曲线与 SLA 拐点、先评后压双向穿透横幅 | 成员 |
| `/datasets` | 数据集工作台 | 目录树结构管理、自定义列管理（+新增列）、单元格行内即点即改、多行/JSON 弹窗编辑器、AI 智能合成新数据与补全缺失行 | 成员 |
| `/cases` | 用例工作台 | 用例集目录树、6 大测试策略分布与自检横幅、用例表格行内编辑、AI 智能从 PRD 生成用例集、批量映射至基准数据集/黄金 QA、72h 倒计时确认入库 | 成员 |
| `/kb` | 知识库与切块检索 | 文档分块预览、2D 向量投影散点图、Top-K 相似度召回连线与重排前后位次对比 (Rerank Delta)、黄金 QA 维护 | 成员 |
| `/admin/profiles` | 协议档治理 | 三大协议（`openai_chat`、`openai_responses`、`anthropic_messages`）维护、Key 只写不回显、连通性检查 | 成员 |
| `/admin/stress` | 压测治理 | 白名单维护、QPS/时长上限、默认预算、单价并发控制、AI 参数推荐 | 成员 |
| `/admin/users` | 账号协同 | 成员开户、停用、重置密码（系统安全保底：不可停用最后一名正常账号） | 成员 |

全站顶栏居中常驻「大模型 / RAG」双模式切换器，全站智能体、任务表、用例映射、知识库与评测发起抽屉自动联动适配。

无独立「改系统提示词」页。

---

### 5.9 REST 一览（V1，均需登录）

`POST /api/auth/login` `POST /api/auth/logout`  
`GET/POST /api/users`（管理）  
`GET/POST /api/files`  
`CRUD /api/profiles`（Key 只写）  
`CRUD /api/datasets` `CRUD /api/case-sets` `POST .../confirm`  
`CRUD /api/kb` `POST /api/kb/{id}/docs` `CRUD /api/gold-qa`  
`POST /api/tasks` `GET /api/tasks` `GET /api/tasks/{id}` `POST /api/tasks/{id}/cancel` `POST /api/tasks/{id}/rerun`  
`GET /api/reports/{id}` `POST /api/reports/{id}/share`  
`GET /api/admin/settings` `PUT /api/admin/settings`  
`POST /api/auth/ws-ticket` `GET /ws/agent?ticket=`

---

## 6. 技术架构

### 6.1 栈

FastAPI（REST + WS）+ worker 进程 + PostgreSQL + Vue3/Naive/Vite + LightRAG 容器 + **stress（go-stress-testing 扩展）**。压测进程暴露 `/metrics`，Compose 固定端口供现有 Prometheus 抓取。

### 6.2 协议适配

内部：`{messages, temperature, max_tokens}` → 适配器 → `{text, usage{prompt,completion}, raw, latency_ms}`。

| 类型 | 请求 | 鉴权 |
| --- | --- | --- |
| `openai_chat` | `POST {base}/v1/chat/completions`，`messages` | `Authorization: Bearer` |
| `openai_responses` | `POST {base}/v1/responses`，`input` 由 messages 转换 | 同上 |
| `anthropic_messages` | `POST {base}/v1/messages`，`system` 拆出，`messages` 仅 user/assistant | `x-api-key` + `anthropic-version: 2023-06-01`（可配） |

被测评测：**非流式**。压测：对 chat/responses 解析 SSE 以算 TTFT。适配失败归 `UPSTREAM`，raw 截断入库（≤32KB）。

每种协议至少 2 个夹具单测（成功 + 4xx）。

### 6.3 架构图

```
浏览器 Vue3
  /agent  ──WS── FastAPI Agent Host（短 MCP + task.create）
  其它页 ──REST─┘
                    │
                    ▼
              PostgreSQL tasks
                    │
                    ▼
              worker（长 MCP：评测 / RAG / 生成用例；压测下发到 stress）
                 │         │              │
                 ▼         ▼              ▼
           三协议适配   LightRAG      go-stress-testing
                         /外部 Chat        /metrics
                                            ▼
                                    现有 Prometheus
```

### 6.4 表

`users, sessions, messages, ws_events, protocol_profiles, settings, files, datasets, dataset_rows, case_sets, cases, case_maps, kbs, kb_docs, gold_qa, tasks, task_events, eval_items, baselines, reports, share_links, audit_logs, usage_ledger`。

### 6.5 开源

testcase-tools：只对齐，不进镜像。LightRAG：MIT，锁 tag。go-stress-testing：Apache-2.0，二次开发保留 NOTICE。

---

## 7. 里程碑与验收

| 阶段 | 交付 | 演示门禁 |
| --- | --- | --- |
| M1 | Compose、账号、协议档、WS、确认卡、任务状态机、短 MCP、文件 | 登录后对话下单空跑任务（kind 可 mock succeeded）；断线按 event_id 续；管理员加协议档 |
| M2 | 真调用、规则分、对比、基线、用例 Skill、表单、预算 | 5.2.3 |
| M3 | LightRAG、外部 Chat RAG、黄金 QA、Hit Rate | 5.3.2 |
| M4 | 先评后压、白名单、Grafana、解读、通知 | 5.6 验收 |

---

## 8. 非功能

| 项 | 要求 |
| --- | --- |
| 性能 | ≤1k 样本且被测稳定 ≥5 QPS → 规则评测 ≤30min；中等 PRD 用例 ≤5min |
| 稳定 | 断点：评测按样本行号续跑；可用性 99%/月 |
| 安全 | Key 加密（KMS 或本地 Fernet，密钥来自环境变量）；WS 使用短票 `ws_ticket`；`/metrics` 不暴露公网 |
| 成本 | usage_ledger + 任务预算 |
| 兼容 | 被测仅 HTTP 三协议；导出 xlsx / xmind 8+ |

---

## 9. 风险

| 风险 | 应对 |
| --- | --- |
| 三协议字段差 | 夹具单测 |
| 并行打爆 API | 平台并发 + 预算 |
| 映射失败 | 待补全；可手传 JSONL |
| LightRAG 升级 | 锁 tag |
| 压测误伤 | F-ST-05 |
| 抓取失败 | M4 对齐网络；默认 job/前缀已写死 |
| 用例确认悬挂 | 72h 自动取消 |

---

## 10. 复查记录（V1.6）

### 10.1 已修缺陷

| 原问题 | 处理 |
| --- | --- |
| Agent 与 worker 都像在跑长任务 | 3.1 明确：Agent 只入队 |
| 无状态机、用例确认会卡死流水线 | 3.3 + 72h 超时 |
| MCP 名与流程不一致（`report.build`） | 统一 5.5 |
| 确认卡、WS、REST、页面缺失 | 5.1.2 / 5.1.3 / 5.8 / 5.9 |
| 评测无并发/超时/抽样 | 5.2.2 |
| Hit@K、doc 命中规则不清 | 5.3.1 |
| 压测 body 从哪来 | F-ST-01 抽样轮询 |
| 通知写在 M3、能力在 M4 | 报告 M3 标红，通知 M4 |
| 预算/并发只有风险没有功能 | F-CM-06、3.4 |
| 协议只有路径无鉴权头 | 6.2 |
| 无验收门禁 | 各模块 + 第 7 节 |
| 引导管理员、密码、分享 | 2.1 |
| 压测 Go/Python 摇摆 | V1.6.2 **改回 go-stress-testing**（与询问/初稿一致，未再征询 Python） |

### 10.2 复查（V1.6.1）又修

| 问题 | 处理 |
| --- | --- |
| `kind` 既有 `benchmark+stress` 又有 `with_stress` | 一任务一种 kind，压测用 `with_stress` 派生子任务 |
| 流程暗示 Benchmark 与 RAG 同单混跑 | V1 禁止；连续两张确认卡 |
| LightRAG 怎么 query 未写 | 原生 `query` API，再映射内部结构 |
| REST `/tasks` 与 `/api/tasks` 不一 | 统一 `/api` |
| WS 长期 token 进 query | 短票 `ws_ticket` |
| 管理员不能取消他人任务 | RBAC 已补 |
| 黄金 QA 无版本 | 覆盖上传 +1 |
| 成功指标 3 个模型 vs 功能 5 个 | 统一 1–5 |

### 10.3 仍接受的限制

- MCP 完整 JSON Schema 开会时出。
- Prometheus 抓取网段依现网。
- Judge 不强制与被测不同模型。
- 无 Open API、无分布式压测。

---

## 附录 A  用例策略

对齐 [testcase-tools](https://github.com/Rue1218/testcase-tools) 公开策略：正向 / 反向 / 边界 / 等价 / 状态 / 场景；P0–P3。自研，不引入源码。

---

## 附录 B  问答复核（V1.6.3）

后答覆盖先答。未询问、由文档补的实现细节标「补全」，不是你的选项。

| 你的结论 | PRD | 一致？ |
| --- | --- | --- |
| 三模块：Agent（MCP+Skill）/ Benchmark / RAG，压测共享 | 1.2、1.6 | 是 |
| OpenAI Chat Completions + Responses + Anthropic Messages | 1.3、6.2 | 是 |
| Agent 主、表单辅 | 1.2、F-AGT-07 | 是 |
| 内部 MCP，Agent 当 Host | 1.6、3.1 | 是（长任务由 worker 调同一 MCP，避免 WS 绑死，询问未单独选） |
| 压测目标：模型推理 + RAG query，不压平台 | 4.2、5.6 | 是 |
| 评测 Skill + 用例生成 Skill | 5.4 | 是 |
| Agent/Judge 三种协议可切换，另配裁判 | F-AGT-06、F-BM-08 | 是 |
| PG 任务表 + worker，WS 只推进度 | 3.1、6.1 | 是 |
| RAG：LightRAG + 外部 HTTP | 5.3 | 是 |
| 外部 RAG 契约：仅 OpenAI Chat（后答覆盖「也可 Anthropic RAG」） | F-RAG-02 | 是（以最后一问为准） |
| 压测进现有 Grafana（后答覆盖「不对接」） | F-ST-04 | 是 |
| 自建账号 | 2.1 | 是 |
| FastAPI + Vue3 Naive UI | 文头、6.1 | 是 |
| WS 自定义事件流 | 5.1.3 | 是 |
| 单机 Compose | 1.3 | 是 |
| 多会话、会话内串行、会话间可并行 | 1.5、3.4 | 是 |
| 先评后压 | 3.2 | 是 |
| 文件本地盘 | F-CM-07 | 是 |
| Key 管理员池 | 1.6 | 是 |
| LightRAG 进同一 Compose | F-RAG-01 | 是 |
| 不内置公开集 | 1.3 | 是 |
| 固定人设，不改系统提示词 | F-AGT-05 | 是 |
| 单团队；先文本后多模态 | 1.2、4.2 | 是 |
| 不涉密、不强制私有化 | 1.6 | 是 |
| 报告不进审批 | 1.6、4.2 | 是 |
| 用例不同步禅道/Jira | 1.6 | 是 |
| 接受 testcase-tools 自研对齐 | 附录 A | 是 |
| 压测内核 | 曾误写 Python，**已改回 go-stress-testing** | 已纠正 |

询问中未出现、文档自行补全（可改）：一任务一种 kind、预算默认 5 USD、平台并发默认 3、用例确认 72h、ws_ticket、Hit@K=5、prod 会签、通知渠道（企微/邮件/Webhook）。

### 本版（V1.6.3）相对问答仍无冲突的说明

- 「Agent 调 MCP」：Host 仍是 Agent；长任务进 PG 后由 worker / stress 执行，避免对话断线任务停。与「PG 队列 + worker」那一问一致。
- 外部 RAG 只用 OpenAI Chat：以最后一问为准；被测/Agent/Judge 仍是三协议。
- 压测 Grafana：以「需要接入」为准，覆盖更早的「不需要」。

### 会话上下文持久化修订（2026-08-20）

思考卡、工具/MCP 卡、技能徽标、确认卡及其回执均通过 `ws_events` 或会话状态保存；
流式增量仍为瞬态，成功回合额外保存 `thought.stream=think_final` 完整思考快照。
历史接口同时返回 `compact_summary` 与服务端 ContextMeter，刷新不得依赖浏览器临时状态。
