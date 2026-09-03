# AI 测试与评估平台 — 混合驱动引擎开发计划

| 项 | 内容 |
| :--- | :--- |
| 版本 | V1.6 |
| 制定 / 审查日期 | 2026-09-03 / 2026-09-03 |
| 计划依据 | `AI测试与评估平台-混合驱动引擎架构.md` V1.5、`AI测试与评估平台-混合驱动引擎环境审计.md` V1.1、PRD、API 契约与 `AGENTS.md` |
| 实施方式 | H0–H6 串行推进；每阶段一分支、一 PR、一次阶段审查；前一阶段合入 `main` 并通过门禁后才启动下一阶段编码 |
| 当前基线 | API：Ruff 通过、pytest 全量 794 passed / 20 skipped（含 H0–H5 批次 1/2 与 H0–H3 联调套件；2 项既有失败 `test_stream_sdk_wire_contract`/`test_web_fetch_allows_public_target` 在 main 上同样存在，与本阶段无关）；Worker：48 passed；前端：`typecheck` 与生产构建通过 |

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
| H2 Workflow | `feat/agent-hybrid-h2-workflow` | H1 | 规则跳步、绕开入队门禁 | DAG 五次路径 100% 一致；零命中/并列错误收尾 |
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

### 2.2 阶段决策门（未裁决不得开始编码）

开放问题不能只保留在架构文档中；每项必须在对应阶段的设计评审记录、API.md（涉及对外契约时）和 PR 描述中形成可复核结论。默认倾向仅在拍板人未反对时生效，不能由实现者临时扩展范围。

| 最晚阶段 | 必须裁决的事项 | 默认 / 约束 | 拍板方 |
| :--- | :--- | :--- | :--- |
| H0 | `project_instructions` 的来源、S3 工具段分桶、`GET /api/agents` 的时机 | L2 先用服务端常量；S3 按 `engine + agent_id` 分桶；H0 **不暴露**目录 API，H1 先改 API.md 后再暴露 | 架构 + 契约 |
| H1 | `direct` 的命令范围、Router 审计载体、L1 协议档 | 当前只承认既有 `/stop`；恢复其他斜杠命令须先改 PRD/API.md。`response.completed.engine` 为 H1 唯一审计载体；L1 复用会话协议档并限制 `max_tokens` | 产品 + 架构 + 契约 |
| H2 | 技能零命中/并列的外部语义、确认卡是否进图内中断 | API.md V1.68+ 裁决为零命中/并列与非法/禁用技能均 `VALIDATION` 错误收尾；确认卡维持 WS 直连，H5 后再评估图内 `interrupt` | API 契约 + 架构 |
| H3 | 首批 Worker 与工具命名口径 | 首批仅 `worker.general` / `worker.diagnose` / `worker.dataset` 的 read/write 非 code 能力；`worker.sandbox` 不得被 discover 选中，待 H5 HITL 上线后单独安全评审 | 架构 + 安全 |
| H5 | `thread_id` 的持久化载体和恢复幂等语义 | 优先扩展既有、带行锁的 `sessions.pending_confirm` JSONB；每个确认/恢复记录必须具备版本、种类、`thread_id`、一次性 nonce 与所有者。若需要改 Model / 表结构，必须先出 Alembic 迁移 | 架构 + 数据库 + 安全 |
| H6 后 | O3 embedding 供应方、O9 分层路由、Fan-out | 仅凭 O2 采样与人工标注证明收益后立项；技能数未超过 10 前不做 O9，Fan-out 单列项目 | 架构 + 产品 |

## 3. 阶段开发任务与检查点

### H0 — 基础设施：缓存边界、Agent Registry 与指令分层

**交付物**

- `assembly.py` 提供固定的 S1–S7 装配边界：Persona、Skill Hint、工具定义、Skill 正文、Overlay、会话摘要、当轮输入/消息窗口/Observation；段序只能 S1→S7，动态段不得插入静态前缀。
- `prompt_cache_enabled=False` 时最终提示词保持字节级一致；开启后由受控提示词来源拆为 S1（L1/L2）、S2（技能目录）与动态 S5（会话负责人/L3 Overlay），仅由适配器在最后静态段附加缓存语义：Anthropic 使用 `cache_control`，OpenAI 保持稳定前缀，未支持协议无损回退 `join` 行为。缓存观测必须记录断点命中，不能把 60% 命中率当硬门槛。
- 新增 `orchestration/agents.py`，静态注册 `worker.general`、`worker.diagnose`、`worker.dataset`、`worker.sandbox`；启动期校验工具、技能、协议档引用。
- 新增受控的 `project_instructions` 槽，H0 仅采用服务端常量；按 L1→L2→L3 顺序注入并拦截接管性措辞；`AGENTS.md` 不进入运行时 prompt。
- 在 `config.py` / `.env.example` / 配置文档同步声明安全默认值：`hybrid_engine_enabled=False`、`hybrid_router_cot_enabled=False`、`hybrid_router_confidence_threshold=0.7`、`agent_registry_strict=True`、`prompt_cache_enabled=False`、`external_mcp_enabled=False`。H0 不新增 `GET /api/agents`，避免在“无契约变更”阶段产生未文档化接口。
- `SKILL.md` 在正文支持 `## 示例请求`，不修改严格六键头部；清理死缓存产物。

**阶段检查与测试**

- 单元测试：段序单调、静态段快照、关闭缓存字节级兼容、按 `engine + agent_id` 的 S3 分桶、供应商无损回退、示例抽取、下层指令拒绝、Registry 的全量子集校验与缺项启动失败。
- 安全测试：`api_key` 不进入 `SerializableRequest`，`model_profile_id` 无效时返回 `VALIDATION`。
- 回归：API Ruff + pytest、Worker pytest、前端 typecheck/build 全绿。

**审查出口**：不改生产图、不改 WS 契约；代码审查确认没有新增依赖、外部 MCP 或第二模型入口。

### H1 — Router：四路分流骨架和审计

**交付物**

- 在现有图接入顶层 Router，并一次性新增可序列化的 RootState 字段 `engine`、`router_confidence`、`router_reason`、`agent_id`、`allowed_tools`、`workflow_step`；不重命名、删除或驱动遗留 `mode` 字段。
- L0 为纯函数，输出 `engine`、`router_confidence`、`router_reason`；阈值固定为配置值 0.7。L1 采用受 `router.v1` JSON Schema / 解析器校验的短调用，结果为 `{engine, skill_id?, confidence, reason, slots?}`，且每次调用必须计入 `budget.model_calls`；格式错误、上游错误、超时或预算耗尽均回落 L0，L0 无结论回落 `chat`。L1 的 `workflow` 结论还须经确定性执行意图门禁，概念问答不得误入确认卡流程。
- H1 的 `direct` 只承认当前收包循环已有的 `/stop` 零模型动作；任何新增或恢复的斜杠命令必须先完成 PRD、API.md、前端交互和安全审查，不能借 Router 重建绕过骨架化范围。
- 主开关关闭时完全保留 chat-only 路径；`workflow`、`agent` 在本阶段先安全降级到 `chat_stream`，并产生审计痕迹。
- 先更新 API.md，在既有 `response.completed` 固定增加 `engine`、`router_confidence` 与脱敏的 `router_reason`，不在 H1 复用尚未恢复的 `thought` 事件；同步前端类型、旧客户端兼容策略和 `GET /api/agents` 的只读目录契约。
- 启动 O2 的四类弱监督信号采集口径，但不把它们直接用作阈值优化目标。

**阶段检查与测试**

- 同一输入连续五次，L1 关闭时 `engine` 与 `router_confidence` 100% 相同；覆盖阈值两侧、`router.v1` 非法 JSON、模型超时、上游 5xx 与预算耗尽，且全部安全回落。
- S1 简单问答必须 `chat/direct`、零工具、无 Plan；低置信度与 L1 失败均不导致异常或猜测性 `agent`。
- 契约对齐测试：WS 事件/字段集合与 API.md 一致；主开关关闭时回归纯对话快照。

**审查出口**：断言 `engine` 写入后本轮不可变；`direct/chat` 时 `agent_id`、`allowed_tools`、`plan` 为空。Router 只做分流，不创建任务、不加载工具、不执行长任务。

### H2 — Workflow：八节点硬编码 DAG 与二段路由

**交付物**

- 按唯一顺序实现 8 节点硬编码 DAG：W0 `select_skill` → W1 `prepare_slots`（节点内最多一次、只读视野的局部 ReAct）→ W2 `load_skill` → W3 `validate_gates` → W4 `build_task_spec` → W5 `await_confirm` → W6 `enqueue` → W7 `summarize`。节点失败只能就地收尾，不能改写下一跳或形成重试回环。
- 同步新增 WorkflowState 的 `skill_id`、`skill_candidates`、`slots`、`slots_missing`、`gate_report`、`task_spec`、`confirm_id`、`enqueued_task_id`；字段全部 JSON 可序列化。`confirm_id` 与 `clarify_id` 必须互斥，`engine=workflow` 时 `replan_count` 恒为 0。
- W0 根据候选做确定性二段路由：已启用的 L1 `skill_id` 直接采用；其余零命中、并列、非法或已禁用技能均以 `VALIDATION` 错误收尾；不得猜测技能。明确「先评后压」归一为 benchmark/rag 质量任务的 `with_stress=true`，直接 `stress` 仍由 W3 拒绝。
- 只允许 W6 通过内部 MCP 长任务桥入队；保持「先评后压」、会话串行和 `skill-rag` fail-closed。
- API.md 先恢复确认卡事件、字段及前端确认卡类型；H2 维持既有 WS 直连确认卡，不提前接入图内 HITL。确认动作必须在既有 `pending_confirm` 行锁事务内完成，且未批准、拒绝、重复确认都不会绕过 W6 入队门禁。

**阶段检查与测试**

- 固定槽位请求五次运行的节点路径一致率为 100%，精确覆盖 8 个节点的顺序，无跳步、回溯或合并 `select_skill/load_skill`。
- `benchmark`、`testcase`、`stress` 的正确技能选择；`rag` 返回 `VALIDATION`，绝不写 succeeded。
- 并列/零命中产生 `VALIDATION` 错误；门禁失败在当前节点收尾；重复提交命中 `uq_tasks_active_session`。
- 确认卡字段和 API.md §5 默认值精确一致；评测成功前不派生压测；`assert_serializable()` 覆盖 WorkflowState 和所有新增 RootState 字段。

**审查出口**：Workflow 不形成多圈 Agent；W1 只读工具视野不越权，任何入队均可追溯至 W6。

### H3 — Agent：Plan、Discover 与 TAOR 主循环

**交付物**

- 恢复 `plan`、`discover`、`orchestrator` 节点壳，复用 `plan.py`、`protocols.py`、`toolnode.py`，不重写执行层。
- `discover` 以 `plan.v1.intent` 的确定性映射生成能力/技能并解析 AgentDef；未命中回落 `worker.general`。首批仅启用 `general`、`diagnose`、`dataset` 的许可集合；虽然 H0 可静态注册 `worker.sandbox`，H3 必须使其不可被 discover 选择，任何 `bash` / code Worker 均等待 H5 持久化 HITL 与安全评审。
- 新增 `plan_step_index` 并在 Replan 后置零、越界直接令 `turn_failed`；工具可见集始终是 AgentDef 白名单的子集。`allowed_tools` 只能使用 ToolRegistry 注册全名；会话看板工具与 `platform.tasks.task.*` 长任务桥不可混用，后者仍仅由 Workflow W6 调用。
- API.md 先恢复 `tool_call`、`tool_result`、`thought`；前端恢复 ToolCard，只展示脱敏摘要。
- Observation 只作为模型输入；不进入助手正文、WS 持久事件或检查点。

**阶段检查与测试**

- S2：Plan 步数 3–7，TAOR 每轮模型输入前有 Observation，工具圈数与调用预算不超限；补覆盖 `parse_retries≤2`、同参只读工具重复三次后的 `repeat_retry` 守卫，以及 `/stop` 与会话并发时即时终止本轮。
- Discover 对同一输入稳定选择同一 Agent，跨 Worker 时 `allowed_tools` 正确切换。
- 所有工具先经过 Schema、门禁、权限、并发和脱敏链；非法工具/协议档返回统一 `VALIDATION`。
- 大文本 Observation 不进入消息历史；ToolCard 和 trace 中无敏感值。

**审查出口**：只恢复单图内循环；不在 WebSocket 收包循环 await 整轮 Harness，也不在 API 进程运行评测。

### H4 — Reflection：五档判决、修复与有界重规划

**交付物**

- 把 `review.py` 从三档扩展为 `pass/clarify/reject/repair/retry`，同步 `REFLECT_SCHEMA` 与 `parse_reflect` 枚举。
- 重建 reflect 节点和条件边；常量收敛为 `MAX_REPAIRS=1`、`MAX_REPLANS=2`。
- 首次可修复失败注入 `repair_hint`；再次失败触发有界 Replan；超过上限以可读原因 `reject` 收尾。
- `repair_hint` 只通过 Observation 进入下一轮 Executor；`replan_reason` 只进入新 Plan 的 notes，且不得参与技能关键词匹配。`turn_failed=True` 时任何路径均不得产生 `pass`。

**阶段检查与测试**

- S3 人为注入失败，验证 `repair → retry → replan → reject` 的路径与每个硬上限。
- 不允许空转至预算耗尽；`reject` 不能误判为 `pass`；`clarify` 不调用工具。
- `rm -rf` 与沙箱关闭均 fail-closed；`rag` 仍返回 `VALIDATION`；所有异常按十类 ErrorCode 归一，响应不泄漏堆栈。

**审查出口**：五档协议、状态类型、条件边和前端展示（如有）必须同一 PR 完整对齐。

### H5 — HITL：持久化、恢复与粘性路由

**交付物**

- 将生产 HITL 运行配置切至 `PgCheckpointer`，并落实按 `session_id` 的网关粘性路由策略。
- 定义并落地版本化的 `thread_id` 持久化/恢复协议：确认/审批记录至少含 `schema_version`、`kind`、`thread_id`、`owner_id`、一次性 `resume_nonce` 与创建时间。优先扩展既有、受 `SELECT ... FOR UPDATE` 保护的 `sessions.pending_confirm` JSONB；若 Model/表结构、索引或清理任务需要变更，必须在同一 PR 提交 Alembic upgrade/downgrade 迁移和迁移演练。
- `ws.py` 实现 `resume`、真实 `ahas_pending_interrupt`，恢复检查点前清空图内 `pending_events`。
- 先更新 API.md 的审批事件、请求和恢复语义；补断线重连与权限校验。

**阶段检查与测试**

- 人为中断后重启 API，按审批记录恢复原 `thread_id` 并只继续一次；不重放历史 WS 事件。并发双击、断线重试或相同 nonce 的重复 `resume` 必须由行锁和状态转换实现“至多一次”，后续请求不再唤醒图。
- 非所有者、过期/不存在审批、错误 session 的 resume 均被拒绝且不改变状态。
- 多副本路由演练验证同一 session 固定落点；恢复后事件号仍单调、`last_event_id` 补发完整。验证功能开关关闭、部署回退或迁移失败时，遗留待审批记录不会被丢失或被错误执行。

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

在 H0 建立 `backend/api/tests/hybrid/fixtures/scenarios.py`、桩 ModelGateway、期望引擎/Worker/Verdict 标注和脱敏事件断言助手；H1 起所有 S1–S4 复用同一套固定语料。模型自由文本不作为断言对象，Router、State、事件、门禁和预算才是可复现断言对象。每次预发灰度须把 `ws_events`、终态 State 与 `/api/mcp/metrics` 聚合为一份脱敏评分报告，保留用于 O2 样本筛选和 H6 放量决策。

### 4.2 基准场景与阈值

| 场景 | 主验收 | 不可违反项 |
| :--- | :--- | :--- |
| S1 简单任务 | `chat/direct`、零工具、一次以内模型调用 | 不伪造 Skill、Plan、DAG 或 Reflection |
| S2 多步推理 | `agent`、Plan 3–7 步、TAOR 受预算约束 | 工具不越出 AgentDef；S2 的 replan 平均不超过 0.5 |
| S3 错误诱导 | 修复一次、重规划最多两次、可读拒绝 | `rm -rf`、沙箱关闭、rag 都必须 fail-closed；凭据和 Observation 不泄漏 |
| S4 跨域协作 | Worker 切换、确认入队、先评后压 | 不绕过 W6；会话唯一活动任务约束生效 |

量化目标：Router 总准确率 ≥95%（S1/S2 各 ≥98%）；Worker 发现准确率 ≥90%；Verdict 与人工标注一致率 ≥90% 且 `reject→pass` 为零；S2 工具圈数中位数 ≤6、S1 恒为零；重复调用率 ≤10%、无效调用率 ≤5%；S3 三次内修复成功率 ≥70%、S2 收敛率 ≥85%。性能报告还须记录 S1 ≤2k token、S2 ≤40k token、S1 整轮 ≤5 秒、首字 ≤2 秒、S2 模型调用 ≤12；缓存 ≥60% 仅作为校准观测值，不作为阻断门槛。

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
| H0 | ✅ 已交付（PR #198）；审查修复（PR #209）已使 L2 受控常量进入 WS 运行时，并将 L3 Overlay 移出缓存静态段 | 缓存/Registry/指令分层 PR、测试输出、基线记录 |
| H1 | ✅ 已交付（PR #200）；审查修复（PR #209）及本次修复已排除概念问答、归一先评后压，并把已启用 L1 `skill_id` 交给 W0 | Router 契约、确定性测试和 O2 口径 |
| H2 | ✅ 批次 1（PR #202）与批次 2 确认卡链路（PR #204）均已合入、CD ✓；本次修复已恢复失败确认卡、合并受控槽位，并让 W0/W2/W3/W6 错误统一写入 `response.completed(error)` | Workflow DAG 与确认卡契约、入队门禁测试 |
| H3 | ✅ 已合入（PR #203，CD ✓）；H0–H3 联调套件已合入（PR #206） | TAOR、ToolCard 契约、工具视野与泄露测试 |
| H4 | ✅ 已合入（PR #210，CD ✓） | 五档 Reflection、上限与失败阶梯测试 |
| H5 | 🔶 批次 1 已合入（PR #211，CD ✓）：图内 interrupt 审批 + resume 协议 + 审批卡 meta（thread_id/一次性 nonce）+ resume 至多一次；批次 2 进行中（本分支 `feat/agent-hybrid-h5-hitl-batch2`）：API.md V1.70 契约先行 + `agent_hitl_strict_pg` 启动门禁 + `/api/health` 实例标识（粘性路由支持）；**未完成**：`AGENT_CHECKPOINTER=postgres` 生产切换、网关粘性路由落地、重启恢复演练（Linux/Docker）、`worker.sandbox` 安全评审 | 持久化/HITL、重启恢复演练证据 |
| H6 | 等 H5 合入 | 灰度报告、并行/Compact 观测和回滚演练 |

阶段任务完成时，负责人必须提交：PR 链接、改动清单、阶段验收结果、完整门禁输出摘要、遗留风险和下一阶段明确的入口提交。若任一硬门槛失败，任务保持在本阶段修复，不能以「后续阶段再处理」作为放行理由。

## 修改代码文件与作用清单

本文档为开发计划，未修改应用源码、配置、依赖、数据库迁移或 API 契约。

- `docs/AI测试与评估平台-混合驱动引擎开发计划.md`（新增）：依据混合驱动引擎架构与环境审计定义 H0–H6 的串行任务、契约前置、阶段验收、S1–S4 测试、发布回滚及交接规则。

**V1.1 审查补充（纯文档）**：

1. 新增阶段决策门，明确 H0–H6 的拍板事项、默认边界和责任角色；消除 H0 `GET /api/agents` 与“无契约变更”、H1 `response.completed` 与 `thought` 审计载体、H1 `direct` 命令范围的歧义；
2. 修正 H2 的 Workflow DAG 为 `select_skill → prepare_slots → load_skill → validate_gates → build_task_spec → await_confirm → enqueue → summarize`，补齐 WorkflowState、`clarify`/`VALIDATION` 分界和 WS 直连确认卡事务约束；
3. 补齐 RootState、Router `router.v1` 协议/预算/回退、H3 首批 Worker 与 sandbox 禁用、Reflection 双通道和停止守卫；
4. 补齐 H5 的确认记录字段、既有行锁复用、迁移条件、重复 resume 至多一次、遗留审批回退保护；
5. 补齐混合测试资产、评分报告和性能/收敛指标，作为 O2 数据采集与 H6 灰度放量依据。

**V1.2 实施记录（H0 已交付，`feat/agent-hybrid-h0-foundation`，2026-09-03）**：按 H0 阶段目标落地基础设施，**未改生产图、未改 WS 契约**——

1. **缓存边界**：`assembly.py` 新增 `PromptSegment`/`assemble_segments`（段序单调 S1/S2/S4 可缓存静态段 + S6/S7 动态段），`assemble()` 内部委托渲染且与骨架化版本**字节级一致**（`prompt_cache_enabled=False` 回归锚点）；`contracts.py` 新增 `SystemSegment` 与 `ModelRequest.system_segments`；`adapters.py` 三协议入口透传并在 Anthropic 分支按「最后一个可缓存段」落 `cache_control: ephemeral`（OpenAI 依赖前缀稳定，不做处理；开关默认关）；
2. **Agent Registry**：新增 `harness/orchestration/agents.py`（`AgentDef`/`AgentRegistry`/首批 4 Worker 静态注册/`validate_agent_registry_integrity`），`main.py` lifespan 启动期校验（strict 缺项即阻止启动；DB 暂不可用仅跳过协议档维度）；
3. **指令分层**：`system.py` 新增 `project_instructions`（L2 受控槽，模板零改动，L2 空时输出与骨架版一致）与 `assert_no_takeover` 接管性措辞校验（L2/L3 命中「忽略以上/你现在是/override」即 VALIDATION）；
4. **Skill 示例段**：`workflows.py` 新增 `extract_skill_examples`（正文 `## 示例请求` 段，头部六键零改动，fail-closed 沿 skill 门禁）；
5. **配置与清理**：`config.py`/`.env.example` 新增 6 项安全默认配置（全部默认关闭）；死 `__pycache__` 产物核查不存在（C-8 关闭）；
6. **测试资产**：新增 `tests/test_hybrid_h0_foundation.py`（16 例）与 `tests/hybrid/fixtures/scenarios.py`（S1–S4 语料，H1 起复用）；
7. **验收结果**：API Ruff 通过、pytest **654 passed / 20 skipped**（含 16 例新测试，零回归）；Worker 48 passed；审查出口确认：无新增第三方依赖、无外部 MCP、无第二模型入口、`hybrid_engine_enabled=False` 时纯对话行为不变。

**V1.3 实施记录（H2 批次 2 确认卡链路，PR #204，974ee17，2026-09-03）**：W5 发卡
+ `confirm_ack` 行锁事务 + `workflow_confirm` 重放，入队唯一经 W6；API.md 升至
V1.68（与 H3 的 V1.67 顺序修正）。

**V1.4 H0/H1 审查修复（`fix/agent-h0-h1-review`，2026-09-03）**：

1. **L2 与缓存边界接线**：新增受控 `DEFAULT_PROJECT_INSTRUCTIONS` 并由 WS 在每轮构造 `SystemVars`；缓存开启时使用 `SystemPromptParts` 将 L1/L2 放入静态 S1、技能目录放入 S2、会话负责人与协议档 Overlay 放入动态 S5，杜绝 L3 Overlay 被错误缓存或技能目录重复注入。缓存关闭仍经旧单字符串渲染路径，保留回滚兼容；上游返回的缓存读/创建 token 将归一并随既有 `turn_stats` 持久化。
2. **Registry 单一实例**：启动校验、Agent TAOR 子图和 `GET /api/agents` 改为查询同一个进程级静态 `AgentRegistry`，避免多处独立构造导致运行时与校验对象漂移。
3. **Router 副作用门禁**：L1 的 `workflow` 与 `direct` 结论分别受“明确执行动作”和“斜杠输入”约束；概念问答回落 L0，不产生确认卡。同步清除已接通 TAOR 后仍称“agent 降级 chat”的错误审计文案。
4. **Workflow 失败终态**：W0/W2/W3/W6 的 `error` 统一经 `workflow_failure` 写入一次 `response.completed(error)`；W5 已自行收尾的确认卡/缺槽路径直接结束，保证每轮恰有一个 completed 事件。
5. **验收结果**：`ruff check . ../shared` 通过；API 全量 `pytest` **729 passed / 19 skipped**；H0/H1/H2 定向回归 56 项通过。无数据库模型、迁移、REST/WS 字段或默认开关变更。

## 修改代码文件与作用清单

- `backend/api/app/adapters.py`、`agent/routing.py`：归一并持久化上游缓存读/创建 token，供既有 `turn_stats` 观测。
- `backend/api/app/harness/prompts/system.py`、`__init__.py`：定义 L2 服务端常量和 S1/S2/S5 受控提示词分段源。
- `backend/api/app/harness/context/assembly.py`、`memory/state.py`：支持动态 S5 Overlay 与无密钥分段来源的可序列化传递。
- `backend/api/app/routers/ws.py`、`routers/admin.py`、`agent/routing.py`：在真实 WS 回合接入 L2/L3，按缓存开关重建正确分段。
- `backend/api/app/harness/orchestration/agents.py`、`main.py`、`routers/agents.py`、`agent/graph.py`：统一使用进程级 Agent Registry。
- `backend/api/app/harness/orchestration/router.py`、`agent/router_node.py`：复用确定性执行意图门禁，并修正 Agent 实际执行审计。
- `backend/api/app/agent/workflow_nodes.py`、`agent/graph.py`：为 Workflow 错误路径补齐唯一 `response.completed(error)` 收尾。
- `backend/api/tests/test_adapters.py`、`test_hybrid_h0_foundation.py`、`test_hybrid_h1_router.py`、`test_hybrid_h2_workflow.py`：覆盖缓存计数、缓存段位、Registry 共享、L1 回落、四路审计和失败终态回归。
- `AGENTS.md`、`docs/AI测试与评估平台-混合驱动引擎开发计划.md`：同步 H0–H3 真实实施状态与本次修复证据。

**V1.5 实施记录（H4 Reflection 五档判决，`feat/agent-hybrid-h4-reflexion`，PR #210，2026-09-03）**：
按 H4 阶段目标恢复五档判决与失败阶梯，**未新增 WS 事件名、未改 API 契约、未改前端**——

1. **五档判决库**：`harness/feedback/review.py` 的 `ReflectVerdict` 由三档扩为
   `pass/clarify/reject/repair/retry`，新增回合级常量 `MAX_REPAIRS=1` /
   `MAX_REPLANS=2`（唯一来源），判决分三级：L1 计划硬矛盾 → L2 失败阶梯 →
   L3 受控短核对（**只降级不放行**，保留 FB-3 硬约束）；
2. **协议同步**：`prompts/protocols.py` 的 `REFLECT_SCHEMA.verdict` 枚举同步为五档
   并补可选 `repair_hint`，`parse_reflect` 文档与过滤口径对齐；
3. **reflect 节点**：`agent/taor_nodes.py` 新增 `make_reflect_node`——L1 `turn_failed`
   一律 `reject`（不调模型、只补收尾帧），L2 阶梯按**回合级** `repair_count` /
   `replan_count` 配额判定，L3 仅在无失败时调用（计入预算，耗尽即跳过）；
   `repair` 把修复建议包成 Observation 回灌下一轮 Executor，`retry` 置
   `force_replan` + `replan_reason` 回 `plan`；
4. **收尾权移交**：`orchestrator` 的 done 路径不再自行发 `response.completed`，
   只写 `final_text` 交 `reflect` 判决后统一收尾（否则 `reject` 会被先发出的
   `stop` 覆盖，判决形同虚设）；`graph.py` 新增 `orchestrator → reflect` 与
   `reflect → END/orchestrator/plan` 两条条件边；
5. **plan 节点消费重规划**：`replan_reason` 只进系统指令与新 Plan 的 `notes`，
   **绝不并入** `build_plan` 文本入参（防失败文本参与 L0 技能关键词匹配）；
   游标与连续失败计数归零，**预算沿用剩余值**（换计划不放大回合预算）；
6. **状态层**：`memory/state.py` 新增 `final_text` 与 `repair_count`，
   `ReflectVerdict` 五档注释与实现三方（state / review / REFLECT_SCHEMA）对齐；
7. **递归上限**：混合引擎开启时 `recursion_limit` 由 32 提到 64（推导：
   2（plan+discover）+ 2×`MAX_REPLANS` + 2×`tool_turns` 上限 ≈ 46，留余量）；
   真正的硬上限仍是回合预算与两档配额；
8. **测试资产**：新增 `tests/test_hybrid_h4_reflection.py`（29 例），覆盖五档协议
   枚举、L1/L2/L3 判决、每个硬上限、`repair → retry → reject/pass` 图级全阶梯、
   `replan_reason` 不参与关键词匹配、无限修复反例；同步修正
   `tests/test_hybrid_h3_taor.py` 中因收尾权移交而变化的 6 处断言；
9. **验收结果**：API Ruff 通过、pytest **767 passed / 19 skipped**（+29 新例，零回归；
   H0–H3 联调套件 2 项按 H4 收尾权移交与失败阶梯同步更新）；
   Worker 48 passed；前端 `typecheck` 与生产构建通过。

### H4 与架构/计划的偏差（需评审确认）

1. **replan 折叠进 plan 节点**：架构 mermaid 画了独立 `replan` 节点，实现改为
   `reflect` 置 `force_replan` / `replan_reason` 后由 `plan` 节点消费（`state.py`
   的 `force_replan` 字段注释即为此语义），少一次无行为的跳转；
2. **clarify 判为收尾叙述而非事件**：`verdict=clarify` 只发 `assistant_message` +
   `response.completed(stop)`，**不恢复** `clarify` 持久事件与 `clarify_reply`
   上行——真正的 `interrupt + resume` 归 H5（与 H2「确认卡先 WS 直连、H5 再评估
   图内 interrupt」同节奏）。API.md V1.67 中「澄清卡待 H4 评审后恢复」据此调整为 H5；
3. **重规划沿用剩余预算**：架构未规定重规划是否重置预算，实现选择**不重置**
   （换计划不放大回合预算，服务「不允许空转至预算耗尽」）；
4. **配额为回合级而非每步级**：`MAX_REPAIRS=1` 实现为本回合最多修复一次
   （与计划表「修复最多一次、重规划最多两次并**收敛**」一致），`step_fail_count`
   仅作「当前是否存在未解决失败」的判据。

### H4 联调实测发现并修复的 H3 遗留缺陷（P1）

1. **`pending_tool.native` 恒为 True**：`graph.py` 建工具节点时未传
   `native_tool_results`，而 `NativeToolResultStore.get()` 在骨架化后**零消费方**
   ⇒ 每条工具调用都撞 fail-closed 的「工具临时上下文不可用」，`observation=None`，
   模型永远看不到文件内容。TAOR 分支是靠 `_observation_lines` 把观察注入用户
   消息的**提示词驱动**循环，已改为 `native: False`；
2. **观察以 frozen dataclass 进 State**：下游 `_observation_lines` /
   `_repeat_count` 全部用 `isinstance(x, Mapping)` 判定，dataclass 会被静默跳过
   ⇒ 模型同样看不到工具结果，且不可 `json.dumps`（H5 接 PgCheckpointer 必然失败）。
   已在 `make_tools_node` 包装层归一为纯 dict。

**H4 改动文件清单**：

- `backend/api/app/harness/feedback/review.py`：五档判决与回合级常量（唯一来源）。
- `backend/api/app/harness/prompts/protocols.py`：`REFLECT_SCHEMA` 五档枚举 + `repair_hint`。
- `backend/api/app/agent/taor_nodes.py`：新增 `make_reflect_node`；`orchestrator` 收尾权移交；
  `tools` 维护 `step_fail_count` 并归一观察为纯 dict；`plan` 消费 `force_replan`。
- `backend/api/app/agent/graph.py`：`orchestrator → reflect`、`reflect → END/orchestrator/plan`
  条件边；混合引擎开启时 `recursion_limit` 32 → 64。
- `backend/api/app/harness/memory/state.py`：新增 `final_text` / `repair_count`，五档注释对齐。
- `backend/api/tests/test_hybrid_h4_reflection.py`（新增 29 例）、`tests/test_hybrid_h3_taor.py`
  （同步收尾权移交后的 6 处断言）。
- `AGENTS.md`、`docs/AI测试与评估平台-混合驱动引擎开发计划.md`：同步 H4 实施状态与偏差。
**V1.5 H1/H2 审查修复（`fix/agent-h1-h2-routing`，2026-09-03）**：

1. **确认回放可恢复**：确认前先占用会话回合租约，避免普通回合竞争后清卡；仅 W6 返回真实 `task_id` 才发送 `confirm_ack.ok=true`。图内门禁、W6 或调度失败时恢复原 `pending_confirm` 并发送既有 `error`，不伪造成功或取消回执。
2. **产品路径归一**：将「先评后压 / 成功后压测」从 Agent 多技能计划改为 benchmark/rag Workflow 的 `with_stress=true`；Worker 仍在质量任务成功后派生压测，直接 `kind=stress` 继续 fail-closed。
3. **H1→H2 可追溯交接**：L1 `router.v1` 的已启用 `skill_id` 写入 GraphState，W0 优先采用；概念问答即使含“生成/创建”等词也不会进入确认卡路径。
4. **受控槽位装配**：W1 仅提取 `profile-*`、`ds-*` 等明确平台短 ID，W4 合并白名单槽位，避免名称猜测和未知字段注入。
5. **验收结果**：`ruff check` 通过；H1/H2 定向 `pytest` **67 passed**。无数据库模型、迁移、REST/WS 字段或默认开关变更。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/router.py` / `agent/router_node.py` | 收紧问答与执行判定，归一先评后压，传递已启用的 L1 技能。 |
| `backend/api/app/agent/workflow_nodes.py` | W0 直采 L1 技能，W1 安全提取明确 ID，W4 合并槽位并写入 `with_stress`。 |
| `backend/api/app/routers/ws.py` | 回放租约、真实任务 ID 成功回执和失败保卡恢复。 |
| `backend/api/tests/test_hybrid_h1_router.py` / `test_hybrid_h2_workflow.py` / `test_hybrid_h2_confirm_card.py` / `test_hybrid_e2e_h0_h3.py` | 新增与更新 H1/H2 审查问题的回归覆盖。 |
| `docs/AI测试与评估平台-API.md` / `docs/AI测试与评估平台-混合驱动引擎架构.md` / 本文档 | 同步 V1.69 API 契约、ADR-4 与阶段状态。 |

**V1.6 实施记录（H5 批次 2，`feat/agent-hybrid-h5-hitl-batch2`，2026-09-03）**：
按 H5 阶段目标推进持久化 HITL 的生产门禁与粘性路由支持，**契约先行**——

1. **API.md V1.70 契约先行**（C-6 红线）：恢复 `tool_approval`（服务→前端，持久化）与 `tool_approval_ack`（前端→服务，恢复回执）为现行事件；补 `meta`（`schema_version`/`confirm_type`/`thread_id`/一次性 `resume_nonce`/`owner_id`/`created_at`）、resume 至多一次、粘性路由前提说明；§4.4 上行枚举升至四类、§9 同步、`worker.sandbox` 注释更新为批次 2 前置；
2. **HITL 检查点启动门禁**：`config.py` 新增 `agent_hitl_strict_pg`（默认 false）与 `agent_instance_id`；`main.py` lifespan 新增 `_validate_hitl_checkpointer`——混合引擎 + memory + strict 时 fail-fast（`AppError(VALIDATION)`），非 strict 仅告警；`checkpoint.py` 文档同步生产切换路径；
3. **实例标识（粘性路由支持）**：`main.py` 新增 `_resolve_instance_id`（显式配置优先，空时派生 `hostname:pid`），`/api/health` 暴露 `instance_id` 供网关按 `session_id` 粘性路由识别副本；`.env.example` 同步三项新配置；
4. **测试资产**：新增 `tests/test_hybrid_h5_batch2.py`（9 例）覆盖门禁四档（关闭/postgres/strict fail-fast/非 strict 告警/大小写）、实例标识派生与 health 端点；
5. **验收结果**：`ruff check . ../shared` 通过；API 全量 `pytest` **794 passed / 20 skipped**（+9 新例，零回归；2 项既有失败在 main 上同样存在）；Worker 48 passed；前端 `typecheck` 与生产构建通过。

**H5 批次 2 未完成项（阻断 HITL 正式发布，须后续 PR 接力）**：
- `AGENT_CHECKPOINTER=postgres` 生产实际切换（本批次仅落门禁与文档，未翻默认——单副本 dev 与测试仍用 memory 验证 interrupt 语义）；
- 网关粘性路由落地（nginx `sticky session_id` upstream 配置，当前单副本天然满足）；
- 重启恢复演练（Linux/Docker：人为中断 → 重启 api → 按审批记录恢复原 `thread_id`，验证至多一次、不重放 `pending_events`）；
- `worker.sandbox` 安全评审（上述三项完成后方可从 `discover.excluded` 移除）。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | V1.70 契约先行：恢复 `tool_approval`/`tool_approval_ack`、补 `meta` 与 resume 语义、上行枚举升至四类、`worker.sandbox` 批次 2 前置注释 |
| `backend/api/app/config.py` | 新增 `agent_hitl_strict_pg`（HITL 生产门禁）与 `agent_instance_id`（粘性路由标识） |
| `backend/api/app/main.py` | lifespan 新增 `_validate_hitl_checkpointer` 启动门禁；新增 `_resolve_instance_id`；`/api/health` 暴露 `instance_id` |
| `backend/api/app/harness/memory/checkpoint.py` | `get_default_checkpointer` 文档补 H5 批次 2 生产门禁路径 |
| `.env.example` | 同步 `AGENT_HITL_STRICT_PG` / `AGENT_INSTANCE_ID` 配置说明 |
| `backend/api/tests/test_hybrid_h5_batch2.py`（新增 9 例） | 覆盖门禁四档、实例标识派生与 health 端点 |
| `docs/AI测试与评估平台-混合驱动引擎开发计划.md` / `AGENTS.md` | 同步 H5 批次进度与实现状态地图 |
