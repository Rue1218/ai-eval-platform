# AI 测试与评估平台

面向单一研发与评测团队的内部 AI 测试平台。平台把模型协议管理、数据集与用例、基准评测、RAG 评测、共享压测、报告分析和 Agent 辅助编排放在同一工作台中，帮助团队以可追踪、可复现的方式评估模型与知识库效果。

项目不是通用聊天机器人：对话是任务规划和工具协作入口，耗时评测统一进入任务队列执行，结果以报告、事件和审计记录沉淀。

> 产品范围以 [PRD](docs/AI测试与评估平台-PRD.md) 为准；接口、字段和 WebSocket 事件以 [API 文档](docs/AI测试与评估平台-API.md) 为准；工程约定见 [AGENTS.md](AGENTS.md)。

## 项目介绍

大模型接入、数据准备、质量评测和容量验证常常分散在不同工具中，难以比较、复跑或说明一次结果是怎样得出的。本平台围绕“先评后压”的闭环设计：先运行基准、用例或 RAG 质量评测，只有质量任务成功且选择压测时，才派生共享压测任务。

平台支持多种上游模型协议，并将调用细节收敛在协议档中。团队成员可以在浏览器中维护评测资源、发起任务、跟踪进度和查看报告；AgentLoop 则提供会话、专家技能、受控工具、工作区文件和人工交互卡片，使复杂评测工作可以通过对话完成编排而不绕过平台权限与审计边界。

## 架构

```text
浏览器（Vue 3 + Naive UI）
  ├── REST /api/* ───────────────────────────────────┐
  └── WebSocket /ws/agent?ticket=... ────────────────┤
                                                       ▼
FastAPI API / AgentLoop Host
  ├── 认证、协议档、数据集、知识库、任务、报告、工作区
  ├── WebSocket 事件持久化、断线补发、受控工具与交互卡片
  └── AgentLoop：专家技能、模型调用、工具编排与会话状态
                         │                         │
                         │                         └── Runner 沙箱 / MCP 工具服务
                         ▼
PostgreSQL + pgvector  ◄──── Redis（短期状态与幂等）
                         │
                         ▼
Worker 任务队列
  ├── Benchmark：多协议模型质量评测
  ├── Testcase：多策略用例生成与确认
  ├── RAG：LightRAG 优先、可标注的本地降级检索
  └── Stress：共享压测与 SLA 判定
```

| 层级 | 主要组件 | 职责 |
| --- | --- | --- |
| 前端工作台 | Vue 3、TypeScript、Naive UI、Pinia | 对话、评测配置、任务、报告、工作区和管理界面 |
| API 与 Agent | FastAPI、WebSocket、AgentLoop | 短请求、权限、会话、流式事件、专家技能、工具与人工交互 |
| 异步执行 | Worker、LightRAG、go-stress-testing | 领取长任务、执行评测、生成报告、运行压力测试 |
| 数据与状态 | PostgreSQL、pgvector、Redis | 业务数据、事件回放、任务状态、向量能力与短期状态 |
| 运行与部署 | Docker Compose、GitHub Actions、GHCR | 服务编排、按改动构建镜像、滚动部署与服务器备用巡检 |

## 业务流程

```text
配置模型协议档 / 数据集 / 知识库 / 评测参数
                     │
                     ▼
创建评测任务 ──► queued ──► Worker 领取并执行 ──► succeeded / failed / cancelled
                     │                                  │
                     │                                  ├── 事件实时推送与断线回放
                     │                                  └── 报告、指标、审计记录落库
                     ▼
勾选压测且质量评测成功 ──► 派生共享压测 ──► SLA 判定与容量报告
```

在 AgentLoop 中，用户可先选择专家与模型，再通过对话使用已授权的技能和工具。需要补充信息、确认任务或批准高风险操作时，系统展示相应交互卡片；确认后的动作仍由服务端校验权限、会话和工作区范围。长耗时评测不会阻塞 WebSocket 收包循环。

## 功能

| 模块 | 功能概览 |
| --- | --- |
| 模型与协议档 | 统一维护 OpenAI Chat、OpenAI Responses、Anthropic Messages 等协议档与模型参数 |
| 基准评测 | 使用数据集运行多协议模型评测、规则评分、预算控制、断点续跑与报告生成 |
| 用例生成 | 通过多种策略生成测试用例，支持人工确认后进入后续流程 |
| RAG 评测 | 面向知识库进行检索与回答质量评测；LightRAG 不可用时明确标注降级来源，避免混淆结果 |
| 共享压测 | 质量评测成功后派生压测，记录吞吐、延迟、错误率并按 SLA 输出结论 |
| AgentLoop | 会话管理、流式回复、专家技能、提示词查看编辑、受控工具、人工问答与审批卡片 |
| 工作区 | 用户工作区、会话绑定、文件管理、上传及媒体预览；工具操作限定在授权范围内 |
| 任务与报告 | 队列状态、事件时间线、报告查看与分享、失败原因和审计留痕 |
| 安全与权限 | Cookie 登录、WebSocket 短票、统一错误码、敏感配置加密、工具沙箱与审计日志 |

## 项目亮点

- **评测与压测闭环**：以质量结果作为容量验证的前置条件，减少没有质量保障的无效压测。
- **真实任务语义**：评测由 Worker 异步执行，任务状态、事件和报告可追踪；RAG 降级路径会明确标注，不用模拟成功掩盖引擎状态。
- **可控的 Agent 协作**：专家技能和提示词可管理，工具权限、工作区范围和人工确认由服务端统一校验。
- **可恢复的实时体验**：WebSocket 事件持久化，网络断开后可按事件游标补发；流式文本与持久业务事件分层处理。
- **按实际改动部署**：部署计划读取 Dockerfile 输入并自动发现 MCP 工具服务。代码改动只构建相关镜像；纯说明文档不消耗 CI/CD 构建资源。
- **安全边界清晰**：浏览器不接触模型密钥或宿主命令；敏感配置加密存储，受控命令经 Runner 沙箱执行。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Naive UI、Pinia
- API：Python、FastAPI、SQLAlchemy、Alembic、WebSocket
- Agent：AgentLoop、模型协议适配层、受控工具与 MCP 服务
- 数据与任务：PostgreSQL 16、pgvector、Redis、异步 Worker
- 评测与运行：LightRAG、go-stress-testing、Docker Compose
- 工程化：GitHub Actions、GHCR、按差异构建与服务器备用自动部署

## 目录结构

```text
.
├── frontend/                 Vue 前端工作台
├── backend/
│   ├── api/                  FastAPI、REST、WebSocket、AgentLoop 与认证
│   ├── worker/               评测、用例生成、RAG 与压测任务执行器
│   ├── runner/               受控工具与沙箱执行服务
│   ├── shared/               API 与 Worker 共用模型、事件与公共能力
│   ├── lightrag/             RAG 引擎服务
│   └── stress/               压测服务
├── deploy/                   初始化、增量部署、备用巡检与部署测试
├── docs/                     PRD、API 契约、架构设计与实施记录
├── Web-Prototype/            原型参考
├── .github/workflows/        CI 与 main 分支部署工作流
└── docker-compose.yml        本地与生产服务编排
```

## 本地启动

前置条件：Docker 与 Docker Compose，或分别安装 Python 3.12+、Node.js 20+ 和 PostgreSQL。

```bash
# 复制并填写本地环境变量
cp .env.example .env

# 启动完整服务栈
docker compose up -d --build
```

启动后可访问：

- 前端：`http://localhost`
- 健康检查：`http://localhost:8000/api/health`
- API 文档：`http://localhost:8000/docs`

首次启动会根据环境变量创建引导管理员。生产环境必须自行设置强密码与密钥，禁止使用示例值。

### 常用本地开发命令

```bash
# 前端热更新
cd frontend
npm install
npm run dev

# API 检查
cd backend/api
ruff check . ../shared
pytest

# Worker 检查（Windows PowerShell）
cd ../worker
$env:PYTHONPATH = ".;.."
pytest

# 前端检查
cd ../../frontend
npm run typecheck
npm run build
```

## 部署说明

生产环境使用 Docker Compose。代码推送到 `main` 后，CI/CD 会按路径和 Dockerfile 输入决定是否构建、构建哪些镜像；纯说明文档提交会跳过构建与部署。

当 GitHub Actions 不可用时，服务器可以使用备用巡检在本地增量构建。详细配置、密钥要求、回滚和故障排查见 [备用自动部署方案](docs/AI测试与评估平台-备用自动部署方案.md) 与 [AGENTS.md](AGENTS.md)。

```bash
# 服务器上手动执行一次备用部署
cd /opt/ai-eval-platform
bash deploy/auto-deploy-watch.sh --force
```

## 文档索引

- [产品需求文档（PRD）](docs/AI测试与评估平台-PRD.md)
- [接口契约（API）](docs/AI测试与评估平台-API.md)
- [Agent 开发文档](docs/AI测试与评估平台-Agent开发文档.md)
- [AgentLoop 后端架构设计](docs/AI测试与评估平台-AgentLoop后端架构设计.md)
- [AgentLoop 前端重写与联调计划](docs/AI测试与评估平台-AgentLoop前端重写与联调计划.md)
- [备用自动部署方案](docs/AI测试与评估平台-备用自动部署方案.md)
- [开发计划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E5%BC%80%E5%8F%91%E8%AE%A1%E5%88%92.md)

## 贡献约定

提交前请遵循 [AGENTS.md](AGENTS.md) 中的分支、测试、提交信息、迁移和安全规范。数据库结构变更必须由 Alembic 迁移管理；新增 API 或 WebSocket 字段必须先同步 API 文档；禁止在日志、接口响应或提交中暴露密码、密钥、Cookie、令牌或上游原始异常。
