# AI 测试与评估平台 — dsh 借鉴与 Agent Harness 改进方案

> 📦 **历史归档（2026-09-11）**：本文为历史设计稿 / 规划，其中提及的 `agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除或演进，仅作决策留痕；请勿按本文直接立项。

> 版本:V1.5 | 状态:五项已实施交付（2026-09-07，见 §九） | 审查:2026-09-07
>
> 背景:2026-09-07 对 DeepSeek 开源 Agent Harness（`dsh`，本地源码
> `C:\Users\gustchen\Desktop\deepseek-harness`）完成两轮只读调研（dsh 工程架构分析 +
> 本平台 Agent 子系统现状对照）。用户裁决:**不引入 dsh 运行时**，仅以其设计为蓝本
> 改进本项目 LangGraph Agent harness；确认立项 #1–#5 五项借鉴改进。本文档为立项
> 依据与分期计划，纯文档变更，不含代码。
>
> 评审:V1.0 于 2026-09-07 完成内部评审（对照 PRD / API.md V1.70 / 代码锚点交叉
> 核验）；按评审意见 R1–R5 修订实质问题、S1–S5 采纳轻量建议，升版 V1.1。
> V1.2（2026-09-07）：#4 代码勘察发现现状事实偏差（R6），同步修正 §二 与 §3.4，
> 并将 #4 详细设计（D1–D6）并入 §3.4。修订明细见 §十。
> V1.3（2026-09-07）：新增 §七「项目影响与变化总览」（代码/契约/数据与运行时/
> 行为/测试 CI/风险依赖/不发生清单）；原 §七–§九 顺延为 §八–§十。
> V1.4（2026-09-07）：文档结构评审修订（R7/R8）：补「### 6.2 预期契约修订清单」
> 标题消除引用悬空、修复 §六 编号断链、V1.3 修订行移入独立 §10.3；修订明细见 §十。

---

## 一、背景与目标

### 1.1 一句话背景

平台 Agent 现状:默认骨架化纯对话（`START → chat_stream → END`），混合引擎
（Router 四路分流 / W0–W7 Workflow DAG / TAOR + reflect 失败阶梯 / H5 HITL 审批）
在 `hybrid_engine_enabled=false` 时整体不生效。V1.7 状态地图已登记一批未完成项
（H5 批次 2:`AGENT_CHECKPOINTER=postgres` 生产切换、网关粘性路由、重启恢复演练、
`worker.sandbox` 安全评审；`clarify` 事件未恢复；超长上下文精度衰减为已知遗留）。

### 1.2 dsh 是什么（调研摘要）

- DeepSeek 官方开源 Agent Harness，MIT，`0.1.2-rc.1` **开发者预览**（破坏性变更
  无承诺，`SESSION_FORMAT_VERSION=0`，后端拒旧格式）。
- TypeScript/Node monorepo（约 250 个 `@deepseek-ai/dsh-*` 包，vendored Cordis 插件
  内核）；**不存在 Python agent runtime**——官方 `deepseek-harness-sdk` 只是子进程
  JSON-RPC 客户端投影，agent 逻辑全在 TS。
- 核心设计：一切皆插件；capability seam（Service Definition / Provider / Consumer
  三件套，换 Provider 即换产品行为）；会话事件日志为真源（模型可见 ⟺ 已记录，
  turn/step 生命周期、中断回合合成收尾、崩溃后恢复）；HITL 完备（一次性 approval
  + 会话级策略 + ask_user 问答 + UI 审批卡）；上下文 compaction（log-only 压缩事件
  + replace 语义落库 + 超大工具结果裁剪）；模型不锁 DeepSeek（OpenAI 兼容
  baseURL / anthropic-messages 均可路由）。

### 1.3 复用裁决（已确认）

| 裁决项 | 结论 | 依据 |
| :--- | :--- | :--- |
| 引入 dsh 运行时（TS/Node、子进程桥接、独立容器） | **不引入** | 与本平台 Python/FastAPI 栈、`ws_events` 事件契约、`pending_confirm` 行锁协议、前端卡组件均需双协议映射；能力面（fs/shell/LSP/skill/subagent…）超出 PRD 范围；零运行时成本诉求 |
| 整体替换 LangGraph 混合引擎 | **不做** | 与 ADR-9「禁止重写 Harness，恢复接线 + 增量升级」、API.md §11.4「扩展只能在 LangGraph 图中加节点/边」直接冲突，属架构裁决级变更 |
| 复制 dsh 会话 JSONL 格式/词汇表 | **不做** | 我们已有 PG 会话 + `ws_events` 回放体系，语义同构处只做对照验证 |
| 以其设计为蓝本改进现有 harness | **确认立项** | 下文的 #1–#5，均与既有遗留项对齐，不超 PRD |

### 1.4 本方案目标

把 dsh 调研中「我们缺、且补上后收益明确」的设计，落成 5 个可独立灰度、契约先行的
改进项，并给出分期与依赖；同时明确范围外禁止项，防止范围蔓延。

---

## 二、现状对照映射（dsh 设计 ↔ 本项目现状 ↔ 差距）

| dsh 设计（来源） | 本项目现状（文件锚点） | 差距 / 改进点 | 立项 |
| :--- | :--- | :--- | :--- |
| `ask_user_question`：AskUserQuestionItem（id/question/detail/options/multiSelect/intent）+ agent-scoped waterfall answerer | `harness/execution/toolnode.py` 已有 `interrupt({"type":"clarify",…})`（无生产者接线）；`harness/execution/ask_user.py` 已实现 questions 校验（radio/checkbox/text、≤8 题）与 `answers_from_reply` 按行投影；`routers/ws.py::_handle_graph_interrupt` 仅处理 `type=tool_approval`，其余类型不落卡返回 False；`harness/contracts/events.py` 词汇表已含 `clarify` | clarify 是「有中断、无卡、无回执、无前端」的半成品；`clarify_reply` 为 PRD 既有上行、API.md 标历史资料待评审恢复 | **#1** |
| compaction：log-only 事件 + `surfaceOp: replace` 落库可回放 + `toolResultPruner` 先裁剪 + token 压力触发 | `harness/context/window.py::recent_window`（默认末 20 条）+ `compact_keep_from`；Observation 全文禁止入检查点/持久事件；「超长上下文精度衰减」为遗留可选项 | 硬裁剪不可回放、无裁剪留痕、超大 tool_result 直接占窗 | **#2** |
| user-approval：`ApprovalOutcome` 闭合（allowed-once/rejected/cancelled/**unavailable** fail-closed）；会话级 `ApprovalPolicy`（ask/never，以日志策略事件为真源）；UI 失效态与升级文案 | `ws.py::_persist_pending_approval` / `_handle_approval_ack`（行锁 + `resume_nonce` 一次性 + resume 至多一次，**消费即失效**）；无超时/不可达终态；演练放行靠 `agent_drill_sandbox_enabled`（默认 false） | 卡无过期语义、无 cancelled/unavailable 区分 | **#3** |
| `SESSION_FORMAT_VERSION` + 拒未知事件（`ignorable: true` 例外） | `harness/contracts/events.py` **已有** `EVENT_VERSION="event.v1"`（M7-Q4）与 `NodeEvent.event_version`，但**未生效**：`_translate_event` 不读版本、`_emit_persistent` 落库丢失版本、Worker `push_ws` 无版本、`_forward_loop` 转发无校验；词汇表碎片化（`NodeEventKind`/`_PERSISTENT_KINDS`/ws.py 与 worker 直产字符串与 API.md §4.3 无单一事实源）；`ws_events` 公共头无版本字段 | 版本机制有雏形无语义：增删 kind 无强制递增、未知 kind 无护栏（Worker 直写时尤其危险） | **#4** |
| capability seam：request/spec 显式 `resolve()`（Explicit > implicit at package boundaries） | `sandbox_engine` / `SANDBOX_RUNNER_URL` 决策分散；`worker.sandbox` 在 discover 静态排除（fail-closed）；工具执行在 `toolnode.py`/`registry.py` 内联决策 | 沙箱/执行选择无单一审计面，`worker.sandbox` 安全评审缺前置收敛 | **#5** |
| guard 循环卫生 / tool-timeout 插件化 | 回合硬上限常量唯一来源 `harness/feedback/review.py`（`MAX_REPAIRS=1`/`MAX_REPLANS=2`） | 无差距（现有已足够） | 暂缓（范围外） |
| 会话事件日志真源 / turn 唯一收尾 / 断线重放 | `ws.py::_claim_terminal`（每轮恰一 `response.completed` 且为最后一条持久事件）、`ws_events` 按 `last_event_id` 补发、H5 检查点 resume | 同构，仅对照验证 | — |

---

## 三、立项改进项

### 3.0 通用纪律（每项适用）

1. **契约先行**：涉及 API.md/PRD/前端先改文档（#1 的 `clarify_reply` 走 §3.1.1
   契约裁决记录的转正路径）；
2. **只动既有接缝**：仅改 LangGraph 图内节点/边或既有卡/事件机制，禁止另起并行
   路径、禁止整体替换引擎；
3. **灰度开关登记制**：新增开关必须默认 false、登记于 §6.3 开关登记表、复盘后
   删除（参照 `agent_drill_sandbox_enabled` 教训）；优先复用既有门控
   （`hybrid_engine_enabled`）而非新增并列开关；
4. 提交前通过 ruff/pytest/typecheck/build 门禁；全中文注释；契约评审留档。

### 3.1 立项概览

| # | 改进项 | 优先级 | 预估规模 | 主要契约面 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | clarify 问答恢复 | P1 | M | API.md §4.3 / §4.4 / §9 / §2 总表；前端统一卡基类 |
| 2 | 上下文压缩事件化 | P1 | M | API.md §4.3（留痕事件 kind 裁决，见 §6.2） |
| 3 | 审批终态（含前端失效态） | P1 | S | API.md §4.3 终态事件；前端 ApprovalCard 失效态 |
| 4 | 事件词汇表版本化 | P1（护栏前置） | M | API.md §4.2 公共头 vocab_version、§4.3 版本语义与演进纪律 |
| 5 | 执行选择显式化 | P2 | M | 无对外契约（内部重构 + 审计面） |

> 规模为相对人日粗估（S ≤ 1d、M ≤ 3d、L > 3d），不含契约评审、前端联调与测试
> 复活；排期以实际为准。#4 于 V1.2 完成代码勘察并细化设计后由 S 上调为 M。

---

### #1 clarify 问答恢复（P1，规模 M）

#### 3.1.1 契约裁决记录（对应评审 R1）

- **出处与现状**：PRD（L0，功能范围权威）的前端 → 服务上行清单自始包含
  `clarify_reply {id, answer}`——澄清问答的产品范围从未被 PRD 删除；V1.63
  骨架化把 `clarify` / `clarify_reply` 一并移除；API.md V1.70 将二者标为
  「历史资料，待 H5 批次 2 / 后续评审后恢复」（§4.4 及下方注释、§4.3 标注
  `clarify` 无生产者、§9 措辞仍含「第五种 WS 上行事件」红线表述）。
- **裁决**：恢复 `clarify_reply` 属向 PRD（L0）对齐的**契约转正**，不是产品范围
  扩张；例外成立的前提是走完整转正路径并在本文档与 API.md 修订记录留档——
  ① API.md §4.3 将 `clarify` 从「无生产者」转正为现行事件并定 payload；
  ② API.md §4.4 将 `clarify_reply` 从历史资料转正为现行上行；
  ③ API.md §9 同步修订「第五种上行」红线措辞为「上行事件以 §4.4 现行清单为准，
  任何新增/恢复必须经契约评审」；④ §2 前后端对应总表与头部修订记录同步。
- **回滚条件**：若恢复后破坏「每轮恰一 `response.completed`」、三类卡互斥或
  历史回放（`ws_events` 中 V1.62 旧 clarify 事件不得渲染），回退为「无生产者」
  状态并同步回退 API.md（参照 V1.63/V1.70 既有回退路径）。

#### 3.1.2 卡存储路线裁决（对应评审 R2）

历史契约（API.md §4.4 下方 V1.62 资料，骨架化前）规定澄清卡「不写
`pending_confirm`、进程内追踪、不占回合预算」——该语义产生于**无检查点 resume
的前 H5 时代**；H5 起 `tool_approval` 已确立「`pending_confirm` 行锁 +
`meta{schema_version=1, thread_id, resume_nonce}` + `Command(resume)` + 至多一次」
模式。恢复 clarify 需在两条路线中裁决：

| 维度 | A 路线：延续 V1.62 语义 | B 路线：H5 同构（推荐） |
| :--- | :--- | :--- |
| 卡状态 | 不落 `pending_confirm`，进程内追踪 | 三类卡共用 `pending_confirm` 单行，`meta.confirm_type` 扩展 `clarify` |
| 回执/resume | `clarify_reply` 直接续跑（无行锁） | 行锁清卡先行 + `Command(resume)`，resume 至多一次 |
| 跨 api 重启 | 中断回合随 memory 检查点丢失，卡态不可寻址 | `meta.thread_id` 可寻址，对齐 H5 批次 2 PG 检查点方向 |
| 实现成本 | 轻（无行锁/一次性逻辑） | 中（`meta` 升版 + 卡种枚举扩展 + 三类互斥回归） |
| 与既有模式一致性 | 低（tool_approval 已走行锁） | 高（复用同一套行锁/清卡/ack 纪律） |

**推荐：B 路线**。理由：与已交付 H5 模式同构；卡与中断回合可跨重启寻址（与
`AGENT_CHECKPOINTER=postgres` 方向一致）；前端/ws 层复用一套纪律。代价为
`meta.schema_version` 升版与 `confirm_type` 枚举扩展，实施时须验证对
`confirm_ack`（W5）/ `tool_approval_ack` 既有路径**零影响**。若评审后续改选 A，
本节与 API.md 的差异记录需同步改写（历史语义「不写 `pending_confirm`、不占回合
预算」与 H5 中断回合占检查点的语义冲突须一并说明）。

**三类卡互斥矩阵**（`pending_confirm` 单行「至多一张」由两类扩为三类）：
- `task_confirm`（确认卡）仅 Workflow 链 W5 产生；`tool_approval`（审批卡）与
  `clarify`（澄清卡）仅 agent(TAOR) 子图工具执行产生——同一回合只走一条引擎链，
  三类卡**天然互斥、不可能并存**；
- 防御层不变：行锁 + 「已有任何待处理卡 → CONCURRENCY」兜底（`ws.py` 现有语义）；
- 恢复 clarify 不改变 W5 重放语义与入队唯一经 W6 的约束。

#### 3.1.3 目标设计

1. `toolnode.py` 的 `clarify` interrupt 接线（按 B 路线）：`ws.py::_handle_graph_interrupt`
   对 `type=clarify` 落卡（`meta.confirm_type=clarify` + `thread_id` + 一次性
   `resume_nonce`）并广播持久 `clarify` 事件，返回 True 暂停回合；
2. `clarify_reply` 经 §3.1.1 转正为现行上行；payload 定稿二选一（实施前在契约
   评审定稿并留档）：V1.62 单卡纯文本 `{id, answer}` vs 按 `ask_user.py` 已实现
   的多题结构 `{questions[] → answers[]}`（≤8 题、radio/checkbox/text、
   `answers_from_reply` 按行对齐投影已就绪）。**建议以多题 `answers[]` 结构升级
   转正**，一次答完，前端体验与 tool_approval 卡一致；
3. resume：行锁清卡先行 → `Command(resume={answers…})` → `toolnode` 按答复
   放行；重复/并发 `clarify_reply` 拒绝且不改变状态（沿用一次性纪律）；
4. 前端约束（S2）：澄清卡与既有卡收敛为**统一卡基类**（历史 ClarifyCard 已删，
   重建时复用 ConfirmCard/ApprovalCard 的 owner/一次性/乐观盖章模式，禁止第三个
   近似独立组件）；事件回放态只读；
5. 测试基线：复活 `backend/api/tests/test_ws_clarify.py`（API.md 测试清单仍引用
   该文件），按新契约改写。

#### 3.1.4 验收要点与边界

- 模型提问 → 澄清卡展示（≤8 题/三题型）→ 用户作答 → 回合按 answers 续跑；
  每轮仍恰一个 `response.completed`；重复/过期 `clarify_reply` 拒绝。
- 涉及模块：`routers/ws.py`、`harness/execution/{toolnode,ask_user}.py`、
  `harness/contracts/events.py`、`harness/security/auth.py`（行锁复用）、前端
  `Agent.vue` 事件分支与卡组件、`api/ws.ts` 上行方法。
- 风险/边界：与 H5 卡共用单行的行锁与一次性纪律必须复用，禁止另开状态字段；
  历史 `ws_events` 中旧 clarify 事件不回放渲染；跨重启寻址依赖 H5 批次 2 的
  PG 检查点切换与粘性路由（单副本/memory 检查点下先交付单副本语义，与 V1.70
  `tool_approval` 现状一致）。

---

### #2 上下文压缩事件化（P1，规模 M，紧随 #4）

#### 3.2.1 动机

治理「超长上下文精度衰减」遗留项；硬窗裁剪丢信息且**不可回放、不可审计**。

#### 3.2.2 dsh 借鉴

`packages/compaction/`——压缩事件 log-only 留痕；`toolResultPruner` 先裁剪超大
工具输出再压缩；`agent/pre-step` 按 token 压力触发。

#### 3.2.3 目标设计（首期落地物已收敛，对应评审 R4）

**首期（本文档立项范围）**：
1. **超大 `tool_result` 先裁剪**：在 `harness/execution/native_results.py`
   （NativeToolResultStore 按 thread 暂存处）加长度上限与**截断标注**，先裁剪再
   进窗口——模型只见带标注的截断结果；
2. **窗口裁剪事件化留痕**：发生窗口裁剪时落一条持久事件/记录（触发原因、保留
   策略、被裁范围元信息），事件流可回放、可审计；**首期不做 LLM 摘要**（摘要
   来源未定之前，避免回合内二次模型调用的成本/中止语义问题）；
3. `recent_window` + `compact_keep_from` 算法兜底不变（行为默认不变）。

**二期增强（不在本文档立项，另立小方案）**：模型摘要 + replace 落库语义
（参照 dsh `surfaceOp: replace`），需契约评审 kind 与展示语义。

#### 3.2.4 契约影响、验收与边界

- 契约影响：API.md §4.3（留痕事件以独立 kind 还是复用现有 kind 呈现，经 #4
  版本化后裁决，见 §6.2 预期契约修订清单）；遵守「Observation 全文禁止写入
  检查点/WS 持久事件」纪律——裁剪留痕只落元信息，不落原文全文。
- 验收：长回合进入窗口的字节/条数下降且行为不变（对照用例回归）；截断标注
  可回放；每轮恰一 completed 不破坏；窗口算法文档同步。
- 边界：首期收益以可观测性 + 防超大工具结果占窗为主，量化指标在立项时定。

---

### #3 审批终态（P1，规模 S；范围已收敛，对应评审 R5）

#### 3.3.1 动机

审批卡无过期/不可达终态——会话关闭、引擎异常、`/stop` 后卡仍悬挂或回执路径
不清；`cancelled` 与 `rejected` 未区分。

#### 3.3.2 dsh 借鉴

`ApprovalOutcome` 闭合（allowed-once/rejected/cancelled/unavailable fail-closed）
+ UI 失效态。

#### 3.3.3 首期目标设计

1. **审批卡 TTL/会话失效扫描**：参照 `backend/worker/app/testcase.py` 既有 72h
   确认超时扫描模式，对 `pending_confirm`（`tool_approval` 类）做 TTL 失效判定；
   扫描归属倾向 api 侧（卡生命周期在 `sessions` 表与 api 检查点侧），但**失效
   判定以卡 `created_at` + 当前时间兜底（幂等）**，不依赖扫描进程存活性；
2. **终态语义区分**：`rejected`（用户拒绝）/ `cancelled`（`/stop`、会话关闭、
   回合取消）/ `expired`（TTL 失效）分别落持久终态事件（kind 经 #4 版本化后
   裁决，见 §6.2）；失效后 ack 一律拒绝且不触发 resume（沿用一次性纪律）；
3. **前端失效态**：`ApprovalCard.vue` 增加 disabled/expired 态展示（卡失效后
   按钮不可操作）。

#### 3.3.4 降级项（P3，不在本文档立项范围）

会话级审批策略行（ask/never）：当前无 headless 场景，唯一动机为演练开关收敛，
属过度设计风险；待演练复盘后再议。如需引入须另走契约评审（可能涉及
`models.py` 字段与 Alembic，契约修订影响见 §6.2 预期契约修订清单）。

#### 3.3.5 契约影响、验收与边界

- 契约影响：API.md §4.3 终态事件 kind 与 payload；前端 ApprovalCard 失效态。
- 验收：卡过期后 ack 被拒且不 resume；终态事件可回放；同一会话仍至多一张卡；
  与 #1 的 clarify 卡（B 路线）共用行锁互斥语义不冲突。
- 边界：默认行为不变（无策略即 ask，fail-closed）；TTL 常量入 config 或既有
  Setting，禁止硬编码。

---

### #4 事件词汇表版本化（P1，护栏前置：一期首项；对应评审 R3；V1.2 代码勘察修正并落地详细设计）

#### 3.4.0 勘察结论（V1.2 事实修正，对应评审 R6）

V1.1 曾描述「词汇表无版本号」。2026-09-07 代码勘察（`contracts/events.py` /
`routers/ws.py` / `worker/app/events.py` 只读核验）修正为：**版本机制已有雏形但
从未生效**，且词汇表碎片化：

| 路径 | 现状事实 |
| :--- | :--- |
| 图内契约 `harness/contracts/events.py` | 已有 `EVENT_VERSION="event.v1"`（M7-Q4 裁决）、`NodeEvent.event_version` 字段、`make_event()` 自动注入 + 图内白名单（未知 kind → ValueError） |
| api 翻译层 `_translate_event`（ws.py） | **不读** `event_version`；未知 kind 无校验，落默认分支直接落库广播 |
| api 落库 `_emit_persistent`（ws.py） | 只落 `event/payload/task_id/event_id/ts`——**版本字段在此丢失**；`ws_events` 表无版本列 |
| Worker 直写 `worker/app/events.py::push_ws` | 无版本概念，任意 `event` 字符串直写 `ws_events` |
| 转发 `_forward_loop` | 从 `ws_events` 读取转发，**无任何校验** |
| 词汇表组织 | 碎片化无单一事实源：`NodeEventKind`（图可产 13 类）+ `_PERSISTENT_KINDS`（15 类）+ ws.py/worker 直产字符串（`task_cancelled`/`session_title` 等不在上述集合），与 API.md §4.3 全量清单靠人肉对齐 |

**结论**：#4 不是「引入版本字段」，而是「把已有 `EVENT_VERSION` 语义化 + 建立
词汇表单一事实源 + 打通三条路径校验」。**新增事件类型（#2/#3）必须先经本项落地**，
否则护栏不成立。

#### 3.4.1 动机（修订）

api/worker 版本漂移无护栏——Worker 直写 `ws_events`（progress/report/error），
`_forward_loop` 转发不校验 kind；图内新增事件类型后旧 api 可能误译（#2 的新
kind、#3 的终态 kind 均依赖本项先立护栏）。

#### 3.4.2 dsh 借鉴

`SESSION_FORMAT_VERSION` + 拒未知事件（`ignorable` 例外）——「后端拒旧格式」的
简洁方向，不做跨大版本迁移机制。

#### 3.4.3 目标设计（V1.2 详细设计 D1–D6）

**D1 — 词汇表单一事实源（核心）**
- 新增 `backend/shared/event_vocab.py`（api/worker 共用，遵循 shared 单一事实源
  纪律）：`PERSISTENT_KINDS` 全量持久事件注册表（对齐 API.md §4.3，补
  `task_cancelled`/`session_title`/`confirm_ack` 等现有缺口）、`NODE_EVENT_KINDS`
  图可产子集、`EVENT_VERSION` 语义化（**增删 kind 必须递增** `event.v2`…，演进
  规则入模块 docstring 与 API.md）、`is_persistent()` 等辅助函数上移；
- `api/app/harness/contracts/events.py` 与 `worker/app/events.py` 改为从 shared
  引用，消灭两份碎片集合。

**D2 — 契约（先行）**
- API.md §4.2 公共头增补可选 `vocab_version` 字段（服务端恒发；旧客户端按既有
  原则忽略未知字段，**无前端改动**）；
- API.md §4.3 注明词汇表版本语义与演进纪律（增删事件必须递增 + 本文档 §6.2 同步）。

**D3 — 三条路径打通**
- `_translate_event` 入口校验：`event_version` 与当前版本不符 → 按当前词汇表
  翻译 + 日志告警；未知 kind → 灰度告警；
- `_emit_persistent` 落库：公共头带 `vocab_version`（随帧广播）+ payload 保留
  字段留版本（免 `WsEvent` 加列/Alembic，向后兼容）；
- `worker/app/events.py::push_ws` 从 shared 注入版本常量，写库与 api 同构；
- `_forward_loop` 转发校验：未知 kind / 版本不符 → 新开关 `event_vocab_strict`
  （默认 `false`：告警 + 跳过不转发；`true`：fail-closed 拒收并落 `error` 事件）。
  开关登记 §6.3。

**D4 — 兼容与灰度**
- 历史 `ws_events` 无版本行按当前版本解释（缺省 `event.v1`，向后兼容只读）；
- 灰度默认 `event_vocab_strict=false`，稳定后置 `true` 并评估去开关。

**D5 — 测试清单**
- 注册表完整性断言：全量清单 vs `NodeEventKind`/ws.py/worker 直产点一致性
  （防再次漂移——对照 dsh 的 verify 门禁思想）；
- `_translate_event` 未知 kind / 版本不符告警路径单测；
- `push_ws` 写库带版本断言；历史无版本行回放兼容测试。

**D6 — 影响面**
- `backend/shared/event_vocab.py`（新）、`harness/contracts/events.py`、
  `routers/ws.py`（`_translate_event`/`_emit_persistent`/`_forward_loop`）、
  `worker/app/events.py` 及 `push_ws` 调用方（经统一函数免逐个改）、`config.py`
  （新开关）、API.md §4.2/§4.3、相关测试（`test_ws_protocol.py` 等）。

#### 3.4.4 契约影响、验收与边界

- 契约影响：API.md §4.2（公共头 `vocab_version` 可选字段）、§4.3（词汇表版本
  语义与演进纪律）；前端无改动（旧客户端忽略未知字段）。
- 验收：D5 测试全绿；现有事件全量通过、行为默认不变；`event_vocab_strict=false`
  灰度路径与 `true` fail-closed 路径均被单测覆盖；历史无版本行兼容。
- 边界：与 PG 检查点切换无耦合，H5 批次 2 若阻塞可先行（见 §4.2 降级路径）；
  禁止为版本化引入跨大版本迁移机制（沿用「后端拒旧格式」简洁方向）。

---

### #5 执行选择显式化（P2，规模 M，随 `worker.sandbox` 安全评审同批）

#### 3.5.1 动机

`worker.sandbox` 是 H5 批次 2 未完成项之一；工具/沙箱执行决策分散在
toolnode/registry 内联，缺少单一审计面，安全评审难以闭环。

#### 3.5.2 dsh 借鉴

capability seam「换 Provider 即换行为」+ request/spec 显式 `resolve()`（默认化是
显式决策步骤，不做隐藏 `?? default`）。

#### 3.5.3 目标设计

1. 收敛「工具执行/沙箱选择」为显式 resolve 点：输入（工具名、命令、会话/演练
   上下文）→ 输出明确 Spec（runner bwrap 沙箱 / drill 放行 / 白名单排除
   fail-closed），决策集中一处可审计、可单测；
2. `worker.sandbox` 的 discover 静态排除与 `agent_drill_sandbox_enabled` 语义迁移
   为 Spec 决策的分支输入，**默认行为不变**（演练后必须复位）；相关开关登记
   §6.3；
3. 不引入抽象框架/新依赖，仅收敛决策点并配中文注释。

#### 3.5.4 契约影响、验收与边界

- 契约影响：无对外事件/字段变化（内部重构 + 审计面）。
- 验收：三档单测（常规沙箱 / drill 放行 / 排除 fail-closed）；discover 白名单
  行为与现状一致；`agent_drill_sandbox_enabled=false` 默认路径全量回归。
- 边界：属内部重构；与 worker.sandbox 安全评审结论联动，评审结论可能调整 Spec
  分支。

---

## 四、分期与依赖

### 4.1 依赖关系

```text
P0 前导（既有立项，非本文档范围）:H5 批次 2 收口
        └── PG 检查点生产切换 / 粘性路由 / 重启演练 / worker.sandbox 安全评审
                                    │
                                    ▼
#4 事件词汇表版本化（P1 护栏，先行） ──► #2 上下文压缩事件化（依赖 #4 新增 kind）
#1 clarify 问答恢复（契约转正；卡路线 B 依赖 #4 词汇表一致性）
#3 审批终态（终态 kind 依赖 #4；行锁互斥与 #1 共用语义）
                                    │
                                    ▼
#5 执行选择显式化（随 worker.sandbox 评审同批，独立可并行）
```

### 4.2 分期

| 期 | 项 | 说明 |
| :--- | :--- | :--- |
| 前置 | H5 批次 2 收口 | 不属本文档立项，但 #1/#3 的跨重启寻址完整价值依赖 PG 检查点切换与粘性路由；#5 与 `worker.sandbox` 评审捆绑 |
| 一期（P1） | #4 → #1 → #3 → #2 | #4 先立词汇表护栏；#1（契约转正 + 卡路线 B）与 #3（行锁互斥）需同批评审避免契约打架；#2 紧随 #4 |
| 二期（P2） | #5 | 随安全评审窗口排期，可与一期并行 |

**前置阻塞降级路径**（对应评审 S5）：#4（词汇表版本化）与 PG 检查点切换无耦合，
H5 批次 2 若阻塞可先行解耦评审；#1/#3 在 memory 检查点单副本下先交付单副本语义
（与 V1.70 `tool_approval` 现状一致），跨重启寻址能力随 PG 切换同步放行。

### 4.3 灰度原则

每个 # 项独立开 `feat/agent-*` 分支、独立 PR、沿用「开关默认关 → 评审 → 灰度 →
默认语义不变」的既有节奏（参照 H0–H5 交付模式）；新开关一律登记 §6.3；纯契约
改动走 `docs/` 分支先行。

---

## 五、范围外与禁止项（防止蔓延）

1. 不引入 dsh TS/Node 运行时、不新增容器/二进制、不引入官方 Python SDK 依赖；
2. 不整体替换 LangGraph harness（ADR-9），禁止复制 dsh 会话 JSONL 格式与
   `SESSION_FORMAT_VERSION` 语义之外的机制；
3. dsh 的 fs/shell/LSP/skill/subagent/workflow/todo/plan/compaction 完整能力不立项
   （超出 PRD，仅吸收其中映射到 #1–#5 的设计思想）；
4. guard/tool-timeout 插件化暂缓（现有 `review.py` 回合硬上限已足够）；
5. **未经契约评审不得新增/恢复 WS 上行或事件 kind**；`clarify_reply` 属 PRD 既有、
   按 §3.1.1 裁决走转正路径（例外成立且必须留档）；任何新事件/字段必须先经
   契约评审；
6. 改代码前必须确认不在 `main` 直接开发；提交前过本地全部门禁。

---

## 六、文档与契约闭环要求

1. 本文档头部版本与审查日期随进展更新；每完成一项，在 §九「修改代码文件与作用
   清单」追加清单并升版本号；
2. 契约面改动顺序：先改 `docs/AI测试与评估平台-API.md`（V 号递增）→ 实现 →
   前端 → 测试；#1 的 `clarify_reply` 属历史资料待评审恢复项，恢复前必须完成
   §3.1.1 转正评审；
3. 本文档仅承诺方向与边界；各 # 项开工前按仓库惯例补充各自的详细技术方案或直接
   以本文档对应小节为方案基础（视改动量定）；
### 6.2 预期契约修订清单（随各项实施同步更新；对应评审 S1）

| # | API.md 需改点 | PRD | 前端 |
| :--- | :--- | :--- | :--- |
| 1 | §4.3 `clarify` 转正；§4.4 `clarify_reply` 转正（payload 定稿留档）；§9 红线措辞；§2 总表；头部修订记录 | 核对（范围已在，无需扩） | 统一卡基类 + 澄清卡 |
| 2 | §4.3 留痕事件 kind（裁决：独立 kind vs 复用现有帧） | — | 视 kind 是否展示 |
| 3 | §4.3 终态事件 kind（rejected/cancelled/expired）与 payload | — | ApprovalCard 失效态 |
| 4 | §4.2 公共头增补 `vocab_version`（可选字段）；§4.3 词汇表版本语义与演进纪律 | — | 无（旧客户端忽略未知字段） |
| 5 | — | — | — |

### 6.3 灰度开关登记表

> 登记原则（§3.0-3 开关登记制落点）：名称 / 引入项 / 默认值 / 复盘删除条件
> 四项必填；新开关一律默认 false、复盘后删除；参照教训：
> `agent_drill_sandbox_enabled`（默认 false，演练后必须复位）——新增开关不得
> 成为常驻配置。

| 开关名 | 引入项 | 默认值 | 复盘删除条件 |
| :--- | :--- | :--- | :--- |
| `event_vocab_strict` | #4 | false | 灰度观察期（生产无未知 kind/版本告警）后置 true；若 fail-closed 长期必要，评估是否固化为常驻校验而非开关 |
| （实施时登记） | #N | false | （描述放行条件与删除时机） |

---

## 七、项目影响与变化总览（V1.3）

> 本节汇总 #1–#5（含前置 H5 批次 2）落地后对项目的全部影响与变化，供立项评审与
> 排期对照。核心承诺：形态不变、零新容器、零新运行时依赖、零数据库迁移；全部
> 用户可感知变化都在 `hybrid_engine_enabled=true` 门内，默认骨架化对话行为不变。

### 7.1 代码影响矩阵

| # | 改动性质 | 涉及文件（现状 → 变化） | 说明 |
| :--- | :--- | :--- | :--- |
| 前置 | — | `checkpoint.py`、网关/`/api/health` 粘性、`cleanup.py` | 既有 H5 批次 2 收口，非本文档新增 |
| #4 | 新增+修改 | `backend/shared/event_vocab.py`（**新，api/worker 共用**）→ `api/app/harness/contracts/events.py` 改引用 → `routers/ws.py`（`_translate_event`/`_emit_persistent`/`_forward_loop`）→ `worker/app/events.py::push_ws` | `EVENT_VERSION` 语义化：注册表单源 + 落库留版本 + 转发校验；`push_ws` 各执行器调用方经统一函数免逐个改 |
| #1 | 修改+接线 | `routers/ws.py`（`_handle_graph_interrupt` 增 clarify 分支、新 `_handle_clarify_reply`）、`toolnode.py`（clarify resume 放行）、`ask_user.py`（接投影）、`harness/security/auth.py`（行锁扩卡种）、`contracts/events.py` | `ask_user_question` 从不可达 → 提问/卡/答/续跑全链路 |
| #3 | 修改 | `routers/ws.py`（TTL 判定/终态事件）、api 侧定时扫描（参照 worker 72h 模式）、前端 `ApprovalCard.vue` | 审批卡从无限期悬挂 → 过期/取消有终态 |
| #2 | 修改 | `harness/context/window.py`、`harness/execution/native_results.py`（截断标注）、`contracts/events.py`（留痕 kind，依赖 #4） | 硬窗裁剪从无痕丢弃 → 可回放留痕 + 超长结果先裁剪 |
| #5 | 重构 | `harness/execution/toolnode.py`、`harness/orchestration/agents.py`、`harness/security/`（收敛 resolve 决策点） | 内部重构，对外零契约 |

> 共同点：全部落在既有接缝（图内节点/边、`pending_confirm` 行锁、`ws_events`
> 三路径），无并行新路径——符合 ADR-9 与 API.md §11.4。

### 7.2 契约影响

| 层 | 变化 | 谁受影响 |
| :--- | :--- | :--- |
| API.md §4.2 | 公共头增补可选 `vocab_version` | 前端忽略未知字段，**无需改** |
| API.md §4.3 | `clarify` 转正为现行事件；新增审批终态 kind（rejected/cancelled/expired）；#2 留痕 kind | 前端事件分支新增 2~3 个 |
| API.md §4.4 | `clarify_reply` 从历史资料转正为第 5 类现行上行（PRD 本有） | `api/ws.ts` 新增上行方法 |
| API.md §9 | 「第五种上行」红线措辞修订为「以 §4.4 清单为准 + 契约评审」 | 文档 |
| PRD | 仅核对（澄清问答范围本就在），无需扩 | 文档 |
| 前端 | 澄清卡 + ApprovalCard 失效态 + 统一卡基类（三组件收敛） | `Agent.vue`、卡组件、`ws.ts`、`types.ts` |

### 7.3 数据与运行时影响

- **零数据库迁移**：V1.2 收敛后五项均无表结构变化——#4 版本走 payload 保留字段
  （免 `WsEvent` 加列）；#1 是 `pending_confirm` JSONB 内部 `meta` 语义升级
  （`schema_version` 1→2）；#3 策略行已降 P3（唯一可能引 Alembic 的点已消除）。
- **shared 新模块**：`backend/shared/event_vocab.py`——api/worker 事件词汇表从两份
  碎片集合变单一事实源（与 `shared/models.py` 同纪律）。
- **配置**：新增开关 `event_vocab_strict`（默认 false，登记 §6.3）；其余项复用
  `hybrid_engine_enabled` 门控，不新增并列开关。
- **进程间协议**：worker 直写事件带版本声明，api `_forward_loop` 转发前校验——
  api/worker 首次具备事件版本一致性护栏。
- **部署/运维**：无新容器、无新依赖；开关走既有 config 体系。

### 7.4 行为变化（用户可见 / 内部）

| 场景 | 现在 | 落地后（`hybrid_engine_enabled=true` 门内） |
| :--- | :--- | :--- |
| 模型需澄清参数 | `ask_user_question` 中断无卡、ws 层忽略，提问能力不可达 | 澄清卡展示 → 用户作答 → 回合续跑 |
| 审批卡悬挂 | 无过期概念，永久待批 | TTL 过期 → `expired` 终态 + 卡失效；`/stop` 区分 `cancelled`/`rejected` |
| 超长工具结果 | 直接占窗 → 硬裁 20 条无痕丢弃 | 先截断标注再进窗；裁剪留痕可审计 |
| api/worker 版本漂移 | 新事件类型可能被旧 api 误译/静默广播 | 未知 kind 告警（灰度）→ fail-closed 拒收 |
| 工具/沙箱执行选择 | 决策分散 3+ 处 | 单一 resolve 审计点（行为不变） |
| 默认骨架化对话 | 现状 | **逐字节不变**（全部在门内） |

### 7.5 测试与 CI 影响

- 新增单测：注册表一致性断言（防词汇表再漂移）、`_translate_event` 未知 kind/
  版本不符两路径、`push_ws` 版本写库、历史无版本行兼容、#3 TTL 幂等、#1 卡互斥
  与一次性、#5 三档单测。
- 复活 `test_ws_clarify.py`（现有测试清单已引用）。
- CI 门禁不变（ruff + pytest + typecheck + build）。

### 7.6 风险与依赖（重点三项）

1. `routers/ws.py` 是热点：#1/#3/#4 同触收包循环/翻译/落库——分期顺序
   （#4 → #1 → #3 → #2）让协议改动串行化、逐项独立 PR 回归；
2. 卡协议共用单行：#1 扩卡种必须对 `confirm_ack`（W5）/`tool_approval_ack`（H5）
   既有路径零影响验证（最大回归风险面，已列验收要点）；
3. 跨重启能力依赖前置：#1/#3 完整价值依赖 H5 批次 2 PG 检查点切换；未切换前交付
   单副本语义（与 V1.70 `tool_approval` 一致，不阻塞）。

### 7.7 明确不发生的变化（防止误读）

- 不替换/不重写 LangGraph harness（ADR-9）；不引入 dsh 运行时/Node 依赖/新容器；
- 不复制 dsh 会话 JSONL 格式；不新增第五类以外上行（仅 `clarify_reply` 一个 PRD
  既有转正恢复）；
- 默认开关关闭时行为不变；历史 `ws_events` 兼容可读；无新表/新列（无迁移）。

---

## 八、参考来源

| 类别 | 来源 |
| :--- | :--- |
| dsh 源码 | 本机只读调研基线：`C:\Users\gustchen\Desktop\deepseek-harness`（`0.1.2-rc.1`，2026-09-07）；协作者可克隆官方仓库 `https://github.com/deepseek-ai/deepseek-harness`（MIT）。参考文档：README.zh.md、AGENTS.md、docs/architecture.zh.md、docs/cordis-primer.md、packages/{interaction,compaction,session,llm,sdk,acp}/、python/README.zh.md |
| 本项目现状 | AGENTS.md（V1.7 状态地图）；`backend/api/app/agent/`、`routers/ws.py`、`harness/{contracts,context,execution,feedback,memory}/`、`config.py`、`backend/worker/app/events.py` |
| 本项目相关文档 | `AI测试与评估平台-API.md`（V1.70）、`AI测试与评估平台-Agent开发文档.md`（V1.6.0，滞后于代码，以代码与 AGENTS.md 为准）、`AI测试与评估平台-混合驱动引擎架构.md`（ADR-9）、`AI测试与评估平台-H5持久化HITL收尾演练.md`、`AI测试与评估平台-PRD.md` |

---

## 九、修改代码文件与作用清单

> 本文档为纯文档方案，尚未实施代码改动。每完成一项改进后按仓库「文档闭环更新」
> 规范在此追加并升版本。

| 版本 | 日期 | 改动内容 | 涉及文件清单 | 对应改进项 |
| :--- | :--- | :--- | :--- | :--- |
| V1.0 | 2026-09-07 | 首版：dsh 调研结论 + 复用裁决 + #1–#5 立项 + 分期 | 本文档 | — |
| V1.1 | 2026-09-07 | 内部评审修订（R1–R5 + S1–S5），见 §十 | 本文档 | — |
| V1.2 | 2026-09-07 | #4 代码勘察事实修正（R6）+ #4 详细设计 D1–D6 落地，见 §十 | 本文档 | #4 |
| V1.3 | 2026-09-07 | 新增 §七 项目影响与变化总览；原 §七–§九 顺延为 §八–§十，见 §十 | 本文档 | — |
| V1.4 | 2026-09-07 | 文档结构评审修订（R7/R8），见 §十 | 本文档 | — |
| V1.5 | 2026-09-07 | **#1–#5 全部实施交付**：#4 `shared/event_vocab.py` 词汇表单一事实源 + 三路径版本护栏（`event_vocab_strict` 开关，§6.3 登记）；#1 clarify 恢复（API.md V1.72：B 路线卡 + `clarify_ack` 回执，词汇表升 `event.v2`，`test_ws_clarify.py` 复活）；#3 审批终态（API.md V1.73：`approval_terminal`，TTL config，词汇表升 `event.v3`，`test_approval_terminal.py` 新增）；#2 压缩事件化首期（API.md V1.74：store 截断标注 + `context_trim` 留痕，词汇表升 `event.v4`，`test_compact_trace.py` 新增）；#5 执行选择显式化（`harness/security/exec_policy.py`，`test_exec_policy.py` 新增）。全量门禁：api 854 passed / 20 skipped / 0 failed、worker 50 passed、前端 typecheck/build 通过 | 见 §7.1 代码影响矩阵 + `backend/api/app/{routers/ws.py,main.py,config.py,harness/security/exec_policy.py(新),harness/execution/{toolnode,ask_user,native_results}.py,harness/orchestration/agents.py,harness/context/{window,__init__}.py,harness/contracts/events.py}`、`backend/shared/event_vocab.py`（新）、`backend/worker/app/events.py`、`backend/worker/tests/test_events_vocab.py`（新）、`backend/api/tests/{test_event_vocab,test_ws_clarify,test_approval_terminal,test_compact_trace,test_exec_policy}.py`（新增/复活）、`frontend/src/{api/{ws,types}.ts,views/Agent.vue,components/agent/{ClarifyCard(新),ApprovalCard}.vue}`、`docs/AI测试与评估平台-API.md`（V1.71–V1.74） | #1–#5 |

---

## 十、修订记录

### 10.1 V1.1 评审修订记录（R1–R5 + S1–S5）

| 评审项 | 级别 | 修订内容 | 落点 |
| :--- | :--- | :--- | :--- |
| R1 | P0 | `clarify_reply` 定性修正：PRD 既有上行、非「新增第 5 类」；新增契约裁决记录（出处/转正路径/回滚条件） | §3.1.1、§五-5、§6.2 |
| R2 | P0 | 卡存储路线 A/B 裁决表（推荐 B）+ 三类卡互斥矩阵；声明与 V1.62 历史语义的差异 | §3.1.2 |
| R3 | P1 | #4 优先级统一为 P1（护栏前置，一期首项），同步概览/依赖图/分期三处表述 | §3.1、§3.4、§四 |
| R4 | P1 | #2 首期落地物收敛：超大 tool_result 裁剪 + 窗口裁剪事件化留痕；模型摘要 replace 明确为二期 | §3.2 |
| R5 | P1 | #3 范围收敛为审批终态 + 前端失效态；会话级审批策略行降 P3 移出立项 | §3.3 |
| S1 | 建议 | 立项概览表补优先级/规模/契约面；新增预期契约修订清单 | §3.1、§6.2 |
| S2 | 建议 | #1 前端约束统一卡基类；复活 `test_ws_clarify.py` 测试基线 | §3.1.3 |
| S3 | 建议 | 参考来源补调研基线（版本/日期）与官方 GitHub 地址 | §八 |
| S4 | 建议 | 通用纪律新增灰度开关登记制 + 开关登记表 | §3.0、§6.3 |
| S5 | 建议 | 分期补充前置阻塞降级路径（#4 与 PG 检查点切换解耦可先行） | §4.2 |

### 10.2 V1.2 修订记录

| 评审项 | 级别 | 修订内容 | 落点 |
| :--- | :--- | :--- | :--- |
| R6 | P0 | #4 现状事实修正：`EVENT_VERSION` 已有雏形但未生效（`_translate_event` 不读、`_emit_persistent` 落库丢失、Worker `push_ws` 无版本、`_forward_loop` 无校验），词汇表碎片化无单一事实源；§二 映射表与 §3.4 同步改写 | §二、§3.4.0 |
| — | 设计落地 | #4 详细设计 D1–D6 并入 §3.4（shared 注册表单源 / API.md §4.2 `vocab_version` / 三条路径校验 / `event_vocab_strict` 开关 / 测试清单 / 影响面）；#4 规模 S→M | §3.4、§3.1、§6.2、§6.3 |

### 10.3 V1.3 修订记录

| 评审项 | 级别 | 修订内容 | 落点 |
| :--- | :--- | :--- | :--- |
| — | 设计落地 | 新增 §七「项目影响与变化总览」（V1.3）：代码影响矩阵 / 契约影响 / 数据与运行时（零迁移、零新依赖）/ 行为变化 / 测试与 CI / 风险依赖 / 不发生清单 | §七 |

### 10.4 V1.4 修订记录

| 评审项 | 级别 | 修订内容 | 落点 |
| :--- | :--- | :--- | :--- |
| R7 | P1 | 文档结构评审修订：§六 补「### 6.2 预期契约修订清单」标题（消除 5+ 处 §6.2 引用悬空） | §六 |
| R8 | P2 | 修复 §六 编号列表断链（编号 5 并入 §6.3 引言）；V1.3 修订行自 10.2 表移入独立 §10.3 | §六、§10.3 |
