# AI 测试与评估平台 — Harness 技能体系模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 技能体系模块设计 |
| 版本 | V0.3 |
| 审查日期 | 2026-08-23 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M10 技能体系（MoE + Progressive Disclosure，§5） |
| 上游权威 | Harness 需求文档 V1.4.4 §5、§2.2、§4.4、§7、§9；API.md V1.4+ §4.3；PRD §5.1.2 |

> **阅读关系**：本文是 Harness §5「技能体系需求」与 §9.2「技能体系」行的展开。`SkillHint` 契约在 M7 `contracts/artifacts.py`；技能路由节点在 M4 `orchestration/router.py`；本模块定义技能目录与按需装配策略。当前全部冻结未实现，属 M2/M3 演进项。

---

## 1. 模块定位与边界

### 1.1 定位

技能体系按评测域组织专家能力，采用 **Mixture of Experts（MoE）** + **Progressive Disclosure**：每个 skill 对外只暴露名称 + 一句话描述（Skill Hint），完整工作流按需加载；skill 路由节点按 `intent/skill_id` 选择 Skill Hint 注入上下文。本模块定义 4 个评测域 skill（`skill-benchmark`/`skill-rag`/`skill-testcase`/`skill-stress`）的目录、`skill_id ↔ 任务 kind` 映射、按需装配策略。

当前全部冻结未实现（`app/harness/` 无独立技能包，§9.2 标注"无包"）；`SkillHint` 类型由 M7 提供，技能路由由 M4 承载，本模块是技能**目录与装配策略**的定义。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 4 个评测域 skill 目录与一句话描述 | `SkillHint` 类型定义（M7 `contracts/artifacts.py`） |
| `skill_id ↔ 任务 kind` 映射 | 技能路由节点（M4 `orchestration/router.py`） |
| Progressive Disclosure 按需装配策略 | 上下文装配实现（M2 `context/assembly.py`） |
| skill 未实现时返回 `VALIDATION`（SK-4） | 工具执行（M5） |
| 六专家分工（如需）作为需求变更提交评审 | 当前不落地六专家（planner/generator/executor/healer/reporter/scenario） |

### 1.3 红线（继承 Harness §5 + §7）

- 每个 skill 对外只暴露**名称 + 一句话描述**（Skill Hint），完整工作流按需加载（SK-1）。
- skill 只在当前回合按需注入，**不把历史技能卡逐一重复注入**（SK-2）。
- skill 映射评测域职责：benchmark/testcase/rag/stress（SK-3）。
- 未实现 skill（如 rag）返回 `VALIDATION`，**不得伪装成功**（SK-4，对齐 MEM-5）。
- 前端自定义斜杠只请求 `/api/slash-commands`，与后端技能注册一致（SK-5）。
- 六专家分工如需落地为独立 skill，须作为**需求变更提交评审**（Harness §5 现状）。
- `rag` 未接入不得 mock `succeeded`（§7 红线）。

---

## 2. 需求发散

### 2.1 从 Harness §5 提取的需求

| 编号 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| SK-1 | 每个 skill 对外只暴露名称 + 一句话描述，完整工作流按需加载 | K-1：定义 4 个 `SkillHint`（skill_id/name/summary） | M2/M3 |
| SK-2 | skill 只在当前回合按需注入，不重复注入历史技能卡 | K-2：M4 路由按 `intent/skill_id` 选 Hint，相邻回合互不污染 | M2/M3 |
| SK-3 | skill 映射评测域职责 | K-3：`skill_id ↔ kind` 映射表 | M2/M3 |
| SK-4 | 未实现 skill 返回 `VALIDATION`，不得伪装成功 | K-4：`rag` 未接入时路由节点抛 `VALIDATION` | M2/M3 |
| SK-5 | 前端自定义斜杠只请求 `/api/slash-commands`，前后端一致 | K-5：后端技能注册与 `/api/slash-commands` 对齐 | M2/M3 |

### 2.2 评测域 skill 目录发散

| skill_id | 名称 | 一句话描述 | 对应 kind | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| `skill-benchmark` | 基准评测 | 执行基准评测任务（三协议调用、规则评分、预算熔断、断点续跑） | benchmark | 冻结 |
| `skill-testcase` | 用例生成 | 六策略 LLM 生成用例、72h 确认超时扫描 | testcase | 冻结 |
| `skill-rag` | 知识库评测 | LightRAG 混合检索与图谱评测（未接入必失败） | rag | 冻结（演进） |
| `skill-stress` | 压测 | go-stress-testing 发压，质量任务 succeeded 后派生 | stress | 冻结 |

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| K-A1 | 4 个 SkillHint 常驻，正文不常驻 | 目录断言 |
| K-A2 | 相邻回合 skill 注入互不污染 | 注入断言 |
| K-A3 | `skill_id ↔ kind` 映射 1:1 | 映射断言 |
| K-A4 | `skill-rag` 未接入时路由抛 `VALIDATION` | 未实现断言 |
| K-A5 | 后端技能清单与 `/api/slash-commands` 一致 | 一致性断言 |

---

## 3. 架构设计

### 3.1 技能体系结构（MoE + Progressive Disclosure）

```text
SkillHint（常驻，M7 契约）
  ├── skill-benchmark: 基准评测 — ...
  ├── skill-testcase:  用例生成 — ...
  ├── skill-rag:       知识库评测 — ...（未接入）
  └── skill-stress:    压测 — ...

M4 路由节点（按 intent/skill_id 选 Hint）
  → 注入当前回合上下文（M2 assembly.py 装配 Skill Hint 段）
  → 完整工作流按需加载（Progressive Disclosure：图状态只携带 Hint 索引）
```

- **Skill Hint 常驻**：4 个 `SkillHint`（名称 + 一句话描述）始终可见，供路由节点选择。
- **正文不常驻**：完整工作流（评测执行细节）按需加载，图状态只携带 `skill_id` 索引，不携带完整技能文档（Progressive Disclosure，Harness §2.2）。

### 3.2 `skill_id ↔ 任务 kind` 映射（SK-3）

| skill_id | kind | 说明 |
| :--- | :--- | :--- |
| `skill-benchmark` | `benchmark` | 评测执行 |
| `skill-testcase` | `testcase` | 用例生成 |
| `skill-rag` | `rag` | 知识库评测（未接入必失败） |
| `skill-stress` | `stress` | 压测（由质量任务 succeeded 派生，对话路径不得发 `kind=stress` 确认卡） |

> `stress` 一般不手选，由系统在质量任务 `succeeded` 且 `with_stress=true` 时创建（PRD §5.1.2）。

### 3.3 Progressive Disclosure 装配（SK-1/SK-2）

- **按需注入**：M4 路由节点按当前回合 `intent/skill_id` 选 1 个 `SkillHint`，交 M2 `assembly.py` 装入上下文 Skill Hint 段。
- **不重复注入**：相邻回合 skill 注入互不污染——每回合只注入当前选中的 1 个 Hint，历史技能卡不逐一重复注入（SK-2）。
- **图状态只携带索引**：GraphState 只存 `plan.skill_id`（M3），不存完整技能文档；完整工作流由节点按需装配（Harness §2.2）。

### 3.4 MoE 路由（SK-4）

- M4 `orchestration/router.py` 的 `decide_mode` 在阶段 4 扩展：`has_multi_slots` 时进入 `plan_solve`，`plan.py` 产出 `PlanArtifact.skill_id`。
- 路由节点按 `skill_id` 选 `SkillHint` 注入；**未实现 skill（`skill-rag`）抛 `VALIDATION`**，不得伪装成功（SK-4）。
- 与 M5 `worker_bridge` 协作：`skill_to_kind` 返回 **Task.kind 短名**（`benchmark`/`testcase`/`rag`/`stress`），直接喂给 `enqueue_long_task(kind=...)`；M5 `LONG_TOOLS`（工具名带动作后缀）由 M4 `gates.py` 用于长工具门禁，与 Task.kind 短名分离。

### 3.5 接口签名规格（签名级）

> M10 无独立包（§9.2）；`SkillHint` 类型在 M7，技能目录以数据形式注册供 M4 路由消费。本节定义目录数据与映射函数签名。

```python
# M2/M3 阶段：本地 dataclass 占位（M7 SkillHint 尚未生成）；
# M7 阶段 4 正式接管后改为：from app.harness.contracts import SkillHint
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SkillHint:  # 占位，M7 阶段 4 接管后删除本定义
    skill_id: str
    name: str
    summary: str

# 4 个评测域 SkillHint（常驻目录）
SKILL_CATALOG: tuple[SkillHint, ...] = (
    SkillHint(skill_id="skill-benchmark", name="基准评测",
              summary="执行基准评测任务（三协议调用、规则评分、预算熔断、断点续跑）"),
    SkillHint(skill_id="skill-testcase", name="用例生成",
              summary="六策略 LLM 生成用例、72h 确认超时扫描"),
    SkillHint(skill_id="skill-rag", name="知识库评测",
              summary="LightRAG 混合检索与图谱评测（未接入）"),
    SkillHint(skill_id="skill-stress", name="压测",
              summary="go-stress-testing 发压，质量任务 succeeded 后派生"),
)

# skill_id ↔ 任务 kind 映射
SKILL_KIND_MAP: dict[str, str] = {
    "skill-benchmark": "benchmark",
    "skill-testcase": "testcase",
    "skill-rag": "rag",
    "skill-stress": "stress",
}

# 未接入 skill 集合（路由时抛 VALIDATION）
DISABLED_SKILLS: frozenset[str] = frozenset({"skill-rag"})

def get_hint(skill_id: str) -> SkillHint:
    """取 SkillHint；未注册抛 AppError(VALIDATION)。"""

def skill_to_kind(skill_id: str) -> str:
    """skill_id → kind 映射；未映射抛 AppError(VALIDATION)。"""

def assert_skill_enabled(skill_id: str) -> None:
    """未接入 skill（DISABLED_SKILLS）抛 AppError(VALIDATION, "技能未启用")。
    禁止 mock succeeded（SK-4 / MEM-5）。"""

def list_hints() -> list[SkillHint]:
    """返回全部 SkillHint，供 M4 路由注入与 /api/slash-commands 对齐（SK-5）。
    `/api/slash-commands` 路由同源引用 `SKILL_CATALOG`（非同步副本），保证前后端一致。"""

# 注：M2/M3 落地时 M7 `SkillHint` 尚未生成（阶段 4），以临时 dataclass 占位；
# M7 阶段 4 正式接管 `SkillHint` 定义后，本模块改 `from app.harness.contracts import SkillHint`。
```

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_skills.py`（M2/M3 阶段补）

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_skill_catalog_has_four_hints` | K-A1 |
| `test_skill_hints_only_name_and_summary_no_full_doc` | K-A1 |
| `test_adjacent_turns_skill_injection_no_pollution` | K-A2 |
| `test_skill_kind_map_one_to_one` | K-A3 |
| `test_skill_rag_disabled_raises_validation` | K-A4 |
| `test_skill_list_matches_slash_commands` | K-A5 |

**TDD 顺序**：M2/M3 启动时先写 `test_harness_skills.py` 全红 → 实现目录数据与映射函数 → 全绿。本模块无 DB/WS 依赖，单测独立。`test_skill_list_matches_slash_commands` 需对齐 `/api/slash-commands` 后端实现。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/skills.py`（或 M4 `router.py` 内注册） | M2/M3 | 新增（待定位置，见 §7） | SK-1/SK-3、K-1/K-3 |
| `app/harness/contracts/artifacts.py` | 阶段 4（M7） | 已含 `SkillHint` | SK-1 |
| `app/harness/orchestration/router.py` | 阶段 4（M4） | 修改（按 skill_id 路由） | SK-2/SK-4 |
| `backend/api/tests/test_harness_skills.py` | M2/M3 | 新增 | K-A1~K-A5 |

> M10 无独立包（§9.2）；技能目录数据位置待定（§7-D1）。

---

## 6. 依赖与红线

- **上游依赖**：Harness §5（SK-1~5）、§2.2（Progressive Disclosure）、§4.4（OR-1 路由）、§7；API.md §4.3；PRD §5.1.2。
- **下游被依赖**：M4（`get_hint`/`assert_skill_enabled` 供路由节点）、M2（`list_hints` 供 Skill Hint 段装配）、M5（`skill_to_kind` 供 `worker_bridge` 入队）、`/api/slash-commands`（前后端一致）。
- **跨层协作**：M7（`SkillHint` 契约）、M3（`plan.skill_id` 字段）、M5（`LONG_TOOLS` 入队）。
- **红线**：
  - Skill Hint 常驻，正文不常驻；
  - 相邻回合不重复注入；
  - skill_id ↔ kind 1:1；
  - 未实现 skill 返回 `VALIDATION`，禁 mock；
  - 前后端技能清单一致；
  - 六专家分工须需求变更评审；
  - `rag` 未接入禁 mock succeeded。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M10-D1 | 技能目录数据位置 | **待定**：候选 `app/harness/skills.py`（新模块）或 M4 `router.py` 内注册；倾向独立 `skills.py`（便于 `/api/slash-commands` 对齐），M2/M3 启动时定 |
| M10-D2 | Skill Hint 常驻范围 | 4 个评测域 Hint 常驻，正文按需加载 |
| M10-D3 | 未接入 skill 行为 | `DISABLED_SKILLS`（当前含 `skill-rag`）抛 `VALIDATION`，禁 mock |
| M10-D4 | `stress` skill 特殊性 | 不手选，由质量任务 `succeeded` + `with_stress=true` 派生；对话路径不得发 `kind=stress` 确认卡 |
| M10-D5 | 六专家分工 | 当前不落地；如需独立 skill 须需求变更评审（Harness §5 现状） |
| M10-D6 | 前后端一致性 | 后端 `list_hints` 与 `/api/slash-commands` 对齐（SK-5） |

> **M10-D1 是本模块唯一遗留待定项**：技能目录数据位置（独立 `skills.py` vs M4 内注册）需 M2/M3 启动时定。

---

## 8. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-技能体系.md` | 新增 V0.3 | M10 技能体系模块设计：定义 4 个评测域 SkillHint 目录（benchmark/testcase/rag/stress）、`skill_id ↔ kind` 映射、Progressive Disclosure 按需装配、MoE 路由、未接入 skill 返回 `VALIDATION`；含接口签名级（`SKILL_CATALOG`/`SKILL_KIND_MAP`/`DISABLED_SKILLS`/`get_hint`/`skill_to_kind`/`assert_skill_enabled`/`list_hints`）与 TDD 验收；标注无独立包，目录数据位置待定。 |

本文档仅设计技能体系，不改变任何 API、数据库、前端或 Agent 运行代码。



