# 协议档供应商与思考强度适配

版本：V1.5 ｜ 审查日期：2026-09-17

## 产品与接口增量

供应商新建入口限定 GLM、DeepSeek、阿里百炼、Kimi、MiniMax、NVIDIA、火山引擎、Gemini、OpenAI、Anthropic、New API、Ollama；已有其它协议档保留可管理。供应商表示托管服务，模型品牌用于 Agent 图标，两者独立识别。

统一选择项为 `off / low / medium / high / max`。未选择对话档位时 `reasoning_effort` 默认 `off`；原生 Claude 默认 `high`。不能关闭思考的型号仅提供真实可用选项，并明确说明；只支持开关的型号四个开启档等价，不能宣称有四种原生强度。保留旧回合 `xhigh` 读取兼容，新界面不提供该选项。

协议档页面、列表、编辑弹窗均不提供思考强度设置，不持久化可编辑的协议档默认强度。仅对话输入框保留档位选择。默认值从供应商与模型能力推导；`turn.submit` 显式选择覆盖默认值，旧全局 `agent_reasoning` 仅供 legacy 链路读取。

Profile 响应增加只读 `provider, reasoning_effort, allowed_efforts, reasoning_note`，与 Agent UI 的能力判断共用实际 resolver。Agent UI 脱敏协议档增加 `provider, reasoning_note`，仍不包含端点或密钥。管理页按服务供应商分组，Agent 按模型品牌显示图标。

## 官方依据与映射原则

### 供应商协议与 Base URL 矩阵

快速填充以供应商和协议为联合键。原厂预设切换协议时同时替换 Base URL 与建议模型；New API / Ollama 保留已填写地址与模型；未登记表示官方没有公布该兼容层，界面禁用该组合，但不影响用户手工维护已有自建网关。

| 供应商 | OpenAI Chat Base URL | Anthropic Messages Base URL | Anthropic 思考模板 |
| --- | --- | --- | --- |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `https://open.bigmodel.cn/api/anthropic` | `thinking.type` 开关，逐档探测 |
| DeepSeek | `https://api.deepseek.com` | `https://api.deepseek.com/anthropic` | `thinking.type` + `output_config.effort` |
| 阿里百炼（北京按量） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `https://dashscope.aliyuncs.com/apps/anthropic` | 千问预算；DeepSeek/GLM 等托管模型按模型方言 |
| Kimi | `https://api.moonshot.cn/v1` | `https://api.moonshot.cn/anthropic` | Kimi K3 使用 `output_config.effort` |
| MiniMax（中国区） | `https://api.minimax.cn/v1` | `https://api.minimax.cn/anthropic` | M2 固定思考；M3 adaptive 开关 |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1`（API Catalog）或实际部署 `/v1` 根地址 | 实际 NIM 部署根地址（请求为 `/v1/messages`） | 标准 thinking 预算；实际支持取决于 NIM 版本与模型 |
| 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3` | `https://ark.cn-beijing.volces.com/api/coding` | Coding Plan 专用，`thinking.type` 开关并逐档探测 |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | 官方未提供 | — |
| OpenAI | `https://api.openai.com/v1` | 官方未提供 | — |
| Anthropic | 官方未提供 | `https://api.anthropic.com` | 新型号 adaptive + effort；旧型号预算 |

百炼域名和 API Key 受地域、工作空间及计费方案约束；表中使用华北 2（北京）按量付费共享域名。火山 `/api/coding` 必须使用 Coding Plan Key，不能与按量付费 `/api/v3` 的用途混淆。NVIDIA 官方确认 NIM 2.x 暴露 `/v1/messages`，但该地址属于用户实际部署且没有统一公网 Base URL；界面切到 NIM Anthropic 协议后要求手工填写部署地址，扩展思考仍以保存前的真实探测为最终门禁。

### 完整 URL 开关

协议档创建、更新和响应新增布尔字段 `full_url`，创建默认 false，更新省略则保留；保存为 `AI_PROFILE_<ID>_FULL_URL`。开启后主模型请求严格使用填写的完整 URL（保留尾斜线与查询串），不追加任何版本或协议资源后缀；关闭时按供应商 Base URL 补齐路径。应用于 Agent、探活、评测、裁判、用例生成与压测，Embedding/Reranker 独立地址不受影响。完整 URL 模式不推导 `/models`，界面禁用获取模型按钮并提示手动填写模型；模型列表接口返回 `VALIDATION`。`FetchModelsIn.full_url` 可选，省略时采用已保存协议档设置。

- [OpenAI reasoning](https://developers.openai.com/api/docs/guides/reasoning)：按型号映射 `none/minimal/low/medium/high/xhigh`，平台 max 映射型号支持的最高档。
- [Anthropic effort](https://platform.claude.com/docs/en/build-with-claude/effort)：支持 adaptive 的 Claude 使用 `output_config.effort`；旧扩展思考型号使用预算，预算严格小于总输出上限。
- [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/)：开关 `thinking.type`，V4 使用 low/high/max；medium 映射 high；Anthropic 协议使用 `output_config.effort`。
- [百炼深度思考](https://help.aliyun.com/zh/model-studio/deep-thinking)：`enable_thinking` 与 `thinking_budget`，按已知支持型号开放；预算档为平台映射。
- [GLM](https://docs.bigmodel.cn/cn/guide/models/text/glm-4.5)：`thinking.type` 开关，不虚构 effort 参数。
- [Kimi](https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart)：K2.5/K2.6 开关，固定温度约束，历史 thinking 型号不能关闭。
- [MiniMax](https://platform.minimax.io/docs/api-reference/text-openai-api)：M2 系列不能关闭思考；M3 使用 adaptive/disabled；`reasoning_split` 仅分离返回字段，不是思考开关。
- [NVIDIA NIM](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b)：按模型卡配置 `chat_template_kwargs`，不沿用被托管模型原厂参数。
- [火山 Chat Completions](https://www.volcengine.com/docs/82379/1494384)：`thinking.type`；支持的 Seed 型号映射 reasoning_effort，部署 ID 无法可靠推断型号时不虚构强度。
- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)：2.5 使用预算，3 系列使用 level；不能关闭思考的型号不发布 off。
- [DeepSeek Anthropic API](https://api-docs.deepseek.com/guides/anthropic_api/)：Base URL 为 `/anthropic`，支持 `thinking` 和 `output_config.effort`。
- [百炼地域与计费 Base URL](https://help.aliyun.com/en/model-studio/base-url)：分别列出 OpenAI 与 Anthropic 兼容地址。
- [智谱 Claude API 兼容](https://docs.bigmodel.cn/cn/guide/develop/claude/introduction)：Base URL 为 `/api/anthropic`。
- [Kimi Messages API](https://platform.kimi.com/docs/api/messages)：Base URL 为 `/anthropic`，支持思考和 `output_config`。
- [MiniMax 兼容协议配置](https://platform.minimax.cn/docs/token-plan/other-tools)：中国区同时提供 `/v1` 与 `/anthropic`。
- [NVIDIA NIM API Reference](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html)：NIM 暴露 OpenAI Chat 与 Anthropic `/v1/messages`，扩展思考依赖模型和 vLLM。
- [Anthropic API overview](https://platform.claude.com/docs/en/api/overview)：原生 API 根地址为 `https://api.anthropic.com`。

## 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/llm/providers/{catalog,options,openai,anthropic,common}.py`、`llm/{resolver,contracts,loop_contracts}.py` | 按供应商解析能力、映射请求参数，保留 MiniMax 思考往返状态，支持完整 URL |
| `backend/api/app/{profile_reasoning,profile_env,schemas}.py`、`routers/{profiles,sessions,ws}.py`、`agent/{loop_wiring,loop_presentation}.py` | 供应商默认值、只读能力投影、完整 URL 保存和调用接线 |
| `backend/shared/model_urls.py`、API `adapters.py/llm_client.py/llm/gateway.py/harness/memory/state.py`、Worker `profile_env.py/protocol.py/benchmark.py/eval_graph.py/testcase.py/stress.py` | 主模型端点规则贯通同步、异步、后台任务与恢复配置 |
| `frontend/src/views/AdminProfiles.vue`、`components/modals/ProfileModal.vue` | 两列供应商卡片、按供应商限制协议选项、协议切换同步 URL/模型、完整 URL 开关、数值输入和异步反馈 |
| `frontend/src/assets/providers/`、`components/ProviderLogo.vue`、`utils/{providerLogo,profileVendors}.ts`、`components/agent/loop/{AgentComposer,AgentWorkspace,ThinkingControl}.vue` | 十二个预设供应商品牌矢量图标、托管服务与模型品牌区分、对话档位能力提示 |
| API/Worker 协议档与 URL 回归测试、前端品牌识别测试 | 验证 SDK 最终请求、完整 URL 原样保留、能力与品牌识别 |

验证：本地 API 全量回归 1572 passed / 78 skipped；Worker 50 passed；前端单元测试 97 passed；前端类型检查与生产构建通过。协议参数测试使用真实官方 SDK + MockTransport，不请求生产模型；最终供应商能力仍需用用户配置的 API Key 执行保存前探测。品牌资源来源与许可见 `frontend/src/assets/providers/README.md`。

## V1.1 修订说明与修改代码文件清单（2026-09-15）

修复快速填充把单一 Base URL 跨协议复用的问题。供应商预设改为 `供应商 × 协议` 矩阵；选择 DeepSeek 的 Anthropic Messages 后会使用 `https://api.deepseek.com/anthropic`，并加载原厂 Messages 思考强度模板。协议选择器保留两个统一选项，但对官方未提供的组合显示“官方未提供”并禁用。自建兼容网关和已有非预设协议档仍可手工编辑。

| 修改文件 | 作用 |
| --- | --- |
| `frontend/src/utils/profileVendors.ts` | 登记十家供应商的协议支持、Base URL、建议模型和套餐提示 |
| `frontend/src/components/modals/ProfileModal.vue` | 协议切换同步预设；禁用未登记组合；展示供应商协议说明 |
| `backend/api/app/llm/providers/reasoning_templates.py`、`catalog.py` | 增加 DeepSeek 原厂与 NVIDIA NIM 的 Anthropic Messages 思考模板，并识别 MiniMax 中国区官方域名 |
| `backend/api/app/llm/providers/anthropic.py` | 允许 NIM 兼容流回放无签名 thinking 块，原生 Claude 仍严格校验签名 |
| `frontend/tests/profileVendors.test.mjs`、`backend/api/tests/test_reasoning_templates.py` | 覆盖完整协议矩阵、官方 URL、模板推荐和最终 SDK 请求字段 |


## 2026-09-17 Responses 协议与 New API / Ollama 供应商

- 协议枚举增加 `openai_responses`，适用于协议档创建/更新、模型发现、验证、Agent、Judge、被测模型和派生压测。默认路径为 `POST {base}/v1/responses`；已有版本段不重复追加，完整 URL 保留路径与查询串。
- 请求使用 `input`、`instructions`、`max_output_tokens` 和扁平函数工具，默认 `store=false`；工具结果以 `function_call_output.call_id` 配对。平台持有完整历史，Responses 的原始 output 项（含加密 reasoning）按现有协议状态兼容边界回填，不依赖 previous_response_id。
- 流式文本/思考摘要/函数参数映射到既有 Agent 事件，不增加 WS 事件名。失败/缺少终态不视为成功；截断以 length 收尾，非流式评测拒绝截断响应。input_tokens/output_tokens 归一用量，保留缓存与推理明细。
- 新建供应商增加 New API 与 Ollama。New API 可选 Chat、Responses、Messages，地址和模型由用户填写；实际通道支持以真实探测为准。Ollama 提供 Chat 和 Responses，默认地址 http://localhost:11434/v1，必须改为 API/Worker 可访问地址（容器中的 localhost 指容器自身），模型从服务获取或手填。
- Ollama 本地服务可用 `ollama` 作为 SDK 所需的非空占位 Key，受认证代理应填写真实 Key；不放宽其它协议档凭据校验。供应商仍沿用现有预设/端点/名称识别，不新增持久供应商字段。
- Responses 受控思考模板使用 reasoning.effort；各档位必须真实验证通过后才保存为可选能力。

### 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/shared/responses.py`、`model_urls.py`、`models.py` | 共享编解码、端点及协议约束 |
| `backend/api/migrations/versions/*responses*.py` | 扩展协议 CHECK 约束，回退前拒绝存在 Responses 档 |
| `backend/api/app/llm/providers/responses.py`、`options.py`、`reasoning_templates.py`、`resolver.py` | 原生 Responses 流、历史回填与思考模板 |
| `backend/api/app/adapters.py`、`schemas.py`、`routers/profiles.py`、`agent/loop_wiring.py` | 旧调用路径、接口枚举与输入预算 |
| `backend/worker/app/protocol.py`、`stress.py` | Worker 评测及派生压测 |
| `frontend/src/utils/profileVendors.ts`、`providerLogo.ts`、`components/modals/ProfileModal.vue`、`api/types.ts` | 供应商预设、协议选择与类型 |

协议依据：[OpenAI Responses 迁移指南](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)。

新增供应商依据：[New API 支持端点](https://docs.newapi.pro/en/docs/guide/feature-guide/user/api)。

New API 的模板目录使用下述 V1.5 网关专用规则；Ollama Chat 提供独立 `ollama-reasoning-effort-v1` 模板，使用 `reasoning_effort`（none/low/medium/high/max）和 max_tokens，不透传百炼等托管服务的 enable_thinking/thinking_budget。Ollama 允许任意部署地址，因此此模板按显式选择及真实探测放行，不以主机名假定模型归属。


## V1.3 协议工具与思考兼容审查（2026-09-17）

- 三种 Agent 协议均支持平台函数工具调用。Responses 使用扁平 `tools`、`function_call.call_id` 和 `function_call_output`；完整 reasoning/output 项随工具结果回传。多工具交错增量按 output_index 累积，断流、失败、截断和重复调用身份不允许实际执行工具。平台 MCP 工具仍由本地调度器执行；此处不等于开启 OpenAI 托管工具或远程 MCP 工具类型。
- New API 是协议网关，Chat/Responses/Messages 的工具与思考能力取决于所选通道、模型和网关版本。模板按网关协议推荐，逐档验证参数和思考证据；HTTP 成功本身不证明工具能力。现有保存前验证不执行工具，需另行进行真实 Agent 工具调用验收。
- Ollama Chat 使用 `reasoning_effort`，Responses 新增独立 `ollama-responses-effort-v1`，使用 `reasoning.effort`；均发送文档声明的 none/low/medium/high/max。GPT-OSS 的文档档位为 low/medium/high，不能推定支持关闭或独立 max；不支持档位由真实探测排除。Responses 仅使用无状态历史回放，要求 Ollama 0.13.3+；具体工具能力仍受模型限制。
- OpenAI 的平台最高档不再统一转 xhigh：o1/o3/o4、GPT-5、GPT-5.1 映射 high，GPT-5.1-Codex-Max 与后续型号/未知兼容端点验证 xhigh 候选。high/max 同参时由现有探测去重，只发布一个档位；未知型号不因名称推断为已支持。OpenAI Chat 与通用 Responses 模板版本提升为 3，旧版本探测失效，须重新验证。同步 Responses 网关使用相同最高档映射。
- New API 使用 MIT 品牌资源包的渐变 newapi-color.svg，Ollama 使用完整同名单色 SVG；不再使用字母占位或不完整轮廓，随 currentColor 适配明暗主题。

核对来源：[OpenAI 函数工具调用](https://developers.openai.com/api/docs/guides/function-calling)、[GPT-5.1 参数范围](https://developers.openai.com/api/docs/models/gpt-5.1)、[OpenAI 推理指南](https://developers.openai.com/api/docs/guides/reasoning)、[Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)、[Ollama 思考能力](https://docs.ollama.com/capabilities/thinking)、[New API 支持端点](https://docs.newapi.pro/en/docs/guide/feature-guide/user/api)。

### 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/shared/reasoning.py` | 共用 OpenAI 最高档别名映射 |
| `backend/api/app/llm/providers/{reasoning_templates,options}.py` | Ollama Responses 专属模板、OpenAI 映射及模板版本失效规则 |
| `backend/api/app/responses_adapter.py` | 同步入口与异步入口保持最高档映射一致 |
| `frontend/src/components/ProviderLogo.vue`、`assets/providers/{newapi,ollama}.svg`、`assets/providers/README.md` | 完整品牌图标与来源许可 |
| `backend/api/tests/test_responses_protocol.py` | 多工具回填、异常终态禁止执行、真实 SDK 思考参数和探测版本回归 |

审查验证：API 1673 passed / 78 skipped，Worker 51 passed，前端 98 passed；Ruff、前端 typecheck/build 与 git diff --check 通过。新增品牌 SVG 已用本地浏览器检查明暗主题和小尺寸显示。本次使用官方 SDK + 本地 MockTransport，未使用供应商真实密钥，未执行线上模型调用或部署。


## V1.4 工具验证闭环修复（2026-09-17）

补齐 V1.3 审查指出的保存前仅验证文本/思考问题：勾选 Agent 用途后，“测试并添加/更新”会在一个已通过的思考档位上，额外请求无副作用工具并回填随机结果；两次调用共用最多 30 秒，全部探测阶段共享 55 秒预算。未观察到工具调用、调用参数错误、结果未确认、断流或截断均标记工具未通过。保持思考与工具结果独立，工具失败允许保存评测用模型但明确警告，不宣称 Agent 工具已可用。该探测不执行业务工具，也不改变工具装配权限。

编辑页展示已保存工具状态；旧模板或凭据变更后的旧验证为未验证。API Key、Anthropic 版本变更不再复用旧能力结果。前端验证超时调整为 70 秒。工具模式的说明修正为首轮流式兼容策略，不能暗示切到 legacy 就禁止 tools 字段。

修改代码文件与作用清单：`backend/api/app/profile_tool_probe.py` 复用生产消息拼装与三协议适配器；`profile_probe.py` 选择已验证档位和总时限；`routers/profiles.py` / `schemas.py` 状态投影及失效；`frontend/src/api/{types,http}.ts` / `components/modals/ProfileModal.vue` 独立状态、警告和时限；`backend/api/tests/test_profile_tool_probe.py` 覆盖三种真实 SDK、错误分支和旧验证失效。

V1.4 验证：API 1700 passed / 78 skipped，前端 98 passed；Ruff、typecheck、生产构建和 diff --check 通过。测试覆盖真实 SDK 的三协议往返、异常流、超时清理及凭据/模板失效，网络采用本地替身。本次未调用线上模型、未部署。


## New API 网关思考适配修复（2026-09-17）

New API 使用独立、可持久化的协议模板，不再按模型品牌推荐原厂请求扩展：`newapi-chat-effort-v1` 发送 `reasoning_effort`，`newapi-responses-effort-v1` 发送 `reasoning.effort`，`newapi-messages-effort-v1` 发送 `thinking.type=adaptive` 与 `output_config.effort`。Messages 另提供 `newapi-messages-budget-v1`，用于不支持自适应转换的通道。关闭分别发送 `none` / `thinking.type=disabled`；普通模型可选择 `newapi-no-reasoning-v1`，不发送思考字段。

统一五档仍为 off/low/medium/high/max；Chat/Responses 的已知 GPT/o 系列最高档沿用 OpenAI high/xhigh 映射，其它模型及未知别名验证 max 候选。Chat 使用 max_tokens，Responses 使用 max_output_tokens，Messages 使用 max_tokens。网关负责向上游转换；网关版本、别名、通道与模型决定实际有效档位，只有收到思考证据且完成探测的档位才能出现在对话强度选择中。模板声明不代表已验证支持。

显式 New API 模板可用于任意部署地址，并用于恢复编辑时的供应商和管理页品牌分组；运行时模型供应商继续用于各模型的内容回放。旧档需重新编辑并验证 New API 模板后更新已保存能力，不自动沿用旧探测结果。New API Chat 保留工具轮次的 reasoning_content；Messages 兼容无签名的网关转换思考块，原生 Claude 签名要求保持不变。

图标采用与官方公开 logo.png 一致的青紫／粉色渐变版，使用现有 MIT 图标包 newapi-color.svg；图标来源：[官方公开标志](https://github.com/QuantumNous/new-api/blob/69a50029819a26c53e6babd276d49cfe2f8880ad/web/public/logo.png)。参数依据：[Chat 接口文档](https://docs.newapi.pro/en/docs/api/ai-model/chat/openai/createchatcompletion)、[网关统一思考意图与七档解析](https://github.com/QuantumNous/new-api/blob/69a50029819a26c53e6babd276d49cfe2f8880ad/relaykit/relayconvert/reasoning/intent.go)、[Claude 转换](https://github.com/QuantumNous/new-api/blob/69a50029819a26c53e6babd276d49cfe2f8880ad/relaykit/relayconvert/reasoning/claude.go)。文档仅列 low/medium/high，而当前源码接受更多值，因此最高档必须真实探测。

修改代码文件与作用清单：
- `backend/api/app/llm/providers/reasoning_templates.py`：New API 专用目录、三协议字段和普通模式。
- `backend/api/app/llm/providers/{openai,anthropic}.py`、`backend/api/app/agent/loop_wiring.py`：网关思考内容回放与上下文计量一致。
- `frontend/src/utils/{providerLogo,profileVendors}.ts`、`frontend/src/components/modals/ProfileModal.vue`：保存模板恢复供应商与品牌分组。
- `frontend/src/assets/providers/{newapi.svg,README.md}`：渐变品牌图标与来源说明。
- 后端 New API 回归与前端供应商测试：三协议、多模型别名、档位投影与重新编辑。

V1.5 验证：API 1816 passed / 78 skipped，Worker 51 passed，前端 99 passed；Ruff、typecheck、生产构建通过。New API 回归使用真实 SDK 与本地 HTTP 替身验证三协议、六种模型名称和五档参数，以及工具回填和已保存探测结果投影；未调用线上 New API。渐变图标已检查浅色、深色及 24px 显示。
