# AI 测试与评估平台 — Agent 子系统：界面卡片、Markdown 与斜杠技术方案

| 属性 | 内容 |
| :--- | :--- |
| **文档名称** | Agent 界面卡片、Markdown 与斜杠技术方案 |
| **文档版本** | V1.1 (全量详细设计与实现规范) |
| **基线参考** | 《AGENTS.md》最高规范、《Agent开发文档》§7 / §9 / §11 / §16、API.md V1.6、PRD 5.1 |
| **责任模块** | 前端 `frontend/src/views/Agent.vue` + `frontend/src/components/agent/*` + `frontend/src/agent/*` |
| **审查日期** | 2026-08-20 |
| **最近修订** | 补齐思考快照、工具/技能/确认卡历史回放与 ContextMeter 恢复 |

---

## 1. 方案背景与设计边界

本技术方案针对评测平台 Agent 子系统的 **「模块 7. 界面：卡片、Markdown、斜杠」** 进行深度前端架构设计、交互契约冻结与落地实施指导，涵盖任务编号 `AGT-UI-01`、`AGT-UI-02`、`AGT-UI-05`、`AGT-UI-08`、`AGT-SLH-01`、`AGT-CTX-02`。

### 1.1 核心设计目标
1. **全链路卡片化体系**：对话流内的所有信息单元（思考卡、短 MCP 工具卡、任务确认卡、进度坞、报告卡、用户气泡）全部采用独立组件化设计，支持毫秒/秒级耗时徽章与平滑折叠动画；
2. **安全富文本与图表渲染**：助手长文本与长 thought 支持标准化 Markdown 排版、严格 XSS 安全过滤、围栏代码块高亮与复制、Mermaid 结构图优雅降级、KaTeX 数学公式解析；
3. **沉浸式斜杠命令交互**：键入 `/` 呼出 360px 悬浮命令面板，明确划分「系统 15 条必带命令（只读不可删）」与「团队自定义命令」，支持方向键导航、回车自动填入与 IME 输入法防抖；
4. **四段实时上下文度量**：顶栏常驻展示 `ContextMeter`（消息 M · 技能 S · 摘要 C · 余量 R / 20），点击展开四段结构化详情浮层；
5. **纯粹生产环境（无假数据）**：清理 live 环境中的模拟失败、模拟断线按钮及写死假资产，严格反映真实 WebSocket 状态与服务端真实资产。

### 1.2 红线禁令（核心约束）
- ❌ **严禁用户端自由切换模型**：ChatHead 顶栏与 Composer 输入框右侧固定为只读展示 `Agent · {模型名}`，严禁提供模型切换下拉框或思考强度滑杆；
- ❌ **严禁伪造独立事件**：技能徽标与短工具标识直接从 `thought.payload.skill_id` 与 `tool_call` 推断，严禁在 WebSocket 中伪造 `skill` 或 `mcp` 独立事件名；
- ❌ **严禁在 live 环境制造假数据**：禁止硬编码假协议档、假数据集或模拟成功/失败演示；
- ❌ **严禁弹窗式确认卡**：任务确认卡必须嵌入在对话流内，禁止做成全局 Modal 弹窗；
- ❌ **严禁前端私自计算上下文消息数**：ContextMeter 必须严格取自 `GET /api/sessions/{id}/messages` 返回的 `context_meter` 字段。

---

## 2. 界面拓扑与交互时序

### 2.1 界面三段式布局拓扑
```text
+-----------------------------------------------------------------------------------+
|  [折叠] 新会话 40字...   Agent · gpt-4o (只读)   [规划中 1.2s]   [上下文 8·1·0·12/20] [调度] | <- ChatHead
+-----------------------------------------------------------------------------------+
|                                                                                   |
|      [用户气泡] /benchmark 对比两模型 [附件: smoke.json (2.4KB)]                     |
|                                                                                   |
|      +-- [💡 思考中] --------------------------------------------------------+     |
|      | [技能 · 基准对比] 规划：基准评测。先列出协议档和数据集，再组确认卡。    1.2s  |     |
|      +-----------------------------------------------------------------------+     |
|                                                                                   |
|      +-- [⚙️ 短工具] --------------------------------------------------------+     |
|      | 列出协议档                                                     45ms |     |
|      | MCP · 短工具                                                 [调用完成] |     |
|      | > 输入: {}                                                            |     |
|      | > 输出: { items: [...] }                                              |     |
|      +-----------------------------------------------------------------------+     |
|                                                                                   |
|      +-- [📋 任务确认卡 (基准评测)] -------------------------------------------+     |
|      | 被测协议档: [gpt-4o x] [claude-3-5 x]                                  |     |
|      | 评测数据集: [smoke-20 v3 (20条)]                                       |     |
|      | 采样行数: 1000 | 并发数: 4 | 超时: 60s | 温度: 0                          |     |
|      | [x] 勾选先评后压 (压测 QPS: 10, 时长: 120s)                             |     |
|      |                                                [取消]  [确认并入队]   |     |
|      +-----------------------------------------------------------------------+     |
|                                                                                   |
+-----------------------------------------------------------------------------------+
|      +-- [进度坞 (贴在输入框上方)] ------------------------------------------+     |
|      | [||||||||||........] 50% (10/20) 正在执行模型对比评测...      [取消任务] |     |
|      +-----------------------------------------------------------------------+     |
|                                                                                   |
|      +-- [斜杠面板 (键入 / 触发，宽 360px)] ----------------------------------+     |
|      | 系统命令 (15条)                                                        |     |
|      |   > /benchmark    基准评测                                             |     |
|      |     /rag          RAG 评测 (将在知识库阶段启用)                         |     |
|      |     /testcase     生成用例                                             |     |
|      |     /stress       先评后压                                             |     |
|      | 我的命令                                                               |     |
|      |   自定义命令未启用                                                     |     |
|      +-----------------------------------------------------------------------+     |
|                                                                                   |
|      [附件+] [ 请输入评测需求或输入 / 选择命令...                 ] [Agent·gpt-4o] [↑] | <- Composer
+-----------------------------------------------------------------------------------+
```

### 2.2 WS 事件驱动与卡片渲染时序图
```text
浏览器 (Vue 3)                                    FastAPI (Agent Host)           PostgreSQL / Worker
     │                                                     │                              │
     │── 1. user_message: "/benchmark 对比两模型" ─────────►│                              │
     │   (前端立即渲染 UserBubble)                         │                              │
     │                                                     │── 2. run_plan(...)           │
     │◄─ 3. event: thought { stage: 'plan', skill_id, .. } ─│                              │
     │   (前端渲染 ThoughtCard，带 SkillBadge 与耗时)      │                              │
     │                                                     │── 4. run_react(tool_list)    │
     │◄─ 5. event: tool_call { name: 'model.list' } ───────│                              │
     │   (前端渲染 ToolCard pending 状态)                  │                              │
     │◄─ 6. event: tool_result { ok: true, latency_ms } ───│                              │
     │   (前端更新 ToolCard 状态为 ok，展示耗时与 JSON)    │                              │
     │                                                     │── 7. run_gates(...)          │
     │◄─ 8. event: thought { stage: 'reflect', text } ─────│                              │
     │◄─ 9. event: confirm { kind: 'benchmark', ... } ─────│                              │
     │   (前端渲染 ConfirmCard，等待用户交互)              │                              │
     │                                                     │                              │
     │── 10. confirm_ack { ok: true, patch: {...} } ───────►│                              │
     │                                                     │── 11. task.create (queued) ─►│
     │◄─ 12. event: thought { text: '已入队...' } ─────────│                              │
     │◄─ 13. event: progress { percent: 10, ... } ─────────│◄─────────────────────────────│ (Worker 推送)
     │   (前端底部起坞 ProgressDock)                       │                              │
     │◄─ 14. event: report { report_id: 'uuid' } ──────────│◄─────────────────────────────│
     │   (前端渲染 ReportCard，进度坞隐藏)                 │                              │
```

### 2.3 会话持久化与历史回放契约

卡片的实时渲染与会话保存分层处理，不能把“当前连接看到了”当成“会话已经保存”：

| 信息 | 保存位置 | 刷新/断线恢复规则 |
| :--- | :--- | :--- |
| 用户气泡、助手交付句 | `messages` | 按消息时间回放；助手交付句不再重复渲染成思考卡 |
| 阶段思考、技能徽标 | `ws_events.thought`（含 `stage` / `skill_id`） | 事件回放后恢复 ThoughtCard 与 SkillBadge |
| 模型推理链 | `thought.stream=think` 为瞬态；成功结束写 `thought.stream=think_final` | 不逐 token 写库；完整 `think_final` 快照可回放 |
| MCP 短工具 | 成对的 `tool_call` / `tool_result` 事件 | 按工具名配对恢复 ToolCard，并用历史结果重新填充确认卡选项 |
| 确认卡及回执 | `confirm` 事件 + `sessions.pending_confirm`；`confirm_ack` 事件 | 当前未处理卡由 pending 字段覆盖为可编辑；确认/取消状态从回执回放 |
| 压缩上下文 | `sessions.compact_summary` + `compact_keep_from` | 历史接口返回摘要与服务端 ContextMeter，前端不得自行计算 |

`thought.stream=chunk` 仍只负责在线正文增量，不落库；完整助手正文以 `messages.role=assistant`
保存。所有持久化事件统一进入 `ws_events`，因此团队协作者可通过 forward loop 补发，刷新也不会丢卡片。

---

## 3. 卡片体系详细设计与接口契约

### 3.1 技能徽标组件 (`frontend/src/components/agent/SkillBadge.vue`)
- **定位**：在思考卡头部渲染当前规划所命中的技能标识，**不单开 WS 事件、不单独占一张大卡**；
- **Props 契约**：
  ```typescript
  defineProps<{
    skillId?: string | null
  }>()
  ```
- **文案与色彩映射**（对齐 `frontend/src/agent/skillLabels.ts`）：
  | `skill_id` | 渲染文案 | 背景色 / 边框色 | 图标 |
  | :--- | :--- | :--- | :--- |
  | `skill-benchmark` | `技能 · 基准对比` | `rgba(16, 185, 129, 0.12)` / `rgba(16, 185, 129, 0.25)` | ⚡ 闪电/对比 |
  | `skill-rag` | `技能 · RAG 评估` | `rgba(59, 130, 246, 0.12)` / `rgba(59, 130, 246, 0.25)` | 📚 书籍/知识库 |
  | `skill-testcase` | `技能 · 用例生成` | `rgba(168, 85, 247, 0.12)` / `rgba(168, 85, 247, 0.25)` | 📝 需求/用例 |
  | `skill-stress` | `技能 · 先评后压` | `rgba(245, 158, 11, 0.12)` / `rgba(245, 158, 11, 0.25)` | 🚀 火箭/压力 |
- **显示策略**：`skillId` 为空或无效时不占位不渲染；历史回放中只要 events 记录了 `skill_id`，刷新后依然完整显示。

### 3.2 思考卡组件 (`frontend/src/components/agent/ThoughtCard.vue`)
- **Props 契约**：
  ```typescript
  defineProps<{
    text: string
    done?: boolean
    latencyMs?: number
    stage?: 'plan' | 'react' | 'reflect'
    skillId?: string | null
  }>()
  ```
- **头部要素**：
  1. 灯泡图标（思考中呼吸闪烁，已思考静态展示）；
  2. 标题文案：`done ? '已思考' : '思考中'`；
  3. `SkillBadge` 技能徽标（仅在 `skillId` 有值时展示）；
  4. `formatLatency(latencyMs)` 耗时徽章（如 `1.2s`、`320ms`）；
  5. 折叠指示箭头（展开向下，收起向右）。
- **800ms 平滑折叠状态机**：
  ```typescript
  let collapseTimer: number | null = null
  watch(() => props.done, (isDone) => {
    if (isDone) {
      if (collapseTimer) clearTimeout(collapseTimer)
      collapseTimer = window.setTimeout(() => {
        collapsed.value = true
      }, 800)
    }
  })
  ```
- **正文展示**：未完成时尾部渲染闪烁打字光标（`▍`），完成后支持纯文本或 Markdown 渲染；点击头部任意位置可随时手动展开/收起。

### 3.3 短 MCP 工具卡组件 (`frontend/src/components/agent/ToolCard.vue`)
- **Props 契约**：
  ```typescript
  defineProps<{
    tool: string
    args?: any
    result?: any
    status?: 'pending' | 'ok' | 'fail'
    latencyMs?: number
    open?: boolean
  }>()
  ```
- **头部要素**：
  1. 状态图标（`pending`：蓝色旋转环；`ok`：绿色对勾；`fail`：红色感叹号）；
  2. 标题区：第一行为**标准中文名称**；第二行为固定副标题 **「MCP · 短工具」**；
  3. 右侧元数据：`formatLatency(latencyMs)` 耗时徽章 + 状态文案（`调用中...` / `调用完成` / `调用失败`）；
  4. 折叠指示箭头。
- **标准中文名称映射表**：
  ```typescript
  const toolNameMap: Record<string, string> = {
    'model.list': '列出协议档',
    'dataset.list': '列出数据集',
    'kb.list': '列出知识库',
    'task.get': '查询任务详情',
    'task.create': '创建评测任务',
    'task.cancel': '取消任务',
    'report.get': '读取评测报告',
    'dispatch.overview': '调度概览',
    'testcase.confirm': '确认用例入库',
  }
  ```
- **详情区展开**：点击展开展示两块区域：
  - `输入 (Arguments)`：格式化的 JSON 代码块；
  - `输出 (Result)`：格式化的 JSON 代码块；序列化超过 4000 字符时服务端截断展示。

### 3.4 任务确认卡组件 (`frontend/src/components/agent/ConfirmCard.vue`)
- **定位**：在对话流内嵌展示（**绝非弹窗**），承载用户下单前的参数复核与内联修改；
- **Props 与 Emits 契约**：
  ```typescript
  defineProps<{
    card: ConfirmCardData
    isAcked?: boolean
    disabled?: boolean
    disableReason?: string
  }>()
  defineEmits<{
    (e: 'confirm', patch: Partial<ConfirmCardData>): void
    (e: 'cancel'): void
  }>()
  ```
- **卡片核心结构**：
  1. 头部：`KindTag` 徽标 + 中文标题（如 `基准评测确认卡`、`用例生成确认卡`）；
  2. 主表单区：
     - `benchmark`：协议档多选（1~5个）、数据集单选；
     - `rag`：知识库单选、黄金 QA 单选、LightRAG 模式（`hybrid`/`local`/`global`/`naive`）；
     - `testcase`：需求来源文件或文本展示；
     - 运行参数折叠区（`run`）：`sample_size` (默认 1000)、`concurrency` (默认 4)、`timeout_s` (60s)、`temperature` (0)、`max_tokens` (1024)；
     - 压测参数区（`stress`）：`with_stress` 复选框勾选，展开 `qps` (10)、`duration_s` (120s)、`env` (`test`)；
  3. 操作区：
     - 「取消」按钮：触发 `confirm_ack(ok=false)`，卡片标记为已取消；
     - 「确认并入队」按钮：触发 `confirm_ack(ok=true, patch)`，发起任务入队；若会话已有占槽任务，按钮禁用并悬浮提示 `disableReason`。

### 3.5 进度坞组件 (`frontend/src/components/agent/ProgressDock.vue`)
- **定位**：常驻贴合在底部 Composer 输入框正上方，承载 Worker 异步推送的 `progress` 事件；
- **Props 契约**：
  ```typescript
  defineProps<{
    task: {
      id: string
      kind: string
      status: string
      progress?: { percent?: number; done?: number; total?: number; message?: string }
    }
  }>()
  defineEmits<{
    (e: 'cancel', taskId: string): void
  }>()
  ```
- **交互规范**：
  1. 显示任务类型徽标、实时进度百分比（进度条动画）与进度说明文案（如 `10/20 [50%] 正在进行模型打分...`）；
  2. 取消按钮分流（§17.6）：
     - 评测任务点击取消：弹出 Dialog `「当前样本结束后停止」`；
     - 压测任务点击取消：弹出 Dialog `「立即停止发压」`。

### 3.6 报告卡组件 (`frontend/src/components/agent/ReportCard.vue`)
- **定位**：长任务 `succeeded` 后推送 `report` 事件在对话流中展示的报告入口卡片；
- **Props 契约**：
  ```typescript
  defineProps<{
    reportId: string
    kind?: string
  }>()
  ```
- **内容要素**：报告图标 + 任务类型 + 成功提示 + 「查看完整报告 ↗」按钮（点击跳转 `/reports/{reportId}`）。真实模式下严禁前端伪造假指标。

---

## 4. Markdown 与富文本渲染引擎设计 (`MarkdownView.vue`)

### 4.1 核心需求与架构
```text
原始 Markdown 文本 ──► 1. DOMPurify / 安全过滤 (XSS 消毒)
                    ──► 2. 块级 Token 解析 (段落 / 列表 / 标题 / 粗斜体)
                    ──► 3. 围栏代码块提取 (```lang ... ```) ──► 代码高亮 + 复制按钮
                    ──► 4. Mermaid 图表匹配 (```mermaid)   ──► 尝试渲染，失败降级源码
                    ──► 5. KaTeX 公式匹配 ($...$ / $$...$$) ──► 数学公式解析 / 原文降级
                    ──► 6. 最终安全 HTML 渲染
```

### 4.2 XSS 消毒与安全过滤规范
- 严格过滤 `<script>`、`<iframe>`、`<object>`、`<embed>`、`onload`、`onerror`、`javascript:` 等恶意属性与标签；
- 允许的标签白名单：`<p>`, `<span>`, `<div>`, `<h1>`~`<h6>`, `<ul>`, `<ol>`, `<li>`, `<code>`, `<pre>`, `<blockquote>`, `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`, `<a>` (仅 `http/https` 且强制 `target="_blank" rel="noopener noreferrer"`), `<strong>`, `<em>`, `<hr>`, `<br>`。

### 4.3 围栏代码与复制功能
- 识别 ` ```{lang} ` 语法，提取代码语言标识（如 `python`, `json`, `typescript`, `bash` 等）；
- 渲染为独立的黑色深色代码卡片，右上角常驻语言标识与「复制」按钮；点击复制成功后显示「已复制 ✓」，1.5s 后自动复原。

### 4.4 Mermaid 图表优雅降级
- 识别 ` ```mermaid ` 代码块；
- 若已加载 Mermaid 渲染器且语法合法，动态渲染 SVG 流程图/时序图；
- 若未加载库、渲染抛错或语法非法，**绝对不阻断对话渲染**，优雅降级为等宽代码块显示 Mermaid 源码。

### 4.5 KaTeX 数学公式解析
- 行内公式：匹配 `$...$`，渲染为行内数学符号；
- 块级公式：匹配 `$$...$$`，居中独立排版；
- 若未加载 KaTeX 或解析失败，保留原字符文本显示。

---

## 5. 斜杠命令交互系统设计 (`SlashPalette.vue` + `slashRegistry.ts`)

### 5.1 360px 悬浮面板规格
- **定位**：宽 360px，固定贴在输入框正上方（`bottom: calc(100% + 8px)`），带有 `backdrop-filter: blur(12px)` 半透明毛玻璃背景、深色优雅边框与阴影；
- **触发时机**：当用户在 Composer 输入框中键入 `/` 作为起始字符时即刻呼出。

### 5.2 上区：系统 15 条必带命令规格表
严格对齐《Agent开发文档》§9 与 `slashRegistry.ts`：

| 分组 | 命令标识 | 提示语 | 启用状态 | 未启用原因 / 行为 |
| :--- | :--- | :--- | :---: | :--- |
| **下单组** | `/benchmark` | 基准评测 | **已启用** | 自动填入并引导澄清与确认卡 |
| | `/rag` | RAG 评测 | 灰置 | `将在知识库阶段启用` |
| | `/testcase` | 生成用例 | **已启用** | 支持携带需求附件或粘贴文本 |
| | `/stress` | 先评后压 | **已启用** | `skill_id=skill-stress`，确认卡依然为 quality kind |
| **控制组** | `/cancel` | 取消本会话非终态任务 | **已启用** | 弹出取消确认对话框 |
| | `/rerun` | 拷贝最近任务配置为新确认卡 | **已启用** | 读取终态任务并组装新确认卡 |
| | `/stop` | 停止本轮生成 | **已启用** | 会话级 abort，不取消已入队任务 |
| | `/new` | 新建空会话 | **已启用** | 调用 POST /api/sessions 并重连 WS |
| | `/compact` | 压缩本会话模型窗口 | **已启用** | 保留近 6 条原文，压缩历史为摘要 |
| **只读组** | `/status` | 当前占槽 / 活动任务 | **已启用** | 读取当前会话活动任务详情 |
| | `/profiles` | 列出协议档 | **已启用** | 调用 model.list 工具并展示摘要 |
| | `/datasets` | 列出数据集 | **已启用** | 调用 dataset.list 工具并展示摘要 |
| | `/kb` | 列出知识库 | 灰置 | `将在知识库阶段启用` |
| | `/report` | 读取已有报告 | 灰置 | `报告解读将在 M4 接入` |
| **系统组** | `/help` | 列出当前已启用命令 | **已启用** | 只列出当前启用的可用命令清单 |

### 5.3 下区：团队自定义命令体系
- 请求 `GET /api/slash-commands` 获取团队自定义命令列表；
- **M1 阶段行为**：若接口返回 `VALIDATION`（400），下区明确展示「自定义命令未启用」，严禁使用 localStorage 伪造已保存；
- **M2 阶段行为**：支持展示自定义命令列表，点击底部「+ 添加命令」呼出创建弹窗。

### 5.4 键盘导航与 IME 防抖
- 监听输入框键盘事件：
  - `↑` (ArrowUp)：向上移动高亮光标；
  - `↓` (ArrowDown)：向下移动高亮光标；
  - `Enter`：选中当前高亮命令并填入输入框，自动追加空格并关闭面板；
  - `Esc`：立即关闭斜杠面板；
- **IME 合成感知**：监听 `compositionstart` 与 `compositionend` 事件，中文输入法拼音输入期间**绝不触发**键盘过滤或误提交。

---

## 6. 上下文指示器设计 (`frontend/src/components/agent/ContextMeter.vue`)

### 6.1 呈现格式与度量标准
位于 ChatHead 右侧常驻展示：
$$\text{上下文  消息 } M \text{  · 技能 } S \text{  · 摘要 } C \text{  · 余量 } R \text{  / 20}$$
$$\text{记忆文件  未启用}$$

- **$M$ (消息条数)**：当前滑动窗口内的有效原文消息条数（$0 \le M \le 20$）；
- **$S$ (技能标志)**：当前进行中规划是否激活技能（$1$ 或 $0$）；
- **$C$ (摘要标志)**：当前会话是否存在压缩摘要（$1$ 或 $0$）；
- **$R$ (余量)**：$R = 20 - M$；
- **说明**：`/20` 仅约束消息窗口容量，技能与摘要是 0/1 标志，不占用分母。

### 6.2 Popover 详情浮层
点击指示器展开详情弹层，结构化展示 5 项数据：
1. **系统人设 (Persona)**：写死不可变，约 320 字符；
2. **当前技能说明 (Skill)**：当前激活技能的系统注入说明；
3. **压缩摘要 (Summary)**：`compact_summary` 内容与字数（无则显示「无」）；
4. **窗口内原文 (Messages)**：当前窗口内 $M$ 条消息总字符数；
5. **本轮工具观察 (Observations)**：本轮短工具返回的临时观察摘要；
6. **记忆文件 (Memory Files)**：固定标明「本产品无记忆文件（未启用）」。

---

## 7. 生产环境清理与 Mock 隔离规范

1. **移除 Live 模拟按钮**：
   - 彻底从 `Agent.vue` 模板中移除「模拟失败」与「模拟断线」按钮；
   - 仅在开发调试模式且 `getDataMode() === 'mock'` 时允许展示测试桩。
2. **WS 断线真实反映**：
   - 移除前端制造的伪装断线逻辑；
   - 仅当真实 WebSocket 触发 `onclose`/`onerror` 时展示「已断线，正在重连...」横幅，并在重连后携带 `last_event_id` 自动补发缺失事件。
3. **只读模型展示**：
   - 移除 `Agent.vue` 中原有的模型自由切换 `<n-dropdown>` 下拉菜单；
   - 顶栏与输入框统一渲染脱敏只读文本 `Agent · {模型名}`（未配置时显示 `Agent · 未配置模型`）。

---

## 8. 修改代码文件与作用清单（全量清单）

| 序号 | 代码文件路径 | 变更类型 | 核心作用与改动说明 |
| :--- | :--- | :---: | :--- |
| 1 | `docs/AI测试与评估平台-Agent界面卡片Markdown与斜杠技术方案.md` | **新建** | 模块 7 界面卡片、Markdown 与斜杠技术方案（V1.0）。 |
| 2 | `frontend/src/components/agent/SkillBadge.vue` | **新建** | 思考卡技能徽标独立组件，实现 4 大技能文案匹配与徽标渲染。 |
| 3 | `frontend/src/components/agent/MarkdownView.vue` | **新建** | 统一 Markdown 渲染器，支持 XSS 安全消毒、代码高亮复制、Mermaid 降级与 KaTeX 公式支持。 |
| 4 | `frontend/src/components/agent/SlashPalette.vue` | **新建** | 360px 斜杠命令悬浮面板，实现上区系统 15 条与下区自定义命令分组、键盘导航与 IME 防抖。 |
| 5 | `frontend/src/components/agent/ContextMeter.vue` | **新建** | 上下文度量指示器与详情浮层，准确呈现四段结构与记忆文件未启用状态。 |
| 6 | `frontend/src/components/agent/ThoughtCard.vue` | **修改** | 集成 SkillBadge 徽标、耗时徽章与 800ms 自动平滑折叠动画。 |
| 7 | `frontend/src/components/agent/ToolCard.vue` | **修改** | 规范化标准中文工具名映射，统一副标题为「MCP · 短工具」，支持耗时徽章展示。 |
| 8 | `frontend/src/components/agent/Composer.vue` | **修改** | 接入 SlashPalette 面板、IME 输入法防抖、只读模型名展示。 |
| 9 | `frontend/src/views/Agent.vue` | **修改** | 移除模型下拉切换菜单与 live 模拟按钮，集成 ContextMeter 与统一卡片组件。 |
| 10 | `docs/AI测试与评估平台-Agent开发文档.md` | **修改** | 同步勾选 Task 清单（AGT-UI-01/02/05/08, AGT-SLH-01, AGT-CTX-02）并更新修订记录。 |
| 11 | `backend/api/app/agent/harness.py` | **修改** | 保存 `think_final` 思考快照并记录 `confirm_ack` 回执事件。 |
| 12 | `backend/api/app/agent/context.py` | **修改** | 从持久化事件恢复技能与 MCP 工具计数。 |
| 13 | `backend/api/app/routers/sessions.py` | **修改** | 历史接口返回 `compact_summary`。 |
| 14 | `frontend/src/views/Agent.vue` | **修改** | 回放思考快照、确认回执与历史工具资产。 |

---

## 9. 自动化测试与构建验证方案

1. **前端生产构建**：`npm run build`（验证 Vite 生产打包和 TypeScript 类型校验 0 错误）；
2. **后端全量单测**：`pytest backend/api/tests`（验证 192 项单测 100% 通过）；
3. **代码规范自检**：`ruff check .`（验证后端代码 0 警告 0 错误）。
