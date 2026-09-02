# AI 测试与评估平台 — AI Agent 行为规范与工程指南 (AGENTS.md)

> **最高指示**：本文件是面向所有参与本项目的 **AI Agent 与开发者** 的最高行动指南。在编写或修改代码前，**必须严格遵守本文档所规定的架构边界、开发契约与行为红线**。
> 版本：V1.2 ｜ 审查日期：2026-09-02（V1.6.0 Agent 骨架化：纯对话图，范式/思考链/确认卡/澄清卡/斜杠已移除）

---

## 1. 项目简介与架构 (Overview & Architecture)

- **定位**：面向**单一研发/评测团队**的内部平台，利用 **AI Agent（WebSocket + 内部 MCP Host）** 自动化完成大模型 **基准评测（Benchmark）** 与 **知识库评测（RAG）**。
- **核心逻辑**：对话驱动任务入队 -> 质量评测成功 (`succeeded`) 且勾选压测后 -> 自动派生执行共享压测（**先评后压**）。

### 1.1 服务拓扑与网络端点
| 服务名称 | 容器标识 | 端口 | 访问方式 / 说明 |
| :--- | :--- | :--- | :--- |
| **Web 前端** | `web` | `80` | `http://47.119.132.83/`（Nginx 反代 `/api` 与 `/ws`） |
| **API 服务** | `api` | `8000` | `http://47.119.132.83:8000/docs`（FastAPI + Swagger + 短 MCP） |
| **Worker 引擎** | `worker` | - | 容器内部网络通信，轮询 PG 任务队列执行耗时评测 |
| **数据库** | `postgres` | `5432` | PostgreSQL 16 关系数据库（pgvector 镜像，含向量扩展；持久卷 `pgdata`） |
| **缓存/记忆** | `redis` | - | 容器内部网络通信；Harness 记忆层短期回合状态与幂等键（持久卷 `redisdata`） |
| **RAG 引擎** | `lightrag` | `9621` | LightRAG 混合检索与图谱评测服务 |
| **压测引擎** | `stress` | `19090` | go-stress-testing 发压引擎，暴露 `/metrics` |

> 初始管理员：`admin / admin123`（由 `.env` 中 `BOOTSTRAP_ADMIN_PASSWORD` 注入）。

### 1.2 核心架构流
```text
浏览器 Vue 3 (Naive UI)
  │── WS: /ws/agent?ticket= ──► FastAPI Agent Host (纯对话流式生成 + 任务事件桥接)
  │── REST: /api/* ───────────► FastAPI REST API (认证 / 协议档 / 数据集 / 报告)
                                        │
                                        ▼
                                  PostgreSQL 16 (tasks 状态机 / task_events / 数据集)
                                        │
                                        ▼
                                  Python Worker (异步执行：三协议评测 / LightRAG / 派生压测)
```

> 骨架化说明（V1.6.0）：Agent 图已收敛为单节点纯对话
> `START → chat_stream → END`；多范式路由（direct/chat/react/plan_solve）、
> ReAct 思考链、reflect 反思、思考流、澄清卡、确认卡、短工具调用与斜杠命令
> 已全部移除，仅保留消息 → LLM 直接生成回复 → `assistant_message` +
> `response.completed` 的最小链路。

### 1.3 权威文档与冲突裁决
1. **L0 产品权威**：[`docs/AI测试与评估平台-PRD.md`](docs/AI测试与评估平台-PRD.md)（功能范围、状态机、确认卡字段唯一真理）；
2. **L1 接口契约**：[`docs/AI测试与评估平台-API.md`](docs/AI测试与评估平台-API.md) **V1.4+**（REST/WS 路径、JSON 契约唯一真理）；
3. **Agent 子系统**：[`docs/AI测试与评估平台-Agent开发文档.md`](docs/AI测试与评估平台-Agent开发文档.md)（骨架化纯对话、上下文算法、长任务门禁）；**JSON 字段名与路径仍以 API.md 为准**；
4. **裁决铁律**：代码/计划与 PRD 冲突以 PRD 为准；接口与 API.md 冲突以 API.md 为准。禁止私自扩充产品范围（Agent 说明书新增路径必须先回写 API.md）。

### 1.4 文档命名与更新规范 (Documentation Conventions)
1. **统一文件命名**：所有设计、契约与技术方案文档统一归档于 `docs/` 目录，格式严格遵循 `docs/AI测试与评估平台-<模块或主题>.md`（如 `docs/AI测试与评估平台-Agent大模型接入与耗时技术方案.md`），严禁无前缀或随意自创命名；
2. **文档闭环更新**：功能迭代或契约演进后，必须在对应技术文档末尾同步追加「修改代码文件与作用清单」，并在文档头部更新版本号（如 `V1.1`、`V1.2`）与审查日期；
3. **提交与分支规范**：纯文档变更使用 `docs(<scope>): <中文描述>` 格式提交，重要文档改造建议拉出 `docs/<scope>-简述` 分支。

### 1.5 运行时数据流与实现状态地图

**任务状态机与 Worker 领取**（`tasks` 表 `queued→running→succeeded/failed/cancelled`）：
- Worker 主循环（`backend/worker/app/main.py`）用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取 `queued` 任务，受 `settings.max_running_tasks` 并发闸门约束（默认 3）；
- `uq_tasks_active_session` 部分唯一索引在创建侧保证**同一会话内任务串行**（防止确认卡重复提交）；
- 执行器（benchmark / testcase）自管数据库 Session，主循环只负责领取与终态兜底；**禁止跨 Session 传 ORM 对象**（会触发 `InvalidRequestError`，导致任务永久卡 `running`）。

**WS 事件机制**（`backend/api/app/routers/ws.py` + `session_connections.py`）：
- 持久事件统一写入 `ws_events` 表并带公共头 `{event, session_id, task_id, event_id, ts, payload}`；
- `_emit` 在连接锁内完成「取号 → 落库 → 发送 → 推进游标」；`_forward_loop` 后台循环按游标增量把 **Worker 进程外**写入的事件推送到当前连接；
- 断线重连按 `last_event_id` 补发；流式帧（`assistant_delta`）与心跳 `pong` 为瞬态帧，**不落库、不占事件号**（骨架化后无 `stream=think`）；
- 关闭码 `4401`=重新领票，`4404`=会话不存在/共享被收回。

**Agent Harness 并发模型**（`routers/ws.py` + `agent/graph.py`）：
- 收包循环**不得 await 整轮 Harness**，`_handle_user_message` 必须丢 `asyncio.Task` 执行；
- 会话级 abort 是进程内 dict（单副本或网关按 `session_id` 粘性路由的前提）；
- 骨架化后 Agent 为单节点纯对话图（`graph.py` + `routing.py` 的 `chat_stream_node`），
  不再有多范式调度与思考链；`/stop` 即时中断与 `cancel_task` 保留在收包循环。

**模型单一事实源**：`backend/shared/models.py` 由 api 与 worker 共用（`api/app/models.py` 仅为 re-export）；改表必须 `alembic revision --autogenerate`，禁止双副本漂移。

**实现状态地图（真实现 vs Mock）**：

| 模块 | 状态 | 位置 |
| :--- | :--- | :--- |
| benchmark 基准评测 | 真实执行器（三协议调用、规则评分、预算熔断、断点续跑） | `backend/worker/app/benchmark.py` |
| testcase 用例生成 | 真实执行器（六策略 LLM 生成、72h 确认超时扫描） | `backend/worker/app/testcase.py` |
| rag 知识库评测 | **必须失败**：LightRAG 未接入，禁止 mock `succeeded` | `backend/worker/app/main.py` |
| stress 压测 | 骨架 mock（M4 替换） | `backend/worker/app/main.py` |
| Agent 图 | **骨架化**：单节点纯对话（`START → chat_stream → END`），无工具/确认卡/澄清卡/斜杠 | `backend/api/app/agent/graph.py`、`routing.py` |
| bash 工具 | **真实 bwrap 沙箱**（阶段 3）：一次性进程级沙箱（无网络、会话工作区唯一可写、ulimit 资源限制、超时整树清理）+ 黑名单纵深防御；bwrap 不可用/引擎 `off` 时 fail-closed（骨架化后 Agent 不再调用，保留供未来扩展） | `backend/api/app/harness/execution/sandbox.py`、`dispatch.py`、`registry.py` |

---

## 2. 项目结构 (Project Structure)

```
ai-eval-platform/
├── backend/
│   ├── api/                     # FastAPI 主服务（路由、认证、数据模型、短 MCP）
│   │   ├── app/                 # 核心代码（routers/, models.py, schemas.py, errors.py, security.py, agent/）
│   │   ├── migrations/          # Alembic 数据库迁移版本脚本
│   │   └── tests/               # Pytest 自动化测试
│   ├── worker/                  # 异步任务 Worker（轮询任务队列、三协议适配、评测执行）
│   ├── lightrag/                # LightRAG 服务组件
│   └── stress/                  # go-stress-testing 压测组件
├── frontend/                    # Vue 3 前端工程（Naive UI, Pinia, Vue Router, Vite）
│   └── src/                     # 源码（api/, layouts/, router/, stores/, views/, naive-theme.ts）
├── deploy/                      # 部署脚本（server-setup.sh 服务器初始化, deploy.sh 同步部署）
├── docs/                        # PRD、API 契约、原型设计与开发计划
├── Web-Prototype/               # 静态 HTML 原型（视觉与交互参考）
└── docker-compose.yml           # 全栈六件套容器编排文件
```

### 2.1 常用开发命令（工作目录 = 命令所在目录）

后端 API（`backend/api/`）：
- 安装依赖：`pip install -r requirements.txt -r requirements-dev.txt`
- Lint：`ruff check . ../shared`（CI 会连同 `backend/shared` 一起检查）
- 全部测试：`pytest`
- 单个文件：`pytest tests/test_ws_agent.py`
- 单个用例：`pytest tests/test_ws_agent.py -k "confirm_ack"`
- 生成迁移：`alembic revision --autogenerate -m "中文描述"`
- 应用迁移：`alembic upgrade head`（api 容器启动时自动执行）

后端 Worker（`backend/worker/`）：
- 测试：`PYTHONPATH=.:.. pytest`（依赖共享包 `backend/shared`；Windows 用 `set PYTHONPATH=.;..`）

前端（`frontend/`）：
- 开发热更：`npm run dev`（http://localhost:5173，`/api` 与 `/ws` 代理到 :8000）
- 类型检查：`npm run typecheck`（`vue-tsc --noEmit`；注意 `npm run build` **不包含**类型检查）
- 构建：`npm run build`

全栈一键启动：`docker compose up -d --build`（前端 http://localhost，API http://localhost:8000/api/health，Swagger http://localhost:8000/docs）

---

## 3. Git 提交与分支规范 (Git Conventions)

采用 **[Conventional Commits](https://www.conventionalcommits.org/)** 规范。**提交描述（Subject 与 Body）必须使用中文**。  
提交作者身份由宿主机当前的 Git 配置（`git config`）或 GitHub CLI 自动决定。

### 3.1 模块开发必须开分支（强制）

`main` 只接受已审查的合并，**禁止**在 `main` 上直接开发模块功能、修缺陷或改契约。AI Agent 写代码前必须确认当前分支**不是** `main` / `master`；若在主干上，先开分支再改。

```text
main（保护，仅 PR 合入）
  └── feat/agent-harness
  └── feat/web-confirm-card
  └── fix/worker-progress
  └── docs/api-v1.4
         │
         ▼
      Pull Request → CI 通过 → 合并 main → CD 部署生产
```

**分支命名**：`<type>/<scope>-<短横线英文或拼音简述>`，type/scope 与提交规范同一套。

| 场景 | 分支示例 | 说明 |
| :--- | :--- | :--- |
| Agent 子系统 | `feat/agent-harness` | 对话、Harness、斜杠、WS |
| API / 短 MCP | `feat/api-slash-commands` | FastAPI 路由、契约落地 |
| 前端工作台 | `feat/web-context-meter` | Vue 页面与组件 |
| Worker / 压测 | `fix/worker-rag-stub` | 长任务、进度、LightRAG 占位 |
| 数据集 / 用例 | `feat/dataset-ai-generate` | 页面 AI 候选 |
| 文档 / 契约 | `docs/api-agent-prefs` | 仅文档也可开分支，避免和功能混在 main |

规则：

1. **一模块一分支**（或一 Task 一分支）。Agent、前端、Worker 不要堆在同一条长期分支上。  
2. 从最新 `origin/main` 拉出：`git fetch origin && git checkout -b feat/agent-xxx origin/main`。  
3. 推送功能分支：`git push -u origin HEAD`。合入用 **Pull Request**，禁止把功能分支 `push --force` 到 `main`。  
4. **只有 `main` 触发生产 CD**。功能分支只跑 CI，不部署 `47.119.132.83`。  
5. 允许直接在 `main` 的例外：**无代码、无迁移**的错别字级文档（仍建议开 `docs/` 分支）。契约变更（API.md / PRD / Agent 说明书）按模块开 `docs/` 分支。  
6. 合并后删除远程功能分支，不在本地长期占用 `main` 做开发。

### 3.2 提交信息

- **提交格式**：`<type>(<scope>): <中文简述>`
- **常见 Type**：`feat`（新功能）、`fix`（修缺陷）、`docs`（文档）、`style`（格式）、`refactor`（重构）、`test`（测试）、`ci`（CI/CD）、`chore`（杂项）。
- **常用 Scope**：`api`、`worker`、`web`、`mcp`、`rag`、`stress`、`auth`、`dataset`、`profile`、`task`、`report`、`agent`、`deploy`。
- **提交前强制门禁**：提交代码前**必须在本地先完成构建与自检**，确保 0 错误后方可执行 `git commit`：后端 `cd backend/api && ruff check . ../shared && pytest`、`cd backend/worker && PYTHONPATH=.:.. pytest`；前端 `cd frontend && npm run typecheck && npm run build`。
- **中文示例**：
  - `feat(api): 新增 WebSocket 短票鉴权接口`
  - `fix(worker): 修复大模型裁判调用超时重试逻辑`
  - `docs(agent): 更新自动部署排查指南与提交规范`

---

## 4. 自动部署与 CI/CD (CI/CD & DevOps)

```text
功能分支 Push ──► GitHub Actions CI（Ruff + Pytest；不部署）
合并 PR 到 main ──► GitHub Actions CI
                         │ (通过)
                         ▼
                    GitHub Actions CD (SSH) ──► 服务器 /opt/ai-eval-platform
                                                    │
                                                    ▼
                                            deploy.sh: git reset --hard && docker compose build & up -d
```

**生产只跟 `main`。** 功能分支、个人 fork、未合并 PR 不得触发对 `47.119.132.83` 的 CD。

### 4.1 Secrets 配置清单
- `SSH_HOST`：`47.119.132.83`（纯 IP，严禁带 `http://`）
- `SSH_PORT`：`22`（**必须是 22**，切勿误填 Web 的 80/8000）
- `SSH_USER`：`deploy`
- `SSH_PRIVATE_KEY`：服务器 `/home/deploy/.ssh/id_ed25519` 的完整私钥（含首尾标记）

### 4.2 部署与构建失败排查 SOP
1. **CI 失败**：本地进入 `backend/api/` 执行 `ruff check --fix .` 与 `pytest`；进入 `frontend/` 执行 `npm run build`。
2. **CD SSH 握手失败 (`connection reset by peer`)**：检查 `SSH_PORT` 是否误填为 80/8000（必须为 22）；确认云服务器安全组 22 端口对 `0.0.0.0/0` 放行。
3. **Docker 容器残留 (`No such container`)**：`deploy.sh` 会自动调用 `docker rm -f` 强力清理并自愈拉起。手动修复命令：
   ```bash
   docker rm -f $(docker ps -a -q --filter "name=ai-eval-platform") 2>/dev/null || true
   sudo -u deploy bash /opt/ai-eval-platform/deploy/deploy.sh
   ```
4. **容器状态异常 / 端口占用**：在服务器执行 `netstat -tlpn | grep -E '80|8000|5432'` 排查端口占用；执行 `docker compose logs -n 100 api` 查看日志。
5. **git `HEAD.lock` / `update_ref failed`**：被取消的旧 CD 可能留下 `/opt/ai-eval-platform/.git/HEAD.lock`。确认没有正在跑的 `git`/`deploy.sh` 后删除锁文件并重跑 Deploy：
   ```bash
   rm -f /opt/ai-eval-platform/.git/HEAD.lock /opt/ai-eval-platform/.git/index.lock
   sudo -u deploy bash /opt/ai-eval-platform/deploy/deploy.sh
   ```
   `deploy.sh` 在拿到部署互斥锁后会自动清理过期 `*.lock`。
6. **紧急回滚**：本地 `git revert HEAD && git push origin main`，或在服务器执行 `git reset --hard <commit_id> && bash deploy/deploy.sh`。

---

## 5. 开发规范 (Development Standards)

### 5.1 全中文注释要求（核心铁律）
所有新增与修改的代码（Python、Vue/TypeScript、Shell），**函数/类 docstring、复杂业务分支、类型定义必须配齐中文注释**。

```python
# Python 注释范例
@router.post("/tasks", response_model=TaskOut, summary="创建评测任务")
async def create_task(payload: TaskCreateIn, db: Session = Depends(get_db)) -> Task:
    """创建评测任务并入队 (queued)。若 payload.with_stress=True，评测成功后由 Worker 派生压测。"""
```

### 5.2 后端规范 (Python 3.12 / FastAPI)
1. **10 大标准错误码**：禁止原生 422/500 直接出给浏览器，必须统一抛出 `AppError(code=ErrorCode.XXX, message="说明")`：
   `UNAUTHORIZED`(401/403), `VALIDATION`(400), `NOT_FOUND`(404), `BUDGET_EXCEEDED`(409), `CONCURRENCY`(409), `WHITELIST`(403), `NEED_APPROVAL`(403), `UPSTREAM`(502), `TIMEOUT`(504), `INTERNAL`(500)。
2. **数据库与迁移**：修改 `models.py` 后必须通过 Alembic 生成迁移脚本：`alembic revision --autogenerate -m "..."`，禁止私自手动改库。
3. **安全与鉴权**：API Key 必须用 Fernet 加密存储且只写不回显；用户鉴权用 `HttpOnly` Cookie；WebSocket 使用 5 分钟有效期的单次短票 `ws-ticket`。
4. **长短任务分离**：`api` 容器仅负责快速交互与任务入队，耗时评测与压测全部由 `worker` 异步消费并下发给 `stress` 容器执行。**禁止**在 `routers/ws.py` / `harness.py` 里 `time.sleep` 评测、同步调用 `benchmark.run` / `rag.evaluate` / `testcase.generate` / `stress.run`、或轮询等到任务终态。
5. **能力未启用**：抛 `AppError(ErrorCode.VALIDATION, ...)`，HTTP **400**。禁止用 409 表示「功能没做」。LightRAG 未接入时 `kind=rag` **不得** mock `succeeded`。

### 5.2.1 异常处理与控制台追踪（冻结）

业务失败一律 `raise AppError`。外层只把 `AppError` 转成 REST JSON 或 WS `error` 事件。**禁止** `except Exception` 后把 `str(exc)`、traceback、SQL、上游原文发给浏览器。

内部函数（短工具、LLM、校验）冻结写法：

```python
from app.errors import AppError, ErrorCode
from app.agent.log import agent_trace

try:
    ...
except AppError:
    raise
except Exception as exc:
    agent_trace(f"内部异常 type={type(exc).__name__}")
    raise AppError(ErrorCode.INTERNAL, "操作失败") from exc
```

WebSocket 分发冻结写法：

```python
try:
    await _handle_user_message(...)
except AppError as exc:
    agent_trace(f"user_message AppError code={exc.code.value}")
    await _emit(
        db, ws, session_id, "error",
        {"code": exc.code.value, "message": exc.message},
        state=state,
    )
```

控制台：`agent_trace("...")` 打到 stderr（`[agent] ...`），Docker logs 可见。只打协议名、模型名、耗时、工具名、错误码，**禁止**打印 API Key、Cookie、密码、完整提示词。Worker 用 `print(..., flush=True)` 的 `[worker] start/succeeded/failed` 同样不得带密钥。

未配置 Agent 协议档、上游 4xx/5xx、超时分别归一为 `VALIDATION` / `UPSTREAM` / `TIMEOUT`，与 `llm.py` 现实现一致。

### 5.3 前端规范 (Vue 3 / TypeScript / Naive UI)
1. **统一架构**：采用 `<script setup lang="ts">` + `naive-ui`，严格遵循薄荷绿/深空蓝设计令牌 (`naive-theme.ts`)。
2. **通信与重连**：API 使用相对路径 `/api/*`；WS 使用相对路径 `/ws/agent?ticket=${ticket}`，支持断线按 `last_event_id` 自动补发事件流。关闭码 `4401` 重新领票，`4404` 视为会话不存在。
3. **确认卡默认值** 与 API.md §5 / PRD 5.2.2 同一份，禁止前端另备 sample_size=20 等第二套默认；后端侧默认值唯一来源在 `backend/api/app/agent/defaults.py`，前后端各存一份，改默认值必须双端同步（骨架化后 Agent 不再产出确认卡，该约定仅适用于未来恢复或 REST 直连场景）。
4. ContextMeter 只读 `GET /api/sessions/{id}/messages` 的 `context_meter`；骨架化后斜杠命令已整体移除，前端不再请求 `/api/slash-commands`。

---

## 6. AI Agent 行为准则 (AI Guardrails)

### 🔴 六大核心红线（绝对禁止）
1. **禁止私自扩充产品范围**（如外部 MCP、自定义系统提示词、多租户等）；新 REST/WS 字段必须先改 API.md；
2. **禁止破坏统一错误契约**（必须归一化为 10 大 `ErrorCode`；未启用能力用 `VALIDATION` 400，不用 409）；
3. **禁止明文暴露敏感凭据**（API Key、密码、JWT Secret 严禁打印、回显或写入 `agent_trace`）；
4. **禁止跳过 Alembic 手动改库**（改 Model 必须配 Migration）；
5. **禁止全量无意义重写**（必须局部替换，保留已有注释与架构）。
6. **禁止在 `main` 上开发模块**（必须按 §3.1 开 `feat/` `fix/` `docs/` 分支，经 PR 合入）。

额外（Agent / Worker）：
- 禁止在 WS 收包循环里 `await` 整轮 Harness；禁止在 api 进程跑完长 MCP；
- 禁止 LightRAG 未接入时把 RAG 任务 mock 成成功；
- 禁止 `except Exception` 后把异常原文或堆栈发给浏览器。
- **bash 必须走 bwrap 沙箱**（`sandbox.py`），禁止降级为裸 subprocess 或绕过沙箱执行命令（V1.2 红线）。

### 🟢 推荐操作五步法
1. **先查后改、先开分支**：查阅 PRD、API.md、Agent 开发文档；从 `origin/main` 拉出 `<type>/<scope>-简述` 再写代码；
2. **中文注释**：编写规范的中文 docstring 与代码注释；
3. **本地先构建与自检**：提交前必须在本地执行 §2.1 的门禁命令：前端 `npm run typecheck && npm run build`、后端 `ruff check . ../shared` / `pytest`，验证 100% 通过；
4. **规范中文提交**：严格采用 `<type>(<scope>): <中文描述>` 格式在**功能分支**上原子化提交，再开 PR；
5. **监控部署**：PR 合入 `main` 后关注 GitHub Actions CI/CD 流水线，异常时按 SOP 处置。
