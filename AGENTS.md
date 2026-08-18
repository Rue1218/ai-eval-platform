# AI 测试与评估平台 — AI Agent 行为规范与工程指南 (AGENTS.md)

> 本文件是面向所有参与本项目的 **AI Agent（以及人类开发者）** 的最高行动指南与行为规范。
> 在阅读、分析、编写或修改本仓库的任何代码与文档前，**必须严格遵守本文档所规定的原则与约束**。

---

## 1. 项目简介 (Project Overview)

### 1.1 业务背景与核心定位
- **项目名称**：AI 测试与评估平台 (`ai-eval-platform`)
- **核心定位**：面向**单一研发/评测团队**的内部平台，利用 **AI Agent（WebSocket + 内部 MCP Host）** 自动化完成大语言模型（LLM）**基准评测（Benchmark）** 与 **知识库检索增强生成评测（RAG）**。
- **核心特色**：
  - **对话驱动**：通过 WebSocket Agent 交互，自动化解析意图并生成结构化「确认卡」；
  - **先评后压**：压测作为质量评测的共享下游环节，仅在质量评测成功 (`succeeded`) 且勾选压测后自动派生执行，继承同一被测端点；
  - **三协议适配**：统一适配 OpenAI Chat Completions、Anthropic Messages、Dify Completion 协议；
  - **单团队全员同权**：单一 `member` 角色，操作留痕审计，敏感 Key 采用 Fernet 强加密且只写不回显。

### 1.2 核心架构模型
```
浏览器 Vue 3 (Naive UI)
  │── WS: /ws/agent?ticket= ──► FastAPI Agent Host (短 MCP + 意图拆解 + 任务入队)
  │── REST: /api/* ───────────► FastAPI REST API (认证 / 协议档 / 数据集 / 报告 / 审计)
                                        │
                                        ▼
                                  PostgreSQL 16 (tasks 状态机 / task_events / 数据集 / 审计)
                                        │
                                        ▼
                                  Python Worker (长任务调度：Benchmark / RAG / 用例生成)
                                   ├── 三协议统一调用 + 规则评分 / LLM Judge
                                   ├── LightRAG 原生检索 / 外部 Chat RAG (Hit Rate@K / 黄金QA)
                                   └── 派生压测 ──► stress 容器 (go-stress-testing) ──► /metrics (Prometheus)
```

### 1.3 核心技术栈
| 层次 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| **前端** | Vue 3.5 + TypeScript + Vite + Naive UI + Pinia | 响应式薄荷绿毛玻璃 / 深空蓝暗色设计系统，Nginx 反代 `/api` 与 `/ws` |
| **API 服务** | Python 3.12 + FastAPI + Uvicorn + Pydantic v2 | 提供 REST 接口、WebSocket Agent Host、内部 MCP 工具注册 |
| **数据库/ORM** | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic | 结构化数据存储与全自动化数据库迁移管理 |
| **Worker 引擎** | Python 3.12 异步 Worker | 轮询 PostgreSQL 任务队列，驱动三协议评测与 RAG 评测 |
| **RAG 引擎** | LightRAG 服务 | 专有知识图谱/混合检索评估服务 |
| **压测引擎** | go-stress-testing 服务 | 高性能发压，暴露 `/metrics` 供 Prometheus/Grafana 监控采集 |
| **容器编排** | Docker Compose 六件套 | `web`、`api`、`worker`、`postgres`、`lightrag`、`stress` |

### 1.4 文档权威与冲突裁决
本仓库 `docs/` 目录下存放了完整的规格说明书，效力层级如下：
1. **L0 产品权威**：[`docs/AI测试与评估平台-PRD.md`](docs/AI测试与评估平台-PRD.md)（功能范围、状态机、确认卡字段、错误码名单唯一真理）。
2. **L1 接口契约**：[`docs/AI测试与评估平台-API.md`](docs/AI测试与评估平台-API.md)（REST/WS 路径、JSON Payload 唯一真理）。
3. **L1 视觉规范**：[`docs/AI测试与评估平台-设计规范.md`](docs/AI测试与评估平台-设计规范.md)（Naive UI 主题覆盖、色彩令牌、排版与微交互规范）。
4. **L2 计划文档**：[`docs/AI测试与评估平台-开发计划.md`](docs/AI测试与评估平台-开发计划.md)、[`docs/AI测试与评估平台-后端开发计划.md`](docs/AI测试与评估平台-后端开发计划.md)、[`docs/AI测试与评估平台-前端开发计划.md`](docs/AI测试与评估平台-前端开发计划.md)。

> ⚠️ **冲突裁决原则**：
> - 若代码/计划与 PRD 冲突，**以 PRD 为准**；
> - 若接口字段与 API.md 冲突，**以 API.md 为准**；
> - 禁止任何 AI Agent 私自扩大产品范围或变更核心字段命名。

---

## 2. 项目结构 (Project Structure)

```
ai-eval-platform/
├── .github/
│   └── workflows/
│       ├── ci.yml               # GitHub Actions CI（Python 3.12 + ruff lint + pytest）
│       └── deploy.yml           # GitHub Actions CD（push main 触发 SSH 自动部署）
├── backend/
│   ├── api/                     # FastAPI 主服务（API & Agent Host）
│   │   ├── app/
│   │   │   ├── routers/         # API 路由模块（auth, tasks, profiles, datasets, admin, ws）
│   │   │   ├── config.py        # Pydantic 环境变量配置
│   │   │   ├── db.py            # SQLAlchemy 引擎与 Session 依赖
│   │   │   ├── deps.py          # 鉴权依赖注入（当前登录用户、WS ticket 校验）
│   │   │   ├── errors.py        # 统一 10 大错误码枚举与 AppError 异常处理器
│   │   │   ├── main.py          # FastAPI 应用入口与中间件配置
│   │   │   ├── models.py        # SQLAlchemy 数据库 ORM 模型
│   │   │   ├── schemas.py       # Pydantic 请求/响应 DTO 定义
│   │   │   └── security.py      # JWT、密码 bcrypt 散列、Fernet Key 加解密工具
│   │   ├── migrations/          # Alembic 数据库迁移版本脚本
│   │   ├── tests/               # Pytest 单元测试与契约测试
│   │   ├── alembic.ini          # Alembic 配置文件
│   │   ├── Dockerfile           # API 容器构建配置
│   │   ├── entrypoint.sh        # 容器启动脚本（自动执行 alembic upgrade head）
│   │   ├── pyproject.toml       # Ruff 与 Pytest 工具链配置
│   │   ├── requirements.txt     # 运行时依赖
│   │   └── requirements-dev.txt # 开发与测试依赖
│   ├── worker/                  # 异步任务 Worker 服务
│   │   ├── app/                 # Worker 执行引擎（任务状态机轮询、评测驱动）
│   │   ├── Dockerfile           # Worker 容器构建配置
│   │   └── requirements.txt     # Worker 依赖
│   ├── lightrag/                # LightRAG 服务组件
│   │   └── Dockerfile           # LightRAG 容器构建配置
│   └── stress/                  # go-stress-testing 压测服务组件
│       └── Dockerfile           # 压测容器构建配置
├── frontend/                    # Vue 3 前端工程
│   ├── src/
│   │   ├── api/                 # Axios 请求封装与 REST 接口模块
│   │   ├── layouts/             # 全局布局组件（侧边栏、主工作区）
│   │   ├── router/              # Vue Router 路由配置与守卫
│   │   ├── stores/              # Pinia 状态管理（user, agent, tasks 等）
│   │   ├── styles/              # 全局样式与 CSS 变量令牌
│   │   ├── views/               # 页面视图（/agent, /tasks, /datasets, /kb, /admin/* 等）
│   │   ├── App.vue              # 根组件（Naive UI ConfigProvider 注入）
│   │   ├── main.ts              # 前端入口文件
│   │   └── naive-theme.ts       # Naive UI 主题色与组件定制令牌
│   ├── nginx.conf               # 生产环境 Nginx 配置文件（反代 /api 与 /ws）
│   ├── package.json             # 前端依赖配置
│   ├── tsconfig.json            # TypeScript 编译配置
│   └── vite.config.js           # Vite 构建与开发代理配置
├── deploy/
│   ├── server-setup.sh          # 生产服务器一键初始化脚本（安装 Docker, 配置用户, 生成 SSH 密钥）
│   └── deploy.sh                # 生产环境自动化构建部署脚本（拉取代码, 注入构建版本, 重建容器）
├── docs/                        # 官方设计文档、PRD、API 契约与开发计划
├── Web-Prototype/               # 静态 HTML 原型参考（仅供视觉与交互参考）
├── docker-compose.yml           # 全栈六件套本地与生产编排文件
├── .env.example                 # 环境变量模板与配置说明
├── AGENTS.md                    # AI Agent 行为准则与项目工程规范（本文件）
└── README.md                    # 项目快速上手指南
```

---

## 3. Git 提交规范 (Git Commit Conventions)

本项目严格采用 **[Conventional Commits](https://www.conventionalcommits.org/)** 规范。

### 3.1 提交格式
```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

### 3.2 允许的 Type 类型
| Type | 说明 | 示例 |
| :--- | :--- | :--- |
| `feat` | 新增功能 | `feat(api): add ws-ticket authentication endpoint` |
| `fix` | 修复缺陷 | `fix(worker): handle connection timeout on LLM judge call` |
| `docs` | 仅文档变更 | `docs: update deployment secret configuration guide` |
| `style` | 不影响代码含义的代码格式修改（空格、分号、lint等） | `style(frontend): format vue components with prettier` |
| `refactor` | 代码重构（既不是新增功能也不是修 bug） | `refactor(backend): extract Fernet cipher helper to security module` |
| `perf` | 提高性能的代码更改 | `perf(worker): optimize dataset batch stream processing` |
| `test` | 增加或修正现有测试 | `test(api): add contract tests for profile CRUD` |
| `build` | 影响构建系统或外部依赖的更改（Vite, Docker, pip 等） | `build(docker): optimize api multi-stage build cache` |
| `ci` | CI/CD 配置文件与脚本变更（GitHub Actions, deploy.sh 等） | `ci(github): add secret check step in deploy workflow` |
| `chore` | 其他不修改 src 或测试文件的琐碎变更 | `chore: update .gitignore rules` |
| `revert` | 撤销此前的某次提交 | `revert: feat(api): revert experimental streaming parser` |

### 3.3 常用 Scope 作用域
- `api`：FastAPI 后端业务逻辑
- `worker`：异步评测/压测 Worker 调度引擎
- `web` 或 `frontend`：Vue 3 前端界面
- `mcp`：Agent MCP 工具与协议
- `rag`：LightRAG 或外部 RAG 适配器
- `stress`：go-stress-testing 压测模块
- `auth`：认证、会话与权限
- `dataset`：数据集管理与解析
- `profile`：模型协议档配置
- `task`：任务状态机与任务管理
- `report`：报告生成与对比
- `deploy`：部署脚本、Docker 或 Nginx 配置

### 3.4 提交准则
1. **Subject 规范**：使用动词祈使句开头，首字母小写（若为英文），结尾不加句号，长度控制在 50 字符内，清晰表达修改意图。
2. **Body 规范**：若修改涉及复杂架构变更、破坏性变更或关键决策，必须在 Body 中详细说明原因、影响范围和解决方案。
3. **关联 PRD / Issue**：推荐在 Footer 中标注对应的 PRD 需求项或 Issue 编号，例如 `Ref: PRD-5.2` 或 `Closes #12`。
4. **分支管理**：
   - `main`：生产主分支，受 CI 保护，直接对接生产自动部署；
   - `feature/<name>`：特性开发分支；
   - `fix/<name>`：缺陷修复分支。

---

## 4. 自动部署服务 (CI/CD & Automated Deployment)

本项目实现了全自动化的 CI/CD 管道，基于 GitHub Actions + Docker Compose 架构。

### 4.1 CI 持续集成工作流 (`.github/workflows/ci.yml`)
- **触发条件**：向 `main` 分支 push 或发起针对 `main` 分支的 Pull Request。
- **检查内容**：
  1. **Python 3.12** 环境搭建与依赖安装；
  2. **静态代码检查**：执行 `ruff check .`（必须 0 错误）；
  3. **单元测试与契约测试**：执行 `pytest`（必须全部通过）。
- **门禁要求**：CI 检查未全部通过前，禁止将代码合入 `main` 分支。

### 4.2 CD 自动部署工作流 (`.github/workflows/deploy.yml`)
- **触发条件**：代码合入或直接 push 到 `main` 分支（或手动 `workflow_dispatch` 触发）。
- **工作流机制**：
  1. 自动检测 GitHub Secrets（`SSH_HOST`, `SSH_USER`, `SSH_PORT`, `SSH_PRIVATE_KEY`）；
  2. 使用 `appleboy/ssh-action` 建立安全 SSH 隧道连接生产服务器；
  3. 切换至生产工作目录并以 `deploy` 用户执行 `/opt/ai-eval-platform/deploy/deploy.sh`。

### 4.3 部署脚本核心流程 (`deploy/deploy.sh`)
1. **代码同步**：执行 `git fetch origin && git reset --hard origin/main`，保证生产环境严格与远程 `main` 一致；
2. **构建元数据注入**：自动提取 Git commit hash 注入 `BUILD_VERSION`，提取当前 UTC 时间注入 `BUILD_TIME`；
3. **无缝容器重建**：执行 `docker compose up -d --build --remove-orphans`；
4. **数据库自动迁移**：`api` 容器在 `entrypoint.sh` 中自动执行 `alembic upgrade head`；
5. **镜像清理**：执行 `docker image prune -f` 清理孤儿镜像，避免磁盘耗尽；
6. **健康自检**：输出 `docker compose ps` 状态。

### 4.4 生产服务器初始化 (`deploy/server-setup.sh`)
- 自动安装 Docker CE 及 Docker Compose 插件；
- 创建低特权部署用户 `deploy` 并赋予 `docker` 组权限；
- 生成专属 ed25519 密钥对用于 GitHub Actions SSH 通信与 Deploy Keys；
- 初始化生产目录 `/opt/ai-eval-platform` 与 `.env` 环境变量模板。

---

## 5. 开发规范 (Development Standards)

### 5.1 通用编码与注释规范（核心准则）
1. **全中文注释要求**：所有新增及修改的代码（包括后端 Python、前端 Vue/TypeScript、配置脚本等），其类说明、方法/函数 docstring、关键业务逻辑分支、复杂算法及类型定义**必须提供清晰、准确的中文注释**。
2. **文档与代码一致性**：注释需与 PRD/API 规范中的专有名词保持一致（例如：“确认卡”、“协议档”、“先评后压”、“短票”等）。

### 5.2 后端开发规范 (Python 3.12 / FastAPI)
1. **类型安全与注释**：所有函数、方法必须标注完整的 Python Type Hints，并附带规范的中文 docstring 说明入参、出参和异常场景。
2. **统一错误码机制（铁律）**：
   - 严禁直接 `raise HTTPException` 或返回自定义格式的错误 JSON；
   - 必须使用 `backend/api/app/errors.py` 中定义的 **10 大标准错误码**：
     `UNAUTHORIZED`, `VALIDATION`, `NOT_FOUND`, `BUDGET_EXCEEDED`, `CONCURRENCY`, `WHITELIST`, `NEED_APPROVAL`, `UPSTREAM`, `TIMEOUT`, `INTERNAL`；
   - 统一通过抛出 `AppError(code=ErrorCode.XXX, message="说明", fields={...})` 触发全局异常拦截器，输出规范响应 `{ "code": "...", "message": "..." }`。
3. **数据库与 ORM 规范**：
   - 必须遵循 SQLAlchemy 2.0 声明式风格；
   - **禁止直接修改生产数据库表结构**，所有数据模型（`models.py`）变更必须通过 Alembic 生成迁移版本（`alembic revision --autogenerate -m "..."`），并在 `migrations/versions/` 提交版本文件。
4. **安全与密钥防护**：
   - 模型协议档 API Key 必须使用 Fernet 进行双向加密存储；
   - 接口返回协议档数据时，**严禁回显明文 Key**（仅返回 `has_key: true` 掩码标志）；
   - 用户鉴权采用 `HttpOnly` Cookie（`aieval_session`），有效期 12h；
   - WebSocket 连接鉴权禁止传递长期 JWT，必须先调用 `POST /api/auth/ws-ticket` 获取 5 分钟有效期的单次短票。

### 5.3 前端开发规范 (Vue 3 / TypeScript / Naive UI)
1. **组件与类型规范**：
   - 统一采用 `<script setup lang="ts">` 语法；
   - 复杂组件、Pinia Store、工具函数与 TypeScript Interface 必须添加中文注释；
   - 严禁随意引入未经批准的大型 UI 库或图表库，必须基于 `naive-ui` 配合设计规范令牌开发；
   - 色彩体系遵从 `naive-theme.ts` 与 `styles/` 中的薄荷绿毛玻璃 / 深空蓝暗色设计令牌。
2. **API 与网络通信**：
   - API 请求统一封装在 `src/api/` 目录下，使用 Axios 实例；
   - 请求路径必须使用相对路径 `/api/*`，严禁在前端代码中硬编码 `http://localhost:8000` 或生产服务器 IP；
   - 全局拦截器必须统一捕获后端 10 大错误码，并映射到 Naive UI `n-message` 或表单标红提示。
3. **WebSocket 与 Agent 会话**：
   - WebSocket 地址使用相对路径 `/ws/agent?ticket=${ticket}`；
   - 严格维护连接状态机（`connecting` / `connected` / `reconnecting` / `disconnected`）；
   - 支持断线自动重连，携带 `last_event_id` 请求补发断线期间的事件流；
   - 统一渲染 `thought`（思考气泡）、`confirm`（确认卡）、`tool_call`（MCP工具卡）与 `progress`（任务进度条）。

### 5.4 异步调度与 Worker 规范
1. **职责单一性**：
   - `api` 容器仅负责 Agent 对话、确认卡生成、短工具执行与任务入队（写入 PG `tasks` 表，状态为 `queued`）；
   - `worker` 容器负责轮询 PG 任务队列并执行耗时较长的评测长任务；
   - 严禁在 `api` 进程内直接运行耗时几十分钟的模型评测或压测循环。
2. **压测隔离机制（先评后压）**：
   - Worker 在完成 Benchmark/RAG 质量评测且状态置为 `succeeded` 后，若任务配置了 `with_stress=true`，则自动创建并入队压测子任务（`parent_task_id` 指向质量任务）；
   - 压测执行由 Worker 下发给独立的 `stress` 容器运行，禁止 Worker 本身耗尽连接池发压。

---

## 6. AI Agent 行为规范与铁律 (AI Agent Guardrails)

作为协助开发本项目的 AI Agent，在执行任何编码、重构或调试指令时，必须严格执行以下准则：

### 🔴 核心禁忌（绝对禁止）
1. **禁止私自扩充产品范围**：禁止引入 PRD V1.6.3 明确声明不做的特性（如外部 MCP、用户自定义系统提示词、多租户隔离、TMS 外部同步、沙箱代码执行等）。
2. **禁止破坏统一错误契约**：禁止直接返回原生 422/500 JSON 或私自造错误码，所有错误必须归一化为 `ErrorCode` 的 10 种枚举。
3. **禁止明文暴露敏感凭据**：禁止在日志、控制台、代码、Git 提交或 API 响应中打印/回显用户 API Key、数据库明文密码或 JWT Secret。
4. **禁止跳过 Alembic 手动改库**：修改 `backend/api/app/models.py` 后，必须配套更新/生成 Alembic 迁移脚本，严禁直接手写原生 ALTER TABLE 绕过版本追踪。
5. **禁止全量无意义重写**：修改现有代码时，必须使用局部替换，保留既有注释、docstring 与既定架构，严禁随意删除已有类型定义或业务分支。

### 🟢 推荐操作模式（主动遵循）
1. **先查后改 (Read-Before-Write)**：
   - 修改业务逻辑前，优先阅读 `docs/AI测试与评估平台-PRD.md` 和 `docs/AI测试与评估平台-API.md` 相关章节；
   - 修改前端视图前，先查看 `Web-Prototype/` 对应页面的静态原型结构。
2. **代码合规自检 (Verification)**：
   - 每次后端代码改动后，在提交前确保运行并通过 `ruff check .` 与 `pytest`；
   - 每次前端代码改动后，确保通过 `npm run typecheck`。
3. **中文注释完备 (Chinese Documentation)**：
   - 所有编写、重构或新增的代码必须配齐规范的**中文注释与 docstring**，准确阐述业务意图、输入输出参数及核心算法逻辑。
4. **原子化提交 (Atomic Commits)**：
   - 将逻辑清晰的独立改动拆分为符合 Conventional Commits 的提交。
5. **保持架构清晰与文档一致**：
   - 新增 API 路由时，必须同步在 `backend/api/app/main.py` 注册，并确保请求/响应 Schema 在 `backend/api/app/schemas.py` 严格定义。

---

> **本指南自发布之日起对本项目所有代码生成与协作行为具有强制约束力。**
