# AI 测试与评估平台 — Harness 跨层安全模块设计

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 跨层安全模块设计 |
| 版本 | V0.5.0 |
| 审查日期 | 2026-08-24 |
| 文档性质 | 模块设计说明书（需求发散 + 架构设计 + 接口签名） |
| 适用模块 | M8 跨层安全（`app/harness/security/`） |
| 上游权威 | Harness 需求文档 V1.5.0 §4.2/§4.4/§4.5/§5.2.1/§7；API.md V1.22 §4.1/§4.4/§5；PRD §5.1.2 |

> **阅读关系**：本文是 Harness §9.2「跨层安全」行的展开。`secrets.py` 递归脱敏供 M2/M5/M6 调用（CX-3）；`auth.py` 确认卡 owner 校验 + 行锁供 M4 `confirm.py` 调用（OR-8）。本层不含用户鉴权（通用 `security.py`）与 WS 短票（`ws.py`）。

---

## 1. 模块定位与边界

### 1.1 定位

跨层安全提供 Harness 内的**脱敏**与**确认卡授权**两类横切能力：递归脱敏把工具结果/日志中的密钥类字段抹除；确认卡 owner 校验 + 行锁保证共享会话中只有卡作者可确认/拒绝/提交 patch。本层不调模型、不持 WS 连接、不产生副作用（脱敏是纯函数，owner 校验是只读 + 行锁）。

### 1.2 边界

| 在范围内 | 不在范围内 |
| :--- | :--- |
| 递归脱敏（`secrets.py`，CX-3） | 用户登录鉴权（通用 `security.py`） |
| 确认卡 owner 校验 + 行锁（`auth.py`，OR-8） | WS 短票鉴权（`ws.py:_consume_ws_ticket`） |
| 脱敏键集合管理 | 会话可见性（`session_access.py`） |
| owner 校验返回值 | 确认回执事务（M4 `confirm.py`） |

### 1.3 红线（继承 Harness §5.2.1 + §7）

- API Key/Cookie/密码/JWT Secret **严禁打印、回显或写入日志/事件**（§5.2.1）。
- 脱敏递归覆盖 `api_key`/`token`/`password`/`secret`/`cookie` 键（CX-3）。
- 共享会话确认卡只允许 `pending_confirm_author_id` 对应成员确认/拒绝/提交 patch（PRD §5.1.2、API.md §4.4）。
- owner 校验失败抛 `AppError`（`UNAUTHORIZED`/`VALIDATION`），不泄露具体原因给前端。
- 不私自扩充对外字段。

---

## 2. 需求发散

### 2.1 从 Harness 提取的需求

| 来源 | 需求 | 发散为本模块子需求 | 落地阶段 |
| :--- | :--- | :--- | :--- |
| §4.2 CX-3 | 工具结果为脱敏 observation 摘要 | S-1：`secrets.py` `redact(obj)` 递归脱敏 | 阶段 2 |
| §5.2.1 | 密钥不得打印/回显/写日志 | S-2：`redact_for_log(obj)` 日志专用脱敏 | 阶段 2 |
| §4.4 OR-8 | `task.create` 只在 `confirm_ack.ok=true` 且 patch 合并后二次校验通过时发生 | S-3：`auth.py` `assert_confirm_owner(db, session_id, user_id)` 行锁校验 | 阶段 4 |
| PRD §5.1.2 | 共享会话确认卡只允许卡作者操作 | S-4：`auth.py` `lock_pending_confirm(db, session_id)` 行锁读 | 阶段 4 |

### 2.2 脱敏键集合发散

| 键名模式（大小写不敏感） | 脱敏方式 |
| :--- | :--- |
| `api_key`/`apikey` | 保留前 4 + `***` |
| `token`/`access_token`/`refresh_token` | 保留前 4 + `***` |
| `password`/`passwd`/`pwd` | 全量 `***` |
| `secret`/`client_secret` | 全量 `***` |
| `cookie`/`set-cookie` | 全量 `***` |

### 2.3 验收标准（TDD 先行）

| 编号 | 验收点 | 测试形态 |
| :--- | :--- | :--- |
| S-A1 | 递归脱敏覆盖 dict/list/嵌套结构，命中键被抹除 | 脱敏断言 |
| S-A2 | 日志脱敏不含原始密钥 | 日志断言 |
| S-A3 | 非 owner 确认被拒绝（`UNAUTHORIZED`） | owner 断言 |
| S-A4 | 行锁读 `pending_confirm`，并发确认只成功一次 | 并发断言 |
| S-A5 | owner 校验失败不泄露具体原因 | 文案断言 |

---

## 3. 架构设计

### 3.1 文件结构

```text
app/harness/security/
├── __init__.py    # re-export redact / redact_for_log / assert_confirm_owner / lock_pending_confirm
├── secrets.py    # 阶段 2：递归脱敏（CX-3 + §5.2.1）
└── auth.py       # 阶段 4：确认卡 owner 校验 + 行锁（OR-8）
```

### 3.2 secrets.py（阶段 2 落地）

**职责**：递归脱敏，供 M2（observation 注入前）、M5（dispatch 日志）、M6（归一）、`ws.py`（事件 payload）调用。

- `redact(obj)`：递归遍历 dict/list，命中 §2.2 键集合的值按方式抹除；非密钥键原样保留。
- `redact_for_log(obj)`：日志专用，更严格（所有疑似密钥全量 `***`），供 `agent_trace`/`logger` 调用。
- 纯函数，无副作用，可单测。

### 3.3 auth.py（阶段 4 落地）

**职责**：确认卡 owner 校验 + 行锁，供 M4 `confirm.py:handle_confirm_ack` 调用。

- `lock_pending_confirm(db, session_id)`：`SELECT ... FOR UPDATE` 行锁读 `sessions.pending_confirm` + `pending_confirm_author_id`，返回 `PendingConfirm`。**唯一行锁入口**。
- `assert_confirm_owner(pending, user_id)`：复用已取得行锁的 `PendingConfirm` 做 owner 校验（不再单独行锁）；非 owner 抛 `AppError(UNAUTHORIZED, "无权操作确认卡")`（不泄露"非作者"具体原因）。
- `assert_no_concurrent_confirm(pending)`：复用同一 `PendingConfirm` 检测卡是否已被消费。
- 行锁保证共享会话并发确认只成功一次（第二个抛 `CONCURRENCY`）；M4 `handle_confirm_ack` 全程同一事务单次行锁。

### 3.4 接口签名规格（签名级）

#### 3.4.1 secrets.py

```python
from typing import Any

# 脱敏键集合（大小写不敏感匹配）
REDACT_KEYS: frozenset[str] = frozenset(
    {"api_key", "apikey", "token", "access_token", "refresh_token",
     "password", "passwd", "pwd", "secret", "client_secret", "cookie", "set-cookie"}
)

def redact(obj: Any) -> Any:
    """递归脱敏（CX-3）：遍历 dict/list，命中 REDACT_KEYS 的值按方式抹除。
    纯函数，返回脱敏后的副本。"""

def redact_for_log(obj: Any) -> Any:
    """日志专用脱敏（§5.2.1）：更严格，所有疑似密钥全量 '***'。
    供 agent_trace / logger 调用。"""

def is_sensitive_key(key: str) -> bool:
    """判定键是否敏感（大小写不敏感）。"""

def mask_partial(value: str, keep: int = 4) -> str:
    """部分保留脱敏：保留前 keep 字符 + '***'（用于 api_key/token）。"""

def mask_full(_value: str) -> str:
    """全量脱敏：返回 '***'（用于 password/secret/cookie）。"""
```

#### 3.4.2 auth.py

```python
from dataclasses import dataclass
from app.errors import AppError, ErrorCode

@dataclass(frozen=True, slots=True)
class PendingConfirm:
    """行锁读出的确认卡状态。"""
    pending: dict | None              # sessions.pending_confirm JSONB
    author_id: str | None             # pending_confirm_author_id

def lock_pending_confirm(db, session_id: str) -> PendingConfirm:
    """SELECT ... FOR UPDATE 行锁读 sessions.pending_confirm + author_id。
    返回 PendingConfirm；无卡时 pending=None。
    **唯一行锁入口**：M4 confirm.py 应先调本函数取得行锁 + PendingConfirm，
    再在同一事务内做 owner 校验与并发检测，避免重复锁。"""

def assert_confirm_owner(pending: PendingConfirm, user_id: str) -> None:
    """owner 校验（OR-8）；**复用已取得的行锁 PendingConfirm，不再单独行锁**：
    无卡 → AppError(VALIDATION, "无待确认卡")；
    非 owner → AppError(UNAUTHORIZED, "无权操作确认卡")（不泄露具体原因）。"""

def assert_no_concurrent_confirm(pending: PendingConfirm) -> None:
    """并发确认检测；**复用同一事务内已取得的行锁 PendingConfirm**：
    若卡已被消费 → AppError(CONCURRENCY, "确认卡已被处理")。"""
```

> **调用顺序约定**（M4 `handle_confirm_ack`）：`lock_pending_confirm`（取行锁）→ `assert_confirm_owner`（owner 校验，复用 pending）→ `assert_no_concurrent_confirm`（并发检测，复用 pending）→ patch 合并 → 二次校验 → task.create。全程同一 DB 事务，单次行锁。

---

## 4. 测试策略（TDD）

测试文件：`backend/api/tests/test_harness_security.py`（含 `test_redact.py`/`test_confirm_auth.py`）

| 测试用例 | 覆盖验收 |
| :--- | :--- |
| `test_redact_nested_dict_keys_masked` | S-A1 |
| `test_redact_list_of_dicts_masked` | S-A1 |
| `test_redact_for_log_no_raw_secret` | S-A2 |
| `test_assert_confirm_owner_rejects_non_owner` | S-A3 |
| `test_lock_pending_confirm_concurrent_one_succeeds` | S-A4 |
| `test_owner_reject_message_does_not_leak_reason` | S-A5 |

**TDD 顺序**：先写 `test_redact.py`（阶段 2）全红 → 实现 `secrets.py` → 全绿；阶段 4 补 `test_confirm_auth.py` + `auth.py`。`auth.py` 测试需 DB 夹具 + 并发模拟。

---

## 5. 文件清单（引用 Harness §9.3）

| 文件 | 阶段 | 操作 | 对应需求 |
| :--- | :--- | :--- | :--- |
| `app/harness/security/__init__.py` | 阶段 2 | 修改（re-export） | — |
| `app/harness/security/secrets.py` | 阶段 2 | 新增 | CX-3、§5.2.1、S-1/S-2 |
| `app/harness/security/auth.py` | 阶段 4 | 新增 | OR-8、S-3/S-4 |
| `backend/api/tests/test_harness_security.py` | 阶段 2/4 | 新增 | S-A1~S-A5 |

---

## 6. 依赖与红线

- **上游依赖**：Harness §4.2（CX-3）、§4.4（OR-8）、§5.2.1（密钥保护）、§7；API.md §4.4；PRD §5.1.2。
- **下游被依赖**：M2（`redact` 供 observation 注入前脱敏）、M5（`redact_for_log` 供 dispatch 日志）、M6（`redact` 供归一）、M4（`assert_confirm_owner`/`lock_pending_confirm` 供 `confirm.py`）、`ws.py`（`redact` 供事件 payload）。
- **跨层协作**：M3（`sessions` 表行锁）、通用 `security.py`（用户鉴权，不重叠）。
- **红线**：
  - 密钥不打印/回显/写日志；
  - 脱敏递归覆盖 5 类键；
  - 确认卡只 owner 可操作；
  - owner 校验失败不泄露原因；
  - 行锁保证并发安全。

---

## 7. 已决裁决

| 编号 | 问题 | 裁决 |
| :--- | :--- | :--- |
| M8-D1 | 脱敏粒度 | `redact` 部分保留（api_key/token 保留前 4），`redact_for_log` 全量 `***`（更严格） |
| M8-D2 | owner 校验失败码 | 非 owner → `UNAUTHORIZED`；无卡 → `VALIDATION`；并发 → `CONCURRENCY` |
| M8-D3 | owner 校验文案 | 不泄露"非作者"具体原因，统一"无权操作确认卡" |
| M8-D4 | 行锁方式 | `SELECT ... FOR UPDATE` 行锁读 `sessions.pending_confirm` |
| M8-D5 | 脱敏键集合 | 5 类（api_key/token/password/secret/cookie）大小写不敏感 |
| M8-D6（V0.5.0） | bash 沙箱边界 | 阶段 3 开放通用 bash：**bwrap 进程级沙箱**（`sandbox.py`）——`--unshare-user/net/pid/ipc/uts` 命名空间隔离、最小只读 bind（`/usr`/`/bin`/`/sbin`/`/lib*`/`/etc`，**不暴露** `/app`、`/run/config/.env`、`/data` 下其他会话工作区）、`--bind` 会话工作区到 `/work`（唯一可写面）、`--tmpfs /tmp /run`、`--clearenv` + 最小 PATH；`ulimit` 内存（256MB）/进程数（32）/CPU（10s）+ 墙钟超时（15s）`killpg` 整树清理（`--die-with-parent`）。命令黑名单为**纵深防御**；bwrap 不可用/引擎 `off` 时 **fail-closed（VALIDATION）**，禁止降级为裸 subprocess。威胁模型：防跨会话/宿主逃逸与资源耗尽（fork 炸弹/内存），不防会话内自毁（工作区文件由模型操作）。部署依赖 api 容器 `security_opt: seccomp:unconfined`；更严格的自定义 seccomp profile 列为后续项 |

---

## 8. 前端联调

> 本模块前端联调由 **陈东超** 独立负责，契约以 API.md V1.22 §4.1/§4.4 为唯一真理。M8 影响前端的两个点：`auth.py` 确认卡 owner 校验（前端 `canConfirmItem` 预校验 + 服务端 `UNAUTHORIZED`/`CONCURRENCY` 拒绝）与 WS 关闭码 4401/4404（前端重连策略）；`secrets.py` 脱敏标记经 M2/M5 流到前端 ToolCard。前端不臆造字段，发现契约缺失先回写 API.md 再实现。

### 8.1 对应前端组件与任务

| M8 文件 | 产出 | 前端渲染/处理 | 前端文件 | 对接契约 | 落地阶段 | 验收点 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `auth.py` `assert_confirm_owner` | `error(UNAUTHORIZED)`（非 owner） | ErrorStrip + Toast | `views/Agent.vue` `canConfirmItem`；`api/types.ts` `ERROR_MESSAGES` | API.md §1.3 + M8 §3.4.2 | 阶段 4 | 客户端预校验 + 服务端拒绝 fallback 文案中性化（「无权操作确认卡」由后端 `message` 透传） |
| `auth.py` `assert_no_concurrent_confirm` | `error(CONCURRENCY)`（并发确认） | ErrorStrip + Toast | `api/types.ts` `ERROR_MESSAGES` | API.md §1.3 + M8 §3.4.2 | 阶段 4 | 场景化文案「确认卡已被他人处理」，不与「平台并发已满」混淆 |
| `auth.py` `lock_pending_confirm` | 确认卡行锁（后端内部） | 确认卡按钮禁用 | `views/Agent.vue` | API.md §4.4 | 阶段 4 | 会话有非终态任务时旧卡确认按钮禁用 |
| `secrets.py` `redact` | `Observation.redacted=true` | ToolCard「已脱敏」徽标 | `components/agent/ToolCard.vue` | API.md §4.3 `tool_result.redacted`（V1.22）+ M8 §3.4.1 | 阶段 2 | `redacted=true` 渲染徽标，不静默丢弃 |
| WS 关闭码 4401/4404 | 短票过期 / 会话不存在 | 重连策略 + UI 清理 | `api/ws.ts` `onclose`；`views/Agent.vue` `onClosed` | API.md §4.1 | 全阶段 | 4401 显式分支 + Toast「短票过期，重新连接中」+ 重新领票；4404 停止重连 + `currentSessionId=null` + 跳转会话列表 |

### 8.2 前端验收要点

- **owner 校验双层**：客户端 `canConfirmItem` 预校验（基于 `confirm_author.id`）+ 服务端 `assert_confirm_owner` 兜底，前端提交 patch 必须剥离 `confirm_author` 元数据。
- **关闭码显式处理**：`ws.ts` `onclose` 加 4401/4404 显式分支，4401 重新领票，4404 清理 UI 状态。
- **错误码文案中性化**：`UNAUTHORIZED`/`CONCURRENCY` fallback 改中性，场景文案由后端 `message` 透传，前端不硬编码场景文案。

## 9. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-跨层安全.md` | 新增 V0.3 → 修订 V0.4 → 修订 V0.4.1 | V0.3 M8 跨层安全模块设计：定义递归脱敏（`redact`/`redact_for_log`，5 类键）与确认卡 owner 校验 + 行锁（`assert_confirm_owner`/`lock_pending_confirm`）；含接口签名级与 TDD 验收；明确与通用 `security.py`（用户鉴权）的边界；V0.4 对齐 API.md V1.21：新增 §8「前端联调」章节列出 auth/secrets 对应的前端处理、契约与验收点（含 owner 校验双层、4401/4404 关闭码显式处理、错误码文案中性化）；V0.4.1 契约收敛版：统一上游权威与 §8 契约为 API.md V1.22；补充现状标记（本层当前冻结未实现，`app/harness/security/` 为空包边界）。 |
| `docs/AI测试与评估平台-Harness-跨层安全.md` | 修订 V0.5.0 | V0.5.0 bwrap 沙箱配套：§7 新增 M8-D6「bash 沙箱边界」裁决（bwrap 进程级隔离、fail-closed、部署依赖 seccomp:unconfined、威胁模型）；上游权威同步 Harness 需求文档 V1.5.0。 |

本文档仅设计跨层安全，不改变任何 API、数据库、前端或 Agent 运行代码。

