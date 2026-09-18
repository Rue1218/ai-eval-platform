# 协议档供应商与思考强度适配

版本：V1.11 ｜ 审查日期：2026-09-18

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


### 添加失败的诊断修复（2026-09-17）

保存前探测的 `attempts[].error_code` 增补安全分类：`AUTH_FAILED`（密钥或权限）、`MODEL_OR_ENDPOINT_UNAVAILABLE`（模型或接口）、`RATE_LIMITED`（限流）、`UPSTREAM_UNAVAILABLE`（上游服务）、`CONNECTION_FAILED`（连接）、`PARAMETERS_REJECTED`（协议或参数）、`INVALID_RESPONSE`（流格式）、`INCOMPLETE_RESPONSE`（未正常结束）。额度不足继续使用 `BUDGET_EXCEEDED`。这些是探测明细分类，不改变 REST 十大错误码；不回显上游错误正文、密钥或提示词。任何验证全部失败的档仍不保存。

修改代码文件与作用清单：`backend/api/app/profile_probe.py` 保留 SDK 已脱敏的具体故障类别；`backend/api/app/routers/profiles.py` 显示可操作的修正提示；`backend/api/tests/test_newapi_reasoning.py` 通过真实 SDK 注入错误状态，核对分类及秘密不外泄。

补充验证：诊断分类加入后 API 全量 1837 passed / 78 skipped，Ruff 与 diff --check 通过。无密钥连通性检查确认用户网关 v1.0.0-rc.37 的 Chat/Responses 路由返回标准 401；未获得已认证模型调用结果，不据此宣称模型可用。


## 连通检查与 New API Responses 一致性修复（2026-09-17）

列表连接测试沿用实际对话的 build_adapter / resolve_request，不再走旧非流式 call_protocol，不再把输出上限强设为 1，也不丢失保存的思考模板。使用 profile_reasoning 投影的已验证默认档位与实际输出上限；模板未验证或失效时返回 VALIDATION 并要求重新测试。探活等待首个有效正文、思考片段或合法终态，整段上限仍为 30 秒并关闭流及连接池。探活成功只说明本次模型接口可响应，不写回思考档位或工具能力。失败前端显示服务端安全 message，状态文案改为“测试未通过”，避免把参数拒绝、等待超时统称网络断开。

GPT-5.6（含 sol/terra/luna 及快照）的统一最高档发送原生 max；已知旧型号继续 high/xhigh。New API Chat/Responses 模板版本升至 3，OpenAI Chat/通用 Responses 模板升至 4，旧探测结果须重新验证后开放档位，避免使用旧 xhigh 回执宣称 max 已验证。依据：https://developers.openai.com/api/docs/models/gpt-5.6-terra 。

Responses 识别 response.reasoning_text.delta 与已有摘要增量，保留供应商返回的协议状态，不生成或推断隐藏推理。工具调用、加密推理回放与正常结束规则不变。依据：https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_reasoning_text_delta_event.py 。

修改代码文件与作用清单：
- backend/api/app/profile_check.py、routers/profiles.py：复用运行时适配器的单次流式探活与清理。
- backend/shared/reasoning.py、backend/shared/responses.py、backend/api/app/llm/providers/{options,reasoning_templates}.py：原生 max 映射、版本失效与增量识别。
- frontend/src/api/{types,http}.ts、views/AdminProfiles.vue、components/modals/CheckResultModal.vue：保留并展示安全诊断。
- API 探活/Responses 回归测试：真实 SDK 请求、连接清理、档位映射与安全诊断；前端类型检查验证诊断字段贯通。

V1.6 本地验证：API 1878 passed / 78 skipped，Worker 51 passed，前端 99 passed；Ruff、typecheck、生产构建与 diff --check 通过。新增真实 SDK + HTTP 替身回归覆盖流式限定网关、完整 URL、已验证默认 max、模板版本失效、首字退出/超时清理、两种 Responses 思考增量及脱敏错误。本次未使用生产密钥调用用户通道。

## 协议档审查修复（2026-09-17）

- 凭据复用限定同源（协议、主机、有效端口）。主模型、Embedding、Reranker 跨源编辑均需显式提供新 Key；保存前探测与模型列表获取使用相同规则。模型列表只从已绑定端点选择环境凭据，不再按域名子串或协议向陌生主机兜底。只有 Key、没有配套地址的旧第三方环境配置需补充 BASE_URL 或显式输入凭据；原生 OpenAI/Anthropic 专属 Key 可匹配其官方默认地址。
- 首批五档探测仍并发，RATE_LIMITED 档位在首批结束后串行重试一次，最多十次实际思考请求（单并发触发场景为九次）。重试和工具探测共用 55 秒总预算；不重试认证、参数或模型错误，不因限流推断模型不支持思考。回执仍按唯一档位保存，无新增 REST 字段。
- Responses 完成快照按 output_index/content_index 校验正文与拒绝文本。可追加的缺失后缀补齐一次；正文冲突、回退、缺失或不能追加的错序返回响应协议错误，不能宣布成功。用户正文与持久回放快照保持一致。
- 不透明协议状态以服务器 HMAC 绑定端点、模型协议、档案版本及凭据身份，不持久化原始地址/凭据或普通密钥哈希。切换连接时使用既有消息迁移流程清理旧状态；旧版兼容键会在首次续聊时清理，正文及工具调用历史保留。修改思考档位不改变连接身份。

Responses 事件字段依据：[OpenAI 官方流式响应示例](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create)。

修改代码文件与作用清单：
- `backend/shared/model_urls.py`、`backend/api/app/{profile_env.py,routers/profiles.py}`：同源判断、环境凭据绑定及编辑/探测/模型列表防护。
- `backend/api/app/{security.py,llm/resolver.py}`：受保护的协议状态连接作用域。
- `backend/api/app/profile_probe.py`：限流串行重试及剩余总时限。
- `backend/shared/responses.py`、`backend/api/app/llm/providers/responses.py`：正文终态核对、补齐与安全错误分类。
- `frontend/src/components/modals/ProfileModal.vue`：跨源变更重新填写密钥的提示。
- `backend/api/tests/test_{profile_credential_scope,replay_connection_scope,reasoning_templates,responses_protocol,newapi_reasoning,fetch_models}.py`：凭据边界、连接迁移、限流预算与正文一致性回归。

本轮验证：API 全量 1918 passed / 78 skipped；随后补充端口 0 边界并重跑凭据安全测试。Worker 51 passed，前端 99 passed；Ruff、typecheck、生产构建通过。所有新增供应商用例使用虚构凭据及本地替身，未使用生产密钥。


## V1.8 New API Responses 空终态兼容（2026-09-18）

New API 的部分 Codex 通道会在流中发出 `response.output_text.done`，但在 `response.completed` 省略 `response.output` 中的助手消息。平台为该缺陷提供文本兼容：只有成功终态为空、没有工具调用、只有一个正文或拒绝内容块，并且完成正文严格覆盖所有既有增量时，才恢复一个最小助手消息快照。

这个兼容不改变供应商思考模板，也不把完成正文当作思考证据。思考强度必须仍由请求完成和可验证的思考证据逐档探测。该网关没有返回完整工具终态时，原生工具验证保持 `failed`，只能用于文本对话与评测，不能标记为 Agent 工具可用。

修改代码文件与作用清单：`backend/shared/responses.py` 实现受限终态重建；`backend/api/tests/test_responses_protocol.py` 覆盖 SDK 事件、缺失完成正文和工具状态拒绝。

## V1.9 Responses 兼容审查修复（2026-09-18）

V1.8 的空终态兼容增加消息项、内容块及身份核对：已观察的额外输出不可忽略，三层完成事件发生冲突时拒绝成功终态；重复完成事件只允许完全一致。补齐缺少 ID 的回复不生成固定供应商身份，连续对话回放使用普通助手消息，并处理旧版保存的 `responses-fallback-0`。有真实身份的完整输出项继续保留。思考强度及原生工具的真实验证门禁不变。

修改代码文件与作用清单：`backend/shared/responses.py` 完成事件与终态核验；`backend/api/app/llm/providers/responses.py` 新旧缺失身份历史转换；`backend/api/tests/test_responses_protocol.py` 冲突、额外项及 SDK 三轮续聊回归。

本轮验证：新增 26 项回归；定向测试 267 passed，API 全量 1949 passed / 78 skipped，Worker 51 passed，Ruff、前端 typecheck/build 与 diff --check 通过。网关事件使用本地 HTTP 替身复现，未调用线上模型。

## V1.10 New API 完整工具输出项兼容（2026-09-18）

真实无副作用探测确认：该类 Codex 通道能够返回完整的 `function_call` 完成项，失败发生于随后空的 `response.completed.output`。现在允许从全量、连续、身份稳定的 `output_item.done` 恢复工具/推理输出；工具参数必须是合法对象并与参数完成事件一致，推理必须保留原始加密回放状态。缺项、断流、截断、冲突和不完整参数仍不能执行工具。

已通过同一网关、同一模型的关闭思考档真实工具往返验证；仍不授权其他未经验证的思考档。线上旧工具失败状态不会自动改为成功，须在部署后编辑协议档并重新测试更新。

修改代码文件与作用清单：`backend/shared/responses.py` 完整项恢复与参数事件核验；`backend/api/tests/test_responses_gateway_tools.py` SDK 实际序列化的双向回填与安全边界；`backend/api/tests/test_responses_protocol.py` 单/多工具只执行一次、后续回合及非法工具禁止调度。

本轮验证：新增 22 项回归，定向 289 passed，API 全量 1971 passed / 78 skipped，Worker 51 passed；Ruff、前端 typecheck/build 通过。真实网关关闭思考档工具往返返回 passed；只运行无副作用回显探测，未执行业务工具，未保存密钥、模型正文或工具参数。


## V1.11 Responses AgentLoop 展示闭环（2026-09-18）

Responses 公开摘要兼容 `reasoning_summary_text.done`、`reasoning_summary_part.done`、`output_item.done` 与完整终态补齐；保留多段边界，校验身份、重复完成与文本前缀。`encrypted_content` 仍仅供回放，不投影到页面。普通摘要仍可能短于其他供应商思考文本，不代表未启用思考。

正文 `phase=commentary/final_answer` 经独立展示字段贯穿流式和持久历史，模型回放继续保留原始协议项；流式只发定位和增量，终态才校正完整展示快照。思考区渲染安全 Markdown，文件产物链接来自成功 write 的结构化回执与会话绑定目录，非模型自造路径。

修改代码文件与作用清单：`backend/shared/responses{,_reasoning}.py`（摘要与分段）、`backend/api/app/llm/{loop_contracts,providers/responses}.py`（流展示元数据）、`backend/api/app/agent/{stream,loop,loop_service,events,loop_presentation,loop_wiring}.py`（事件/下载投影和文件交付提示）、`backend/api/app/harness/contracts/loop_events.py`（目录 V7）、前端 `responsePresentation.ts`、reducer、turnSummary、MarkdownView、ReasoningBlock、AgentWorkspace 及对应测试。

本轮验证：新增后端 15 项回归，API 全量 1986 passed / 78 skipped、Worker 51 passed、前端 116 项通过；新增浏览器用例通过，Ruff、前端 lint（0 错误）、typecheck/build 与 diff 检查通过。本轮采用本地协议/真实 SDK/Agent 图和浏览器夹具验证，未新增真实供应商请求。
