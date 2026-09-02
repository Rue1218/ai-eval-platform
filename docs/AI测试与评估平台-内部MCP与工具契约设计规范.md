# AI 测试与评估平台 — 内部 MCP 与工具契约设计规范

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | 内部 MCP 与工具契约设计规范 |
| 版本 | V1.0 |
| 审查日期 | 2026-09-02 |
| 文档性质 | 只读审计结论 + 契约设计规范（**本版不改对外契约，落地项逐阶段先改 API.md**） |
| 适用范围 | `ToolDef` / `ToolDescriptor` / `ToolCall` / `ToolResult` 契约、JSON Schema 子集、内部 MCP Host、工具提示词、资源寻址 |
| 上游权威 | `docs/AI测试与评估平台-PRD.md`＞`docs/AI测试与评估平台-API.md`＞`docs/AI测试与评估平台-Agent开发文档.md`＞本文 |
| 事实来源 | `backend/api/app/harness/execution/{registry,policy,dispatch,toolnode}.py`、`harness/execution/mcp/{catalog,manager,provider,metrics}.py`、`harness/contracts/artifacts.py`、`harness/prompts/{system,protocols}.py`、`harness/skills/storage.py`、`harness/context/assembly.py`、`app/{adapters,llm/gateway,llm/contracts}.py`、`app/routers/mcp.py`、`requirements.txt` |
| 外部规范对照 | MCP 规范 `2025-11-25` / `2025-06-18`（tools 字段、JSON Schema 用法、三原语）、MCP `ToolAnnotations`（2025-03-26 引入）、JSON Schema 2020-12 |
| 相关文档 | `docs/AI测试与评估平台-ReAct与MCP工具调用重构方案.md`（阶段 A–E 实施史，本文是其**契约规范化续篇**）、`docs/AI测试与评估平台-Harness-执行层.md`、`docs/AI测试与评估平台-混合驱动引擎架构.md` |

---

## 1. 审计结论

### 1.1 先纠正一个前提

需求原话是「模型的调用层没有使用 langchain+langgraph」。**这半句不成立**：

| 框架 | 事实 | 证据 |
| :--- | :--- | :--- |
| **LangChain** | **确实完全没有** | `requirements.txt` 无任何 `langchain*` / `langsmith` 包；全仓 `rg langchain` 零命中 |
| **LangGraph** | **在用，且模型调用层内部就有两张图** | `langgraph==1.2.10`；`llm/gateway.py` 建了 `invoke_model` 与 `stream_model` 两个单节点 `StateGraph`，`invoke/stream/ainvoke/astream` 全部走 `graph.invoke/stream` |

真正的 HTTP 调用不在 LangGraph 里，而在 `app/adapters.py` 手写的三协议适配器（`openai_chat` / `openai_responses` / `anthropic_messages`）。所以准确说法是：**模型调用层用 LangGraph 做节点编排与 custom stream 投影，用手写适配器做协议落地，不引入 LangChain 的 `ChatModel` / `BaseTool` / `AgentExecutor` 抽象**。这个选择是对的，理由见 §7。

### 1.2 问题清单

| # | 问题 | 严重度 | 位置 |
| :--- | :--- | :--- | :--- |
| **F1** | 同一份输入 Schema 在链路上有**三个不同字段名**（`parameters_schema` / `input_schema` / `parameters`），`_adapt_tools` 靠 `or` 兜底兼容 | 🟠 契约漂移 | `registry.py` / `artifacts.py` / `routers/mcp.py` / `adapters.py:248` |
| **F2** | `output_schema` **全链路无运行时校验**，是装饰性字段：注册期只校验「Schema 自身合法」，handler 返回值从不比对 | 🔴 契约失效 | `registry.py:127` 仅 `validate_tool_schema`；`rg output_schema` 除投影外零消费 |
| **F3** | 三个 `transport=mcp` 工具（`task.create` / `task.status` / `task.cancel`）**根本没声明 `output_schema`**，投影为 `{}`。进 MCP 目录的工具反而没有输出契约 | 🔴 契约缺失 | `registry.py` 三处 `ToolDef(...)` 缺 `output_schema=` |
| **F4** | JSON Schema **方言未声明**，只实现 12 个关键字子集，缺 `minItems`/`maxItems` → **数组长度不可约束** | 🟠 校验缺口 | `registry.py:26` `_SUPPORTED_SCHEMA_KEYWORDS` |
| **F5** | 内部 MCP **没有 JSON-RPC、没有 initialize、没有能力协商**，`ToolResult` 形状也不是 MCP 的 `content[]`/`structuredContent`/`isError`。命名叫 MCP 会误导 | 🟠 命名误导 | `mcp/manager.py`（注释自称 tools/list、tools/call）、`mcp/provider.py` |
| **F6** | **资源注册表完全不存在**：MCP 三原语只实现了 tools，`resources/list`、`resources/read`、URI 寻址零实现 | 🟡 能力缺失 | 全仓 `rg resource` 仅命中并发锁键 `tool_resource_key` |
| **F7** | **工具提示词无模板库**：四段式（适用/不适用/前置/推荐用法）硬编码在 `ToolDef.description` 里，且只有 `read`/`edit`/`task` 写全，`write`/`web_search`/`web_fetch`/`bash` 只有一句话 | 🟡 一致性缺失 | `registry.py` 各 `description=` |
| **F8** | `GET /api/mcp/tools/{name}/code` 返回的 `code_snippet` 是**手写的假代码**，与真实实现不符；且只校验登录、无 admin 门禁 | 🔴 伪造展示 | `routers/mcp.py:50` 起 `TOOL_METADATA_EXT` |
| **F9** | `harness/execution/adapters/__init__.py` 是**空占位**（仅一行 docstring），但混合引擎架构文档 ADR-5 已把「`adapters.py` 落 `cache_control`」写成落地位置 | 🟡 文档与代码不一致 | `harness/execution/adapters/__init__.py` |

### 1.3 F8 细节（必须修）

`TOOL_METADATA_EXT` 的 `code_snippet` 不是从磁盘读取的真实源码，而是人工编写的示意代码，与实现存在**实质性偏离**：

| 假代码 | 真实实现 |
| :--- | :--- |
| `_read_handler` 用 `arguments["path"]` | 真实 schema 必填字段是 `file_path`（`path` 只是 handler 内的兜底别名） |
| `_task_create_handler` 直接 `TaskCreateIn(**arguments)` + `Task(...)` 建 ORM 对象 | 真实走 `task_tools.create_task_safe(arguments, context)`，`session_id`/`user_id` 由平台注入 |
| `_task_planner_handler` | **该函数不存在**，真实函数名是 `_task_handler` |
| `_bash_handler` 内联 `bwrap` 参数数组 | 真实经 `sandbox.py` 的 `SandboxLimits` + `run_bash`，且 `sandbox_engine != "bwrap"` 时 fail-closed |

这与 `AGENTS.md` 的「禁止伪造」精神直接冲突：运维或新同事按这个端点理解链路会得出错误结论。**要么改为从 `inspect.getsource()` 取真实源码并加 admin 门禁，要么删掉 `code_snippet` 字段**（推荐后者，见 §8）。

### 1.4 做对了的部分（不要动）

审计中确认以下设计**优于**MCP 官方规范或业界常见做法，规范化时必须保留：

1. **`pattern` 用 `re.search` 而非 `re.fullmatch`** —— 符合 JSON Schema「非锚定部分匹配」语义，很多实现这里是错的；
2. **`_matches_json_type` 显式排除 `bool` 冒充 `integer`/`number`** —— Python `isinstance(True, int)` 为真，这是常见坑；
3. **Schema 关键字白名单是「注册期拒绝未实现语义」而非「运行期静默放行」** —— 不支持 `$ref` / 远程引用 / 任意代码执行，模型参数只能在受控本地边界内被解释；
4. **风险与权限字段是强制执行的策略，不是 MCP 那样的 untrusted hint** —— `risk_level` / `permission_policy` / `concurrency_class` / `requires_confirmation` 由 ToolNode 门禁真实拦截。MCP 官方明确 `annotations`「不保证忠实描述行为，客户端必须视为不可信」，平台这套更强；
5. **`transport=native` 与 `transport=mcp` 分层** —— 基础文件/网络/沙箱工具绝不进 MCP 目录，缩小了 MCP 边界的攻击面；
6. **`call_id` 全链路贯穿**（`NativeToolCall` → `ToolCall` → `tool_call`/`tool_result` 事件 → 下一轮 `tool` 消息），不用工具名猜配对。

---

## 2. 定位裁决：MCP-shaped，不是 MCP-compliant

### 2.1 官方规范要点（对照基线）

| 维度 | MCP 官方要求 |
| :--- | :--- |
| 传输 | 所有消息 **MUST** 遵循 JSON-RPC 2.0；有 `initialize` 生命周期与能力协商 |
| 三原语 | **Tools**（`tools/list`、`tools/call`）、**Resources**（`resources/list`、`resources/read`，URI 寻址只读上下文）、**Prompts**（`prompts/list`、`prompts/get`，可复用模板） |
| 工具字段 | `name`（必填唯一）、`title`（可选展示名）、`description`、`icons`、`inputSchema`（必填，必须是合法 JSON Schema 对象、不可为 `null`）、`outputSchema`（可选）、`annotations`、`execution.taskSupport` |
| Schema 方言 | 无 `$schema` 时默认 **JSON Schema 2020-12**；实现 **MUST** 支持 2020-12，**MUST** 对不支持的方言优雅报错 |
| 无参工具 | 推荐 `{"type":"object","additionalProperties":false}` |
| 结果形状 | `content[]`（`text`/`image`/`audio`/`resource_link`/`resource`）+ 可选 `structuredContent`（**离开 server 前须按 `outputSchema` 校验**）+ `isError` |
| `annotations` | `readOnlyHint`(默认 false)、`destructiveHint`(默认 **true**)、`idempotentHint`(默认 false)、`openWorldHint`(默认 **true**)；全部是 hint，默认值刻意保守 |

### 2.2 裁决

**平台内部 MCP 定位为「MCP-shaped 内部工具目录」，不追求 MCP-compliant。**

理由：

1. 内部 MCP 的两端在**同一个 Python 进程内**（`MCPClientManager` → `InProcessProvider` → `execute_raw`）。为进程内调用套一层 JSON-RPC 2.0 编解码，只会增加序列化开销与故障面，换不来任何互操作收益；
2. 平台红线明确**禁止外部 MCP 默认接入**（混合引擎架构 ADR-8，`external_mcp_enabled=False` fail-closed）。没有第三方 client/server 要对接，协议合规无消费者；
3. `ToolResult` 的 `{ok, data, error}` 形状与平台**十大 ErrorCode 错误契约**同源，改成 MCP 的 `isError` + `content[]` 会把统一错误契约撕开。

**但裁决附带三条强制义务**：

| 义务 | 内容 |
| :--- | :--- |
| **O-1 命名不得误导** | `mcp/manager.py` 的 `refresh_catalog` / `call_tool` 注释里 `tools/list` / `tools/call` 的类比**必须标注「语义类比，非 JSON-RPC 方法」**；模块 docstring 须写明「MCP-shaped，不实现 JSON-RPC 与能力协商」 |
| **O-2 字段名向官方靠拢** | 内部字段名统一为 MCP 语义名（见 §3.3），降低将来接入外部 MCP 时的翻译成本 |
| **O-3 外部 MCP 边界文档化** | 一旦 `external_mcp_enabled=True`，**必须**新增真实 JSON-RPC client 与 2020-12 方言支持；当前 12 关键字子集**不足以**声称支持 2020-12（见 §3.2） |

---

## 3. JSON Schema 规范

### 3.1 现状：12 关键字子集

`registry.py` 的 `_SUPPORTED_SCHEMA_KEYWORDS` 当前允许 12 个关键字：

```text
type  description  properties  required  additionalProperties  enum
items  minLength  maxLength  pattern  minimum  maximum
```

`_SUPPORTED_JSON_TYPES` 允许 7 种类型：`object` `array` `string` `integer` `number` `boolean` `null`（支持 `type` 为类型数组，如 `{"type": ["integer","null"]}`）。

注册期 `validate_tool_schema()` 递归拒绝任何未列出的关键字，运行期 `validate_tool_arguments()` 按同一子集校验模型传参。

### 3.2 必须补的关键字

| 关键字 | 为什么必须补 | 优先级 |
| :--- | :--- | :--- |
| **`minItems` / `maxItems`** | **当前数组长度完全不可约束**。`ask_user_question.questions`、`task.steps`、`profile_ids`、`include_domains` 等数组模型可传任意长度，直接冲击上下文预算与 handler 循环。这是子集里最实质的缺口 | 🔴 P0 |
| **`$schema`（只读容忍）** | 外部 MCP server 会带 `$schema`。当前会被判「不支持的关键字」而注册失败。应**接受并校验其值为 2020-12**，不接受其他方言（对齐官方「MUST 优雅报错」） | 🟠 P1（外部 MCP 前置） |
| **`default`** | 现在默认值只写在 `description` 自然语言里（如「默认 5，平台上限 10」），模型得靠读描述猜。声明式 `default` 让模型少犯错，且不需要执行器实现任何语义（纯声明） | 🟡 P2 |
| **`title`** | MCP 工具字段与 Schema 内层参数的展示名，前端 ToolCard 可直接用，不必再维护一份中文映射 | 🟡 P2 |

**明确不补**（保持注册期 fail-closed）：`$ref`（远程引用 = SSRF 面）、`anyOf`/`oneOf`/`allOf`/`not`（组合语义校验器要重写，且平台工具无此需求）、`format`（`date-time`/`email` 等语义校验引入正则地雷）、`patternProperties`、`dependentSchemas`、`if`/`then`/`else`。

**外部 MCP 的取舍必须写清**：这些关键字不支持意味着，一旦开启外部 MCP，对方 server 只要用了 `anyOf`，注册就会被拒。这是**有意的 fail-closed**，不是缺陷——但必须在 §8 的外部 MCP 落地项里显式声明，避免将来被当成 bug 修成「静默放行」。

### 3.3 命名统一（修 F1）

一份 Schema 现在有三个名字，链路如下：

```text
ToolDef.parameters_schema
   ├─ to_descriptor() ──► ToolDescriptor.input_schema ──► routers/mcp.py 输出键名 "parameters_schema"
   ├─ all_defs()/get_def() ──► dict 键名 "parameters_schema" ──► assemble() tools ──► _adapt_tools()
   └─ _adapt_tools() 兜底：definition.get("parameters_schema") or definition.get("parameters") or {...}
```

**规范裁决**：

| 层 | 统一后的字段名 | 说明 |
| :--- | :--- | :--- |
| Python 内部契约（`ToolDef` / `ToolDescriptor`） | **`input_schema` / `output_schema`** | 蛇形命名符合 Python 惯例，语义与 MCP `inputSchema`/`outputSchema` 一一对应 |
| 对外 REST（`/api/mcp/*`） | **`input_schema` / `output_schema`** | **须先改 API.md**；`parameters_schema` 保留一个版本作为别名同时输出，前端切换后再删 |
| 上游模型线格式 | 各协议原生名 | `openai_chat`/`openai_responses` → `parameters`；`anthropic_messages` → `input_schema`。**这层不统一**，由 `_adapt_tools` 负责翻译，是正确的边界 |

`_adapt_tools` 的 `or` 兜底链在迁移期保留，迁移完成后**收敛为单一键名**并对缺失键抛 `VALIDATION`。当前行为是**静默降级**：两个键都取不到时回退成 `{"type":"object","properties":{}}`，工具会带着「无参数」的空 Schema 发给模型——比报错更难排查，因为模型会照着空 Schema 发起无参调用，然后在 `validate_tool_arguments` 阶段才因缺必填参数失败。

### 3.4 已知小瑕疵（低危，记录不急修）

1. **`enum` 的 Python 等值陷阱**：`value not in enum` 中 `True == 1`、`1.0 == 1` 均为真，故 `{"enum": [1]}` 会接受 `true`。平台现有 enum 全为字符串枚举，暂不触发；补 `minItems` 时一并加 `type` 前置判定即可；
2. **`_validate_schema_value` 对 `additionalProperties: false` 只在 `Mapping` 分支生效**，非对象值不检查——语义正确，无需改；
3. **无参工具写法已合规**：`TaskList` 用 `{"type":"object","additionalProperties":false,"properties":{}}`，正是 MCP 推荐形式。

---

## 4. 工具注册表规范

### 4.1 `ToolDef` 字段分类（唯一事实源）

`ToolRegistry` 是「白名单与分派唯一源」，重名登记抛 `VALIDATION`。字段按**可见性**分四类，这个分类必须显式化，因为它决定了什么能到模型、什么只能留在服务端：

| 类别 | 字段 | 可见范围 |
| :--- | :--- | :--- |
| **模型可见** | `name`、`description`、`input_schema` | 经 `select_tool_defs` → `assemble()` → `_adapt_tools` 送上游 |
| **前端可见** | `display_name`、`output_schema`、`risk_level`、`execution_mode`、`timeout_s`、`requires_confirmation`、`supports_streaming`、`permission_policy`、`recovery_policy` | 经 `/api/mcp/all-tools` 投影；**脱敏后**用于 ToolCard |
| **仅执行层** | `handler`、`contextual`、`concurrency_class`、`requires_prior_result`、`permission` | **不投影到模型 / MCP 目录 / 浏览器**（`concurrency_class` 注释已明确） |
| **路由用** | `transport`、`server_id`、`tool_id` | 模型参数中**不得携带**（`ToolDescriptor` docstring 已明确） |

**铁律**：新增字段必须在本表归类。归类不明的字段一律先归「仅执行层」。

### 4.2 MCP `annotations` 等价映射（不新增字段）

平台**不引入** `annotations` 对象，理由是平台字段更细且是强制执行的。但为了将来能对外投影，固定如下**推导规则**（只读派生，不落库）：

| MCP hint | 平台推导 |
| :--- | :--- |
| `readOnlyHint` | `risk_level in {"read"}` → `true`；其余 `false` |
| `destructiveHint` | `risk_level in {"modify","code"}` → `true`；`read`/`network` → `false`。注意 `write` 工具实际**不覆盖已有文件**（`write_file_safe` 拒绝已存在路径），语义偏 additive，但保守起见仍标 `true` |
| `idempotentHint` | `recovery_policy.retryable_codes` 非空且 `max_auto_repairs > 0` → `true`；`write`/`bash`（`max_auto_repairs=0`）→ `false` |
| `openWorldHint` | `risk_level == "network"` → `true`（`web_search`/`web_fetch`）；其余 `false`（沙箱与 PG 均为闭域） |
| `title` | `display_name` |

**这张表只用于「若将来对外暴露 MCP 目录」**。平台自身的门禁**永远读 `permission_policy` 与 `risk_level`，不读推导出的 hint**——官方也明确 hint 不可信、真正的安全保证必须落在确定性控制上。

### 4.3 `output_schema` 强制化（修 F2 / F3）

三条规范：

1. **所有工具必须声明非空 `output_schema`**。`ToolRegistry.register()` 增加校验：`output_schema` 为空字典时抛 `VALIDATION`（现有三个 MCP 工具必须补齐）；
2. **运行期按 `output_schema` 校验 handler 返回的展示投影**，位置在 `execute_raw` 归一之后、`ToolResult` 构造之前。校验失败**不得**把原始返回发给浏览器，而是归一为 `INTERNAL` + `agent_trace` 记录工具名与失败字段名（不打印值）；
3. **`output_schema` 不发给模型**。当前 `_adapt_tools` 只取输入 Schema，这是对的——三家上游的 `tools` 参数都不吃 outputSchema。模型侧的输出约束由 `Observation.text` 的归一格式承担。

第 2 条是对齐 MCP「structuredContent 离开 server 前须校验」的核心义务，也是让 `output_schema` 从装饰变成契约的唯一办法。

### 4.4 数组长度约束落地（修 F4 的 P0 项）

补 `minItems`/`maxItems` 后，以下现有 Schema **必须**同批加上限，否则约束能力仍是零：

| 工具.参数 | 建议上限 | 依据 |
| :--- | :--- | :--- |
| `ask_user_question.questions` | `maxItems: 5` | 一次澄清不应超过 5 问，超过说明该走 Workflow 槽位收集 |
| `ask_user_question.questions[].options` | `maxItems: 10` | 前端单选/多选可读性上限 |
| `task.steps` | `maxItems: 20` | 与「3–7 步计划」的 description 引导一致，留冗余 |
| `task.tools` | `maxItems: 20` | 仅展示字段，防超长 |
| `task.create.profile_ids` | `maxItems: 10` | 与协议档实际规模匹配 |
| `task.create.rag_mode` | `maxItems: 4` | 枚举只有 4 个值，去重后天然上限 |
| `web_search.include_domains` / `exclude_domains` | `maxItems: 20` | 域名白/黑名单 |
| `web_fetch.allowed_domains` / `blocked_domains` | `maxItems: 20` | 同上 |

---

## 5. 资源注册表规范（新建，修 F6）

### 5.1 为什么该建

MCP 把 **Resources** 定义为「URI 寻址的只读上下文」，与 Tools（执行动作）正交。平台当前把所有「读取素材」的需求都塞进 tools：`read` 读工作区文件、附件靠 `require_owned_attachment` 权限位、数据集/报告只能经 REST 拿。

**素材其实已经就位**：`Observation.source` 字段的注释已经写明「复用 messages 表 source_id 格式（如 `file:uuid` / `message:uuid`）」——**平台已经在用 URI 风格寻址，只是没有注册表**。

### 5.2 资源注册表设计

```text
ResourceDef（新建，与 ToolDef 平级，同属执行层注册表）
├─ uri_scheme: Literal["file", "message", "dataset", "report", "kb"]
├─ name / description                  # 模型可见
├─ resolver: Callable[[str, ctx], ...]  # 仅执行层，不投影
├─ permission: str                      # 复用现有权限标识体系
├─ permission_policy: ToolPermissionPolicy   # 复用，不新造
├─ mime_type: str                       # 如 "text/markdown"
└─ max_bytes: int                       # 单次读取预算上限
```

| 规范项 | 内容 |
| :--- | :--- |
| **URI 格式** | `<scheme>:<uuid>`，与既有 `source_id` **同一格式**，不另造。禁止 `http(s)://` 等出网 scheme（出网只能走 `web_fetch` 的 SSRF 防护链） |
| **归属校验** | 每次解析**必须**校验资源属于当前 `session_id` / `user_id`，与 `require_owned_attachment` 同一套判定。资源注册表不是绕过附件归属的后门 |
| **只读铁律** | Resources **只读**。任何写操作必须是 tool，不得做成「写资源」 |
| **上下文预算** | 资源正文**不入 `GraphState`**，与 Skill 正文同一处理（Progressive Disclosure）；只有归一后的 `Observation` 进历史 |
| **不实现 `resources/subscribe`** | MCP 有订阅与变更通知，平台无消费者，fail-closed 不做 |

### 5.3 与现有 `read` 工具的边界

**不要把 `read` 改成资源读取。** 边界是：

- `read` = 会话**工作区**内的相对路径文本文件，模型自主探索用（`path_scoped` 并发类）；
- Resources = 平台**已登记实体**（附件、数据集、黄金 QA、报告），有 UUID、有归属、有 MIME 类型。

两者重叠的部分（用户上传的附件）当前走 `read` + 附件归属校验，**保持不变**；资源注册表首批只覆盖 `dataset` / `report` / `kb` 三个 scheme，这三个现在模型完全拿不到。

---

## 6. 工具提示词模板库规范（新建，修 F7）

### 6.1 现状与错位

「工具提示词模板库」当前**不存在**。`harness/prompts/` 里是：

| 文件 | 内容 | 是不是工具提示词 |
| :--- | :--- | :--- |
| `system.py` | 五段固定系统策略（角色/安全/确认卡/长短任务/密钥保护）+ 三个受控占位符白名单 | ❌ 会话级人格，非工具级 |
| `protocols.py` | `plan.v1` / `react.v1` / `reflect.v1` 三个严格 JSON 协议 Schema | ❌ 阶段输出协议，非工具描述 |
| `safety.py` | 安全断言 | ❌ |

工具级提示词实际硬编码在 `registry.py` 的 `description=` 字符串里，且**质量分布极不均匀**：

| 工具 | description 形态 |
| :--- | :--- |
| `read` | 完整四段式：适用 / 不适用 / 前置 / 推荐用法（含分页反模式警告） |
| `edit` | 完整四段式 |
| `task` | 完整四段式 |
| `write` | **一句话**：「在沙箱目录内新建文本文件（相对路径）」 |
| `web_search` / `web_fetch` | **一句话** |
| `bash` | **一句话** |
| `task.create` / `task.status` / `task.cancel` | 一句话（长任务语义靠 `system.py` 兜） |

`read` 那段之所以写得长，是因为踩过「模型反复小窗口读同一文件」的坑。**其余工具的坑只是还没踩到，不是不存在**——`write` 不覆盖已有文件这条硬语义，现在只写在 `recovery_policy.default_hint` 里（失败后才看得到），模型第一次调用前看不见。

### 6.2 模板库设计

新建 `harness/prompts/tools.py`，定义四段式模板与装配函数：

```text
ToolPromptTemplate（frozen dataclass）
├─ summary: str        # 一句话，必填。等价现在的短 description
├─ use_when: str       # 适用场景，必填
├─ avoid_when: str     # 不适用 + 应改用哪个工具，必填
├─ preconditions: str  # 前置条件（路径要求、须先 read 等），可空
└─ best_practice: str  # 推荐用法与反模式，可空
```

| 规范项 | 内容 |
| :--- | :--- |
| **装配** | `render(template) -> str` 拼成模型可读文本，结果赋给 `ToolDef.description`。**`ToolDef` 字段不变**，只是 description 的来源从裸字符串变成模板渲染 |
| **注册期强制** | `summary` / `use_when` / `avoid_when` 三段**必填非空**，缺失抛 `VALIDATION`。这是让 `write`/`bash` 补齐的强制手段 |
| **`avoid_when` 必须点名替代工具** | 现有 `read` 的「不适用：创建文件（用 write）」是正确范式。工具越多，误用成本越高 |
| **长度预算** | 单工具渲染结果 ≤ 600 字符。工具描述常驻每轮上下文，写成说明书会挤占窗口 |
| **不做的事** | **不引入 Jinja2 等模板引擎**。四段式是固定结构，f-string 足够；引模板引擎等于在提示词层开一个任意代码执行面 |

### 6.3 与 MCP `prompts` 原语的关系

MCP 第三原语 **Prompts**（`prompts/list` / `prompts/get`，可复用模板）在平台**已有功能对应物：`SKILL.md`**（`skills/storage.py` + `list_hints()` 的常驻目录 + `load_skill_workflow()` 的按需正文）。

**裁决**：`SKILL.md` 就是平台的 prompts 原语，**不再另建一套**，也不对外暴露 `prompts/*` 端点。§6.2 的工具提示词模板库与 SKILL.md 分工是：

| 载体 | 粒度 | 注入时机 |
| :--- | :--- | :--- |
| `ToolPromptTemplate` | **单个工具**怎么用 | 随 `tools` 每轮常驻 |
| `SKILL.md` | **一类业务**怎么走流程 | Hint 常驻，正文按需（Progressive Disclosure） |

---

## 7. 模型调用层与框架边界

### 7.1 LangGraph 用在哪（三处，各有理由）

| 位置 | 图结构 | 为什么值得用图 |
| :--- | :--- | :--- |
| `llm/gateway.py` | `START → invoke_model → END` 与 `START → stream_model → END` 两张单节点图 | 为了 **custom stream 与 `RunnableConfig` 透传**：`get_stream_writer()` 投影正文/推理/工具调用增量，`should_abort` 经 `configurable.abort` 注入而**不入 State**（回调不可序列化，不能进检查点） |
| `agent/graph.py` | `START → chat_stream → END`（骨架化后） | 检查点、中断、流式的统一宿主 |
| `worker/app/eval_graph.py` | Worker 侧评测图 | 长任务编排 |

单节点图看着像过度设计，但换来的是**取消回调与流式写入器不必手工穿参**——`gateway.py` 的 docstring 已明确「这里不放 Agent 循环、工具节点、确认卡、记忆和任务队列，避免模型层重新膨胀成 Harness」。这个边界要守住。

### 7.2 为什么不引入 LangChain（规范化为红线）

| LangChain 抽象 | 平台已有的替代 | 引入的代价 |
| :--- | :--- | :--- |
| `ChatModel` / `BaseChatModel` | `ModelGateway` + `adapters.py` 三协议手写适配 | 平台需要 `reasoning_effort`、`anthropic_version`、`tool_call_mode`(native/legacy) 逐协议档差异化控制，还要按协议档灰度原生流式（`stream_policy.py`）。这些都得穿透 LangChain 的抽象层，等于同时维护两套 |
| `BaseTool` / `StructuredTool` | `ToolDef` + `ToolRegistry` | `ToolDef` 携带 `permission_policy` / `recovery_policy` / `concurrency_class` / `risk_level` 四类平台专有策略，`BaseTool` 无处安放，只能塞 metadata dict，反而失去类型 |
| `AgentExecutor` | LangGraph 图 + Harness 九层 | 直接违反「禁止第二个 Harness 循环」红线 |
| `output_parser` | `prompts/protocols.py` 严格 JSON + 版本不兼容策略 | 平台要求协议版本**严格不兼容**（旧版直接拒绝，无兼容窗口），LangChain parser 的容错重试与之冲突 |

**红线**：不引入 `langchain` / `langchain-core` / `langchain-community` / `langsmith` 任何包。模型侧新能力一律加在 `adapters.py` + `ModelConfig`。

### 7.3 线格式翻译边界（保持现状）

`_adapt_tools` 的三分支是**正确且必要**的，规范化确认：

| 协议 | 工具描述形状 |
| :--- | :--- |
| `openai_chat` | `{"type":"function","function":{"name","description","parameters"}}` |
| `openai_responses` | `{"type":"function","name","description","parameters"}`（扁平，无嵌套 `function`） |
| `anthropic_messages` | `{"name","description","input_schema"}` |

这层**不做统一**。内部统一叫 `input_schema`（§3.3），到线上按各家原生名翻译，翻译只发生在 `adapters.py` 一处。

---

## 8. 落地清单

每项一分支一 PR，先改契约再改代码（`AGENTS.md` §3.1）。

| # | 落地项 | 契约影响 | 建议分支 | 验收断言 |
| :--- | :--- | :--- | :--- | :--- |
| **T1** | 补 `minItems`/`maxItems` 关键字 + §4.4 全部数组上限 | 无（收紧校验） | `feat/tool-schema-array-bounds` | 超长数组入参被 `VALIDATION` 拒绝；既有用例全绿 |
| **T2** | `output_schema` 强制非空 + 运行期校验（§4.3） | 无（内部校验） | `feat/tool-output-schema-enforce` | 三个 `task.*` MCP 工具补齐 Schema；校验失败归一 `INTERNAL` 且不外泄原文 |
| **T3** | 删除 `code_snippet` 假代码与 `/tools/{name}/code` 端点（或改真源码 + admin 门禁） | **改 API.md**（删端点） | `fix/mcp-fake-code-snippet` | `rg code_snippet` 零命中；前端不再请求该端点 |
| **T4** | 字段名统一为 `input_schema`/`output_schema`（§3.3），`parameters_schema` 作别名过渡一版 | **改 API.md** | `refactor/tool-schema-naming` | `_adapt_tools` 缺键抛 `VALIDATION` 而非静默降级为空 Schema |
| **T5** | 新建 `harness/prompts/tools.py` 模板库，`write`/`bash`/`web_*` 补齐四段式 | 无 | `feat/tool-prompt-templates` | 注册期缺三必填段即失败；单工具渲染 ≤ 600 字符 |
| **T6** | `mcp/manager.py` 与 `mcp/provider.py` docstring 标注 MCP-shaped（O-1） | 无 | 随 T4 一并 | 注释不再让读者以为有 JSON-RPC |
| **T7** | 资源注册表首批（`dataset`/`report`/`kb` 三 scheme） | **改 API.md + PRD** | `feat/resource-registry` | 归属校验不通过即 `UNAUTHORIZED`；资源正文不入 State |
| **T8** | `harness/execution/adapters/__init__.py` 空占位处置（修 F9） | 无 | 随混合引擎 H0 | 要么落 `cache_control` 实现，要么删目录并改架构文档 ADR-5 的位置表述 |
| **T9** | `$schema` 只读容忍 + 2020-12 校验 | 无 | 外部 MCP 立项时 | 非 2020-12 方言明确报错而非静默 |

**优先级**：T1 → T2 → T3 为一组（都是「契约名不副实」类问题，且互不依赖）；T4 → T6 一组；T5 独立可并行；T7 依赖产品拍板；T9 挂外部 MCP 立项。

---

## 9. 明确不做

1. **不实现 JSON-RPC 2.0 内部传输**（§2.2 裁决，进程内无收益）；
2. **不实现 MCP `initialize` 与能力协商**（无第三方端点）；
3. **不把 `ToolResult` 改成 MCP 的 `content[]` / `structuredContent` / `isError`**（会撕开十大 ErrorCode 统一契约）；
4. **不引入 `annotations` 字段**，只保留 §4.2 的只读推导规则；
5. **不实现 `resources/subscribe`** 与资源变更通知；
6. **不对外暴露 `prompts/*`**，SKILL.md 即平台 prompts 原语（§6.3）；
7. **不引入任何 LangChain 包**（§7.2 红线）；
8. **不支持 `$ref` / `anyOf` / `oneOf` / `allOf` / `format` / `patternProperties`**（§3.2，有意 fail-closed）；
9. **不引入模板引擎**做工具提示词（§6.2）；
10. **不默认开启外部 MCP**（沿用混合引擎架构 ADR-8 的 fail-closed）。

---

## 10. 术语

| 术语 | 含义 |
| :--- | :--- |
| **MCP-shaped** | 借用 MCP 的目录/调用/描述符**概念形状**，但不实现 JSON-RPC 传输与能力协商的内部工具目录 |
| **MCP-compliant** | 完整实现 MCP 规范（JSON-RPC 2.0 + 生命周期 + 三原语 + 结果形状），可与任意 MCP client 互操作。**平台不追求** |
| **三原语** | MCP 的 Tools（执行动作）/ Resources（URI 寻址只读上下文）/ Prompts（可复用模板） |
| **线格式** | 发往上游模型 HTTP 请求体里的工具描述形状，逐协议不同，只在 `adapters.py` 翻译 |
| **装饰性字段** | 已声明、有投影、但**无任何运行时消费者**的契约字段（`output_schema` 修复前的状态） |
| **四段式工具提示词** | summary / use_when / avoid_when / preconditions + best_practice 的固定结构 |
| **untrusted hint** | MCP `annotations` 的定位：描述而非强制，客户端必须视为不可信。与平台强制执行的 `permission_policy` 有本质区别 |

---

## 修改代码文件与作用清单

本文档为**只读审计 + 契约设计规范**，未修改任何源码、配置、依赖或数据库迁移。

- `docs/AI测试与评估平台-内部MCP与工具契约设计规范.md`（新增）：V1.0 审计 ToolCall 设计与内部 MCP 实现，对照 MCP `2025-11-25`/`2025-06-18` 规范、`ToolAnnotations` 与 JSON Schema 2020-12，产出 9 项问题清单（F1–F9）、MCP-shaped 定位裁决与三条强制义务（O-1…O-3）、JSON Schema 12 关键字子集规范与必补/不补关键字裁决、`ToolDef` 四类可见性分类、MCP `annotations` 只读推导映射表、`output_schema` 强制化与运行期校验规范、数组长度上限清单、资源注册表（`ResourceDef` + URI 复用 `source_id` 格式）新建规范、工具提示词四段式模板库（`ToolPromptTemplate`）新建规范、LangGraph 三处用法与不引入 LangChain 的四条红线依据、T1–T9 落地清单与 10 项明确不做。

**待回写的既有文档**（实施各阶段时同步，`AGENTS.md` §1.4 文档闭环要求）：

- `docs/AI测试与评估平台-API.md`：T3 删 `/api/mcp/tools/{name}/code`、T4 字段名 `input_schema`/`output_schema`、T7 资源注册表端点；
- `docs/AI测试与评估平台-Harness-执行层.md`：§4.1 `ToolDef` 四类可见性分类、§4.3 `output_schema` 运行期校验位置；
- `docs/AI测试与评估平台-Harness-提示词工程层.md`：§6 工具提示词模板库归属本层；
- `docs/AI测试与评估平台-Harness-跨层契约层.md`：`ToolDescriptor` 字段改名与 `ResourceDef` 新契约；
- `docs/AI测试与评估平台-ReAct与MCP工具调用重构方案.md`：标注 §5「ToolCall 与内部 MCP Host」的契约规范化续篇为本文；
- `docs/AI测试与评估平台-混合驱动引擎架构.md`：ADR-5 中 `adapters.py` 落 `cache_control` 的位置表述需按 T8 结论修正（当前该文件为空占位）；
- `docs/AI测试与评估平台-模型调用层LangGraph重设计.md`：§7.2 不引入 LangChain 的红线依据回写。
