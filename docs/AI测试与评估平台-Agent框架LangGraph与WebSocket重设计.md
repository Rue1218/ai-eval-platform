# AI 测试与评估平台 Agent 框架 LangGraph 与 WebSocket 重设计

> 版本：V0.1
> 状态：首期最小链路已实现
> 审查日期：2026-08-23

## 1. 目标

移出旧 Agent/Harness 运行时，只保留一条可验证的调用链：

```text
WebSocket -> LangGraph Agent -> ModelGateway -> 三协议适配器
```

首期只支持单轮文本模型调用和流式交付，保证模型调用层、Agent 图和 WS 协议各自只有一个实现。

## 2. LangGraph 分层

### 2.1 模型调用图

`backend/api/app/llm/gateway.py` 提供两个单节点图：

- `invoke_model`：一次性调用并返回 `ModelResponse`；
- `stream_model`：通过 LangGraph `custom` stream 投影 `content` / `reasoning`，通过 `updates` 收尾为 `completed`。

协议 URL、鉴权头和响应解析仍集中在 `app/adapters.py`，Agent 图不得直接调用适配器。

### 2.2 Agent 图

`backend/api/app/agent/graph.py` 只提供：

```text
START -> call_model / stream_model -> END
```

状态只包含 `ModelRequest` 和 `ModelResponse`，不持有数据库会话、WebSocket、工具、确认卡或任务状态。这样后续 Harness 可以组合 Agent，而不会把传输和平台状态写进图节点。

## 3. WebSocket 桥接

`backend/api/app/routers/ws.py` 负责：

- 消费 `POST /api/auth/ws-ticket` 签发的五分钟单次短票；
- 校验会话可见性，支持无 `session_id` 时创建私有会话；
- 按 `last_event_id` 补发 `ws_events`；
- 将 `user_message` 写入 `messages`，然后用后台 Task 启动 Agent 回合；
- 将正文增量发送为 `thought.stream=chunk`，推理增量发送为 `thought.stream=think`；
- 将最终推理快照写为 `think_final`，助手交付句写入 `messages` 并发送无 `stream` 的 `thought` 终帧；
- 在 receive 循环之外发送应用层 `pong`。

模型回合不会在 WebSocket 收包循环中同步等待。会话内在线连接通过进程内 Hub 接收持久化事件和正文增量；多 API 副本部署前必须替换为进程外 Pub/Sub。

## 4. 首期事件范围

| 事件 | 首期行为 |
| --- | --- |
| `message` | 用户消息落库并实时广播 |
| `thought` | 正文/推理流式增量、`think_final` 和交付终帧 |
| `error` | 业务错误统一映射为十类 `ErrorCode` |
| `pong` | 服务端应用层心跳 |
| `confirm_ack` | 保留上行协议名，返回能力未启用 |
| `cancel_task` | 保留上行协议名，返回能力未启用 |

本轮不实现 MCP、ReAct 工具循环、人工确认、长任务入队、任务取消、并发规划或 Harness 记忆。

## 5. 后续扩展规则

1. 新增 Harness 前先定义独立输入、输出、事件和取消契约；
2. 工具执行必须位于 Harness 边界，不得写入 `app/llm/`；
3. 需要人工确认的能力必须先更新 PRD/API，再实现 API 层确认卡；
4. 长任务只能入 PostgreSQL 队列，由 Worker 执行；
5. 任何新 Agent 范式只能新增 LangGraph 节点/边，禁止保留第二条旧循环。

## 修改代码文件与作用清单

- `backend/api/app/agent/graph.py`：单轮 Agent LangGraph；
- `backend/api/app/routers/ws.py`：WebSocket 到 Agent 图的异步桥接；
- `backend/api/app/session_connections.py`：会话内事件和流增量广播；
- `backend/api/tests/test_agent_graph.py`：Agent 图回归测试。
