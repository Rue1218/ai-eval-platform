# AI 测试与评估平台 — Harness 执行层模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 执行层模块设计 |
| 版本 | V0.4.1 |
| 审查日期 | 2026-08-23 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M5 执行层（`app/harness/execution/` + `app/agent/react.py`） |
| 上游权威 | Harness 需求文档 V1.4.4 §4.5、§2.4、§7、§9；API.md V1.22 §4.3；PRD §5.1.3 |

> **阅读关系**：本文是 Harness §9.2「层 5 执行」行的展开。工具注册表为工具元数据唯一源；`ToolNode` 包装注册表（禁用 `create_react_agent`）；长任务经 PG 队列交 Worker（M4 `worker_bridge` 阶段 4）；`Observation` 归一交 M6 反馈层。

> **⚠️ 定位扩展声明**（已回写 Harness §7，见 V1.4.3）：本层工具集**扩展为通用能力**——阶段 2 先落地基础 IO 工具（`read`/`write`/`edit`/`bash`/`web_search`/`web_fetch`），评测域工具（`task.create` 等）阶段 4 随确认卡入队再加。基础工具中的 `web_search`/`web_fetch` 走**内部短 MCP**（平台自实现适配器，不走外部 MCP 服务器，不触碰 Harness §7「禁止外部 MCP」红线）。

---

## 1. 模块定位与边界

### 1.1 定位

执行层在权限、参数绑定、超时、脱敏与白名单边界内**真正产生副作用**。本层提供工具注册表（元数据/白名单/分派唯一源）、附件参数系统绑定、`ToolNode`（LangGraph 节点包装注册表）、短工具分派（含 bash 沙箱与 web 内部短 MCP）、长任务入队桥接、Worker 自管 Session 守卫。

模型不直接执行副作用；编排层（M4）产出 `ToolCall`，本层 `ToolNode` 消费并归一为 `Observation`/`ToolResult`。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 工具注册表（元数据/白名单/分派唯一源，`registry.py`） | 工具调用决策（M4 ReAct 节点） |
| 附件参数系统绑定（`binding.py`） | 模型 JSON 解析（M1 `protocols.py`） |
| `ToolNode` 包装（`toolnode.py`，LangGraph 节点） | 图拓扑（M4 `app/agent/react.py`） |
| 短工具分派 + 超时 + 脱敏日志（`dispatch.py`） | 脱敏递归实现（M8 `security/secrets.py`） |
| bash 沙箱（subprocess + 受限环境） | 沙箱宿主编排（运维） |
| web 内部短 MCP 适配器（`web_search`/`web_fetch`） | 外部 MCP 服务器（红线禁止） |
| 长任务入队（`worker_bridge.py`，阶段 4） | Worker 执行器（`backend/worker/`） |
| Worker 自管 Session 守卫（`session_guard.py`） | 跨 Session ORM 传对象（红线禁止） |
| `Observation` 归一产出 | 反馈复核（M6） |

### 1.3 红线（继承 Harness §4.5 + §2.4 + §7）

- 工具元数据、白名单与执行分派**唯一来源为注册表**（EX-1）；新增工具必须登记并走统一执行入口。
- 附件参数**系统绑定**，模型不得伪造附件 ID（EX-2）。
- 每个工具声明 `permission` 与 `timeout_s`，执行带超时与脱敏日志（EX-3）。
- 长任务经 PG 队列由 Worker 消费，进度/报告/错误写 `ws_events`（EX-4）。
- 未注册工具、未启用能力一律拒绝（`VALIDATION` 400），**禁止假成功**（EX-5）。
- Worker 执行器自管 DB Session，**禁止跨 Session 传 ORM 对象**（EX-6）。
- **排除 `create_react_agent`**；`ToolNode` 必须包装注册表，参数绑定/白名单/超时/脱敏不得被框架默认行为绕过（Harness §2.4）。
- `web_search`/`web_fetch` 走内部短 MCP，**禁止外部 MCP**（Harness §7）。
- `rag` 未接入不得 mock 成功（MEM-5）。

---

## 2. 需求发散

### 2.1 从 Harness §4.5 提取的需求

| 编号 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| EX-1 | 工具元数据、白名单与执行分派唯一来源为注册表 | X-1：`registry.py` 提供 `register`/`get`/`all_defs`；未注册即拒绝 | 阶段 2 |
| EX-2 | 附件参数系统绑定，模型不得伪造附件 ID | X-2：`binding.py` `bind_attachments(call, db, user_id)` 校验 file_id 归属 | 阶段 2 |
| EX-3 | 每个工具声明 `permission` 与 `timeout_s`，执行带超时与脱敏日志 | X-3：`dispatch.py` `execute(call)` 带超时 + 脱敏日志 | 阶段 2 |
| EX-4 | 长任务经 PG 队列由 Worker 消费，进度/报告/错误写 `ws_events` | X-4：`worker_bridge.py` `enqueue_long_task(kind, spec)` 创建 `queued` Task | 阶段 4 |
| EX-5 | 未注册工具、未启用能力一律拒绝（`VALIDATION`），禁止假成功 | X-5：`dispatch.execute` 未注册抛 `VALIDATION` | 阶段 2 |
| EX-6 | Worker 执行器自管 DB Session，禁止跨 Session 传 ORM 对象 | X-6：`session_guard.py` 守卫 + 文档约束 | 阶段 4 |

### 2.2 基础工具集发散（定位扩展）

| 工具名 | 类别 | 阶段 | 安全边界 |
| :--- | :--- | :--- | :--- |
| `read` | 文件读 | 阶段 2 | 受限工作目录、只读 |
| `write` | 文件写（新建） | 阶段 2 | 受限工作目录 |
| `edit` | 文件编辑（改） | 阶段 2 | 受限工作目录、原子替换 |
| `bash` | 命令执行 | 阶段 2 | subprocess + 受限环境（工作目录/超时/命令黑名单） |
| `web_search` | 网络检索 | 阶段 2 | 内部短 MCP 适配器（平台自实现） |
| `web_fetch` | 网页抓取 | 阶段 2 | 内部短 MCP 适配器（平台自实现） |
| `task.create`/`task.cancel`/`testcase.confirm`/`dispatch.overview` | 评测域 | 阶段 4 | 随确认卡入队（API.md §4.3） |
| `audio.*`/`image.generate` | 多媒体 | 阶段 4+ | 现有短工具，按需纳入注册表 |

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| X-A1 | 未注册工具调用被拒绝（`VALIDATION`） | 注册表断言 |
| X-A2 | 附件 file_id 伪造被拒绝（非归属用户） | 绑定断言 |
| X-A3 | 工具执行超时返回 `timeout` observation | 超时断言 |
| X-A4 | 执行日志不含密钥/敏感参数 | 脱敏断言 |
| X-A5 | 长任务入队创建 `queued` Task，不阻塞对话回合 | 入队断言 |
| X-A6 | Worker 自管 Session，跨 Session 传 ORM 抛错 | 守卫断言 |
| X-A7 | `bash` 黑名单命令（rm/sudo/网络）被拒绝 | 沙箱断言 |
| X-A8 | `web_search`/`web_fetch` 走内部适配器，不连外部 MCP 服务器 | 路径断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/execution/
├── __init__.py
├── registry.py        # 阶段 2：工具注册表（元数据/白名单/分派唯一源）
├── binding.py         # 阶段 2：附件参数系统绑定
├── toolnode.py        # 阶段 2：ToolNode 包装（LangGraph 节点，包装注册表）
├── dispatch.py        # 阶段 2：短工具分派 + 超时 + 脱敏日志（含 bash 沙箱、web 内部短 MCP）
├── worker_bridge.py   # 阶段 4：长任务入队（PG 队列 → Worker）
├── session_guard.py   # 阶段 4：Worker 自管 Session 守卫
├── adapters/          # 占位：执行适配器边界（按需填充）
└── mcp/              # 占位：MCP 边界（明确不做外部 MCP，保留包边界）

app/agent/react.py     # 阶段 2：ReAct 子图（agent 节点 + ToolNode 条件边）
```

### 3.2 registry.py（阶段 2 落地）

**职责**：工具元数据、白名单与执行分派的**唯一来源**（EX-1/5）。

- 每个工具登记 `ToolDef`：`name`/`description`/`parameters_schema`/`permission`/`timeout_s`/`handler`。
- `register(def_)`：登记工具；`get(name)`：取定义；`all_defs()`：取全部工具定义（供 M2 `select_tool_defs` 最小注入）。
- 未注册工具调用一律拒绝（`VALIDATION`），禁止假成功。
- 阶段 2 注册基础 6 工具；阶段 4 追加评测域工具。

### 3.3 binding.py（阶段 2 落地）

**职责**：附件参数系统绑定（EX-2）。

- `bind_attachments(call, db, user_id)`：校验 `call.arguments` 中的 `file_id` 归属当前用户与会话，模型不得伪造附件 ID。
- 伪造或不归属 → 抛 `VALIDATION`。

### 3.4 toolnode.py（阶段 2 落地）

**职责**：LangGraph `ToolNode` 包装注册表（Harness §2.4，禁用 `create_react_agent`）。

- 包装 `registry` + `binding` + `dispatch`：参数绑定 → 白名单校验 → 超时执行 → 脱敏 → 归一为 `Observation`/`ToolResult`。
- 节点返回 `{'observations': [Observation], 'pending_events': [NodeEvent(tool_call/tool_result)]}`，写入 GraphState。
- **不得**被框架默认行为绕过参数绑定/白名单/超时/脱敏。

### 3.5 dispatch.py（阶段 2 落地，含 bash 沙箱与 web 内部短 MCP）

**职责**：短工具分派 + 超时 + 脱敏日志（EX-3）。

- `execute(call, *, timeout_s, permission)`：按 `call.name` 分派到 handler，带超时；超时返回 `timeout` observation；日志脱敏（调 M8）。
- **bash 沙箱**（subprocess + 受限环境）：
  - 工作目录限定（会话沙箱目录）；
  - 超时（工具 `timeout_s`）；
  - 命令黑名单（`rm`/`sudo`/网络类等危险命令拒绝）；
  - 不给 root、不写宿主敏感路径。
- **web 内部短 MCP**（`web_search`/`web_fetch`）：
  - 平台自实现适配器（`dispatch.py` 内或 `adapters/` 子模块），**不走外部 MCP 服务器**；
  - `web_search`：调内部检索后端；`web_fetch`：内部抓取 + 脱敏；
  - 不引入外部 MCP 依赖（Harness §7 红线）。

### 3.6 worker_bridge.py（阶段 4 落地）

**职责**：长任务入队（EX-4）。

- `enqueue_long_task(db, session_id, user_id, kind, spec, *, parent_task_id=None)`：创建 `queued` Task + AuditLog，交 Worker 消费。
- **`kind` 取 Task.kind 短名**（`benchmark`/`testcase`/`rag`/`stress`），与 M10 `skill_to_kind` 对齐、与 PRD/API `Task.kind` 一致。
- **不阻塞对话回合**：入队即返回 `task_id`，进度/报告/错误由 Worker 写 `ws_events`。
- **长工具集** `LONG_TOOLS`（工具名，带动作后缀）= `{benchmark.run, testcase.generate, rag.evaluate, stress.run}`，供 M4 `gates.py` 识别长工具做门禁；与 Task.kind 短名分离（`kind` ↔ `LONG_TOOLS` 映射：`benchmark`↔`benchmark.run` 等，由 M4 路由层在 `gates.py` 落地时维护对照表）。

### 3.7 session_guard.py（阶段 4 落地）

**职责**：Worker 自管 Session 守卫（EX-6）。

- 守卫 Worker 执行器自管 DB Session，**禁止跨 Session 传 ORM 对象**（会触发 `InvalidRequestError`，任务永久卡 `running`）。
- 提供 `with_managed_session()` 上下文管理器；执行器内 `Session` 创建/提交/关闭受守卫约束。
- 文档 + 运行时断言双保险。

### 3.8 接口签名规格（签名级）

#### 3.8.1 registry.py

```python
from dataclasses import dataclass, field
from typing import Callable, Mapping

@dataclass(frozen=True, slots=True)
class ToolDef:
    """工具元数据（注册表唯一源）。"""
    name: str                          # 如 "read"/"bash"/"web_search"
    description: str
    parameters_schema: Mapping[str, object]   # JSON schema
    permission: str                    # 权限标识
    timeout_s: float                    # 执行超时
    handler: Callable[..., object]      # 执行函数（不入 GraphState，仅运行时）

class ToolRegistry:
    """工具注册表；白名单与分派唯一源。"""
    def register(self, def_: ToolDef) -> None: ...
    def get(self, name: str) -> ToolDef:
        """取定义；未注册抛 AppError(VALIDATION)。"""
    def all_defs(self) -> list[Mapping[str, object]]:
        """返回全部工具定义（供 M2 select_tool_defs 最小注入）。"""
    def is_registered(self, name: str) -> bool: ...

# 阶段 2 默认注册（基础 6 工具）
def build_default_registry() -> ToolRegistry:
    """注册 read/write/edit/bash/web_search/web_fetch。"""
```

#### 3.8.2 binding.py

```python
from app.harness.contracts import ToolCall

def bind_attachments(call: ToolCall, db, user_id: str) -> ToolCall:
    """校验 call.arguments 中的 file_id 归属当前用户与会话；
    伪造/不归属抛 AppError(VALIDATION)。返回绑定后的 call。"""
```

#### 3.8.3 toolnode.py

```python
from langgraph.graph import StateGraph

def build_tool_node(registry: ToolRegistry, binding, dispatch) -> Callable:
    """构造 LangGraph ToolNode 包装：参数绑定 → 白名单校验 → 超时执行 → 脱敏
    → 归一为 Observation/ToolResult。返回节点函数。
    节点返回 {'observations': [Observation], 'pending_events': [NodeEvent]}。"""
```

#### 3.8.4 dispatch.py

```python
from app.harness.contracts import Observation, ToolCall, ToolResult

def execute(call: ToolCall, *, timeout_s: float, permission: str,
             sandbox_dir: str | None = None) -> Observation:
    """按 call.name 分派到 handler，带超时；超时返回 timeout observation；
    日志脱敏（调 M8）。sandbox_dir 限 bash 工作目录。"""

# bash 沙箱
BASH_BLOCKLIST: frozenset[str] = frozenset(
    {"rm", "sudo", "curl", "wget", "nc", "ssh", "scp", "chmod", "chown"}
)

def run_bash(cmd: str, *, sandbox_dir: str, timeout_s: float) -> str:
    """subprocess + 受限环境：工作目录限定、超时、命令黑名单校验。
    黑名单命中抛 AppError(VALIDATION)。"""

# web 内部短 MCP 适配器
def web_search(query: str, *, timeout_s: float) -> str:
    """内部检索适配器（平台自实现，不走外部 MCP 服务器）。"""

def web_fetch(url: str, *, timeout_s: float) -> str:
    """内部抓取适配器 + 脱敏（不走外部 MCP 服务器）。"""
```

#### 3.8.5 worker_bridge.py

```python
from app.errors import AppError, ErrorCode

# Task.kind 短名（与 M10 skill_to_kind、PRD/API Task.kind 一致）
TASK_KINDS: frozenset[str] = frozenset({"benchmark", "testcase", "rag", "stress"})

# 长工具名集（带动作后缀，供 M4 gates.py 识别长工具做门禁；与 Task.kind 短名分离）
LONG_TOOLS: frozenset[str] = frozenset(
    {"benchmark.run", "testcase.generate", "rag.evaluate", "stress.run"}
)

def enqueue_long_task(db, session_id: str, user_id: str,
                       kind: str, spec: dict,
                       *, parent_task_id: str | None = None) -> str:
    """创建 queued Task + AuditLog，交 Worker 消费；返回 task_id。
    不阻塞对话回合。kind 取 Task.kind 短名 ∈ TASK_KINDS，否则抛 AppError(VALIDATION)。
    rag 未接入时禁止 mock succeeded（MEM-5）。"""
```

#### 3.8.6 session_guard.py

```python
from contextlib import contextmanager

@contextmanager
def with_managed_session():
    """Worker 执行器自管 DB Session 上下文；
    禁止跨 Session 传 ORM 对象（运行时断言）。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def assert_no_orm_leak(obj: object) -> None:
    """断言对象不含跨 Session ORM 引用（EX-6）。"""
```

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_execution.py`（含 `test_tool_registry.py`/`test_toolnode.py`/`test_bash_sandbox.py`）

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_unregistered_tool_rejected` | X-A1 |
| `test_bind_attachments_rejects_foreign_file_id` | X-A2 |
| `test_execute_timeout_returns_timeout_observation` | X-A3 |
| `test_execute_log_no_secret` | X-A4 |
| `test_enqueue_long_task_creates_queued_task_nonblocking` | X-A5 |
| `test_session_guard_rejects_cross_session_orm` | X-A6 |
| `test_bash_blocklist_rejects_rm_sudo_network` | X-A7 |
| `test_web_search_uses_internal_adapter_no_external_mcp` | X-A8 |

**TDD 顺序**：先写 `test_tool_registry.py`（阶段 2）全红 → 实现 `registry.py`/`binding.py`/`dispatch.py`/`toolnode.py` → 全绿；阶段 4 补 `worker_bridge`/`session_guard` 测试。bash 沙箱测试用临时目录夹具；web 适配器测试用 mock 后端。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/execution/__init__.py` | 阶段 2 | 修改（re-export） | — |
| `app/harness/execution/registry.py` | 阶段 2 | 新增 | EX-1/EX-5、X-1 |
| `app/harness/execution/binding.py` | 阶段 2 | 新增 | EX-2、X-2 |
| `app/harness/execution/toolnode.py` | 阶段 2 | 新增 | EX-1（ToolNode 包装） |
| `app/harness/execution/dispatch.py` | 阶段 2 | 新增 | EX-3、X-3（含 bash 沙箱 + web 内部短 MCP） |
| `app/harness/execution/worker_bridge.py` | 阶段 4 | 新增 | EX-4、X-4 |
| `app/harness/execution/session_guard.py` | 阶段 4 | 新增 | EX-6、X-6 |
| `app/agent/react.py` | 阶段 2 | 新增 | ReAct 子图（M4 协作） |
| `backend/api/tests/test_harness_execution.py` | 阶段 2/4 | 新增 | X-A1~X-A8 |

> `adapters/` 与 `mcp/` 子包保留边界占位；`mcp/` 明确不做外部 MCP。

---

## 6. 依赖与红线

- **上游依赖**：Harness §4.5（EX-1~6）、§2.4（ToolNode 包装）、§7（外部 MCP 红线）、API.md §4.3（短工具清单）、PRD §5.1.3。
- **下游被依赖**：M4（`ToolNode` 供 ReAct 子图、`worker_bridge` 供确认卡入队）、M6（`Observation` 归一消费）、M2（`registry.all_defs` 供工具定义最小注入）、Worker（`session_guard` 约束执行器）。
- **跨层协作**：M7（`ToolCall`/`ToolResult`/`Observation` 契约）、M8（脱敏函数）、M3（`observations` 字段）。
- **红线**：
  - 注册表为唯一源，未注册即拒绝，禁止假成功；
  - 附件参数系统绑定，禁伪造 file_id；
  - 超时 + 脱敏日志；
  - 长任务入队不阻塞；
  - Worker 自管 Session，禁跨 Session 传 ORM；
  - 禁用 `create_react_agent`，ToolNode 必须包装注册表；
  - web 走内部短 MCP，禁外部 MCP；
  - `rag` 未接入禁 mock。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M5-D1 | 工具集范围 | 阶段 2 先做基础 6 工具（read/write/edit/bash/web_search/web_fetch），评测工具阶段 4 随确认卡入队 |
| M5-D2 | bash 安全边界 | subprocess + 受限环境（工作目录限定/超时/命令黑名单 `BASH_BLOCKLIST`） |
| M5-D3 | web 工具实现 | 内部短 MCP（平台自实现适配器，不走外部 MCP 服务器，不碰 §7 红线） |
| M5-D4 | 定位扩展声明 | 基础工具集为通用能力；已回写 Harness V1.4.3 §7 |
| M5-D5 | ToolNode 实现 | 自建包装注册表，禁用 `create_react_agent`（Harness §2.4） |
| M5-D6 | 长工具集合 | `LONG_TOOLS`（工具名，带动作后缀）= `{benchmark.run, testcase.generate, rag.evaluate, stress.run}`，供 M4 `gates.py` 识别长工具；`enqueue_long_task.kind` 取 Task.kind 短名（`benchmark`/`testcase`/`rag`/`stress`，对齐 M10 `skill_to_kind`），二者分离 |
| M5-D7 | Worker Session | 自管 Session + `with_managed_session` 守卫 + `assert_no_orm_leak` 断言 |

> **已回写 Harness V1.4.3 §7**：新增「内部短 MCP 允许 + 基础工具集为通用能力」裁决行（M5-D4）。

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.21 §4.3 为唯一真理。M5 产出的 `tool_call`/`tool_result` 事件是前端 ToolCard 的数据来源；长任务经 `worker_bridge` 入队后，前端只收 `progress`/`report`/`error`（API.md §4.3 末尾）。前端不臆造字段，发现契约缺失先回写 API.md 再实现。

### 8.1 对应前端组件与任务

| M5 文件 | 产出事件 | 前端渲染 | 前端文件 | 对接契约 | 落地阶段 | 验收点 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `toolnode.py` `build_tool_node` | `tool_call`/`tool_result` | ToolCard pending→done | `components/agent/ToolCard.vue` | API.md §4.3 + M7 §3.6.2 | 阶段 2 | 三态正常；`latency_ms` 展示；中文名映射（API.md §4.3 短工具中文名表） |
| `dispatch.py` `execute`（短工具） | `tool_result`（含 `truncated`/`source`/`redacted`） | ToolCard done + 徽标 | `components/agent/ToolCard.vue` | API.md §4.3（V1.21 扩展字段）+ M7 §3.6.2 `Observation` | 阶段 2 | `source` 为溯源标识字符串（对齐 M7）；`truncated`/`redacted` 徽标渲染 |
| `worker_bridge.py` `enqueue_long_task` | `progress`/`report`/`error`（长任务） | ProgressDock + ReportCard + ErrorStrip | `components/agent/ProgressDock.vue`/`ReportCard.vue` | API.md §4.3 末尾「长工具不由 Agent 进程跑完；前端只收 progress/report/error」 | 阶段 4 | 前端不直接收长任务 `tool_result`，只收 `progress`/`report`/`error` |
| `registry.py` `ToolRegistry` | 工具元数据（间接） | ToolCard 中文名 | — | API.md §4.3 短工具中文名表 | 阶段 2 | 前端中文名表与注册表 `name` 对齐 |
| `session_guard.py` | Worker 自管 Session（后端内部） | — | — | — | 阶段 4 | 前端无直接对接 |

### 8.2 前端验收要点

- **长任务事件边界**：长任务（benchmark/testcase/rag/stress）入队后，前端**不得**期待 `tool_result`，只处理 `progress`/`report`/`error`（API.md §4.3 末尾）。因此 `tool_result` 仅由短工具产出，`source` 字段（对齐 M7 `Observation.source`，溯源标识字符串如 `"file:uuid"`）不会出现 `"long"` 值。
- **`source` 字段语义**：`source` 为 M7 `Observation.source` 的溯源标识字符串（可选），非工具类型枚举；前端据此展示结果来源，不用于区分短/长工具（长工具不发 `tool_result`）。
- **ToolCard 中文名**：前端中文名表覆盖 API.md §4.3 列出的全部短工具（`model.list`/`dataset.list`/`kb.list`/`task.get`/`report.get`/`task.create`/`task.cancel`/`testcase.confirm`/`dispatch.overview`/`audio.*`/`image.generate`）。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-执行层.md` | 新增 V0.3 → 修订 V0.4 → 修订 V0.4.1 | V0.3 M5 执行层模块设计：定义工具注册表、附件参数绑定、ToolNode 包装（禁 `create_react_agent`）、短工具分派（含 bash 沙箱 + web 内部短 MCP）、长任务入队、Worker 自管 Session 守卫；含定位扩展声明（基础工具集为通用能力，已回写 Harness V1.4.3 §7）与接口签名级与 TDD 验收；V0.4 对齐 API.md V1.21：新增 §8「前端联调」章节；V0.4.1 配合 API.md V1.22：§8.1/§8.2 修正 `source` 字段语义（对齐 M7 `Observation.source` 溯源标识字符串，删除 `source="long"` 矛盾表述）。 |

本文档仅设计执行层，不改变任何 API、数据库、前端或 Agent 运行代码。




