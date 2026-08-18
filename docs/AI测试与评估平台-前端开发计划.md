# AI 测试与评估平台 — 前端开发计划

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.3 |
| 对应 PRD | V1.6.3（功能唯一权威） |
| 对应设计规范 | V1.2（页面 / 组件 / 浮层 / 令牌） |
| 对应总计划 | V1.0（日历与门禁） |
| 对应后端计划 | V1.3（契约提供方） |
| 对应 API | V1.3（路径/JSON 唯一冻结） |
| 撰写日期 | 2026-08-17 |
| 最近修订 | 2026-08-18：增加原型逐页还原矩阵、真实数据持久化边界与 V1.0 受控降级 |
| 计划起点 | 2026-08-18 |
| V1.0 目标发布 | 2026-12-04 |
| 总工期 | **16 周**（与总计划同一日历） |
| 主责角色 | Vue 前端 × 1 |

---

## 1. 编制说明

本文把总计划里的「Vue」列拆成可执行的页面、组件、契约与周任务。  
**不改范围**：做不做、字段名、路由、事件名只认 PRD；像素与交互形态认设计规范；日期与门禁认总计划。

冲突裁决：PRD > 总计划 / 本文 > 设计规范中的视觉细节。若本文与 PRD 冲突，改本文。

### 1.1 范围

| 做（V1.0 前端） | 不做 |
| --- | --- |
| PRD 5.8 全部路由；设计规范 AppShell / 令牌 / Naive 主题 | 新增业务路由（含 `/reports` 列表、改系统提示词页、审计独立页） |
| `/agent`：会话列表 + 对话流 + 确认卡 + 进度坞 + WS | Ask/Plan/Bypass、切模型、外部 MCP、SSE/socket.io 旧事件名 |
| 工作台：任务 / 报告 / 数据集 / 用例 / KB / 三块管理页 | Tailwind、UnoCSS、Element Plus、ECharts |
| 浮层：`n-message` / `n-dialog` / `n-modal` / `n-drawer` | `window.alert`；把确认卡做成 `n-modal` |
| 表单双入口与确认卡同一 field schema（F-AGT-07） | Open API 控制台（F-CM-08 / V1.1） |
| 压测曲线 Chart.js（M4） | RAG 过程可视化（F-RAG-07）、多租户、多模态 |

### 1.2 与总计划的关系

| 总计划 | 本文 |
| --- | --- |
| 16 周日历、M0–M4 / H 门禁 | 完全复用，不另开工期 |
| 「Vue」列工作项 | 拆到页面 / 组件 / store / 契约 |
| 周三契约对表 | 前端以 OpenAPI / 共享类型为准，禁止私自发明路径 |
| 门禁未过禁止下一阶段 | 前端同样：M2 没出对比报告就不做 `/kb` 真功能 |

### 1.3 人员与节奏

- 编制：Vue × 1（与总计划一致）。  
- 周一排本周条目；周三与后端对契约；周五 30 分钟演示。  
- 后端未就绪时：仅可用显式 Mock（`?data=mock`，同 schema）；**不得**把 Mock 作为请求失败回退，更不得改字段名迁就 Mock。

### 1.4 V1.2 权限口径校正

PRD 2.1 已冻结为单一 `member`、全员同权。本计划中早期出现的 `admin`、`engineer`、`readonly`、`minRole`、按角色裁剪侧栏等文字均为旧版遗留，**不进入实现**；以 §2.2 和 API V1.3 为准。保留 `/admin/*` 仅为信息架构和历史 URL，不代表角色限制。任务取消仍按“创建者”约束，`prod` 会签须非创建者成员。

---

## 2. 技术栈与工程骨架

| 项 | 选型 | 来源 |
| --- | --- | --- |
| 框架 | Vue 3 + Vite + TypeScript | PRD 文头 |
| UI | Naive UI（`n-config-provider` 包整站） | PRD 5.8、设计规范 §8.4 |
| 状态 | Pinia：`theme` `auth` `agent` `nav` | 设计规范 §10 |
| 路由 | Vue Router，表 = PRD 5.8 | 不得增减业务路由 |
| HTTP | `frontend/src/api/http.ts`，前缀 `/api`，Cookie 会话 | PRD 5.9、2.1 |
| WS | `frontend/src/api/ws.ts`，短票升级 | F-AGT-01/02 |
| 图表 | Chart.js（仅 M4 压测三曲线） | 设计规范 §8.4 |
| 样式 | `tokens.css` + `data-theme` | 设计规范 §8；禁止用 Vue 响应式改写 CSS 变量 |

### 2.1 目录（设计规范 §10，M0 一次建齐）

```
frontend/src/
├── styles/        tokens.css  base.css  animations.css  layout.css  agent.css  platform.css
├── naive-theme.ts
├── router/        index.ts          # 仅 PRD 5.8
├── stores/        theme.ts  auth.ts  agent.ts  nav.ts
├── api/           http.ts  ws.ts  types.ts    # REST=5.9；WS=5.1.3
├── schemas/       confirmCard.ts    # 与 POST /api/tasks 同一套
├── components/
│   ├── layout/    AppShell Sidebar Topbar
│   ├── overlay/   （统一 message/dialog/modal 封装，禁止散落 window.*）
│   └── agent/     SessionList ChatStream UserBubble ThoughtCard ToolCard
│                  ConfirmCard ReportCard ErrorStrip ProgressDock Composer
└── views/         Login Agent Tasks Report Datasets Cases Kb
                   AdminProfiles AdminStress AdminUsers
```

不建：多项目 store、用户可选模型 store、旧仓 `/targets` 等页面。

### 2.2 路由与权限（设计规范 §3）

| 路由 | 视图 | 访问口径 | 侧栏 | 最早可演示 |
| --- | --- | --- | --- | --- |
| `/login` | Login | 无 | 否 | M0 |
| `/agent` | Agent | 已登录成员 | 是「智能体」 | M1 |
| `/tasks` | Tasks | 已登录成员；取消限创建者 | 是 | M1 |
| `/reports/:id` | Report | 已登录成员；`?share=` 可未登录只读 | 否 | M2 |
| `/datasets` | Datasets | 已登录成员 | 是 | M2 |
| `/cases` | Cases | 已登录成员 | 是 | M2 |
| `/kb` | Kb | 已登录成员 | 是 | M3 |
| `/admin/profiles` | AdminProfiles | 已登录成员（路由名保留） | 是 | M1 |
| `/admin/stress` | AdminStress | 已登录成员（路由名保留） | 是 | M4（M1 可放空壳） |
| `/admin/users` | AdminUsers | 已登录成员（路由名保留） | 是 | M1 |

守卫：未登录跳 `/login`；分享 token 仅开放对应报告的只读视图。V1.0 不按历史 `admin/engineer/readonly` 隐藏入口；敏感变更由后端审计，任务取消由创建者约束。登录后统一落地 `/agent`。

---

## 3. 前后端契约（前端必须遵守）

### 3.1 REST（PRD 5.9 + 正文补全）

前端 **只调用** `AI测试与评估平台-API.md` V1.3 列出的浏览器路径。5.9 是摘要，补全路径以 API 文档为准，**不算新产品功能**。

| 方法 | 路径 | 前端消费者 | 阶段 |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | Login | M1 |
| POST | `/api/auth/logout` | 顶栏退出 Dialog | M1 |
| POST | `/api/auth/change-password` | 首次改密 Modal | M1 |
| GET | `/api/auth/me` | `auth` store 刷新恢复身份 | M1 |
| POST | `/api/auth/ws-ticket` | Agent WS | M1 |
| GET | `/ws/agent?ticket=` | `/agent` | M1 |
| GET/POST | `/api/sessions`；GET `/api/sessions/{id}/messages` | SessionList（**方案 A，已冻结**） | M1 |
| GET/POST | `/api/users`；PUT `/api/users/{id}`、`/status`；GET `/api/users/activity-summary`；POST `/api/users/{id}/reset-password` | `/admin/users` | M1 |
| GET/POST | `/api/files`；GET `/api/files/{id}` | Composer 附件、各上传 | M1 |
| CRUD | `/api/profiles`；POST `/api/profiles/{id}/check` | `/admin/profiles`；确认卡下拉 | M1 |
| CRUD | `/api/datasets`；POST `/{id}/upload`；GET `/{id}/rows` | `/datasets` | M2 |
| GET | `/api/case-sets` `/{id}`；POST `/{id}/confirm` `/{id}/map`；GET `/{id}/export` | `/cases` | M2/M3 |
| CRUD | `/api/kb`；POST `/{id}/documents`；DELETE `/{id}/documents/{doc_id}` | `/kb` | M3 |
| CRUD | `/api/kb/{id}/gold-qa` | `/kb` | M3 |
| POST/GET | `/api/tasks`；GET `{id}`；POST `{id}/cancel` `{id}/rerun` | Agent / Tasks / 抽屉 | M1 起 |
| POST | `/api/tasks/{id}/approve-stress` | `prod` 会签 | M4 |
| GET | `/api/tasks/{id}/stress-series` | ProgressDock / Chart.js | M4 |
| GET | `/api/reports/{id}`；POST `{id}/share` `{id}/baseline` | Report | M2 |
| GET/PUT | `/api/admin/settings` | Agent 后端；stress 治理；通知开关 | M1/M4 |

会话 **不再周三二选一**：以 API V1.3 方案 A 为准。
禁止发明：`/api/chat/completions`、旧 TestPilot 路径、把 MCP 工具名当 REST、浏览器直连 `/metrics`。

### 3.2 WebSocket（PRD 5.1.3）

登录后 `POST /api/auth/ws-ticket`（5 分钟）→ `GET /ws/agent?ticket=`。心跳 30s。重连带 `session_id` + `last_event_id`。

**服务 → 前端**（事件名不可改）：`thought` `tool_call` `tool_result` `confirm` `progress` `report` `error` `pong`。  
**前端 → 服务**：`user_message` `{text, attachments[]?}`、`confirm_ack` `{ok, patch?}`、`cancel_task` `{task_id}`。

禁止参考文档的 `thinking` / `token` / `chat:send` / `tool_call_start`。

公共头：`event`, `session_id`, `task_id?`, `event_id`, `ts`。

### 3.3 确认卡 = `POST /api/tasks`（F-AGT-04 / 07）

字段名、必填语义不得改，见 PRD 5.1.2 / 设计规范 §6。实现为 `schemas/confirmCard.ts`，Agent 确认卡与 `/datasets` `/kb` 抽屉共用。

`kind` 四选一：`benchmark` / `rag` / `testcase` / `stress`（`stress` 一般不手选）。

### 3.4 错误码文案（设计规范 §7.3）

`UNAUTHORIZED` `VALIDATION` `NOT_FOUND` `BUDGET_EXCEEDED` `CONCURRENCY` `WHITELIST` `NEED_APPROVAL` `UPSTREAM` `TIMEOUT` `INTERNAL` —— Toast / 卡内红字用固定中文，不展示 stack、Key、token。

确认卡校验留在卡内，不 Toast。

---

## 4. 组件与页面交付清单

### 4.1 壳与浮层（M0–M1）

| 组件 | 规范 | 完成标准 |
| --- | --- | --- |
| AppShell / Sidebar / Topbar | §3、§8.3；260↔72；主区 18px | 分组：评测 + 管理；所有已登录成员一致渲染 |
| 主题切换 | `data-theme` | 明暗令牌；`prefers-reduced-motion` 关装饰动画 |
| Toast | §14.2 `n-message` | 右上；error 5s；必 Toast 点按规范清单 |
| Dialog | §14.3 | 取消评测 vs 取消压测两套文案；`prod` 点遮罩不关 |
| Modal | §14.4 | 改密 / 开户 / 协议档 / 分享 |
| Drawer | §14.5 | 任务详情；发起评测（M2/M3） |

### 4.2 Agent（M1，M4 增强）

| 组件 | PRD / 规范 | 阶段 |
| --- | --- | --- |
| SessionList | 多会话；非终态徽章；V1 不删除会话 | M1 |
| ChatHead | 只读模型名；无切模型 | M1 |
| UserBubble / AssistantText / ThoughtCard / ToolCard | §15.3；工具标题用中文名 §7.3 | M1 |
| ConfirmCard | §6；Naive 控件；未 ack 不入队 | M1 |
| ReportCard | `report_id` → `/reports/:id`；M4 加「解读」 | M1 壳 / M2 真报告 / M4 解读 |
| ErrorStrip | `error` + Toast | M1 |
| ProgressDock | `progress`；用例 72h；M4 曲线 | M1 / M4 |
| Composer | 附件先 `POST /api/files`；≤20MB 白名单 | M1 |

快捷芯片（可选，非 PRD 功能）：最多 4 个——「生成用例」「基准评测」「RAG 评测」「先评后压」。只预填一句话，仍须澄清 + 确认卡。

### 4.3 工作台页面

| 页 | 功能编号 | 阶段 | 要点 |
| --- | --- | --- | --- |
| Login | F-CM-03 | M0 能开 / M1 真登录 | 失败不区分用户/密码；引导改密；不写 JWT 到 localStorage |
| Tasks | F-CM-01、F-AGT-09 | M1 | 筛状态/kind；时间线抽屉；取消权限 2.1；复制为新任务 |
| Report | F-CM-02、F-BM-05/06/07、F-RAG-04/06、F-ST-02/06/07 | M2 起 | 并排 1–5；MD 导出；分享 7 天；Hit 分母脚注；未填 SLA 不出达标；模型压测加 TTFT/TPOT/tokens/s |
| Datasets | F-BM-03/04/05、F-AGT-07 | M2 | JSONL/CSV；版本 +1；待补全不进分母；抽屉下单 |
| Cases | 5.4.1/5.4.2 | M2 | 自检红字；确认/拒绝；导出；72h |
| Kb | F-RAG-01～05、F-AGT-07 | M3 | 不把 LightRAG 展示成 Chat Completions |
| AdminProfiles | F-BM-01、F-AGT-06 | M1 | Key 只写不回显；指定唯一 Agent 后端；可标裁判 |
| AdminStress | F-ST-05、F-CM-05/06、3.4 | M4 | 白名单、单价、并发、预算默认、通知开关 |
| AdminUsers | F-CM-03 | M1 | 开户/停用/重置密/审计查看 |

---

## 5. 分周计划

日历与总计划相同。每项含：**PRD**、**规范**、**依赖后端**、**完成标准**。

---

### M0  工程启动（W1，08-18 ~ 08-24）

**目标**：Compose 打开登录页；后续页面都落在同一壳上。

| 编号 | 工作项 | PRD / 规范 | 完成标准 |
| --- | --- | --- | --- |
| FE-M0-1 | Vite + Vue3 + TS + Naive + Pinia + Router | 总计划 M0-3 | `web/` 可热重载 |
| FE-M0-2 | 迁入 `tokens.css`；`naive-theme.ts`；`data-theme` | 规范 §8 | 明暗切换；主色=`--accent-ai` |
| FE-M0-3 | AppShell 空壳 + 5.8 全部空路由 | 规范 §3 | `/login` 可打开；侧栏分组正确 |
| FE-M0-4 | `http.ts` 前缀 `/api`；401 回登录 | 总计划 M0 出口 | 不存长期 token |
| FE-M0-5 | 浮层封装（message/dialog）空转 | 规范 §14 | 禁止 `alert` |

**本周不做**：真登录、WS、确认卡逻辑。  
**M0 出口**：周五只验收「环境能起、登录页能开」。

---

### M1  底座 + Agent（W2–W5，08-25 ~ 09-21）

对应：F-AGT-01/02/03/04/05/06/09，F-BM-01，F-CM-01/03/04/07。  
长任务后端可 mock `succeeded`；前端按真事件流渲染。

#### W2  账号、权限、文件、浮层

| 工作项 | 完成标准 |
| --- | --- |
| Login + Cookie 会话 + 首次改密 Modal（不可点遮罩关） | 设计规范 5.1 / 14.4；密码校验提示 ≥8 且字母+数字 |
| `auth` store：身份、停用态与 `must_change_password`；侧栏不按角色裁剪 | 登录后统一进 `/agent`；停用/失效时清理会话 |
| `/admin/users`：开户 / 停用 / 重置密 Modal | 全员同权；写操作走 Dialog，敏感变更由后端审计 |
| 退出登录 Dialog（任务不停止） | 规范 §14.3 |
| 通用上传：`POST /api/files`；≤20MB；类型白名单 | 超限 Toast；附件芯片 |
| 错误码 → 中文映射表 | 规范 §7.3 |

**依赖**：后端首次成员引导、单一 `member` 鉴权、`/api/users`、`/api/files`。

#### W3  协议档管理

| 工作项 | 完成标准 |
| --- | --- |
| `/admin/profiles` CRUD Modal | 协议三选一；Key 空=不修改；**永不回显** |
| 指定唯一 Agent 后端（settings） | 输入栏只读模型名有来源 |
| 连通性检查：`POST /api/profiles/{id}/check`，结果 Modal | 失败摘要不含 Key；不打进 console |
| 协议档用途：被测 / Agent 后端 / 裁判（可标，不强制互斥除 Agent 仅一个） | 与 F-AGT-06、F-BM-08 对齐 |
| Key 变更 Toast「已更新」 | F-CM-04 前端不展示审计页 |

**依赖**：`CRUD /api/profiles`、`GET/PUT /api/admin/settings`。

#### W4  任务中心 + 状态徽章 + 会话契约冻结

| 工作项 | 完成标准 |
| --- | --- |
| `/tasks` 表：筛状态 / kind；列按规范 5.3 | 徽章色：灰/靛蓝转圈/琥珀/绿/红/灰 |
| 行：详情抽屉（`task_events`）、取消 Dialog、复制为新任务 | 所有成员可见；取消仅创建者可用，其他写操作按资源规则呈现 |
| 取消文案：评测=样本结束后停（M1 无压测，压测文案可先写死到组件待 M4 启用） | 规范 §14.3 |
| 周三按 API V1.3 实现 `GET/POST /api/sessions` 与 messages 回放 | 不再二选一 |
| `schemas/confirmCard.ts` + 单测（必填随 kind 变化） | 与 PRD 5.1.2 一致；含 `run.*`（sample_size/concurrency/timeout_s/retry/temperature/max_tokens/system_prompt）；后端未齐也锁字段 |
| 复制为新任务 → `POST /api/tasks/{id}/rerun` | F-AGT-09；写操作均有 loading 与错误态 |

#### W5  WebSocket Agent + 确认卡（M1 门禁周）

| 工作项 | 完成标准 |
| --- | --- |
| `ws.ts`：短票、30s ping、断线重连、按 `last_event_id` 补消息 | 刷新/断线进度仍在 |
| SessionList + ChatStream 全套消息组件 | 规范 §15；无 Ask/Plan/Bypass |
| ConfirmCard：Naive 字段；`confirm_ack`；未确认不入队 | 主按钮黑底白字；取消 `{ok:false}` |
| 占槽时确认按钮禁用并说明 | 规范 §6（M1 先认父任务非终态） |
| ProgressDock + Composer 附件 | 工具卡中文标题 §7.3 |
| 人设无 UI：无改提示词、无思考强度 | F-AGT-05/06 |
| 快捷芯片（可选） | 仅四种 kind 文案 |

**M1 前端演示脚本（对齐总计划）**

1. 成员登录 → `/admin/profiles` 新增协议档（Key 不回显）。
2. 成员在 `/agent` 说「帮我下一单 Benchmark」。
3. 确认卡出现 → 确认 → 进度坞 `queued → running → succeeded`（后端 mock）。  
4. 断线重连，消息与进度仍在；`/tasks` 看得到事件。

**M1 前端出口**

- [ ] `/login` `/agent` `/tasks` `/admin/users` `/admin/profiles` 主路径 + 空态 + 错误码  
- [ ] WS 短票、心跳、补发  
- [ ] 确认卡未 ack 无任务  
- [ ] 全部成员看见相同导航；非创建者只能看到不可用的取消说明
- [ ] 无 TestPilot 字样、无 T logo、无旧胶囊

---

### M2  Benchmark + 用例 + 表单（W6–W9，09-22 ~ 10-19）

对应：F-AGT-07，F-BM-03～07，F-CM-02/06，5.4.1～5.4.2。  
成功指标「Agent 闭环」在本阶段由前端配合达成。

#### W6  数据集

| 工作项 | 完成标准 |
| --- | --- |
| `/datasets`：上传 JSONL/CSV；列说明；覆盖上传 Dialog（版本 +1） | ≤50MB 前端先拦；行数展示 |
| 每集主指标选择：exact/contain/regex/rouge_l/bleu，默认 contain | 只展示，提交随集保存 |
| 待补全行单独 Tab/表，文案写明不进评分分母 | F-BM-04 |
| 删除自己的集 → Dialog | 规范 §14.3 |

#### W7  报告、对比、基线、预算

| 工作项 | 完成标准 |
| --- | --- |
| `/reports/:id`：1–5 profile 并排；主指标 KPI `.num` | 配置快照可见 |
| 失败样本表；失败率 | 样本级失败不 Toast |
| 导出 Markdown；分享 Modal（7 天链接，可复制） | 只读可打开未过期 `?share=` |
| 成员冻结基线 Dialog → `POST /api/reports/{id}/baseline`；解冻入口 | 不同版本/指标对比入口禁用并说明；敏感操作写审计 |
| `BUDGET_EXCEEDED` Toast + 任务 failed 展示 | F-CM-06 |
| ReportCard 接真 `report_id` | Agent 可跳转报告 |

#### W8  用例确认页

| 工作项 | 完成标准 |
| --- | --- |
| `/cases`：generated 列表 → 确认页 | 自检红字：无核心正向、缺约束反向 |
| 超上限/拆分提示；禁止灌水的只读说明 | 5.4.1 |
| 确认入库 / 拒绝 Dialog；72h 倒计时（ProgressDock 链到本页） | 确认 → succeeded；拒绝/超时 → cancelled |
| 导出 xlsx / xmind | 下载走 export API |
| 映射待补全入口（跳数据集待补全） | 缺 question 不进分母（演示用）；**映射到黄金 QA 放到 M3**，本周只做 Benchmark 映射结果展示 |

**本周不做**：Postman / Markdown 接口输入（P1）。

#### W9  表单双入口 + M2 门禁

| 工作项 | 完成标准 |
| --- | --- |
| `/datasets` 抽屉「发起评测」= ConfirmCard `benchmark` 段 | 提交 `POST /api/tasks`，无对话也能出报告 |
| 会话占槽：queued/running/awaiting_case_confirm 时抽屉与确认卡同样禁用 | 规范 §6；子任务占槽逻辑前端先读父任务字段，M4 再含 stress 子任务 |
| 空态 / 错误态补齐（无集、无协议档、上传失败） | DoD |

**M2 前端演示脚本（PRD 5.2.3）**

1. 上传 ≥20 条 JSONL。  
2. 两个协议档已存在。  
3. Agent 确认后出 contain 对比报告；断线仍能看进度。  
4. 缺 `question` 的映射行在待补全，不进分母。  
5. 不经过 Agent，用数据集抽屉再下一单。

**M2 前端出口**

- [ ] Agent 闭环可演示  
- [ ] 报告对比 + 分享 + 导出  
- [ ] 双入口字段一致  
- [ ] 预算超限可见  
- [ ] 不做 `/kb` 真功能（门禁未过不拉下一阶段）

---

### M3  RAG（W10–W12，10-20 ~ 11-09）

对应：F-RAG-01～06，F-BM-08（Judge，P1）。通知不做。

#### W10  知识库页（内置）

| 工作项 | 完成标准 |
| --- | --- |
| `/kb`：文档上传、文档数、索引状态 | `doc_id` 不强制给用户编辑（UUID 后端写） |
| 知识库标核心；删文档（Dialog + 审计由后端写） | 单一成员权限；资源归属与敏感操作由后端校验 |
| 文案：查询走 LightRAG `query`，**UI 不写 Chat Completions** | F-RAG-01 |
| 空壳里的「发起 RAG」先禁用直到 W11 黄金 QA | 避免半成品下单 |

#### W11  黄金 QA + RAG 报告 + 外部 RAG 表单

| 工作项 | 完成标准 |
| --- | --- |
| 黄金 QA 上传：`question,reference,expected_doc_ids[]?`；版本 +1 | ≤1 万条前端提示 |
| 抽屉「发起 RAG 评测」= 确认卡 `rag` 段：`kb_id`+`gold_qa_id`；`rag_mode` 1–4 默认 hybrid；外部 Chat 时 1 个 RAG 服务档 | F-AGT-07 |
| 报告：Hit Rate@K / MRR / Recall@K（K 默认 5，可展示配置 1–20）；答案 contain | 无 id 样本不进 Hit 分母，**页脚必须写明**；K 用 `run.k`（API V1.3 已冻结，**不改确认卡必填列**） |
| 用例映射到黄金 QA：缺 `expected_doc_ids` 手补；无 id 仅答案侧 | PRD 5.4.2；M2 已做的 Benchmark 映射不回退 |
| Agent 确认卡补齐 RAG 字段下拉（W5 已有 schema） | 选项来自 `kb.list` 对应 REST |

#### W12  Judge + 退化标红 + M3 门禁

| 工作项 | 完成标准 |
| --- | --- |
| 报告 Judge：1–5 分 + 理由；裁判档=被测时 warning Toast，不拦截 | F-BM-08；确认卡 **不新增** judge 必填列；认 `run.use_judge`（API V1.3，默认 false） |
| RAG 基线冻结（成员 Dialog，规则同 Benchmark） | F-RAG-06 |
| 退化 ≥5pp **报告内标红**；不发通知、不 Toast 轰炸 | M3 只标红 |
| 模式对比（1–4 个 `rag_mode`） | 只读可看报告 |

**M3 前端演示**：默认库 + ≥20 条带 `expected_doc_ids` 的 QA，hybrid 出 Hit Rate@5；同一套 QA 打外部 RAG 出 contain。

**M3 前端出口**

- [ ] `/kb` 主路径 + 空态  
- [ ] Hit 分母口径在 UI 可见  
- [ ] 无过程可视化（F-RAG-07）  
- [ ] 无通知开关（留给 M4）

---

### M4  共享压测 + 解读 + 通知（W13–W15，11-10 ~ 11-30）

对应：F-ST-02/03/05/06/07，F-AGT-08，F-CM-05。  
压测内核不在前端；前端只展示与会签。

#### W13  进度区曲线骨架 + 取消语义分流

| 工作项 | 完成标准 |
| --- | --- |
| ProgressDock / 任务行：压测 running 迷你 QPS/RT/错误率，轮询 `GET /api/tasks/{id}/stress-series` | F-ST-02/03；**不扩展** WS `progress` 字段来塞曲线 |
| 取消压测 Dialog：「立即停止发压」；评测仍用「样本结束后停」 | 规范 §14.3 / F-AGT-09 |
| 会话槽位：**含子任务**；父 succeeded 后子任务占槽，确认按钮保持禁用 | PRD 3.4 / V1.6.3 |
| `prod`：确认卡展示会签人；会签走 `POST /api/tasks/{id}/approve-stress`；未会签压测 queued 的 info Toast | F-ST-05 |

#### W14  压测治理页 + SLA/费用展示

| 工作项 | 完成标准 |
| --- | --- |
| `/admin/stress`：host 白名单、QPS/时长上限展示、单价 /1k tokens、`max_running_tasks`、`max_inflight_model_calls`、默认 `max_usd` | 全员同权；**M2 起预算已按默认 5 USD 生效**，本页只是改默认值且写审计 |
| 无白名单时压测不得显示为 running（列表保持 queued + `WHITELIST`） | 负例 UI |
| 报告：未填 `sla_p99_ms` 不出「是否达标」；填了展示拐点 | F-ST-06 |
| 费用估算展示（父任务 usage × 单价） | F-ST-07 |
| `prod` 二次确认 Dialog：必须勾选白名单确认 | 规范 §14.3 |

#### W15  解读、通知、曲线对齐、M4 门禁

| 工作项 | 完成标准 |
| --- | --- |
| ReportCard / 报告页「在对话中解读」：带上 `report_id` 进 `/agent`，不重跑 | F-AGT-08 |
| `/admin/stress` 通知开关：企微 / 邮件 / Webhook，默认关 | F-CM-05 |
| Chart.js 三曲线，颜色取令牌；与 Grafana 用同一 `task_id` 对（联调） | 规范 §8.4 |
| 任务页 running 可看 QPS | 规范 5.3 |
| 模型压测报告：TTFT / TPOT / tokens/s（SSE）；RAG 非流式可不展示 TTFT | F-ST-02 |

**M4 前端演示**：test 白名单、质量成功后自动压 2 分钟；平台曲线可展示；去掉白名单后任务停在 queued；取消后曲线停止。

**M4 前端出口**

- [ ] 先评后压在 UI 上：质量非 succeeded 无压测 running  
- [ ] 两套取消文案无混用  
- [ ] 解读不触发新的评测确认卡（除非用户另说）

---

### H  硬化（W16，12-01 ~ 12-04）

不加功能。

| 工作项 | 完成标准 |
| --- | --- |
| E2E 走查：M2 演示再跑 + 非创建者取消任务走一遍 | 主路径 + 空态 + 错误码 |
| 视觉对照规范 §12：760px 对话列、签名按钮、无旧品牌 | `prefers-reduced-motion` |
| 分享未登录只读；Cookie 12h 续期不把 token 写入 localStorage | 安全走查前端侧 |
| 已知问题列表（前端） | 随 V1.0 tag |

---

## 6. 前端「完成」定义（DoD）

合入主干须同时满足（总计划 5.2 的前端部分）：

1. 有 PRD 编号，字段/事件/路由一致。  
2. 主路径 + 空态 + 错误码可见（卡内或 Toast，按 §14）。  
3. 权限至少测过未登录、已登录成员、任务创建者与非创建者。
4. 确认卡与表单抽屉同一 `schemas/confirmCard.ts`。  
5. 不把 P1/后续项（Open API、过程可视化、Postman 输入）塞进当前里程碑。  
6. 不引入参考文档里的产品能力。

---

## 7. 测试分层（前端）

| 层 | 何时 | 覆盖 |
| --- | --- | --- |
| schema 单测 | M1 W4 起 | kind 必填、`with_stress` 连带 `stress`、1–5 profile |
| 组件测 | M1 W5 | ConfirmCard ack；ToolCard 中文名 |
| 关键路径手工 / Playwright | M2、H | 确认卡下单、报告对比、分享链接、只读守卫 |
| 视觉走查 | 每里程碑周五 | 规范 §12 清单 |

---

## 8. 风险与降级（前端视角）

| 风险 | 周 | 前端降级 |
| --- | --- | --- |
| 三协议/WS 未齐 | M1 W5 | mock 事件流，**事件名仍用 PRD** |
| 用例映射大量待补全 | M2 W8 | 手传 JSONL 走数据集主路径，不挡门禁 |
| LightRAG 未就绪 | M3 | `/kb` 不提前做假 Chat UI |
| Prometheus/Grafana 对不上 | M4 | 平台 Chart.js 仍可验收；Grafana 为并行门禁 |
| 会话 REST | M1 W4 | 以 API V1.3 方案 A 为准 |

**进度红线**：与总计划相同——门禁未过只修门禁项。

---

## 9. 明确不排进本周期的前端工作

- F-CM-08 Open API 文档站 / Token 控制台  
- F-RAG-07 检索过程可视化  
- 用例输入：Postman、Markdown 接口  
- 删除会话、改系统提示词、思考强度、外部 MCP 管理  
- 独立 `/reports` 列表、独立审计页  
- 评测与压测并行的 UI、分布式压测看板  

---

## 10. 开工当天（08-18）前端待办

1. 按 §2.1 建 `web/` 目录与空视图。  
2. 从参考实现迁入令牌，**改品牌文案为「AI 测试与评估平台」**。  
3. 路由表一次性写死 PRD 5.8；不实现 `minRole`。
4. 与后端约定错误码枚举共享（TS 类型可先手写，周三对齐）。  
5. 周五只演示登录页壳。

本文与 PRD 冲突时 **以 PRD V1.6.3 为准**；与设计规范冲突时改 UI 对齐 PRD 字段，不改规范去迁就旧原型。

---

## 附录 A  对照检查记录（V1.3）

检查对象：PRD V1.6.3、设计规范 V1.2、总计划 V1.0、本文、后端计划 V1.3。

### A.1 功能编号

| 编号 | 前端落点 | 结论 |
| --- | --- | --- |
| F-AGT-01～06、09 | M1 `/agent` + WS | 覆盖 |
| F-AGT-07 | M2 数据集抽屉；M3 KB 抽屉 | 覆盖 |
| F-AGT-08 | M4 解读入口 | 覆盖 |
| F-BM-01 | M1 `/admin/profiles` | 覆盖 |
| F-BM-02 | 无 UI（适配器在后端） | 正确不排 |
| F-BM-03～07 | M2 数据集/报告 | 覆盖 |
| F-BM-08 | M3 报告 Judge | 覆盖；确认卡不新增字段 |
| F-BM-09 | 不做 | 未排 |
| F-RAG-01～06 | M3 `/kb` + 报告 | 覆盖 |
| F-RAG-07 | 后续 | 未排 |
| F-ST-01、04 | 无 UI / 无公网 metrics 页 | 正确不排 |
| F-ST-02/03/05/06/07 | M4 曲线、会签、SLA、费用、治理页 | 覆盖 |
| F-CM-01/03/07 | M1 | 覆盖 |
| F-CM-02/06 | M2 | 覆盖 |
| F-CM-04 | 无独立审计页；Key 变更只 Toast | 与规范一致 |
| F-CM-05 | M4 通知开关 | 覆盖 |
| F-CM-08 | V1.1 | 未排 |

### A.2 路由与组件

PRD 5.8 / 规范 §3 十一条路由均在 §2.2；无改系统提示词页、无 `/reports` 列表。  
规范 §15 Agent 组件、§14 浮层、§10 目录均在 M0–M1 交付清单。确认卡不是 Modal。

### A.3 检查中发现并已修

1. 5.9 未列但正文/规范需要的路径：以 API V1.3 为准（含 `GET /api/auth/me`、会话方案 A）。
2. 黄金 QA 映射（PRD 5.4.2）误只写在 M2 → 改到 M3。  
3. Hit@K 的 `k`、Judge 开关不在确认卡 5.1.2 → API 已冻结为可选 `run.k` / `run.use_judge`。  
4. 知识库「标核心」、删文档与敏感修改审计补进 W10。
5. F-ST-02 报告侧 TTFT/TPOT 补进 W15。

### A.4 与总计划日历

M0–H 周次与日期与总计划第 1.3 / 第 4 节一致。门禁脚本一致。红线一致。

---

## 11. 实时 API 接入实施清单（V1.3）

本节把原型审计结论转换为 Vue 实施任务。它是第 3 节“契约”的落地顺序：先让失败可见、再替换 Mock、最后做完整业务页；不以“页面有示例数据”作为完成标准。

### 11.1 数据分层与代码责任

| 层 | 前端位置 | 内容 | 规则 |
| --- | --- | --- | --- |
| 静态配置 | `constants/`、路由、UI token、表头、枚举 | 不随用户/任务变化的显示配置 | 不得存任务、报告、用户、KPI 或接口示例实体 |
| API 类型与请求 | `api/http.ts`、`api/*.ts`、`types/` | API V1.3 的请求、响应、错误、分页类型 | 所有业务请求只能从此层发出；`credentials: include` |
| Store/Query 缓存 | `stores/` 或 Vue Query | 最近一次真实响应、loading/error/stale 状态 | 初始为空；写成功后失效并重取，不能以内置样本补空 |
| Mock | `mocks/`（MSW 或等价 adapter） | 与 API V1.3 同 schema 的固定夹具 | 仅 `VITE_DATA_MODE=mock`；构建/顶栏必须显示 Mock |

原型 `assets/app.js` 的 `MOCK_SEED`、`assets/api.js` 的 `?data=mock` 是上述划分的验证样例。生产 Vue 代码不得复制其业务样本到 store。

### 11.2 M0：先交付可观测请求层（W1）

| 编号 | 工作项 | 输入/输出 | 验收 |
| --- | --- | --- |
| FE-API-01 | 建 `http.ts`、`ApiError`、JSON/FormData/Blob 三分支 | 输入 API §1；输出统一 `request<T>` | 401/403/4xx/5xx/network 均保留 `code/status/fields`，无自动 Mock 回退 |
| FE-API-02 | 建运行配置 | `VITE_API_BASE`、`VITE_DATA_MODE`、开发反代 | 默认 `live`；CI build 禁止把 `mock` 设为默认 |
| FE-API-03 | 定义共享 DTO 与 Zod/TS 校验 | list envelope、Error、TaskSpec、WS event | `TaskSpec` 同时供 ConfirmCard 和表单；类型断言不能吞未知必填字段 |
| FE-API-04 | 加全局 SourceBadge、Loading/Error/Empty 边界 | AppShell、路由页 | 断网时明确报接口/错误码；不显示示例 KPI 或报告 |
| FE-API-05 | 为 API adapter 写 MSW 夹具和契约测试 | 登录、列表、写、上传、WS event fixture | Mock 与 live 使用同一 API service 函数；切换模式无页面分支 |

### 11.3 页面替换顺序与接口清单

| 阶段 | 页面/Store | 首批读接口 | 首批写接口 | UI 完成条件 |
| --- | --- | --- | --- |
| M1 W2 | auth、member、profiles、settings | me/users/profiles/settings | login、change-password、profile CRUD/check | 刷新身份、密钥不回显、字段错误定位至表单 |
| M1 W4–W5 | sessions、agent、tasks | sessions/messages、profiles、tasks | create session、TaskSpec、cancel/rerun | 确认卡只提交后端返回的 schema；WS 重连从 `last_event_id` 补发 |
| M1 W5 | dispatch | overview/workers/queued tasks | dispatch config | 拓扑、队列、容量仅由响应驱动；无 Worker 时显示空态 |
| M2 W6–W9 | datasets、cases、reports | datasets/rows、case-sets、reports/samples | upload/save rows、case confirm/map、share/baseline | 编辑保存后 `invalidate`；报告不存在时只显示空/错误态 |
| M3 W10–W12 | kb、gold QA、RAG report | kb/documents/gold-qa、report | 文档/QA 上传、query | query 结果与返回 doc ID 一一对应；无 ID 样本的指标说明来自 API |
| M4 W13–W15 | stress settings、series、notify | whitelist/usage/settings/stress-series | whitelist、settings、approve-stress | 图表只用 series，绝不从 WS progress 拼曲线；prod 未会签只呈 queued |

### 11.4 每个接口页面的联调动作

1. 先在浏览器 Network 中确认请求 URL、Cookie、请求体、响应 schema 与 API V1.3 一致。
2. 对每一个列表做空、分页、401、403、500 五种状态；图表不得用硬编码数列兜底。
3. 每一个写操作必须覆盖成功、`VALIDATION.fields`、重复点击、刷新后回读四种情形。
4. 上传操作覆盖 FormData、20MB 限制、服务端异步处理中/失败、重新拉取版本。
5. WS 覆盖短票失败、网络断开、事件重放、重复 event_id 去重；不新增未契约化事件名。

### 11.5 前端联调门禁

| 门禁 | 必须提供的证据 |
| --- | --- |
| M1 | 浏览器 HAR：login/me、profiles、sessions、WS 短票；录像显示 API 故障页而非 Mock 数据 |
| M2 | JSONL 上传后 rows 回读、TaskSpec 下单、报告/样本读取、基线和分享链接的自动化测试 |
| M3 | 文档上传到 query 回答的完整链路；Golden QA 版本变更后指标刷新 |
| M4 | 白名单/会签负例、stress-series 图表、断线后最终任务状态一致 |

未通过任一门禁时，相关页面只能标记“Mock 已验收”，不得标记“API 已接入”。

### 11.6 本次原型复查新增的逐页落地项

| 编号 | 页面 | 实施项 | API/验收 |
| --- | --- | --- | --- |
| FE-API-06 | Agent | 附件先上传为 `file_id`；会话历史 REST 回放；消息、工具、确认、进度、报告仅消费 WS 固定事件 | `/files`、`/sessions/{id}/messages`、`ws/agent`；服务端无事件时不得浏览器生成任务成功/进度 |
| FE-API-07 | 数据集/用例 | 行与用例候选统一为“API 返回 → 用户采纳 → 保存”三段；编辑后写回并刷新 | datasets rows/ai-generate，case-sets ai-generate/create/cases；生成接口只返回候选，不暗写业务数据 |
| FE-API-08 | KB | 文档列表、切块预览、Query 指标和召回都由接口响应驱动 | documents、chunks、query；生产模式没有投影接口时显示说明，不画样本散点 |
| FE-API-09 | 调度 | Worker/队列只轮询服务端；浏览器不得随机入队、分配或完成任务 | overview/workers/tasks；注册和节点治理分别 POST/PUT worker；手动造队列只允许 Mock |
| FE-API-10 | Mock 隔离 | 所有示例实体移到 `mocks/`，以显式开关加载 | 代码审查搜索 `Math.random`、`setTimeout`、固定业务 ID；live 分支不得用于生成业务结果 |

### 11.7 原型逐页还原矩阵（V1.3，开发排期的验收基线）

本矩阵以 `Web-Prototype/` 的页面结构为视觉与交互基线，以 API V1.3 为数据唯一来源。这里的“还原”不是复刻示例数字：首次加载、刷新、空态、权限失败和写后回读必须都呈现同一组区域。页面尚无可用后端能力时，只能显示明确的禁用/说明，不得补画样本实体。

| 页面 | 必须还原的原型区域与状态 | 前端交付 / 里程碑 | 数据、写入与验收 |
| --- | --- | --- | --- |
| 全局 Shell | 左侧模块导航、顶栏身份/数据模式、主题、统一 Empty/Error/Loading | M1 W2；抽成 `AppShell`、`DataState`、`ApiErrorStrip` | live 初始 store 为空；401 回登录；每页 Network 可见真实请求，数据源标识不得伪装为实时 |
| Agent | 会话轨、对话流、Thought/Tool/Confirm/Progress/Report 卡、附件、迷你调度轨 | M1 W4–W5；REST 回放 + WS 增量，迷你轨只读复用 dispatch query | sessions/messages、files、WS；刷新后同一 session 与 task 可恢复；无事件时不生成工具调用或进度 |
| 调度中心 | KPI、健康雷达、策略/容量、Queue→Worker 拓扑、节点治理、分配日志 | M1 W5；`dispatchStore` 以 5s 轮询聚合，不在浏览器派单 | overview/workers/queued tasks/dispatch events/config；无 Worker、无队列、Worker down、更新失败均有独立状态；节点状态变更后重取 |
| 任务中心 | 24h 状态趋势、筛选表、详情事件、诊断区、去调度入口 | M1 W4；列表与摘要分开 query，详情抽屉复用任务事件 | tasks、task summary、task events；取消仅创建者可提交；筛选/刷新/重跑后 ID 与终态均服务端回读 |
| 数据集工作台 | 目录树、数据集卡片、行内编辑网格、待补全数、自定义列、AI 候选确认、导入/导出/发起评测 | M2 W6、W9；目录/列定义存入资源，候选停在本地 draft，提交才失效重取 | dataset folders、datasets、rows、AI generate、upload；刷新后目录、列和编辑值不丢；候选不进入评分分母或版本，直至用户保存 |
| 用例工作台 | 目录树、策略分布、可编辑用例表、自定义列、自检/72h、目标映射、候选确认、导出 | M2 W8–W9；映射目标由服务端列表驱动，倒计时用 `expires_at` | case folders、case sets/cases、confirm/cancel/map/export、AI generate；确认前不落正式目标；超时/拒绝后清晰显示 cancelled |
| 报告中心 | Benchmark 雷达、RAG 指标、压测曲线、样本表、基线差异、分享/导出、对话解读入口 | M2 W7，RAG/Judge 在 M3，压测曲线/解读在 M4 | reports、samples、stress-series；报告类型由 `kind` 决定；缺少对应报告段时显示空说明，不能显示另一类静态图 |
| KB | 三栏（库/文档与切块/查询）、四模式检索、召回/指标、Golden QA、Rerank 对照区域 | M3 W10–W12；文档与 chunks 使用分页 query，检索结果按返回 doc/chunk ID 标识 | kb/documents/chunks/query/gold-qa；投影散点与 rerank 实验只在 capability=true 时渲染；V1.0 未提供 capability 时保留区域说明，禁止本地样本散点 |
| 协议档与智能体 | 四 Tab 壳：协议档、MCP 工具、技能、运行时；探活与敏感字段掩码 | M1 W3；协议档/运行时为可编辑，工具清单为服务端受控只读 | profiles/check、mcp tools、settings；V1.0 不接入外部 MCP Server 或自定义 System Prompt 写入，相关原型操作显示“未纳入 PRD V1.0”，不得假成功 |
| 压测治理 | 7 日 QPS、白名单、容量/预算阈值、用量、通知开关 | M4 W14–W15；图表仅消费 usage/series，写后重取 | admin stress settings/whitelist/usage；`/metrics` 不由浏览器调用；无白名单和未会签均维持 queued |
| 成员与账号 | KPI、成员表、登录活动、审计抽屉、开户/停用/改密 | M1 W2；普通账号与安全审计数据分区加载 | users、member audit logs、activity summary；单一 `member` 不展示改角色控件；异地登录 AI 判断无 API 前只显示“能力未启用” |

### 11.8 原型还原的前端门禁

1. 每页至少录制一次 live 模式的“首次读 → 写 → 刷新回读”证据；目录、列定义、倒计时、拓扑与图表不接受页面内变量作为事实来源。
2. 逐页比对上表区域：若 V1.0 不做某能力，区域必须保留位置并展示受控说明；不得以 Mock 卡片、曲线或候选替代。
3. Playwright 覆盖 Agent、调度、数据集、用例、KB、报告六条主链；截图同时显示数据源标识、空/错态与关键写后状态。
4. 合入前由前后端共同签署“页面—接口—持久化—验收”四列；少任意一列，页面只能标为“结构已还原”，不能标为“真实联调完成”。

