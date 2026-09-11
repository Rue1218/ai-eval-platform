# AI 测试与评估平台 — SessionState 结构化任务状态机升级方案

> 📦 **历史归档（2026-09-11）**：本文为历史设计稿 / 规划，其中提及的 `agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除或演进，仅作决策留痕；请勿按本文直接立项。

| 项 | 内容 |
| --- | --- |
| 文档版本 | V1.2 |
| 状态 | 已实施完成并验收通过 |
| 审查日期 | 2026-08-29 |
| 适用范围 | `backend/api/app/harness/`、`app/agent/`、`frontend/src/views/Agent.vue`、`frontend/src/components/agent/TaskStateDrawer.vue` |
| 上游权威 | `AI测试与评估平台-PRD.md`、`AI测试与评估平台-API.md`、`AGENTS.md`、`AI测试与评估平台-Harness-记忆层.md` |

> **核心宗旨**：将 Agent 的多步任务认知体系从「非结构化聊天记录/静态待办清单」全面升级为**「动态结构化任务状态机（Task State Blackboard）」**。彻底解决复杂多步任务中 Agent **“做到一半提前总结”、“反复踩同一个失败坑”、“关键信息缺失仍强行交付”** 的结构性顽疾。

---

## 1. 背景与核心问题诊断

### 1.1 现状与痛点：聊天记录不是状态
当前平台在 M4 阶段引入了 `PlanArtifact` 与 `Observation`，初步具备了“先规划后执行”的能力。然而在多步长任务（如技术债分析、根因故障排查、复杂用例拆解）中，Agent 仍面临以下认知脆弱性：

1. **“做到一半开始总结”（提前收工/伪收敛）**：
   大模型受指令微调和自回归目标影响，本能地偏向于扮演“友好助手的总结者”。当一次工具（如 `read` 或 `bash`）返回了大段输出后，模型极易在未经全面核实的情况下，顺手把中间观察提炼为助手正文，导致后续关键分析步骤被腰斩。
2. **“在已被证伪的方向上反复转圈”（遗忘负向经验）**：
   当某个假设被排除或某个工具参数报错时，该报错信息随着时间线推移沉入对话历史深处。在注意力稀释（Attention Dilution / Lost in the Middle）的作用下，模型在第 5、6 轮往往会再次提出已被排除的假设或重试同类错误命令。
3. **“无显式交付标准（Done Definition）”**：
   系统目前依赖 `reflect.py` 里的有限规则判定，模型自身意识不到“到底还缺什么证据才能交差”，缺乏对信息缺口（Missing Info）的持续追踪。

### 1.2 升级理念：认知黑板模型（Blackboard Architecture）
**Session State 不是聊天历史，而是任务进行状态的真理单一本（Ground Truth）。**

```text
传统 Chatbot 流（易漂移）：
[用户目标] ──► [轮次1对话] ──► [工具返回大段文本] ──► [轮次2对话(注意力被大文本带偏)] ──► [提前草率总结]

结构化 State-Driven 流（强锚定）：
┌──────────────────────────────────────────────────────────────────────────┐
│                   结构化任务状态机 (Session Task State)                     │
├──────────────────────────────────────────────────────────────────────────┤
│ 🎯 终局目标 (Goal)              : 定位支付变慢根因                        │
│ 💡 当前活跃假设 (Hypothesis)    : 第三方支付回调超时                      │
│ 🔍 已确立事实与证据 (Evidence)   : 22:10 后 P95 升至 3.8s；22:05 发布 v2.3.1│
│ ❌ 已排除方向 (Rejected)        : 数据库慢查询（排查日志均<50ms）         │
│ ⏳ 关键信息缺口 (Missing Info)   : 缺少第三方回调错误码分布 ◄─【严禁交付】 │
│ 📋 下一步精准动作 (Next Actions) : 查询第三方回调错误码分布                │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据结构与契约设计

### 2.1 `TaskSessionState` 规范定义
在 `backend/api/app/harness/contracts/task_state.py` 中新增核心不可变数据类（兼容并逐步扩展 `PlanArtifact`）：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

TaskPhase = Literal["exploring", "verifying", "converging", "completed", "blocked"]

@dataclass(frozen=True, slots=True)
class RejectedHypothesis:
    """已证伪的假设与排查记录（防止反复踩坑）。"""
    hypothesis: str
    reason: str
    evidence_ref: str = ""

@dataclass(frozen=True, slots=True)
class FailedStep:
    """失败步骤与原因。"""
    step: str
    reason: str
    repair_hint: str = ""

@dataclass(frozen=True, slots=True)
class TaskSessionState:
    """结构化任务状态机契约（全字段 JSON 可序列化）。"""
    protocol: Literal["task_state"] = "task_state"
    version: Literal["v1"] = "v1"
    
    # 1. 终局目标（抗漂移锚点）
    goal: str = ""
    phase: TaskPhase = "exploring"
    
    # 2. 步骤推进链
    completed_steps: tuple[str, ...] = field(default_factory=tuple)
    current_step: str = ""
    next_actions: tuple[str, ...] = field(default_factory=tuple)
    failed_steps: tuple[FailedStep, ...] = field(default_factory=tuple)
    
    # 3. 认知与事实库
    current_hypothesis: str = ""
    confirmed_facts: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)
    rejected_hypotheses: tuple[RejectedHypothesis, ...] = field(default_factory=tuple)
    
    # 4. 闭环门禁（最关键的防假收尾字段）
    missing_info: tuple[str, ...] = field(default_factory=tuple)
    can_deliver: bool = False
    
    # 5. 补充元数据
    blocked_reason: str = ""
    notes: str = ""
```

### 2.2 GraphState 状态容器扩展
在 `backend/api/app/harness/memory/state.py` 中为 `GraphState` 增加状态机槽位：

```python
class GraphState(TypedDict, total=False):
    # 保持原有字段...
    plan: object | None                # 保持向后兼容现有 PlanArtifact
    task_state: Mapping[str, object]   # 新增：TaskSessionState 序列化投影
    # ...
```

---

## 3. 运行时流转与闭环机制

升级后的 Agent 单轮循环由原本的“纯工具执行”升级为**“状态演进 ➔ 上下文置顶 ➔ 门禁复核”**三位一体流转：

```text
               ┌───────────────────────────────┐
               │    Planner / 路由初态生成     │
               │   (生成初始 TaskSessionState)  │
               └───────────────┬───────────────┘
                               │
                               ▼
               ┌───────────────────────────────┐
               │         react_agent           │ ◄─────────────────────────┐
               │   (置顶注入 TaskSessionState) │                           │
               └───────────────┬───────────────┘                           │
                               │ 决定调用工具 (ToolCall)                   │
                               ▼                                           │
               ┌───────────────────────────────┐                           │
               │           ToolNode            │                           │
               │       (执行工具 ➔ 产出 Obs)    │                           │
               └───────────────┬───────────────┘                           │
                               │                                           │
                               ▼                                           │
               ┌───────────────────────────────┐                           │
               │      TaskState Synchronizer   │                           │
               │   (根据工具产出更新状态黑板):  │                           │
               │   - 补充已确立事实与证据      │                           │
               │   - 记录已排除方向与失败步骤  │                           │
               │   - 从 missing_info 剔除已解项│                           │
               │   - 重算 can_deliver          │                           │
               └───────────────┬───────────────┘                           │
                               │                                           │
                               ▼                                           │
                     [can_deliver == True?]                                │
                     /                   \                                 │
          (是: 无 missing_info)        (否: 仍有 missing_info)             │
                   /                       \                               │
                  ▼                         ▼                              │
        ┌──────────────────┐      ┌──────────────────┐                     │
        │ 流式生成交付正文 │      │ reflect 反射门禁 │ ──[继续调工具探查]──┘
        │ (允许收尾完成)   │      │ (硬性阻止伪完成) │
        └──────────────────┘      └──────────────────┘
```

### 3.1 提示词置顶装配（CX-4 扩展）
在 `react.py` 的 `assemble` 阶段，格式化注入【当前任务状态黑板】：

```text
【当前结构化任务看板 (Session State)】
🎯 终局目标：定位支付接口变慢原因
🚦 当前阶段：verifying（验证中）
💡 当前假设：第三方支付回调超时可能导致接口变慢
🔍 已确立事实 (2项)：
  - 22:10 后 /api/pay P95 从 300ms 升到 3.8s
  - 22:05 发布了 payment-service v2.3.1
❌ 已排除方向 (1项)：
  - 数据库慢查询导致变慢（慢查询日志耗时<50ms）
⏳ 关键信息缺口 (Missing Info，严禁收尾！)：
  1. 缺少第三方支付错误码分布
  2. 尚未核对 v2.3.1 是否包含回调重试变更
📋 下一步动作：检查 v2.3.1 是否改动回调重试逻辑

【行为红线警告】：
当前 can_deliver=False，信息缺口未清空！
严禁直接输出最终总结正文！必须使用工具探查上述缺失项。
```

### 3.2 Reflect 反射门禁的硬约束
在 `reflect.py` 中增加针对 `missing_info` 的物理拦截：

```python
# 伪完成拦截门禁：
if not state_data.get("can_deliver") and state_data.get("missing_info"):
    # 模型试图调用 done=true 或输出无工具正文，但缺口未消除
    missing_str = "、".join(state_data["missing_info"][:3])
    repair_text = (
        f"【反射门禁驳回】：任务关键信息尚未闭环（缺少：{missing_str}），"
        "禁止提前总结收尾！请针对未解决的信息缺口继续调用工具排查。"
    )
    return {
        "verdict": "repair",
        "observations": [Observation(tool="__reflect__", text=repair_text, ok=False)]
    }
```

---

## 4. WebSocket 事件与前端可视化

### 4.1 新增 WS 事件契约：`task_state`
对齐 `API.md`，新增推送帧：
* `event`: `"task_state"`
* `payload`: 符合 `TaskSessionState` 的完整 JSON 结构。

### 4.2 前端可视化看板：`TaskStateDashboard.vue`
将现有的简单 `PlanCard.vue` 升级为一个富有视觉表现力的任务进展中枢：

1. **目标与阶段徽章**：顶部显示目标和当前处于探索、验证还是交付阶段；
2. **已排除方向（红条划线）**：让用户直观看到 Agent 已经排除了哪些假方向，极大提升技术可信度；
3. **事实与证据库（绿条确认）**：沉淀出来的客观数据；
4. **待消除的信息缺口（橙色呼吸灯）**：当 Agent 消除一个缺口时，展示动态划掉动效；
5. **行动步骤列表**：显示当前正在做哪一步。

---

## 5. 分期实施路线图

```text
Milestone 1: 契约与模型定义 (P1)
  ├── 新增 contracts/task_state.py (TaskSessionState)
  ├── GraphState 扩展字段与序列化支持
  └── 单元测试覆盖 schema 校验与序列化

Milestone 2: 编排与状态流转驱动 (P2)
  ├── plan_solve.py 增加初始 task_state 生成
  ├── react.py 增加任务看板系统提示词置顶注入
  └── reflect.py 接入 missing_info 硬收敛门禁

Milestone 3: WS 协议下发与前端看板 (P3)
  ├── ws.py 增加 task_state 事件持久化与广播
  ├── 前端升级 TaskStateDashboard.vue 组件
  └── blocks 列表支持 task_state 动态原地更新

Milestone 4: 端到端测试与质量验证 (P4)
  ├── 多步排查场景回归测试（验证防提前总结）
  ├── 排除方向记忆测试（验证防二次踩坑）
  └── 前后端端到端验证与构建门禁自检
```

---

## 6. 修改代码文件与作用清单

| 模块 | 文件路径 | 状态与作用说明 |
| :--- | :--- | :--- |
| **契约层** | `backend/api/app/harness/contracts/task_state.py` | `[NEW]` 实现 `TaskSessionState`、`FailedStep`、`RejectedHypothesis` 不可变数据类、`evolve_task_state` 演进函数与 `from_dict`/`to_dict` 序列化，嵌入 `missing_info` 强制 `can_deliver=False` 防线 |
| **契约层** | `backend/api/app/harness/contracts/__init__.py` | `[MODIFY]` 导出 `TaskSessionState`、`FailedStep`、`RejectedHypothesis` 与 `evolve_task_state` 契约符号 |
| **记忆层** | `backend/api/app/harness/memory/state.py` | `[MODIFY]` 在 `GraphState` TypedDict 容器中新增 `task_state: Mapping[str, object] \| None` 纯数据投影字段 |
| **编排层** | `backend/api/app/harness/orchestration/plan.py` | `[MODIFY]` 实现 `task_state_from_plan` 转换函数，从 PlanArtifact 意图与步骤自动结构化派生初始任务状态黑板 |
| **编排层** | `backend/api/app/harness/orchestration/__init__.py` | `[MODIFY]` 导出 `task_state_from_plan` 编排函数 |
| **执行层** | `backend/api/app/agent/plan_solve.py` | `[MODIFY]` 在 `plan_solve_node` 中初始化 `task_state` 并同步嵌入 `plan.slots.task_state`，支持旧 WS 协议无缝透明下发 |
| **执行层** | `backend/api/app/agent/react.py` | `[MODIFY]` 升级 `_plan_stage_input` 置顶注入任务黑板提示词（目标/假设/事实/排除方向/信息缺口/收尾门禁）；在多轮工具迭代中调用 `evolve_task_state` 动态演进 |
| **反射层** | `backend/api/app/agent/reflect.py` | `[MODIFY]` 在 `reflect_node` 中增加针对 `missing_info` 与 `can_deliver` 的物理拦截门禁，驳回未完成交付并打回 `repair` 阶梯 |
| **测试集** | `backend/api/tests/test_harness_contracts.py` | `[MODIFY]` 新增 4 组针对 `TaskSessionState` 序列化双向无损、缺口不变式、工具成功演进与失败证伪的完整自动化测试（全套 15 个契约单测通过） |
| **前端契约**| `frontend/src/api/types.ts` | `[MODIFY]` 声明前端 TypeScript `TaskSessionState` 强类型接口 |
| **前端组件**| `frontend/src/components/agent/TaskStateDrawer.vue` | `[NEW]` 对话输入框上方吸附的抽屉式任务看板卡片，动态渲染 `task 1 ：XXXXX` 格式任务清单与完成/执行/失败/待办动态图标 |
| **前端主视图**| `frontend/src/views/Agent.vue` | `[MODIFY]` 挂载 `TaskStateDrawer`，通过 `latestPlan` 响应式计算属性实时向抽屉组件输送最新状态机数据 |
| **技术规划**| `docs/AI测试与评估平台-Agent内容块交错流式调用规划.md` | `[NEW]` 深度调研与梳理 LLM 流式交错内容块机制及平台平滑演进路径 |
| **技术设计**| `docs/AI测试与评估平台-SessionState结构化任务状态机升级方案.md` | `[NEW]` SessionState 结构化任务状态机权威技术升级方案与闭环记录 |

---

## 7. V1.2 完整性修复与修改代码文件清单（2026-08-29）

### 7.1 运行时约束

1. `missing_info` 非空时，`TaskSessionState` 无论经由反序列化还是直接构造，`can_deliver` 都必须为 `false`。
2. `observations` 是 append reducer 的累计历史；Task State 只消费消费计数之后新增的观察。重规划会把计数重置为当前历史长度，避免旧计划结果推进新计划。
3. 工具成功仅在当前步骤文本明确包含该工具短名时推进步骤；其他成功结果只沉淀为事实与证据。工具执行失败不能自动作为业务假设已证伪的依据。
4. `delivery=chat` 的最终正文及其 `assistant_delta` 先存入 GraphState `response`，只有 Reflect 判定 `pass` 后才生成 `assistant_message`。缺口未闭环且修复额度耗尽时发送统一 `VALIDATION` 错误并结束，不得降级为最终结论。

### 7.2 修改文件与作用

| 模块 | 文件路径 | 作用 |
| :--- | :--- | :--- |
| 契约层 | `backend/api/app/harness/contracts/task_state.py` | 固化交付不变式；按显式工具名推进；分离执行失败与假设证伪。 |
| 记忆层 | `backend/api/app/harness/memory/state.py` | 增加 `task_state_observation_count` 检查点字段。 |
| 编排/执行 | `backend/api/app/agent/plan_solve.py`、`backend/api/app/agent/react.py` | 初始化并传递观察消费计数；暂存 chat 最终正文直至反射放行。 |
| 反射层 | `backend/api/app/agent/reflect.py` | 放行后发送暂存正文；未闭环任务受控拦截和终止。 |
| 测试 | `backend/api/tests/test_harness_contracts.py`、`backend/api/tests/test_plan_budget_task_state.py`、`backend/api/tests/test_harness_phase4.py` | 新增状态机和最终正文门禁的回归覆盖。 |

验证命令：`pytest tests/test_agent_react.py tests/test_harness_contracts.py tests/test_plan_budget_task_state.py tests/test_harness_phase4.py`（105 passed）、`ruff check . ../shared`、`npm run typecheck`。
