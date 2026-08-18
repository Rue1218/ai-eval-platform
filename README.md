# AI 测试与评估平台

基于《AI 测试与评估平台 PRD V1.6.3》搭建的**基础框架**。面向单一团队，用 Agent 自动化完成大模型基准测试与 RAG 测试，压测是两类评测的共享步骤。

> 📖 **开发规范与 AI 行为准则**：详见 [AGENTS.md](AGENTS.md)。

技术栈：Vue3 + TypeScript + Naive UI / Python 3.12 FastAPI / PostgreSQL / WebSocket / Docker Compose / go-stress-testing（预留）。

## 架构

```
浏览器 Vue3 ──WS/REST── FastAPI Agent Host（短 MCP + task.create）
                              │
                              ▼
                        PostgreSQL tasks
                              │
                              ▼
                     worker（长任务：评测 / RAG / 生成用例；压测下发到 stress）
                       │          │             │
                       ▼          ▼             ▼
                  三协议适配   LightRAG    go-stress-testing(/metrics)
```

Compose 六件套：`web` `api` `worker` `postgres` `lightrag` `stress`。

## 目录结构

```
.
├── frontend/       Vue3 + TypeScript + Naive UI + Vite 前端（nginx 反代 /api 与 /ws）
├── backend/
│   ├── api/        FastAPI 后端（认证 / 任务 / 协议档 / 数据集 / admin / WS）
│   ├── worker/     Python worker（轮询 PG 任务队列，骨架版 mock 执行）
│   ├── lightrag/   LightRAG 服务骨架（M3 接入真实内核）
│   └── stress/     go-stress-testing 服务骨架（暴露 /metrics，M4 接入内核）
├── deploy/         server-setup.sh（服务器初始化）+ deploy.sh（同步部署）
├── .github/workflows/   CI（lint+test）与 deploy.yml（push main 自动 SSH 部署）
└── docker-compose.yml
```

## 本地开发

```bash
# 1. 准备环境变量（可选，默认值即可跑通）
cp .env.example .env

# 2. 一键启动（首次会构建镜像）
docker compose up -d --build

# 3. 访问
#    前端   http://localhost
#    API    http://localhost:8000/api/health
#    文档   http://localhost:8000/docs
```

首次部署会从环境变量创建引导管理员（默认 `admin / admin123`），登录后请立即改密。

### 前端本地热更新（可选）

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 与 /ws 代理到 localhost:8000
```

## 已实现（骨架）

| 模块 | 状态 |
| --- | --- |
| 账号：登录 / 登出 / me / ws-ticket（HttpOnly Cookie + JWT，WS 短票） | ✅ |
| 任务：创建 / 列表 / 详情 / 取消 / 重跑（状态机 queued→running→succeeded/failed/cancelled） | ✅ |
| WebSocket `/ws/agent`：心跳 pong、thought/confirm 事件、断线按 last_event_id 补发 | ✅ |
| worker：轮询 queued 任务，mock 执行 2s 后 succeeded，写 task_events/ws_events | ✅ |
| 协议档：CRUD（Key 加密只写不回显，Fernet） | ✅ |
| 数据集：CRUD（仅元数据，文件解析待 M2） | ✅ |
| admin settings：读 / 写 | ✅ |
| 前端：登录 / Agent 会话 / 任务中心 / 协议档 | ✅ |

## 待实现（对应 PRD 里程碑）

- **M1**：真实任务入队由 Agent 确认卡驱动、MCP 完整 JSON Schema
- **M2**：三协议统一调用 + 规则评分 + Judge + 对比基线 + 用例生成 Skill
- **M3**：LightRAG 真实集成（锁 tag）、外部 OpenAI Chat RAG、黄金 QA、Hit Rate
- **M4**：先评后压、go-stress-testing 内核、白名单、Grafana、费用估算、通知

## 部署到服务器

### 1. 首次：服务器初始化

把本仓库代码放到服务器（或直接克隆），然后以 root 运行：

```bash
sudo bash deploy/server-setup.sh
```

脚本会安装 Docker、创建 `deploy` 用户、生成 SSH key、生成 `.env`。

### 2. 配置 GitHub

脚本末尾会提示两步，务必完成：

**A. Deploy Key（服务器 → GitHub 拉取）**
- 打开仓库 `Settings → Deploy keys → Add deploy key`
- 粘贴脚本打印的公钥，只读即可

**B. Actions Secrets（GitHub → 服务器 SSH）**
- 打开仓库 `Settings → Secrets and variables → Actions → New repository secret`
- 新增 4 个 secret：

| Secret | 值 |
| --- | --- |
| `SSH_HOST` | 服务器公网 IP |
| `SSH_USER` | `deploy` |
| `SSH_PORT` | `22` |
| `SSH_PRIVATE_KEY` | 服务器上 `/home/deploy/.ssh/id_ed25519` 完整内容 |

> 说明：同一把密钥对同时服务于两个方向——公钥加到 Deploy keys 用于服务器拉取代码；私钥存到 Actions Secrets 用于 CI SSH 登录服务器。脚本已把公钥写入服务器的 `authorized_keys`。

### 3. 首次部署

```bash
# 服务器上手动执行一次（或直接 push 触发 Actions）
sudo -u deploy bash /opt/ai-eval-platform/deploy/deploy.sh
```

### 4. 之后的自动同步

往 `main` 分支 push 代码，GitHub Actions 会自动 SSH 到服务器执行：

```
git fetch + reset --hard origin/main  →  docker compose up -d --build  →  image prune
```

也可手动在服务器上运行 `deploy/deploy.sh`。

## 环境变量

见 [.env.example](.env.example)。生产必改：`SECRET_KEY`、`POSTGRES_PASSWORD`、`BOOTSTRAP_ADMIN_PASSWORD`、`KEY_ENCRYPTION_KEY`。

- 会话 JWT：HttpOnly Cookie，默认 12h（`ACCESS_TOKEN_EXPIRE_MINUTES`）
- WS 短票：5 分钟（`WS_TICKET_EXPIRE_MINUTES`）
- 协议档 Key：Fernet 加密（`KEY_ENCRYPTION_KEY`，留空则由 SECRET_KEY 派生，仅用于开发）

## 说明

- 表结构由 Alembic 管理，api 容器启动时自动执行 `alembic upgrade head`（迁移文件在 `backend/api/migrations/`）。
- 统一错误码枚举在 `backend/api/app/errors.py`，对应 PRD 5.5 / API V1.0 §1.3 的十个 `code`。
- worker 侧为容器隔离复制了 `Task/TaskEvent/WsEvent/Report` 模型，后续可抽成共享 package。
- stress 与 lightrag 均为可运行的骨架服务，真实内核按 PRD 里程碑接入。
