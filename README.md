# AI 测试与评估平台

基于 PRD V1.12 的单团队大模型测试与评估平台。当前首期采用 LangGraph 实现单轮 Agent
与模型调用层，并通过 FastAPI WebSocket 提供流式对话；用户消息、思考摘要、助手正文
增量、最终助手消息和结束信号已拆分为独立事件。Harness、人工确认和长任务按阶段冻结，
避免多套运行时并存。

> 开发规范：[AGENTS.md](AGENTS.md)
>
> 需求：[PRD V1.12](docs/AI测试与评估平台-PRD.md) · 接口：[API V1.20](docs/AI测试与评估平台-API.md)
>
> Agent：[Agent 开发文档 V0.5](docs/AI测试与评估平台-Agent开发文档.md) · [LangGraph + WebSocket 设计](docs/AI测试与评估平台-Agent框架LangGraph与WebSocket重设计.md)

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
| 模型调用层 | 三协议统一配置、思考开关/强度、同步/异步调用、正文/推理流和取消信号 |
| WebSocket | 短票、会话可见性、心跳 `pong`、事件回放、后台单轮回合 |
| WS 事件 | `user_message`、`thought`、`assistant_delta`、`assistant_message`、`response.completed`、`error`、`pong` |
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
│   ├── src/api/              REST 客户端、WS 客户端与 TypeScript 契约
│   ├── src/components/       Agent、任务、数据集等可复用组件
│   ├── src/layouts/          主布局
│   ├── src/stores/           Pinia 状态
│   └── src/views/            登录、Agent、任务、数据集、知识库等页面
├── backend/
│   ├── api/                  FastAPI 主服务、REST、WS Bridge、Agent、ModelGateway
│   │   ├── app/              配置、依赖、错误、模型、会话与 Agent 入口
│   │   │   ├── agent/        LangGraph 单轮 Agent 图
│   │   │   ├── harness/      Harness 未来扩展的空包边界
│   │   │   ├── llm/          ModelRequest/Response 与模型网关
│   │   │   ├── routers/      REST、认证、会话和 `/ws/agent` 路由
│   │   │   └── runtime/      旧运行时隔离的空包边界
│   │   ├── migrations/       Alembic 数据库迁移
│   │   └── tests/            API、Agent、模型和契约测试
│   ├── worker/               长任务 Worker、评测执行器与 Worker 测试
│   ├── shared/               API 与 Worker 共用的数据库模型
│   ├── lightrag/             LightRAG 服务组件
│   └── stress/               go-stress-testing 服务组件
├── docs/                     PRD、API、Agent/Harness 设计与开发计划
├── deploy/                   服务器初始化、数据库初始化与部署脚本
├── Web-Prototype/            静态 HTML 原型与原型资源
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

# Worker（Windows PowerShell）
cd ../worker
$env:PYTHONPATH = ".;.."
python -m pytest -q

# 前端
cd ../../frontend
npm run typecheck
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

- [产品需求 PRD V1.12](docs/AI测试与评估平台-PRD.md)
- [API 契约 V1.20](docs/AI测试与评估平台-API.md)
- [Agent 开发文档 V0.5](docs/AI测试与评估平台-Agent开发文档.md)
- [Agent 重设计工作区 V0.3](docs/AI测试与评估平台-Agent重设计工作区.md)
- [LangGraph + WebSocket 设计](docs/AI测试与评估平台-Agent框架LangGraph与WebSocket重设计.md)
- [模型调用层 LangGraph 设计](docs/AI测试与评估平台-模型调用层LangGraph重设计.md)
- [总开发计划](docs/AI测试与评估平台-开发计划.md)
- [后端开发计划](docs/AI测试与评估平台-后端开发计划.md)
- [前端开发计划](docs/AI测试与评估平台-前端开发计划.md)

## 说明

- 表结构由 Alembic 管理，禁止绕过迁移直接修改数据库；
- API 统一使用十类错误码，禁止向浏览器返回 Key、Cookie、SQL、traceback 或上游原文；
- 当前唯一平台 WS 入口是 `backend/api/app/routers/ws.py`，不恢复旧 Agent 工程的 Socket.IO `chat:*` 事件协议；
- `frontend/codex-make-patch.py` 与 `frontend/codex-ui.patch` 若存在，属于本地未跟踪文件，不属于平台运行时。
