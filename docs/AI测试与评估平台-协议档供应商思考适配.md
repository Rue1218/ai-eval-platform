# 协议档供应商与思考强度适配

版本：V1.0 ｜ 审查日期：2026-09-09

## 产品与接口增量

供应商新建入口限定 GLM、DeepSeek、阿里百炼、Kimi、MiniMax、NVIDIA、火山引擎、Gemini、OpenAI、Anthropic；已有其它协议档保留可管理。供应商表示托管服务，模型品牌用于 Agent 图标，两者独立识别。

统一选择项为 `off / low / medium / high / max`。未选择对话档位时 `reasoning_effort` 默认 `off`；原生 Claude 默认 `high`。不能关闭思考的型号仅提供真实可用选项，并明确说明；只支持开关的型号四个开启档等价，不能宣称有四种原生强度。保留旧回合 `xhigh` 读取兼容，新界面不提供该选项。

协议档页面、列表、编辑弹窗均不提供思考强度设置，不持久化可编辑的协议档默认强度。仅对话输入框保留档位选择。默认值从供应商与模型能力推导；`turn.submit` 显式选择覆盖默认值，旧全局 `agent_reasoning` 仅供 legacy 链路读取。

Profile 响应增加只读 `provider, reasoning_effort, allowed_efforts, reasoning_note`，与 Agent UI 的能力判断共用实际 resolver。Agent UI 脱敏协议档增加 `provider, reasoning_note`，仍不包含端点或密钥。管理页按服务供应商分组，Agent 按模型品牌显示图标。

## 官方依据与映射原则

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

## 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/llm/providers/{catalog,options,openai,anthropic,common}.py`、`llm/{resolver,contracts,loop_contracts}.py` | 按供应商解析能力、映射请求参数，保留 MiniMax 思考往返状态，支持完整 URL |
| `backend/api/app/{profile_reasoning,profile_env,schemas}.py`、`routers/{profiles,sessions,ws}.py`、`agent/{loop_wiring,loop_presentation}.py` | 供应商默认值、只读能力投影、完整 URL 保存和调用接线 |
| `backend/shared/model_urls.py`、API `adapters.py/llm_client.py/llm/gateway.py/harness/memory/state.py`、Worker `profile_env.py/protocol.py/benchmark.py/eval_graph.py/testcase.py/stress.py` | 主模型端点规则贯通同步、异步、后台任务与恢复配置 |
| `frontend/src/views/AdminProfiles.vue`、`components/modals/ProfileModal.vue` | 两列供应商卡片、统一搜索筛选、表格滚动、完整 URL 开关、数值输入和异步反馈；删除管理页思考设置 |
| `frontend/src/assets/providers/`、`components/ProviderLogo.vue`、`utils/{providerLogo,profileVendors}.ts`、`components/agent/loop/{AgentComposer,AgentWorkspace,ThinkingControl}.vue` | 十个品牌矢量图标、托管服务与模型品牌区分、对话档位能力提示 |
| API/Worker 协议档与 URL 回归测试、前端品牌识别测试 | 验证 SDK 最终请求、完整 URL 原样保留、能力与品牌识别 |

验证：本地 API 全量回归 1259 passed / 74 skipped；Worker 50 passed；新增供应商及完整 URL 定向回归 96 passed；前端 19 passed；前端类型检查与构建通过。新增完整 URL 用例使用真实官方 SDK + MockTransport，不请求生产模型；页面浏览器验证使用示例数据。品牌资源来源与许可见 `frontend/src/assets/providers/README.md`。上线及真实供应商密钥验收与本地验证分开进行。
