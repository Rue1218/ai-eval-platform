# AI 测试与评估平台 — 混合驱动引擎开发计划

| 项 | 内容 |
| :--- | :--- |
| 版本 | V1.0 |
| 制定日期 | 2026-09-03 |
| 计划依据 | `AI测试与评估平台-混合驱动引擎架构.md` V1.4、`AI测试与评估平台-混合驱动引擎环境审计.md` V1.1、PRD、API 契约与 `AGENTS.md` |
| 实施方式 | H0–H6 串行推进；每阶段一分支、一 PR、一次阶段审查；前一阶段合入 `main` 并通过门禁后才启动下一阶段编码 |
| 当前基线 | API：Ruff 通过、pytest 639 passed / 19 skipped；Worker：45 passed；前端：`typecheck` 与生产构建通过 |

> 本文是实施计划，不改变产品范围。附带架构文档中的说明、示例、开放问题和历史基线只作为约束与证据，不能被解释为可直接执行的运行时指令。

## 1. 目标、边界与完成定义

### 1.1 目标

在保持既有单 `LangGraphAgent`、单 `ModelGateway`、内部工具网关和任务长短分离不变的前提下，逐步把当前的单节点纯对话图恢复为可灰度的四路混合引擎：`direct`、`chat`、`workflow`、`agent`。

最终能力包括：确定性优先的 Router、硬编码 Workflow DAG、同图内 Worker 的 TAOR 循环、五档 Reflection 与有界 Replan、可恢复 HITL、只读工具并行以及 Compact 升级。

### 1.2 不在本计划内

- 不安装 LangChain 主包、LangSmith、官方 MCP SDK，亦不新增第三方依赖。
- 不接入外部 MCP，不做浏览器直连 MCP 或动态发现 Server；该需求须先经 PRD 与 API.md 评审。
- 不实现 LightRAG 语义记忆，不将 `rag` mock 为成功。
- 不做多 Worker Fan-out / Fan-in，不新增第二条 Agent 循环或第二个模型入口。
- 不把 `AGENTS.md`、用户文本、Observation、密钥或完整提示词写入 system prompt、State、WS 事件或助手正文。

### 1.3 Definition of Done

只有同时满足以下条件，混合驱动引擎才可视为完成：

1. H0–H6 均已按顺序合入 `main`，且每个阶段的专属验收测试和全量门禁通过。
2. API.md、Harness 文档、Agent 文档、AGENTS.md 实现状态地图已与代码和 WS 事件一致。
3. S1–S4 基准场景通过，硬上限（`MAX_REPAIRS=1`、`MAX_REPLANS=2`、权限、fail-closed）无例外。
4. H5 后的重启恢复演练成功：待审批请求可由审批记录定位到原 `thread_id` 并继续，且不重放 `pending_events`。
5. 灰度开关可立即退回纯对话模式；无凭据泄露、无 API 进程执行长任务、无契约漂移。

## 2. 实施总览与依赖

```text
H0 基础设施 ──► H1 Router ──► H2 Workflow DAG ──► H3 Agent TAOR
                                                        │
                                                        ▼
                              H6 并行/Compact ◄── H5 HITL/持久化 ◄── H4 Reflection/Replan
```

| 阶段 | 分支 | 依赖 | 主要风险 | 合入前的硬门槛 |
| :--- | :--- | :--- | :--- | :--- |
| H0 基础设施 | `feat/agent-hybrid-h0-foundation` | 无 | 缓存改造破坏既有纯对话输出 | 关闭缓存时字节级兼容；Registry 启动期 fail-fast |
| H1 Router | `feat/agent-hybrid-h1-router` | H0 | L0 误分流、契约漏改 | L0 五次运行 100% 一致；未实现路径安全降级 |
| H2 Workflow | `feat/agent-hybrid-h2-workflow` | H1 | 规则跳步、绕开入队门禁 | DAG 五次路径 100% 一致；零命中/并列澄清 |
| H3 TAOR | `feat/agent-hybrid-h3-taor` | H2 | 工具越权、Observation 泄露 | 工具经唯一网关；视野与预算均受控 |
| H4 Reflection | `feat/agent-hybrid-h4-reflexion` | H3 | 无限修复/重规划 | 修复最多一次、重规划最多两次并收敛 |
| H5 HITL | `feat/agent-hybrid-h5-hitl` | H4 | 重启丢失或跨副本恢复错误 | PostgreSQL 检查点与重启恢复演练通过 |
| H6 灰度 | `feat/agent-hybrid-h6-rollout` | H5 | 并发资源冲突、压缩丢槽位 | 只读并行不冲突；Compact 保留关键字段 |

### 2.1 开工前统一裁决

每一阶段开始前，负责人确认以下事项仍成立；若不成立，停止编码并先更新权威文档。

| 编号 | 裁决 | 实施动作 |
| :--- | :--- | :--- |
| C-1 | `profile_env.py` 是模型凭据主事实源 | H0 同步修正 AGENTS.md 的历史表述，任何节点只传 profile ID、不传 key |
| C-2 | 外部 MCP 默认 fail-closed | 仅保留关闭的配置接口；不实现外部 Server |
| C-3 / C-5 | 复用现有 Harness，在同一图内实现 Worker | 禁止新建并行 Harness、模型客户端或进程级 Agent |
| C-4 | Router 采用 L0 确定性优先、低置信度 L1 短调用 | L1 关闭时必须完全可复现；L1 失败回落 L0 |
| C-6 | 新 WS 事件/字段先改 API.md | 每个 PR 的第一个代码提交前完成契约和类型同步 |
| C-7 | HITL 必须持久化 | H5 不允许使用 `memory` checkpointer 发布 |
| C-8 | 清理死 `__pycache__` 产物 | 在 H0 确认未跟踪后删除并验证 `.gitignore` |
| C-10 | Reflection 是恢复性扩展而非简单接线 | H4 同时修改判决、协议枚举、节点和条件边 |

## 3. 阶段开发任务与检查点

### H0 — 基础设施：缓存边界、Agent Registry 与指令分层

**交付物**

- `assembly.py` 提供稳定的七段装配边界；`prompt_cache_enabled=False` 时最终提示词保持字节级一致。
- 适配器仅在开关开启时附加对应协议的 `cache_control`；静态段按 global、agent、skill 分桶。
- 新增 `orchestration/agents.py`，静态注册 `worker.general`、`worker.diagnose`、`worker.dataset`、`worker.sandbox`；启动期校验工具、技能、协议档引用。
- 新增受控的 `project_instructions` 槽，按 L1→L2→L3 顺序注入并拦截接管性措辞；`AGENTS.md` 不进入运行时 prompt。
- `SKILL.md` 在正文支持 `## 示例请求`，不修改严格六键头部；清理死缓存产物。

**阶段检查与测试**

- 单元测试：段序单调、静态段快照、关闭缓存字节级兼容、缓存分桶、示例抽取、下层指令拒绝、Registry 的全量子集校验与缺项启动失败。
- 安全测试：`api_key` 不进入 `SerializableRequest`，`model_profile_id` 无效时返回 `VALIDATION`。
- 回归：API Ruff + pytest、Worker pytest、前端 typecheck/build 全绿。

**审查出口**：不改生产图、不改 WS 契约；代码审查确认没有新增依赖、外部 MCP 或第二模型入口。

### H1 — Router：四路分流骨架和审计

**交付物**

- 在现有图接入顶层 Router；新增 RootState 的 `engine`，不驱动遗留 `mode` 字段。
- L0 为纯函数，输出 `engine`、`router_confidence`、`router_reason`；低于阈值才允许 L1，L1 故障回落 L0。
- 主开关关闭时完全保留 chat-only 路径；`workflow`、`agent` 在本阶段先安全降级到 `chat_stream`，并产生审计痕迹。
- 先更新 API.md，在既有 `response.completed` 或经裁决的 `thought.stage="route"` 中提供 `engine`；同步前端类型。
- 启动 O2 的四类弱监督信号采集口径，但不把它们直接用作阈值优化目标。

**阶段检查与测试**

- 同一输入连续五次，L1 关闭时 `engine` 与 `router_confidence` 100% 相同。
- S1 简单问答必须 `chat/direct`、零工具、无 Plan；低置信度与 L1 失败均不导致异常或猜测性 `agent`。
- 契约对齐测试：WS 事件/字段集合与 API.md 一致；主开关关闭时回归纯对话快照。

**审查出口**：Router 只做分流，不创建任务、不加载工具、不执行长任务。

### H2 — Workflow：八节点硬编码 DAG 与二段路由

**交付物**

- 实现 W0 `select_skill`、W1 受限单圈 ReAct、W2 槽位提取、W3 `validate_gates`、W4 参数组装、W5 确认、W6 enqueue、W7 展示的硬编码 DAG。
- W0 根据候选做确定性二段路由；零命中或并列必须 `clarify`，不猜测技能。
- 只允许 W6 通过内部 MCP 长任务桥入队；保持「先评后压」、会话串行和 `skill-rag` fail-closed。
- API.md 先恢复确认卡事件、字段及前端确认卡类型；不提前接入图内 HITL。

**阶段检查与测试**

- 固定槽位请求五次运行的节点路径一致率为 100%，无跳步和回溯。
- `benchmark`、`testcase`、`stress` 的正确技能选择；`rag` 返回 `VALIDATION`，绝不写 succeeded。
- 并列/零命中产生澄清；门禁失败在当前节点收尾；重复提交命中 `uq_tasks_active_session`。
- 确认卡字段和 API.md §5 默认值精确一致；评测成功前不派生压测。

**审查出口**：Workflow 不形成多圈 Agent；W1 只读工具视野不越权，任何入队均可追溯至 W6。

### H3 — Agent：Plan、Discover 与 TAOR 主循环

**交付物**

- 恢复 `plan`、`discover`、`orchestrator` 节点壳，复用 `plan.py`、`protocols.py`、`toolnode.py`，不重写执行层。
- `discover` 以 `plan.v1.intent` 的确定性映射生成能力/技能并解析 AgentDef；未命中回落 `worker.general`。
- 新增 `plan_step_index` 并在 Replan 后置零；工具可见集始终是 AgentDef 白名单的子集。
- API.md 先恢复 `tool_call`、`tool_result`、`thought`；前端恢复 ToolCard，只展示脱敏摘要。
- Observation 只作为模型输入；不进入助手正文、WS 持久事件或检查点。

**阶段检查与测试**

- S2：Plan 步数 3–7，TAOR 每轮模型输入前有 Observation，工具圈数与调用预算不超限。
- Discover 对同一输入稳定选择同一 Agent，跨 Worker 时 `allowed_tools` 正确切换。
- 所有工具先经过 Schema、门禁、权限、并发和脱敏链；非法工具/协议档返回统一 `VALIDATION`。
- 大文本 Observation 不进入消息历史；ToolCard 和 trace 中无敏感值。

**审查出口**：只恢复单图内循环；不在 WebSocket 收包循环 await 整轮 Harness，也不在 API 进程运行评测。

### H4 — Reflection：五档判决、修复与有界重规划

**交付物**

- 把 `review.py` 从三档扩展为 `pass/clarify/reject/repair/retry`，同步 `REFLECT_SCHEMA` 与 `parse_reflect` 枚举。
- 重建 reflect 节点和条件边；常量收敛为 `MAX_REPAIRS=1`、`MAX_REPLANS=2`。
- 首次可修复失败注入 `repair_hint`；再次失败触发有界 Replan；超过上限以可读原因 `reject` 收尾。

**阶段检查与测试**

- S3 人为注入失败，验证 `repair → retry → replan → reject` 的路径与每个硬上限。
- 不允许空转至预算耗尽；`reject` 不能误判为 `pass`；`clarify` 不调用工具。
- `rm -rf` 与沙箱关闭均 fail-closed；`rag` 仍返回 `VALIDATION`；所有异常按十类 ErrorCode 归一，响应不泄漏堆栈。

**审查出口**：五档协议、状态类型、条件边和前端展示（如有）必须同一 PR 完整对齐。

### H5 — HITL：持久化、恢复与粘性路由

**交付物**

- 将生产 HITL 运行配置切至 `PgCheckpointer`，并落实按 `session_id` 的网关粘性路由策略。
- 定义并落地 `thread_id` 持久化/恢复协议：审批或确认记录携带 `thread_id`，`resume` 通过记录恢复同一图。
- `ws.py` 实现 `resume`、真实 `ahas_pending_interrupt`，恢复检查点前清空图内 `pending_events`。
- 先更新 API.md 的审批事件、请求和恢复语义；补断线重连与权限校验。

**阶段检查与测试**

- 人为中断后重启 API，按审批记录恢复原 `thread_id` 并只继续一次；不重放历史 WS 事件。
- 非所有者、过期/不存在审批、错误 session 的 resume 均被拒绝且不改变状态。
- 多副本路由演练验证同一 session 固定落点；恢复后事件号仍单调、`last_event_id` 补发完整。

**审查出口**：重启恢复演练为阻断发布条件；未完成前不得发布任何需确认的 code/write 工具能力。

### H6 — 灰度：只读并行与 Compact LLM 压缩

**交付物**

- 依协议档分批启用既有 `agent_parallel_tool_batch_enabled`；只读工具可并行，写/网络/独占工具继续串行。
- 把 `compact.summarize()` 升级为使用既有 ModelGateway 的受控 LLM 压缩，保留关键槽位并有失败降级。
- 建立发布观测：并发波次、资源键冲突、缓存命中、Compact 前后槽位完整性、延迟与模型调用数。

**阶段检查与测试**

- 只读工具同波次无资源键冲突，写工具和 `exclusive` 工具绝不并行。
- Compact 后任务目标、权限、计划进度、工具结果摘要和未决审批槽位均完整；上游失败时可安全降级。
- 灰度关闭可立即回到 H5 行为；S1–S4 全量回归不退化。

**审查出口**：先小流量协议档、再扩大范围；任一资源冲突或关键槽位丢失立即关闭开关并回滚到 H5。

## 4. 统一测试策略

### 4.1 测试分层

| 层级 | 覆盖对象 | 最低要求 |
| :--- | :--- | :--- |
| 单元 | Router、Registry、State、协议解析、门禁、段装配 | 新增分支与负例均有断言；纯函数包含确定性测试 |
| 组件 | 图节点、工具网关、Checkpointer、WS 事件 | 使用桩 Gateway，验证状态与事件而非模型自由文本 |
| 契约 | REST/WS、前端 TypeScript 类型、API.md | 事件名、字段、默认值及错误码全部对齐 |
| 端到端 | S1–S4、重启恢复、确认入队 | 使用隔离数据库/协议档；覆盖失败和断线场景 |
| 回归 | API、Worker、前端全量 | 每 PR 必跑；合入 main 前无失败 |

### 4.2 基准场景与阈值

| 场景 | 主验收 | 不可违反项 |
| :--- | :--- | :--- |
| S1 简单任务 | `chat/direct`、零工具、一次以内模型调用 | 不伪造 Skill、Plan、DAG 或 Reflection |
| S2 多步推理 | `agent`、Plan 3–7 步、TAOR 受预算约束 | 工具不越出 AgentDef；S2 的 replan 平均不超过 0.5 |
| S3 错误诱导 | 修复一次、重规划最多两次、可读拒绝 | `rm -rf`、沙箱关闭、rag 都必须 fail-closed；凭据和 Observation 不泄漏 |
| S4 跨域协作 | Worker 切换、确认入队、先评后压 | 不绕过 W6；会话唯一活动任务约束生效 |

量化目标：Router 总准确率 ≥95%（S1/S2 各 ≥98%）；Worker 发现准确率 ≥90%；Verdict 与人工标注一致率 ≥90% 且 `reject→pass` 为零；S2 工具圈数中位数 ≤6、S1 恒为零；重复调用率 ≤10%、无效调用率 ≤5%。缓存 ≥60% 仅作为校准观测值，不作为阻断门槛。

### 4.3 每阶段合入门禁

```powershell
# API
Set-Location backend/api
ruff check . ../shared
pytest

# Worker
Set-Location ../worker
$env:PYTHONPATH = '.;..'
pytest

# Frontend
Set-Location ../../frontend
npm run typecheck
npm run build
```

此外必须通过：新增字段 `assert_serializable()`、WS/API 契约一致性、Registry 子集校验、缓存段稳定快照，以及红线守卫（沙箱 off、rag、外部 MCP off）。Linux/Docker 环境还须在 H3、H5、H6 对 bwrap Runner、PostgreSQL 检查点和反向代理粘性路由做真实演练；Windows 本机结果不能替代这些演练。

## 5. 阶段审查、发布与回滚

### 5.1 阶段审查清单

每个 PR 的审查者逐项勾选：

1. 已从最新 `origin/main` 创建对应分支，且不夹带无关改动、迁移或依赖。
2. 契约变更先于实现，API.md、前端类型、后端事件同步更新；无未记录的新事件。
3. 所有新增/修改代码具有中文 docstring、复杂分支和类型注释；异常遵守 `AppError` 与脱敏 `agent_trace` 规范。
4. 阶段专属测试、全量 API/Worker/前端门禁和静态检查均有可复核输出。
5. 关键开关默认安全关闭，失败路径为 fail-closed；没有泄漏密钥、原始 Observation、提示词或异常详情。
6. 文档末尾已更新「修改代码文件与作用清单」，实现状态地图与本计划的阶段状态同步。

### 5.2 发布策略

- H0–H1 通过 `hybrid_engine_enabled=False` 默认关闭发布，先验证不影响纯对话。
- H2–H4 先在测试/预发启用，再选择内部协议档灰度；收集 O2 信号只作样本筛选。
- H5 仅在 PostgreSQL 检查点、粘性路由和重启恢复演练完成后启用 write/code/HITL。
- H6 从单个协议档的小流量开始；按延迟、错误率、资源冲突、槽位完整性决定扩大或暂停。

### 5.3 回滚策略

| 触发 | 立即动作 | 后续处理 |
| :--- | :--- | :--- |
| 分流错误、工具越权、契约不一致 | 关闭 `hybrid_engine_enabled`，恢复纯对话 | 保存脱敏事件，定位后在阶段分支修复 |
| 缓存异常、模型调用成本异常 | 关闭 `prompt_cache_enabled` 或 L1 Router | 用稳定段快照和 usage 对比复盘 |
| HITL 恢复错误 | 停止 `resume` 与 write/code 工具发布 | 保留审批记录，修复后重新演练 |
| 并行资源冲突、Compact 丢关键槽位 | 关闭并行/Compact 灰度 | 回到 H5 行为，补覆盖用例 |

## 6. 任务看板与推进规则

本计划配套建立 7 个 Codex 任务（H0–H6）。任务是串行依赖，不允许因工作区隔离而并行实施相邻阶段；每个任务须在开始编码前确认上游 PR 已合入 `main`、基线命令通过、开放问题没有扩大范围。

| 任务 | 状态规则 | 交接产物 |
| :--- | :--- | :--- |
| H0 | 可立即开始 | 缓存/Registry/指令分层 PR、测试输出、基线记录 |
| H1 | 等 H0 合入 | Router 契约、确定性测试和 O2 口径 |
| H2 | 等 H1 合入 | Workflow DAG、确认卡契约、入队门禁测试 |
| H3 | 等 H2 合入 | TAOR、ToolCard 契约、工具视野与泄露测试 |
| H4 | 等 H3 合入 | 五档 Reflection、上限与失败阶梯测试 |
| H5 | 等 H4 合入 | 持久化/HITL、重启恢复演练证据 |
| H6 | 等 H5 合入 | 灰度报告、并行/Compact 观测和回滚演练 |

阶段任务完成时，负责人必须提交：PR 链接、改动清单、阶段验收结果、完整门禁输出摘要、遗留风险和下一阶段明确的入口提交。若任一硬门槛失败，任务保持在本阶段修复，不能以「后续阶段再处理」作为放行理由。

## 修改代码文件与作用清单

本文档为开发计划，未修改应用源码、配置、依赖、数据库迁移或 API 契约。

- `docs/AI测试与评估平台-混合驱动引擎开发计划.md`（新增）：依据混合驱动引擎架构与环境审计定义 H0–H6 的串行任务、契约前置、阶段验收、S1–S4 测试、发布回滚及交接规则。
