# AI 测试与评估平台 — 模型调用层 LangGraph 重设计

> 版本：V0.1  
> 状态：首期最小实现  
> 审查日期：2026-08-23

## 设计边界

模型调用层只负责一次模型请求的配置、协议适配、LangGraph 状态流转和流式事件投影。它不负责：

- Agent 规划、ReAct 循环或反思；
- 工具注册、MCP 传输或工具执行；
- 人工确认卡、权限策略或敏感操作门禁；
- 会话记忆、数据库落库或异步任务队列。

这些能力由后续 Harness / Agent 层组合，不能再次写入 `app/llm/`。

## 当前实现

`ModelGateway` 内含两个单节点 LangGraph：

1. `invoke_model`：调用一次三协议适配器并返回 `ModelResponse`；
2. `stream_model`：把适配器的 `content` / `reasoning` 增量写入 LangGraph `custom` stream，并在末尾返回 `completed`。

三种既有协议仍由 `backend/api/app/adapters.py` 负责 HTTP 细节：`openai_chat`、`openai_responses`、`anthropic_messages`。因此 LangGraph 不会与协议适配器形成第二套 HTTP 实现。

## 对外契约

- `ModelConfig`：协议、端点、模型、采样参数与超时；API Key 不参与 repr；
- `ModelRequest`：不可变消息列表、系统提示词和可选取消回调；
- `ModelResponse`：正文、token usage、原始响应和耗时；
- `ModelStreamEvent`：`content`、`reasoning`、`completed` 三类事件。

## 后续接入规则

Harness 只能依赖 `ModelGateway` 与上述契约，不能直接导入 `app.adapters`。如果后续要增加结构化输出、重试、模型路由或持久化检查点，必须先修改本契约并补测试，再决定是否扩展图节点。

## 修改代码文件与作用清单

- `backend/api/app/llm/contracts.py`：模型调用输入输出契约；
- `backend/api/app/llm/gateway.py`：LangGraph 调用图与同步/异步/流式入口；
- `backend/api/app/llm/__init__.py`：模型层公开导出；
- `backend/api/requirements.txt`：锁定 `langgraph==1.2.10`；
- `backend/api/tests/test_llm_graph.py`：图调用、异步调用、流式事件、错误脱敏测试。
