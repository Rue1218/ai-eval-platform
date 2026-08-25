# AI 测试与评估平台 — Harness 上下文工程层模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 上下文工程层模块设计 |
| 版本 | V0.4.3 |
| 审查日期 | 2026-08-26 |
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
- 上下文装配顺序固定：Persona → Skill Hint → 摘要 → 阶段输入（CX-4）。
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
| CX-4 | 上下文装配顺序固定：Persona → Skill Hint → 摘要 → 阶段输入 | X-4：`assembly.py` `assemble(system, skill_hints, summary, stage_input, messages)` | 阶段 1 |
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
| X-A4 | 装配顺序输出为 Persona → Skill Hint → 摘要 → 阶段输入 → 消息 | 顺序断言 |
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
| `docs/AI测试与评估平台-Harness-上下文工程层.md` | 新增 V0.3 → 修订 V0.4 → 修订 V0.4.1 → 修订 V0.4.2 → 修订 V0.4.3 | V0.3–V0.4.2 见上；V0.4.3：`assemble`/`select_tool_defs` 接入 ReAct 与 Chat 节点；ReAct 按 CX-5 注入短原生工具；`compact_summary` 经 `configurable.session` 装配。 |

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `backend/api/app/harness/context/assembly.py` | 修改 | `select_tool_defs` 对 ReAct 注入 native 短工具；新增 `skill_hint_lines` / `compact_summary_from_configurable` |
| `backend/api/app/agent/react.py` | 修改 | `react_agent_node` 走 `assemble`，不再 `all_defs()` 全量注入 |
| `backend/api/app/agent/routing.py` | 修改 | `chat_stream_node` 走 `assemble`，Chat 不注入工具 |
| `backend/api/app/routers/ws.py` | 修改 | 默认 Persona 填常驻 Skill Hint；`compact_summary` 注入 configurable |
| `backend/api/app/harness/skills/registry.py` | 修改 | 补 `get_hint` |
| `backend/api/tests/test_harness_context.py` / `test_agent_react.py` / `test_agent_routing.py` / `test_agent_multiturn.py` / `test_harness_phase4.py` | 修改 | CX-4/CX-5 与 `get_hint` 回归 |




