# 协议档供应商与思考强度适配

版本：V1.1 ｜ 审查日期：2026-09-15

## 产品与接口增量

供应商新建入口限定 GLM、DeepSeek、阿里百炼、Kimi、MiniMax、NVIDIA、火山引擎、Gemini、OpenAI、Anthropic；已有其它协议档保留可管理。供应商表示托管服务，模型品牌用于 Agent 图标，两者独立识别。

统一选择项为 `off / low / medium / high / max`。未选择对话档位时 `reasoning_effort` 默认 `off`；原生 Claude 默认 `high`。不能关闭思考的型号仅提供真实可用选项，并明确说明；只支持开关的型号四个开启档等价，不能宣称有四种原生强度。保留旧回合 `xhigh` 读取兼容，新界面不提供该选项。

协议档页面、列表、编辑弹窗均不提供思考强度设置，不持久化可编辑的协议档默认强度。仅对话输入框保留档位选择。默认值从供应商与模型能力推导；`turn.submit` 显式选择覆盖默认值，旧全局 `agent_reasoning` 仅供 legacy 链路读取。

Profile 响应增加只读 `provider, reasoning_effort, allowed_efforts, reasoning_note`，与 Agent UI 的能力判断共用实际 resolver。Agent UI 脱敏协议档增加 `provider, reasoning_note`，仍不包含端点或密钥。管理页按服务供应商分组，Agent 按模型品牌显示图标。

## 官方依据与映射原则

### 供应商协议与 Base URL 矩阵

快速填充以供应商和协议为联合键。切换协议时同时替换 Base URL 与建议模型；未登记表示官方没有公布该兼容层，界面禁用该组合，但不影响用户手工维护已有自建网关。

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
| `frontend/src/assets/providers/`、`components/ProviderLogo.vue`、`utils/{providerLogo,profileVendors}.ts`、`components/agent/loop/{AgentComposer,AgentWorkspace,ThinkingControl}.vue` | 十个品牌矢量图标、托管服务与模型品牌区分、对话档位能力提示 |
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
