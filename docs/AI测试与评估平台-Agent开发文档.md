# AI 测试与评估平台 Agent 开发文档

> 版本：V0.5.2
> 状态：首期 LangGraph 单轮 Agent、WebSocket 流式事件与多协议思考摘要已拆分
> 审查日期：2026-08-24
> 对应需求：`AI测试与评估平台-PRD.md` V1.12
> 对应接口：`AI测试与评估平台-API.md` V1.24

## 1. 当前唯一运行链路

```text
浏览器
  -> WebSocket /ws/agent（五分钟单次短票）
  -> app/routers/ws.py
  -> app/agent/graph.py（LangGraph 单轮 Agent）
  -> app/llm/gateway.py（LangGraph 模型调用图）
  -> app/adapters.py（三协议 HTTP 适配）
  -> 上游模型
```

本链路只有一个 Agent 入口和一个模型调用入口。禁止恢复旧 `react.py`、旧 Harness 循环或第二套模型客户端。

## 2. 分层边界

### 2.1 WebSocket Bridge

`app/routers/ws.py` 只负责：

- 消费 `POST /api/auth/ws-ticket` 签发的五分钟单次票据；
- 校验会话可见性，支持首次连接创建私有会话；
- 保存 `messages` 与 `ws_events`，按 `last_event_id` 补发历史事件；
- 在后台 Task 中启动单轮 Agent，不阻塞 WebSocket `receive` 循环；
- 将 LangGraph 流事件投影为 `user_message`、`thought`、`assistant_delta`、`assistant_message`、`response.completed`、`error`、`pong`。

路由不得直接调用 `app.adapters`，不得执行 Benchmark、RAG、用例生成或压测。

### 2.2 Agent Graph

`app/agent/graph.py` 只依赖 `app.llm` 的公开契约：

```text
START -> call_model -> END
START -> stream_model -> END
```

图状态只有 `ModelRequest` 与 `ModelResponse`。图节点不持有数据库 Session、WebSocket、工具注册、确认状态或任务队列。

### 2.3 ModelGateway

`app/llm/` 提供：

- `ModelConfig`：协议、Base URL、模型、采样、超时和 reasoning 开关/强度配置；
- `ModelRequest`：不可变消息列表、系统提示词和可选取消回调；
- `ModelResponse`：正文、用量、原始响应和耗时；
- `ModelStreamEvent`：`content`、`reasoning`、`completed`；
- `ModelGateway`：基于 LangGraph 的同步、异步和流式调用入口。

三协议 HTTP 细节只允许存在于 `app/adapters.py`。API Key 不得出现在日志、事件、异常消息或模型层对象的默认 repr 中。

Agent 思考配置从 `Setting(key="agent_reasoning")` 读取，结构为
`{"enabled": true, "effort": "medium"}`。开启时，OpenAI Responses 使用
`reasoning.effort` 与 `reasoning.summary="auto"`，Gemini OpenAI 兼容端点使用
`extra_body.google.thinking_config`，OpenAI Chat / Mimo 与 Anthropic 使用各自的思考字段；
前端只渲染上游提供的摘要/增量，不把助手正文写入 `thought`。关闭时网关过滤 reasoning
事件，并对已知支持显式关闭的端点发送关闭参数。Gemini 的 `xhigh/max` 映射为 `high`。

## 3. 首期 WebSocket 事件

已实现服务端事件：

| 事件 | 作用 |
| --- | --- |
| `user_message` | `role=user` 的用户消息落库并向会话在线成员广播；服务端不再使用含义不明确的 `message` |
| `thought` | 思考摘要/阶段状态；`stream=think` 推理增量、`stream=think_final` 思考快照，不承载助手正文 |
| `assistant_delta` | 助手正文瞬态增量，仅向在线会话成员广播，不占事件号 |
| `assistant_message` | 助手完整交付句，落库并占用会话事件号 |
| `response.completed` | 本轮生成结束，携带 `finish_reason` 和 `role=assistant` 并可回放 |
| `error` | 脱敏后的 `ErrorCode` 与用户可见消息 |
| `pong` | 应用层心跳，不占用持久化事件号，可与业务事件交错到达 |

保留但未启用的上行事件：`confirm_ack`、`cancel_task`。当前收到后返回 `VALIDATION` 能力未启用错误。

## 4. 当前冻结范围

以下内容不属于首期实现，不得在 Agent 图或 WebSocket 路由中提前加入：

- ReAct、Plan/Reflect、并行 Facade 或多 Agent 编排；
- Harness、MCP Server/Transport、工具调用和工具结果；
- 人工确认卡、权限策略、consent、安全门禁；
- Redis/pgvector 记忆、检查点和复杂上下文压缩；
- PostgreSQL 长任务入队、Worker 执行和 stress 派生；
- Alembic 新迁移以及 `plan.py` / `reflect.py` 等挂起模块。

## 5. 后续扩展门禁

1. 新增 Harness 前先定义独立的输入、输出、事件、取消和错误契约；
2. 新增 MCP 或确认卡前先同步 PRD 与 API，再实现 API 层门禁；
3. 长任务只能入 PostgreSQL 队列，由 Worker 执行，API 进程不等待终态；
4. 所有异常统一为十类 `ErrorCode`，不得把 traceback、SQL 或上游原文发送给浏览器；
5. 扩展 Agent 只能在 LangGraph 图中增加节点/边，禁止保留旧路径或复制协议适配。

## 修改代码文件与作用清单

- `backend/api/app/agent/graph.py`：LangGraph 单轮 Agent 图；
- `backend/api/app/llm/contracts.py`：模型调用输入输出契约；
- `backend/api/app/llm/gateway.py`：LangGraph 模型调用与流式投影；
- `backend/api/app/routers/ws.py`：WebSocket 鉴权、会话事件与后台 Agent 回合；
- `backend/api/app/session_connections.py`：会话内事件和流增量广播；
- `backend/api/tests/test_agent_graph.py`：Agent 图回归测试；
- `frontend/src/api/ws.ts`：识别 `assistant_delta` 瞬态帧并跳过事件号去重；
- `frontend/src/api/types.ts`：补充 `user_message`、`assistant_delta`、`assistant_message`、`response.completed` 事件类型；
- `frontend/src/views/Agent.vue`：分离思考卡、助手正文增量、最终助手消息和结束状态。

### V0.3（2026-08-23）修改代码文件与作用清单

- `backend/api/app/routers/ws.py`：用户回显改发 `user_message`，回合完成改发 `response.completed`，保留 `session_id` / `task_id` 公共头；
- `frontend/src/api/types.ts`：同步新事件类型并保留旧事件类型兼容历史数据；
- `frontend/src/views/Agent.vue`：监听新用户回显与完成事件，思考卡不再消费助手正文；
- `README.md`、`docs/AI测试与评估平台-API.md`、`docs/AI测试与评估平台-PRD.md`：同步事件生命周期与客户端渲染契约。

### V0.5（2026-08-23）修改代码文件与作用清单

- `backend/api/app/adapters.py`：为 Gemini OpenAI 兼容端点补充 `include_thoughts` 与思考强度映射，并识别 `thinking` 增量；
- `backend/api/tests/test_adapters.py`：增加 Gemini 请求体和思考增量回归测试；
- `docs/AI测试与评估平台-API.md`：将 Gemini 思考字段写入接口适配契约。

### V0.4（2026-08-23）修改代码文件与作用清单

- `backend/api/app/routers/admin.py`：新增 Agent 思考开关与强度的配置默认值、校验和读取入口；
- `backend/api/app/routers/ws.py`：将 `agent_reasoning` 注入每轮 `ModelConfig`；
- `backend/api/app/llm/contracts.py` / `gateway.py`：扩展 reasoning 配置并支持关闭时过滤思考流；
- `backend/api/app/adapters.py`：按 OpenAI Chat/Responses、Mimo、Anthropic 协议映射思考参数；
- `frontend/src/views/AdminProfiles.vue` / `frontend/src/api/types.ts` / `frontend/src/api/mockData.ts`：增加管理页设置、类型与 Mock 数据；
- `backend/api/tests/test_adapters.py` / `backend/api/tests/test_llm_graph.py`：覆盖思考强度映射和关闭行为。

### V0.5.1（2026-08-24）修改代码文件与作用清单

- `docs/AI测试与评估平台-Agent开发文档.md`：头部版本与对应接口同步为 API.md V1.22（Harness 契约收敛，纯文档变更，无功能改动）。

### V0.5.2（2026-08-24）修改代码文件与作用清单

- `backend/api/app/agent/attachments.py`：校验消息附件归属，解析文本、PDF、DOCX、XLSX，并把图片转换为内部图文内容块；解析结果只进入模型请求，不覆盖用户原文。
- `backend/api/app/routers/ws.py`：将用户消息附件注入 Harness 模型窗口，支持附件-only 消息并持久化安全预览元数据。
- `backend/api/app/adapters.py`：将内部图文内容块适配为 OpenAI Chat/Responses 与 Anthropic Messages 请求格式。
- `backend/api/app/routers/sessions.py` / `frontend/src/api/types.ts`：历史回放返回并消费附件文件名、大小、类型和内容地址，刷新后仍可预览。
- `backend/api/tests/test_agent_attachments.py`：覆盖文本注入、图片内容块和三协议格式转换。
