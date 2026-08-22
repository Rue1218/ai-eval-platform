# AI 测试与评估平台 Agent 开发文档

> 版本：V0.1
> 状态：首期 LangGraph 单轮 Agent 与 WebSocket 基础链路已实现
> 审查日期：2026-08-23
> 对应需求：`AI测试与评估平台-PRD.md` V1.8
> 对应接口：`AI测试与评估平台-API.md` V1.16

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
- 将 LangGraph 流事件投影为 `thought`、`message`、`error`、`pong`。

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

- `ModelConfig`：协议、Base URL、模型、采样和超时配置；
- `ModelRequest`：不可变消息列表、系统提示词和可选取消回调；
- `ModelResponse`：正文、用量、原始响应和耗时；
- `ModelStreamEvent`：`content`、`reasoning`、`completed`；
- `ModelGateway`：基于 LangGraph 的同步、异步和流式调用入口。

三协议 HTTP 细节只允许存在于 `app/adapters.py`。API Key 不得出现在日志、事件、异常消息或模型层对象的默认 repr 中。

## 3. 首期 WebSocket 事件

已实现服务端事件：

| 事件 | 作用 |
| --- | --- |
| `message` | 用户消息落库并向会话在线成员广播 |
| `thought` | `stream=chunk` 正文增量、`stream=think` 推理增量、`stream=think_final` 推理快照和最终交付句 |
| `error` | 脱敏后的 `ErrorCode` 与用户可见消息 |
| `pong` | 应用层心跳，不占用持久化事件号 |

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
- `backend/api/tests/test_agent_graph.py`：Agent 图回归测试。
