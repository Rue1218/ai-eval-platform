# AI 测试与评估平台

基于 PRD V1.8 的单团队大模型测试与评估平台。当前首期已将旧 Agent 骨架移出，采用
LangGraph 实现单轮 Agent 与模型调用层，并通过 WebSocket 提供流式对话；Harness、MCP、
人工确认和长任务按阶段冻结，避免多套运行时并存。

> 开发规范：[AGENTS.md](AGENTS.md)
>
> 需求：[PRD V1.8](docs/AI测试与评估平台-PRD.md) · 接口：[API V1.16](docs/AI测试与评估平台-API.md)
>
> Agent：[Agent 开发文档](docs/AI测试与评估平台-Agent开发文档.md) · [LangGraph + WebSocket 设计](docs/AI测试与评估平台-Agent框架LangGraph与WebSocket重设计.md)

技术栈：Vue 3 + TypeScript + Naive UI / Python 3.12 + FastAPI / LangGraph / PostgreSQL /
WebSocket / Docker Compose / LightRAG / go-stress-testing。

## 当前架构

```text
浏览器 Vue 3
  ├─ REST /api/* ────────────────┐
  └─ WS /ws/agent?ticket= ───────┤
                                ▼
                         FastAPI WS Bridge
                                │
                                ▼
                    LangGraph 单轮 Agent Graph
                                │
                                ▼
                    ModelGateway（LangGraph）
                                │
                                ▼
                    三协议适配器 / 上游模型

       sessions / messages / ws_events ──► PostgreSQL
       后续长任务 ───────────────────────► worker ──► LightRAG / stress
```

模型调用协议：`openai_chat`、`openai_responses`、`anthropic_messages`。协议 HTTP 细节只
保留在 `backend/api/app/adapters.py`；Agent 图只依赖 `backend/api/app/llm/` 的稳定契约。

WebSocket 建连流程：

1. 登录后调用 `POST /api/auth/ws-ticket` 获取五分钟单次短票；
2. 连接 `GET /ws/agent?ticket=...&session_id=...&last_event_id=...`；
3. 首次连接可创建私有会话，重连按 `last_event_id` 补发持久化事件；
4. `user_message` 进入后台 Agent Task，收包循环不等待模型整轮执行。

## 首期已实现

| 模块 | 当前状态 |
| --- | --- |
| LangGraph Agent | 单轮 `invoke` / 流式 `astream`，只组合 `ModelGateway` |
| 模型调用层 | 三协议统一配置、同步/异步调用、正文/推理流和取消信号 |
| WebSocket | 短票、会话可见性、心跳 `pong`、事件回放、后台单轮回合 |
| WS 事件 | `message`、`thought`、`error`、`pong`；`thought` 支持 `chunk` / `think` / `think_final` |
| 会话 | 私有/团队可见性、消息与事件持久化、断线补发 |
| 平台基础 | 登录、协议档、文件、任务/数据集等 REST 基础接口 |

## 当前冻结范围

以下能力不在首期 Agent 运行时中实现：

- 旧 `react.py`、旧 Harness 循环、Plan/Reflect、ParallelFacade；
- MCP Server/Transport、工具调用、工具结果和自定义 Skill；
- 人工确认卡、`confirm_ack`、任务取消 `cancel_task`；
- Agent 直接创建长任务、Worker 终态等待、Redis/pgvector 记忆；
- 新增数据库迁移、外部 MCP、可配置系统 Prompt。

当前收到未启用的确认/任务控制事件时，服务端返回统一 `VALIDATION` 错误，不伪造成功任务或报告。

## 目录结构

```text
.
├── frontend/                 Vue 3 + TypeScript + Naive UI + Vite
├── backend/
│   ├── api/                  FastAPI、REST、WS Bridge、LangGraph Agent、ModelGateway
│   ├── worker/               后续长任务 Worker
│   ├── lightrag/             LightRAG 服务组件
│   └── stress/               go-stress-testing 服务组件
├── docs/                     PRD、API、Agent 设计与开发计划
├── deploy/                   服务器初始化与部署脚本
├── .github/workflows/        CI 与 main 分支部署流程
└── docker-compose.yml
```

## 本地开发

```bash
# 1. 准备环境变量（可选，默认值可用于本地启动）
cp .env.example .env

# 2. 启动完整 Compose
docker compose up -d --build

# 3. 访问
# 前端：http://localhost
# API：http://localhost:8000/api/health
# Swagger：http://localhost:8000/docs
```

首次部署会从环境变量创建引导管理员（默认 `admin / admin123`），登录后请立即改密。

### 前端本地热更新

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173，/api 与 /ws 代理到 localhost:8000
```

### 本地检查

```bash
# 后端
cd backend/api
python -m ruff check . ../shared
python -m pytest -q

# 前端
cd ../../frontend
npm run build
```

## 部署

首次初始化服务器：

```bash
sudo bash deploy/server-setup.sh
```

之后推送 `main` 会触发 GitHub Actions，通过 SSH 执行部署脚本；服务器也可以手动执行：

```bash
sudo -u deploy bash /opt/ai-eval-platform/deploy/deploy.sh
```

生产环境至少修改：`SECRET_KEY`、`POSTGRES_PASSWORD`、`BOOTSTRAP_ADMIN_PASSWORD`、
`KEY_ENCRYPTION_KEY`。完整 SSH、Deploy Key 和 Actions Secret 说明见
[AGENTS.md](AGENTS.md) 与 `deploy/`。

## 文档索引

- [产品需求 PRD V1.8](docs/AI测试与评估平台-PRD.md)
- [API 契约 V1.16](docs/AI测试与评估平台-API.md)
- [Agent 开发文档 V0.1](docs/AI测试与评估平台-Agent开发文档.md)
- [Agent 重设计工作区 V0.3](docs/AI测试与评估平台-Agent重设计工作区.md)
- [LangGraph + WebSocket 设计](docs/AI测试与评估平台-Agent框架LangGraph与WebSocket重设计.md)
- [模型调用层 LangGraph 设计](docs/AI测试与评估平台-模型调用层LangGraph重设计.md)
- [总开发计划](docs/AI测试与评估平台-开发计划.md)
- [后端开发计划](docs/AI测试与评估平台-后端开发计划.md)
- [前端开发计划](docs/AI测试与评估平台-前端开发计划.md)

## 说明

- 表结构由 Alembic 管理，禁止绕过迁移直接修改数据库；
- API 统一使用十类错误码，禁止向浏览器返回 Key、Cookie、SQL、traceback 或上游原文；
- `frontend/codex-make-patch.py` 与 `frontend/codex-ui.patch` 若存在，属于本地未跟踪文件，不属于平台运行时。
