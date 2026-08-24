# AI 测试与评估平台 — Harness 六层架构

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 六层架构 |
| 版本 | V0.1.0 |
| 审查日期 | 2026-08-24 |
| 文档性质 | 架构总览（六层职责 + 跨层数据流 + 范式映射 + 模块导航） |
| 适用范围 | `/agent` 对话智能体的 Harness 运行时：提示词 / 上下文 / 记忆 / 编排 / 执行 / 反馈六层 |
| 事实来源 | `backend/api/app/harness/`、`app/agent/`、`app/llm/`、`app/routers/ws.py`；各层模块设计文档；Harness 需求文档 V1.5.0 |

> **阅读关系**：本文是**架构总览与导航**——回答"六层分别管什么、数据如何流过六层、对应哪些范式"。逐层实现细节以各层模块设计文档为准（见 §8 导航），需求条目与验收标准以《Harness 需求文档》为准，对外契约以 API.md / PRD 为准。本文不新增任何对外 REST/WS 字段。

---

## 1. 六层总览

Harness 把 Agent 运行时拆成六层，每层解决一个维度的问题；通过**反馈回流**与**记忆持久化**耦合成闭环。

```text
┌─────────────────────────────────────────────────────────────┐
│  层1 提示词工程  harness/prompts/    定义"行为规范"（严格 JSON 协议） │
│  层2 上下文工程  harness/context/    控制"看到什么"（窗口/脱敏/懒加载）│
│  层3 记忆        harness/memory/     沉淀"状态与经验"（State/检查点/工作区）│
│  层4 编排        harness/orchestration/ + agent/  决定"做什么/顺序/谁做" │
│  层5 执行        harness/execution/  完成"物理动作"（注册表/沙箱/超时）  │
│  层6 反馈        harness/feedback/   判定"对不对"（归一/门禁/复核/抑制） │
├─────────────────────────────────────────────────────────────┤
│  跨层：contracts/（契约）· security/（脱敏/auth）· skills/（技能目录）  │
│  桥接：routers/ws.py（事件桥接）· llm/（ModelGateway 三协议适配器）    │
└─────────────────────────────────────────────────────────────┘
```

**需求总目标**（Harness §1.2）：上下文高效 + 专业能力强 + 可并行扩展 + 能自我纠错——单层无法同时满足，故按维度分层。

---

## 2. 跨层数据流（一条用户消息的完整旅程）

```text
① ws.py 收包 user_message
   → 校验 attachments 格式 → normalize_attachment_refs（归属校验，attachments.py）
   → 持久化 Message（attachments 存安全元数据 JSON）
② _run_turn（ws.py）
   → _history_messages → _window_messages（层2 窗口 CX-1）
        · 每条 user 消息经 model_content_for_message：txt/md staging 进工作区 +
          输出路径清单（懒加载）；图片→base64；pdf/docx/xlsx→内联截断
   → LangGraphAgent.astream（graph.py），configurable 注入：
        thread_id / abort / credentials / session / assets(file_ids) / sandbox
③ routing_node（层4，routing.py）
   → decide_mode：斜杠→direct；关键词或 has_attachments→react；否则 chat
④ react_agent_node（react.py）
   → system（五段策略 + 工具清单 + 累计 observations）→ ModelGateway（llm/）→ 严格 JSON
   → parse_react 校验 → pending_tool 或 done
⑤ tool_node（层5，toolnode.py）
   → check_gates（层6 门禁）→ bind_attachments（归属）→ execute（dispatch.py，超时+脱敏）
   → 归一 Observation（层6 observation.py）→ 注入下一轮 system（层2 to_observation）
⑥ 循环直至 done → assistant_message / response.completed
   → ws.py 统一 emit 事件（events.py 契约）→ ws_events 持久化 + 广播
```

长任务路径：`confirm_ack`（收包循环直连，confirm.py OR-8）→ `enqueue_long_task`（worker_bridge.py）→ PG 队列 → Worker → progress/report/error 写 `ws_events` 实时转发（**不阻塞对话回合**）。

---

## 3. 六层职责与关键文件

### 层1 提示词工程（`app/harness/prompts/`）

**职责**：固定系统策略与阶段输出协议；模型不持有控制逻辑（PR-1/2/3/4）。

| 文件 | 机制 | 对应需求 |
| :--- | :--- | :--- |
| `system.py` | 五段固定系统策略（角色/安全边界/确认卡/长短任务/密钥保护）；`SystemVars` 受控变量槽（skill_hints/session_owner），用户配置**不可覆盖**；`assert_no_secret_leak` | PR-1 / P-A6 |
| `protocols.py` | plan/react/reflect 三阶段严格 JSON 输出协议（schema 白名单，多余字段拒绝、类型严格、版本严格不兼容）；`parse_react` **丢弃 thought**（PR-3，只回显不触发） | PR-2 / PR-3 |
| `safety.py` | 用户文本注入检测（"忽略系统提示/扮演角色"等模式直接拒绝）+ 注入回归用例 | PR-4 / P-A4 |

### 层2 上下文工程（`app/harness/context/` + `app/agent/attachments.py`）

**职责**：决定模型本轮可见输入，同时优化相关性、来源、安全、容量与成本（CX-1~7）。

| 文件 | 机制 | 对应需求 |
| :--- | :--- | :--- |
| `window.py` | 最近消息窗口为**唯一**窗口算法（默认末尾 20 条 user/assistant，`compact_keep_from` 截断更早）；thought/tool/confirm/progress 事件**不进窗口**（只走 ws_events 回放） | CX-1 / CX-2 |
| `observation.py` | 工具结果 `to_observation`：先 M8 递归脱敏 → 截断带标记（默认 2000 字符）→ 来源溯源（`file:uuid`/`message:uuid`）；**read 工具放开到 21000**（懒读取全文进模型） | CX-3 |
| `assembly.py` | 上下文装配顺序 + 工具定义按本轮能力最小注入 | CX-4 / CX-5 |
| `compact.py` | `/compact` 可控摘要：保留最近 6 条原始 + 摘要 ≤2000 字符，**不删除原始记录**（MEM-3） | CX-6 |
| `meter.py` | ContextMeter 只读 `GET /api/sessions/{id}/messages` 的 `context_meter` | CX-7 |
| `attachments.py`（agent/） | 附件懒加载（V0.1.0 新增）：txt/md **staging 进会话工作区**（`os.link` 硬链，幂等），模型内容只给**路径清单**由 read 工具按需读取；图片 ≤4MB base64 视觉块；pdf/docx/xlsx 保持内联抽取（后续迁 read 路径）；无工作区时回退内联 | 懒加载/渐进式披露 |

### 层3 记忆（`app/harness/memory/` + `app/harness/execution/workspace.py`）

**职责**：按类型保存、检索、摘要与失效；记忆不进上下文，而是可检索的状态（MEM-1~6）。

| 文件 | 机制 | 对应需求 |
| :--- | :--- | :--- |
| `state.py` | `GraphState` 全字段 JSON 可序列化（PG 检查点兼容）；**api_key/should_abort 不入 State**（走 RunnableConfig）；`pending_events` append reducer | MEM-1 / §2.4 红线 |
| `checkpoint.py` | `InMemoryCheckpointer`（threading.local，容量 512）+ `PgCheckpointer`（`harness_checkpoints` 表）；恢复语义 M3-D4：事件不依赖检查点重放（走 ws_events），断线不重复 emit | 回合隔离/澄清卡恢复 |
| `episodic.py` / `compressed.py` / `preference.py` / `cleanup.py` | 情景记忆（ws_events 重放）/ 压缩记忆（摘要派生状态）/ 偏好记忆 / 超龄清理 | MEM-2/3/4 |
| `workspace.py`（execution/） | 每会话一个独立文件夹 `{root}/{session_id}`：agent 写入文件 + 附件 staging 均持久化，跨回合可 read；session_id 正则校验**防路径穿越**（M5-D7） | 会话隔离/懒加载载体 |

### 层4 编排（`app/harness/orchestration/` + `app/agent/`）

**职责**：选择控制流（Chat/ReAct/Plan-and-Solve/Direct），生成可验证中间状态，模型不直接执行副作用（OR-1~8）。

| 文件 | 机制 | 对应需求 |
| :--- | :--- | :--- |
| `orchestration/router.py` | `decide_mode`：斜杠→direct；工具关键词或 **has_attachments→react**（V0.1.0 新增，带附件必须进 react 才有 read 工具）；否则 chat | OR-1 |
| `agent/routing.py` | `routing_node`/`route` 从 `configurable.assets.file_ids` 读附件存在性 → 强制 react | OR-1 |
| `orchestration/budget.py` | 计数型预算 `model_calls=4 / tool_turns=4`，耗尽抛 `BUDGET_EXCEEDED` | OR-5 |
| `orchestration/gates.py` | 长工具判定 + 会话占槽（DB 事实填入 GateContext） | OR-6 / OR-7 |
| `orchestration/plan.py` | `PlanArtifact` 规划解析（重试降级） | OR-2 / OR-3 |
| `orchestration/confirm.py` | 确认卡回执（OR-8）：行锁 + owner 校验 + patch 深合并 + 二次校验 + 入队，收包循环直连 | OR-8 |
| `agent/graph.py` | LangGraph 状态机 `START → routing → (direct\|chat_stream\|react_agent⇄tools\|plan_solve→reflect) → END`；Checkpointer 回合隔离 | 图拓扑 |
| `agent/react.py` | ReAct 循环：system（五段策略+工具清单+observations）→ 模型严格 JSON → `parse_react` → pending_tool/done；**OR-4 重复抑制**（相同 tool+args 首次纠正、二次硬错误）；read 观察放开 21000 | OR-4 / ReAct |
| `agent/plan_solve.py` / `reflect.py` | Plan-and-Solve 执行子图（图内复用节点）+ reflect 复核节点（pass/clarify/reject 条件边） | Plan-Solve / Reflexion |

### 层5 执行（`app/harness/execution/`）

**职责**：在权限、参数绑定、超时、脱敏与白名单边界内真正产生副作用（EX-1~6）。

| 文件 | 机制 | 对应需求 |
| :--- | :--- | :--- |
| `registry.py` | 工具注册表（元数据/白名单/分派唯一源）；`build_default_registry` 注册 read/write/edit/web_search/web_fetch/bash；未注册一律 VALIDATION | EX-1 / EX-5 |
| `binding.py` | 附件参数系统绑定：`file_id` 归属校验，模型不可伪造 | EX-2 |
| `toolnode.py` | `ToolNode`（async 节点）：门禁 → `bind_attachments` → `execute` 经 `asyncio.to_thread`（防 bash 阻塞事件循环）→ Observation | EX-1 |
| `dispatch.py` | `execute` 统一分派：超时 + 脱敏日志 + 异常归一，**不裸抛**；`read_file_safe` 沙箱内路径解析 + 防穿越 + **offset/limit 分段 + 未读完截断标记**（V0.1.0 新增）；`run_bash` 黑名单纵深防御 | EX-3 |
| `sandbox.py` | bwrap 进程级沙箱：无网络、工作区唯一可写、资源受限（ulimit）、超时整树清理；bwrap 不可用 **fail-closed** | EX-3 / §7 |
| `workspace.py` | 会话工作区（同层3） | 会话隔离 |
| `worker_bridge.py` | 长任务入队（`TASK_KINDS`/`LONG_TOOLS`），PG 队列 → Worker，不阻塞回合 | EX-4 |
| `session_guard.py` | Worker 自管 DB Session，禁止跨 Session 传 ORM 对象 | EX-6 |

### 层6 反馈（`app/harness/feedback/`）

**职责**：把工具结果/校验/外部任务事件变成下一步可信依据（FB-1~5）。

| 文件 | 机制 | 对应需求 |
| :--- | :--- | :--- |
| `observation.py` | 工具结果/异常归一 `Observation`（ok/redacted/truncated/source），**不裸抛、不泄露内部细节** | FB-1 |
| `rules.py` | 8 类门禁先行（长工具/白名单/任意代码/一单一 kind/必填槽位/**资产溯源**/占槽/先评后压），确定性不调模型 | FB-2 |
| `review.py` | 模型辅助核对：只允许 `pass→clarify` 降级，**不得 reject→pass** | FB-3 |
| `budget.py` | 失败反馈受预算约束，禁止无限重试 | FB-4 |
| `isolation.py` | Worker 的 progress/report/error 只进任务/事件链路，不污染消息窗口 | FB-5 |

---

## 4. Agent 范式映射

Harness 需求文档 §2.2 定义了七种设计模式，本项目当前落地情况：

| 范式 | 落地形态 | 现状 |
| :--- | :--- | :--- |
| ReAct | `react_agent ⇄ tools` 严格 JSON 协议循环（自建 StateGraph，**禁用 create_react_agent**） | ✅ 落地 |
| Direct | 斜杠命令 L0 路由（不调模型） | ✅ 落地 |
| Chat | 无工具流式回答 | ✅ 落地 |
| Plan-and-Execute | `plan_solve` 执行子图（图内复用节点）+ `reflect` 复核 | 🟡 阶段 4 最小实现（工具执行未接线） |
| Reflexion | OR-4 重复抑制（首次纠正/二次硬错误）+ reflect 复核 | 🟡 浅层版 |
| Orchestrator-Worker | 进程级：确认卡回执 → PG 队列 → Worker（**禁止 LLM 子代理**） | ✅ 进程级 |
| Mixture of Experts / Progressive Disclosure | `skills/registry.py` 技能目录（名称+一句话描述常驻）+ 附件/工具定义按需加载 | 🟡 技能为轻量 hint，非长文档专家 |

---

## 5. 跨层契约与安全

| 模块 | 作用 | 关键点 |
| :--- | :--- | :--- |
| `contracts/artifacts.py` | 跨层 artifact（`ToolCall`/`ToolResult`/`Observation`/`PlanArtifact`/`SkillHint`） | 全部 frozen + JSON 可序列化（PG 检查点兼容），禁止嵌 Callable/WS/Session |
| `contracts/events.py` | `NodeEvent` 事件意图契约 + `make_event` 白名单 | 事件生产者归属：图节点 / 收包循环直产 / Worker 直产三分类，`confirm_ack` 不可由图节点产出 |
| `security/secrets.py` | 递归脱敏（api_key/token/password/secret/cookie）+ 日志脱敏 | 注入模型前先脱敏（CX-3） |
| `security/auth.py` | 确认卡 owner 校验 + 行锁（`lock_pending_confirm`） | OR-8 安全 |
| `configurable` 注入 | ws.py 每回合注入 `thread_id / abort / credentials(api_key,user_id) / session(id) / assets(file_ids) / sandbox(dir,engine,limits)` | 回调与密钥不入 State；`sandbox_dir` 平台注入、**模型不可传**（M5-D7） |

---

## 6. 关键设计决策与红线

- **LangGraph 六层全覆盖**：依赖仅 `langgraph==1.2.10`，禁 langchain 全家桶/外部 MCP/LLM 子代理；**排除 `create_react_agent`**（tool-calling 会绕过参数绑定与白名单门禁）。
- **事件桥接**：图节点只返回纯数据（`pending_events`），ws.py 收包循环统一 emit；节点内禁止持有 WS 连接。
- **GraphState 可序列化**：状态只放 JSON 可序列化值；DB Session/WS 连接/回调不入 State。
- **确认卡收包循环直连**（不用 `interrupt()`）；澄清卡用 `interrupt()` + `Command(resume)`。
- **长任务必须走 Worker**（OR-6/EX-4）；`rag` 未接入不得 mock 成功。
- **沙箱 fail-closed**：bwrap 不可用/引擎关闭时 bash 拒绝执行，禁止降级裸 subprocess。
- **附件懒读取安全边界**：txt/md staging 在会话工作区内（防穿越不变），模型只拿到沙箱内相对路径，不暴露宿主路径。

---

## 7. 测试基线

`cd backend/api && ruff check . ../shared && pytest`（全量 337 项测试全绿，其中 9 项 skip；WS 测试需 `pytest-asyncio`，详见部署记忆）。

---

## 8. 模块文档导航

| 主题 | 文档 |
| :--- | :--- |
| 六层需求与验收 | `AI测试与评估平台-Harness需求文档.md` |
| 层1 提示词工程 | `AI测试与评估平台-Harness-提示词工程层.md` |
| 层2 上下文工程 | `AI测试与评估平台-Harness-上下文工程层.md` |
| 层3 记忆 | `AI测试与评估平台-Harness-记忆层.md` |
| 层4 编排 | `AI测试与评估平台-Harness-编排层.md` |
| 层5 执行 | `AI测试与评估平台-Harness-执行层.md` |
| 层6 反馈 | `AI测试与评估平台-Harness-反馈层.md` |
| 技能体系 | `AI测试与评估平台-Harness-技能体系.md` |
| 跨层契约 | `AI测试与评估平台-Harness-跨层契约层.md` |
| 跨层安全 | `AI测试与评估平台-Harness-跨层安全.md` |
| 运行时基础设施 | `AI测试与评估平台-Harness-运行时基础设施.md` |
| 联调规划 | `AI测试与评估平台-Harness团队开发与联调规划.md` |
| 对外契约 | `AI测试与评估平台-API.md` / `AI测试与评估平台-PRD.md` |

---

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-六层架构.md` | 新增（V0.1.0） | 六层架构总览与导航：职责/关键文件/跨层数据流/范式映射/文档索引；同步记录 2026-08-24 附件懒加载改动（txt/md staging + read offset/limit + has_attachments 强制 react + 截断标记） |

本次修订不改变任何 API、数据库表结构、前端或 Worker 运行契约。
