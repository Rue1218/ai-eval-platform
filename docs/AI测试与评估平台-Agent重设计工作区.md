# AI 测试与评估平台 Agent 重设计工作区

> 版本：V0.3
> 状态：LangGraph 单轮 Agent 与 WebSocket 桥接已落地，Harness 仍冻结
> 审查日期：2026-08-23

## 当前边界

旧 Agent、Harness、模型调用层与运行时实现已从本分支移除，避免旧路径与新设计并存。当前目录边界如下：

- `backend/api/app/agent/`：仅承载 LangGraph 单轮 Agent 图；当前不含工具、确认卡、记忆和长任务；
- `backend/api/app/llm/`：承载模型调用契约、三协议适配入口和 LangGraph 流式投影；
- `backend/api/app/harness/`：保持空包边界，等待单独评审；
- `backend/api/app/runtime/`：保持空包边界，暂不恢复旧运行时。

API、Worker、数据库模型、迁移和前端平台能力保持不变。Agent WebSocket 已恢复为最小单轮文本通道；Agent 偏好、工具清单、确认卡、数据集/用例 AI 候选和长任务仍按能力未启用处理，不调用旧实现。

## 已落地的两层链路

```text
WebSocket 短票
  -> backend/api/app/routers/ws.py
  -> backend/api/app/agent/graph.py（LangGraph 单轮图）
  -> backend/api/app/llm/gateway.py（LangGraph 模型调用图）
  -> 三协议 adapters.py
  -> user_message/thought/assistant_delta/assistant_message/response.completed/error/pong WebSocket 事件
```

Agent 图只接收 `ModelRequest`，并投影 `content`、`reasoning`、`completed` 事件。WS 路由负责短票消费、会话可见性、消息与事件落库、历史补发、心跳和后台任务创建；收包循环不等待模型整轮完成。

## 明确冻结的能力

本轮不恢复旧 ReAct、MCP 传输、security/consent、ParallelFacade、确认卡、Redis/pgvector、Alembic 迁移、plan/reflect 或 Worker 长任务。`confirm_ack` 与 `cancel_task` 保留协议入口，但在当前 Agent 范式下返回 `VALIDATION` 能力未启用错误。

下一阶段如需增加 Harness，必须只依赖 `LangGraphAgent` 与 `app.llm` 稳定契约；不得在 `app/agent/graph.py` 复制模型协议调用，也不得重新引入第二条 Agent 循环。

## 修改代码文件与作用清单

- `backend/api/app/agent/graph.py`：LangGraph 单轮 Agent 图与流式事件投影；
- `backend/api/app/agent/__init__.py`：公开 `LangGraphAgent`；
- `backend/api/app/routers/ws.py`：短票鉴权、会话 WS、后台 Agent 回合和事件协议桥接；
- `backend/api/app/session_connections.py`：补充持久化事件与流式 chunk 的会话内广播；
- `backend/api/app/llm/gateway.py`：保持 `StreamAborted` 受控传播，支持 WS 回合取消语义；
- `backend/api/tests/test_agent_graph.py`：覆盖 Agent 图非流式与流式事件顺序。
