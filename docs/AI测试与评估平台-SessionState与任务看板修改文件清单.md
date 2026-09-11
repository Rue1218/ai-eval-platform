# AI 测试与评估平台 — SessionState 与任务看板修改文件内容详述

> 📦 **历史归档（2026-09-11）**：本文为历史设计稿 / 规划，其中提及的 `agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除或演进，仅作决策留痕；请勿按本文直接立项。

| 项 | 内容 |
| :--- | :--- |
| 文档版本 | V1.1 |
| 审查日期 | 2026-08-29 |
| 对应提交 / PR | PR #137 (Commit `fb4f934`) |
| 涉及模块 | 后端 Harness 契约层、记忆层、编排层、执行层、反射层；前端类型层、抽屉看板组件、Agent 对话视图 |

---

## 1. 概述与核心变更意图

本次升级解决了大模型在处理复杂多步任务时的三大痛点：
1. **“做到一半开始总结”**：模型在获取中间输出后过早输出自然语言总结，中断了排查链路；
2. **“在同一个被排除的方向上反复踩坑”**：由于长上下文注意力稀释，已证伪的假设容易被遗忘；
3. **“缺乏显式可交付状态与用户可见的任务流”**：前端缺少即时、清晰的多任务进度展示。

本方案在后端建立了 **Session State（结构化认知黑板）** 状态机，结合 Reflect 物理拦截门禁，并在前端对话输入框上方设计了抽屉卡片（`TaskStateDrawer.vue`），严格按照 `task 1 ：XXXXX` 格式展示任务流与动态状态动效。

---

## 2. 修改与新增文件详细内容清单

### 2.1 后端文件 (Backend)

#### 1. `[NEW]` [`backend/api/app/harness/contracts/task_state.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/harness/contracts/task_state.py)
* **作用**：定义结构化任务状态机的核心不可变契约、演进逻辑与状态守卫。
* **主要内容**：
  - `FailedStep` 与 `RejectedHypothesis` 数据类：用于结构化存储单步失败原因与被证伪的假设及凭据引用。
  - `TaskSessionState` 数据类：涵盖 `goal`（终局目标）、`phase`（阶段）、`completed_steps`、`current_step`、`next_actions`、`failed_steps`、`current_hypothesis`、`confirmed_facts`、`evidence`、`rejected_hypotheses`、`missing_info`、`can_deliver` 等字段。
  - `to_dict` / `from_dict` 安全序列化方法：内置**不变式防线**——只要 `missing_info` 非空，强制设置 `can_deliver = False`，杜绝伪完工。
  - `evolve_task_state` 纯函数：接收最新 `Observation` 观察队列，自动根据工具调用的 `ok` 状态将数据沉淀为事实或失败记录、证伪假设，并推进步骤队列与更新交付资格。

#### 2. `[MODIFY]` [`backend/api/app/harness/contracts/__init__.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/harness/contracts/__init__.py)
* **作用**：对外统一暴露状态机契约符号。
* **主要内容**：
  - 导出 `TaskSessionState`、`FailedStep`、`RejectedHypothesis`、`TaskPhase` 与 `evolve_task_state`。

#### 3. `[MODIFY]` [`backend/api/app/harness/memory/state.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/harness/memory/state.py)
* **作用**：扩展 LangGraph 图状态数据容器。
* **主要内容**：
  - 在 `GraphState` TypedDict 中追加 `task_state: Mapping[str, object] | None` 纯数据投影字段，确保在各节点（Planner、ReAct、ToolNode、Reflect）间透明传递且 100% JSON 可序列化。

#### 4. `[MODIFY]` [`backend/api/app/harness/orchestration/plan.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/harness/orchestration/plan.py)
* **作用**：实现从规划产物到状态机的转换适配。
* **主要内容**：
  - 实现 `task_state_from_plan(plan: PlanArtifact) -> TaskSessionState`：优先解析模型在 `slots` 中携带的高级状态，缺省时根据 `intent` 与 `steps` 自动构建初始任务黑板，将未执行步骤结构化为初始信息缺口。

#### 5. `[MODIFY]` [`backend/api/app/harness/orchestration/__init__.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/harness/orchestration/__init__.py)
* **作用**：导出编排工具函数。
* **主要内容**：
  - 导出 `task_state_from_plan`。

#### 6. `[MODIFY]` [`backend/api/app/agent/plan_solve.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/agent/plan_solve.py)
* **作用**：在 Plan-Solve 节点中生成并注入初始任务状态。
* **主要内容**：
  - 当生成规划时调用 `task_state_from_plan` 生成 `task_state`，存入返回值中的 `state["task_state"]`。
  - 同步将 `task_state.to_dict()` 嵌入 `plan_payload["slots"]["task_state"]`，使得现有的 `plan` WebSocket 事件无需扩展未知事件名即可透明下发至前端。

#### 7. `[MODIFY]` [`backend/api/app/agent/react.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/agent/react.py)
* **作用**：上下文黑板装配与多轮迭代状态演进。
* **主要内容**：
  - 升级 `_plan_stage_input`：实现 `_format_task_state_input`，将终局目标、验证假设、已确立事实、已排除方向、关键信息缺口、交付门禁格式化置顶，保留【当前规划】标识兼容已有单测。
  - 在 `react_agent_node` 入口处检测新到达的 `observations`，调用 `evolve_task_state` 演进状态黑板。
  - 在原生工具调用、最终自然语言完成、以及传统 ReAct 分支中，持续传递并返回最新的 `task_state`。

#### 8. `[MODIFY]` [`backend/api/app/agent/reflect.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/app/agent/reflect.py)
* **作用**：反射收尾物理拦截门禁（硬收敛防线）。
* **主要内容**：
  - 检查当前 `task_state`：若为对话交付型任务，且已执行过真实工具排查，但 `not task_state.can_deliver` 且存在未闭环的 `missing_info`：
  - 在不超过最大修复次数（`MAX_REPAIRS`）前提下，直接将 `verdict` 置为 `"repair"`，物理驳回模型提前交付，向观察队列注入明确警示：“任务关键信息尚未闭环（尚缺：...），当前禁止提前交付最终结论！请继续调用工具探查”，强行驱使模型回到执行器补齐缺口。

#### 9. `[MODIFY]` [`backend/api/tests/test_harness_contracts.py`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/backend/api/tests/test_harness_contracts.py)
* **作用**：单元测试套件覆盖。
* **主要内容**：
  - `test_task_session_state_serialization_roundtrip`：双向无损序列化测试。
  - `test_task_session_state_missing_info_forces_can_deliver_false`：缺口不变式防线测试。
  - `test_evolve_task_state_advances_steps_and_records_evidence`：工具成功推进与证据记录测试。
  - `test_evolve_task_state_records_failures_and_rejects_hypothesis`：工具失败记录与假设证伪测试。

---

### 2.2 前端文件 (Frontend)

#### 10. `[MODIFY]` [`frontend/src/api/types.ts`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/frontend/src/api/types.ts)
* **作用**：前端 TypeScript 契约声明。
* **主要内容**：
  - 声明 `TaskSessionState` 强类型接口，包含 `goal`、`phase`、`completed_steps`、`current_step`、`next_actions`、`failed_steps`、`confirmed_facts`、`evidence`、`rejected_hypotheses`、`missing_info`、`can_deliver` 等字段。

#### 11. `[NEW]` [`frontend/src/components/agent/TaskStateDrawer.vue`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/frontend/src/components/agent/TaskStateDrawer.vue)
* **作用**：在对话输入框上方吸附的抽屉式任务看板卡片。
* **主要内容**：
  - **位置设计**：紧贴在输入框组件（`composer-card`）上方，作为可展开/折叠的抽屉面板。
  - **折叠态（紧凑条）**：仅占 36px 空间，左侧呼吸灯指示阶段，显示任务目标、进度条（如 `2/4`），以及正在推进的当前步骤缩略；右侧提供展开按钮。
  - **展开态（任务清单）**：
    - 严格按照用户指定的格式展示：**`task 1 ：XXXXX`**、**`task 2 ：XXXXX`**、**`task 3 ：XXXXX`**。
    - 每一步配齐专属动态图标：
      - `completed`（已完成）：高保真绿色圆圈对勾图标；
      - `running`（执行中）：蓝色旋转 Spinner 动效；
      - `pending`（待执行）：灰色时钟图标；
      - `failed`（执行失败）：红色圆圈告警图标并显示失败简因。
  - **辅助徽章**：底部动态展示 `📌 已沉淀证据 N 项`、`❌ 已排除方向 N 项`、`⏳ 待探查缺口 N 项`。

#### 12. `[MODIFY]` [`frontend/src/views/Agent.vue`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/frontend/src/views/Agent.vue)
* **作用**：在主对话视图中挂载并连接抽屉看板。
* **主要内容**：
  - 导入并在 `composer-card` 上方声明 `<TaskStateDrawer :plan="latestPlan" :is-generating="isGenerating" />`。
  - 新增 `latestPlan` 响应式计算属性，从当前会话事件流中精准提取最新的有效规划与任务状态机数据。

---

## 3. 技术设计方案文档

#### 13. `[NEW]` [`docs/AI测试与评估平台-SessionState结构化任务状态机升级方案.md`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/docs/AI测试与评估平台-SessionState结构化任务状态机升级方案.md)
* **作用**：本次重构的顶层技术规范、架构拓扑与修改清单归档（已更新至 V1.1 已实施状态）。

#### 14. `[NEW]` [`docs/AI测试与评估平台-Agent内容块交错流式调用规划.md`](file:///c:/Users/Administrator/Desktop/ai-eval-platform/docs/AI测试与评估平台-Agent内容块交错流式调用规划.md)
* **作用**：全面调研与梳理 LLM 流式交错内容块机制及平台平滑演进路径的技术调研报告。

---

## 4. 验证通过情况与生产状态

| 门禁类型 | 验证命令 | 结果 |
| :--- | :--- | :--- |
| **后端单元测试** | `pytest tests/test_harness_contracts.py` 等 | **92 passed, 0 failed**（包含新增 4 组契约单测与全套阶段 4 回归单测） |
| **后端代码规范** | `ruff check . ../shared` | **All checks passed!（0 错误，0 警告）** |
| **前端类型检查** | `npm run typecheck` | **0 错误（`vue-tsc --noEmit` 完全通过）** |
| **前端生产构建** | `npm run build` | **`vite build` 成功通过（耗时 53.74s）** |
| **Git 合并与分支**| PR #137 | **已成功通过 PR 合并至主干 `main` (`fb4f934`)，清理临时分支** |

---

## 5. V1.1 运行逻辑修复（2026-08-29）

本次代码审查发现：累计 Observation 会重复推进步骤、直接构造状态可绕过交付不变式、未闭环任务会先发送最终正文、工具失败会错误证伪业务假设。已完成以下局部修复，**未新增 REST/WS 对外字段**：

| 文件 | 修改作用 |
| :--- | :--- |
| `backend/api/app/harness/contracts/task_state.py` | 在 `TaskSessionState.__post_init__` 固化 `missing_info` 与 `can_deliver` 不变式；仅工具名与当前步骤明确匹配时推进；工具失败只记录执行失败，不再自动证伪假设。 |
| `backend/api/app/harness/memory/state.py` | 为 GraphState 增加已消费 Observation 计数，配合 append reducer 防止旧观察重复回放。 |
| `backend/api/app/agent/plan_solve.py`、`backend/api/app/agent/react.py` | 新建或重规划时初始化消费计数；ReAct 仅消费新增观察；chat 规划的最终正文及其流式正文增量均先暂存，等待 Reflect 放行。 |
| `backend/api/app/agent/reflect.py` | 缺口未闭环时不发送暂存正文；超过修复次数后以受控错误结束，避免伪交付；通过复核后才发送最终正文。 |
| `backend/api/tests/test_harness_contracts.py`、`backend/api/tests/test_plan_budget_task_state.py`、`backend/api/tests/test_harness_phase4.py` | 覆盖构造不变式、未匹配工具、累计观察、未闭环正文拦截与放行后发送。 |

本次定向验证：`pytest tests/test_agent_react.py tests/test_harness_contracts.py tests/test_plan_budget_task_state.py tests/test_harness_phase4.py` 为 **105 passed**；`ruff check` 与 `npm run typecheck` 通过。
