# AI 测试与评估平台 Agent 开发文档

> ⚠️ **文档维护提示（2026-09-11）**：本文部分章节含历史实现引用（`agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除，ReAct / Plan-Solve 图已由 AgentLoop v2 取代）；当前实现与契约以 `AGENTS.md` 状态地图及本文最新修订为准。

> 版本：V1.7.7
> 状态：新建会话统一使用 AgentLoop v2；历史 legacy 行仅保留审计与显式回放路径。此前骨架化与混合引擎说明属于 legacy 路径及其历史阶段，不能据此认定新路径仍为纯对话。前端输入栏按每回合协议档选择模型和思考强度，完整真实供应商/Linux Runner 联调验收仍未结束。
> 审查日期：2026-09-11
> 对应需求：`AI测试与评估平台-PRD.md` V1.19
> 对应接口：`AI测试与评估平台-API.md` V1.93

## 1. legacy 骨架化运行链路（历史基线）

```text
浏览器
  -> WebSocket /ws/agent（五分钟单次短票）
  -> app/routers/ws.py
  -> app/agent/graph.py（LangGraph 纯对话图）
  -> routing.py（chat_stream_node：assemble 装配上下文 → ModelGateway 流式生成）
  -> app/llm/gateway.py（LangGraph 模型调用图）
  -> app/adapters.py（两类协议 HTTP 适配）
  -> 上游模型
```

本链路只有一个 Agent 入口和一个模型调用入口，全链路不注入任何工具定义，不产生思考链/确认卡/澄清卡事件。

## 2. 分层边界

### 2.1 WebSocket Bridge

`app/routers/ws.py` 只负责：

- 消费 `POST /api/auth/ws-ticket` 签发的五分钟单次票据（Redis `SET NX` + TTL，Redis 不可用时回退进程内存）；
- 校验会话可见性，支持首次连接创建私有会话；
- 保存 `messages` 与 `ws_events`，按 `last_event_id` 补发历史事件；
- 在后台 Task 中启动单轮 Agent，不阻塞 WebSocket `receive` 循环；
- 将 LangGraph 流事件投影为 `user_message`、`assistant_delta`、`assistant_message`、`response.completed`、`error`、`pong`；平台取消成功由收包循环另发 `task_cancelled`（骨架化后不再产生 `thought` / `tool_*` / `confirm` / `clarify` 等事件）；
- `cancel_task` 由收包循环直连，不在 api 进程执行评测或压测。

路由不得直接调用 `app.adapters`，不得执行 Benchmark、RAG、用例生成或压测。

### 2.2 Agent Graph

`app/agent/graph.py` 保持一个 LangGraph 图，模型调用只依赖 `app.llm` 的公开契约：

```text
START -> chat_stream -> END
```

骨架图只有一个 `chat_stream_node`（`app/agent/routing.py`）：`assemble` 装配
Persona / Skill Hint / 会话摘要 / 历史消息后，直接调用 `ModelGateway.stream()`
流式生成，正文增量经 `assistant_delta` 投影，收尾产出
`assistant_message` + `response.completed`。不再有 `decide_mode` 范式路由、
ReAct 循环、Plan/reflect 节点、工具节点、澄清卡与确认卡。

图节点不持有数据库 Session、WebSocket 或任务队列；节点只返回纯数据
（`pending_events` / `response` 投影），事件持久化与广播由 ws.py 负责。
`/stop` 即时中断保留在收包循环（不进入图），其余斜杠命令已移除。

### 2.3 ModelGateway

`app/llm/` 提供：

- `ModelConfig`：协议、Base URL、模型、采样、超时和 reasoning 开关/强度配置；
- `ModelRequest`：不可变消息列表、系统提示词和可选取消回调；
- `NativeToolCall`：统一的 `call_id`、工具名与 JSON 参数；
- `ModelResponse`：正文、用量、原始响应、耗时和完整原生 ToolCall；
- `ModelStreamEvent`：`content`、`reasoning`、`tool_call`、`completed`；
- `ModelGateway`：基于 LangGraph 的同步、异步和流式调用入口。

两类协议 HTTP 细节只允许存在于 `app/adapters.py`。API Key 不得出现在日志、事件、异常消息或模型层对象的默认 repr 中。

骨架化后 Agent 不再注入工具定义、不消费 `ModelStreamEvent(kind="tool_call")`；
模型层仍保留原生 ToolCall 契约（供 Worker/未来扩展复用），但浏览器与 Agent 图
均不接收工具事件。正文流式投影：`ModelStreamEvent(kind="content")` 以
`assistant_delta` 瞬时广播，`completed` 收尾产出 `assistant_message`。

Agent 思考配置从 `Setting(key="agent_reasoning")` 读取，结构为
`{"enabled": true, "effort": "medium"}`。开启时，OpenAI Chat 的兼容推理模型使用
`reasoning_effort`，Gemini OpenAI 兼容端点使用
`extra_body.google.thinking_config`，DeepSeek / Mimo 与 Anthropic 使用各自的思考字段；
骨架化后不再投影 `thought` 事件，前端不渲染任何思考摘要。关闭时网关过滤
reasoning 事件，并对已知支持显式关闭的端点发送关闭参数。Gemini 的
`xhigh/max` 映射为 `high`。

## 3. 首期 WebSocket 事件

已实现服务端事件（骨架化后收敛为纯对话 + 平台任务流）：

| 事件 | 作用 |
| --- | --- |
| `user_message` | `role=user` 的用户消息落库并向会话在线成员广播；服务端不再使用含义不明确的 `message` |
| `assistant_delta` | 助手正文瞬态增量，仅向在线会话成员广播，不占事件号 |
| `assistant_message` | 助手完整交付句，落库并占用会话事件号 |
| `response.completed` | 本轮生成结束，携带 `finish_reason` 和 `role=assistant` 并可回放 |
| `task_cancelled` | 任务取消已持久化；公共头携带 `task_id`，payload 含 `status` 与 `kind` |
| `error` | 脱敏后的 `ErrorCode` 与用户可见消息 |
| `pong` | 应用层心跳，不占用持久化事件号，可与业务事件交错到达 |

平台任务流（Worker 直产，`_forward_loop` 推送，与骨架 Agent 无关）：
`progress`（任务进度）、`report`（评测报告）、带 `task_id` 的 `error`（任务失败）。

上行已启用：`user_message`、`cancel_task`（直连取消任务）。`/stop` 以
`user_message` 文本上行，由收包循环即时中断。

## 4. 当前冻结范围

以下内容仍不属于当前已实施范围，不得绕过契约提前加入：

- 多范式路由、ReAct 思考链、reflect 反思、think_stream 展示、澄清卡、确认卡、短工具调用与斜杠命令（骨架化后已整体移除，恢复需先回写 PRD/API 再实现）；
- 外部通知渠道（企微/邮件/Webhook）与 Grafana 抓取编排；
- PostgreSQL Checkpointer 多副本粘性路由（默认仍为 memory）；
- 未经模型变更、Alembic 自动生成与审阅的新迁移。

## 5. 后续扩展门禁

1. 新增 Harness 前先定义独立的输入、输出、事件、取消和错误契约；
2. 新增 MCP、确认卡或范式路由前先同步 PRD 与 API，再实现 API 层门禁；
3. 长任务只能入 PostgreSQL 队列，由 Worker 执行，API 进程不等待终态；
4. 所有异常统一为十类 `ErrorCode`，不得把 traceback、SQL 或上游原文发送给浏览器；
5. 扩展 Agent 只能在 LangGraph 图中增加节点/边，禁止保留旧路径或复制协议适配。

## 修改代码文件与作用清单

- `backend/api/app/agent/graph.py`：LangGraph 单轮 Agent 图（骨架化：`START → chat_stream → END`）；
- `backend/api/app/agent/routing.py`：纯对话流式节点 `chat_stream_node`（骨架化后唯一节点）；
- `backend/api/app/routers/ws.py`：WebSocket 鉴权、会话事件与后台 Agent 回合（骨架化：移除 thought/clarify/tool_approval/confirm/斜杠逻辑）；
- `backend/api/app/session_connections.py`：会话内事件和流增量广播；
- `backend/api/tests/test_agent_graph.py`：Agent 图回归测试；
- `frontend/src/api/ws.ts`：识别 `assistant_delta` 瞬态帧并跳过事件号去重；
- `frontend/src/api/types.ts`：补充 `user_message`、`assistant_delta`、`assistant_message`、`response.completed` 事件类型；
- `frontend/src/views/Agent.vue`：纯对话消息流（移除思考卡/工具卡/确认卡/澄清卡/斜杠面板）。

### V1.6.0（2026-09-02）骨架化改造修改代码文件与作用清单

**后端（Agent 骨架化）**：

- `backend/api/app/agent/graph.py`：重写为纯对话图 `START → chat_stream → END`；删除 routing/react/plan_solve/reflect/clarify/tools 节点；
- `backend/api/app/agent/routing.py`：只保留 `chat_stream_node`（assemble → ModelGateway 流式生成 → `assistant_message` + `response.completed`）；删除 `routing_node`/`route`/`direct_node`；
- 删除 `backend/api/app/agent/react.py`、`plan_solve.py`、`reflect.py`、`think_stream.py`、`clarify.py`；
- `backend/api/app/routers/ws.py`：删除 think 流、`__interrupt__` 翻译（clarify/tool_approval）、confirm 事件与 `confirm_ack`、斜杠命令（/help /compact /cancel /stress）、`_handle_clarify_*`/`_handle_tool_approval_*`/`_persist_pending_confirm`/`_confirm_author_payload`；保留 `/stop` 即时中断与 `cancel_task`；
- 删除 `backend/api/app/routers/slash_commands.py`、`backend/api/app/harness/memory/slash_store.py`；`main.py` 移除斜杠路由注册；`schemas.py` 删除 `SlashCommandCreate`。

**测试**：

- 删除 `test_agent_react.py`、`test_agent_routing.py`、`test_agent_clarify.py`、`test_think_stream.py`、`test_ws_clarify.py`、`test_plan_budget_task_state.py`、`test_harness_phase4.py`、`test_confirm_ack.py`、`test_slash_commands.py`；
- 改写 `test_agent_multiturn.py`（纯对话多轮）、`test_ws_protocol.py`（移除确认卡/斜杠用例）、`test_harness_prompts.py`（移除 ReAct stage input 用例）。

**前端（同步拆除）**：

- 删除组件 `ThoughtCard.vue`、`ToolCard.vue`、`PlanCard.vue`、`ClarifyCard.vue`、`ConfirmCard.vue`、`ToolApprovalCard.vue`、`SlashPalette.vue`、`TaskStateDrawer.vue`、`Composer.vue`；
- 删除 `agent/slashRegistry.ts`、`utils/toolCard.ts`；
- `Agent.vue` 重写为纯对话消息流（保留会话管理、附件、模型切换、ContextMeter、进度坞、报告卡）；
- `ws.ts` 删除 `sendConfirmAck`/`sendClarifyReply`/`sendToolApprovalAck`；`types.ts` 收窄 `WsServerEvent`；`http.ts` 移除 `/api/slash-commands`。

**文档**：

- `docs/AI测试与评估平台-Agent开发文档.md`：同步骨架化链路、事件表与冻结范围（本文档 V1.6.0）；AGENTS.md 状态地图同步。

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
- `backend/api/app/adapters.py`：按 OpenAI Chat、Mimo、Anthropic 协议映射思考参数；
- `frontend/src/views/AdminProfiles.vue` / `frontend/src/api/types.ts` / `frontend/src/api/mockData.ts`：增加管理页设置、类型与 Mock 数据；
- `backend/api/tests/test_adapters.py` / `backend/api/tests/test_llm_graph.py`：覆盖思考强度映射和关闭行为。

### V0.5.1（2026-08-24）修改代码文件与作用清单

- `docs/AI测试与评估平台-Agent开发文档.md`：头部版本与对应接口同步为 API.md V1.22（Harness 契约收敛，纯文档变更，无功能改动）。

### V0.5.2（2026-08-24）修改代码文件与作用清单

- `backend/api/app/agent/attachments.py`：校验消息附件归属，解析文本、PDF、DOCX、XLSX，并把图片转换为内部图文内容块；解析结果只进入模型请求，不覆盖用户原文。
- `backend/api/app/routers/ws.py`：将用户消息附件注入 Harness 模型窗口，支持附件-only 消息并持久化安全预览元数据。
- `backend/api/app/adapters.py`：将内部图文内容块适配为 OpenAI Chat 与 Anthropic Messages 请求格式。
- `backend/api/app/routers/sessions.py` / `frontend/src/api/types.ts`：历史回放返回并消费附件文件名、大小、类型和内容地址，刷新后仍可预览。
- `backend/api/tests/test_agent_attachments.py`：覆盖文本注入、图片内容块和两类协议格式转换。

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
- `backend/api/app/adapters.py`：实现 OpenAI Chat Completions、Anthropic Messages 的工具 schema、完整 ToolCall 和 ToolResultMessage 双向映射；上游缺少 ID 时生成 `toolcall_<uuid>`。
- `backend/api/app/agent/react.py` / `graph.py`：原生 ToolCall 优先，保留严格 `react.v1` JSON 兼容回退；同轮多调用以队列串行执行，结果作为标准 `assistant.tool_calls` / `role=tool` 消息回传模型，工具后最终正文继续走无工具模型流式回合。
- `backend/api/app/harness/memory/state.py` / `contracts/artifacts.py` / `execution/toolnode.py`：将 `call_id` 写入可序列化状态、`tool_call`、成功/拒绝/超时失败的 `tool_result`；不修改既有 Gate、附件绑定、dispatch 或 bwrap 安全边界。
- `frontend/src/views/Agent.vue`：ToolCard 按 `call_id` 回填，只有旧历史事件缺失 ID 时才退回“同名最近 pending”兼容逻辑。
- `backend/api/tests/test_adapters.py` / `test_agent_react.py`：覆盖两类协议原生 ToolCall、协议化 ToolResult 回填、同轮两个 `read` 的队列执行、`call_id` 顺序与工具后最终正文流式输出。
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

- `backend/api/app/adapters.py`：两类协议流式请求透传已验证的工具 schema，在适配器内累计工具参数片段，仅输出完整 JSON 对象的 ToolCall；无效参数归一为 `UPSTREAM`。
- `backend/api/app/llm/gateway.py`：将适配器完整 ToolCall 投影为 `ModelStreamEvent(tool_call)`，并保留到流式收尾的 `ModelResponse.tool_calls`。
- `backend/api/app/agent/react.py`：native 模式在 ToolResult 后直接使用第二个流式模型回合收敛正文或继续工具调用，消除简单路径的第三次无工具调用；不改变 WebSocket 事件契约。
- `backend/api/tests/test_adapters.py` / `test_llm_graph.py` / `test_agent_react.py`：覆盖两类协议参数累计、网关工具事件、`call_id` 保留及 native 两回合流式收敛。

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

### V1.3.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/orchestration/router.py`：`detect_plan_intent` + `decide_mode` 接线 `plan_solve`；附件仍强制 ReAct。
- `backend/api/app/agent/routing.py` / `plan_solve.py`：路由传入多槽判定；规划节点调用 `build_plan`，禁止假 `tool_call`。
- `backend/api/app/agent/react.py`：ReAct / native 阶段输入改为 Observe → Think → Act。
- `backend/api/app/harness/contracts/artifacts.py` / `feedback/observation.py` / `context/observation.py`：`Observation.repair_hint` 只进模型摘要。
- `backend/api/app/harness/execution/dispatch.py` / `registry.py`：edit 失败带邻近行修复建议；read/edit/task 描述补适用与前置条件。
- `backend/api/tests/test_agent_routing.py` / `test_agent_react.py` / `test_harness_*.py`：覆盖分流、规划事件、OTA 提示词与 repair_hint。

### V1.3.1（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/orchestration/plan.py`：L0 合并全部命中技能，产出 3–7 步；`tools_needed` 只含短工具 `task`。
- `backend/api/app/agent/plan_solve.py` / `graph.py`：成功规划后进入 ReAct；失败就地 `response.completed`；`plan` 事件下发完整 PlanArtifact。
- `backend/api/app/agent/react.py`：有 `plan` 时注入【当前规划】且不发 `response.completed`；`react_route` 收尾进 reflect。
- `backend/api/app/agent/reflect.py`：有计划回合由本节点发出唯一 `response.completed`（reject 为 `finish_reason=error`）。
- `backend/api/tests/test_agent_routing.py` / `test_harness_phase4.py`：覆盖规划→执行→复核事件序与多技能合并。
- 审查修复：规划路径 ReAct 硬错误发 `completed(error)` 且不再进 reflect；失败规划清空 `plan`；`plan.budget` 写入图预算；`LangGraphAgent.invoke` 接受 `plan_solve`。

### V1.4.0（2026-08-25）修改代码文件与作用清单

- `docs/AI测试与评估平台-API.md`：V1.33 单回合多条 `assistant_message` + `interim`。
- `backend/api/app/agent/react.py`：native 同轮正文+ToolCall 先发阶段叙述。
- `backend/api/app/agent/reflect.py` / `graph.py` / `clarify.py` / `plan_solve.py`：clarify interrupt、有界重规划回 `plan_solve`。
- `backend/api/app/config.py` / `harness/memory/checkpoint.py`：`AGENT_CHECKPOINTER` 默认 memory。
- `frontend/src/views/Agent.vue`：多段助手正文与 `plan.slots.steps` 清单回放。

### V1.4.1（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/execution/dispatch.py`：`read` 窗口收齐后按块统计剩余行/字符，不再对大文档逐行扫完全文。
- `backend/api/app/harness/execution/registry.py`：`read` 超时 10s→20s，描述标明大文件分页。
- `backend/api/app/harness/context/observation.py`：原生工具回传模型统一 8,000 字符上限。
- `backend/api/app/harness/execution/sandbox.py` / `dispatch.py`：bash/web 窗口与该上限对齐；`read` 未读完时 `model_text` 带 `next_offset`。
- `backend/api/app/agent/react.py` / `toolnode.py`：hydrate 截断兜底；追踪工具耗时、模型耗时与 payload 字符数。
- `docs/AI测试与评估平台-API.md`：V1.34。
- `backend/api/tests/test_harness_execution.py` / `test_agent_react.py`：覆盖大文档分页、回传截断。

### V1.5.0（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/orchestration/confirm_spec.py` / `app/agent/reflect.py`：`delivery=confirm` 且复核通过后发出 TaskSpec 确认卡；`kind` 不得为 `stress`。
- `backend/api/app/routers/ws.py`：确认卡补 `confirm_author`；短票 jti 走 Redis 单次消费。
- `backend/api/app/ws_tickets.py`：`SET NX` + TTL，Redis 不可用回退进程内存。
- `backend/worker/app/stress.py` / `main.py`：压测下发 stress 容器，取消立即停发，报告含 `time_series`。
- `backend/stress/main.go`：真实 HTTP 发压、`/status` `/stop`、Prometheus 指标。
- `docker-compose.yml` / `.env.example`：Worker 注入 `STRESS_URL`。
- `backend/api/tests/test_harness_phase4.py` / `test_ws_tickets.py` / `backend/worker/tests/test_stress.py`：确认卡、短票、压测映射回归。

### V1.5.1（2026-08-25）修改代码文件与作用清单

- `backend/api/app/harness/context/meter.py`：`compute_meter` 按窗口消息估算 token，字段对齐 API.md §3.4。
- `backend/api/app/routers/sessions.py`：`GET .../messages` 下发真实 `context_meter`，不再返回 `null`。
- `frontend/src/components/agent/ContextMeter.vue` / `api/types.ts`：`compacted` 徽标与类型。
- `docs/AI测试与评估平台-API.md`：V1.36。
- `docs/AI测试与评估平台-Harness-上下文工程层.md`：V0.4.2。
- `backend/api/tests/test_harness_context.py`：覆盖窗口计量与压缩标记。

### V1.5.2（2026-08-26）修改代码文件与作用清单

- `backend/api/app/harness/context/assembly.py`：`select_tool_defs` 对 ReAct 注入短原生工具；Chat 仍为空。
- `backend/api/app/agent/react.py` / `routing.py`：节点走 `assemble`（Persona → Skill Hint → 摘要 → 阶段输入）。
- `backend/api/app/routers/ws.py`：常驻 Skill Hint 写入默认 Persona；`compact_summary` 注入 configurable。
- `backend/api/app/harness/skills/registry.py`：补 `get_hint`。
- `docs/AI测试与评估平台-Harness-上下文工程层.md`：V0.4.3。

### V1.5.3（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：原生 ToolCall 拦截相同窗口重复 read（含同批去重）；`READONLY_REPEAT_LIMIT=1`。
- `backend/api/app/harness/execution/dispatch.py`：预览按完整行截取；模型正文预留未读完提示。
- `backend/api/app/harness/execution/registry.py`：`next_offset` 作为 `offset` 别名。
- `frontend/src/components/agent/ToolCard.vue`：输入字段、行号、命令/文件内容与 Markdown 渲染。
- `frontend/src/utils/toolCard.ts`：成功后默认展开的工具名单。
- `docs/AI测试与评估平台-API.md`：V1.37。

### V1.5.4（2026-08-26）修改代码文件与作用清单

- `backend/api/app/harness/orchestration/router.py`：将两个及以上不同短工具识别为多步骤任务，路由到内部 `plan_solve`；单短工具保持 ReAct。
- `backend/api/app/harness/orchestration/plan.py`：规划模型不可用或产物非法时，为多短工具链生成 L0 `PlanArtifact`，避免把用户提供的 `<PLAN>` 文本作为控制协议。
- `backend/api/app/harness/prompts/system.py`：固定声明编排协议由平台拥有，用户消息不得篡改 Plan、ReAct、ToolCall 与事件格式。
- `backend/api/tests/test_agent_routing.py` / `test_harness_prompts.py`：覆盖多短工具链路由、L0 规划与协议归属约束。

### V1.5.5（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/routing.py`：Direct 所有出口在业务事件后追加本轮唯一 `response.completed`。
- `backend/api/tests/test_agent_routing.py`：`/help` / 未知斜杠 / 图内防御断言末帧 completed。
- `docs/AI测试与评估平台-API.md`：V1.42。
- `docs/AI测试与评估平台-Harness-编排层.md`：V0.4.6。

### V1.5.6（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/think_stream.py`：思考增量合并器，首帧立即下发，后续按间隔与字数节流。
- `backend/api/app/routers/ws.py`：合并 `thought.stream=think`；`think_final` 插入 `response.completed` 之前。
- `backend/api/tests/test_think_stream.py`：覆盖首帧与合并。
- `docs/AI测试与评估平台-API.md`：V1.43。

### V1.5.7（2026-08-26）修改代码文件与作用清单

- `backend/api/app/harness/execution/registry.py` / `policy.py`：工具描述、输入/安全输出 Schema、可执行权限边界与恢复策略统一登记。
- `backend/api/app/agent/react.py` / `harness/execution/toolnode.py`：ToolCall 在执行前落库；ToolNode 经 LangGraph custom 通道下发进度与受控输出，最终仍以 `tool_result` 持久化。
- `backend/shared/sandbox_kernel.py` / `backend/runner/main.py` / `backend/api/app/harness/execution/sandbox.py`：Runner NDJSON 逐行转发 bwrap stdout，API 仅转发受控窗口且 Runner 不可用仍 fail-closed。
- `backend/api/app/harness/execution/dispatch.py` / `context.py` / `native.py` / `feedback/observation.py`：read/write/bash 输出投影、运行期回调与结构化恢复信息。
- `backend/api/app/routers/ws.py`：`tool_progress`、`tool_output_delta` 仅向在线会话成员转发，不落库、不补发。
- `frontend/src/views/Agent.vue` / `components/agent/ToolCard.vue` / `api/types.ts`：实时行号输出、阶段加载态、失败恢复建议及 `call_id`/`seq` 去重。
- `docs/AI测试与评估平台-API.md`：V1.44，冻结工具流、输出、权限与恢复契约。
- `backend/api/tests/test_harness_execution.py` / `test_sandbox_runner_client.py` / `backend/runner/tests/test_runner.py`：覆盖工具策略登记、ToolNode custom 帧与 Runner NDJSON 端点。

### V1.5.8（2026-08-26）修改代码文件与作用清单

- `backend/api/app/harness/skills/workflows.py`：启用技能完整工作流正文，按 `skill_id` 按需加载。
- `backend/api/app/harness/context/assembly.py`：`skill_hints_for_turn`；`assemble` 可选【当前技能工作流】。
- `backend/api/app/agent/react.py` / `plan_solve.py`：选中技能注入正文；`skill-rag` 规划即 VALIDATION。
- `backend/api/tests/test_harness_skills.py`：K-A1~K-A5。

### V1.5.9（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/think_stream.py`：隐藏 CoT 收成可展示摘要；流式暂扣包装头。
- `backend/api/app/routers/ws.py`：think / think_final 走 `sanitize_reasoning`。
- `backend/api/tests/test_think_stream.py` / `test_harness_probe_l2.py`：替换与探针拒绝原文。
- `docs/AI测试与评估平台-API.md`：V1.45。

### V1.5.10（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：native 首轮改走 `gateway.stream()`，工具前正文实时投影，完整 ToolCall 仍在响应结束后入队。
- `backend/api/tests/test_agent_react.py` / `test_llm_graph.py` / `test_adapters.py`：覆盖首轮交错流、两类协议 text→tool_call 夹具。
- `docs/AI测试与评估平台-API.md`：V1.46，冻结「ToolCall 结束当前上游响应」。
- `docs/AI测试与评估平台-Agent内容块交错流式调用规划.md`：V0.2，P1 落地对照。

### V1.5.11（2026-08-26）修改代码文件与作用清单

- `backend/api/app/harness/execution/batch.py`：可序列化 ToolBatch（batch_id / block_index / 终态）。
- `backend/api/app/harness/execution/toolnode.py` / `memory/state.py` / `agent/react.py`：同轮调用入批次，全部终态后按原顺序一次性回填；执行仍串行。
- `backend/api/tests/test_harness_execution.py` / `test_agent_react.py`：覆盖乱序标记保序、失败+成功同批、read+write 回填。
- `docs/AI测试与评估平台-Agent内容块交错流式调用规划.md`：V0.3，P2 落地。

### V1.5.12（2026-08-26）修改代码文件与作用清单

- `backend/api/app/config.py` / `.env.example` / `docker-compose.yml`：`AGENT_PARALLEL_TOOL_BATCH_ENABLED` 默认 false，`MAX_PARALLEL_TOOL_CALLS` 默认 3。
- `backend/api/app/harness/execution/registry.py`：`ToolDef.concurrency_class` / `requires_prior_result`；不投影到 `all_defs` / `to_descriptor`。
- `backend/api/app/harness/execution/batch.py` / `toolnode.py`：规范化路径资源键、只读波次 `TaskGroup`、单项失败隔离；无批次时仍一次一项。
- `backend/api/tests/test_harness_execution.py`：开关关闭串行、独立 read 重叠、失败不取消同组、bash/写/task.create 屏障。
- `docs/AI测试与评估平台-Agent内容块交错流式调用规划.md`：V0.4，P3 落地、flag 默认关。

### V1.5.13（2026-08-26）修改代码文件与作用清单

- `backend/api/app/harness/execution/stream_policy.py` / `stream_metrics.py`：协议档白名单、脱敏指标、并行脚踢线（冷却恢复，不改历史事件）。
- `backend/api/app/config.py` / `.env.example` / `docker-compose.yml`：`AGENT_NATIVE_STREAM_*` 与 `AGENT_PARALLEL_TOOL_BATCH_PROFILE_IDS`。
- `backend/api/app/agent/react.py` / `harness/execution/toolnode.py` / `routers/ws.py`：按协议档决定流式/并行；`configurable.profile.id`。
- `backend/api/app/routers/agent_prefs.py`：`GET /api/agent/metrics`。
- `backend/api/tests/test_stream_rollout.py` / `test_agent_react.py` / `test_harness_execution.py`：灰度、脚踢、invoke 回退。
- `docs/AI测试与评估平台-API.md`：V1.47；规划稿 V0.5。

### V1.5.14（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：流式成功不再提前 `record_stream`；call_id 校验后再记一笔终态，关联错乱可累计脚踢。
- `backend/api/tests/test_stream_rollout.py` / `test_agent_react.py`：连续 associate_error 触发脚踢；流式空 call_id 两轮 `rounds==2`。
- `docs/AI测试与评估平台-API.md`：V1.48，§4.3 默认串行、灰度只读并行。
- `docs/AI测试与评估平台-Agent内容块交错流式调用规划.md`：V0.6。

### V1.5.15（2026-08-26）修改代码文件与作用清单

- `backend/api/tests/test_stream_p3_integration.py`：真实 bwrap bash 串行屏障、`last_event_id` 重连不补瞬态、team 会话瞬态广播范围、ToolCard call_id 乱序回填契约。
- `frontend/src/utils/toolCard.ts` / `views/Agent.vue`：直播与历史回放共用 `findPendingToolItem`，禁止同名工具串卡。
- `docs/AI测试与评估平台-Agent内容块交错流式调用规划.md`：V0.7。

### V1.5.16（2026-08-27）修改代码文件与作用清单

- `backend/api/app/harness/execution/registry.py`：read 工具描述与 `limit` 参数说明新增正向引导——除局部行段外省略 limit 一次读完（单次上限 2000 行 / 600000 字符），禁止人为拆成多个小窗口连续多次读取；治理模型自选 200 行小页分页、多轮浪费模型调用预算的行为。
- `backend/api/app/agent/react.py`：`REACT_STAGE_INPUT` / `NATIVE_TOOL_STAGE_INPUT` 同步补一次读完约束；`_inject_observations` 对 read 观察豁免最近 6 条条数上限（分页读取全页保留到最终回答阶段，避免模型只见尾部页导致回答内容不全），新增 `INJECT_READ_TOTAL_MAX_CHARS=1_200_000` 总字符熔断，超预算优先保留较新的页；非 read 观察仍只注入最近 6 条。
- `backend/api/tests/test_agent_react.py`：新增阶段输入/工具描述引导断言、read 观察全页注入与总字符熔断回归。

### V1.5.17（2026-08-27）修改代码文件与作用清单

- `backend/api/app/routers/files.py`：附件上传改为 1MB 分块写入、流式计算 SHA-256 并原子发布，避免把 20MB 文件一次性读入 API 内存。
- `backend/api/app/agent/attachments.py`：TXT/Markdown/HTML/JSON/YAML/CSV/JSONL 统一 staging 到会话工作区；以独立副本替代上传卷硬链接，防止 bash 原地写入污染原附件。
- `backend/api/app/harness/execution/dispatch.py` / `registry.py`：`read` 文件大小上限与附件接口统一为 20MB；单次窗口仍固定为 2,000 行 / 600,000 字符。
- `frontend/src/api/http.ts` / `views/Agent.vue` / `components/agent/AttachmentPreview.vue`：上传过程回传并显示百分比。
- `frontend/src/components/modals/ProfileModal.vue`：新建协议档默认 native ToolCall；既有协议档保持保存值，需按上游能力手工选择 legacy 回退。
- `docs/AI测试与评估平台-API.md`：升级 V1.50，同步 read 边界与附件链路契约。
- `backend/api/tests/test_files.py` / `test_agent_attachments.py` / `test_harness_execution.py`：覆盖分块上传、结构化文本 staging、工作区副本隔离与 20MB read 契约。

### V1.5.18（2026-08-26）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：native 流式若收到 JSON ReAct，不把协议 JSON 投影为助手正文；按 native ToolCall 排入 ToolBatch，read 完整正文按 call_id 回填下一轮。
- `backend/api/tests/test_agent_react.py`：覆盖 native 流式 JSON ReAct read 回填附件正文。

### V1.5.19（2026-08-27）修改代码文件与作用清单

- `frontend/src/api/ws.ts`：将 `tool_progress` / `tool_output_delta` 按瞬态帧处理，避免复用连接游标时被 `event_id` 去重误丢。
- `backend/api/tests/test_agent_react.py`：覆盖 `web_search` / `web_fetch` 原生 ToolCall 与同 `call_id` 的 `tool_result` 事件契约。

### V1.5.20（2026-08-27）修改代码文件与作用清单

- `backend/api/app/harness/orchestration/router.py`：识别明确的链接访问/爬取动作并路由到 ReAct，普通 URL 提及仍保持 Chat。
- `backend/api/tests/test_agent_routing.py`：覆盖链接抓取路由与普通 URL 聊天不误触发工具。

### V1.5.21（2026-08-27）修改代码文件与作用清单

- `backend/api/app/harness/orchestration/router.py`：将点名的 `write` / `edit` / `bash` / `task` 等单个基础工具路由至 ReAct，保留多工具链走 Plan-and-Solve。
- `backend/api/tests/test_agent_routing.py`：覆盖单个基础工具的直接路由，确保能产生 ToolCall 卡片。
- `backend/api/tests/test_agent_react.py`：覆盖全部七个原生基础工具在参数校验失败时仍以相同 `call_id` 关联 `tool_call` 与 `tool_result`。

### V1.5.22（2026-08-27）修改代码文件与作用清单

- `frontend/src/components/agent/MarkdownView.vue`：流式正文按动画帧合并 Markdown 更新，Mermaid 仅在正文稳定后渲染；完整独立 JSON 自动展示为结构化内容。
- `frontend/src/components/agent/StructuredDataView.vue`：新增安全投影的字段树与对象数组表格视图，可复制 JSON，并限制深度和单层展开数量；空对象/数组有明确状态，嵌套视图使用紧凑样式。
- `frontend/src/components/agent/ToolCard.vue`：通用 ToolCall 参数及无文本预览的工具结果改用结构化视图；文件、网页、命令等受控文本预览保持原有行号与 Markdown 渲染。

### V1.5.23（2026-08-29）修改代码文件与作用清单

- `frontend/src/components/agent/ToolCard.vue`：edit 工具成功结果新增专用摘要卡（成功图标 + 文件路径徽章 + 替换处数与字符数变化胶囊），替代通用 JSON 字段树的低对比度展示；edit 结果为静态摘要，跳过 JSON 打字机动画；样式全部使用设计令牌，明暗主题自适应。

### V1.5.24（2026-08-30）修改代码文件与作用清单

- `backend/api/app/harness/skills/files/<skill_id>/SKILL.md`：四个内置技能统一为固定六码头部（`id/name/kind/version/enabled/summary`）与 `## 工作流` 正文；运行时副本位于 `AGENT_SKILLS_ROOT`（容器默认 `/data/skills`）。
- `backend/api/app/harness/skills/storage.py`：读取前先验证单个 `SKILL.md` 存在；目录只读取 8KB 头部，完整工作流仅在选中 `plan.skill_id` 后读取；编辑校验规格、禁止启用 RAG、以 SHA-256 修订指纹和原子替换避免覆盖。
- `backend/api/app/harness/skills/registry.py` / `workflows.py` / `context/assembly.py` / `agent/react.py`：Skill Hint 不携带正文，图状态只保存 `skill_id`，按回合最小装配工作流，未启用技能继续返回 `VALIDATION`。
- `backend/api/app/routers/admin.py` / `agent_prompt_settings.py`：新增 `/api/admin/skills*` 与 `/api/admin/agent-prompts/{profile_id}`；文件与提示词写入均做最小审计，审计明细不保存正文或密钥。
- `backend/api/app/harness/prompts/system.py` / `routers/ws.py`：核心系统策略始终由 Harness 生成；各 Agent 协议档只能注入受审计的补充提示词，核心安全、权限、错误契约和任务状态机始终优先。
- `backend/api/tests/test_harness_skills.py` / `test_harness_prompts.py`：覆盖技能文件缺失拒绝、头部/全文两阶段读取、RAG 禁用与补充提示词优先级说明。

### V1.5.25（2026-08-31）修改代码文件与作用清单

- `backend/api/app/harness/execution/dispatch.py` / `feedback/rules.py`：将 `rm`、权限与文件变更命令从硬拒绝改为 HITL 候选；保留提权、网络和远程连接命令的硬黑名单，且多段命令不能绕过。
- `backend/api/app/harness/execution/toolnode.py`：危险 bash 在全部校验后、Runner 副作用前调用 LangGraph `interrupt()`；只接受同 call_id 的批准/拒绝，拒绝产出 `tool_result.status=rejected`。
- `backend/api/app/routers/ws.py`：新增 `tool_approval` / `tool_approval_ack` 事件和会话内待确认关联，确认后使用 `Command(resume=...)` 恢复原图检查点。
- `backend/api/app/agent/think_stream.py` / `react.py`：原始 reasoning 仅保留服务端处理，浏览器最多展示一次过程摘要；带 ToolCall 的流式正文先缓冲，避免工具终态前出现成功叙述。
- `frontend/src/components/agent/ToolApprovalCard.vue` / `ToolCard.vue` / `src/api/ws.ts` / `src/api/types.ts` / `src/views/Agent.vue`：展示危险命令确认卡、等待/拒绝状态，并将用户决定回传 WebSocket。
- `backend/api/tests/test_bash_hitl.py` / `test_harness_execution.py` / `test_ws_clarify.py` / `test_think_stream.py` / `test_agent_react.py` / `test_stream_p3_integration.py`：覆盖暂停、批准执行、拒绝不执行、事件恢复、思考摘要脱敏、ToolCall 草稿延迟投影和 bash 串行边界。
- `docs/AI测试与评估平台-PRD.md` / `AI测试与评估平台-API.md`：同步确认卡、事件和恢复契约。

### V1.5.26（2026-08-31）修改代码文件与作用清单

- `backend/api/app/agent/react.py`：JSON ReAct 的 `thought` 只保留为内部控制字段；带 ToolCall 的原生响应不再投影正文草稿；无工具最终回合重新请求自然语言交付，拒绝将控制 JSON 或未执行动作当作最终答案。
- `backend/api/app/agent/plan_solve.py` / `reflect.py`：PlanCard、确认卡和工具终态继续保留；删除规划、反射、修复和重规划产生的阶段 `thought`，消除范式叠加造成的卡片堆积。
- `frontend/src/views/Agent.vue`：单回合最多显示一张固定过程摘要；历史 `thought` 不回放，Plan/Reflect 阶段仅驱动生成状态而不创建聊天卡。
- `backend/api/tests/test_agent_react.py` / `test_agent_routing.py` / `test_agent_multiturn.py`：覆盖 ReAct 内部 thought、ToolCall 草稿和 Plan/Reflect 阶段均不出站，且工具后必须重新生成最终交付。
- `docs/AI测试与评估平台-PRD.md` / `AI测试与评估平台-API.md`：升级至 PRD V1.18 / API V1.61，冻结可见过程卡与历史重放边界。

### V1.64（2026-09-02）任务取消回执与工具状态同步

- `backend/api/app/routers/ws.py`：`cancel_task` 成功后发送持久化 `task_cancelled`，不再发送已从骨架化事件集移除的 `tool_result`。
- `frontend/src/api/types.ts` / `frontend/src/views/Agent.vue`：新增 `task_cancelled` 类型与实时/后台会话收尾逻辑，只有收到回执才结束取消中状态。
- `backend/api/app/harness/execution/task_tools.py` / `registry.py`：为未来恢复 ToolNode 保留的 `task.create` 与 REST 复用 TaskSpec 校验；当前 Agent 图仍不注入它。
- `backend/api/app/routers/mcp.py` / `frontend/src/views/AdminProfiles.vue`：工具目录标明“已注册、当前纯对话 Agent 未接线”。

## AgentLoop v2 后端增量（V1.7.0，2026-09-09）

新建会话固定为 `engine_version=agent_loop_v2`，不再使用 `AGENT_LOOP_ENABLED` 灰度开关；入口 `/ws/agent/v2?ticket=...`，独立 WS v2 命令与 cursor。旧会话仅能通过携带既有 session_id 的原路径显式回放，缺失 session_id 不创建会话。前端以 AgentLoop 作为唯一工作台，不把历史 legacy 会话迁写为新事实。

运行链：`LoopService → AgentRuntime → pre_step → model → tools/retry_wait → close_step → decide_next → finalize_turn`。协议档解析产生每回合依赖，原生工具结果进入规范模型历史，再次调用模型直到正常终态、取消、错误或步数上限。业务任务确认后只入队，执行仍归 Worker。常规工具失败回填结果后继续；取消和未知远端结果独立结算。

旧 `llm/gateway.py`、`adapters.py`、`llm_client.py`、Worker 评测和既有业务工具保留。新路径不嵌套旧 TAOR、文本 react.v1 或第二套工具注册表；源项目尚未实现的 steer、反思和自动续写不凭设计稿补造。

### 本次修改代码文件与作用清单

- `backend/api/app/agent/loop.py`、`runtime.py`、`stream.py`、`loop_settings.py`：七节点、流式 attempt、回合管理与恢复。
- `backend/api/app/agent/loop_service.py`、`loop_wiring.py`：身份、幂等命令、依赖接线、审批及资源生命周期。
- `backend/api/app/llm/loop_contracts.py`、`resolver.py`、`providers/`：异步两类协议与供应商状态往返。
- `backend/api/app/main.py`、`config.py`、`schemas.py`、`routers/sessions.py`、`routers/ws.py`、`routers/ws_v2.py`：新路径装配与引擎隔离。

细节和当前验证边界见 [后端架构设计](AI测试与评估平台-AgentLoop后端架构设计.md) 与 [实施记录](AI测试与评估平台-AgentLoop后端实施记录.md)。


### V1.7.1 前端试验接线（历史快照，2026-09-09）

本节记录试验接线时的状态：前端按 Session.engine_version 选择独立 transport。相同 v2 连接 resubscribe 只重启读流，避免 detach 误取消；工具内交互继续携带 nonce 与执行身份。V1.7.2 已固定新会话为 AgentLoop，并移除服务器开关；当前契约见 API V1.80。legacy 清理、真实供应商/Linux 验收仍未完成。

修改代码文件与作用清单：`agent/loop_presentation.py` 提供安全投影，`agent/events.py` 提供持久思考 ACL，`agent/loop.py`/`loop_wiring.py` 提供实际请求统计，`routers/sessions.py` 提供 UI 能力，`routers/ws_v2.py` 保留重同步控制权；前端新增 `agent/loop`、`components/agent/loop` 和 `api/agentLoop*`，由 `views/Agent.vue` 分流。

### V1.7.2 单入口与协议档选择（2026-09-09）

POST /api/sessions 只创建 AgentLoop 会话，数据库默认值迁至 agent_loop_v2，历史 legacy 行不改写。GET /api/sessions/agent-ui 与会话同名接口返回脱敏 profiles 数组，每项仅有 id、name、version、model、protocol、allowed_efforts 与 default_effort。输入栏提交 turn.submit.profile_id 与 reasoning_effort 后，loop_wiring 每回合重新检查 Agent 用途、有效凭据、模型配置和档位兼容性；浏览器不能提交端点、密钥或供应商参数。AGENT_LOOP_ENABLED 已从配置和部署变量移除。

修改代码文件与作用清单：backend/shared/models.py 与 migrations/versions/8f9a2c4d6e01_新会话默认使用agentloop.py 固化新会话默认引擎；schemas.py、routers/sessions.py、routers/ws.py、routers/ws_v2.py 与 agent/loop_service.py、agent/loop_wiring.py 落实单入口和逐回合校验；frontend/src/components/agent/loop/AgentComposer.vue、AgentWorkspace.vue、ThinkingControl.vue 与 views/Agent.vue 实现模型选择和 DeepSeek Harness 风格的思考控制；docs/AI测试与评估平台-API.md 升级至 V1.80。

### V1.7.5 消息操作与真实用量（2026-09-09）

AgentLoop 消息卡在实际模型名后展示该持久事件的发送日期时间；回答提供复制、重新生成和「引用为参考记忆」三个线性图标操作。重新生成重新提交同一回合的原用户内容与附件引用，引用操作仅将回答写入下一轮草稿的明确引用块，不创建或伪造服务端持久记忆。

每个完成的助手消息展示上游返回的 token 总量与单次模型生成耗时。输入框下方聚合已持久化 `assistant.message.usage` 与 `latency_ms`：显示输入/输出 token、生成速度和缓存命中率。上游未返回的 token 或缓存字段一律显示未知，绝不按文本反推；生成速度只在输出 token 与模型耗时都存在时计算。浏览器 v2 流 schema 更新为 `agent-loop-stream.v2.2`，源事实目录版本为 `5`。

修改代码文件与作用清单：`backend/api/app/agent/loop.py` 在成功 attempt 上记录模型流耗时；`agent/events.py`、`harness/contracts/loop_events.py`、`routers/ws_v2.py` 公开 `latency_ms` 并升级目录；`frontend/src/api/agentLoopTypes.ts`、`agent/loop/reducer.ts` 保留消息时间、用量与耗时；`components/agent/loop/AgentWorkspace.vue` 与 `AgentComposer.vue` 呈现消息操作和会话统计；对应后端与前端 AgentLoop 测试覆盖事件投影和前端状态。

### V1.7.4 上下文来源分布（2026-09-09）

每个 `assistant.start` 的 `request_summary.context_meter` 按实际请求序列化拆分系统提示词、对话消息、工具、MCP、Skill 与记忆文件。六项只统计输入并严格合计 `input_tokens`；输出预留继续由 `reserved_output_tokens` 单列，不混入任一来源。Skill 和记忆文件未注入当前请求时必须显示 `0`，历史事实没有 `breakdown` 时前端把旧输入合并显示为对话消息并标明限制。

修改代码文件与作用清单：`backend/api/app/agent/loop.py` 固化本轮工具传输快照；`loop_wiring.py` 以实际 wire 投影计算来源分项；`loop_presentation.py` 将分项写入安全请求摘要；`frontend/src/components/agent/loop/LoopContextMeter.vue` 以小型分色圆环、进度条和来源列表展示；`frontend/src/api/agentLoopTypes.ts` 补齐前端契约；`backend/api/tests/test_loop_presentation.py` 校验分项与输入总量一致；`docs/AI测试与评估平台-API.md` 登记 V1.87 增量。

### V1.7.7 Task 工具命名、状态卡片与工作区弹层（2026-09-11）

Task 工具只允许三层已登记名称：注册表短名 `task.create/status/cancel`、模型 Function
Calling 安全 wire 名 `platform_task_create/status/cancel`、以及 MCP 全名
`platform.tasks.task.create/status/cancel`。三者均路由至同一 `ToolDef`、JSON Schema 和
MCP `tool_id`；未知前缀不推断为平台工具。工具事件保留模型实际回传的 `name` 与
`wire_name`，同时用 `registry_name` 固化短名，前端不需要新 WS 字段即可显示准确工具名。

工作台对三种已登记 Task 名渲染统一的任务卡片。卡片只解析服务端已经脱敏的
`display.arguments_preview/result_preview` 以取得 `task_id`，再关联同一会话的持久
`task.queued/progress/report/end` 事实。Worker 进度和终态始终覆盖一次工具调用的快照，
不会因 `progress.percent=100` 自行伪造成功。工作区选择器改为从输入框上方展开；打开时
选择器平滑上移、箭头转向并播放弹层入场动画，减少对输入编辑区的遮挡。

修改代码文件与作用清单：`backend/api/app/harness/execution/task_contract.py`、
`loop_bridge.py`、`scheduler.py` 与 `agent/loop_presentation.py` 统一任务名称、Schema
投影和调度；`frontend/src/agent/loop/taskPresentation.ts`、`TaskRunCard.vue`、
`AgentWorkspace.vue` 连接 Task 卡与工作区弹层动效；`backend/api/tests/test_loop_tools.py`、
`test_loop_presentation.py`、`frontend/tests/agentLoop.test.mjs` 与
`frontend/tests/e2e/agentLoop.spec.ts` 覆盖工具别名、Worker 事件关联和浏览器契约。
