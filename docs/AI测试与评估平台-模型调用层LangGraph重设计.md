# AI 测试与评估平台 — 模型调用层 LangGraph 重设计

> 版本：V0.3
> 状态：已接入 LangGraph 单轮 Agent 与 WebSocket 流式桥接
> 审查日期：2026-08-23

## 设计边界

模型调用层只负责一次模型请求的配置、协议适配、LangGraph 状态流转和流式事件投影。它不负责：

- Agent 规划、ReAct 循环或反思；
- 工具注册、MCP 传输或工具执行；
- 人工确认卡、权限策略或敏感操作门禁；
- 会话记忆、数据库落库或异步任务队列。

这些能力由 Harness / Agent 层组合，不能再次写入 `app/llm/`。当前 Agent 层只实现
单轮文本调用，Harness、工具、人工确认和长任务仍保持冻结。

## 当前实现

`ModelGateway` 内含两个单节点 LangGraph：

1. `invoke_model`：调用一次三协议适配器并返回 `ModelResponse`；
2. `stream_model`：把适配器的 `content` / `reasoning` 增量写入 LangGraph `custom` stream，并在末尾返回 `completed`。

三种既有协议仍由 `backend/api/app/adapters.py` 负责 HTTP 细节：`openai_chat`、`openai_responses`、`anthropic_messages`。因此 LangGraph 不会与协议适配器形成第二套 HTTP 实现。

## 与 Agent / WebSocket 的连接

`backend/api/app/agent/graph.py` 只依赖本文件定义的 `ModelGateway` 与模型契约，提供
`START -> call_model / stream_model -> END` 两条单轮图路径。`backend/api/app/routers/ws.py`
负责短票鉴权、会话事件落库和后台回合调度，不直接调用 `app.adapters`；模型流被投影为
`content` 被投影为 WebSocket `assistant_delta`，`reasoning` 被投影为
`thought.stream=think`，最终响应由 `assistant_message` 与 `done` 事件收尾。

模型层的 `StreamAborted` 保持为受控取消信号，由 Agent 回合决定如何交付停止结果，不能
被误报为 `INTERNAL` 或把上游异常原文发送给浏览器。

## 对外契约

- `ModelConfig`：协议、端点、模型、采样参数与超时；API Key 不参与 repr；
- `ModelRequest`：不可变消息列表、系统提示词和可选取消回调；
- `ModelResponse`：正文、token usage、原始响应和耗时；
- `ModelStreamEvent`：`content`、`reasoning`、`completed` 三类事件。

## 后续接入规则

Harness 与 Agent 只能依赖 `ModelGateway` 与上述契约，不能直接导入 `app.adapters`。如果后续要增加结构化输出、重试、模型路由或持久化检查点，必须先修改本契约并补测试，再决定是否扩展图节点。

## 修改代码文件与作用清单

- `backend/api/app/llm/contracts.py`：模型调用输入输出契约；
- `backend/api/app/llm/gateway.py`：LangGraph 调用图与同步/异步/流式入口；
- `backend/api/app/llm/__init__.py`：模型层公开导出；
- `backend/api/app/agent/graph.py`：只组合模型层契约的单轮 Agent 图；
- `backend/api/app/routers/ws.py`：把模型流映射到 WebSocket 事件，不复制协议调用；
- `frontend/src/api/ws.ts` / `frontend/src/api/types.ts` / `frontend/src/views/Agent.vue`：同步 WebSocket 流式事件类型、瞬态帧去重和前端渲染分流；
- `backend/api/requirements.txt`：锁定 `langgraph==1.2.10`；
- `backend/api/tests/test_llm_graph.py`：图调用、异步调用、流式事件、取消和错误脱敏测试；
- `backend/api/tests/test_agent_graph.py`：Agent 图非流式与流式事件顺序测试。
