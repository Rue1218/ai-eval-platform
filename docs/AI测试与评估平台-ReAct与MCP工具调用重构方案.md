# AI 测试与评估平台 — ReAct 与内部 MCP 工具调用重构方案

| 项 | 内容 |
| --- | --- |
| 文档版本 | V0.8.0 |
| 状态 | P0/P1、P2-A（完整原生 ToolCall）、P2-B（流式参数累积、网关投影、两回合收敛）、P3（内部 MCP Host）与 P3.1（原生基础工具直连）已实施；评测/RAG MCP 扩展待按契约接入 |
| 审查日期 | 2026-08-25 |
| 适用范围 | `backend/api/app/agent/`、`app/harness/`、`app/llm/`、`app/routers/ws.py` 与内部短工具 |
| 上游权威 | `AI测试与评估平台-PRD.md`、`AI测试与评估平台-API.md`、`AGENTS.md` |

> 本文定义主项目的**原生 ToolCall、ReAct 收敛、基础工具直连与内部 MCP 扩展边界**。它不授权接入外部 MCP Server、浏览器直连 MCP、让 API 同步执行 Benchmark/RAG/Testcase/Stress，或绕过 bwrap 沙箱。对外 REST/WS 字段变更须先更新 API.md。

---

## 1. 背景与调查结论

当前项目已经具备 LangGraph、工具注册表、ToolNode、Observation、Worker 队列和 bwrap 沙箱等正确基础，但“工具成功后继续推理并给出最终结论”的 ReAct 收敛链不完整。

### 1.1 当前真实执行链

```text
user_message
  → ws.py：创建 SerializableRequest + 配置会话工作区
  → routing：进入 react_agent
  → react.py：模型输出严格 ReAct JSON（read / done）
  → toolnode.py：门禁 → 参数绑定 → handler 执行
  → Observation 写入 GraphState
  → react.py：把 Observation 拼进 system，再请求模型决定 done
  → 无工具模型调用生成自然语言回答
```

调查得到以下事实：

1. **工具结果会回传模型，但回传形式不理想。** `Observation` 会拼接为 system 文本中的“工具结果”，而不是有身份、范围和元数据的独立工具观察。
2. **同参数 `read` 重复时存在原文直出。** 当前 ReAct 在多次重复 `read` 后直接以 `assistant_message` 回显 `Observation.text`，完全跳过模型总结。这是“读取成功后把文件全文交给用户”的直接根因。
3. **读取单位是字符而非行。** 当前 `read_file_safe` 默认只返回 24,000 字符，`offset/limit` 也是字符偏移；它不能稳定表达“读取前 2,000 行”。
4. **一个简单读取通常需要三次模型往返。** 第一次决定读文件，第二次只输出 `done` JSON，第三次才生成自然语言结果；这比“工具结果后直接继续回答”的 ReAct 慢一轮。
5. **ReAct 覆盖了调用侧系统提示。** `ws.py` 构造的 `agent_system_prompt` 存在于 `SerializableRequest`，但 `react.py` 会重建固定 system，导致工具路径可能忽略“读取后必须分析、不可原文回显”等配置。
6. **现有测试偏控制流。** 已覆盖工具事件、预算、重复抑制和最终流式帧，但没有覆盖“成功读取 3,000 行后必须分析而非回显原文”的端到端质量契约。

### 1.2 问题不是“提高字符上限”

把 24,000 提高到更大值只能让模型看到更多原文，不能解决以下问题：

- 工具结果缺少行范围、完成状态和下一页位置；
- 模型不被要求将工具结果转化为用户问题的结论；
- 重复读取仍可能进入原文直出分支；
- 大段原文写入 system 会稀释固定安全策略和用户目标；
- 过长结果进入 WS 持久化事件、检查点或模型上下文会增加成本和重放风险。

因此本方案把问题拆为四层：**模型回合、工具调用、结果观察、执行隔离**。

### 1.3 主流 Agent 流与原生 ToolCall 调查

调研 LangGraph/LangChain、Agent Streaming Protocol、MCP 规范与模型协议后，得到以下结论：

1. **“正文与工具卡交错出现”是成熟 Agent 的常见交互能力，但不是 LangGraph 的自动效果。** 标准回合是“模型消息（可含 ToolCall）→ 工具结果消息 → 下一轮模型消息”；实现该体验还需要模型流、工具生命周期事件和前端按 `call_id` 合并状态。
2. **LangGraph 正是本项目应保留的编排层。** 它可分别流出模型 token、节点状态和自定义数据；项目现有 `astream(stream_mode=["custom", "updates"])` 已具备 WebSocket 投影基础。改造对象是 `react_agent` 的模型协议，不是替换 LangGraph 或再引入第二个 Agent 框架。
3. **原生 ToolCall 不等于模型直连 MCP。** 模型只接收平台投影出的工具 schema，并返回结构化调用；ToolNode 仍须执行门禁、确认、附件绑定、脱敏与超时控制。基础工具由原生执行器调用，只有显式 MCP 扩展才交内部 Host。
4. **模型不保证在 ToolCall 前输出正文。** 有些模型会只返回工具调用；因此“正在读取/检索”的可信展示必须来自 `tool_call`、`tool_result` 与工具进度，而非要求模型虚构工具已成功的叙述。
5. **MCP 进度只表示工具执行进度，不会让模型在等待工具时继续生成正文。** 短工具结束后要重新进入模型回合；长任务则由 Worker 与 WebSocket 推送真实进度。

本项目采用“**原生 ToolCall + 原生基础工具执行器 + 内部 MCP 扩展 Host**”的组合，而不采用“上游模型服务直接调用远程 MCP Server”。read/write/edit/bash/web_search/web_fetch/task 直接执行；只有后续评测/RAG 扩展经内部 MCP Host。这同时满足原生模型工具协议、项目仅内部 MCP 的产品边界以及 bwrap fail-closed 的安全红线。

调研依据：

- LangChain Streaming：<https://docs.langchain.com/oss/python/langchain/streaming>
- LangChain Tool Calling UI：<https://docs.langchain.com/oss/python/langchain/frontend/tool-calling>
- LangGraph Agent Streaming Protocol：<https://langchain-ai.github.io/agent-protocol/streaming/>
- MCP Progress：<https://modelcontextprotocol.io/specification/2024-11-05/basic/utilities/progress>

---

## 2. 目标、非目标与硬约束

### 2.1 目标

1. 工具成功后，模型必须基于工具观察继续判断：继续调用工具，或直接交付面向用户的分析结果。
2. 任意兜底路径不得把工具原始内容伪装成助手结论。
3. `read` 支持按行读取，默认可覆盖前 2,000 行，并保留字符和上下文预算上限。
4. 建立 API 内部 MCP 扩展 Host：评测/RAG 等跨服务能力经受控目录调用；基础工具不增加 MCP 路由；浏览器只看 ToolCard 事件。
5. 保留当前 ToolNode 的白名单、附件绑定、规则门禁、Worker 长任务边界、脱敏和 bwrap fail-closed 机制。
6. 保持图节点不持有 WebSocket、DB Session、裸密钥或不可序列化对象。

### 2.2 非目标

- 不接入用户自定义或互联网外部 MCP Server；
- 不把 MCP transport 暴露给浏览器；
- 不在 API/WS 进程同步运行 Benchmark、RAG、Testcase 或 Stress；
- 不允许模型传入 sandbox 工作目录、MCP Server 命令、环境变量或 API Key；
- 不引入 LangChain Agent、第二条 ReAct 循环或 LLM 子代理；
- 不把隐藏推理链作为可审计或用户可见数据保存。

### 2.3 不可破坏的现有边界

| 边界 | 保留要求 |
| --- | --- |
| WebSocket | `ws.py` 仍是唯一事件桥接和持久化入口；图节点只返回 `NodeEvent` 与纯数据。 |
| 长任务 | `benchmark.run`、`testcase.generate`、`rag.evaluate`、`stress.run` 只入 PG 队列，再由 Worker 消费。 |
| 数据库 | `backend/shared/models.py` 继续是 API/Worker 单一模型事实源；改表必须 Alembic。 |
| 错误 | 浏览器只接收既有十类 `ErrorCode` 和中性文案，不返回 traceback、SQL、Key 或上游原文。 |
| 沙箱 | Bash 仅经 bwrap；引擎不可用必须 fail-closed，禁止裸 subprocess 降级。 |
| MCP | 当前阶段只连接平台部署、审计、允许列表内的内部 Server。 |

---

## 3. 目标架构

```text
浏览器 Vue / WebSocket
        │
        ▼
routers/ws.py
  - 短票鉴权、会话权限、事件落库/补发、abort
        │
        ▼
LangGraphAgent
  routing → chat | direct | react
                      │
                      ▼
                ReAct 编排节点
        ┌─────────────┼───────────────────┐
        ▼             ▼                   ▼
  ModelGateway   Tool Policy          Context Assembly
  （ToolCall）   / Approval Gate      / Observation
        │             │                   │
        └─────────────▼───────────────────┘
                      │
                      ▼
                 ToolNode
                      │
                      ▼
               Internal MCP Host
        ┌─────────────┼───────────────────┐
        ▼             ▼                   ▼
   files MCP      web MCP        sandbox / task MCP
 read/write/edit  search/fetch   bash / enqueue
        │             │                   │
        └─────────────┴───────────┬───────┘
                                  ▼
                  bwrap Workspace / PG Queue / Worker
```

### 3.1 职责划分

| 层 | 唯一职责 | 禁止事项 |
| --- | --- | --- |
| `app/llm/` | 将模型增量归一为文本、推理摘要、ToolCall、完成状态 | 不执行工具、不查 DB、不发 WS。 |
| `app/agent/` | 选择 Chat / ReAct / Plan-Solve，决定图条件边 | 不直接调用 handler 或 MCP transport。 |
| `harness/context/` | 根据用户目标、工具观察和上下文预算装配模型输入 | 不将原始工具结果写成系统策略。 |
| `harness/execution/` | 工具目录、门禁、参数绑定、调用 MCP、超时、归一化 | 不持有 WS，不运行长任务。 |
| `harness/execution/mcp/` | 内部 MCP Client Manager、工具发现、路由、会话生命周期 | 不接受浏览器指定 server/command。 |
| `worker/` | 消费长任务、执行评测、写任务事件 | 不依赖 WS 连接，不把 ORM 跨 Session 传入。 |

---

## 4. ReAct 收敛重构

### 4.1 目标回合模型

对“读取文件并分析”的理想路径是两次模型回合，而不是三次：

```text
第 1 回合：理解用户目标 → 请求 read
第 2 回合：收到 read Observation
  ├─ 还缺信息 → 请求下一次 read（使用 next_offset）
  └─ 信息足够 → 直接流式输出分析、结论、风险和建议
```

在第二回合中，模型必须在同一次连续决策中完成“是否继续调用工具”和“无工具时的自然语言交付”。不得要求它先输出一个只含 `done=true` 的控制 JSON，再另起一次没有连续行动语义的回答回合。

### 4.2 原生 ToolCall 模型回合

P2-A 已不再要求支持 Function Calling 的模型输出 `react.v1` JSON，而是将内部 `ToolDescriptor` 映射为当前协议档的原生工具定义；完整 ToolCall 由 `app/llm/` 统一归一，图层不感知上游字段差异。旧协议 JSON 仅作为兼容回退保留。

| 上游协议 | 向模型发送 | 模型返回 | 下一回合回填 |
| --- | --- | --- | --- |
| OpenAI Chat Completions | `tools` | `assistant.tool_calls` | `role=tool` + `tool_call_id` |
| OpenAI Responses | `tools` | `function_call` 输出项 | `function_call_output` |
| Anthropic Messages | `tools` + `input_schema` | `tool_use` 内容块 | `tool_result` 内容块 |
| 非标准兼容网关 | 协议档显式设为 `native` 后才启用 | 按已验证映射处理 | 设为 `legacy` 时不发送 `tools`，固定走受控 JSON 分支 |

所有适配器先在内部累计协议特有的参数片段，再产出同一可执行事件序列：

```text
content_delta* → tool_call_completed(call_id, name, arguments)
```

参数片段只存在于协议适配器的调用内存，既不投影为 WebSocket 事件，也不得执行。仅当参数 JSON 完整、schema 校验通过且 ToolPolicy 放行后，才进入 ToolNode。`call_id` 必须从模型消息到 ToolResult、审计记录与前端 ToolCard 全程保持不变。

**当前实施边界（P2-A）**：三协议的非流式完整 ToolCall 已双向映射；`tool_call_mode` 默认 `legacy`，只有经人工验证后显式设置为 `native` 的协议档发送 `ModelRequest.tools`。`ModelResponse.tool_calls` 已回到 LangGraph；空、空白、重复 `call_id` 或无效工具名/参数会归一为 `UPSTREAM`，不进入工具队列。同一有效响应的多个调用以队列串行执行，每一项先经过注册期受限 JSON Schema、Gate、附件绑定、`dispatch` 和 bwrap。未知工具、参数错误、Gate/绑定拒绝、超时和执行失败均发送与原始调用相同 `call_id` 的 `tool_result`，前端优先按 ID 回填卡片。原始工具正文只保留在 Agent 实例内、按 `thread_id` 隔离的单回合存储；GraphState、RunnableConfig、WS 事件和检查点均不保存 120,000 字符 read 原文。

**P2-B 实施边界**：OpenAI Chat Completions 按 `index` 累积 `tool_calls[].function.arguments`，OpenAI Responses 累积 `response.function_call_arguments.delta` 并以 `done` 收尾，Anthropic Messages 累积 `input_json_delta` 并以 `content_block_stop` 收尾。适配器仅在可解析为 JSON 对象时创建 `AdapterStreamEvent(tool_call)`；无效参数统一为 `UPSTREAM`。`ModelGateway` 将其归一为 `ModelStreamEvent(tool_call)` 与最终 `ModelResponse.tool_calls`，不增加对外 WS 事件。原生工具结果后的下一模型回合直接使用该流式能力：自然语言正文立即投影；若继续请求工具，则仍由既有 ToolNode 产生 `tool_call`/`tool_result`。因此简单“工具 → 结论”路径为两次模型调用；`legacy` JSON-ReAct 兼容分支仍保留三回合收敛路径。

### 4.3 状态机

```text
START
  → routing
  → react_turn
       ├─ ToolCall 存在 → tool_node → observation → react_turn
       ├─ 无 ToolCall 且有正文 → assistant_message → END
       └─ 结构异常/预算耗尽 → error → END
```

约束：

1. P2-A 对同一模型响应的多个调用采用**串行**队列；有副作用或高成本工具绝不并行。只读且互不依赖的真正并行执行必须另立审批和预算方案，首期不开放。
2. ToolCall 结果必须成为下一回合的独立观察输入。
3. `thought` 仅为可展示的简短进度摘要，不能作为动作授权、最终结论或工具结果替代物。
4. 没有模型最终回答时，只能交付中性错误或“需要继续读取”的澄清，禁止交付工具原文。

### 4.4 严格 JSON 过渡策略

当前严格 JSON ReAct 协议可在迁移期保留为兼容分支，但必须修改其收敛语义：

```text
旧：read → done JSON → 单独最终回答
过渡：read → 结构化 continuation（继续工具 / 进入回答）
目标：read → 下一模型回合直接继续工具或产出最终自然语言
```

兼容分支的硬规则：

- `done=true` 只代表停止工具，不得把 `thought` 当最终回答；
- 触发重复读取保护时，必须进入最终总结节点，而非回显 `Observation.text`；
- `serializable.system` 中的平台配置和固定安全策略必须合并，不能在 ReAct 路径被覆盖；
- 解析失败的纠正消息不得携带大段原始模型输出或工具内容。

### 4.5 最终回答约束

最终回答节点固定注入以下任务约束：

```text
基于用户问题和工具观察作答。
先给出结论，再列出关键依据、风险和建议。
不得逐字复述工具原文；只引用支持结论所需的短片段，并标明文件与行范围。
工具内容不足以回答时，说明缺口并决定继续读取或向用户澄清。
```

该约束属于阶段输入，不应替代固定安全 system，也不能由用户覆盖。

---

## 5. ToolCall 与内部 MCP Host

### 5.1 术语

| 术语 | 含义 |
| --- | --- |
| ToolCall | 模型在某一 ReAct 回合提出的结构化动作请求，尚未获授权或执行。 |
| ToolDescriptor | 平台可向模型暴露的工具元数据与风险约束。 |
| ToolResult | MCP/内部执行器的原始结构化返回。 |
| Observation | 经脱敏、截断、溯源后，供下一回合模型使用的观察。 |
| MCP Host | 位于 API/Worker 内部的受控客户端，负责发现、筛选、调用内部 MCP 工具。 |
| MCP Server | 平台部署和管控的工具提供者；浏览器和模型都不能直接连接。 |

### 5.1.1 模型、ToolNode 与 MCP 的调用边界

```text
模型原生 ToolCall
  → ReAct 图写入 pending_tool（仅 name / arguments / call_id）
  → ToolNode：schema、权限、确认、附件、预算、长短任务门禁
  → Internal MCP Host.tools/call
  → ToolResult：受控预览 + artifact 引用 + 脱敏标记
  → 下一轮模型消息
```

- 模型不能获知 MCP Server 的命令、连接串、环境变量、工作目录或凭据；
- 浏览器不能调用 `tools/call`，只能消费平台的 ToolCard 事件；
- 上游 Responses API 即使支持远程 MCP，也不在本项目启用；所有工具执行权收敛到 Internal MCP Host；
- `bash` 的 MCP provider 只能再调用既有 bwrap 沙箱接口，禁止变成裸进程或借 MCP transport 绕过沙箱。

### 5.2 统一工具描述符

现有 `ToolDef` 扩展为内部标准描述符；模型、策略、MCP 和前端均从同一投影读取，而不是分别维护工具名和 schema。

```python
@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool_id: str                 # 例如 "platform.files.read"
    server_id: str               # 例如 "platform.files"
    name: str                    # 对模型稳定暴露的短名，例如 "read"
    display_name: str            # 例如 "读取文件"
    description: str
    input_schema: Mapping[str, object]
    permission: str              # 例如 sandbox.read
    risk_level: Literal["read", "modify", "network", "code", "long"]
    execution_mode: Literal["short", "long"]
    timeout_s: float
    requires_confirmation: bool
    supports_streaming: bool
```

约束：

- `tool_id` 和 `server_id` 由平台目录决定，模型参数中不得携带；
- 名称冲突使用 `server_id + tool_id` 路由，前端仍展示中文 `display_name`；
- `input_schema` 在执行前必须由统一 JSON Schema 校验器强制校验；
- `permission` 必须参与策略判定，不能只作为展示字段；
- `execution_mode=long` 的工具不允许在 ToolNode 内同步调用。

### 5.3 MCP Host 接口

建议新增 `MCPClientManager`，只暴露以下内部能力：

```python
class MCPClientManager:
    async def refresh_catalog(self) -> list[ToolDescriptor]: ...
    async def call_tool(
        self,
        tool_id: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult: ...
    async def close(self) -> None: ...
```

调用顺序固定：

```text
tools/list
  → 平台 allowlist 与 ToolDescriptor 归一
  → 按会话、风险、任务模式筛选
  → 模型产生 ToolCall
  → schema / 权限 / 确认 / 预算 / 资产门禁
  → tools/call
  → ToolResult
  → Observation
```

首期只允许以下内部来源：

| Server | 工具 | 执行方式 |
| --- | --- | --- |
| `platform.files` | `read`、`write`、`edit` | 会话 workspace；读写路径边界不变。 |
| `platform.web` | `search`、`fetch` | SSRF 防护、响应大小限制；search 未接入时返回 `VALIDATION`。 |
| `platform.sandbox` | `bash` | bwrap；无网络、资源受限、fail-closed。 |
| `platform.tasks` | `create`、`status`、`cancel` | 只入 PG 队列或查询，不等待 Worker 终态。 |

迁移初期可用 in-process provider 包装当前 handler，以减少一次性改动；但 Agent 图只能依赖 `MCPClientManager`，不得再直接导入 `dispatch.py` handler。生产 stdio MCP Server 必须由平台配置启动，不能由用户或模型传入命令。

### 5.4 ToolCall 生命周期

```text
模型 ToolCall delta
  → 累积成完整 call_id / name / arguments
  → ToolCall（未执行）
  → ToolPolicy 决策
       ├─ reject       → tool_result(ok=false) + Observation
       ├─ need_approval→ confirm / confirm_ack
       ├─ long         → enqueue + task_id Observation
       └─ short        → MCP tools/call
  → ToolResult
  → Observation
  → 下一轮 ReAct
```

`ToolCall` 最低字段：

```json
{
  "call_id": "toolcall_xxx",
  "tool_id": "platform.files.read",
  "name": "read",
  "arguments": {"path": "attachments/spec.md", "offset": 0, "limit": 2000}
}
```

`ToolResult` 与 `Observation` 必须分离：

- `ToolResult` 可以有结构化数据和服务端诊断码；
- `Observation` 只保留已脱敏、按上下文预算裁剪的模型可见内容；
- WS `tool_result` 只发送 UI 所需摘要和元数据，不持久化大段文件原文；
- 原始内容需临时保存时只保存到会话 workspace / 受控 artifact，状态中保存引用、hash 和范围。

---

## 6. `read` 工具专项设计

### 6.1 新输入契约

`offset` 与 `limit` 统一为**行**：

```json
{
  "path": "attachments/requirements.md",
  "offset": 0,
  "limit": 2000
}
```

默认值：

| 参数 | 默认 | 限制 |
| --- | ---: | --- |
| `offset` | 0 | 非负整数，0-based 行号。 |
| `limit` | 2,000 行 | 允许平台按 profile 上下文预算下调。 |
| `max_chars` | 120,000 字符 | 服务端固定上限，模型不可覆盖。 |
| 文件字节上限 | 10 MB | 超限必须分页或返回受控错误。 |

### 6.2 新输出契约

```json
{
  "path": "attachments/requirements.md",
  "total_lines": 3560,
  "total_chars": 180423,
  "start_line": 0,
  "end_line": 2000,
  "lines_read": 2000,
  "is_complete": false,
  "next_offset": 2000,
  "content": "...",
  "content_truncated": false,
  "source": "workspace:session_id/attachments/requirements.md"
}
```

若 2,000 行在 120,000 字符内放不下，必须以实际 `end_line` 作为边界，并返回正确 `next_offset`；不得截断到半行后仍声称读取了 2,000 行。

### 6.3 读取后的模型观察

模型不应只看到一段裸文本，而应看到：

```text
工具观察：platform.files.read 成功
文件：attachments/requirements.md
范围：第 0–1999 行 / 共 3560 行
状态：未读完；下一页从 2000 行开始
任务：用户要求“分析核心风险并总结”。
内容：……
```

当用户问题只需要当前片段即可回答，模型应直接总结；只有当结论依赖后续行时才请求 `offset=next_offset`。

### 6.4 重复调用策略

| 情况 | 策略 |
| --- | --- |
| 相同 `path + offset + limit` 且上次成功 | 不再执行 I/O；回传缓存 Observation，并要求模型“总结或使用 next_offset”。 |
| `is_complete=false` 且模型需要后续内容 | 只允许 `offset=next_offset` 的顺序翻页。 |
| 模型重复同参数两次仍不收敛 | 强制进入最终总结回合；不得直接发送原文。 |
| 文件过大或上下文预算不足 | 返回范围/下一页信息，请模型缩小范围、搜索关键词或要求用户指定章节。 |

---

## 7. 安全、沙箱与长任务

### 7.1 统一策略门禁

ToolPolicy 在调用 MCP 前按固定顺序执行：

1. 工具是否在已发现且平台允许的目录内；
2. ToolCall 参数是否通过 JSON Schema；
3. 用户、会话、附件与 workspace 归属是否一致；
4. 风险等级是否允许；
5. 是否需要确认，以及确认是否绑定 `session_id + user_id + tool_id + arguments_hash + expiry`；
6. 是否超过模型、工具、并发或失败预算；
7. 长任务是否改为 `enqueue_long_task`；
8. 是否违反“先评后压”“一会话一活动任务”等业务门禁。

### 7.2 MCP Server 运行隔离

MCP 不是沙箱。即使通过 stdio 调用，Server 仍可能访问宿主机，因此：

- 只允许平台部署清单中的绝对命令、工作目录和环境变量白名单；
- 不允许 `shell=True`、模型传 command、模型传 cwd 或模型传 env；
- 每个 Server 必须有请求超时、最大帧大小、输出截断、失败熔断和重启退避；
- API Key、Cookie、数据库连接串不得透传给无关 MCP Server；
- stdio 的 stderr 只进入受控服务端日志，不能回显给浏览器或模型；
- 后续将 `platform.sandbox` 迁到独立沙箱 Runner/容器，降低 API 容器 `privileged` + `SYS_ADMIN` 的暴露面。

### 7.3 bwrap 保留规则

`bash` 的现有安全设计继续有效：

```text
ToolPolicy 黑名单（纵深防御）
  + bwrap --unshare-net / --unshare-pid / 最小只读 bind
  + 当前会话 workspace 唯一可写
  + memory / nproc / cpu / wall-clock 限制
  + timeout killpg
  + bwrap 不可用即 VALIDATION
```

`read`、`write`、`edit` 仍要做 realpath、相对路径和会话 workspace 校验；不能因为接入 MCP 而放宽这些规则。

### 7.4 长任务桥接

`platform.tasks.create` 返回的不是报告正文，而是：

```json
{"status": "queued", "task_id": "...", "kind": "benchmark"}
```

下一轮模型只能告知用户“已入队”；真实进度、报告和错误由 Worker 写入 `task_events`/`ws_events`，再由 WS 转发。Agent 不等待终态，不轮询 Worker，不在 ToolNode 执行评测。

---

## 8. WebSocket、持久化与前端表现

### 8.1 保持的对外事件

首期继续使用现有事件名：

```text
tool_call
tool_result
assistant_delta
assistant_message
response.completed
error
progress
report
```

`tool_call` 表示已经通过模型解析、但尚未完成执行的调用；`tool_result` 表示策略拒绝、确认拒绝、短工具结果或长任务入队结果。更细的“参数累计中/执行中”属于后续 API.md 明确后才可新增的事件，不能私自扩展前端契约。

### 8.1.1 原生 ToolCall 的流式投影规则

首期在不新增对外事件名的前提下，按下列规则投影：

| 内部事件 | WebSocket 投影 | 说明 |
| --- | --- | --- |
| `content_delta` | `assistant_delta` | 只能来自模型自然语言正文；可发生在工具调用前或工具结果后的下一模型回合。 |
| `tool_call_completed` | `tool_call` | payload 必须含稳定 `call_id`、工具名和已经完成校验的参数。 |
| `ToolResult` | `tool_result` | 与 `call_id` 关联；只放受控摘要、状态、耗时和 artifact 引用。 |
| 无 ToolCall 的模型回合结束 | `assistant_message` + `response.completed` | 收敛为本轮最终答案；native 工具结果后的第二回合直接投影正文，不再补发无工具模型调用。 |

`assistant_delta` 是瞬态帧，仍不落库；每个模型消息段完成时必须以现有 `assistant_message` 形式保存完整受控文本，供断线重连和历史消息恢复。若 API.md 当前 `assistant_message` 契约无法区分中间段与最终段，必须先更新 API.md 再实现，不得私自加字段。

### 8.1.2 MCP 与 Worker 进度

内部 MCP Host 调用可带唯一 `progressToken`；收到 MCP `notifications/progress` 后仅可投影真实工具进度。若后续需要新增 `tool_progress` WS 事件，必须先更新 API.md。对于 Benchmark、RAG、Testcase、Stress 等长任务，ToolResult 只返回入队结果和 `task_id`，真实进度继续由 Worker 写 `progress/report` 事件；API 进程不得等待任务终态。

### 8.2 ToolCard 与助手正文分离

| 载体 | 应展示内容 | 禁止内容 |
| --- | --- | --- |
| ToolCard | 工具中文名、参数、行范围、总行数、完成状态、受控预览、耗时、截断/脱敏标记 | 整个大文件、秘密、内部异常堆栈。 |
| Assistant | 用户问题的结论、依据、风险、建议、必要行号引用 | 未加工的工具原文、内部协议 JSON、工具诊断。 |
| 思考卡 | 简短进度摘要 | 隐藏推理链、敏感工具结果。 |

### 8.3 状态与检查点

`GraphState` 只能保存 JSON 可序列化、可审计的状态：ToolCall 摘要、Observation 摘要、artifact 引用、预算和事件意图。不得将 120,000 字符 read 原文长期塞入检查点或 `ws_events`。

需要跨节点读取大结果时，使用：

```text
artifact_id / workspace 相对路径 / sha256 / 行范围 / 可见预算
```

由 Context Assembly 在下一模型回合按预算读取并注入；断线重连时只回放 ToolCard 摘要和最终回答。

---

## 9. 迁移计划

### 阶段 A：止血与回归（P0）

1. 删除 ReAct 重复 `read` 的原文直出分支；
2. 保证 ReAct 路径合并调用侧 system 与固定安全策略；
3. 成功工具调用后，最终回答必须由模型节点产出；
4. 新增成功 `read`、重复 `read`、最终总结的回归测试；
5. 不改对外 API，不引入 MCP transport。

### 阶段 B：行级 `read` 与 Observation（P1）

1. `read` 改为行级 `offset/limit`，默认 2,000 行、120,000 字符硬上限；
2. 定义 `ReadResult` 元数据和受控 UI 预览；
3. 扩展 Observation 的范围、完成状态和 artifact 引用；
4. 让 Context Assembly 用独立工具观察装配下一轮输入；
5. 不再把原始工具内容直接拼进固定 system。

### 阶段 C：ToolCall 模型契约与 ReAct 收敛（P2）

1. 保留 LangGraph 的 `routing → react_agent → tools → react_agent` 条件边，不新增第二套 Agent 框架；
2. **P2-A 已完成**：扩展 `app/llm/contracts.py` 的完整 ToolCall、ToolResultMessage 和“无 ToolCall 的最终正文”；
3. **P2-A 已完成**：三协议适配器映射工具定义、完整 ToolCall 与工具结果，并维护稳定 `call_id`；
4. **P2-B 已完成**：`ModelGateway` 流式投影完整 ToolCall 与正文；参数片段只在适配器内累计，不把协议差异或不完整参数带到 Agent 图；
5. **P2-A/P2-B 已完成**：协议档已有 `native|legacy` 的已验证原生调用开关；真正并行调用等细粒度能力标记仍不在本阶段范围，且不支持的网关不可静默降级；
6. **P2-A/P2-B 已完成**：Agent 图可在工具结果后继续调用或直接流式进入自然回答收敛；同轮多调用先串行执行；
7. 严格 JSON 保留为临时兼容路径；在协议档能力标记上线后再确定淘汰日期。

### 阶段 D：内部 MCP Host（P3）✅ 已实施

1. ✅ 新建 `harness/execution/mcp/manager.py`、`catalog.py`、`provider.py`；
2. ✅ 先将现有 read/write/edit/web/bash 包装为内部 in-process provider；
3. ✅ ToolRegistry 转为目录、风险和策略唯一源（`ToolDef` 扩展 server/风险/展示元数据 + `iter_defs`/`to_descriptor`），Agent 不再直接持有 handler（ToolNode 统一经 `MCPClientManager`）；
4. ✅ 为 `tools/list`/`tools/call`、超时、取消、错误归一、工具名冲突和目录刷新补测试（`tests/test_harness_mcp.py` 15 项）；
5. ✅ `/api/mcp/tools` 在 API.md §3.6.1（V1.29）更新后只读展示平台允许的目录，不展示连接命令或凭据。

### 阶段 E：长任务与沙箱 Runner（P4）

1. 接入 `platform.tasks` MCP，统一入队和状态查询；
2. 把 bash MCP Server 放入独立 Runner/容器，保留 bwrap fail-closed；
3. 补充取消传播、资源配额、审计和熔断指标；
4. 在生产验证后，再评估是否需要任何新内部 MCP Server；外部 MCP 仍不在本范围。

---

## 10. 验收标准

### 10.1 ReAct 行为

- 给定“读取文件并总结风险”，`read` 成功后最终助手消息必须包含分析结论，不能等于或大段复制工具原文；
- 同一 `read(path, offset, limit)` 重复两次以上，不得直接回显文件内容；
- native 模式下完整小文件读取与最终流式总结最多两次模型回合；legacy JSON-ReAct 兼容路径最多三次；
- 多页读取时，下一页必须使用上一页 `next_offset`，不能从 0 重读；
- 工具失败、模型解析失败、预算耗尽均返回中性错误，不泄露内部原文或堆栈。
- 原生 ToolCall 的 `call_id` 从模型请求、`tool_call`、`tool_result` 到下一轮 ToolResultMessage 均一致；
- 模型仅返回 ToolCall 而无正文时，前端仍显示真实 ToolCard 状态，不伪造“工具已成功”的助手正文；
- 模型在工具调用前输出正文时，事件顺序允许为 `assistant_delta* → tool_call → tool_result → assistant_delta* → assistant_message → response.completed`；工具前正文为空同样合法。

### 10.2 `read` 工具

- 3,000 行文件默认返回前 2,000 行及正确 `next_offset=2000`；
- 2,000 行触发字符硬上限时，`end_line` 与 `next_offset` 准确；
- 文件全读完时 `is_complete=true`；
- 路径穿越、绝对路径、跨会话 workspace、软链接逃逸均拒绝；
- ToolCard 只展示受控预览，WS 持久化事件不包含完整大文件。

### 10.3 MCP 与执行安全

- 只有 allowlist 内部 Server 的工具能被发现和调用；
- 模型无法指定 Server 命令、环境变量、工作目录或 sandbox 根；
- schema、权限、附件归属、确认、预算和长任务门禁均在 `tools/call` 前执行；
- bash 无网络、资源受限、超时整树清理，bwrap 缺失时拒绝执行；
- Worker 任务只接收 ID/JSON spec，跨 Session 传 ORM 对象的测试继续通过。

### 10.4 质量与观测

- 记录并可查询：模型首字节耗时、工具耗时、工具到最终回答耗时、重复读取次数、输入/输出截断次数、预算耗尽次数；
- 对 ReAct 关键路径建立测试：正常 read→总结、分页 read→总结、重复 read、工具失败、取消、断线重连；
- 前端按 `call_id` 原地更新 ToolCard；`running`、`finished`、`error` 三种状态均有受控展示；
- 模型最终正文必须在匹配的 `tool_result` 后产生；若有工具前正文则它只可表达计划或下一步，不能声称工具尚未返回的结果；
- 断线恢复后不丢失已完成的助手消息段与 ToolCard 摘要。

---

## 11. 预计代码影响清单

| 文件/目录 | 预计作用 |
| --- | --- |
| `backend/api/app/agent/react.py` | P0/P1 已删除原文直出；P2-A 已接入原生 ToolCall 与兼容回退；P2-B 在工具结果后的下一原生回合直接流式收敛。 |
| `backend/api/app/agent/graph.py` | P2-A 已支持 ToolCall 队列的串行条件边与最终正文分流。 |
| `backend/api/app/llm/contracts.py` | P2-A 已定义完整 ToolCall、模型回合和工具结果输入契约；P2-B 复用完整 ToolCall 作为流式收尾契约。 |
| `backend/api/app/llm/gateway.py` | P2-B 将适配器已完成 ToolCall 投影为流事件及收尾响应，不执行工具。 |
| `backend/api/app/adapters.py` | P2-A 已实现三协议的工具定义、完整工具调用和工具结果映射；P2-B 已实现 SSE 参数累计与完整性校验。 |
| `backend/api/app/harness/context/assembly.py` | 以独立观察装配模型输入，执行预算裁剪。 |
| `backend/api/app/harness/contracts/artifacts.py` | 扩展 ToolDescriptor/ToolCall/ToolResult/Observation/artifact 引用。 |
| `backend/api/app/harness/execution/registry.py` | 从 handler 注册表演进为目录、风险、schema 和策略唯一源。 |
| `backend/api/app/harness/execution/toolnode.py` | 执行 ToolPolicy 和 MCP Host，而非直接 handler。 |
| `backend/api/app/harness/execution/dispatch.py` | 将 read 改为行级结果；保留路径、SSRF 与 bwrap 安全边界。 |
| `backend/api/app/harness/execution/mcp/` | ✅ 已实施：内部 MCP Client Manager（`manager.py`）、目录（`catalog.py`）与 in-process provider（`provider.py`）；首期无 stdio transport（外部/浏览器直连 MCP 仍不在范围） |
| `backend/api/app/harness/execution/worker_bridge.py` | 作为 `platform.tasks` 的唯一长任务入队桥接。 |
| `backend/api/app/routers/ws.py` | 继续仅负责事件桥接；按 API 契约投影 ToolCall 事件。 |
| `backend/api/app/routers/mcp.py` | API.md 更新后展示只读内部工具目录。 |
| `backend/api/tests/` | 新增 ReAct 收敛、行级 read、MCP、沙箱、WS 顺序和回归测试。 |
| `docs/AI测试与评估平台-API.md` | 仅在确定新增字段或事件后更新对外契约。 |

---

## 12. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| --- | --- | --- |
| `docs/AI测试与评估平台-ReAct与MCP工具调用重构方案.md` | 新增并更新至 V0.6.0 | 固化故障调查与主流 Agent 事件流调研结论，明确保留 LangGraph、接入原生 ToolCall、内部 MCP、行级 read、Worker、沙箱的重构边界、迁移阶段和验收标准；记录 P0/P1/P2-A/P2-B 实施与加固状态。 |
| `backend/api/app/harness/execution/native_results.py` | 新增 | 提供按 Agent 回合隔离、结束即清理的原生 ToolResult 临时内存，避免原文进入 Config、State、事件或检查点。 |

### V0.2.1（2026-08-25）实施记录

- P0 已实施：工具执行后的最终正文一律由无工具模型回合生成；重复 read 不再直接回显 Observation 原文；流式与仅 invoke 网关均覆盖。
- P1 已实施：read 统一为行级 offset/limit，默认/最大 2,000 行、120,000 字符硬上限、10MB 文件上限；ToolCard 只接收行范围、统计和 500 字符预览。
- 当时未实施：三协议原生 ToolCall、`call_id`、并行调用、内部 MCP Host/transport、长任务 MCP bridge 与独立沙箱 Runner；其中完整原生 ToolCall 与 `call_id` 已于 V0.3.0 落地，其余仍按 P2-B–P4 推进。

### V0.3.0（2026-08-25）实施记录

- P2-A 已实施：`ModelRequest.tools` 透传至 OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages；三协议完整 ToolCall 分别归一为 `NativeToolCall(call_id, name, arguments)`，并按各协议格式回传 assistant ToolCall 与 ToolResultMessage。
- `call_id` 已闭环：原生上游 ID 原样保留，缺失时生成 `toolcall_<uuid>`；LangGraph、ToolNode、`tool_call`、成功/拒绝/超时失败的 `tool_result`、前端 ToolCard 均使用同一 ID。多个同轮调用先按队列串行执行，绝不并行绕过现有 Gate、附件绑定、dispatch 或 bwrap。
- 严格 `react.v1` JSON 保留兼容回退，避免不支持原生 ToolCall 的既有模型立即失效；P2-B 仍需完成上游 SSE 参数增量、协议档能力标记，以及将工具后第二回合直接作为原生流输出。
- 本次未实施：内部 MCP Host/transport、外部 MCP、浏览器直连 MCP、长任务 MCP bridge 与独立沙箱 Runner；P3/P4 的安全边界不变。

### V0.4.0（2026-08-25）实施记录

- P2-A 加固：协议档新增 `tool_call_mode`，只有明确的 `native` 档发送上游 `tools`；未验证的兼容网关切换为 `legacy` 后只走严格 JSON-ReAct，不以 4xx 为依据静默重试或降级。
- ToolNode 在执行前执行受限 JSON Schema 校验；未注册工具、参数错误、Gate/附件拒绝都产出关联 `call_id` 的失败 ToolResult，任何失败路径都不进入 handler、dispatch 或 bwrap。
- 三协议消息适配补齐 Anthropic 多 ToolResult 合并；ReAct 保留 `serializable.system` 的平台配置；完整 read 结果以单回合临时缓存回灌下一模型回合，GraphState/checkpoint 只保留受控摘要和关联 ID。
- 本次仍未实施：上游参数增量流、原生 ToolCall 与正文同回合流式收敛、细粒度参数流/并行能力标记、内部 MCP Host/transport 与外部 MCP。

### V0.5.0（2026-08-25）实施记录

- P2-A 安全修复：`tool_call_mode` 默认及存量迁移均为 `legacy`；只有管理员验证 Function Calling 后才可显式开启 `native`。
- 原生 ToolCall 在 ReAct 入队前校验 `call_id` 非空且同轮唯一，并校验工具名与参数对象；异常统一为 `UPSTREAM`，不触发 ToolNode。
- 完整原生 ToolResult 从 RunnableConfig 移至 Agent 实例私有、按回合隔离的内存存储；模型网关仅透传取消回调，回合结束立即清理正文。
- 受限 JSON Schema 在工具注册时拒绝未实现关键字；ToolNode 不再访问注册表私有字段，附件绑定未知异常记录脱敏类型轨迹。

### V0.6.0（2026-08-25）实施记录

- P2-B 已实施：OpenAI Chat Completions、OpenAI Responses 与 Anthropic Messages 的 SSE 工具参数分别在适配器内累计，并只在参数构成 JSON 对象后输出完整 ToolCall；流末兼容补齐缺失的完成帧，无效参数统一为 `UPSTREAM`。
- `ModelGateway.stream/astream` 已将完整调用投影为内部 `ModelStreamEvent(tool_call)`，同时写入收尾 `ModelResponse.tool_calls`；对外 WebSocket 仍只使用既有 `tool_call`、`tool_result`，不新增参数增量事件，也不暴露不完整参数。
- ReAct 的 native 工具结果回合直接复用流式模型调用：自然语言正文立即显示，继续调用工具时仍回到既有 ToolNode。简单工具读取和总结由三次模型调用降为两次；`legacy` JSON-ReAct 兼容分支保持原有行为。
- 本次未实施：内部 MCP Host/transport、外部 MCP、浏览器直连 MCP、长任务 MCP bridge、真正并行工具调用与独立沙箱 Runner；P3/P4 的安全边界不变。
- 修改文件：`backend/api/app/adapters.py`、`backend/api/app/llm/gateway.py`、`backend/api/app/agent/react.py`、`backend/api/tests/test_adapters.py`、`backend/api/tests/test_llm_graph.py`、`backend/api/tests/test_agent_react.py`。

### V0.7.0（2026-08-25）实施记录

- **P3 内部 MCP Host 已实施**（阶段 D 全部 5 项闭环）：
  - 新增 `harness/execution/mcp/`：`catalog.py`（`ToolCatalog`：tool_id/短名双索引，tool_id 重复与短名跨 server 冲突抛 VALIDATION，refresh 重建）、`provider.py`（`InProcessProvider`：in-process 包装注册表 handler，委托 `execute_raw` 保持既有沙箱/脱敏/错误归一边界）、`manager.py`（`MCPClientManager`：`refresh_catalog`/`call_tool`/`cancel_call`/`close`，同步 handler 经 `asyncio.to_thread` 线程池，超时 cancel + TIMEOUT，`/stop` 取消经 `CancelledError` 穿透，`ToolExecutionContext` 不入 GraphState）。
  - `ToolDef` 扩展 `server_id`/`display_name`/`risk_level`/`execution_mode`/`requires_confirmation`/`supports_streaming`（带默认值）+ `tool_id` 属性 + `to_descriptor()` + `ToolRegistry.iter_defs()`；`build_default_registry` 补 platform.files/web/sandbox 归属与风险等级。
  - `dispatch.py` 拆分 `execute_raw`（返回 ToolResult，不抛、错误归一）与 `execute`（委托 normalize）；`normalize` 在 data 为空时回退 `error.message`。
  - `toolnode.py` `build_tool_node(registry, *, manager=None, ...)`：执行统一经 manager，不再访问 `definition.handler`；顺带修复 execution↔agent 模块加载循环（`agent_trace` 改函数内延迟导入）。
  - `agent/graph.py` 构建 `MCPClientManager` 传入 ToolNode；Agent 图只依赖 manager。
  - `routers/mcp.py` `GET /api/mcp/tools` 改为真实只读目录（API.md §3.6.1 先行更新至 V1.29）：6 项描述符投影，`name=tool_id`，不含命令/凭据。
- 测试：新增 `tests/test_harness_mcp.py` 15 项（catalog list/refresh/冲突、manager 成功/失败/未知/超时/取消/close、router 目录、toolnode 显式/自建 manager 等价与失败 payload）；既有执行层测试签名兼容无改动。
- 验收：`ruff check . ../shared` 全绿；api pytest **411 passed/16 skipped**，worker pytest **34 passed**。
- 本次仍未实施：`platform.tasks` 长任务 MCP bridge、独立沙箱 Runner/容器（bash MCP Server 迁出 api 容器）、真正并行工具调用；P4 安全边界不变，`platform.tasks` 工具不入当前目录。
- 修改文件：`contracts/artifacts.py`+`__init__.py`、`execution/registry.py`、`execution/dispatch.py`、`execution/toolnode.py`、`execution/mcp/`（新增）、`agent/graph.py`、`routers/mcp.py`、`feedback/observation.py`、`execution/__init__.py`、`tests/test_harness_mcp.py`（新增）、`docs/AI测试与评估平台-API.md`（V1.29）。

### V0.8.0（2026-08-25）实施记录 — 原生基础工具直连（本版裁决）

本节覆盖并替代本文此前“所有短工具均经 P3 MCP Host”的实现描述。P3 的
catalog、provider、manager 继续保留，但职责收窄为**未来评测/RAG MCP 扩展**；
它不再包裹基础工具。

#### 1. 最终分层与完整工作链路

```text
用户输入 / 附件
  → ws.py：鉴权、会话、工作区和 RunnableConfig 注入（不 await 整轮 Harness）
  → LangGraph routing → react.py：三协议原生 Function Calling
  → NativeToolCall(call_id, name, arguments)
  → ToolNode：Schema → Gate → 附件绑定 → 选择 transport
       ├─ transport=native（read/write/edit/bash/web_search/web_fetch/task）
       │    → NativeToolExecutor（asyncio.to_thread + 超时/取消）
       │    → 受控 handler / dispatch / bwrap 或 Firecrawl REST
       └─ transport=mcp（未来 benchmark / rag 等扩展）
            → MCPClientManager → catalog → provider → 扩展工具
  → ToolResult → Observation（模型正文与 ToolCard 投影分离）
  → tool_result(call_id) 写 WS 事件；完整正文不落库
  → react.py 第二模型回合：继续调用工具或流式输出分析结论
  → assistant_delta* → assistant_message → response.completed
```

基础工具直连只删除 MCP catalog/provider/短名路由这一层，**不删除** Schema、
权限、附件、重复调用抑制、超时、错误归一、Observation、call_id、二次模型
收敛或 WebSocket 事件。因此工具成功后仍必定回到模型分析，而不是把文件或网页
原文直接交付给用户。

#### 2. 工具能力、性能与安全边界

| 工具 | 原生实现与性能优化 | 安全与结果投影 |
| --- | --- | --- |
| `read` | 0-based 分页，最多 2,000 行/120,000 字符；扫描文件时不再 `readlines()` 保留整文件副本 | realpath/workspace 校验；模型拿完整片段，ToolCard 只拿行统计和 ≤500 字符预览 |
| `write` | `O_EXCL` 排他新建，减少先检查再写入的竞争；单次 ≤2MB | 只写会话 workspace；拒绝覆盖；fsync；不回显写入正文 |
| `edit` | 精确替换一次，在同目录临时文件 fsync 后 `os.replace` 原子提交 | 路径受控；old 不匹配即拒绝；失败不留下临时文件 |
| `bash` | 原生异步线程调度，不经过 MCP provider；仍保留 15 秒工具预算 | bwrap 无网络、唯一可写工作区、资源上限、超时杀整棵进程树；黑名单检查命令链段；引擎不可用 fail-closed |
| `web_search` | 服务端 Firecrawl REST，查询 1–10 条、20 秒预算；不再是成功占位 | Key 只来自 API 环境变量；未配置返回 `VALIDATION`；模型只见结构化标题/URL/摘要 |
| `web_fetch` | 优先 Firecrawl Markdown；未配置 Key 时受控 HTTP 文本抓取；正文上限 20,000 字符 | 仅 http/https，拒绝 URL 凭据、内网和保留 IP；初始 URL 与每次重定向均做 SSRF 校验；ToolCard 只看短预览 |
| `task` | 1–12 步会话内清单，低延迟纯内存计算 | 不是 ORM `Task`；不入队、不建 Worker 任务、不绕过确认卡和 `confirm_ack` |

#### 3. MCP 留给什么，不能做什么

1. 默认注册表的基础工具全部标记 `transport=native`，因此 `/api/mcp/tools`
   返回空数组是“没有扩展已挂载”的真实状态，不是能力失败。
2. 后续 Benchmark、RAG、报告、数据集等需要跨服务协议、异步队列或 Worker
   协作的工具，才登记 `transport=mcp` 并提供 `server_id`/`tool_id`。
3. `task` 拆解不等于创建评测任务。真正入队仍固定为“确认卡 →
   `confirm_ack.ok=true` → `enqueue_long_task`/Worker”；API 进程不得等待终态。
4. MCP 不是沙箱：任何未来 MCP 里的命令执行仍必须复用 bwrap，不能因 transport
   改造降级成裸 subprocess；模型和浏览器均不能提供连接命令、环境变量或密钥。

#### 4. 回归验收

- `tests/test_harness_execution.py`：覆盖行级读取、字符边界、原子写入/编辑、
  bash fail-closed、SSRF、Firecrawl 未配置/结构化结果、task 拆解；
- `tests/test_harness_mcp.py`：验证默认基础工具不进入 catalog、显式 MCP 扩展仍
  支持目录/超时/取消/错误归一，并验证基础 `read` 忽略 MCP manager；
- `tests/test_agent_react.py`：保持原生 ToolCall 后第二模型回合流式分析的契约。

#### 5. 本版修改文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/harness/execution/context.py` | 提取只在运行时存在的 ToolExecutionContext，禁止进入 State/检查点/模型参数。 |
| `backend/api/app/harness/execution/native.py` | 新增 NativeToolExecutor：基础工具直连、线程隔离、超时与取消。 |
| `backend/api/app/harness/execution/registry.py` | 新增 `transport=native|mcp`，默认注册 7 个原生基础工具。 |
| `backend/api/app/harness/execution/toolnode.py` / `agent/graph.py` | 按 transport 分流；没有 MCP 扩展时不构建 manager。 |
| `backend/api/app/harness/execution/dispatch.py` | 读写、编辑、bash、搜索、抓取和 task 的性能、安全与受控 Observation 投影。 |
| `backend/api/app/harness/execution/mcp/*` / `routers/mcp.py` | MCP 目录只收显式扩展；默认返回真实空目录。 |
| `backend/api/app/config.py` / `.env.example` / `docker-compose.yml` | 增加仅 API 容器可见的 Firecrawl 环境变量。 |
| `frontend/src/components/agent/ToolCard.vue` / `views/AdminProfiles.vue` | 显示基础工具中文卡片与受控结果；说明 MCP 空目录的真实含义。 |
| `backend/api/tests/test_harness_execution.py` / `test_harness_mcp.py` | 覆盖直连边界、Firecrawl、SSRF、task 和未来 MCP 回归。 |
| `docs/AI测试与评估平台-API.md` / `AI测试与评估平台-Agent开发文档.md` | 升级对外目录契约和运行时分层说明。 |
