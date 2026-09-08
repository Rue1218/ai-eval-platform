# AI 测试与评估平台 — Agent 原生工具装配方案

> 版本:V0.4（定稿候选） | 状态:**P1/P2 已部署（main aec6621）**；**P3 开发完成（feat/agent-native-tools-p3 分支）**，待 PR 评审合入；端点冒烟与开闸观察待执行 | 日期:2026-09-08
> 范围：仅设计文档，不改代码。评审通过后按 §5 分期实施。
> V0.4（2026-09-08）：P3 落地登记——**编造对账护栏（R3-M6）**：reflect 新增
> L1.5 声明-证据规则（`_fabrication_claim`，窄词表仅覆盖确认卡/任务创建入队类
> 本回合即时声明；证据 = 本回合对应工具 ok 观察）——命中先 repair（共用修复
> 配额，纠正观察回灌）一次，复现即 reject + **fabrication 审计事件**
> （event.v5；词汇表 v5 登记：shared/event_vocab + events.py + API.md §4.3，
> 测试矩阵断言同步）；**待决点 1 收口（tool_call_mode 裁决）**：不翻转默认值
> ——上游 tools 装配与档级放行由三态许可独立承担（native_tools_policy 为唯一
> 消费点），`tool_call_mode` 语义收敛为协议档能力标记（native=可流式/可装配，
> legacy=无原生首轮流式），contracts.py 过时注释已修正；**待决点 3 收口
> （react 淘汰里程碑评审）**：react.v1 保留为兼容回退（P1 defer/fail-safe 依赖），
> 淘汰条件 = 目标档 tool_use 率 ≥80% 且 defer/回退率 <5% 观察 ≥7 天（判据随
> P3 灰度数据复核后另立迁移评审）；tests/test_native_tools_p3.py 7 用例（声明
> 检测纯函数 5 + 图级 repair→reject→审计/修正→pass 2）；门禁 api 933 passed /
> ruff 全绿。
> V0.3（2026-09-08，历史）：P2 落地登记（§5 P2 全部决策）——orchestrator 原生
> Act（tool_use 名守卫/OR-4 重复守卫/round 缓冲 assistant 段/多 tool_use 全量
> 入队 native=True）；Observe 回填组装 `_build_native_backfill`（store 正文
> 合成 + 缺失显式降级文案 + 单条 60K 二次裁剪带标注 + 占位观察跳过注入）；
> graph tools 自环 drain + orchestrator 注入 store（与 build_tool_node 同源
> 实例）；ask_user 答复明细并入 model_text（修复原生答复丢失，R2 高 4）；
> GraphState 新增 `native_tool_round`（覆盖式缓冲，无正文入持久层——契约保持）；
> P1 fail-safe 回退保留（装配开但 store 未接线时 defer）；tests/
> test_native_tools_p2.py 8 用例（纯函数组装 + 图级原生全链真实 read/多工具
> 自环/越权 fail-closed/失败正文回填）；门禁 api 926 passed / ruff 全绿。
> V0.2.1（2026-09-08，历史）：P1 落地登记（§5 P1 全部验收项）——config 新增
> `agent_native_tools_enabled`（默认 false）/`agent_native_tools_profile_ids`
> （另立字段，待决点 5 收口）；新增 `harness/execution/native_tools_policy.py`
> （三态许可 + 档级熔断，装配唯一消费点）；`select_tool_defs` 新增 `only`
> 交集收窄（含空元组语义）；taor orchestrator 装配/双通道裁剪/tool_use 无
> tools 重发回退（`native_tools_defer` 审计日志）/breaker 上报；`turn_usage`
> 回合 usage 累计（plan/orchestrator/reflect L3 全接入 → assistant_message
> turn_stats，R3-M1）；`tests/test_native_tools_p1.py` 13 用例覆盖验收①–⑥；
> 门禁 api 918 passed / ruff 全绿。部署后冒烟清单见 PR 描述。
> V0.2（2026-09-08）：按团队评审修订——①**D1/D4 装配白名单交集失实修正**（select_tool_defs
> 现语义 = 全量 native ∪ tools_needed∩registered，无 allowed 交集——交集收窄为本方案新增
> 行为，D1 收敛为 orchestrator 执行轮装配 + 装配层前置断言）；②**D5 灰度三态许可**
> （tool_call_mode 生产默认已为 native（迁移 a9c41b7e2d10），"转正即许可"不自洽 → 主闸门 ×
> per-profile 显式清单，装配层成为唯一消费点）；③**§3 断点表述按 R2 事实修正**（三协议
> 适配器对 tools 定义/role=tool 输入/tool_use 返回**均已实现**；真断点 = 无生产路径产出带
> 正文的回填——native_messages content=''、NativeToolResultStore.get() 零消费方）；④**D3
> 改互斥分支**（tool_calls 非空禁 react 解析，防同工具双执行/双卡）+ 回合内缓冲/持久化
> 契约/失败正文回填/store 缺失降级五项决策；⑤**P1 DoD 扩为**：测试档隔离 + 回退精确语义 +
> deepseek 端点专项冒烟与档级熔断 + per-call usage 审计 + 混合互斥断言；⑥证据修正（agent
> 文本路径请求不含 L1 五段（system.py L62-85），禁编句效力为零；模型调用点补全 plan/
> reflect/router）；⑦风险表并入端点熔断/成本计量/持久化回滚矩阵；⑧待决点收口（1 默认
> legacy 翻转最小决议、2 read+ask_user+web_fetch 先行、3 后置、4 入 P1 只读 PoC）。

## 1. 背景与实测证据（2026-09-08 生产验证）

对生产 `/agent`（engine=agent，MaaS DeepSeek V4 Flash / Anthropic 协议）做
工具调用测试发现：模型**从不产生真实工具调用**，且可"文本编造已发起确认卡"
（服务端 `pending_confirm=null` 证伪）。代码勘察确认这是**架构性事实**：

1. **模型请求不携带协议 `tools`**：hybrid agent 全部模型调用（plan L362 /
   orchestrator L499 / reflect L724 均经 `_model_input` L208 构造、router L1
   `router_node.py:262-266`、chat `routing.py:104-110 tools=()`）均不传
   `tools` → 适配器不写请求体 `"tools"` 键 → 模型不存在原生 `tool_use`
   能力。行号勘误：react 模板在 `taor_nodes.py:101-112`、schemas 文本
   `L171-185`、parse 循环 `L496-543`（L545-608 为解析后字段消费区）；
2. **工具经文本 react.v1 表达**：orchestrator 把工具 schema 压缩为 JSON 文本
   注入系统提示词（`_REACT_SYSTEM_TEMPLATE` + `_tool_schemas_text`），要求
   模型输出 react.v1 JSON；deepseek 在无 tools 请求下倾向自由文本 → JSON
   纪律弱，工具选择不可靠；
3. **确认卡唯一真实来源**是 `ask_user_question` 在 ToolNode 内 interrupt 或
   Workflow W5 确定性产出——模型口头"发卡"不产生任何卡。**R2 事实修正**：
   engine=agent 的 plan/orchestrator/reflect 请求 system 只含各自协议模板
   （`_PLAN_SYSTEM`/`_REACT_SYSTEM_TEMPLATE`/`_REFLECT_SYSTEM`），**不含
   system.py L62-85 的 L1 五段**——`L68` 禁编造句仅存在于 chat/workflow 的
   persona，文本 react 路径上效力为零（V0.1 表述"效力有限"系低估）；
4. 模型能提到「基准评测/用例生成/知识库评测/压测」来自技能目录文本
   （`skills/registry.py` SKILL_CATALOG）与系统提示词，**不是可调用工具**；
   `platform.tasks.task.*` 架构级不进入任何 Worker 视野（仅 Workflow W6
   `enqueue_long_task` 直调 worker_bridge——agents.py docstring 称"经工具
   十层链"与实际 W6 直调不符，引用时注意）——任务创建仍走确认卡/Workflow，
   本次不改。

## 2. 目标与非目标

**目标**：hybrid agent（engine=agent）向模型下发**真实协议工具定义**
（Anthropic/openai/responses `tools`），模型输出原生 `tool_use`，经现有
十层工具链执行并**原生回填工具结果**，循环直至完成——替代不可靠的文本
react JSON 纪律；对 `worker.general` 可见工具面（read/web_search/web_fetch/
task/ask_user_question 等 native 短工具）生效。

**非目标**（明确排除，独立排期）：
- `platform.tasks.*`（benchmark/rag/stress 创建）进入 agent 视野——任务创建
  维持「确认卡/Workflow」流程；
- `worker.sandbox`（read/bash 文件命令域）放行——仍受 H5 批次 2 安全评审
  与 S3 观察期约束（G6 范畴）；
- 文本 react.v1 路径删除——本方案与其**双轨兼容**（回退），后续另立迁移。

## 3. 现状积木与断点

| 层 | 现状 | 缺口 |
| :--- | :--- | :--- |
| 工具定义选择 | `context/assembly.py select_tool_defs(mode="react")` **零调用方（死代码）**。R2 事实：现语义 = 非 planned_only 时全量 native ∪ (tools_needed∩registered)，**无 allowed_tools 交集**（planned_only=True 分支仅 tests 引用，设计预留）；tool_defs 序列化投影经 registry.all_defs/get_def | 需**新增**交集收窄 + orchestrator 接线 |
| 装配 | `assemble(...)` 返回 `{'system','messages','tools'}`；routing.py 消费 system+messages（tools 键无人取） | tools 未被携带进 ModelRequest |
| 传输 | `llm/contracts.py ModelRequest.tools`（默认空元组）；gateway 原样透传 | 上游不填 |
| 协议转换 | `adapters._adapt_tools`（三协议定义转换 L247-290）、tool_use 返回解析（`_full_tool_calls` L592-631 + 流式三分支）、role=tool/tool_result 输入（`_adapt_messages` L152-180：responses→function_call_output / anthropic→tool_result 并入 user / chat→role=tool）**代码已全部实现** | 无生产调用方喂 tools → body 无 `"tools"` 键。tool_call_mode 字段**完全无装配消费**（唯一读者 stream_policy.native_stream_allowed 亦零生产调用；contracts.py L39 注释与实现不符，系"已接线"错觉源） |
| 执行 | toolnode 十层链 + interrupt（ask_user→clarify 卡，toolnode.py:357-389；独占波次）+ 工具名守卫（orchestrator L559 allowed_tools） | 就绪，无需改（batch 执行器为休眠设施，原生单工具也走 toolnode） |
| 回填 | 文本路径观察经 `_observation_lines` 以 user 消息注入（L212-225）。R2 事实：toolnode 已产出 `native_messages` role=tool **空壳**（content=''，toolnode.py:561-573 / batch.py:104-116）；正文在 NativeToolResultStore（上限 600K 字符）但 `get()` **零消费方**；`native_messages` 图状态通道（state.py:130）零读取；native=True 时 observation 被占位（toolnode.py:455-465） | **组装消费端未接线**：store 正文合成 → 下一轮请求装配 → 长链多轮配对全链路缺失（含 ask_user 答复正文在原生循环丢失风险） |
| 事件 | tool_call/tool_result 持久事件（V1.67 恢复）在 toolnode 发 | 原生路径事件同源，复用 |

## 4. 方案设计

### D1 装配接线（orchestrator 执行轮携带 tools，R1/R2/R3 修订）
- **注入范围收敛（R1-B2）**：plan/reflect 节点**不装配 tools**（共用
  `_model_input` 时以 per-node 开关隔离）——下发仅发生在 orchestrator
  执行轮；避免 plan 轮 tool_use → plan.v1 解析必 turn_failed 的新失败面。
- **装配集合（R2/R3-B1 事实修正）**：装配层新增显式交集
  `下发集 = allowed_tools ∩ registered ∩ transport="native"`，并在
  discover 节点落 State 处与装配前各加一次断言（`下发集 ⊆ allowed_tools`）；
  select_tool_defs 现有"全量 native"语义**不得直接使用**（会把视野外
  write/edit/bash/Task* 定义铺给模型）。
- **文本 react 模板裁剪（R1-B2）**：原生开启时 system 移除 `_tool_schemas_text`
  正文，仅保留 react.v1 格式说明作为回退提示（避免同 schema 双通道下发与
  上下文膨胀）；关闭时逐字节保持现状。
- **L1 策略并入（R2 高 3）**：agent 文本路径请求本不含 system.py L62-85
  L1 五段；原生循环开启时把【安全边界/确认卡约束/密钥保护/禁编句】段并入
  orchestrator system（修正"禁编约束缺失"并服务 D3 互斥不变量）。
- 主闸门 `agent_native_tools_enabled`（config，默认 false）见 D5。

### D2 协议适配（tools 下发）
- 复用 `_adapt_tools`/`_full_tool_calls`/`_adapt_messages`（R2 核验：三协议
  定义转换、tool_use 返回、role=tool/tool_result 输入代码均已实现，无需
  新增协议层代码）。冒烟义务转为**行为验证**：Anthropic/openai/responses
  请求含 tools 键 + 返回 tool_use 解析 + 回填后下一轮不 4xx（P1 DoD）。

### D3 原生循环与双轨兼容（orchestrator 节点策略，R1/R2/R3 修订）
```
请求（携带 tools）
 → 响应 tool_calls/tool_use 非空? ──是──→【互斥分支】只走原生：
       │     逐 tool_use → toolnode 十层链执行（interrupt 沿用现卡语义）；
       │     响应中任何文本仅作 stray 并入回填，禁止 react JSON 解析
       │否（纯文本）→ 尝试 react.v1 JSON ──成功──→ 文本执行路径（现状）
              └失败 → 既有 3 次容错 → turn_failed（现状不变）
```
- **单轮 Act 唯一性不变量（R3-M4）**：tool_calls 非空即不进入 react 解析
  （防止同名工具被排两次队列 → 双执行/ask_user 双卡）。
- **回合内消息缓冲生命周期（R1-M2）**：本轮 assistant(tool_use) 消息入回合
  缓冲（GraphState 或 extra 链，仅回合内存在）→ toolnode flush
  `native_messages` 后，orchestrator 下轮从缓冲 + NativeToolResultStore
  合成配对消息注入请求（store.get 接通为消费方）。回填范围 = 最近 N 对
  （见预算），正文经 `_adapt_messages` role=tool 形态（anthropic 的
  tool_result 必须紧邻对应 assistant.tool_use，次序由缓冲保证）。
- **持久化契约（R3-M2）**：原生中间往返**不落 Message 表/检查点持久层**
  （与现状一致，只落最终文本）——tool 对仅回合内临时存在，正文只经 store；
  保证关闸后 legacy 装配零残留（回滚矩阵见 §7）。附验收断言：REST 回放/
  窗口装配不含 role=tool 泄漏。
- **失败正文回填（R3-M5）**：失败 tool_result（含 repair_hint/错误原文）
  与成功正文同等回填——当前 role=tool content='' 会造成 H4 repair 阶梯
  退化为盲重试。P2 规格化"失败/成功正文均从 store 合成回填"。
- **store 缺失降级（R1-M5）**：`agent_hitl_strict_pg` 语义下 resume 可跨
  进程，store 正文可能不可得 → 回填降级策略：错误收尾 vs 文本提示重读
  （P2 定），并断言 resume 后请求仍含此前原生工具正文（同实例路径）。
- **回填预算（R1-M4/R3-M1）**：tool 消息只带最近 N 对（对齐 `tool_turns`/
  context 预算）；正文二次裁剪带截断标注（与文本路径 `_MAX_OBSERVATION_CHARS`
  口径对齐），防单条 600K 正文叠加超 context_window。
- interrupt 语义沿用 toolnode（独占波次既有）；卡事件协议零变化；
  ask_user 答复正文经原生回填通道（见上，修复现 content='' 丢答复）。

### D4 守卫（R2/R3-B1 修订）
- 工具选择 = `allowed_tools ∩ registered ∩ native`（**本方案新增行为**，
  非既有约束——select_tool_defs 现语义全量 native ∪ tools_needed 须先行
  修正）；装配层断言"下发集 ⊆ allowed_tools 且不含 mcp def"（逐 worker
  参数化单测，worker.general 不得含 bash/write/edit/TaskCreate）；
- 工具可用性装配规则（R3-1c）：服务未配置即不下发——firecrawl key 为空 →
  web_search 不出现在下发集；
- 回合预算（model_calls/tool_turns）、门禁十层链、日志脱敏全部沿用；
- 新增断言：tool_use 名 ∉ allowed → VALIDATION（沿用 L559 文本守卫语义
  扩展至 tool_use 名；注意该守卫为既有 allowed 唯一执行前屏障，装配交集
  修复后"诱导尝试"面大幅收敛，剩余尝试消费预算属可接受噪声，计入指标）。

### D5 灰度（三态许可，R1-B1/R3-B2 修订）
- 新 config `agent_native_tools_enabled: bool = False`（主闸门，默认关）；
- **协议档级许可不用 tool_call_mode 现字段承担**（生产默认已 native——
  迁移 a9c41b7e2d10，"转正即逐档许可"会致主闸门一开即全量下发）；改用
  per-profile 显式清单 `agent_native_tools_profile_ids`（仿既有
  `agent_native_stream_profile_ids` 模式，config.py:86）。灰度顺序：内部
  验证 profile → 观察指标 ≥7 天 → 逐 profile 加入清单；
- 装配层成为 `tool_call_mode` 或新许可字段的**唯一消费点**（现状零消费，
  防多处理解漂移）；tool_call_mode 默认值是否翻转 legacy 随 P3 契约评审
  一并裁决（待决点 1 收口）；
- 灰度指标（P1 即埋点）：tool_use 率、parse 失败率、卡产出正确率、工具
  失败/重试率、**轮均模型调用数 + 输入 token 中位数（native vs legacy 对照，
  修复 agent 内部调用 usage 现恒空 { } 的计量缺口——R3-M1）**。

### D6 边界不变声明
- discover/worker 视野、sandbox 排除、platform.tasks 授权路径、WS 事件
  词汇表、REST 契约**全部不变**；本文档只动「agent 图 orchestrator 装配层 +
  tool_use 执行与回合内回填」，发布面 = api 单服务。G6 开放 worker.sandbox
  时（drill 开关）bash 自动进入装配面——设计兼容，开放前按 S5 复查 bash
  描述对抗性参数（dangerouslyDisableSandbox 等经原生 tools 的绕过尝试，
  执行侧 enforce 已就位）。

## 5. 分期

| 阶段 | 内容 | 依赖 | 验收 |
| :--- | :--- | :--- | :--- |
| P1 | 装配接线（D1，仅 orchestrator）+ 交集收窄与断言 + 主闸门 + 下发冒烟（D2 行为验证）+ per-call usage 审计埋点（R3-M1）；**不循环**——tool_use 出现走精确回退（见下） | 无 | ① 测试档隔离下发：请求含 tools 且集合 ⊆ allowed∩registered∩native；② **deepseek Anthropic 兼容端点专项冒烟**（含 tools 键、tool_use 解析、回填后不 4xx）——任一档异常自动摘除该档装配（档级熔断）；③ 回退语义可验收：tool_use 出现 → **以无 tools 请求重发一次**并记 agent_trace/审计（不落入 3 次纠正噪音）；④ 混合互斥断言（tool_calls 非空 → 无 react 双解析）；⑤ 关闸回归：请求字节级无 tools 键；⑥ store 回填组装只读 PoC（M1 附加项：store 正文合成 + 下一轮装配可行性验证，吸收 P2 最大风险） |
| P2 | 原生循环 + 回合缓冲/配对回填（D3 全部决策）+ tool_use 名守卫 + store 缺失降级 + 失败正文回填 | P1 | read/web_search/ask_user 端到端原生调用成功（测试 profile 灰度）；持久化契约断言（中间往返不落库、回放无泄漏）；resume 后请求含此前工具正文（同实例）；ask_user 答复正文回填可见 |
| P3 | 契约与灰度：per-profile 清单逐档放行、tool_call_mode 默认值翻转裁决、指标观察 ≥7 天、编造对账护栏（声明-证据规则 + fabrication 审计事件，R3-M6）、react 淘汰里程碑评审 | P2 | 灰度判据（量化口径 P1 埋点建基期：tool_use 率/失败率阈值）；文档/API.md 留档 |

回滚：`agent_native_tools_enabled=false` 一键回文本路径（tools 不注入、
行为与 V0 前一致）；**回滚完整性验收**（R1-M6）：关闸后新建请求工具定义
为零、历史中无 tool 消息残留（依赖 D3 持久化契约成文）；P2 异常回 P1 形态
（P1 副作用 = 工具定义仍下发 + tool_use 被回退为无 tools 重发——成本 +1
调用/轮，接受并记录）。

## 6. 测试矩阵

单测（fake gateway + InMemory 图，仓库既有 hybrid 测试模式）：
- 装配面参数化断言（R3-T1）：逐 worker 下发集 ⊆ allowed_tools（worker.general
  无 bash/write/edit/TaskCreate/mcp def；drill 开时 worker.sandbox 含 bash
  对照）；
- select_tool_defs 交集修正回归（tools_needed 全量铺开路径已关闭）；
- orchestrator 请求 tools 字段断言（开关关=空且 body 无 tools 键/开=交集）；
- tool_use 响应 → 执行 → 回填 → 下一轮输入含 tool 消息（含失败正文）；
- 纯文本响应 → react 兼容回退（现状用例不破）；混合输出 → 每工具恰好一次
  tool_call/tool_result（R3-T3）；空名/缺参 tool_use 静默过滤不崩溃；
- 非法工具名（VALIDATION/turn_failed）、tool_turns 预算上限；同参重复守卫
  原生扩展（R3-T4）；
- ask_user interrupt 卡原生路径回归 + resume 语义（含正文回填断言 R3-T5）；
- 提示注入对抗（R3-T2）：用户文本诱导越权工具选择仍限 allowed；伪造
  tool_use 越权名（bash/write/edit/task.create）→ VALIDATION 事件面一致；
- 窗口裁剪后 assistant(tool_use)/tool 配对分离的上游 400 防护；超长正文
  截断标注回填请求预算；关闸"字节级无 tools 字段"回归基线（R1-M8 三项）；
- 回滚矩阵（R3-T8）：native 回合后关开关 → legacy 装配成功、窗口/回放无
  role=tool 泄漏、usage/turn_stats 含原生循环每次调用；
- 编造对账（P3，若采纳 R3-M6）：声明"已发卡/已创建"无工具证据 → 纠正一次
  后 reject + fabrication 审计事件（词汇表扩展按事件注册表流程）。

集成：三协议适配器 tools 定义/解析/回填行为冒烟；WS tool_call/tool_result
事件在原生路径不重复/不丢失断言；web_search 无 Key（装配剔除 + 失败率指标）
与 web_fetch SSRF 回归 native/文本双跑（R3-T7）。

生产验证（P3 前人工）：复用 2026-09-08 工具测试剧本（read/web_search/
澄清卡；每档含确认卡发起与取消闭环）。

## 7. 风险

| 风险 | 缓解 |
| :--- | :--- |
| 协议 tools 定义/回填行为不兼容（含 deepseek Anthropic 兼容端点 tools 支持度为最大外部不确定项） | P1 专项冒烟（含该端点）+ **档级自动熔断**（单档连续 N 次异常摘除装配，复用 circuit 模式）；有差异仅灰度该档 |
| 模型借原生工具滥用（多轮循环/乱参/诱导越权尝试） | 下发集 = allowed∩registered∩native（装配断言）+ 预算上限 + 门禁十层链 + 开关回滚；越权尝试消耗预算计入失败指标 |
| tool 回填改变上下文计量/成本 | 窗口只收 user/assistant（R2 已证 role=tool 永不进窗）；回填预算（最近 N 对 + 二次截断标注）；**P1 起 per-call usage 审计**（现 agent 内部调用 usage 恒空，成本不可观测——R3-M1） |
| 与文本 react 双轨行为分叉/双执行 | 互斥分支（tool_calls 非空禁 react 解析）+ 单轮 Act 唯一性不变量 + 事件面"每工具恰好一次"断言 |
| 关闸/回滚残留 | 持久化契约（中间往返不落库）+ 回滚完整性验收（无 tools 字段/tool 消息零残留） |
| 编造确认卡/执行类文本行为依旧 | 本方案不承诺消除（R3-M6）；P3 提供服务端声明-证据对账护栏 + fabrication 审计事件作为收口项 |
| 原生失败正文回填缺位致盲重试 | 失败/成功正文统一从 store 合成回填（P2 规格 + 单测） |
| resume 跨进程后 store 正文缺失 | P2 定降级策略（错误收尾 vs 文本提示重读）并断言 |

## 8. 评审待决点（V0.2 收口）

1. ~~灰度放行主体~~ **最小决议（R1-B1/R3-B2）**：主闸门 × per-profile 显式
   清单（`agent_native_tools_profile_ids`）；`tool_call_mode` 现默认 native
   不担任装配许可（防一开全量），默认值翻转 legacy 与否留 P3 契约评审。
2. ~~先行工具面~~ **决议：read + ask_user_question 先行**（web_search 无
   Key 装配剔除规则一并落地；web_fetch 直抓可用性核验后同批）；P1 冒烟含
   该子集。
3. 双轨保留期/react 淘汰里程碑：随 P3 另评审（V0.2 仅要求互斥分支 + 回退
   精确语义，不阻塞 P1/P2）。
4. ~~原生回填兼容 PoC~~ **已收口（R2 事实 + R1-M1）**：协议形态支持已存在；
   真断点为组装消费端——store 回填组装只读 PoC 入 P1 附加项（吸收 P2 风险）。
5. （新增）per-profile 许可清单是否复用 `agent_native_stream_profile_ids`
   字段或另立：倾向另立 `agent_native_tools_profile_ids`（stream 与 tools
   是独立放行面），P1 定。
