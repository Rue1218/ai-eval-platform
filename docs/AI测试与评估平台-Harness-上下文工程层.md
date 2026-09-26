# AI 测试与评估平台 — Harness 上下文工程层模块设计

> **文档维护提示（2026-09-26）**：正文旧 `CompactProtocol`、最近六条及 `sessions.compact_summary` 是历史设计；当前 AgentLoop v2 自动摘要、来源回读与个人记忆计量见文末 V0.4.6–V0.4.9，以 API V2.30 为接口权威。旧 ReAct / Plan-Solve 文件已删除，不能用旧章节推断当前运行状态。

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 上下文工程层模块设计 |
| 版本 | V0.4.9 |
| 审查日期 | 2026-09-26 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M2 上下文工程层（`app/harness/context/`） |
| 上游权威 | Harness 需求文档 V1.4.4 §4.2、§2.4、§7、§9；API.md V1.22 §3.4（context_meter）；PRD §5.1.3 |

> **阅读关系**：本文是 Harness §9.2「层 2 上下文工程」行的展开。装配顺序对齐 M1 提示词工程层（Persona → Skill Hint → 摘要 → 阶段输入 → 用户消息，CX-4）；`Observation` 脱敏摘要消费 M7 契约 + M8 安全层脱敏函数；`CompactProtocol` 由 M1 移归本层（M1-Q5 裁决）。

---

## 1. 模块定位与边界

### 1.1 定位

上下文工程层决定**模型本轮可见输入**：相关性、来源、安全、容量与成本同时优化。本层提供最近消息窗口算法、observation 脱敏摘要、上下文装配、`/compact` 可控摘要、ContextMeter 投影。本层不调模型、不持 WS 连接、不产生副作用（`/compact` 摘要写入会话记录由 M3 记忆层承担，本层只产出摘要文本）。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 最近消息窗口算法（`window.py`） | 消息持久化（M3 记忆层 / `messages` 表） |
| observation 脱敏/截断/带来源摘要（`observation.py`） | 脱敏递归实现（M8 `security/secrets.py`） |
| 上下文装配顺序与按需工具注入（`assembly.py`） | 系统策略文本（M1 `system.py`） |
| `/compact` 可控摘要 + `CompactProtocol`（`compact.py`） | 摘要写入会话记录（M3） |
| ContextMeter 投影（`meter.py`） | 前端 ContextMeter 组件（前端） |
| 工具定义按本轮能力最小注入（CX-5） | 工具注册表元数据（M5 `registry.py`） |

### 1.3 红线（继承 Harness §4.2 + §7）

- 思考/工具/确认/进度事件**不进消息窗口**，只入 `ws_events` 供回放（CX-2）。
- 工具结果为脱敏、截断、带来源 observation 摘要，**不原样注入**（CX-3）。
- 上下文装配顺序固定：Persona → Skill Hint → 技能工作流（可选）→ 摘要 → 阶段输入（CX-4 / SK-1）。
- 工具定义按本轮能力最小注入，**不默认全量注入**（CX-5）。
- `/compact` 保留最近 6 条、摘要 ≤2000 字符、**不删除原始记录**（CX-6）。
- ContextMeter 只读 `GET /api/sessions/{id}/messages` 的 `context_meter`，前端不自行计算（CX-7）。
- 提示词与日志不含密钥（§5.2.1）。

---

## 2. 需求发散

### 2.1 从 Harness §4.2 提取的需求

| 编号 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| CX-1 | 最近消息窗口为唯一窗口算法（默认末尾 20 条，`compact_keep_from` 截断） | X-1：`window.py` 提供 `recent_window(messages, limit=20, keep_from=None)` | 阶段 1 |
| CX-2 | 思考/工具/确认/进度事件不进消息窗口，只入 `ws_events` | X-2：`window.py` 只取 `role in (user,assistant)` 消息，过滤事件 | 阶段 1 |
| CX-3 | 工具结果为脱敏、截断、带来源 observation 摘要 | X-3：`observation.py` 调 M8 脱敏 + 截断 + 标 `truncated`/`source` | 阶段 2 |
| CX-4 | 上下文装配顺序固定：Persona → Skill Hint → 摘要 → 阶段输入 | X-4：`assembly.py` `assemble(..., skill_workflow=)` 在 Hint 后按需插入技能工作流（SK-1） | 阶段 1 / 技能按需 |
| CX-5 | 工具定义按本轮能力最小注入，不默认全量注入 | X-5：`assembly.py` 按本轮 `mode`/`plan.tools_needed` 选工具定义 | 阶段 2 |
| CX-6 | `/compact` 为可控摘要：保留最近 6 条、摘要 ≤2000 字符、不删除原始记录 | X-6：`compact.py` `summarize(messages, keep_recent=6)` + `CompactProtocol` | 阶段 3 |
| CX-7 | ContextMeter 只读 `GET .../messages` 的 `context_meter` | X-7：`meter.py` 投影 token/窗口占比，数据源为会话 messages | 阶段 3 |

### 2.2 与他层协作发散

| 协作点 | 对端 | 本模块职责 |
| :--- | :--- | :--- |
| 装配 Persona | M1 `system.py` | 调 `build_system_prompt` 取 Persona，放装配首位 |
| Observation 脱敏 | M8 `security/secrets.py` | 调递归脱敏函数，本层只负责截断 + 来源标注 |
| 摘要写入会话 | M3 记忆层 | 本层产出摘要文本，写入 `sessions.compact_summary` 由 M3 承担 |
| 工具定义来源 | M5 `registry.py` | 按本轮 `tools_needed` 从注册表取工具定义，最小注入 |
| ContextMeter 数据 | `messages` 表 / `context_meter` 字段 | 本层只读投影，不计算 |

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| X-A1 | `recent_window` 默认取末尾 20 条，`compact_keep_from` 截断生效 | 窗口算法断言 |
| X-A2 | 窗口只含 user/assistant 消息，工具/思考事件被过滤 | 过滤断言 |
| X-A3 | observation 含 `truncated`/`source`/`redacted` 标记，密钥被脱敏 | 脱敏 + 截断断言 |
| X-A4 | 装配顺序输出为 Persona → Skill Hint → 技能工作流 → 摘要 → 阶段输入 → 消息 | 顺序断言 |
| X-A5 | 未注册工具不出现在注入清单；本轮未选工具不注入 | 最小注入断言 |
| X-A6 | `/compact` 保留最近 6 条、摘要 ≤2000 字符、原始记录保留 | 摘要断言 |
| X-A7 | ContextMeter 投影字段与 `context_meter` 一致，前端不自行计算 | 投影断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/context/
├── __init__.py        # re-export recent_window / assemble / summarize / context_meter / to_observation
├── window.py         # 阶段 1：最近消息窗口算法（CX-1/2）
├── observation.py    # 阶段 2：observation 脱敏/截断/带来源摘要（CX-3）
├── assembly.py       # 阶段 1/2：上下文装配 + 按需工具注入（CX-4/5）
├── compact.py        # 阶段 3：/compact 可控摘要 + CompactProtocol（CX-6）
└── meter.py          # 阶段 3：ContextMeter 投影（CX-7）
```

### 3.2 window.py（阶段 1 落地）

**职责**：唯一窗口算法。从 `messages` 表读取 `role in (user, assistant)` 消息，取末尾 `limit` 条（默认 20），`compact_keep_from` 指定保留起点时截断更早消息。

- **过滤规则**（CX-2）：只取 user/assistant 消息；思考（thought）、工具调用/结果、确认、进度事件**不进窗口**，只入 `ws_events`。
- **现状对齐**：当前 `ws.py:_history_messages` 已实现末尾 20 条 user/assistant 读取（`ws.py:316`），阶段 1 把该逻辑迁入 `window.py`，`ws.py` 改为调本模块。

### 3.3 observation.py（阶段 2 落地）

**职责**：消费 M6 已归一的 `Observation`，做截断/脱敏后产出可注入上下文的 observation 摘要（归一逻辑 owner 是 M6，M6-D1）。

- **入参**：M6 `observation.normalize` 产出的 `Observation`（异常已在 M6 归一，不裸抛）。
- **脱敏**：调 M8 `security/secrets.py` 递归脱敏（`api_key`/`token`/`password`/`secret`/`cookie` 键递归脱敏）；M6 归一时已标 `redacted=True`，本层确保上下文注入前最终脱敏。
- **截断**：超长文本截断，标 `truncated=true`，保留头部 + 尾部摘要。
- **来源**：`source` 复用 messages 表 `source_id` 格式（M7-Q2 裁决，如 `"file:uuid"`/`"message:uuid"`）。
- **产出**：`Observation`（M7 契约），`redacted=True` 默认。

### 3.4 assembly.py（阶段 1/2 落地）

**职责**：按固定顺序装配模型本轮输入，并按本轮能力最小注入工具定义。

- **装配顺序**（CX-4）：Persona（M1）→ Skill Hint（M4/M10）→ 摘要（本层 `compact.py` 产出，可选）→ 阶段输入（M4 节点提供当前阶段协议说明）→ 用户消息（`window.py`）。
- **工具注入**（CX-5）：按本轮 `mode` 与 `plan.tools_needed`（阶段 4）从 M5 注册表取工具定义，**未注册不注入、本轮未选不注入**。阶段 1 Chat 路径不注入工具定义。

### 3.5 compact.py（阶段 3 落地，含 CompactProtocol）

**职责**：`/compact` 会话级上下文副作用，仅会话 owner 可执行（API.md §4.4）。

- **可控摘要**（CX-6）：保留最近 6 条原始消息、摘要 ≤2000 字符、**不删除原始记录**（原始与摘要冲突时原始优先，MEM-3）。
- **`CompactProtocol`**（M1-Q5 移归本层）：定义压缩阶段严格 JSON 输出协议（`summary`/`kept_ids[]`/`token_count`）+ `parse_compact` + 版本号 + 严格不兼容策略。
- **写入**：摘要文本交 M3 写入 `sessions.compact_summary`，本层不直接写库。

### 3.6 meter.py（阶段 3 落地）

**现状（V0.4.2）**：`GET /api/sessions/{id}/messages` 已由 `meter.compute_meter` 计算并返回 `context_meter`（窗口条数、token 估算、`compacted`）。前端只读该字段，禁止按 `messages` 总条数估算（CX-7）。未选会话时前端可渲染空环，选中会话后必须用服务端数字。

**职责**：ContextMeter 计算与投影，经 `GET /api/sessions/{id}/messages` 的 `context_meter` 下发（CX-7）。

- **数据源**：`recent_window` 产出的 user/assistant 窗口 + `compact_summary` + 常驻 Skill Hint + Agent 协议档 `context_window`。
- **计算**：`compute_meter` 估算 token（CJK 1.5 字/token，其余 4 字符/token），字段对齐 API.md §3.4。
- **投影**：`project_meter` 兼容早期 `token_used`/`token_limit` 键；`null`/空仍返回 None。

### 3.7 接口签名规格（签名级）

#### 3.7.1 window.py

```python
from typing import Mapping, TypedDict

class WindowMessage(TypedDict, total=False):
    """窗口内消息的最小投影；只含 user/assistant。"""
    role: str            # "user" | "assistant"
    content: str
    source_id: str | None

def recent_window(
    messages: list[WindowMessage],
    *,
    limit: int = 20,
    keep_from: str | None = None,   # compact_keep_from：保留起点 source_id
) -> list[WindowMessage]:
    """唯一窗口算法：取末尾 limit 条 user/assistant 消息；
    keep_from 指定时截断更早消息。事件（thought/tool/confirm/progress）已在调用方过滤。"""

def is_window_eligible(role: str) -> bool:
    """仅 user/assistant 进窗口（CX-2）。"""
```

#### 3.7.2 observation.py

```python
from app.harness.contracts import Observation

def to_observation(
    obs: Observation,            # M6 normalize 产出的已归一 Observation（异常已在 M6 处理）
    *,
    max_chars: int = 2000,
    source: str | None = None,
) -> Observation:
    """消费 M6 已归一的 Observation：调 M8 脱敏 + 截断 + 标 truncated/source，
    产出可注入上下文的 Observation（redacted=True）。归一逻辑 owner 是 M6（M6-D1）。"""

def truncate_with_marker(text: str, max_chars: int) -> tuple[str, bool]:
    """超长截断，保留头尾 + 截断标记（X-D2）；返回 (text, truncated)。"""
```

#### 3.7.3 assembly.py

```python
from typing import Mapping, Sequence

def assemble(
    *,
    system: str,                       # Persona（M1 build_system_prompt 产出）
    skill_hints: Sequence[str] | None = None,
    summary: str | None = None,         # compact 摘要（本层 compact.py 产出）
    stage_input: str | None = None,     # 当前阶段协议说明（M4 节点提供）
    messages: list[Mapping[str, object]],  # window.py 产出
    tool_defs: Sequence[Mapping[str, object]] | None = None,  # 按本轮最小注入
) -> dict:
    """按固定顺序装配模型本轮输入（CX-4）：
    Persona → Skill Hint → 摘要 → 阶段输入 → 用户消息。
    返回 {'system': str, 'messages': list, 'tools': list} 供 ModelRequest 构造。"""

def select_tool_defs(
    registry: "ToolRegistry",           # M5 registry.py（Protocol/类型由 M5 提供）
    *,
    mode: str,
    tools_needed: tuple[str, ...] = (),
) -> list[Mapping[str, object]]:
    """按本轮 mode 与 tools_needed 从注册表取工具定义（CX-5）。
    Chat/Direct 返回空。ReAct 注入已注册短原生工具并并入 tools_needed；
    未注册不返回；MCP 长工具不默认注入。"""
```

#### 3.7.4 compact.py

```python
from typing import Literal, TypedDict, Mapping
from app.errors import AppError, ErrorCode

ProtocolVersion = str  # 如 "compact.v1"

class CompactProtocolResult(TypedDict, total=False):
    protocol: Literal["compact"]
    version: ProtocolVersion
    fields: Mapping[str, object]   # summary/kept_ids/token_count

COMPACT_SCHEMA: dict   # summary(str)/kept_ids(list)/token_count(int)

def parse_compact(raw: str) -> CompactProtocolResult:
    """压缩协议严格 JSON 解析 + schema 校验；失败抛 AppError(VALIDATION)。
    summary ≤2000 字符（CX-6）。版本严格不兼容（拒绝旧版）。"""

def summarize(
    messages: list[Mapping[str, object]],
    *,
    keep_recent: int = 6,
    max_summary_chars: int = 2000,
) -> tuple[str, list[str]]:
    """可控摘要：保留最近 keep_recent 条原始消息，产出摘要文本 ≤max_summary_chars。
    返回 (summary, kept_ids)；**不删除原始记录**（CX-6/MEM-3）。
    摘要文本交 M3 写入 sessions.compact_summary。"""
```

#### 3.7.5 meter.py

```python
from typing import TypedDict

class ContextMeter(TypedDict, total=False):
    """ContextMeter 投影，只读 context_meter 字段（CX-7）。"""
    token_used: int
    token_limit: int
    window_ratio: float
    compacted: bool

def project_meter(context_meter: Mapping[str, object]) -> ContextMeter:
    """从会话 messages 的 context_meter 字段投影前端可读 meter。
    本层只投影，不重算（CX-7）。"""
```

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_context.py`

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_recent_window_default_20_tail` | X-A1 |
| `test_recent_window_compact_keep_from_truncates` | X-A1 |
| `test_window_filters_non_user_assistant` | X-A2 |
| `test_to_observation_redacts_and_truncates` | X-A3 |
| `test_to_observation_marks_source` | X-A3 |
| `test_assemble_order_persona_skill_summary_stage_messages` | X-A4 |
| `test_select_tool_defs_unregistered_excluded` | X-A5 |
| `test_select_tool_defs_chat_returns_empty` | X-A5 |
| `test_compact_keeps_recent_6_summary_le_2000` | X-A6 |
| `test_compact_does_not_delete_original` | X-A6 |
| `test_parse_compact_version_strict_rejects_old` | X-A6 |
| `test_project_meter_matches_context_meter` | X-A7 |

**TDD 顺序**：先写 `test_harness_context.py` 全红 → 实现 `window.py`（阶段 1）→ `assembly.py`（阶段 1）→ `observation.py`（阶段 2）→ `compact.py`/`meter.py`（阶段 3）→ 全绿。`observation.py` 依赖 M8 脱敏，测试用夹具注入脱敏函数。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/context/__init__.py` | 阶段 1 | 修改（re-export） | — |
| `app/harness/context/window.py` | 阶段 1 | 新增 | CX-1/CX-2、X-1/X-2 |
| `app/harness/context/assembly.py` | 阶段 1/2 | 新增 | CX-4/CX-5、X-4/X-5 |
| `app/harness/context/observation.py` | 阶段 2 | 新增 | CX-3、X-3 |
| `app/harness/context/compact.py` | 阶段 3 | 新增 | CX-6、X-6、CompactProtocol（M1 移入） |
| `app/harness/context/meter.py` | 阶段 3 | 新增 | CX-7、X-7 |
| `backend/api/tests/test_harness_context.py` | 阶段 1/2/3 | 新增 | X-A1~X-A7 |
| `app/routers/ws.py` | 阶段 1 | 修改 | `_history_messages` 改调 `window.recent_window` |

---

## 6. 依赖与红线

- **上游依赖**：Harness §4.2（CX-1~7）、§2.4（密钥保护）、API.md §3.4（context_meter）/§4.4（/compact owner 限制）、PRD §5.1.3。
- **下游被依赖**：M4（`assemble` 供节点装配上下文）、M5（`select_tool_defs` 消费注册表）、M3（`summarize` 产出交 M3 写库）、前端（`project_meter` 投影）。
- **跨层协作**：M1（Persona）、M7（`Observation` 契约）、M8（脱敏函数）、M5（工具注册表）。
- **红线**：
  - 事件不进窗口；
  - 工具结果脱敏截断带来源，不原样注入；
  - 装配顺序固定；
  - 工具定义最小注入；
  - `/compact` 不删除原始记录；
  - ContextMeter 只读不重算；
  - 提示词不含密钥。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M1-Q5 移入 | `CompactProtocol` 归属 | 归本层 `compact.py`（压缩是上下文行为），M1 不再定义 |
| X-D1 | `recent_window` 默认 limit | 20（对齐现有 `ws.py:_history_messages`） |
| X-D2 | observation 截断阈值 | 默认 `max_chars=2000`，保留头尾 + `truncated` 标记 |
| X-D3 | `/compact` 保留条数 | 最近 6 条（CX-6） |
| X-D4 | `CompactProtocol` 版本策略 | 严格不兼容（对齐 M1-Q3） |
| X-D5 | ContextMeter 计算方 | 本层只投影，由 `messages.context_meter` 数据源提供，不重算 |

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.22 §3.4 为唯一真理。M2 是前端 ContextMeter 与 `/compact` 的数据源头：`meter.py` 投影的 `context_meter` 经 `GET /api/sessions/{id}/messages` 下发，前端只读不重算（CX-7）；`compact.py` 执行 `/compact` 会话级副作用。前端不臆造字段，发现契约缺失先回写 API.md 再实现。

### 8.1 对应前端组件与任务

| M2 文件 | 前端用途 | 前端文件 | 对接契约 | 落地阶段 | 验收点 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `meter.py` `project_meter` | ContextMeter 双圆环 + 明细 | `components/agent/ContextMeter.vue` | API.md §3.4 `context_meter`（V1.22 加 `compacted`）+ M2 §3.7.5 | 阶段 3 | `compacted=true` 显示「已压缩」徽标；`compact_summary` 存在时显示摘要提示；只读服务端数字，禁止按 messages 条数自减 |
| `compact.py` `summarize` | `/compact` 斜杠执行 | `views/Agent.vue` `handleSlashSelect`；`agent/slashRegistry.ts` | API.md §4.4 `/compact` owner 限制 + M2 §3.5 | 阶段 3 | 非 owner 提交 Toast「仅会话 owner 可压缩」；执行后刷新 `currentCompactSummary` 与 `context_meter` |
| `observation.py` `to_observation` | ToolCard 截断/脱敏徽标 | `components/agent/ToolCard.vue` | API.md §4.3 `tool_result`（V1.22 加 `truncated`/`source`/`redacted`）+ M2 §3.7.2 | 阶段 2 | `truncated=true` 显示「结果已截断」；`redacted=true` 显示「已脱敏」（M6 标记脱敏，M2 调 M8 递归脱敏） |
| `assembly.py` `select_tool_defs` | 工具定义装配（间接） | — | — | 阶段 1/2 | 前端无直接对接，仅 ToolCard 中文名映射由 API.md §4.3 短工具中文名表提供 |
| `window.py` `recent_window` | 消息窗口（间接） | — | — | 阶段 1 | 前端无直接对接，ContextMeter 的 `messages`/`window` 字段反映窗口状态 |

### 8.2 前端验收要点

- **ContextMeter 数据源唯一性**：只读 `GET /api/sessions/{id}/messages` 的 `context_meter`，禁止 localStorage / admin settings 冒充（AGENTS.md §5.3.3）。
- **`compacted` 字段对接**：`ContextMeterData` 类型加 `compacted: boolean`，与 API.md V1.22 §3.4 一致。
- **`/compact` owner 预校验**：客户端先判 owner，非 owner 直接 Toast，不发上行。
- **截断/脱敏徽标**：`ToolCard` 渲染 `truncated`/`redacted` 徽标，不静默丢弃 M6 标记的脱敏信息。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-上下文工程层.md` | 新增 V0.3 → 修订 V0.4 → 修订 V0.4.1 → 修订 V0.4.2 → 修订 V0.4.3 → 修订 V0.4.4 | V0.3–V0.4.3 见上；V0.4.4：`assemble` 增加可选【当前技能工作流】段，`skill_hints_for_turn` 按本轮 `skill_id` 选 Hint。 |
| `backend/api/app/harness/context/assembly.py` | 修改 | `skill_hints_for_turn`；`assemble(skill_workflow=)` 插入 Hint 之后 |
| `backend/api/app/agent/react.py` / `routing.py` | 修改 | Chat 常驻 Hint；ReAct 按 `plan.skill_id` 注入工作流 |
| `backend/api/tests/test_harness_context.py` / `test_harness_skills.py` | 修改 / 新增 | 装配顺序与相邻回合不污染 |

### V0.4.5（2026-09-09）— AgentLoop 实际请求来源计量

AgentLoop 的请求仪表不复用历史会话的宽泛预估，而是以本轮 `LoopRequest` 的协议序列化作为唯一计量来源。计量分为系统提示词、Skill、MCP、原生工具和对话消息：MCP/原生工具根据注册表的 `transport` 归类，Skill 仅在其正文确实进入本轮请求时计入；当前 Loop 没有注入 Skill 正文，故为 0。前端按五类来源以不同颜色显示分段进度条，保留为 0 的明细行，输出预留不参与已用比例。

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `backend/api/app/agent/loop_wiring.py` | 修改 | `LoopRequest` 同源序列化 token 拆分与 MCP 注册表归类。 |
| `backend/api/app/agent/loop_presentation.py` | 修改 | 将五类输入 token 写入 `request_summary.context_meter`。 |
| `frontend/src/components/agent/loop/LoopContextMeter.vue` | 修改 | 紧凑仪表、彩色分段进度条和五类详细明细。 |

### V0.4.6（2026-09-26）— v2 自动摘要、原文证据与来源回读

当前 v2 使用 `agent/compaction.py` 的异步请求准备：输入达到可用预算的 85% 自动摘要，目标 65%，保留最新用户输入和最近完整工具单元。旧固定六条窗口、2000 字符和严格 JSON `CompactProtocol` 不适用于此路径；手动 `/compact` 已下线。摘要与原始事实边界持久化，后续请求恢复，原文不删除。

摘要固定区分约束、事实、未完成／失败和来源，可用 `[m:N]` 指向当前运行规范消息。正文引用须位于已覆盖历史；额外保留最多三条有界完整用户原文并逐条校验来源，作为优先于派生摘要的证据。原文预算为 `min(512, 可用输入预算/10)`，从最近已覆盖用户消息向前收集，遇过长或多模态消息即停止，不越过可能的新更正而强调旧要求，不声称全部历史要求无损。主运行可调用 `history.read` 按来源分页回读，返回受总 token 上限约束且不含 opaque、内部推理或图像二进制的历史资料。

一次准备复用历史快照及同候选 token 估算，下次准备重新读取，不以跨回合缓存掩盖新增事实。摘要、证据和偏好均计入实际请求预算。会话仪表中的“会话记忆”计入实际摘要资料，摘要模型的已知调用用量由 `context.usage` 累计；这与存储历史总量不同。

### 修改代码文件与作用清单

- `backend/api/app/agent/compaction.py`：同源预算、来源引用、有界原文和准备过程复用。
- `backend/api/app/agent/history.py`、`backend/api/app/agent/loop_wiring.py`：当前日志回读工具及真实请求接线。
- `backend/api/app/harness/contracts/loop_events.py`：证据元数据与敏感路径。
- API 连续压缩、恢复、回读与偏好测试：验证有界原文、来源合法性、调用隔离及实际注入预算；不替代真实供应商语义保真验收。

### V0.4.7（2026-09-26）— 个人记忆逐请求装配

个人记忆按当前用户问题和工作区在每次模型请求前检索，作为不可缓存的动态资料段注入，只用于本人私有主会话。摘要调用等待后再次读取，防止等待期间的更正或删除继续作为最新记忆传入；刷新后重新计算完整请求硬预算，超限不发送。摘要、配置偏好和个人记忆均按实际协议序列化后的 token 差额计入 `memory_files`，不在会话仪表或公共诊断事件中输出记忆正文。

### 修改代码文件与作用清单

- `backend/api/app/agent/loop_wiring.py`：动态资料刷新、摘要后重建与硬预算检查，以及三类记忆同源计量。
- `backend/api/app/harness/memory/{personal,preference}.py`：有界召回与私有会话消费登记。
- `backend/api/tests/test_loop_personal_memory.py`：每次请求、摘要等待、更正撤回、子运行隔离和实际请求预算回归。

### V0.4.8（2026-09-26）— 原文证据安全与主专家回读修复

证据遇已知凭据整条停止保留；旧证据先验证来源和逐字一致，再移除敏感项及其之前的证据。保留的原文仍逐字准确，原始日志不变。新摘要候选含已知凭据时走现有失败回退，不持久化候选正文。该检测与个人记忆复用纯文本安全函数，不依赖 ORM。

四类显式主专家同步声明 `history.read`，注册后不再被工具白名单丢弃；子运行继续由原工具交集排除。回归通过实际装配、压缩和调度回读验证，避免仅检查工具注册名。

### 修改代码文件与作用清单

- `backend/api/app/agent/compaction.py`、`backend/api/app/harness/security/loop_redaction.py`：证据筛选、恢复验真后的过滤与摘要候选校验。
- `backend/api/app/agent/experts.py`、压缩凭据及历史工具测试：主专家白名单与运行内回读闭环。

### V0.4.9（2026-09-26）— 回读分页前的凭据过滤

`history.read` 的用户正文、工具结果及参数内文本统一复用个人记忆的已知凭据识别。包含密码／密钥赋值或私钥头的字符串整体替换为脱敏占位，再生成公开 JSON 和分页位置；避免公开工具结果重新带出压缩证据已拒绝的内容。保留原始事实，普通安全说明仍可完整回读。

### 修改代码文件与作用清单

- `backend/api/app/agent/history.py`：在公开投影和分页前递归过滤已知凭据。
- `backend/api/tests/test_loop_history.py`：覆盖三类位置、三类凭据、分页重组和普通说明保留。




