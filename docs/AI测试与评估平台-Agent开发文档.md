# AI 测试与评估平台 Agent 开发文档

> 版本：V1.2.0
> 状态：LangGraph Harness 已启用 ReAct P0/P1、P2-A/P2-B（流式参数累计、完整 ToolCall 投影、native 两回合收敛）、P3 MCP 扩展 Host、P3.1 原生基础工具直连与 P4 platform.tasks/熔断/独立沙箱 Runner
> 审查日期：2026-08-25
> 对应需求：`AI测试与评估平台-PRD.md` V1.12
> 对应接口：`AI测试与评估平台-API.md` V1.32

## 1. 当前唯一运行链路

```text
浏览器
  -> WebSocket /ws/agent（五分钟单次短票）
  -> app/routers/ws.py
  -> app/agent/graph.py（LangGraph 路由 + ReAct 图）
  -> react.py（原生 ToolCall，严格 JSON 兼容回退）→ toolnode.py（原生基础工具 / MCP 扩展）→ react.py（模型收敛）
  -> app/llm/gateway.py（LangGraph 模型调用图）
  -> app/adapters.py（三协议 HTTP 适配）
  -> 上游模型
```

本链路只有一个 Agent 入口和一个模型调用入口。ReAct 只能作为该 LangGraph 图的子图，禁止复制第二套 Harness 循环或模型客户端。

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

`app/agent/graph.py` 保持一个 LangGraph 图，模型调用只依赖 `app.llm` 的公开契约：

```text
START -> routing -> (direct | chat_stream | react_agent)
react_agent -> (tools | END)
tools -> (tools | react_agent)
```

图节点不持有数据库 Session、WebSocket 或任务队列。ToolNode 只消费可序列化 `pending_tool` / `pending_tools`、执行既有门禁与沙箱工具，并返回 Observation；同一模型响应的多个 ToolCall 在节点内串行消费，不绕过任一调用的门禁。`transport=native` 的 read/write/edit/bash/web_search/web_fetch/task 经 NativeToolExecutor 直连受控 handler；`transport=mcp` 的 `platform.tasks.task.create/status/cancel` 和后续评测/RAG 扩展经 MCPClientManager。路由层仍负责事件持久化与投影。

### 2.3 ModelGateway

`app/llm/` 提供：

- `ModelConfig`：协议、Base URL、模型、采样、超时和 reasoning 开关/强度配置；
- `ModelRequest`：不可变消息列表、系统提示词和可选取消回调；
- `NativeToolCall`：统一的 `call_id`、工具名与 JSON 参数；
- `ModelResponse`：正文、用量、原始响应、耗时和完整原生 ToolCall；
- `ModelStreamEvent`：`content`、`reasoning`、`tool_call`、`completed`；
- `ModelGateway`：基于 LangGraph 的同步、异步和流式调用入口。

三协议 HTTP 细节只允许存在于 `app/adapters.py`。API Key 不得出现在日志、事件、异常消息或模型层对象的默认 repr 中。

流式工具参数只能在 `app/adapters.py` 的单次调用内累计：OpenAI Chat 按调用索引、OpenAI Responses 按输出项、Anthropic 按内容块累计，只有 JSON 对象完整后才产生 `ModelStreamEvent(kind="tool_call")`。该内部事件用于 Agent 控制流和最终 `ModelResponse.tool_calls`，浏览器继续只接收既有的完整 `tool_call`/`tool_result`，不得新增或透传参数片段。

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
| `tool_call` | 已解析的短工具 `call_id`、名称与参数；创建 ToolCard，不直接执行业务长任务 |
| `tool_result` | 与 `tool_call.call_id` 相同的短工具受控结果；`read` 仅包含行范围、文件统计与 500 字符预览，完整正文不进入 WS 事件 |
| `error` | 脱敏后的 `ErrorCode` 与用户可见消息 |
| `pong` | 应用层心跳，不占用持久化事件号，可与业务事件交错到达 |

保留但未启用的上行事件：`confirm_ack`、`cancel_task`。当前收到后返回 `VALIDATION` 能力未启用错误。

## 4. 当前冻结范围

以下内容仍不属于当前已实施范围，不得绕过契约提前加入：

- 外部 MCP、浏览器直连 MCP、动态加载未知 MCP Server 与真正并行执行；
- 人工确认卡、权限策略、consent、安全门禁；
- Redis/pgvector 记忆、检查点和复杂上下文压缩；
- PostgreSQL 长任务入队、Worker 执行和 stress 派生；
- 未经模型变更、Alembic 自动生成与审阅的新迁移，以及 `plan.py` / `reflect.py` 等挂起模块。

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

### V0.5.3（2026-08-25）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：工具调用完成且 ReAct 判定收敛后，切换无工具自然语言流式调用，将最终正文通过 `assistant_delta` 投影；保留仅有 `invoke` 网关的非流式兜底。
- `backend/api/tests/test_agent_react.py`：增加工具调用后最终回答流式增量与完整收尾事件回归测试。

### V0.6.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：重复 `read` 达到收敛阈值时改走无工具模型总结，禁止把 Observation 原文作为 `assistant_message`；read Observation 上限提升到 120,000 字符。
- `backend/api/app/harness/execution/dispatch.py` / `registry.py`：read 改为 0-based 行级分页（默认/上限 2,000 行、120,000 字符、10MB 文件），输出结构化 `ReadResult` 与正确 `next_offset`。
- `backend/api/app/harness/contracts/artifacts.py` / `feedback/observation.py` / `execution/toolnode.py`：分离模型可见正文与 ToolCard 展示数据，完整 read 内容不写入 `ws_events`。
- `frontend/src/components/agent/ToolCard.vue`：read 卡片显示行范围、分页状态与受控预览。
- `backend/api/tests/test_agent_react.py` / `test_harness_execution.py` / `test_harness_workspace.py`：覆盖最终模型总结、行级分页、字符上限和 ToolNode 不泄露 `model_text`。
- `docs/AI测试与评估平台-API.md`：升级 V1.25，冻结 read 的 `tool_result.data` 受控投影。

### V0.7.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/llm/contracts.py` / `gateway.py`：增加统一 `NativeToolCall` 和 `ModelResponse.tool_calls`，把 `ModelRequest.tools` 透传给模型协议适配器。
- `backend/api/app/adapters.py`：实现 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 的工具 schema、完整 ToolCall 和 ToolResultMessage 双向映射；上游缺少 ID 时生成 `toolcall_<uuid>`。
- `backend/api/app/agent/react.py` / `graph.py`：原生 ToolCall 优先，保留严格 `react.v1` JSON 兼容回退；同轮多调用以队列串行执行，结果作为标准 `assistant.tool_calls` / `role=tool` 消息回传模型，工具后最终正文继续走无工具模型流式回合。
- `backend/api/app/harness/memory/state.py` / `contracts/artifacts.py` / `execution/toolnode.py`：将 `call_id` 写入可序列化状态、`tool_call`、成功/拒绝/超时失败的 `tool_result`；不修改既有 Gate、附件绑定、dispatch 或 bwrap 安全边界。
- `frontend/src/views/Agent.vue`：ToolCard 按 `call_id` 回填，只有旧历史事件缺失 ID 时才退回“同名最近 pending”兼容逻辑。
- `backend/api/tests/test_adapters.py` / `test_agent_react.py`：覆盖三协议原生 ToolCall、协议化 ToolResult 回填、同轮两个 `read` 的队列执行、`call_id` 顺序与工具后最终正文流式输出。
- `docs/AI测试与评估平台-API.md`：升级 V1.26，冻结 `tool_call` / `tool_result` 的 `call_id` 规则。

### V0.8.0（2026-08-25）修改代码文件与作用清单

- `backend/shared/models.py` / `migrations/versions/998e913697fe_新增协议档工具调用模式.py` / `schemas.py` / `routers/profiles.py`：协议档增加 `tool_call_mode=native|legacy`；迁移由 Alembic 自动生成，已有档案默认兼容模式。
- `backend/api/migrations/env.py`：仅在显式设置 `ALEMBIC_AUTOGEN_TABLES` 时按表收窄 autogenerate 对比范围，供缺少可选扩展的隔离开发库生成迁移；正常 upgrade 与生产运行不受影响。
- `backend/api/app/agent/react.py` / `harness/memory/state.py` / `routers/ws.py`：仅 `native` 协议档发送 `ModelRequest.tools`；`legacy` 固定走严格 JSON-ReAct。ReAct 保留 `agent_system_prompt`，原生工具正文仅保存在单回合临时上下文，检查点只保存关联元数据与受控 Observation。
- `backend/api/app/harness/execution/registry.py` / `toolnode.py`：执行前校验受限 JSON Schema；未知工具、参数错误、Gate 与附件绑定失败均产生带原 `call_id` 的 `tool_result`，不进入 handler、dispatch 或 bwrap。
- `backend/api/app/adapters.py`：Anthropic 同一 assistant 的多个 ToolResult 合并为一个 user 消息，符合多 `tool_use` 返回序列。
- `frontend/src/components/modals/ProfileModal.vue` / `frontend/src/api/types.ts`：协议档编辑界面暴露工具调用模式，默认兼容模式。
- `backend/api/tests/test_harness_execution.py` / `test_adapters.py` / `test_agent_react.py` / `test_profile_schemas.py`：新增模式降级、schema 拒绝、call_id 闭环、多结果适配、系统提示词和临时结果回灌回归。

### V0.9.0（2026-08-25）修改代码文件与作用清单

- `backend/shared/models.py` / `migrations/versions/998e913697fe_新增协议档工具调用模式.py` / `schemas.py` / `routers/profiles.py` / `ProfileModal.vue`：将 `tool_call_mode` 默认值统一收紧为 `legacy`；存量协议档不会在未验证时发送上游 `tools`。
- `backend/api/app/agent/react.py` / `graph.py` / `harness/execution/native_results.py` / `routers/ws.py`：完整原生 ToolResult 改存 Agent 实例内、按 `thread_id` 隔离的单回合内存；回合结束清理。模型网关仅接收取消回调配置，不接收正文、凭据或会话上下文。
- `backend/api/app/agent/react.py`：在原生 ToolCall 入队前拒绝空、空白、重复 ID、空工具名和非对象参数，归一 `UPSTREAM`。
- `backend/api/app/harness/execution/registry.py` / `toolnode.py` / `agent/log.py`：Schema 在注册期拒绝未实现关键字；ToolNode 改用注册表公开查询接口，并对附件绑定未知异常输出脱敏 `agent_trace`。
- `backend/api/tests/test_agent_react.py` / `test_harness_execution.py` / `test_profile_schemas.py`：覆盖原始结果配置隔离、空/重复 `call_id`、Schema 注册拒绝与默认兼容模式。

### V1.0.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/adapters.py`：三协议流式请求透传已验证的工具 schema，在适配器内累计工具参数片段，仅输出完整 JSON 对象的 ToolCall；无效参数归一为 `UPSTREAM`。
- `backend/api/app/llm/gateway.py`：将适配器完整 ToolCall 投影为 `ModelStreamEvent(tool_call)`，并保留到流式收尾的 `ModelResponse.tool_calls`。
- `backend/api/app/agent/react.py`：native 模式在 ToolResult 后直接使用第二个流式模型回合收敛正文或继续工具调用，消除简单路径的第三次无工具调用；不改变 WebSocket 事件契约。
- `backend/api/tests/test_adapters.py` / `test_llm_graph.py` / `test_agent_react.py`：覆盖三协议参数累计、网关工具事件、`call_id` 保留及 native 两回合流式收敛。

### V1.1.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/execution/context.py` / `native.py`：把工具运行时上下文从 MCP manager 中抽离，并新增原生基础工具直连执行器；同步 handler 进入线程池，超时/取消与 MCP 保持同一 ToolResult 契约。
- `backend/api/app/harness/execution/registry.py` / `toolnode.py` / `agent/graph.py`：新增 `transport=native|mcp`。默认 read/write/edit/bash/web_search/web_fetch/task 走 native；只有评测/RAG 等未来扩展有 `transport=mcp` 时才构建 MCP manager。
- `backend/api/app/harness/execution/dispatch.py`：read 改为不保留整文件副本的单次扫描；write/edit 使用排他/原子写；web_search 使用 API 容器 Firecrawl Key，web_fetch 每跳重检 SSRF；task 仅产出会话内计划。
- `backend/api/app/routers/mcp.py` / `frontend/src/views/AdminProfiles.vue`：MCP 清单只展示扩展；基础工具不在目录中。
- `frontend/src/components/agent/ToolCard.vue`：补基础工具中文名称和 task/web 的受控卡片展示。
- `backend/api/tests/test_harness_execution.py` / `test_harness_mcp.py`：覆盖原生直连与 MCP 目录隔离、Firecrawl、安全抓取、原子写入和任务拆解。

### V1.2.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/execution/registry.py`：在七项原生基础工具外保留 `transport=mcp` 的 `platform.tasks.task.create/status/cancel`，避免将对话拆解和评测任务队列混为同一能力。
- `backend/api/app/harness/execution/task_tools.py` / `mcp/metrics.py`：评测任务 MCP 的会话归属、队列门禁、配额、审计、熔断和度量继续生效。
- `backend/api/app/harness/execution/sandbox.py` / `backend/runner/`：bash 仍由独立 Runner 调用 bwrap，API 不降级为裸 subprocess。
- `backend/api/app/routers/mcp.py` / `frontend/src/views/AdminProfiles.vue`：目录仅展示当前 `platform.tasks` 与未来扩展，基础工具仍走原生调用。
