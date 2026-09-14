# AI 测试与评估平台 PRD

> ⚠️ **文档维护提示（2026-09-11）**：本文部分章节含历史实现引用（`agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除，ReAct / Plan-Solve 图已由 AgentLoop v2 取代）；当前实现与契约以 `AGENTS.md` 状态地图及本文最新修订为准。

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.21 |
| 文档状态 | 冻结基线 + V1.21 登记（2026-09-14：按用户要求补充专家提示词受控管理与草稿保护） |
| 撰写日期 | 2026-08-17 |
| 本轮修订 | 2026-09-09：V1.20 删除 OpenAI Responses 协议档及适配器；迁移同时删除该档环境凭据、历史密文和失效 Agent 默认引用。V1.19 废除首次登录强制改密（产品决策）：开户/重置密码/引导账号不再强制首登改密，账号可自助在右上角「修改密码」更新凭据；密码强度规则（≥8 位含字母与数字）不变。2026-08-31：V1.18 收敛 Agent 对话投影：Plan 只用 PlanCard，工具只用 ToolCard，危险 bash 只用确认卡；ReAct `thought`、Plan/Reflect 阶段、工具调用前草稿均属于内部控制，禁止出现在对话或历史重放。最终回答只能在真实工具终态之后展示。 |
| 最近修订 | 2026-08-31：V1.17 增加危险 bash 的 LangGraph 人在回路：风险命令必须弹出确认卡，原发起成员确认后才进入 bwrap 沙箱；拒绝不执行。思考卡只呈现过程摘要，禁止显示会与工具真实结果冲突的原始推理。2026-08-30：V1.16 增加受控 Agent 技能文件与协议档专属补充提示词管理；技能正文遵循渐进式披露，核心安全提示词不可覆盖。2026-08-28：V1.15 统一基准目录治理、独立导入队列、staging 并发发布、成员同权双人复核与 M3 里程碑；冻结任务必须锁定数据集/黄金集版本。2026-08-28：V1.14 新增基准数据集目录、异步导入、staging 表格和发布门禁；下载/解析仅由 Worker 执行，未审核行不得评测。2026-08-24：补充 Agent 多附件交互：支持图片（PNG/JPG/JPEG/WEBP/GIF）、Markdown/TXT/HTML/JSON/YAML、PDF、Word（DOC/DOCX）、Excel（XLS/XLSX）、CSV/JSONL 与音频；输入区支持文件选择和拖拽上传，图片显示缩略图，PDF/文本支持预览，Office 文件显示类型卡片并可打开/下载。2026-08-23：补齐 Gemini OpenAI 兼容端点的思考摘要请求与增量归一化；增加 Agent 思考摘要开关与思考强度设置；将用户回显固定为 `user_message`，将完成信号固定为 `response.completed`，明确 `thought` 不承载助手正文；协议档增加可选 Embedding / Reranker 独立端点配置，三类 Key 均按 profile 写入受控环境文件 |
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
| V1.7.1 | 2026-08-21 | 协议档支持可选 Embedding / Reranker 的 URL、模型标识与 Key；Key 只写不回显 |
| V1.8 | 2026-08-23 | Agent 运行基线切换为 LangGraph；首期只交付单轮模型调用与 WebSocket 流式链路，Harness、MCP、确认卡与长任务保持后续阶段 |
| V1.9 | 2026-08-23 | 拆分用户消息、思考摘要、助手正文增量、助手最终消息和 done 事件，明确 `pong` 为独立心跳 |
| V1.10 | 2026-08-23 | 用户回显使用 `user_message`，助手正文使用 `assistant_delta` / `assistant_message`，回合结束使用 `response.completed`，`thought` 严禁承载助手正文 |
| V1.11 | 2026-08-23 | Agent 后台增加思考摘要开关与 `low/medium/high/xhigh/max` 强度；不改变 WebSocket 公共头与正文事件语义 |
| V1.12 | 2026-08-23 | Gemini OpenAI 兼容流式请求增加 `include_thoughts` 与强度映射；思考摘要仍通过 `thought` 事件独立展示 |
| V1.14 | 2026-08-28 | 基准数据集页新增受控目录筛选、异步制品导入、staging 表格预览和审核发布门禁；不做社交媒体抓取 |
| V1.15 | 2026-08-28 | 补齐目录/release 双人复核、导入队列租约与重试、staging 版本号发布和版本锁定；将该能力与 RAG 黄金集统一收敛至 M3，代码题继续不做 |
| V1.16 | 2026-08-30 | Agent 技能文件统一规格、渐进式加载、管理端预览/编辑及协议档专属补充提示词；核心安全提示词继续固定 |
| V1.17 | 2026-08-31 | 危险 bash 先弹人工确认卡再执行；推理仅呈现过程摘要，工具结果是唯一执行事实 |
| V1.18 | 2026-08-31 | ReAct / Plan-and-Solve / reflect 的内部过程不再生成对话卡；只显示 Plan、工具、确认与真实最终结果 |
| V1.19 | 2026-09-09 | 废除首次登录强制改密；账号自助改密入口保留（右上角「修改密码」），密码强度规则不变 |
| V1.20 | 2026-09-09 | 协议档收敛为 OpenAI Chat 与 Anthropic Messages，删除 OpenAI Responses 适配与已有档位凭据 |

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

面向**单一团队**。主入口是 **WebSocket Agent**；表单为辅。产品目标是由 LangGraph Agent 组合 Harness 后作为 **MCP Host**，只调短工具并 `task.create`；当前首期先交付单轮模型调用与 WS 流式基础链路，MCP 与任务下单暂不启用。三个模块 + 共享压测：

| 模块 | 职责 |
| --- | --- |
| A. Agent | 会话、拆解、确认卡、进度；**不执行长任务** |
| B. Benchmark | 自定义文本集、两类协议调用、规则评分 / Judge、对比与基线 |
| C. RAG | Compose 内 LightRAG，或外部 **OpenAI Chat Completions** RAG HTTP |
| 共享压测 | 质量成功后压同一推理 / query 接口；平台面板 + Prometheus scrape |

### 1.3 目标

1. 对话完成：用例（可选）→ Benchmark 和 / 或 RAG →（可选）压测 → 报告。
2. 兼容 `openai_chat`、`anthropic_messages`；Agent / Judge / 被测均可切换。
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
| 协议档 | `openai_chat` / `anthropic_messages` 之一 + 主模型 base_url/模型名/Key；可选 Embedding、Reranker 各自 base_url/模型名/Key，均写入受控环境文件 |
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

### 1.7 Agent 运行基线（V1.8）

当前首期实现以以下链路为唯一事实源：

```text
WebSocket 短票
  -> LangGraph Agent Graph（单轮）
  -> ModelGateway（LangGraph 模型调用图）
  -> 两类协议适配器
  -> user_message / thought / assistant_delta / assistant_message / response.completed / error / pong
```

- `app/agent/graph.py` 只编排一次模型调用，不持有数据库、WebSocket、工具或任务状态；
- `app/llm/` 只负责 `ModelRequest`、`ModelResponse`、两类协议适配与流式事件，不承载 Harness；
- `app/routers/ws.py` 负责短票、会话事件、后台 Task 和流式 WS 投影，收包循环不得等待整轮模型调用；
- 首期支持 `user_message(role=user)`、`thought` 思考摘要、`assistant_delta` 正文增量、`assistant_message` 最终交付句和 `response.completed` 结束信号；`pong` 为独立应用层心跳；`message` 不再作为新用户回显事件；
- Harness、ReAct/MCP、人工确认、任务取消、长任务队列和记忆层属于后续设计，不得在首期代码中提前实现。

本节是对“最终产品能力”和“当前实现阶段”的区分：下文 M2–M4 的任务、MCP、确认卡和评测闭环仍是产品目标，但在首期 Agent 基础链路稳定前不宣称已交付。

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

首次部署：环境变量创建初始成员账号。密码 ≥8 位，含字母和数字。浏览器会话使用 HttpOnly Cookie（12h 可续）。WebSocket 连接使用 5 分钟短票（ticket），见 F-AGT-01。（V1.19 修订：不再强制首次改密——账号可自主在右上角「修改密码」更新凭据。）

#### 2.1.1 数据资产治理（不新增 RBAC）

目录、release、导入和发布仍由同一个 `member` 角色执行；“提报人”“审核人”是某一次操作的审计身份，不是永久角色或权限等级。这样既保持全员同权，也避免同一人对自己的来源、许可证和数据行作无复核发布。

| 治理动作 | 执行规则 | 必须记录的审计信息 |
| --- | --- | --- |
| 新建目录来源、登记 release、发起允许的导入 | 任一正常成员可执行 | actor、对象 ID、来源/release manifest 哈希、原因、时间 |
| 审核并批准 release、审核并发布 staging、确认许可证例外 | 审核成员必须与该 release/导入的提报成员不同；同一成员不得审批自己的提交 | 提报人与审核人、前后状态、许可证证据引用、审核意见、冻结版本 ID |
| 暂停或封禁 release | 任一正常成员可立即暂停新的导入以止损；另一成员必须复核为 `blocked` 或恢复 | 暂停原因、影响版本、复核结果与时间 |
| 撤销正式版本 | 任一正常成员可提交撤销；另一成员复核后将旧版本置为 `deprecated`，历史报告只读保留 | 版本 ID、内容/manifest 哈希、撤销原因、两名操作者 |

系统初始化账号、运行并发上限和密钥托管是运维配置，不授予数据资产的单人发布豁免。所有上述操作均写入 `audit_logs`；浏览器和模型上下文不得获得下载令牌、授权文件正文或未脱敏上游响应。

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
| Agent（WS 进程） | 当前仅调用 LangGraph 单轮模型图；后续可由 Harness 组合短工具并写「待执行」任务 | 自己跑完 Benchmark/RAG/压测 |
| Worker | 评测 / RAG / 用例生成 MCP；`stress.run` 只负责向 stress 容器下发 | 向用户闲聊；自己打满压测连接 |
| 表单 REST | 直接 `POST /api/tasks`，状态与 Agent 下单相同 | — |

这样 WS 断开不影响后续异步执行；确认卡只决定「是否入队」。当前首期尚未启用确认卡和任务下单，WS 只完成单轮文本生成与事件持久化。

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

三模块、共享压测、两类协议、内部 MCP、用例/评测 Skill、Naive UI 工作台、Compose 六件套（含 stress）、Grafana scrape、预算与并发。

### 4.2 外

外部 MCP、改系统提示词、多租户、多模态、未经目录审核的预置公开集、TMS 同步、通用审批流（目录/release 双人复核除外）、强制私有化、压平台自己、评测与压测并行、被测走 WS、HumanEval 沙箱、分布式压测、Open API（V1.1）。

---

## 5. 功能需求

### 5.1 模块 A — Agent

#### 5.1.1 功能表

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-AGT-01 | WS 会话 | P0 | M1 | 登录后发 5 分钟 `ws_ticket`，`GET /ws/agent?ticket=` 升级（不用长期 JWT 进 query）。心跳 30s；重连带 `session_id`+`last_event_id` |
| F-AGT-02 | 事件流 | P0 | M1 | 见 5.1.3 |
| F-AGT-03 | MCP Host | P0 | 后续阶段 | 目标是只连内部 Server；短工具同步，长任务只 `task.create`；首期保持能力未启用 |
| F-AGT-04 | 确认卡 | P0 | 后续阶段 | 见 5.1.2；未确认不入队；首期不生成确认卡 |
| F-AGT-05 | 人设与技能治理 | P0 | 后续阶段 | 核心系统提示词由 Harness 固定生成；每个 Agent 协议档预留独立补充提示词入口，内置技能以统一 `SKILL.md` 受控预览/编辑，均需审计 |
| F-AGT-06 | Agent 后端 | P0 | M1 基础 | 管理员指定一个协议档；LangGraph 单轮调用默认读取最近 20 条用户/助手消息；系统提示词与复杂上下文策略留后续 |
| F-AGT-07 | 表单双入口 | P0 | M2 | `POST /api/tasks` 与确认卡字段一致 |
| F-AGT-08 | 解读 | P1 | M4 | 仅对已有 `report_id` 调评测 Skill，不重跑评测 |
| F-AGT-09 | 取消 / 重跑 | P0 | M1 | 工程师取消自己的非终态任务；管理员可取消任何人的。评测取消=当前样本结束后停；**压测取消=立即停发**。重跑=新任务拷配置 |
| F-AGT-10 | 团队共享与软删除会话 | P0 | M1 基础 | 默认私有；会话创建者可切为 `team`，在线协作者实时看到用户消息与 AI 正文 chunk；删除为软删除，运行中的 Agent 回合、待确认卡或非终态任务必须先结束 |

#### 5.1.1.1 Agent 技能与 Prompt 管理边界

内置任务技能统一存为 `skills/<skill_id>/SKILL.md`，头部固定 `id`、`name`、`kind`、`version`、`enabled`、`summary`，正文固定以 `## 工作流` 开始。系统提示词常驻的仅是技能目录摘要；仅当本轮计划选中技能后，Harness 才读取该技能全文。读取技能前必须验证目标 `SKILL.md` 存在；缺失或规格不合法时不得降级为硬编码工作流。

管理端可预览和编辑已登记的 Skill 文件，写入必须采用修订指纹并发保护、原子替换和不含正文的审计记录。每个 `agent` 用途的协议档预留独立 Prompt 管理入口：核心角色/安全/任务状态机提示词始终只读且优先，管理员只能维护该协议档的补充提示词。普通会话中的文件工具始终限制在会话工作区，不得读取或写入运行时 Skill/Prompt 配置。

V1.21（2026-09-14，按用户要求登记）：Agent 技能页同时列出本轮专家目录，支持已登记专家的专属提示词查看、编辑与恢复内置；通用助手无专属段时只展示说明。专家配置与协议档补充层独立，保存需修订指纹并发保护和无正文审计，下一个回合生效，不能改变核心策略与工具授权。恢复内置先进入草稿、保存后生效；保存失败保留草稿，不允许静默覆盖其他成员的修改。

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

#### 5.1.2.1 危险工具确认卡（P0）

`bash` 不是任务确认卡：它只处理会话工作区内的短命令。删除、覆盖、移动、权限变更，或无法静态证明只读的命令，必须在任何副作用前暂停并展示 `ToolApprovalCard`。卡片必须显示待执行命令、风险原因与沙箱边界；仅命令原发起成员可选择“确认执行”或“拒绝”。确认后才允许 Runner 在 bwrap 中执行；拒绝后命令不得执行，并把 ToolCard 标为“已拒绝”。`sudo`、网络和远程连接命令不属于可确认范围，必须保持硬拒绝。

思考卡每回合至多一张，只描述“正在分析/校验”这类固定过程状态，不得展示模型原始推理、未执行动作或任何“已成功”结论。ReAct JSON 的 `thought`、Plan-and-Solve / reflect 阶段状态以及带 ToolCall 响应中的正文草稿均为内部控制信息，禁止生成卡片或回放。工具的 `tool_result.ok=true` 才是可向用户陈述已执行成功的唯一事实来源。

#### 5.1.3 WS 事件

公共头：`event`, `session_id`, `task_id?`, `event_id`（单调）, `ts`。

| event | payload 要点 |
| --- | --- |
| `thought` | 当前回合最多一条固定过程摘要；不得含阶段、推理原文或业务结论，历史 UI 不重放 |
| `user_message` | 已持久化用户消息、作者与浏览器幂等键；协作者即时补气泡 |
| `tool_call` | `name`, `arguments` |
| `tool_result` | `name`, `ok`, `data` 或 `error`；用户拒绝危险工具时 `status=rejected` |
| `tool_approval` | 危险 bash 的命令、风险、沙箱边界与可选决定；命令尚未执行 |
| `tool_approval_ack` | 原发起成员的 `approve` / `reject` 回执；确认才恢复原 ToolNode |
| `confirm` | 确认卡 JSON，等前端 `confirm_ack` |
| `progress` | `percent?`, `done`, `total`, `message` |
| `report` | `report_id` |
| `error` | `code`, `message`（可给用户看） |
| `pong` | 心跳 |

前端 → 服务：`user_message` `{text, attachments[]?, client_message_id?}`，`confirm_ack` `{ok, patch?}`，`cancel_task` `{task_id}`，`clarify_reply` `{id, answer}`，`tool_approval_ack` `{id, action:"approve"|"reject"}`。

`assistant_delta` 只在在线时即时广播，断线不回放；含 ToolCall 的上游响应不得下发正文草稿。`thought.stream=think` 仅发给本轮发起连接，不向团队协作者泄露；`think_final` 只保留固定摘要且历史 UI 不重放。`assistant_message` 只保存已验证的最终交付句，`response.completed` 标记本轮结束。

当前已实现事件以 API 契约为准：`tool_call`、`tool_result`、`tool_approval`、`tool_approval_ack`、`plan`、`confirm`、`confirm_ack`、`progress` 与 `report` 均按各自状态机处理。任何未启用能力必须返回 `VALIDATION`，不得伪造任务或工具成功。

附件：先 `POST /api/files` 得 `file_id`，再在消息里引用。单文件 ≤20MB；支持图片（PNG/JPG/JPEG/WEBP/GIF）、PRD/OpenAPI/Markdown/TXT/HTML/JSON/YAML、PDF、Word（DOC/DOCX）、Excel（XLS/XLSX）、JSONL/CSV 与 wav/mp3。Agent 输入区支持多选和拖拽上传；本地暂存阶段图片显示缩略图，PDF/文本支持预览，Office 文件显示文件类型卡片并可打开/下载。

---

### 5.2 模块 B — Benchmark

#### 5.2.1 功能表

| 编号 | 功能 | 优先级 | 交付 | 说明 |
| --- | --- | --- | --- | --- |
| F-BM-01 | 协议档 CRUD | P0 | M1 | 见 6.2；主模型及可选 Embedding / Reranker 端点配置，三类 Key 只写不回显，审计变更 |
| F-BM-02 | 统一调用 | P0 | M1 | 入 `messages`，出 `text,usage,raw,latency_ms` |
| F-BM-03 | 数据集 | P0 | M2 | JSONL/CSV UTF-8；列 `question,reference,context?`；导入/编辑先写 `draft` 或 staging，审核发布才生成可评测版本；单集 ≤50MB、≤2 万行 |
| F-BM-04 | 用例入集 | P0 | M2 | 5.4.2；待补全不评分 |
| F-BM-05 | 规则评分 | P0 | M2 | 每集选一种主指标：exact / contain / regex / rouge_l / bleu；默认 contain |
| F-BM-06 | 多模型 | P0 | M2 | 1–5 个 profile；报告并排 |
| F-BM-07 | 基线 | P0 | M2 | 成员冻结某次 succeeded；同 dataset 版本+主指标才能对比 |
| F-BM-08 | Judge | P1 | M3 | 裁判协议档 ≠ 被测（警告，不强制）；1–5 分 + 理由 |
| F-BM-09 | 代码题 | — | 不做 | |
| F-BM-10 | 基准目录与异步导入 | P1 | M3 | 仅展示双人复核的固定 release；独立 Worker 队列下载/校验/解析后写入带版本号的 staging 表格，非提报人审核原子发布前不得评分 |

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

#### 5.2.4 基准目录、导入与发布（M3）

`/datasets` 提供“导入公开基准”入口，只展示**来源与固定 release 均已复核批准**的目录条目。成员可按能力场景、任务族、语言、许可状态、测试标签可用性、评分器支持度、污染风险与预计规模筛选，并选择 release 明示的 split、subject/子集与目标数据集。页面不得提交任意 URL、Cookie、请求头、Token 或解析脚本；筛选字段、枚举值、默认值、最大行数和确定性排序均由目录 release 返回的 `filter_schema` 定义。

目录治理分为来源和 release 两层：成员先登记来源和固定 release manifest（官方地址、允许域名、revision、制品清单/哈希、许可证证据、允许 split、解析器与筛选 schema），另一成员审核后才可见、可导入。release 一经批准不可原地编辑；修订、许可证变化或上游制品变化必须新建 release。任一成员可暂停 release 阻止新导入，复核后再恢复或置为 `blocked`；被封禁 release 的正式版本只保留历史报告，不得新建任务。

提交后 API 只创建独立 `DatasetImport` 作业并立即返回；Worker 负责下载、哈希/许可证/格式校验、解压、解析、去重和 staging 写入，API 进程不得等待或执行这些耗时步骤。作业状态：`queued → downloading → validating → parsing → review_ready → published`，或转为 `failed | rejected`。作业有不可变导入 manifest、唯一请求指纹、尝试次数和租约；Worker 使用行锁领取，租约过期时回收重排，超过重试上限才置为 `failed`。同一 release manifest、切分、规范化过滤规则、解析器版本和目标数据集的重复请求必须幂等返回既有作业，禁止重复写行或由失效 Worker 覆盖新尝试结果。

当导入状态为 `review_ready`，目标数据集在左侧树和主表格中可见，主表展示该 `import_id` 的 staging 行、稳定行 ID、`staging_revision`、split、来源 release 和解析告警；这些行可审核修订，但不进入确认卡、任务分母或基线。表格编辑必须带回读取时的 `staging_revision`，成功编辑递增该版本号。由**非提报成员**点击“审核并发布”时，服务端锁住 import 与数据集，校验 `import_id + staging_revision + accepted_row_ids[]`，并在一个事务中冻结审核通过行、来源 manifest、制品/行内容哈希、解析器/评分器版本和审核记录为新的 `DatasetVersion`；过期 revision、重复发布或并发编辑返回 `CONCURRENCY`，不得按行号猜测选择。数据集容器可继续保持旧 `active_version_id`，新 staging 不影响正在运行任务；发布成功才原子切换新的 `active_version_id`，作业变为 `published`。`failed`/`rejected` 只保留最小审计与错误摘要。标准集的 `train` split 默认禁止导入；无公开 test 标签的条目只能导入 validation 并显著标记“非官方 test”。

创建 benchmark 任务时，服务端在同一事务读取数据集当前 `active_version_id` 并锁定为 `Task.config.dataset_version_id`；请求方不能指定、替换或在重跑时漂移到最新版本。Worker、报告、基线和重跑只读取该冻结版本。RAG 任务同理锁定 `gold_qa_version_id` 与 KB 文档快照。

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

平台最终采用 **MCP Host** 统一智能体架构。长任务由 Worker 异步执行；Agent 仅调用 MCP 短工具进行信息发现与 `task.create` 结构化建单。MCP 是后续 Harness 阶段能力，首期 LangGraph Agent 不注册或执行 MCP 工具。

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
| `/login` | 登录 | 居中登录卡、统一错误提示（不区分用户或密码）（V1.19 起不再首登强制改密） | 成员（全员） |
| `/agent` | 智能体 | 会话列表、对话流式交互、过程摘要卡、工具卡、危险 bash 确认卡、TaskSpec 确认卡、底部吸附进度坞、内嵌迷你调度视图 | 成员 |
| `/dispatch` | 调度中心 | 调度内核雷达、分发策略切换、并发容量滑块、Task 队列 → Worker 节点平滑三次贝塞尔连线拓扑、调度日志流 | 成员 |
| `/tasks` | 任务中心 | 六态徽章、24h 吞吐面积图与状态分布分段条、多维筛选、AI 智能编排、任务详情抽屉与事件时间线 | 成员 |
| `/reports` `/reports/:id` | 评测报告中心 | 独立一级导航；支持 Benchmark 多协议横向对比/基线Δ/Judge裁判分、RAG LightRAG 4模式召回对比、压测多轴曲线与 SLA 拐点、先评后压双向穿透横幅 | 成员 |
| `/datasets` | 数据集工作台 | 目录树结构管理、自定义列管理（+新增列）、单元格行内即点即改、多行/JSON 弹窗编辑器、AI 智能合成新数据与补全缺失行 | 成员 |
| `/cases` | 用例工作台 | 用例集目录树、6 大测试策略分布与自检横幅、用例表格行内编辑、AI 智能从 PRD 生成用例集、批量映射至基准数据集/黄金 QA、72h 倒计时确认入库 | 成员 |
| `/kb` | 知识库与切块检索 | 文档分块预览、2D 向量投影散点图、Top-K 相似度召回连线与重排前后位次对比 (Rerank Delta)、黄金 QA 维护 | 成员 |
| `/admin/profiles` | 协议档治理 | 两类协议（`openai_chat`、`anthropic_messages`）及可选 Embedding / Reranker 端点维护、Key 只写不回显、连通性检查 | 成员 |
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
| `anthropic_messages` | `POST {base}/v1/messages`，`system` 拆出，`messages` 仅 user/assistant | `x-api-key` + `anthropic-version: 2023-06-01`（可配） |

被测评测：**非流式**。压测：对 chat/responses 解析 SSE 以算 TTFT。适配失败归 `UPSTREAM`，raw 截断入库（≤32KB）。

每种协议至少 2 个夹具单测（成功 + 4xx）。

### 6.3 架构图

```
浏览器 Vue3
  /agent  ──WS── FastAPI WS Bridge
                    │
                    ▼
              LangGraph Agent Graph
                    │
                    ▼
              ModelGateway（LangGraph）
                    │
                    ▼
              两类协议适配器 / 上游模型

  其它页 ──REST─┐
                └── PostgreSQL（sessions / messages / ws_events / tasks）
                                      │
                                      ▼
              worker（后续长任务：评测 / RAG / 生成用例；压测下发到 stress）
                 │         │              │
                 ▼         ▼              ▼
           两类协议适配 LightRAG      go-stress-testing
                         /外部 Chat        /metrics
                                            ▼
                                    现有 Prometheus
```

### 6.4 表

`users, sessions, messages, ws_events, protocol_profiles, settings, files, dataset_catalog_entries, dataset_catalog_releases, dataset_catalog_reviews, dataset_source_artifacts, dataset_imports, dataset_import_attempts, dataset_import_rows, datasets, dataset_rows, dataset_versions, dataset_version_rows, case_sets, cases, case_maps, kbs, kb_docs, gold_qa, tasks, task_events, eval_items, baselines, reports, share_links, audit_logs, usage_ledger`。

### 6.5 开源

testcase-tools：只对齐，不进镜像。LightRAG：MIT，锁 tag。go-stress-testing：Apache-2.0，二次开发保留 NOTICE。

---

## 7. 里程碑与验收

| 阶段 | 交付 | 演示门禁 |
| --- | --- | --- |
| M1 | Compose、账号、协议档、LangGraph 单轮 Agent、WS 基础事件、会话回放、文件 | 登录后完成单轮流式对话；断线按 event_id 续；确认卡、短 MCP、任务下单进入后续 Harness 阶段 |
| M2 | 真调用、规则分、对比、基线、用例 Skill、表单、预算 | 5.2.3 |
| M3 | LightRAG、外部 Chat RAG、黄金 QA、Hit Rate、目录/release 双人复核、独立导入队列、staging 原子发布和任务版本锁定 | 5.3.2 + 5.2.4；仅支持当前 PRD 已列任务族，不含代码题 |
| M4 | 先评后压、白名单、Grafana、解读、通知 | 5.6 验收 |

---

## 8. 非功能

| 项 | 要求 |
| --- | --- |
| 性能 | ≤1k 样本且被测稳定 ≥5 QPS → 规则评测 ≤30min；中等 PRD 用例 ≤5min |
| 稳定 | 断点：评测按样本行号续跑；可用性 99%/月 |
| 安全 | 协议档 URL、模型 ID、API Key 按 profile 写入服务器受控环境文件（文件权限 0600、API 加锁刷新并 fsync、Worker 只读）；旧数据库密文仅迁移后清空；WS 使用短票 `ws_ticket`；`/metrics` 不暴露公网 |
| 成本 | usage_ledger + 任务预算 |
| 兼容 | 被测仅 HTTP 两类协议；导出 xlsx / xmind 8+ |

---

## 9. 风险

| 风险 | 应对 |
| --- | --- |
| 两类协议字段差 | 夹具单测 |
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
| 核心人设固定；协议档可维护受审计补充提示词 | F-AGT-05 | 是 |
| 单团队；先文本后多模态 | 1.2、4.2 | 是 |
| 不涉密、不强制私有化 | 1.6 | 是 |
| 报告不进审批 | 1.6、4.2 | 是 |
| 用例不同步禅道/Jira | 1.6 | 是 |
| 接受 testcase-tools 自研对齐 | 附录 A | 是 |
| 压测内核 | 曾误写 Python，**已改回 go-stress-testing** | 已纠正 |

询问中未出现、文档自行补全（可改）：一任务一种 kind、预算默认 5 USD、平台并发默认 3、用例确认 72h、ws_ticket、Hit@K=5、prod 会签、通知渠道（企微/邮件/Webhook）。

### 本版（V1.6.3）相对问答仍无冲突的说明

- 「Agent 调 MCP」：Host 仍是 Agent；长任务进 PG 后由 worker / stress 执行，避免对话断线任务停。与「PG 队列 + worker」那一问一致。
- 外部 RAG 只用 OpenAI Chat：以最后一问为准；被测/Agent/Judge 仅支持两类协议。
- 压测 Grafana：以「需要接入」为准，覆盖更早的「不需要」。

### 会话上下文持久化修订（2026-08-20）

思考卡、工具/MCP 卡、技能徽标、确认卡及其回执均通过 `ws_events` 或会话状态保存；
流式增量仍为瞬态，成功回合额外保存 `thought.stream=think_final` 完整思考快照。
历史接口同时返回 `compact_summary` 与服务端 ContextMeter，刷新不得依赖浏览器临时状态。

### 协议档多模型端点修订（2026-08-21）

协议档在主模型配置之外，可选保存 Embedding 与 Reranker 的独立 URL、模型标识和 API Key；
三类 Key 均只写入受控环境文件，不进入数据库或任何响应正文。

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/schemas.py` / `backend/api/app/profile_env.py` | 定义附加端点字段及按 profile 隔离的环境变量写入契约 |
| `backend/api/app/routers/profiles.py` / `backend/worker/app/profile_env.py` | CRUD 保存、脱敏返回与 Worker 只读解析 |
| `frontend/src/components/modals/ProfileModal.vue` / `frontend/src/views/AdminProfiles.vue` | 配置表单和协议档列表标识 |

### Agent 附件交互修订（2026-08-24）

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/files.py` | 扩展图片与 DOC/DOCX 上传白名单，继续执行单文件 20MB 校验 |
| `frontend/src/components/agent/AttachmentPreview.vue` | 提供图片缩略图、PDF/文本预览和 Office 文件类型卡片 |
| `frontend/src/views/Agent.vue` | 支持多选/拖拽上传、附件暂存、移除、上传状态与消息内展示 |
| `frontend/src/api/http.ts` | 同步文件上传响应的内容类型字段 |
| `backend/api/tests/test_files.py` | 增加附件扩展名白名单回归测试 |

### V1.15 修改代码文件与作用清单

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-PRD.md` | 统一成员同权双人复核、目录/release 生命周期、独立导入队列、staging 并发发布、版本锁定及 M3 边界 |
| `docs/AI测试与评估平台-API.md` | 定义目录治理、导入租约与重试、稳定 staging 行 ID/revision、原子发布和任务快照接口契约 |
| `docs/AI测试与评估平台-测试数据集与黄金集采集技术方案.md` | 细化来源 manifest、队列领取/回收、审计、发布事务和与 PRD 一致的分期实施方案 |

### V1.16 修改代码文件与作用清单

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/skills/files/*/SKILL.md` / `storage.py` | 统一内置技能文件规格、持久化副本、文件存在校验、头部按需读取和全文工作流延迟加载 |
| `backend/api/app/harness/skills/registry.py` / `workflows.py` | Skill Hint 从文件头部生成，选中技能后才加载正文 |
| `backend/api/app/routers/admin.py` / `agent_prompt_settings.py` | 受审计的 Skill 预览/编辑和协议档补充提示词管理接口 |
| `backend/api/app/harness/prompts/system.py` / `routers/ws.py` | 固定核心系统策略与协议档补充提示词装配，禁止设置项替换核心规则 |
| `frontend/src/views/AdminProfiles.vue` / `frontend/src/components/modals/*` | Agent 技能文件预览/编辑与当前 Agent 提示词管理入口 |

### V1.17 修改代码文件与作用清单

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/dispatch.py` / `feedback/rules.py` | 识别危险 bash、保留提权/网络硬拒绝，定义确认后才可执行的工作区修改范围 |
| `backend/api/app/harness/execution/toolnode.py` / `routers/ws.py` | 在 Runner 前执行 LangGraph 中断、持久化确认卡/回执并恢复同一图线程 |
| `backend/api/app/agent/react.py` / `agent/think_stream.py` | 收紧原始 reasoning 和工具前草稿正文，防止假性成功与过程卡堆积 |
| `frontend/src/components/agent/ToolApprovalCard.vue` / `ToolCard.vue` / `views/Agent.vue` | 提供确认/拒绝交互和 ToolCard 等待确认、已拒绝状态 |
| `frontend/src/api/ws.ts` / `api/types.ts` | 增加危险工具确认的 WS 上行/下行事件类型 |
| `backend/api/tests/test_bash_hitl.py` / `test_agent_react.py` / `test_stream_p3_integration.py` | 覆盖确认前不执行、拒绝不执行、ToolCall 草稿延迟投影和 bash 串行边界 |
| `docs/AI测试与评估平台-API.md` / `docs/AI测试与评估平台-Agent开发文档.md` | 固定 HITL 卡片、恢复、事件与过程输出契约 |

### V1.18 修改代码文件与作用清单

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/react.py` | 将 JSON ReAct `thought` 完全限制为内部控制字段；删除 ToolCall 前正文草稿投影，并在最终回合重新请求自然语言交付，防止把未执行动作说成结果 |
| `backend/api/app/harness/execution/dispatch.py` | 硬拒绝检测覆盖多段、嵌套 shell 与包装命令，确保 `bash -c "sudo …"` 等不会降级为可确认操作 |
| `backend/api/app/agent/plan_solve.py` / `reflect.py` | PlanCard 与确认卡保留为唯一可见规划产物；删除 Plan/reflect 的阶段 thought，避免每个图节点增加过程卡 |
| `frontend/src/views/Agent.vue` | 一个回合最多显示一张固定过程摘要卡；历史事件跳过 `thought`，阶段事件只更新生成状态，不创建对话卡 |
| `backend/api/tests/test_agent_react.py` / `test_agent_routing.py` / `test_agent_multiturn.py` | 覆盖 JSON ReAct thought 不出站、ToolCall 草稿不出站、Plan/Reflect 无阶段卡与最终回答重新生成 |
| `docs/AI测试与评估平台-PRD.md` / `AI测试与评估平台-API.md` / `AI测试与评估平台-Agent开发文档.md` | 统一过程卡、最终交付和历史重放边界 |


## 2026-09-09 协议档供应商与完整 URL 优化

详见 [协议档供应商思考适配](AI测试与评估平台-协议档供应商思考适配.md) V1.0：十个供应商新建入口、真实模型品牌图标、只读能力投影及 `full_url` 字段以该节定义为准。管理页和编辑弹窗删除思考强度设置，仅在对话输入框选择；AgentLoop 按供应商能力初始化，不再继承 legacy 全局思考偏好。完整 URL 开启后不追加版本或协议后缀，后台主模型调用使用同一规则。

## V1.21 修改代码文件与作用清单（2026-09-14）

`backend/api/app/expert_prompt_settings.py` / `routers/admin.py`：专家专属配置的并发保护与无正文审计；`agent/loop_wiring.py`：按回合读取有效专家提示词；`frontend/src/views/AdminProfiles.vue` / `components/modals/AgentExpertPromptModal.vue` / `composables/useExpertPromptEditor.ts`：技能页专家目录、查看/编辑、恢复草稿与异步请求隔离；接口字段以 API V1.97 §3.6.2 为准。
