# AI 测试与评估平台 — Harness 运行时基础设施模块设计

> ⚠️ **文档维护提示（2026-09-11）**：本文部分章节含历史实现引用（`agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除，ReAct / Plan-Solve 图已由 AgentLoop v2 取代）；当前实现与契约以 `AGENTS.md` 状态地图及本文最新修订为准。

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 运行时基础设施模块设计 |
| 版本 | V0.4.3 |
| 审查日期 | 2026-08-26 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M9 运行时基础设施（`app/runtime/`） |
| 上游权威 | Harness 需求文档 V1.4.4 §2.3/§2.4/§2.5/§7、§9；API.md V1.22 §4.1 |

> **阅读关系**：本文是 Harness §9.2「运行时基础设施」行的展开。阶段 3 落地：`PostgresSaver`（`thread_id=session_id`）只存图内部执行状态；检查点表经 Alembic 建表（红线 4）；保留策略 TTL + 会话软删除联动；对外事件与断线重放仍由 `ws_events` 承担。本模块同时解决 M3-D4 遗留待定项（`pending_events` 检查点恢复语义）。

---

## 1. 模块定位与边界

### 1.1 定位

运行时基础设施为 LangGraph 图提供**检查点持久化**与**保留清理**：`PostgresSaver` 按 `thread_id=session_id` 保存图内部执行快照，支持澄清卡 `interrupt()`/`Command(resume)`；检查点表经 Alembic 迁移建表；TTL + 会话软删除联动清理过期检查点。本模块不调模型、不持 WS 连接、不编排图拓扑。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| `PostgresSaver` 接入与 `thread_id` 映射（`checkpoint.py`） | 图拓扑与节点（M4 `app/agent/`） |
| 检查点表 Alembic 迁移建表 | 业务表迁移（`backend/api/migrations/`） |
| 检查点 TTL + 会话删除联动清理（`cleanup.py`） | 会话软删除本身（`sessions` 表 `deleted_at`） |
| `interrupt()`/`Command(resume)` 检查点读写 | 澄清卡业务逻辑（M4 `clarify.py`） |
| `pending_events` 检查点恢复语义（M3-D4） | GraphState 主体定义（M3 `state.py`） |

### 1.3 红线（继承 Harness §2.4 + §7）

- 检查点表**必须经 Alembic 迁移建表**（红线 4），不得依赖框架运行时自动建表。
- `PostgresSaver` 只存**图内部执行状态**；对外事件与断线重放仍由 `ws_events` + `last_event_id` 承担（Harness §2.5）。
- GraphState 可序列化约束（M3）——检查点内容必须 JSON 可序列化。
- `should_abort` 等回调不得入检查点（走 `RunnableConfig`，非检查点内容）。
- 共享会话并发：保留"单会话单活动回合"约束，Checkpointer 写入不得覆盖并发回合。
- 允许新增 `langgraph-checkpoint-postgres` 依赖（V1.4.1 白名单），引入时同步更新 `requirements.txt` 并在 PR 说明。
- 保留策略 TTL + 会话软删除联动，过期清理由**后台任务**执行。

---

## 2. 需求发散

### 2.1 从 Harness §2.3/§2.4 提取的需求

| 来源 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| §2.3 阶段 3 | 接入 Checkpointer（PostgresSaver，thread_id=session_id） | R-1：`checkpoint.py` `build_saver(db_url)` + `thread_id` 映射 | 阶段 3 |
| §2.4 | 检查点表经 Alembic 建表 | R-2：Alembic 迁移脚本建检查点表 | 阶段 3 |
| §2.4 | 保留策略 TTL + 会话删除联动 | R-3：`cleanup.py` TTL 清理 + 会话软删除联动 | 阶段 3 |
| §2.4 | 过期清理由后台任务执行 | R-4：`cleanup.py` 后台任务调度 | 阶段 3 |
| §2.4 | 允许 `langgraph-checkpoint-postgres` | R-5：`requirements.txt` 新增依赖 | 阶段 3 |
| §2.5 | 检查点只存图内部状态，对外事件走 ws_events | R-6：`checkpoint.py` 不写 ws 事件 | 阶段 3 |
| M3-D4 | `pending_events` 检查点恢复语义 | R-7：本模块定 `pending_events` 恢复策略 | 阶段 3 |
| §2.5 | Worker 写入 `ws_events` 的事件须实时推送到在线连接 | R-8（V0.4.1 新增）：WS 连接级**后台转发循环**——按 `last_event_id` 增量查询 `ws_events`，在连接锁内发送并推进游标；多 API 副本时改用 Redis Pub/Sub 进程外总线 | 阶段 3（阻断项） |

### 2.2 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| R-A1 | `PostgresSaver` 按 `thread_id=session_id` 保存与恢复 GraphState | 检查点往返断言 |
| R-A8（V0.4.1 新增） | Worker `push_ws` 写入 `progress`/`report`/`error` 后，在线 WS 连接实时收到，断线补发不重复、不丢事件 | 集成测试（Worker 真实写入 + 在线连接断言 + 断线重连断言） |
| R-A2 | 检查点表由 Alembic 迁移创建，非框架自动建表 | 迁移测试 |
| R-A3 | TTL 过期检查点被后台任务清理 | TTL 用例 |
| R-A4 | 会话软删除联动清理该会话检查点 | 联动断言 |
| R-A5 | `interrupt()` 写检查点，`Command(resume)` 恢复 | 澄清卡恢复断言 |
| R-A6 | `pending_events` 恢复后不重复 emit（M3-D4 解决） | 恢复断言 |
| R-A7 | `should_abort` 不出现在检查点内容 | 反射断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/runtime/
├── __init__.py        # re-export build_saver / run_cleanup / ResumeCommand
├── checkpoint.py     # 阶段 3：PostgresSaver 接入 + thread_id 映射 + pending_events 恢复策略
└── cleanup.py        # 阶段 3：检查点 TTL + 会话软删除联动后台任务

backend/api/migrations/versions/xxxx_add_checkpointer_tables.py  # 阶段 3：Alembic 建表
backend/api/requirements.txt                                      # 阶段 3：新增 langgraph-checkpoint-postgres
```

### 3.2 checkpoint.py（阶段 3 落地）

**职责**：接入 `PostgresSaver`，按 `thread_id=session_id` 保存图内部执行状态。

- `build_saver(db_url)`：构造 `PostgresSaver`，**不调用框架自动建表**（由 Alembic 建）。
- `thread_id` 映射：`config={"configurable": {"thread_id": session_id}}`，供 M4 图 `astream` 调用。
- **`pending_events` 恢复策略**（M3-D4 解决）：检查点保存的是图终态累积的 `pending_events`；恢复时**不重放**累积列表（避免重复 emit），仅恢复 `mode`/`plan`/`verdict` 等控制字段。`pending_events` 在恢复点重置为空——事件已由 `ws_events` 持久化，断线重放走 `ws_events`，不依赖检查点。
- **`should_abort` 不入检查点**：回调走 `RunnableConfig`，检查点内容只含可序列化字段。
- 不写 ws 事件（对外事件走 `ws_events`）。

### 3.3 cleanup.py（阶段 3 落地）

**职责**：检查点 TTL + 会话软删除联动清理。

- `cleanup_orphaned_checkpoints` / `cleanup_session_checkpoints`：TTL 与会话软删除联动（实现位于 `app/harness/memory/cleanup.py`）。
- **后台任务**（M9-D6 已决）：API 进程 `lifespan` 周期调度 `checkpoint_ttl_loop`（默认 6 小时），见 `app/runtime/cleanup.py`。默认 memory 引擎检查点只存在于 API 进程，不把清理塞进 Worker。
- 与 `sessions.deleted_at` 联动：`DELETE /api/sessions/{id}` 提交软删除后调用 `purge_session_checkpoints`；`thread_id` 现行约定为 `{session_id}:{turn_id}`，同时兼容裸 `session_id`。

### 3.4 Alembic 迁移（阶段 3 落地）

**职责**：检查点表经 Alembic 建表（红线 4）。

- 迁移脚本 `xxxx_add_checkpointer_tables.py`：创建 `PostgresSaver` 所需表（`checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 等，具体表名按 `langgraph-checkpoint-postgres` 版本定）。
- **不得**依赖 `PostgresSaver.setup()` 运行时自动建表。
- 迁移脚本须在 PR 内配套，`alembic upgrade head` 由 api 容器启动时执行。

### 3.5 接口签名规格（签名级）

#### 3.5.1 checkpoint.py

```python
from langgraph_checkpoint_postgres import PostgresSaver  # 独立包，非 langgraph 主包（V1.4.1 依赖白名单）
from langgraph.types import Command

def build_saver(db_url: str) -> PostgresSaver:
    """构造 PostgresSaver；不调用 setup()（由 Alembic 建表）。
    返回的 saver 供 M4 图 compile(checkpointer=saver) 使用。"""

def thread_config(session_id: str) -> dict:
    """构造 thread_id 映射：{'configurable': {'thread_id': session_id}}。
    供 graph.astream(..., config=thread_config(session_id))。
    注：`should_abort` 注入键 `configurable['abort']['should_abort']`（M4-Q2）由 M4 ws.py
    在调用 graph.astream 时合并进 config，本函数只负责 thread_id 映射。"""

def resume_command(reply: object) -> Command:
    """构造 Command(resume=reply)，供澄清卡恢复图执行。"""

def restore_state(saver: PostgresSaver, session_id: str) -> dict | None:
    """从检查点恢复 GraphState 控制字段（以 M3 `GraphState` 定义为准）：
    mode/plan/verdict 等控制字段恢复；**pending_events 重置为空**（M3-D4/M9-D3）：
    事件已由 ws_events 持久化，断线重放走 ws_events，不依赖检查点，避免重复 emit。
    恢复字段集合以 M3 `app/harness/memory/state.py` 的 GraphState 字段清单为准。"""

def assert_no_callback_in_checkpoint(state: dict) -> None:
    """断言检查点内容不含 Callable（should_abort 等）（R-A7）。"""
```

#### 3.5.2 cleanup.py

```python
def run_cleanup(db, *, ttl_seconds: int = 7 * 24 * 3600) -> int:
    """删除超过 TTL 的检查点记录；返回清理条数。"""

def cleanup_session(db, session_id: str) -> None:
    """会话软删除联动：清理该会话全部检查点（thread_id=session_id）。"""

def schedule_cleanup(*, interval_seconds: int = 6 * 3600) -> None:
    """注册后台周期清理任务（调度载体在阶段 3 实现时定，见 §7）。"""
```

#### 3.5.3 Alembic 迁移（脚本签名）

```python
# backend/api/migrations/versions/xxxx_add_checkpointer_tables.py
revision = "xxxx"
down_revision = "<当前 head>"

def upgrade() -> None:
    """创建 PostgresSaver 所需表（checkpoints/checkpoint_blobs/checkpoint_writes）。"""

def downgrade() -> None:
    """删除检查点表。"""
```

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_runtime_checkpoint.py`（含 `test_cleanup.py`）

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_saver_saves_and_restores_graph_state_by_thread_id` | R-A1 |
| `test_checkpoint_tables_created_by_alembic_not_setup` | R-A2 |
| `test_run_cleanup_removes_expired_checkpoints` | R-A3 |
| `test_cleanup_session_removes_session_checkpoints` | R-A4 |
| `test_interrupt_writes_checkpoint_resume_restores` | R-A5 |
| `test_restore_state_resets_pending_events_no_replay` | R-A6 |
| `test_checkpoint_has_no_should_abort_callback` | R-A7 |

**TDD 顺序**：先写 `test_runtime_checkpoint.py` 全红 → Alembic 迁移 → `checkpoint.py` → `cleanup.py` → 全绿。检查点往返测试用 `MemorySaver`（主包内置，无新依赖）验证 `thread_id` 恢复；PostgresSaver 集成测试用 DB 夹具。`pending_events` 恢复测试断言恢复后列表为空。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/runtime/__init__.py` | 阶段 3 | 修改（re-export） | — |
| `app/runtime/checkpoint.py` | 阶段 3 | 新增 | R-1/R-6/R-7 |
| `app/runtime/cleanup.py` | 阶段 3 | 新增 | R-3/R-4 |
| `backend/api/migrations/versions/xxxx_add_checkpointer_tables.py` | 阶段 3 | 新增 | R-2 |
| `backend/api/requirements.txt` | 阶段 3 | 修改 | R-5（新增 `langgraph-checkpoint-postgres`） |
| `backend/api/tests/test_runtime_checkpoint.py` | 阶段 3 | 新增 | R-A1~R-A7 |

---

## 6. 依赖与红线

- **上游依赖**：Harness §2.3（阶段 3）、§2.4（检查点治理）、§2.5（检查点边界）、§7；`langgraph==1.2.10` + `langgraph-checkpoint-postgres`（V1.4.1 白名单）。
- **下游被依赖**：M4（`build_saver`/`thread_config`/`resume_command` 供图接入）、M3（`pending_events` 恢复策略消费）、`ws.py`（断线重放仍走 ws_events，不依赖检查点）。
- **跨层协作**：M3（GraphState 可序列化约束）、M4（澄清卡 `interrupt()`/`Command(resume)`）、Worker/定时任务（`run_cleanup` 调度）。
- **红线**：
  - 检查点表经 Alembic 建表，禁框架自动建表；
  - 检查点只存图内部状态，对外事件走 ws_events；
  - GraphState 可序列化，回调不入检查点；
  - 单会话单活动回合，Checkpointer 不得覆盖并发回合；
  - TTL + 会话软删除联动，后台任务清理；
  - 新增依赖须在 PR 说明；
  - **Worker 事件实时转发（M9-D8）已落地**：`ws.py` `_forward_loop` 按游标增量推送 `progress`/`report`/带 `task_id` 的 `error`；查询/发送/游标推进同一把连接锁。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M9-D1 | `thread_id` 映射 | `thread_id = session_id`（`config['configurable']['thread_id']`） |
| M9-D2 | 检查点建表方式 | Alembic 迁移建表，禁 `PostgresSaver.setup()` 自动建表（红线 4） |
| M9-D3 | **M3-D4 解决：`pending_events` 检查点恢复语义** | 检查点保存累积 `pending_events`，但**恢复时重置为空**——事件已由 `ws_events` 持久化，断线重放走 `ws_events`，不依赖检查点，避免重复 emit；仅恢复 `mode`/`plan`/`verdict` 控制字段 |
| M9-D4 | `should_abort` 与检查点 | 回调走 `RunnableConfig`，不进检查点内容（R-A7 反射断言） |
| M9-D5 | 保留策略 | TTL（默认 7 天）+ 会话软删除联动（`cleanup_session`） |
| M9-D6 | 后台清理调度载体 | **已决（V0.4.3）**：API 进程 `lifespan` 周期任务（`app/runtime/cleanup.py` `checkpoint_ttl_loop`，默认 6 小时）。默认 memory 引擎只能在 API 进程内清理；postgres 引擎同库删除幂等。不新增 Worker 进程、不改默认 Checkpointer 为 postgres |
| M9-D7 | 新增依赖 | `langgraph-checkpoint-postgres`（V1.4.1 白名单），PR 内说明 |
| M9-D8（V0.4.1 新增 / V0.4.2 落地） | **Worker 事件实时转发** | WS 连接生命周期内启动 `_forward_loop`：按游标增量查询 `ws_events`，在连接级发送锁内发送并推进游标；只转发 Worker 直产（`progress`/`report`、带 `task_id` 的 `error`）。多 API 副本时改 Redis Pub/Sub 进程外总线 |

> **M9-D6 已闭环（V0.4.3）**：后台清理调度载体定为 API 进程 lifespan 周期任务。M3-D4 已在本模块解决（D3）。

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.22 §4.1 为唯一真理。M9 对前端**基本无感**：`PostgresSaver` 按 `thread_id=session_id` 只存图内部执行状态，对外事件与断线重放仍由 `ws_events` + `last_event_id` 承担（M9 §3.2）。前端现有 `ws.ts` 的 `last_event_id` 补发机制已足够，无需感知 `thread_id`。前端只需联调验证澄清卡 `interrupt()` 期间断线重连后能通过 `ws_events` 回放看到澄清卡。

### 8.1 对应前端验证任务

| M9 能力 | 前端影响 | 前端文件 | 对接契约 | 落地阶段 | 验收点 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `checkpoint.py` `PostgresSaver`（`thread_id=session_id`） | 无感（前端不感知 thread_id） | — | M9 §3.2 + API.md §4.1 | 阶段 3 | `last_event_id` 补发仍生效，无需改动 |
| `interrupt()`/`Command(resume)`（澄清卡暂停/恢复） | 澄清卡断线重连回放 | `api/ws.ts`；`views/Agent.vue` `handleWsEvent` `clarify` 分支 | API.md §4.3 `clarify`（V1.22）+ M9 §3.5.1 | 阶段 3 | 澄清卡 `interrupt()` 期间断线重连后，`ws_events` 回放重建 ClarifyCard UI 状态 |
| `pending_events` 检查点恢复重置为空 | 无感（事件走 ws_events 不重发） | — | M9 §3.2（M3-D4 裁决） | 阶段 3 | 重连后无重复事件，前端 `event_id` 单调去重仍生效 |
| `cleanup.py` TTL + 软删除联动 | 会话失效后 4404 | `api/ws.ts` `onclose` 4404 分支 | API.md §4.1 | 阶段 3 | 会话被清理后重连收到 4404，前端停止重连 + 清理 UI |

### 8.2 前端验收要点

- **断线重连不依赖 thread_id**：前端只靠 `last_event_id`，不读取/传递 `thread_id`，与 M9 §3.2 一致。
- **澄清卡回放**：`interrupt()` 暂停期间断线重连，前端从 `ws_events` 回放 `clarify` 事件重建 ClarifyCard，用户仍可 `clarify_reply` 恢复。
- **4404 清理**：会话被 `cleanup.py` 清理后，前端 4404 分支清理 `currentSessionId` 并跳转会话列表。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-运行时基础设施.md` | 新增 V0.3 → 修订 V0.4 → 修订 V0.4.1 → 修订 V0.4.2 → **修订 V0.4.3** | V0.3–V0.4.1 为设计与裁决；V0.4.2 记录 M9-D8 落地；**V0.4.3 闭环 M9-D6**：API lifespan TTL + 会话软删除按 `{session_id}:` 前缀清理检查点。 |
| `backend/api/app/harness/memory/checkpoint.py` | 修改 | 内存检查点进程内共享；默认 Checkpointer 单例 |
| `backend/api/app/harness/memory/cleanup.py` | 修改 | `cleanup_session_checkpoints` |
| `backend/api/app/runtime/cleanup.py` | 新增 | TTL 后台循环 |
| `backend/api/app/routers/sessions.py` | 修改 | 软删除联动 |
| `backend/api/app/main.py` | 修改 | lifespan 挂载 TTL |
| `backend/api/tests/test_checkpointer.py` | 修改 | R-A4 会话前缀清理 |
| `backend/api/tests/test_runtime_checkpoint.py` | 新增 | R-A3 后台循环可取消 |

