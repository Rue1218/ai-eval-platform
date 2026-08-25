# AI 测试与评估平台 — Agent 混合范式与架构完善

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Agent 混合范式与架构完善 |
| 版本 | V0.3.1 |
| 审查日期 | 2026-08-25 |
| 文档性质 | 演进规划（范式冻结 + 架构完善 + 分阶段接线，**本版不改对外契约**） |
| 适用范围 | `/agent` 对话智能体：LangGraph 单图、Harness 六层、WebSocket 事件桥、短工具与长任务分离 |
| 事实来源 | `backend/api/app/agent/`、`app/harness/`、`app/llm/`、`app/routers/ws.py`；前端 `Agent.vue` / `ToolCard.vue` |
| 上游权威 | PRD V1.12（产品范围）；API.md V1.34（REST/WS 字段唯一真理）；Agent 开发文档 V1.4.1（当前运行链路）；Harness 六层架构 V0.1.1、编排层 V0.4.3 |
| 参考实现 | Claude Code 设计指南第 7 章（两层状态）、第 9 章（原子工具与 ToolResult 回灌）；业界 Plan-and-Execute / Reflexion |

> **阅读关系**：本文是「当前已跑通的受控 ReAct」到「可规划、可中间叙述、可有界重规划」的**完善规划**。六层职责仍以《Harness 六层架构》为准；图节点与路由细节以《编排层》为准；JSON 字段名与 WS 事件以 API.md 为准。本文**不新增** REST/WS 字段；若后续阶段需要新事件或放宽 `assistant_message` 语义，必须先改 API.md / PRD，再改代码。
>
> **一句话目标**：外层循环由代码控制，模型只负责感知与推理；控制流采用 Observe → Think → Act；用户看见的是「阶段叙述 + 工具卡」，模型看见的是完整 Observation；复杂任务走 Plan-and-Execute，失败按分级 Reflexion 有界重规划。

---

## 1. 为什么要完善

### 1.1 现网已经成立的部分

当前唯一运行链路没有第二条 Agent 循环，这是后续一切扩展的前提：

```text
浏览器 WS /ws/agent
  → routers/ws.py（短票、落库、后台回合、事件投影）
  → agent/graph.py（LangGraph 单图）
      → routing → direct | chat_stream | react_agent ⇄ tools
      → 多技能：plan_solve → react_agent ⇄ tools → reflect
      → llm/gateway.py → adapters.py（三协议）
      → harness/execution（native 基础工具 / 内部 MCP / bwrap）
  → 长任务只入 PG 队列，由 Worker 执行
```

已经对齐混合架构的工程内核：

| 原则 | 现网落点 |
| :--- | :--- |
| LLM 当受控微服务，外层循环由代码控制 | `react_route` / ToolNode 门禁 / Schema / bwrap；模型不能跳过校验 |
| 图纯、桥脏 | 节点只返回 `pending_events`；WS / DB / 密钥走 `configurable` |
| 短长分离 | 对话内只跑短工具；`benchmark` / `testcase` / `rag` / `stress` 入队 |
| 观察与展示分离 | `model_text` 只进模型；`tool_result` 只给 ToolCard 受控预览 |
| 原子工具 | `read` / `write` / `edit` / `bash` / `web_*` / `task` 各做一件事 |

### 1.2 现网和目标形态的落差

对照 Claude Code 类工作台（阶段叙述 → 工具卡 → 再叙述 → 再工具）与本平台产品目标，缺口集中在「编排闭环」而不是「再写一套 Harness」：

| 维度 | 现网 | 目标 |
| :--- | :--- | :--- |
| 路由 | 代码主导：斜杠 / 附件 / 多技能 / 工具词 → Direct / ReAct / Plan-and-Solve / Chat | 保持代码选模式；复杂任务才出 `PlanArtifact` |
| Plan-and-Execute | 多技能进入 `plan_solve` → ReAct 执行短工具 → `reflect` 收尾 | 中间叙述、澄清卡 interrupt、有界重规划仍属后续 |
| 用户可见节奏 | 工具卡堆完，回合结束才一条 `assistant_message` | 中间也可落阶段叙述（计划 / Skill 已加载 / 下一步） |
| 观察流 | 已注入模型；失败文案偏「错误码」 | 失败带 `repair_hint`（可修复、可定位） |
| 任务清单 | `task` 工具能产会话内步骤，无独立回放态 | `todos` / `PlanArtifact` 成为会话一等状态，前端清单卡 |
| Reflexion | OR-4 重复纠正 + 确定性门禁 | 规则 → 计算 → 推理分级；连续失败且允许则有界重规划 |
| 状态分层 | GraphState + 进程内 abort/clarify dict + 内存 Checkpointer | 明确「平台级 / 会话级 / 回合级」，todos 不进助手正文 |

---

## 2. 范式冻结

### 2.1 混合范式定义

本平台 Agent **不是**通用自治 Agent，而是评测工作台的受控助手。混合范式固定为三层，全部挂在**同一张** LangGraph 图上：

```text
                    ┌──────────── Planner ────────────┐
                    │ 代码选模式；复杂任务才调模型出计划 │
                    │ 产出：mode + 可选 PlanArtifact    │
                    └───────────────┬─────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
           Direct                 Chat              Executor
         （斜杠/L0）          （无工具流式）     （OTA 主战场）
                                                      │
                                                      ▼
                                                 Reflexion
                                      规则 → 计算 → 推理（按需）
                                      pass / clarify / 有界重规划
```

| 层 | 谁主导 | 输入 | 输出 | 禁止 |
| :--- | :--- | :--- | :--- | :--- |
| **Planner** | 代码选模式；仅复杂任务调 LLM（**现状未接线**，见 §4.1） | 用户文本、附件、活动任务、上一轮失败原因 | `mode`；可选 3–7 步 `PlanArtifact`（可经 `task` 显式清单） | 在对话回合同步跑评测 / 压测；另起子 Agent 循环 |
| **Executor** | 代码循环；模型只出 Thought + ToolCall | 当前步、Observe 集合、工具 schema | `tool_call` 或阶段 / 最终正文 | 跳过 Schema / 门禁 / 沙箱；并行无门禁执行 |
| **Reflexion** | 代码分级；模型核对只能降级 | 计划、Observation、预算、重复计数 | `pass` / `clarify` / `reject`；可选打回 Planner | `reject→pass`；无预算的无限重规划 |

`task` 是 Planner 的**显式出口**（会话内步骤清单），不是评测入队。评测入队只走 `platform.tasks.task.create` + 确认卡 / REST，与对话拆解分离（API.md V1.32）。

### 2.2 控制流：Observe → Think → Act（OTA）

经典教材 ReAct 写成 Thought → Action → Observation。本平台把**控制语义**改为 Observe → Think → Act，更符合「先看证据再决策」：

```text
Observe  = 用户原文 + 附件 + 上一轮 Observation（模型可见，可含 repair_hint）
Think    = thought / 上游 reasoning 摘要（用户可见折叠卡）+ 可选阶段叙述
Act      = tool_call（短工具）或最终 assistant_message
```

现网**后半圈已经是 OTA**：ToolNode 写入 `observations` / `native_messages` 后，下一轮 `react_agent` 先注入观察再调模型。缺的是：

1. 提示词写明「先基于【工具结果】思考，再决定行动」；
2. 允许「阶段叙述 + ToolCall」同轮出现（见 §4）；
3. 第一圈把用户消息 / 附件 / 活动任务明确当作 Observe，而不是空转 Thought。

Plan-and-Execute 的每一步也必须是 OTA：Planner 先 Observe（槽位、是否已有活动任务、附件），再拆步；Executor 逐步执行，不得先写空计划再补证据。

### 2.3 模式选择（代码主导，不每轮问模型）

`decide_mode` 继续是唯一分流入口，阶段完善后扩展输入，不改为「先让 LLM 选模式」：

| 条件 | 模式 | 说明 |
| :--- | :--- | :--- |
| 文本以 `/` 开头 | `direct` | L0，不调模型；`/stop` `/compact` 仍由 WS 直连 |
| 无工具意图、无附件、单轮问答 | `chat` | 流式正文，不注入工具 schema |
| 单工具意图、带附件、或计划中的单步 | `react` | OTA 循环；附件强制 react（模型需 `read`） |
| 多槽、多 skill、要确认卡、用户显式要清单 | `plan_solve` | 先 `PlanArtifact`，每步复用 react ⇄ tools |
| Reflexion 连续失败且 `allows_replan=true` | 回到 Planner | 计入 `Budget`，次数封顶 |

`has_multi_slots` 已由 `routing_node` 传入 `detect_plan_intent(text)`（P0 已接线）：由路由层根据技能组命中数、确认卡意图、清单措辞等**确定性特征**填写，禁止用另一次模型调用做路由。

### 2.4 三条通道：观察、展示、叙述（硬约束）

截图式工作台容易被误读成「把 Observation 写进 aimessage」。本平台冻结为三条通道，互不替代：

| 通道 | 事件 / 存储 | 给谁 | 内容 | 禁止 |
| :--- | :--- | :--- | :--- | :--- |
| **观察** | GraphState `observations` / `native_messages`；`model_text` 仅内存 | 下一轮模型 | 完整或按工具上限截断的结果；失败含 `repair_hint` | 写入 `ws_events`、`messages`、日志原文 |
| **展示** | `tool_call` / `tool_result` → ToolCard | 用户 | `call_id`、短预览、行范围、脱敏 / 截断徽标 | `read` 全文、密钥、上游协议字段 |
| **叙述** | `assistant_delta` / `assistant_message` | 用户 | 计划宣布、阶段结论、「Skill 已加载，下一步…」、最终交付 | 粘贴 Observation 原文；复读工具卡 |

对应关系：

```text
用户看见：  [阶段叙述] → [ToolCard × N] → [阶段叙述] → [ToolCard] → [最终回答]
模型看见：  Observe(完整) → Think → Act
落库：      叙述进 messages / 持久 assistant_message
            工具进 ws_events（受控 tool_result）
            观察全文不落库、不进检查点
```

API.md V1.25 / V1.26 已冻结 `read` 的 `tool_result.data` 与 `call_id`。完善阶段**不得**把 `model_text` 提升为 `assistant_message`。若产品需要「观察摘要气泡」，只能是模型根据 Observation **新生成的短叙述**（建议 ≤ 200 字），且须先改 API.md 明确「中间 `assistant_message` 可多次」。

---

## 3. 目标架构

### 3.1 仍保持「一张图、一个模型入口」

禁止新增第二条 Harness 循环或绕过 `ModelGateway` 的协议客户端。目标拓扑在现图上加边，不复制节点：

```text
START → routing
          ├─ direct ──────────────────────────────────────── END
          ├─ chat_stream ────────────────────────────────── END
          └─ planner（完善后：简单直接标 react；复杂出 plan）
                │
                ├─ react_agent ⇄ tools ──► (可选中间叙述) ──► reflexion
                └─ plan_solve
                      │  按 PlanArtifact.tools_needed / steps 逐步
                      │  每步仍走 react_agent ⇄ tools
                      ▼
                   reflexion
                      ├─ pass     → 最终 assistant_message → END
                      ├─ clarify  → interrupt()（人补槽，不建任务）
                      └─ retry    → planner（仅 allows_replan 且预算未尽）
```

`clarify` 节点与图上边（`reflect → clarify`、`clarify → plan_solve`）均已接线（P2 已落地）：按 `verdict=clarify` 挂 interrupt，不与确认卡混用（澄清不写 `pending_confirm`、不占任务槽）。

确认卡继续 **WS 直连** `handle_confirm_ack`，不唤醒图、不占回合预算（编排层 OR-8）。长任务进度由 Worker 写 `ws_events`，不进模型窗口（反馈层 FB-5）。

### 3.2 三层状态（对齐 Claude Code 两层，补回合层）

Claude Code 把状态分成 Bootstrap（进程）与 AppState（会话）。本平台再拆出回合层，避免把 ToolResult 全文和密钥推进检查点：

| 层 | 存活范围 | 现网对应 | 完善后放入 | 不放入 |
| :--- | :--- | :--- | :--- | :--- |
| **平台级** | 进程 / 部署 | `settings`、协议档、沙箱引擎、MCP 度量、默认 Checkpointer | 继续保持少而稳 | 会话 todos、单轮 Observation 原文 |
| **会话级** | 一个 `session_id` | `messages`、`ws_events`、工作区、`pending_confirm`、活动任务 | **todos / PlanArtifact 投影**、进行中 `call_id` 集合 | `api_key`、abort 回调 |
| **回合级** | 一次 `_run_turn` | `GraphState`、`NativeToolResultStore`、`thread_id` 检查点、进程内 abort | `repair_hint`、`repeat_retry`、本轮 budget | 跨回合复用的全文工具结果 |

更新原则与 Claude Code 第 7 章相同：**函数式 / reducer 追加，禁止「先读后写」竞态**。现网 `pending_events` / `observations` / `native_messages` 的 append reducer 继续沿用。`write_todos` 类能力复用已有 `task` 工具 + 会话态，不把清单文本写入 `assistant_message`。

Checkpointer：生产默认仍为 `InMemoryCheckpointer`（每回合独立 `thread_id`）。`PgCheckpointer` 表结构已就绪，切换须单独评审；恢复时 `pending_events` 必须清空，事件重放只走 `ws_events`（M3-D4）。

### 3.3 执行层：继续原子工具 + 显式上下文

对齐 Claude Code 第 9 章，不改执行哲学，只补描述与失败观察质量：

| 原则 | 本平台要求 |
| :--- | :--- |
| 统一接口 | 继续 `ToolDef`：`name` / `description` / `parameters_schema` / `handler` / `transport` |
| 描述即文档 | 每个工具写清适用、不适用、前置条件（如 edit 必须先 read，`old_string` 须唯一） |
| 显式上下文 | 副作用只经 `ToolExecutionContext` + `configurable`，禁止全局隐式读写 |
| 原子性 | 禁止「检索+分析+写设计」超级工具；复杂编排由 Planner / 模型完成 |
| 结果截断 | `model_text` 与 `display` 继续分离；截断必须带 `truncated` 与下一步（如 `next_offset`） |
| 幂等与确认 | 只读工具可重试；`write` / `edit` / `bash` 受 OR-4 与门禁约束；长工具必须确认卡 / 队列 |
| 双通道 | `transport=native`：read/write/edit/bash/web_search/web_fetch/task；`transport=mcp`：仅 `platform.tasks.*` 与未来评测扩展 |

同轮多个原生 ToolCall **继续串行**过门禁，不引入真正并行（Agent 开发文档冻结项）。外部 MCP、浏览器直连 MCP、动态加载未知 Server 仍禁止。

### 3.4 Observation 完善（不改 WS 事件名）

在现有 `Observation` 上增加规划字段（检查点 / 模型注入使用，**不自动出现在 `tool_result`**）：

```text
Observation
  tool / ok / arguments / source / truncated / redacted
  text            归一后的模型可见正文（现有）
  display         ToolCard 用（现有，经 tool_result.data）
  repair_hint     失败时必填：可操作修复建议（已接线，P0）
                  例：「edit 失败：未找到匹配文本；文件第 42 行附近是：…」
  progress        可选：已完成步骤、未读完 offset、todos 当前项（**待加**：
                  契约尚无该字段，且 from_dict 拒绝未声明字段，落地须先改契约）
```

`normalize()` 失败路径今日只回 `操作失败（ErrorCode）`。完善后：有文件位置 / 参数缺失 / 未读完时必须带 `repair_hint`；无内部栈、无密钥、无 SQL。

### 3.5 中间叙述（产品形态，契约需分阶段）

目标 UI（与参考截图同构，事件名不新造）：

```text
assistant_message   「收到需求。先建清单，再按评测技能检索工作区。」
tool_call/result    task / read / …
assistant_message   「清单已建立。下一步读取协议档与数据集摘要。」
tool_call/result    read / …
assistant_message   「依据已读内容，结论是…」（回合收尾）
response.completed
```

落地约束：

1. **P0（契约内）**：native 路径已能在工具后流式投影 `assistant_delta`。完善提示词，允许「先输出简短阶段叙述，再发起 ToolCall」；若同轮只有 ToolCall 无正文，保持现状，不强制每步说话。
2. **P1（须先改 API.md）**：明确同一用户回合允许**多条**持久 `assistant_message`（阶段叙述），`response.completed` 仍表示整轮结束。前端 `Agent.vue` 按事件序组块：`thought → tool → assistant → tool → assistant`。
3. 任意阶段都禁止把 `Observation.text` / `model_text` 当作助手正文。重复 read 收敛、预算耗尽、强制收尾时，必须再走无工具模型总结（现网已有，保持）。

`thought` 继续只承载推理摘要 / 阶段机读状态，不承载助手正文（与 `agent_reasoning` 配置一致）。

---

## 4. Planner / Executor / Reflexion 详细设计

### 4.1 Planner

**职责**：理解目标，把复杂任务拆成 3–7 步高层计划；简单任务直接标 `react` 或 `chat`。

输入（全部确定性，可序列化）：

- 最近用户文本、是否有附件、`owned_file_ids`
- 会话是否存在活动任务（`get_active_tasks`）
- 可见技能 hint（`skills.list_hints`，`skill-rag` 未启用须在计划中拒绝）
- 上一轮 Reflexion 的失败原因（若有）

输出：

- `mode ∈ {direct, chat, react, plan_solve}`
- 可选 `PlanArtifact`：`intent` / `skill_id` / `slots` / `tools_needed` / `delivery` / `budget` / `allows_replan` / `notes`
- 可选会话 todos（来自 `task` 工具或计划 steps 的投影）

规则：

- 规划解析失败重试一次，仍失败走 L0 关键词降级，降级产物必须经 Reflexion（现 `build_plan` 已具备，需真正被路由调用）。
- **LLM 规划未接线（实现现状）**：`build_plan` 目前只对用户原始文本做严格 JSON 解析（几乎必然失败）后走 L0 关键词降级，`plan_solve` 全程无模型调用。§2.1 的「仅复杂任务调 LLM」与 Q3 的短模型生成 JSON 计划仍是目标态；接线时须把上一轮 Reflexion 失败原因一并传入规划输入，避免重规划拿不到新信息。
- `delivery=confirm` 时不得缺工具；对话路径不得直接发起压测确认卡（系统策略已写，规划器必须遵守）。
- 计划步数 3–7；超出则合并，不足且无多槽则降为单圈 ReAct。

### 4.2 Executor

**职责**：OTA 循环的主战场。接收当前步，思考后调用工具；参数由代码校验后执行。

保持现网 ReAct 双协议：

| 协议档 `tool_call_mode` | 行为 |
| :--- | :--- |
| `legacy`（默认） | 严格 `react.v1` JSON；解析失败最多纠正 2 次 |
| `native` | Function Calling；同轮多调用串行；工具后第二回合流式收敛 |

守卫（已有，完善时只调参不推翻）：

- 计数预算：`model_calls` / `tool_turns`（当前默认 12，计划派生可收紧）
- 只读工具同参成功 ≥3 次：纠正 → 再重复则无工具总结
- 副作用工具同参：首次纠正，再次硬错误
- 长工具名命中即 `VALIDATION`，必须走队列

Executor **不**负责宣布最终成功；最终交付由 Reflexion `pass` 或「无计划的普通 ReAct done」发出。

### 4.3 Reflexion

**职责**：有明确验证标准时开启；按成本分级，失败反馈 Planner。

| 级 | 类型 | 谁执行 | 示例 | 失败 |
| :--- | :--- | :--- | :--- | :--- |
| L1 | 规则验证 | 代码，不调模型 | 门禁、必填槽、一单一 kind、先评后压、技能是否启用 | `reject` 或 `clarify` |
| L2 | 计算验证 | 代码 | 预算、重复次数、文件是否读完、todos 是否卡住、活动任务占槽 | 纠正观察或 `retry` |
| L3 | 推理验证 | 仅当有验收标准时调 `review()` | 计划与 Observation 是否回答了用户问题 | 只允许 `pass→clarify` |

连续失败阈值（目标阶梯，实现时写入 `Budget` / 常量，禁止魔法数散落）：

- 同一步 L2 失败 2 次 → 注入 `repair_hint` 后再给 Executor 一次；
- 仍失败且 `allows_replan=true` 且重规划次数 &lt; 2 → 回到 Planner，notes 带失败原因；
- 否则 `reject` / `error(VALIDATION)` 收尾，向用户说明卡在哪一步。

**实现现状（P2 已落地，与上述阶梯的差异）**：

- `reflect_node` 在工具首次失败且 `allows_replan` 且重规划次数 < 2 时**直接 `retry` 重规划**，尚无「先注入 `repair_hint` 再回 Executor 一次」的中间档；
- 重规划未把上一轮失败原因传入 `build_plan`，两次重规划可能产出相同计划，仅靠次数上限兜底（P2 遗留项）；
- 重规划计数为 GraphState 独立字段 `replan_count` + `MAX_REPLANS=2` 常量，未并入 `Budget` dataclass（语义等价，后续如需统一预算口径再合并）；
- `allows_replan=false` 且工具失败时，`review` 对 `not obs.ok` 返回 `clarify`，即澄清卡兼作失败兜底出口（行为合理，与「澄清=人补槽」原语义略有扩张）。

`reflect.py` 今日对无 `plan` 直接 `pass`，且 `review(model_call=None)` 跳过推理。接线后：无计划的纯 ReAct 仍可跳过 L3；有 `PlanArtifact` 必须跑 L1+L2。

---

## 5. 与现有文档的冲突裁决

| 主题 | 以谁为准 | 本文立场 |
| :--- | :--- | :--- |
| REST/WS 字段、事件名、`call_id`、`read` 投影 | API.md V1.32+ | 本版不改；P1 中间多条 `assistant_message` 必须先改 API.md |
| 产品范围、确认卡字段、先评后压 | PRD | 不扩大到外部 MCP、多租户、自定义系统提示词 |
| 当前已实现链路 | Agent 开发文档 V1.4.1 | P0–P2 已接线；LLM Planner（Q3）与「先回 Executor 再重规划」阶梯仍属目标 |
| 六层职责、GraphState、门禁 | Harness 各层模块文档 | 本文只规定完善项与挂载点 |
| 《Agent 重设计工作区》V0.3 仍写「Harness 冻结」 | 已被开发文档 / 六层架构取代 | 以开发文档与本文为准，工作区文档视为历史快照 |

《编排层》V0.4.3 已回写：OR-4 为同轮串行多 ToolCall + 重复抑制；默认预算 12/12。运行事实仍以 `budget.py` 与 Agent 开发文档 V1.3.1 为准。

---

## 6. 明确不做什么

1. 不新增第二条 Agent / 模型客户端 / `create_react_agent`。
2. 不把 Observation / `model_text` 写入 `assistant_message`、`ws_events` 或检查点。
3. 不把 RAG / LightRAG mock 为 `succeeded`；语义记忆 `retrieve` 未接入前保持 `VALIDATION`。
4. 不在 API 进程同步执行评测、用例生成、知识库评测、压测。
5. 不引入外部 MCP、浏览器直连 MCP、未知 Server 动态加载、真正并行 ToolCall。
6. 不在 `main` 上开发；功能按 `feat/agent-*` 分 PR，契约变更先改 API.md。
7. 不把 todos / 计划原文当作唯一用户可见进度（必须有清单卡或阶段叙述，二者都不是工具原文）。
8. 不用 LLM 替代 `decide_mode` 做每次分流。

---

## 7. 分阶段落地

阶段划分遵循「先接线、后体验、再闭环」。每一阶段单独开分支、单独 PR；阶段完成须回写本文版本号与「修改代码文件与作用清单」，并视需要回写 Agent 开发文档 / 编排层 / API.md。

### P0 — 范式接线（不改对外契约）

**目标**：路由能进入 `plan_solve`；OTA 写进提示词；Observation 带 `repair_hint`；无新 WS 事件。

| 项 | 内容 |
| :--- | :--- |
| 路由 | `routing_node` 传入多槽 / 多 skill / 确认卡意图；命中则 `plan_solve` |
| 规划 | 调用现有 `build_plan`；缺计划时 L0 降级；`plan` 事件若前端未渲染可先只打 `thought.stage=plan` |
| 提示词 | ReAct / native 阶段输入改为「先观察【工具结果】，再思考，再行动」 |
| 观察 | `Observation.repair_hint` + `normalize` 失败补修复建议 |
| 工具描述 | `read` / `edit` / `task` 补适用、不适用、前置条件 |
| 验收 | 多槽评测表述进入 `plan_solve`；单关键词仍 ReAct；edit 失败 Observation 含行号或邻近文本；WS 事件名集合与 API.md V1.32 一致 |
| 建议分支 | `feat/agent-hybrid-p0-planner` |
| 状态 | **已落地**（V0.2.0） |

### P0+ — 规划接到执行（不改对外契约）

**目标**：修审查缺口，把 `PlanArtifact` 真正交给 ReAct，并由 `reflect` 统一收尾。

| 项 | 内容 |
| :--- | :--- |
| 规划 | L0 合并全部命中技能（不再先命中先返回）；步骤 3–7；`tools_needed` 只含短工具 `task` |
| 事件 | `plan` 下发完整 PlanArtifact；规划节点不再发 `response.completed` |
| 图 | `plan_solve → react_agent ⇄ tools → reflect → END`；失败规划就地收尾 |
| 执行 | ReAct 注入【当前规划】；有 plan 时不发 `response.completed` |
| 复核 | reflect 发出本轮唯一 `response.completed`（reject 为 `finish_reason=error`） |
| 验收 | 多技能事件序为 plan → assistant_message → reflect thought → completed；无假 `tool_call` |
| 建议分支 | 仍在 `feat/agent-hybrid-p0-planner` |
| 状态 | **已落地**（V0.2.1：失败收尾、计划预算、invoke、中英关键词对齐） |

### P1 — 中间叙述与清单（须先改 API.md）

**目标**：同一回合可多条阶段 `assistant_message`；`task` / 计划投影为可回放清单。

| 项 | 内容 |
| :--- | :--- |
| 契约 | API.md 声明：单回合允许多条 `assistant_message`；`response.completed` 仍为整轮结束；清单若用现有 `plan` / `tool_result(task)` 则不新事件 |
| 后端 | native 同轮「正文 + ToolCall」时先 persist 阶段叙述再执行工具；legacy 不强制 |
| 前端 | `Agent.vue` 按事件序插入多段助手正文，不把后续叙述并进第一条 |
| 状态 | 会话级 todos 与 `PlanArtifact.steps` 同源；刷新后能回放 |
| 验收 | 出现「叙述 → 工具卡 → 叙述 → 工具卡 → 最终回答」；刷新不丢阶段句；read 全文仍不进历史 |
| 建议分支 | `feat/agent-hybrid-p1-p2` |
| 状态 | **已落地**（API.md V1.33；native 阶段叙述；`plan.slots.steps` 清单） |

### P2 — Reflexion 回边

**目标**：有计划的任务跑 L1+L2；连续失败有界重规划。

| 项 | 内容 |
| :--- | :--- |
| 图 | `react` / `plan_solve` 后进入 `reflect`；`verdict=clarify` 挂 `interrupt`；`retry` 回 `planner` |
| 预算 | 重规划次数封顶 2（实现为 GraphState 独立字段 `replan_count` + `MAX_REPLANS` 常量，未并入 `Budget`，见 §4.3） |
| 验收 | 缺槽澄清可 resume；故意重复失败会重规划一次后收尾，不会打满 12 轮空转 |
| 建议分支 | `feat/agent-hybrid-p1-p2` |
| 状态 | **已落地**（`verdict=clarify` 挂 interrupt；失败且 `allows_replan` 重规划 ≤2） |

### P3 — 记忆与检查点（独立评审）

**目标**：按需切换 `PgCheckpointer`；压缩摘要与 todos 联动；仍禁止 Observation 全文持久化。

本阶段不默认开工。代码提供 `AGENT_CHECKPOINTER=memory|postgres`，**默认 memory**；切 postgres 须单独评估多副本粘性路由与 `harness_checkpoints` 运维。语义记忆 / LightRAG 仍 fail-closed。

| 状态 | **可选能力已接线，默认关闭** |

---

## 8. 验收总表

| 编号 | 断言 | 阶段 |
| :--- | :--- | :--- |
| H-A1 | 仍只有一个 `LangGraphAgent` 入口和一个 `ModelGateway` | 全程 |
| H-A2 | 简单问题走 Chat/ReAct，不强制出 3–7 步计划 | P0 |
| H-A3 | 复杂 / 多槽走 `plan_solve`，步骤 3–7 | P0 |
| H-A4 | 模型上下文能看到上一轮 Observation；用户历史看不到 `read` 全文 | 全程 |
| H-A5 | 工具失败 Observation 含 `repair_hint`，且 `tool_result` 仍脱敏 | P0 |
| H-A6 | 中间叙述（若启用）不是 Observation 原文 | P1 |
| H-A7 | `allows_replan` 重规划 ≤2，预算耗尽必停 | P2 |
| H-A8 | `skill-rag` / 未接入能力返回 `VALIDATION`，不 mock 成功 | 全程 |
| H-A9 | bash 仍走 bwrap，引擎 `off` fail-closed | 全程 |
| H-A10 | 确认卡仍 WS 直连，澄清卡与确认卡互斥 | P2 |

测试落点（实施时补，不在本文发明用例名之外的新框架）：

- `backend/api/tests/test_agent_graph.py` / `test_agent_react.py`：路由、OTA 注入、中间叙述不泄露 `model_text`
- `test_harness_execution.py`：`repair_hint`、工具描述回归
- 前端 `Agent.vue` 相关单测或手工：多段 `assistant_message` 回放（P1）

---

## 9. 推荐实施顺序与人力切分

按仓库「一模块一分支」：

1. **编排 / Agent 图**（`feat/agent-hybrid-p0-planner`）：路由接线、`build_plan` 真正调用、提示词 OTA、`repair_hint`
2. **契约 + 前端**（P1）：API.md 中间叙述、`Agent.vue` 组块、todos 回放
3. **反馈 / 图边**（P2）：`reflect` 条件边、重规划、clarify 挂载
4. **文档回写**：Agent 开发文档拓扑、编排层 OR-4/预算、六层架构「范式映射」表把 Plan-and-Execute / Reflexion 从「最小实现」改为对应阶段状态

Buy / Build（本平台已选定，本文只重申）：

- **Buy**：上游模型、三协议 HTTP、Firecrawl 检索
- **Build**：门禁、确认卡、沙箱、评测入队、错误码、观察三通道、模式路由

---

## 10. 开放问题（不阻塞 P0）

| 编号 | 问题 | 默认倾向 | 谁拍板 |
| :--- | :--- | :--- | :--- |
| Q1 | 中间叙述是否对 `legacy` 协议档也强制 | 否，仅 native；legacy 保持收尾一条正文 | 产品 + 协议档负责人 |
| Q2 | todos 用现有 `plan` 事件还是 `task` 的 `tool_result` | 先复用 `task` 结果 + 会话投影，避免新事件 | 实施 P1 时对照 API.md |
| Q3 | Planner 复杂任务是否用一次短模型调用生成 JSON 计划 | 是，失败走 L0；不得用多 Agent 辩论 | 架构 |
| Q4 | 阶段叙述字数上限 | 建议 200 字，超出截断并记 `truncated` 仅服务端 | P1 契约 |
| Q5 | 何时切 `PgCheckpointer` | 多副本或澄清卡跨进程恢复成为需求时 | 运维 + 架构 |
| Q6 | 关键词路由（`detect_plan_intent`）的召回边界：同组关键词共现（如「评测 + benchmark」）不算多技能，可能漏升 `plan_solve` | P0 确定性启发式可接受；LLM Planner 接线后由模型规划兜底 | 架构 |

---

## 11. 术语

| 术语 | 含义 |
| :--- | :--- |
| OTA | Observe → Think → Act，本平台控制流语义 |
| 阶段叙述 | 工具之间的简短 `assistant_message` / 增量，描述计划与下一步，不是工具原文 |
| Observation | 供模型使用的工具结果对象，与 ToolCard 展示分离 |
| `PlanArtifact` | 可序列化规划产物，字段以 `harness/contracts/artifacts.py` 为准 |
| todos | 会话级步骤清单，Planner / `task` 工具的用户可见投影 |
| 有界重规划 | Reflexion 打回 Planner，次数计入预算且上限为 2 |

---

## 修改代码文件与作用清单

V0.1.0 为规划文档。V0.2.0 记录 P0 / P0+ 已接线。V0.2.1 收口审查缺口。V0.3.0 记录 P1 / P2 接线。V0.3.1 为架构审查后的状态校准（纯文档，无代码改动）。

- `docs/AI测试与评估平台-Agent混合范式与架构完善.md`：V0.1.0 冻结混合三层与 P0–P3 计划；V0.2.0 将 Plan-and-Execute 改为 `plan_solve → react → reflect`；V0.2.1 记录失败收尾与预算接线。
- `backend/api/app/harness/orchestration/plan.py` / `agent/plan_solve.py` / `graph.py` / `react.py` / `reflect.py`：P0+ 规划合并、执行接线；硬错误 `completed(error)`、清空非法 plan、`plan.budget` 写入图状态、`invoke` 接受 `plan_solve`、L0 中英别名、reflect 非法 plan 兜底。
- `docs/AI测试与评估平台-Agent开发文档.md`：V1.3.1 拓扑回写。
- `docs/AI测试与评估平台-Harness-编排层.md` / `Harness-六层架构.md`：OR-4 串行多调用、默认预算 12/12、范式映射回写。
- V0.3.0：P1 中间叙述与清单、P2 澄清/有界重规划已接线；P3 检查点默认 memory，`AGENT_CHECKPOINTER=postgres` 可选。涉及：`backend/api/app/agent/react.py`（native 同轮阶段叙述 + `interim`）、`agent/reflect.py`（有界重规划 / 非法 plan 兜底）、`agent/clarify.py`（澄清卡 interrupt）、`agent/graph.py`（`reflect → clarify`、`clarify → plan_solve` 边）、`app/config.py` + `app/harness/memory/checkpoint.py`（`AGENT_CHECKPOINTER` 开关）、`docs/AI测试与评估平台-API.md`（V1.33 多条 `assistant_message`）。
- `docs/AI测试与评估平台-Agent混合范式与架构完善.md`（V0.3.1）：校准滞后陈述——§2.3 `has_multi_slots` 已接线、§3.1 `clarify` 图边已挂载；§2.1 / §4.1 明确 LLM Planner 未接线、当前为纯规则解析 + L0 降级；§4.3 拆分目标阶梯与实现现状（首次失败即重规划、`replan_count` 独立于 `Budget`、澄清卡兼作失败兜底）；§3.4 标注 `Observation.progress` 待加；§5 开发文档引用统一为 V1.4.1；§10 新增 Q6 关键词路由召回边界；删除文末误留的孤立右括号。
