# AI 测试与评估平台 — dsh 借鉴与 Agent Harness 改进开发计划

> 📦 **历史归档（2026-09-11）**：本文为历史设计稿 / 规划，其中提及的 `agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除或演进，仅作决策留痕；请勿按本文直接立项。

| 项 | 内容 |
| :--- | :--- |
| 版本 | V1.2 |
| 制定 / 审查日期 | 2026-09-07 / 2026-09-07 |
| 最近修订 | 2026-09-07：V1.2 #1–#5 全部实施交付（D0 契约 V1.71–V1.74 先行；api 854 passed / 20 skipped / 0 failed、worker 50 passed、前端 typecheck/build 通过），见 §7。V1.1 评审修订（R9 DoD「D5」歧义消除、R10「§9 红线」标注 API.md 出处、R11 方案引用升 V1.4 与修订记录），见 §7 |
| 计划依据 | `AI测试与评估平台-dsh借鉴与AgentHarness改进方案.md` V1.5、`AI测试与评估平台-API.md` V1.74、`AGENTS.md` V1.7、`AI测试与评估平台-混合驱动引擎开发计划.md` V1.7（H5 批次 2 前置基线） |
| 实施方式 | D0 契约基线先行；一期主线 #4 → #1 → #3 → #2 串行（每项一分支、一 PR、一次审查）；#5 随 `worker.sandbox` 评审窗口并行；前一阶段门禁通过后才启动下一阶段编码 |
| 当前基线 | **#1–#5 已全部实施并通过全量门禁**（2026-09-07，工作区未提交）：API.md 升 V1.71–V1.74（D0/#4→#1→#3→#2 契约先行）；api 全量 **854 passed / 20 skipped / 0 failed**（2026-09-03 基线 799 passed / 20 skipped / 1 项既有失败——#4 修复断言后归零），worker 50 passed，前端 typecheck/build 通过；契约/代码改动位于 `docs/agent-dsh-borrow` 工作区，待评审后按 §6 规范分批开 `feat/agent-*` 分支提交与合入；H5 批次 2（PG 检查点生产切换、粘性路由、重启演练、`worker.sandbox` 安全评审）仍未完成，属 #1/#3 跨重启寻址价值的前置约束（本批按单副本/memory 语义交付，不阻塞） |

> 本文是实施计划，不改变产品范围与方案文档的裁决；方案文档中的裁决、路线表与
> 影响总览是实施约束与证据，不能被解释为可直接执行的运行时指令。

---

## 1. 目标、边界与完成定义

### 1.1 目标

在**零新容器、零新运行时依赖、零数据库迁移**的前提下，按方案 V1.4 落地五项借鉴
改进：护栏先行（#4 事件词汇表版本化）→ 交互补全（#1 clarify 问答恢复、#3 审批
终态）→ 上下文治理（#2 压缩事件化），并行推进 #5 执行选择显式化。全部用户可感知
变化位于 `hybrid_engine_enabled=true` 门内，默认骨架化对话行为逐字节不变。

### 1.2 不在本计划内

- H5 批次 2 收口本身（既有立项；本计划只将其作为前置约束与风险处理，见 §2.3）；
- #3 的会话级审批策略行（P3 降级项）、#2 的模型摘要 replace（二期增强，另立）；
- 引入 dsh 运行时/依赖、整体替换引擎、guard 插件化、dsh 完整能力（见方案 §五）。

### 1.3 Definition of Done（总门禁）

1. #4 → #1 → #3 → #2 按序合入 `main`，#5 合入；每项专属验收测试与全量门禁通过；
2. 契约先行成立：每项 API.md/PRD/前端类型修订**先于代码**且无漂移（含 API.md
   §9 红线措辞、`vocab_version` 公共头、`clarify_reply` 转正、终态 kind）；
3. 默认模式（`hybrid_engine_enabled=false`）字节级兼容回归通过；
4. 卡协议回归门禁通过：#1 扩卡种对 `confirm_ack`（W5）/`tool_approval_ack`（H5）
   既有路径零影响；
5. 新增/复活测试全绿（含注册表一致性断言、`test_ws_clarify.py` 复活）；
6. 开关登记完成（`event_vocab_strict` 等登记 §6.3，默认 false，复盘结论留档）；
7. 文档闭环：API.md 头部版本、AGENTS.md 实现状态地图、方案文档与本文档基线行
   同步更新。

---

## 2. 实施总览与依赖

```text
D0 契约与基线（docs/ 分支，纯文档）
        │
        ▼
#4 事件词汇表版本化（feat/agent-event-vocab，护栏先行）
        │
        ▼
#1 clarify 问答恢复（feat/agent-clarify-resume，契约转正）
        │
        ▼
#3 审批终态（feat/agent-approval-terminal）──► #2 压缩事件化（feat/agent-compact-trace）
                                                    │
        #5 执行选择显式化（feat/agent-exec-resolve）◄──┘（随 worker.sandbox 评审窗口并行）
                                                    │
                                                    ▼
                                       收尾灰度复盘（开关观察 + 文档闭环）
```

| 阶段 | 分支 | 依赖 | 主要风险 | 合入前硬门槛 |
| :--- | :--- | :--- | :--- | :--- |
| D0 契约与基线 | `docs/`（沿用 `docs/agent-dsh-borrow`） | 无 | 契约评审滞后 | API.md §4.2/§4.3 修订先行定稿；方案 V1.4 引用点一致 |
| #4 词汇表版本化 | `feat/agent-event-vocab` | D0 | `ws.py` 热点回归；Worker 直写兼容 | 默认行为不变；未知 kind 两路径单测；注册表一致性断言 |
| #1 clarify 恢复 | `feat/agent-clarify-resume` | #4 | 三类卡互斥破坏 W5/H5 路径；payload 裁决反复 | `confirm_ack`/`tool_approval_ack` 零影响回归；resume 至多一次 |
| #3 审批终态 | `feat/agent-approval-terminal` | #4、#1 | 扫描归属与幂等；终态 kind 契约 | TTL 幂等（不依赖扫描存活）；过期 ack 拒绝不 resume |
| #2 压缩事件化 | `feat/agent-compact-trace` | #4 | 留痕 kind 与窗口算法回归 | 首期落地物（裁剪标注 + 事件化留痕）验收；Observation 纪律 |
| #5 执行显式化 | `feat/agent-exec-resolve` | 与 `worker.sandbox` 评审捆绑 | 重构改变默认沙箱行为 | 三档单测；`agent_drill_sandbox_enabled=false` 全量回归 |

### 2.1 开工前统一裁决（实施级，均源自方案 V1.4）

| 编号 | 裁决 | 实施动作 |
| :--- | :--- | :--- |
| C-1 | 契约先行（方案 §3.0-1、§6-2） | 每项第一个代码提交前完成 API.md/前端类型修订与评审留档 |
| C-2 | #4 版本落点（方案 D2/D3） | 公共头 `vocab_version` + payload 保留字段；**免 `WsEvent` 加列/Alembic** |
| C-3 | #1 卡路线 B + payload 定稿（方案 §3.1.2/§3.1.3） | 复用 `pending_confirm` 行锁；`meta.schema_version` 升版；`confirm_type` 扩 `clarify`；`clarify_reply` 用多题 `answers[]` 结构（契约评审定稿留档） |
| C-4 | 三类卡互斥（方案 §3.1.2） | 行锁「已有卡 → CONCURRENCY」兜底不变；回归门禁覆盖 W5/tool_approval 路径 |
| C-5 | #3 终态与 TTL（方案 §3.3） | kind（rejected/cancelled/expired）随 #4 注册表扩展路径追加；TTL 常量入 config/Setting，禁硬编码；失效判定幂等 |
| C-6 | #2 首期落地物（方案 §3.2.3） | 首期无 LLM 摘要；裁剪标注 + 事件化留痕；模型摘要二期另立 |
| C-7 | 开关登记制（方案 §3.0-3、§6.3） | `event_vocab_strict=false`；复盘后删除或固化评估，不留常驻开关 |
| C-8 | 默认语义不变 | 全量回归在默认门内执行；定向用例用 `hybrid_engine_enabled=true` 夹具，禁止默认态行为漂移 |

### 2.2 阶段决策门（未裁决不得开始对应编码）

| 最晚阶段 | 必须裁决的事项 | 默认 / 约束 | 拍板方 |
| :--- | :--- | :--- | :--- |
| D0 | API.md §4.2 `vocab_version` 字段名与语义；API.md §9 红线措辞文本 | 可选字段、服务端恒发、旧客户端忽略 | 契约 |
| #1 | `clarify_reply` payload 定稿（单卡文本 vs 多题 `answers[]`）；`meta.schema_version` 升版方案 | 多题 `answers[]`（建议）；升版对 W5/H5 卡零影响 | 契约 + 架构 |
| #3 | 终态 kind 命名与 payload；TTL 默认值与扫描归属 | 随 #4 注册表扩展；TTL 入 config；api 侧扫描 + 幂等兜底 | 契约 + 架构 |
| #2 | 留痕事件 kind（独立 vs 复用）与展示语义 | 服务端留痕为主，前端展示与否随契约评审 | 契约 |
| #5 | Spec 分支与 `worker.sandbox` 评审结论联动 | 默认行为不变；演练开关必须复位 | 架构 + 安全 |

### 2.3 前置约束（H5 批次 2，非本计划实施）

- #1/#3 跨重启寻址的完整价值依赖 PG 检查点生产切换与粘性路由；未切换前按
  **单副本/memory 检查点语义**交付（与 V1.70 `tool_approval` 现状一致），不阻塞；
- #4 与 PG 检查点切换无耦合，H5 批次 2 若阻塞可先行（方案 §4.2 降级路径）；
- #5 与 `worker.sandbox` 安全评审同批，评审结论可能调整 Spec 分支，须预留窗口。

---

## 3. 任务分解与估算

> 估算口径：人日（后端单人次 + 前端联调份额已含在各卡片；不含契约评审等待与
> 缓冲）。基准为 2 人（后端 + 前端）节奏，乐观为理想串行无等待。前端工作量
> 集中在 #1/#3 的卡组件与事件分支。

### 3.1 D0 契约与基线（约 0.5–1 人日）

1. API.md §4.2 增补 `vocab_version`（可选字段，服务端恒发）；
2. API.md §4.3 词汇表版本语义与演进纪律段落；
3. 本计划文档定稿、方案文档与 API.md 引用点一致；
4. 产出：API.md V1.71 草案（`docs/` 分支）。

### 3.2 #4 事件词汇表版本化（约 1.5–3 人日，M）

| 任务 | 内容 | 产出/DoD |
| :--- | :--- | :--- |
| T4-1 | 新增 `backend/shared/event_vocab.py`（`PERSISTENT_KINDS`/`NODE_EVENT_KINDS`/`EVENT_VERSION`/`is_persistent`，演进规则 docstring） | 单一事实源；api/worker 引用切换 |
| T4-2 | `contracts/events.py` 改为引用 shared；`NodeEventKind`/`_PERSISTENT_KINDS` 去碎片 | 无重复集合；现有引用全量通过 |
| T4-3 | `_translate_event` 版本校验 + `_emit_persistent` 落库带 `vocab_version` + payload 保留字段 | 版本不再丢失；告警路径单测 |
| T4-4 | `worker/app/events.py::push_ws` 注入 shared 版本；调用方回归 | 写库带版本断言 |
| T4-5 | `_forward_loop` 校验 + `config.py` 开关 `event_vocab_strict`（默认 false） | 未知 kind 两路径单测；开关登记 §6.3 |
| T4-6 | 注册表一致性断言测试；历史无版本行兼容测试 | `test_ws_protocol.py` 扩展全绿 |

**DoD**：#4 合入门槛 = 方案 §3.4.3-D5（测试清单）全绿 + 默认行为不变 + API.md §4.2/§4.3 先行合入。

### 3.3 #1 clarify 问答恢复（约 2–3.5 人日，M）

| 任务 | 内容 | 产出/DoD |
| :--- | :--- | :--- |
| T1-1 | 契约转正（§3.1.1 路径）：API.md §4.3 `clarify` 转正、§4.4 `clarify_reply` 转正（多题 `answers[]`）、§9 措辞、§2 总表、头部记录 | API.md V1.72 草案先行 |
| T1-2 | `_handle_graph_interrupt` 增 `type=clarify` 分支：落卡（`meta.confirm_type=clarify` + `thread_id` + `resume_nonce`）广播持久事件 | 澄清卡可达；与 tool_approval 共用行锁 |
| T1-3 | `_handle_clarify_reply` 收包循环分支：行锁清卡先行 → `Command(resume={answers})` → `toolnode` 放行 | resume 至多一次；重复 ack 拒绝 |
| T1-4 | `ask_user.py` 投影接线（questions → payload / answers 校验） | ≤8 题三题型全链路 |
| T1-5 | 前端：统一卡基类 + 澄清卡；`ws.ts`/`types.ts` 上行与事件类型 | 与 Confirm/Approval 同模式；回放只读 |
| T1-6 | 复活改写 `test_ws_clarify.py`；三类卡互斥回归（W5/tool_approval 路径） | 验收要点全绿 |

**DoD**：#1 合入门槛 = 提问→卡→答→续跑全链路 + 每轮恰一 `completed` + 卡互斥
回归 + 一次性语义单测 + API.md 转正先行。

### 3.4 #3 审批终态（约 1–1.5 人日，S）

| 任务 | 内容 | 产出/DoD |
| :--- | :--- | :--- |
| T3-1 | 终态 kind（rejected/cancelled/expired）经 #4 注册表扩展 + API.md §4.3 说明 | 契约先行 |
| T3-2 | TTL 失效判定（api 侧扫描，`created_at` + 当前时间幂等兜底）；TTL 常量入 config | 卡过期 → 终态事件 |
| T3-3 | `/stop`/会话关闭路径补 `cancelled` 终态语义（与 `rejected` 区分） | 事件可回放 |
| T3-4 | `ApprovalCard.vue` disabled/expired 态；失效后 ack 拒绝不 resume | 前端失效态 |

**DoD**：#3 合入门槛 = 过期/取消/拒绝三终态单测 + 幂等（不依赖扫描存活）+ 与
#1 行锁互斥语义不冲突。

### 3.5 #2 上下文压缩事件化（约 1.5–2.5 人日，M）

| 任务 | 内容 | 产出/DoD |
| :--- | :--- | :--- |
| T2-1 | `native_results.py` 超大 `tool_result` 长度上限 + 截断标注 | 模型只见带标注截断结果 |
| T2-2 | 窗口裁剪事件化留痕（触发原因/保留策略/被裁元信息；kind 经 #4 扩展） | 事件流可回放审计 |
| T2-3 | `window.py`/`state.py` 相关字段与算法兜底回归；观察纪律（不落原文全文） | `recent_window` 行为不变 |

**DoD**：#2 合入门槛 = 对照用例回归（字节/条数下降且行为不变）+ 留痕可回放 +
每轮恰一 `completed` 不破坏。

### 3.6 #5 执行选择显式化（约 1.5–3 人日，M，随安全评审窗口并行）

| 任务 | 内容 | 产出/DoD |
| :--- | :--- | :--- |
| T5-1 | 收敛工具/沙箱选择为显式 resolve 点（输入 → Spec：runner bwrap / drill / 排除 fail-closed） | 单一审计面 |
| T5-2 | discover 静态排除与 `agent_drill_sandbox_enabled` 语义迁入 Spec 分支输入 | 默认行为不变 |
| T5-3 | 三档单测 + `false` 默认路径全量回归；开关登记 | 与 `worker.sandbox` 评审结论联动 |

### 3.7 收尾灰度复盘（约 0.5–1 人日）

1. `event_vocab_strict` 灰度观察结论（置 true / 固化 / 删除）留档；
2. 全量回归（api + worker + 前端）+ 前端 typecheck/build；
3. 文档闭环：API.md 头部、AGENTS.md 状态地图、方案文档、本文档基线行更新。

**总计：主线 D0 + #4 + #1 + #3 + #2 + 收尾 ≈ 7–12.5 人日；#5 并行 ≈ 1.5–3 人日。
基准节奏（2 人）建议排 3–4 周（含评审等待与缓冲 1 周）；单后端全栈按 1.5 倍
估算。** 日历仅为建议，实际以每阶段门禁通过为准：

| 周次 | 目标 |
| :--- | :--- |
| W1 | D0 契约定稿 + #4 实施与合入 |
| W2 | #1 契约转正 + 实施 |
| W3 | #3 合入 → #2 实施与合入（#5 并行窗口） |
| W4 | #5 合入（若评审窗口未就绪则顺延）+ 灰度复盘与文档闭环 |

---

## 4. 风险登记

| 风险 | 等级 | 缓解 |
| :--- | :--- | :--- |
| `ws.py` 热点：三项同触收包循环/翻译/落库 | 高 | 主线串行化（#4 → #1 → #3 → #2），每项独立 PR + 专属回归，禁止并行改 `ws.py` |
| #1 扩卡种破坏 W5/H5 既有路径 | 高 | `meta.schema_version` 升版对 `confirm_ack`/`tool_approval_ack` 零影响验证（DoD 硬门槛） |
| H5 批次 2 阻塞 | 中 | #4 解耦先行；#1/#3 先交付单副本语义（不阻塞）；粘性/PG 能力随前置就绪放行 |
| 契约评审滞后导致返工 | 中 | D0 先定稿 API.md 修订；每阶段决策门未过不开编码（§2.2） |
| 前端卡基类重构范围蔓延 | 中 | 收敛在 #1 内：先统一新澄清卡与既有卡模式，不先行重构 Confirm/Approval 卡行为 |
| Worker/API 版本不一致期间的告警噪音 | 低 | `event_vocab_strict=false` 灰度；告警日志采样与观察期结论留档 |

---

## 5. 验收与回归基线

1. 每阶段合入前：`backend/api`：`ruff check . ../shared` + `pytest`；`backend/worker`：
   `PYTHONPATH=.:.. pytest`；前端：`npm run typecheck` + `npm run build`；
2. 事件契约专项：`test_ws_protocol.py` 扩展、复活 `test_ws_clarify.py`、注册表
   一致性断言、历史无版本行兼容；
3. 默认模式字节级兼容回归（`hybrid_engine_enabled=false` 全量路径）；
4. 卡协议回归：`confirm_ack`（W5）/`tool_approval_ack`（H5）路径在 #1 合入前后
   行为一致（对照既有 `test_bash_hitl.py` 等测试）；
5. 基线记录：`AI测试与评估平台-混合驱动引擎开发计划.md` V1.7 记录 API 全量
   `799 passed / 20 skipped / 1 项既有失败`（2026-09-03，与本文档项无关）——每项
   合入后在本计划「当前基线」行更新真实计数。

---

## 6. 文档与提交纪律

1. 每项独立 `feat/agent-*` 分支（本文档 §2 表），契约改动走 `docs/` 分支先行；
2. 中文 Conventional Commits，中文消息经临时文件 `-F` 提交防乱码，提交后校验
   标题可读；提交前过全部门禁；
3. 契约先行顺序：API.md（V 号递增）→ 实现 → 前端 → 测试；每项合入后同步
   AGENTS.md 实现状态地图、方案文档版本与本文档「当前基线」行；
4. 新开关一律登记方案文档 §6.3（默认 false、复盘删除）；
5. 纯文档变更提交格式 `docs(agent): <中文描述>`。

---

## 7. 修改代码文件与作用清单

> 本文档为实施计划（V1.0），尚未进入编码。每阶段完成后按仓库「文档闭环更新」
> 规范在本节追加并升版本。

| 版本 | 日期 | 改动内容 | 涉及文件清单 | 对应阶段 |
| :--- | :--- | :--- | :--- | :--- |
| V1.0 | 2026-09-07 | 首版：依据方案 V1.4 制定 D0 + #1–#5 开发计划（任务分解/估算/决策门/风险/验收） | 本文档 | — |
| V1.1 | 2026-09-07 | 评审修订（R9–R11）：#4 DoD「D5 测试清单」改为引用方案 §3.4.3-D5；「§9 红线」标注出处为 API.md §9；方案版本引用升至 V1.4 | 本文档 | — |
| V1.2 | 2026-09-07 | #1–#5 实施交付记录：D0 契约（API.md V1.71 `vocab_version` + 词汇版本语义）→ #4（`shared/event_vocab.py` + 三路径校验 + `event_vocab_strict` + D5 测试）→ #1（API.md V1.72 clarify 转正、B 路线卡、`clarify_ack`、`test_ws_clarify.py` 复活）→ #3（API.md V1.73 `approval_terminal`、TTL config/扫描、`test_approval_terminal.py`）→ #2（API.md V1.74 store 截断 + `context_trim`、`test_compact_trace.py`）→ #5（`exec_policy.py` 显式决策、`test_exec_policy.py`）；前端 ClarifyCard/ApprovalCard 失效态/ws.ts/types.ts；门禁：api 854 passed / worker 50 passed / 前端 typecheck+build | 同方案文档 V1.5 §九 文件清单 | #4/#1/#3/#2/#5 |
