# AI 测试与评估平台 — API 契约

> ⚠️ **文档维护提示（2026-09-11）**：本文部分章节含历史实现引用（`agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除，ReAct / Plan-Solve 图已由 AgentLoop v2 取代）；当前实现与契约以 `AGENTS.md` 状态地图及本文最新修订为准。

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V2.17 |
| 本轮审查日期 | 2026-09-18（Responses 终态完整性审查修复） |
| WS v2 修订日期 | 2026-09-13（§4A，模型错误安全摘要） |
| 对应 PRD | V1.38（功能唯一权威） |
| 对应设计规范 | V1.12（错误码文案、确认卡字段名、调度中心规范） |
| 对应 Agent 说明书 | `AI测试与评估平台-Agent开发文档.md` V1.7.8（AgentLoop 单入口；JSON 仍以本文为准） |
| 对应前端计划 | AgentLoop 前端计划 V0.5 |
| 对应后端计划 | V1.5 |
| 撰写日期 | 2026-08-18 |
| 本轮修订 | 2026-09-16：V2.9 落地准备阶段三类专家、固定版本成果引用、正文校验及前端成果投影。J1 完整修订链、正式资产/报告引用和 J2/J3 仍未实现。 |
| 最近修订 | 2026-09-03：V1.67 混合引擎执行落地（H2 Workflow DAG / H3 Agent TAOR）：恢复持久事件 `tool_call` / `tool_result`（payload 见 §4.3，ToolCard 只渲染脱敏摘要，观察全文不进任何事件）；`response.completed` 的 `engine` 从「分流结论」升级为「真实执行引擎」——`workflow`（H2，W0–W7 硬编码 DAG）与 `agent`（H3，plan→discover→orchestrator⇄tools 单图内 TAOR）均已真实执行，`agent_id` 审计随 Worker 目录（§3.6.3）供归属核验；`thought` / `tool_progress` / `tool_output_delta` / `confirm` / `clarify` 仍不产生。历史 `ws_events` 中的旧工具事件仍不重放。 |2026-09-03：V1.66 混合引擎 H1 Router 审计契约：`response.completed` payload 新增可选 `engine` / `router_confidence` / `router_reason`（仅 `hybrid_engine_enabled=true` 时出现，旧客户端忽略未知字段即可）；新增 `GET /api/agents` Worker 只读目录（§3.6.3）。本版不新增 WS 事件名、不恢复 `thought` / `tool_*`；`workflow` / `agent` 引擎在 H1 阶段降级按 `chat` 执行，`engine` 如实记录分流结论并经 `router_reason` 标注降级。2026-09-02：V1.65 工具契约加固（T1–T3）：JSON Schema 子集新增 `minItems`/`maxItems` 并为 8 处数组参数补上限；`output_schema` 从装饰字段升级为强制契约（注册期拒绝未声明，运行期按声明比对展示投影）；`platform.tasks` 三工具补全 `output_schema`；移除 `/api/mcp/tools/{name}/code` 端点与 `code_snippet` 字段。2026-08-28：V1.53 `web_fetch` 直抓路径接入 trafilatura 正文提取：可读性算法识别文章主体，保留标题层级/链接/图片/表格，未安装或提取失败降级回内置 `_TextExtractor`；提取真实产出 Markdown 时才声明 `format=markdown`（§4.3.1）。V1.52 优化 `web_fetch` 长文完整性与卡片预览：模型正文预算 8,000→60,000 字符，卡片预览与 `read` 同源对齐 `TOOL_PREVIEW_MAX_CHARS` 并随 `web.preview_limit_chars` 下发，直接抓取字节窗口 256KB→1MB（§4.3.1）。2026-08-27：V1.51 新增持久事件 `session_title`（§4.3）与会话标题 AI 生成契约（§4.3.2）：默认标题会话首条消息后由 Agent 协议档弱结构化生成标题并落库广播，修复标题不持久化问题。V1.50 统一 Agent 文本附件 staging 与 `read` 的 20MB 边界；`read` 模型窗口为 2,000 行 / 600,000 字符。V1.49 协议档新增 `max_output_tokens`（256–131072，默认 8192），创建/更新/列表/详情均支持；Agent 模型调用从协议档读取输出上限，长文档总结/导出类任务可调大避免回答被截断。2026-08-26：V1.48 同轮多调用默认串行，灰度开启后仅 `read`/`web_search`/`web_fetch` 可并行，回填按原始 `call_id`。V1.47 新增 `GET /api/agent/metrics`，不含正文/参数，不新增 WS 事件。V1.46 明确 native 一次 ToolCall 结束当前上游响应，结果回填后再请求，不新增事件名。V1.45 思考链只下发可展示摘要，隐藏 CoT（`Here's a thinking process` / `Analyze User Input`）由服务端替换，不原样推给前端。V1.44 ToolCall 在执行前持久化，新增瞬态 `tool_progress` / `tool_output_delta`，并冻结原生工具的输出 Schema、权限边界和失败恢复字段。V1.43 思考增量允许合并下发；有思考链时 `think_final` 在 `response.completed` 之前。V1.42 Direct `/help`、未知斜杠与图内防御提示在业务事件后必须再发 `response.completed`（成功 `stop`，校验/防御 `error`），结束整轮生成态。V1.41 确认卡预填与 `confirm_ack` 入队前丢掉已删除的协议档/数据集/知识库 ID，避免 Worker 再报「协议档不存在或已删除」。V1.40 `/cancel` 与 `/stress` 按 §4.4 解禁（仍走 `user_message`）：`/cancel` 取消本会话非终态任务，`/stress` 发出质量任务确认卡且 `with_stress=true`，禁止 `kind=stress`。V1.39 原生工具卡片收起态副标题统一为 `ToolCall`，不在卡片摘要区回显文件路径、命令或写入内容；详细参数仍在展开区展示。V1.38 明确原生基础 ToolCall 卡片使用英文工具名，展开区统一显示 `ToolCall` 与 `输出`，文件、命令和代码/文档结果使用行号展示；MCP/平台短工具仍按下方中文名映射。2026-08-24：V1.24 修复 Agent 附件上下文链路：服务端校验文件归属并在模型窗口解析文本、PDF、DOCX、XLSX，图片按三协议图文内容块发送；历史消息附件补齐安全元数据，前端可在刷新后继续预览。同步调整输入框内附件按钮与用户消息附件位序。V1.23 扩展 Agent 附件契约，支持图片、Word 文档与多附件拖拽上传；保留 `POST /api/files` 后再以既有 `file_id` 引用的消息链路，补充图片缩略图、PDF/文本预览与 Office 文件打开/下载说明。V1.22 修复 V1.21 遗留：§4.4 标题「仅此三条」改「仅此四条」、§9 禁止清单「第四种」改「第五种」并补四类上行事件枚举、§4.3 `tool_result.source` 语义对齐 M7 `Observation.source`（溯源标识字符串，非 short\|long 枚举）、§4.3 共享流规则补 clarify/plan/confirm 持久化广播说明、§4.4 clarify 多副本限制注明、§9 Ask/Plan 补注非 Harness plan 事件；V1.20 及更早版本沿用历史修订记录。 |
| 适用范围 | V1.0：浏览器 `web/` ↔ `api`；全域 REST + WS 接口规范 |

> V1.86（2026-09-09）：协议档页面 `POST /api/profiles/{id}/check` 的真实 ping 探活上限与通用协议调用统一为 30 秒，避免上游模型冷启动被误判为不可用；响应字段与错误码不变。

> V2.3（2026-09-15）：补齐 Anthropic Messages 兼容供应商的受控思考模板：Kimi K3 使用 `output_config.effort`（`low/high/max`，无 `off`），智谱 GLM 与火山方舟豆包使用 `thinking.type=enabled/disabled` 开关。兼容供应商的无签名 thinking 块可原样回放，原生 Claude 仍要求签名。新模板全部必须经探测同时验证请求完成与思考证据，不能因目录出现就宣称模型支持。

> V2.4（2026-09-15）：供应商快速填充以“供应商 + 协议”为联合键，协议切换同步替换官方 Base URL、建议模型与思考模板。DeepSeek 原厂 Anthropic 使用 `/anthropic` 和 `thinking + output_config.effort`；NVIDIA NIM 的 `/v1/messages` 使用实际部署根地址，不伪造统一公网入口。未公布兼容层的组合仅在官方快速填充中禁用，已有自建兼容网关仍可编辑和真实探测。

> V2.1（2026-09-15，历史记录；模型族限制及超时口径已由 V2.2 替代）：思考模板候选和保存校验新增模型 ID 维度，百炼 DeepSeek 与千问等同端点不同方言不会混用。开启思考的探测必须取得 reasoning 增量或推理用量证据，普通文本完成不再视为通过；各档短请求并发执行，整次探测受单次 30 秒调用超时约束。

> V2.0（2026-09-15）：协议档新模型改为“供应商模板 → 真实验证 → 保存”链路（§3.6）。`GET /api/profiles/reasoning-templates` 返回受控模板目录；`POST /api/profiles/probe-create` 与 `POST /api/profiles/{id}/probe-update` 分别验证后创建、验证后原子更新。探测结果只保存通过档位与安全错误分类，AgentLoop 仅放行这些档位；旧协议档继续使用 legacy 解析。

> V1.89（2026-09-10）：Agent 专家（Expert）选择与附件工作区落地。`turn.submit.data` 新增可选 `agent_id`（专家 ID；缺省或未知值回落默认专家 `general`，服务端按回合解析，不新增会话列）。`GET /api/sessions/agent-ui`（草稿与会话态）响应增量 `agent`（当前选中专家 ID——已有会话按最近一轮 `user/message` 事实的 `extensions.expert_id` 记忆，无记录回落默认）与 `agents[]`（`id,name,description,badge,default` 投影，**不返回**专家提示词与工具视野）。专家为产品内置角色、随代码分发：`general`（默认，无附加提示词、平台全量工具白名单，行为与 V1.88 一致）与 `testcase-agent`（测试用例设计专家：专属提示词 + 工具视野收窄为 `read/write/edit/bash/ask_user_question`）。提示词按「核心 → 专家 → 协议档补充提示词」顺序注入 system 段（专家段 `cacheable=false`，读取时同样拒绝疑似密钥与接管性措辞）；专家声明工具与平台白名单**取交集**（只收窄不扩大，交集为空 fail-closed）；专家不改变权限、错误契约与任务状态机。`user/message` 事实 `extensions` 增量 `expert_id`（审计与跨端一致选择，不参与幂等摘要）。附件落地：`turn.submit` 的文本附件（`.md/.txt/.html/.json/.yaml/.yml/.csv/.jsonl`）随回合 staging 进**会话沙箱根**（与 read/bash 注入根同源），模型收到 `attachments/{file_id}-{name}` 相对路径清单并用 read 读取；行态失效/目录不可得时回退内联注入（与 V1.88 行为一致）。AGENTS.md V2.0 登记的「附件 staging 仍 legacy」在 agent_loop_v2 主链路随之解除。

> V1.93（2026-09-11）：不新增浏览器 WS 字段。AgentLoop 的 `task.create`、`task.status`、`task.cancel` 统一以注册表短名作为权限、Schema 与 MCP 路由事实源；模型请求继续使用无点号的安全 Function Calling 名 `platform_task_create/status/cancel`。调度器仅兼容这三个安全 wire 名、短名和已登记 MCP 全名 `platform.tasks.task.create/status/cancel`，未知前缀一律按未知工具拒绝。三种名称均引用同一 `ToolDef.parameters_schema` JSON Schema（根对象 `additionalProperties=false`），调用事实保留实际 wire 名，同时以 `registry_name` 记录短名，确保轨迹与审计可追溯而不复制字段定义。

> V1.96（2026-09-12）：`question.respond.answers[]` 增加可选 `custom:string<=16000`。`answer` 继续承载 radio 的已选标签或 checkbox 的标签数组，`custom` 单独承载“其他，请填写”的文本；checkbox 可以同时提交已登记标签和自定义文本。服务端仍复用问题 ID、题型、给定选项、必答和交互身份校验，custom 不会伪装成未登记选项；省略 custom 的旧客户端保持原行为。

> V1.97（2026-09-12）：新增受控媒体 MCP 配置 `GET/PUT /api/mcp/media-config`（§3.6.1）：固定 Compose 私网 Streamable HTTP 服务，密钥只写不回显，配置保存写审计 `media_mcp_config_update`；媒体工具目录仅在启用后显示，健康检查真实执行 `initialize → tools/list`，不产生收费内容。视频工具本期仅提交/查询上游任务，不新增浏览器 WS 或平台媒体任务。

> V1.95（2026-09-11）：AgentLoop 原生 `task` 对齐 DeepSeek Harness 的 `todo_write`：它是当前 Agent 会话独占的整表规划工具，与 Worker 队列 `task.create/status/cancel` 严格分离。输入 Schema 为根对象 `additionalProperties=false`，必填 `description` 与 `steps`，每个步骤必填 `title`、`status`（`pending|in_progress|completed`），`steps` 为 1–12 项且顺序执行时最多一项 `in_progress`；每次调用整体替换上一份清单。仅成功的 `task` 与对应 `tool.result` 同事务写入 `task_plan.updated:{plan:{goal,description,steps,counts}}` 持久投影；失败调用、工具调用草稿和旧 `tool.display.task` 都不能改变当前抽屉。重连按该事件回放，简单单步任务不调用该工具；不新增长任务、Worker 事件或浏览器上行字段。

> V1.88（2026-09-09）：浏览器 AgentLoop v2 流 schema 升至 `agent-loop-stream.v2.2`，完整事实目录升至 `catalog_version=5`。`assistant.message.data` 新增可选 `latency_ms`，为单次模型流从建立到完成的真实毫秒耗时，不含工具执行；已有 `usage` 继续仅透传上游返回的 `prompt_tokens`、`completion_tokens`、`total_tokens` 与可选缓存 token。前端聚合统计只能使用已持久化的这些字段：上游没有返回缓存 token 时缓存命中率显示未知，不能补零或估算。

> V1.87（2026-09-09）：`assistant.start.data.request_summary.context_meter` 增量 `breakdown`，键为 `system_prompt`、`conversation_messages`、`tools`、`mcp`、`skill`、`memory_files`，均为非负整数估算 token。服务端按本次实际序列化请求拆分，六项和严格等于 `input_tokens`；工具按本轮注册表快照区分原生工具与 MCP。当前请求未注入 Skill 或记忆文件时对应项为 `0`。`reserved_output_tokens` 不在 breakdown 内，前端可作为中性色与输入分项一起计算预计总占用。旧事实没有该字段，前端须保留合并展示并标注其限制。

> V1.78（2026-09-09）：G6b 磁盘配额与终态契约组（F5 §6.6/M-R3-7）+ G6 评审 M1–M3 合并登记（G6a 升档审批主体已随 #235 于 2026-09-08 合入 main，其 `DENIED` 错误码与 `tool_approval` 升档卡语义见本版事件表与错误码表）。**G6b**：新增配置 `workspace_quota_bytes`（默认 1GiB）与 `sandbox_volume_watermark_bytes`（默认 512MiB）——workspace-write 档写前容量检查（卷水位熔断优先于每目录配额，TTL 缓存 du，VALIDATION 码不触发升档链）；`approval_terminal` outcome 成组扩展 `voided`（ack 行锁内检查点预检缺失作废）/`recovery_failed`（resume 恢复失败）。**评审修订**：审批卡终态按卡型归类（M3）——`approval_terminal` payload 新增可选 `card_type`（`"approval"`|`"clarify"`，缺省 `"approval"`——旧事件与旧客户端按缺省解释，无破坏）：`recovery_failed` 对澄清卡恢复失败同样广播并携带 `card_type="clarify"`（`_start_card_resume` 按发起卡型携带，前端按卡型路由 → ClarifyCard 增 `failed` 终态展示）；`expired`/`voided`/`cancelled` 恒为审批卡（payload 均带 `card_type="approval"`）。错误码 `DENIED`（403）口径收敛为 **bash 只读档拒写**——read-only 只约束 bash 持久写（绑定会话内文件工具仍可写，口径见《工作区与沙箱设计方案》§6.1.1），DENIED 文案不指引升档通道（该通道受 `agent_escalation_approval_enabled` 门控）；磁盘配额卷水位核算失败（disk_usage OSError）改为 fail-closed 拒写（§6.6，不静默放行，核算恢复自动放行）。
>
> V1.81（2026-09-09）：不新增 REST 或 WS 字段。`subscribe` 的 attach 阶段在回放前检查持久开放回合：只有成功取得已释放的 PostgreSQL advisory writer lock，才结算硬重启遗留的 `turn.end(reason="interrupted")`；锁仍被存活实例持有时只订阅，不转移控制权或关闭其回合。每回合按所选 Agent 协议档读取已保存的补充提示词，核心提示词优先、补充段不可缓存，并在读取时再次拒绝疑似密钥或接管性内容。`task.create` 的评测档和裁判档使用全员同权协议档目录，`created_by` 仅为审计字段。CI 同时运行三组 Loop PostgreSQL 夹具和 Runner 回归；真实 cgroup v2 进程树取消仍需部署环境验收。
>
> V1.82（2026-09-09，历史；V2.10 已重新加入 Responses，原有删除迁移不回改、不恢复已删除档案）：协议档只接受 `openai_chat` 与 `anthropic_messages`。删除 OpenAI Responses 的请求适配、模型列表分支和前端选项；迁移执行时删除全部 `openai_responses` 档、其受控环境文件变量及历史数据库密文，并清理指向被删除档位的 `settings.agent_profile_id`，避免 Agent 留下失效默认配置。历史任务与报告的快照不改写；新请求携带已删除协议一律返回 `VALIDATION`。
>
> V1.80（2026-09-09）：AgentLoop 成为**唯一新会话引擎**。`POST /api/sessions` 的 `engine_version` 仅接受且默认 `agent_loop_v2`；历史 `legacy` 行仍可读取，但不能借创建或 WS 入口回退。删除 `AGENT_LOOP_ENABLED` 开关，旧 `/ws/agent` 必须显式携带历史会话 ID，否则关闭 4400；新会话只使用 `/ws/agent/v2`。`turn.submit.data` 新增可选 `profile_id`，只能是平台协议档 ID：服务端每回合重新校验 Agent 用途、连接凭据、模型与 `reasoning_effort`，浏览器不能传模型地址、密钥或供应商参数。`agent-ui` 增量 `profiles[]`，并将 `profile` 扩为同形脱敏投影，供输入栏逐回合选择模型和思考强度。
>
> V1.76（2026-09-07）：会话-工作区绑定（《工作区与沙箱设计方案》V0.5 F3/G5）。`POST /api/sessions` 增量可选 `workspace_id`（工作区 uuid）/`scope_path`（工作区内相对子目录，默认根）——绑定在**创建时固化**（运行期不可变、无换绑端点，需换绑 = 删除重建；前端草稿模式在首条消息随 create 携带）；绑定仅限 `visibility="private"`（BLK-4：写授权不随团队可见性开放），工作区须存在、未软删、属主匹配，scope 逐段 realpath 防穿越 + 目标目录自动就绪；失败一律 `VALIDATION` fail-closed。列表项/响应增量 `workspace_id`/`scope_path`/`workspace_name`（`workspace_name` 服务端按行补查，前端仅展示）；`PUT /api/sessions/{id}/sharing` 对 `workspace_id` 非空会话转 `team` → `VALIDATION`。绑定会话的沙箱根（read/write/edit/bash 数据域）由 `resolve_session_sandbox` 唯一解析为工作区 scope（runner 前缀校验面随 G4 已就绪）；未绑定会话行为与 V1.75 逐字节一致（legacy 自动目录）。附件 staging（`attachments/`）仍落 legacy `{root}/{session_id}/attachments/`——绑定会话附件归属迁移留后续评审。审计新增 `session_workspace_bind`（§3.12.3）。无 WS 事件/上行变化。
>
> V1.74（2026-09-07）：上下文压缩事件化（dsh 借鉴与 Agent Harness 改进 #2 首期落地物）。治理「超长上下文精度衰减」遗留项的可观测性：① 超大 `tool_result` 先裁剪——单回合原生工具结果临时存储（`NativeToolResultStore`）写入前按长度上限（与 read 模型窗口同源 600,000 字符）裁剪并追加截断标注，模型只见带标注的截断结果（禁止假装全文在手），未超限行为逐字节不变；② 窗口裁剪事件化留痕——回合装配模型上下文时若发生窗口裁剪（compact `keep_from` 截断或末 20 条尾窗截断），广播持久留痕事件 `context_trim`（payload 仅元信息 reason/dropped/kept/in_scope_total/keep_from_id/limit，不携带被裁消息原文，观察纪律不变；首期不做 LLM 摘要）。`recent_window` / `compact_keep_from` 窗口算法本身与行为默认不变；新增 kind 按 #4 词汇表纪律版本递增至 `event.v4`（§4.3，`backend/shared/event_vocab.py` 同步）。
>
> V1.73（2026-09-07）：审批终态（dsh 借鉴与 Agent Harness 改进 #3）。审批卡不再无限期悬挂：TTL 常量 `agent_approval_ttl_seconds`（config，默认 3600 秒，禁硬编码）——api 侧后台周期扫描对超龄 `tool_approval` 卡在行锁内二次判定后清卡，广播持久终态事件 `approval_terminal`（payload `{approval_id, outcome:"expired"}`）；`/stop` 放弃悬挂审批卡时广播 `outcome:"cancelled"`（与用户 `reject` 语义区分：`rejected` 仍由 `tool_approval_ack(action="reject")` 回执承载，不回执场景的放弃属 cancelled）。失效判定以卡 `meta.created_at`（UTC ISO）+ 当前时间**幂等兜底，不依赖扫描进程存活性**：过期后任意 ack 先判龄拒绝（清卡 + `expired` 终态 + `error`），绝不触发 resume；卡清后重复 ack 走既有「无待审批卡」拒绝。前端 ApprovalCard 对 expired/cancelled 展示失效态、按钮禁操作（回放只读）。新增 kind 按 #4 词汇表纪律版本递增至 `event.v3`（§4.3 词汇表版本段落、`backend/shared/event_vocab.py` 同步）。
>
> V1.72（2026-09-07）：clarify 问答恢复（dsh 借鉴与 Agent Harness 改进 #1，PRD 契约转正）。`clarify` / `clarify_reply` 自 V1.63 移除、V1.70 标注「待评审恢复」后正式转正：澄清卡由 `engine="agent"` 的 `ask_user_question` 图内 `interrupt()` 产出（≤8 题 radio/checkbox/text 一次作答），卡存储与审批卡同构（B 路线）——落 `sessions.pending_confirm` 单行（`meta.confirm_type="clarify"` + 一次性 `resume_nonce`），三类卡共用行锁互斥；`clarify_reply` 上行 payload 定稿多题结构 `{id, answers:[{id, selected?, custom?}]}`（按行投影的旧单文本结构不再接受）；服务端行锁清卡后以原 `thread_id` 的 `Command(resume={id, answers})` 恢复 ToolNode，resume 至多一次。新增持久回执事件 `clarify_ack`（`{ok:true,id}`，前端乐观盖章、回放一致）；按 #4 词汇表演进纪律**新增 kind → `vocab_version` 递增至 `event.v2`**（词汇表单一事实源同步，见 §4.3）。§9 红线措辞同步为「以 §4.3/§4.4 现行清单为准 + 契约评审」；与 `confirm`（W5）/`tool_approval`（H5）路径零影响的卡互斥回归为合入门槛。
>
> V1.71（2026-09-07）：事件词汇表版本化（dsh 借鉴与 Agent Harness 改进 #4，护栏前置）。§4.2 公共头增补可选 `vocab_version` 字段（取值 `event.v1`，服务端恒发；旧客户端按「忽略未知字段」原则无需改动）；§4.3 明确词汇表版本语义与演进纪律——**增删持久事件 kind 必须递增版本**（`event.v1` → `event.v2` …），演进理由随本节修订记录留档。词汇表单一事实源为 `backend/shared/event_vocab.py`（api/worker 共用，禁止第三份碎片集合）：`PERSISTENT_KINDS` 覆盖 §4.3 现行事件与 api/worker 直产事件（含 `confirm_ack` / `tool_approval_ack` / `task_cancelled` / `session_title`），`NODE_EVENT_KINDS` 为图节点可经 `pending_events` 产出的子集。三条路径护栏：api 图内翻译层对未契约 kind fail-closed（拒绝落库广播）、对版本漂移仅告警并按当前词汇表翻译；api 与 Worker 落库 payload 均内嵌 `event_version` 保留字段（转发/回放剥离，不回显前端；免 `ws_events` 加列/Alembic）；api `_forward_loop` 转发校验——未知 kind / 版本不符按新开关 `event_vocab_strict` 处理：默认 `false` 告警并跳过（灰度），`true` fail-closed 拒收并落 `error`。历史 `ws_events` 无版本行按当前版本解释（只读兼容，不做跨大版本迁移机制）。
>
> V1.70（2026-09-03）：混合引擎 H5 持久化 HITL 批次 1。恢复 `tool_approval`（服务→前端，持久化）与 `tool_approval_ack`（前端→服务，恢复回执）为现行事件。危险 bash 在执行副作用前由图内 `interrupt()` 暂停：ToolCall 已落库后浏览器收到持久化 `tool_approval` 卡，原发起成员可 `approve|reject`；服务端在 `sessions.pending_confirm` 行锁事务内校验 owner/卡种/`id`/action 后清卡提交，再以原中断回合的 `thread_id` 经 `Command(resume=...)` 恢复 ToolNode（resume 至多一次，重复/并发 ack 拒绝且不改变状态）。审批卡 JSONB 带 `meta`：`schema_version=1`、`confirm_type="tool_approval"`、`thread_id`、一次性 `resume_nonce`、`owner_id`、`created_at`；广播 `tool_approval` 事件时剥离 `meta`（前端只见白名单字段）。确认前与拒绝后均不得调用 Runner。该暂停状态与 `clarify` 同为单 API 副本/按 `session_id` 粘性路由前提；`PgCheckpointer` 生产切换、网关粘性路由落地与重启恢复演练属批次 2（未完成前 `worker.sandbox` 的 `bash` 仍不可被 discover 选中，下表 §4.3.1 保留为受控基础设施）。`tool_approval_ack` 上行 payload 为 `{id, action:"approve"|"reject"}`，`id` 必须匹配最近一张待审批卡且仅命令原发起成员可提交；服务端回执 `tool_approval_ack` 持久化事件 payload 为 `{action, approval_id}`。
>
> V1.69（2026-09-03）：混合引擎 H1/H2 审查修复。Workflow 执行动作门禁先排除「什么是 / 如何 / 讲讲」等概念问答，避免动词误发确认卡；只读准备动作仍走 Agent。明确「先评后压 / 成功后压测」时，Router 直接进入 Workflow，W0 归一为 benchmark/rag 质量技能，W4 写 `with_stress=true`，压测仍由 Worker 在成功后派生。`router.v1` 的已启用 `skill_id` 写入 State 并由 W0 直接采用；W1 只提取明确平台短 ID，W4 仅合并白名单槽位。确认 `ok=true` 先抢占会话回合租约，再校验和清卡；**仅** W6 产出真实任务 ID 时发送 `{ok:true,task_id:"uuid",message}`。未入队时恢复同一张 `pending_confirm` 并发既有 `error`，不发送伪成功或 `ok=false` 取消回执；未新增 WS 事件或字段。
>
> V1.68（2026-09-03）：混合引擎 Workflow 确认卡恢复（H2 批次 2）。`confirm`（TaskSpec §5 + 非 TaskSpec 元数据 `confirm_author:{id,username,display_name?}`）与 `confirm_ack`（`{ok,task_id?,message}`）两事件自 V1.63 移除后恢复，语义与 V1.62 一致；产出来源改为 Workflow 子图 W5 `await_confirm`（仅 `hybrid_engine_enabled=true` 且 Router 判定 `engine=workflow` 时可达）。八节点硬编码顺序：`select_skill → prepare_slots → load_skill → validate_gates → build_task_spec → await_confirm → enqueue → summarize`，节点失败就地收尾、不回环。W5 首次到达时**发卡并收尾本轮**（`confirm` + 阶段叙述 + `response.completed(stop)`）；用户确认后服务端在同一 `pending_confirm` 行锁事务内完成 owner 校验、并发检测、patch 深合并、TaskSpec 同源校验与清卡，再以 `workflow_confirm` 注入重放回合，由 **W6 唯一入队**、W7 收尾，`confirm_ack` 携带 W6 写入的真实 `task_id`。未批准/取消只清卡不入队；重复确认或无待确认卡返回 `VALIDATION`（「无待确认卡」），并发已处理为 `CONCURRENCY`，绝不重复入队。`skill-rag` 未接入仍 `VALIDATION` fail-closed，绝不 mock `succeeded`。主开关关闭时全部行为与 V1.66 一致。
>
> V1.66（2026-09-03）：混合引擎 H1（Router 四路分流骨架）审计契约。`response.completed` payload 在混合引擎开启时新增三个可选字段：`engine`（`"direct"|"chat"|"workflow"|"agent"`，Router 分流结论，写入后本轮不可变）、`router_confidence`（0–1 浮点，L0 确定性置信度）、`router_reason`（脱敏分流理由，含降级标注）。`hybrid_engine_enabled=false`（默认）时 payload 与 V1.65 完全一致。L0 为纯函数零模型调用（可复现性 100%）；仅当置信度低于 `hybrid_router_confidence_threshold`（默认 0.7）且 `hybrid_router_cot_enabled=true` 时触发一次 L1 短调用（`router.v1` JSON，计入回合预算），任何失败均回落 L0、L0 无结论回落 `chat`。H1 阶段 `workflow` / `agent` 尚未实现，降级按 `chat` 执行并在 `router_reason` 标注；`direct` 仅承认收包循环既有 `/stop`（图内其余斜杠为防御性拒绝，`finish_reason="error"`，零模型调用）。新增 `GET /api/agents` Worker 只读目录（§3.6.3，登录可见，不含密钥与模型实例）。`engine` 审计为 O2 分流判错信号（立即 `/stop`、`clarify`、门禁失败、重规划计数）的唯一采集载体，信号仅用于样本筛选，不得直接充当阈值优化目标。
>
> V1.65（2026-09-02）：工具契约加固（T1–T3）。T1：JSON Schema 受限子集新增 `minItems`/`maxItems`（注册期与运行期均校验），并为 `web_search.include_domains/exclude_domains`、`web_fetch.allowed_domains/blocked_domains`、`task.steps/tools`、`ask_user_question.questions/options`、`task.create.profile_ids/rag_mode` 等 8 处数组参数补上限。T2：`output_schema` 从装饰字段升级为强制契约——`ToolDef.output_schema` 默认 `None`（未声明）注册期拒绝，显式 `{}` 表示无结构化投影（合法，运行期跳过比对）；`execute_raw` 运行期按声明比对 handler 原始返回的展示投影，失败归一 `INTERNAL` 且不外泄原始返回；`platform.tasks.task.create/status/cancel` 补全 `output_schema`。T3：移除 `GET /api/mcp/tools/{name}/code` 端点与所有 `code_snippet` 字段（后端 `TOOL_METADATA_EXT`、前端 `ToolCodeDetails`/mock/Modal）——原实现为手写示意代码且与真实 handler 不符，违反「禁止伪造」红线；前端「源码实现」Tab 改为引导查看仓库真实文件。
>
> V1.64（2026-09-02）：`cancel_task` 的成功回执为持久化 `task_cancelled`，不再复用已移除的 `tool_result`；payload 为 `{status:"cancelled",kind}`，公共头携带 `task_id`。`task.create` 即使由内部 MCP 触发，也必须通过与 REST 相同的 TaskSpec 校验。
>
> V1.63（2026-09-02）：**Agent 骨架化（breaking）**。Agent 图收敛为单节点纯对话（`START → chat_stream → END`），以下内容整体移除：`thought` / `tool_call` / `tool_progress` / `tool_output_delta` / `tool_result` / `tool_approval` / `tool_approval_ack` / `clarify` / `plan` / `task_state` / `confirm` / `confirm_ack` 事件，`/help` `/compact` `/cancel` `/stress` 斜杠，`/api/slash-commands` 接口，自定义斜杠。下行事件仅保留 `user_message` / `assistant_delta` / `assistant_message` / `response.completed` / `progress` / `report` / `task_cancelled` / `session_title` / `error` / `pong`；上行仅 `user_message` / `cancel_task`（`/stop` 以 `user_message` 文本上行）。历史 `ws_events` 中的旧事件不再渲染（§4.3 事件表标注保留历史兼容，但 Agent 图不再产生）。
>
> V1.62（2026-08-31）：危险 bash 的确认卡以 Composer 上方抽屉呈现，点击确认或取消立即收回；消息流仅显示关联 ToolCard 的等待状态。
>
> V1.61（2026-08-31）：界面只呈现可验证的执行过程：Plan 使用 PlanCard，工具使用 ToolCard，危险 bash 使用确认卡；JSON ReAct `thought`、Plan/Reflect 阶段事件与 ToolCall 前模型草稿一律是内部控制信息。服务端每回合至多发一条固定过程摘要，前端不重放历史 `thought`，`assistant_message` 仅保留工具终态之后的最终交付，避免思考卡堆积和“先报成功、后报工具失败”的矛盾。
>
> V1.60（2026-08-31）：危险 bash 采用 LangGraph `interrupt()` 人在回路：先持久化 `tool_approval` 卡，再由原发起成员上行 `tool_approval_ack` 的 `approve|reject` 恢复同一 `thread_id`。确认前绝不调用 Runner；`sudo`、网络和远程连接仍是硬黑名单。任意上游 reasoning（包括中文）只投影固定过程摘要，工具调用轮次在确认无 ToolCall 前不投影模型正文，禁止出现先报“已完成”后工具失败的矛盾。
>
> V1.59（2026-08-30）：§3.6 的模型目录接口保留上游声明的可选 `parameters`（字段 ID 与可选值）。CursorAPI 等将模型参数编码为方括号后缀的网关，前端据此保存 `model[param=value]`；运行时原样传递该模型标识，不附带 OpenAI `reasoning_effort`。这类端点的原生 Function Calling 仍遵循 `tool_call_mode`；是否向流返回可展示 reasoning 以实际 SSE 为准，禁止伪造。
>
> V1.58（2026-08-30）：§3.6.2 新增管理员受控的 Skill 文件预览/编辑与协议档专属补充提示词接口。Skill 目录只读取 `SKILL.md` 固定头部；本轮选中技能后才读取完整工作流。核心安全提示词只读，补充提示词按 Agent 协议档独立保存、审计并在运行时受核心边界约束。
>
> V1.57（2026-08-29）：§3.12.2 补录管理端工作区接口契约。`GET /api/admin/workspaces` 按 §1.1 分页约定（`offset`/`limit`、`{items,total}`）分页返回会话与工作区文件夹摘要，新增 `keyword` / `folder` / `deleted` 过滤参数与整体聚合 `stats`（会话总数 / 有工作区文件数 / 孤立文件夹数），文件夹扫描仅对当前页会话执行；新增 `GET /api/admin/workspaces/stats` 返回全部工作区磁盘总字节（前端后台加载 KPI）。列表响应由全量数组改为分页对象，前端工作区管理页同步改造。
>
> V1.56（2026-08-29）：§3.7 规定 staging 编辑与发布均由非提报成员完成；发布前拒绝缺少 `question/reference` 或冻结 split 的行、同 split 重复和跨 split 泄漏。`support_status=supported` 的 release 必须使用 Worker 已注册的 parser；不新增接口字段或 WS 事件。
>
> V1.55（2026-08-28）：§3.7 实现目录来源/release 的双人复核、独立 `DatasetImport` 作业的 lease 领取/回收、稳定 staging 行 ID 与 optimistic revision 发布；新建 benchmark 任务写入已发布 `dataset_version_id/version_no` 快照，Worker 只读该版本。所有成员同权，但 release 批准/封禁解除和 staging 发布均不得由提报成员本人完成；不新增 WS 事件。
>
> V1.54（2026-08-28）：§3.7 新增公开基准目录、独立 `DatasetImport` 作业与 staging 行契约。`/datasets` 只能选择受审核的目录 release，下载/解析由 Worker 异步执行；未审核 staging 行不得用于确认卡、评测或基线。本版本不新增 WS 事件。
>
> V1.53（2026-08-28）：§4.3.1 `web_fetch` 直抓路径（未配置 Firecrawl）接入 trafilatura（新增依赖，`requirements.txt` 固定 2.2.0）做正文级提取：可读性算法识别文章主体，丢弃导航/页脚/脚本噪声，保留标题层级、链接、图片与表格；未安装或提取失败降级回内置 `_TextExtractor` 全文本展开。提取真实产出 Markdown 时 `format=markdown`，降级路径仍为 `text`。SSRF 校验、受控字节窗口与正文预算不变，不新增 WS 字段。
>
> V1.52（2026-08-28）：§4.3.1 `web_fetch` 长文完整性与卡片预览优化：模型正文预算 8,000→60,000 字符（`web_fetch` 专属，与全局单条工具结果 8,000 解耦，超限仍带 `truncated` 标记）；ToolCard 预览从固定 500 字符改为与 `read` 同源对齐 `TOOL_PREVIEW_MAX_CHARS`，上限随 `web.preview_limit_chars` 下发；直接抓取路径 HTML 字节窗口 256KB→1MB。不新增 WS 事件名。
>
> V1.51（2026-08-27）：§4.3 新增持久事件 `session_title`（`{"title", "source":"ai"}`），§4.3.2 新增会话标题 AI 生成契约：仅默认标题「新会话」在首条用户消息后触发，弱结构化（提示词约定 JSON + 代码侧强校验）生成，失败降级为消息截断且不发事件；标题先落库 `sessions.title` 再广播，不阻塞对话回合。
>
> V1.48（2026-08-26）：§4.3 同轮多个调用默认串行；仅当并行总开关与协议档白名单命中且脚踢线未触发时，`read` / `web_search` / `web_fetch` 可同波并行。`write` / `edit` / `bash` / `task.create` / `task.cancel` 始终串行。模型回填仍按原始 `call_id` 顺序。不新增 WS 字段。
>
> V1.47（2026-08-26）：§3.4 新增 `GET /api/agent/metrics`（进程内交错流/批次度量，不含正文与参数）；不新增 WS 字段，`segment_id` 仍不进入公共契约。
>
> V1.25（2026-08-25）：细化 ReAct `read` 的 `tool_result.data`，新增受控行范围、文件统计与短预览投影。完整 `content` 仅供服务端下一模型回合使用，禁止写入 WebSocket 事件或 ToolCard。
>
> V1.26（2026-08-25）：原生 ToolCall 为既有 `tool_call` / `tool_result` 增加必填 `call_id`，前端必须以该值关联卡片；不新增事件名，不向浏览器暴露上游协议字段或 MCP 连接信息。
>
> V1.27（2026-08-25）：协议档新增 `tool_call_mode`。仅显式选择 `native` 的 Agent 协议档向上游发送 `tools`；`legacy` 固定走严格 JSON-ReAct，禁止根据一次上游 4xx 静默猜测降级。
>
> V1.28（2026-08-25）：工具调用模式默认改为 `legacy`，存量协议档也以兼容模式迁移；只有人工验证支持 Function Calling 后才可显式切换为 `native`。原生 ToolCall 的空/重复 `call_id` 一律归一为 `UPSTREAM`，不进入工具队列。
>
> V1.29（2026-08-25）：§3.6.1 `GET /api/mcp/tools` 从音频/图像占位清单改为**平台 allowlist 内部短工具目录**（6 项：read/write/edit/web_search/web_fetch/bash），`name` 使用唯一 `tool_id`，新增可选 `tool_id`/`server_id`/`short_name`/`display_name`/`risk_level`/`execution_mode`/`timeout_s`/`requires_confirmation`/`supports_streaming` 字段；仅只读展示，不含任何连接命令或凭据。
>
> V1.30（2026-08-25）：§3.6.1 新增 `platform.tasks` 长任务桥接三工具（`task.create`/`task.status`/`task.cancel`），目录 6→9 项、server 4 组。三工具只入 PG 队列或查询，不等待 Worker 终态；`task.create` 直接入队返回 `queued` + `task_id`，会话/用户归属由平台注入（模型不可传）。
>
> V1.31（2026-08-25）：§3.6.1 新增 `GET /api/mcp/metrics`（admin 只读）——内部 MCP Host 的调用度量（按 tool_id 计数/耗时）与服务器熔断状态（按 server_id，INTERNAL/TIMEOUT/UPSTREAM 连续失败超阈值即 open，冷却自动恢复）。任务创建新增每用户活动任务配额 `max_active_tasks_per_user`（默认 5），MCP 与 REST 同一规则，超限返回 `CONCURRENCY` 并写 `task_quota_rejected` 审计。
>
> V1.32（2026-08-25）：基础 `read`、`write`、`edit`、`bash`、`web_search`、`web_fetch` 与对话拆解 `task` 改为模型原生 Function Calling 直连；仅评测任务桥 `platform.tasks` 继续作为 MCP 扩展。新增 Firecrawl 服务端配置、网页抓取安全投影和原子文件写入边界。
>
> V1.33（2026-08-25）：单回合允许多条 `assistant_message`；`response.completed` 仍为整轮结束。可选 `interim=true` 表示阶段叙述（计划/下一步），不是 Observation 原文，不得结束生成态。清单复用 `plan.slots.steps` 与 `task` 的 `tool_result`，不新事件。
>
> V1.37（2026-08-26）：`read` 预览按完整行截取（最多 4000 字符），禁止半行截断；`next_offset` 可作为 `offset` 别名。相同窗口重复 read 只执行一次。
>
> V1.36（2026-08-25）：`GET /api/sessions/{id}/messages.context_meter` 由服务端按窗口消息计算，不再返回 `null`。字段仍为 §3.4 既有形状（`messages`/`window`/`total_tokens`/`max_tokens`/`compacted` 等）；前端只读，禁止按条数自算。
>
> V1.35（2026-08-25）：对话确认卡由 LangGraph `reflect` 在 `delivery=confirm` 时发出（TaskSpec，`kind` 不得为 `stress`）；WS 短票 jti 用 Redis 单次消费；压测由 Worker 下发 stress 容器，曲线仍只走 `GET /api/tasks/{id}/stress-series`。
>
> V1.34（2026-08-25）：原生工具回传模型的单条结果上限统一为 8,000 字符（`read`/`bash`/`web_*` 对齐）；未读完时模型正文携带 `next_offset`。ToolCard 预览与 WS 投影不变。
>
> V1.44（2026-08-26）：ToolCall 在执行前落库，新增 `tool_progress` 与 `tool_output_delta` 瞬态帧；前者表达校验/执行/收尾阶段，后者仅传输服务端受控窗口内的行级输出。它们不落库、不占 `event_id`、不参与断线补发；`tool_result` 仍是唯一持久化终态。原生工具的输出 Schema、权限边界与恢复策略以 §4.3.1 为唯一契约。
>
> V1.45（2026-08-27）：ToolCard 浏览器预览上限改为可配置（环境变量 `TOOL_PREVIEW_MAX_CHARS`），默认 600,000 字符并与 `read` 模型窗口同源对齐——**ToolCard 所见即模型真实读取内容**。旧 4KB 受控窗可通过设回 4000 恢复；上限值随 `read.preview_limit_chars` 下发，前端提示不硬编码数字。注意：放大后完整文件会随 `tool_output_delta`/`tool_result` 广播给会话全部在线成员并持久化进历史事件。

---

## 0. 文档地位

| 层级 | 文档 | 管什么 |
| --- | --- | --- |
| L0 | PRD V1.6.5 | 做不做、字段语义、状态机、事件名、错误码枚举 |
| L1 | **本文** | 路径、方法、请求/响应 JSON、鉴权、前后端谁调用 |
| L2 | 前端/后端开发计划 | 哪一周实现本文哪一节 |

**冲突裁决**

1. 与 PRD **功能/字段名/事件名** 冲突 → **改本文**，不改 PRD。  
2. PRD 5.9 是摘要：正文已有、5.9 未列的路径，由本文补全，**不算新产品**。  
3. 与前端/后端计划冲突 → **改计划对齐本文**。  
4. 内部 MCP、stress `/metrics` 浏览器 **不得** 直连；仅列在第 7、8 节给后端。

本文冻结此前计划中的「周三待定」：

| 待定项 | 本文裁决 |
| --- | --- |
| 会话 REST | **方案 A**：`/api/sessions` |
| Hit@K 的 K | `run.k`，默认 5，范围 1–20；**不**新增确认卡必填列 |
| Judge 开关 | `run.use_judge`，默认 `false`；裁判档来自协议档用途=`judge` |
| 心跳 | 传输层 WebSocket ping/pong；应用层仅服务端 JSON `pong`。客户端 **不** 发明 JSON `ping` 事件 |

---

## 1. 通用约定

### 1.1 传输

| 项 | 约定 |
| --- | --- |
| REST 前缀 | `/api` |
| WS | `GET /ws/agent?ticket=`（**无** `/api` 前缀，与 PRD 5.9 一致） |
| 协议 | HTTPS/WSS 生产；开发 HTTP + 同域反代 |
| Content-Type | JSON `application/json`；上传 `multipart/form-data` |
| 时间 | ISO-8601 UTC，字段名 `*_at` / `ts` |
| ID | UUID 字符串 |
| 分页 | `offset` 默认 0，`limit` 默认 50、最大 200；列表 `{ "items": [], "total": n }` |

### 1.2 鉴权

- 浏览器会话：登录成功后下发 **HttpOnly** Cookie `aieval_session`，12h，可续（滑动或显式续期由实现决定，对外表现为 12h 内活跃不掉）。  
- **禁止** 把长期 JWT 写入 `localStorage`，**禁止** 长期 token 进 WS query。  
- WS：先 `POST /api/auth/ws-ticket` 得 5 分钟短票，再升级。  
- 除注明外，REST 均需已登录 Cookie。  
- 分享报告：`GET /api/reports/{id}?share={token}` **免登录**，只读。  
- `GET /api/health` 免登录。  
- 角色：单一角色 `member`（全员同权）。未登录 401，body `code=UNAUTHORIZED`。敏感操作（如停用账号、删除基线）记录审计日志。

刷新页面后前端必须能恢复身份 → `GET /api/auth/me`（PRD 2.1 / F-CM-03 补全，5.9 未列）。

### 1.3 成功与错误

成功：HTTP 2xx，body 为资源或 `{ "items", "total" }` 或 `{ "ok": true }`。  
错误：

```json
{
  "code": "VALIDATION",
  "message": "请检查标红字段",
  "fields": { "dataset_id": "必填" }
}
```

| HTTP | code | 前端文案（设计规范 §7.3） |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | 没有权限做这件事（未登录时跳转 `/login`，可不用此句） |
| 403 | `UNAUTHORIZED` | 没有权限做这件事 |
| 400 | `VALIDATION` | 请检查标红字段 |
| 404 | `NOT_FOUND` | 资源不存在或已删除 |
| 409 | `BUDGET_EXCEEDED` | 已达本任务预算上限 |
| 409 | `CONCURRENCY` | 平台并发已满，任务保持排队（**仍 200 创建 queued 时不要用此码**；仅当实现拒绝创建时才 409。默认超限仍创建 queued，前端用 warning Toast） |
| 403 | `WHITELIST` | 目标不在压测白名单 |
| 403 | `NEED_APPROVAL` | 等待会签后才能发压 |
| 502 | `UPSTREAM` | 被测接口失败，详见样本错误 |
| 504 | `TIMEOUT` | 超时 |
| 500 | `INTERNAL` | 内部错误，请重试或联系平台维护者 |
| 403 | `DENIED` | bash 只读档拒写（V1.77/F5，V1.78 口径收敛；升档审批触发源，一般不直达 REST） |

确认卡 / 表单校验失败：`VALIDATION`，`fields` 给前端卡内红字，**不要**只靠 Toast。  
错误 body **不得** 含 Key、Cookie、stack。  
WS `error` 事件 payload 与上表同一套 `code` + `message`（可带 `fields`），HTTP 状态码只用于 REST。  
**能力未启用**（自定义斜杠、RAG、外部 MCP、页面 AI 未交付等）：一律 `VALIDATION` + HTTP **400**，禁止用 409 冒充（409 只给 `BUDGET_EXCEEDED` / `CONCURRENCY`）。  
业务代码只抛 `AppError`；禁止把未捕获异常的 `str(exc)` 或堆栈写入响应或 WS（见 AGENTS.md §5.2.1）。

### 1.4 枚举

| 名 | 值 |
| --- | --- |
| `role` | `member`（PRD 2.1 单一角色；历史三角色字段不再作为 V1.0 契约） |
| `kind` | `benchmark` `rag` `testcase` `stress` |
| `task_status` | `queued` `running` `succeeded` `failed` `cancelled` `awaiting_case_confirm` |
| `protocol` | `openai_chat` `openai_responses` `anthropic_messages` |
| `profile_usage` | `target` `agent` `judge`（被测 / Agent 后端 / 裁判；同一档可多用途，**Agent 后端全局仅一个**，见 settings） |
| `metric` | `exact` `contain` `regex` `rouge_l` `bleu` |
| `rag_mode` | `naive` `local` `global` `hybrid` |
| `stress_env` | `dev` `test` `staging` `prod` |
| `file_kind` 扩展名 | `.md` `.txt` `.html` `.pdf` `.json` `.yaml` `.yml` `.xlsx` `.xls` `.csv` `.jsonl` `.doc` `.docx` `.wav` `.mp3` `.png` `.jpg` `.jpeg` `.webp` `.gif` |

---

## 2. 前后端对应总表

目标态：浏览器前端所有业务图、表与表单均统一经由 API service 调用对应 REST/WS 接口，完成动态拉取与实时落盘。当前原型的真实接入现状与剩余静态视觉资产见 §12；不得把本表当作“后端已实现”清单。

| 模块 / 页面 | 前端功能与图表 | 调用的后端 API 接口 | 请求方法 | 权限口径 |
| --- | --- | --- | --- | --- |
| **登录 (login.html)** | 账号登录 / 自助修改密码 | `/api/auth/login`, `/api/auth/change-password` | POST | 免登录 / 成员 |
| **智能体 (agent.html)** | 会话列表 / 意图识别 / TaskSpec 下单 / 迷你拓扑坞 / 斜杠面板 / 上下文仪表 | `/api/sessions`, `/api/sessions/{id}/messages`, `/api/agent/prefs`, `/api/slash-commands`, `/ws/agent`, `/api/profiles`, `/api/datasets`, `/api/kb`, `/api/tasks`, `/api/dispatch/overview` | GET/POST/DELETE/WS | 成员 · 全员同权 |
| **调度中心 (dispatch.html)** | 调度大盘 / Worker 节点池 / 策略治理 / 分配日志流 | `/api/dispatch/overview`, `/api/dispatch/workers`, `/api/dispatch/workers/{id}`, `/api/dispatch/events`, `/api/dispatch/config`, `/api/tasks?status=queued` | GET/POST/PUT | 成员 · 全员同权 |
| **任务中心 (tasks.html)** | 24h 状态趋势 / 六态过滤表格 / 抽屉详情 / 取消与重跑 | `/api/tasks`, `/api/tasks/summary`, `/api/tasks/{id}`, `/api/tasks/{id}/cancel`, `/api/tasks/{id}/rerun` | GET/POST | 成员 · 全员同权 |
| **报告中心 (report.html)** | 报告列表 / 3合1详情 (Benchmark雷达/RAG水平柱状/压测多轴曲线) / Markdown导出 / 7天免登分享 / 冻结基线 | `/api/reports`, `/api/reports/{id}`, `/api/reports/{id}/samples`, `/api/reports/{id}/share`, `/api/reports/{id}/baseline` | GET/POST | 成员 · 全员同权 |
| **数据集工作台 (datasets.html)** | 数据集目录树 / 行内即点即改网格 / 自定义列扩展 / AI 数据集生成 | `/api/dataset-folders`, `/api/datasets`, `/api/datasets/{id}`, `/api/datasets/{id}/rows`, `/api/datasets/ai-generate`, `/api/kb` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **用例工作台 (cases.html)** | 6大策略分布图 / 用例表格编辑 / 72h倒计时 / Excel 导入导出 / 批量映射入库 / AI PRD 用例抽取 | `/api/case-folders`, `/api/case-sets`, `/api/case-sets/{id}`, `/api/case-sets/{id}/cases`, `/api/case-sets/{id}/confirm`, `/api/case-sets/{id}/cancel`, `/api/case-sets/{id}/map`, `/api/case-sets/ai-generate`, `/api/case-sets/import-template`, `/api/case-sets/{id}/import`, `/api/case-sets/{id}/export` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **知识库 (kb.html)** | 3栏工作台 / 文档与切块预览 / 4模式检索 Playground / 黄金 QA | `/api/kb`, `/api/kb/{id}`, `/api/kb/{id}/documents`, `/api/kb/{id}/documents/{doc_id}/chunks`, `/api/kb/{id}/query`, `/api/kb/{id}/gold-qa` | GET/POST/DELETE | 成员 · 全员同权 |
| **协议档与智能体 (admin-profiles.html)** | 4 Tab 架构（协议档、MCP 工具只读、技能受控说明、运行时治理）/ 连通性探活 Ping | `/api/profiles`, `/api/profiles/{id}/check`, `/api/mcp/tools`, `/api/admin/settings` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **压测治理 (admin-stress.html)** | 7天峰值 QPS 面积图 / Host 白名单表格 / 安全阈值 / 成本预算 / Prometheus `/metrics` | `/api/admin/stress/settings`, `/api/admin/stress/whitelist`, `/api/admin/stress/usage`, `/metrics` | GET/POST/PUT/DELETE | 成员 · 全员同权 |
| **成员与账号 (admin-users.html)** | 4 维 KPI 卡片 / 成员搜索表格 / 24h 登录活动柱状图 / 改密与停用 | `/api/users`, `/api/users/activity-summary`, `/api/users/{id}/status`, `/api/users/{id}/reset-password`, `/api/users/{id}/audit-logs` | GET/POST/PUT | 成员 · 全员同权 |

---

## 3. REST 明细

以下请求/响应为契约。未写的字段前端不得依赖，后端不得当必填。

### 3.1 健康检查

`GET /api/health`  
免登录。

```json
{ "status": "ok", "version": "0.0.0" }
```

---

### 3.2 认证

#### `POST /api/auth/login`

```json
{ "username": "admin", "password": "********" }
```

成功 200，Set-Cookie `aieval_session`，body 与 `GET /api/auth/me` 相同。  
失败 401，**不**区分用户不存在 / 密码错误；写 `audit_logs`。  
V1.84 起不再强制首次改密：登录成功直接进入系统，改密走右上角「修改密码」。

#### `POST /api/auth/logout`

成功 204 或 `{ "ok": true }`，清除 Cookie。进行中的任务 **不停**。

#### `POST /api/auth/change-password`

```json
{ "old_password": "********", "new_password": "********" }
```

规则：≥8 位，含字母和数字；校验旧密码后更新哈希并使旧登录 Cookie 立即失效。

#### `GET /api/auth/me`

```json
{
  "id": "uuid",
  "username": "alice",
  "role": "member",
  "must_change_password": false
}
```

#### `POST /api/auth/ws-ticket`

已登录成员可调用。5 分钟有效，一次性或短期内可重复升级（实现可允许多张未过期票，过期即废）。

```json
{ "ticket": "opaque", "expires_in": 300 }
```

未登录 401。

---

### 3.3 成员与账号管理（全员同权）

平台采用单一角色「成员（Member）」，全员同权。

#### `GET /api/users`

获取全部成员账号列表。

```json
{
  "items": [
    {
      "id": "u-01",
      "username": "alice",
      "display_name": "爱丽丝",
      "email": "alice@company.com",
      "role": "member",
      "disabled": false,
      "last_login_at": "2026-08-18T09:40:00Z",
      "last_login_ip": "10.0.0.12",
      "created_at": "2026-08-01T00:00:00Z"
    }
  ],
  "total": 1
}
```

#### `POST /api/users`

邀请 / 开户。

```json
{
  "username": "bob",
  "display_name": "鲍勃",
  "email": "bob@company.com",
  "password": "********",
  "must_change_password": false  // V1.84 起恒 false（机制废除，仅保留兼容）
}
```

#### `PUT /api/users/{id}` / `PUT /api/users/{id}/status`

更新成员资料或切换账号启用/停用状态（禁止停用系统中最后一名正常账号，写审计）。

```json
{ "disabled": true }
```

#### `POST /api/users/{id}/reset-password`

重置指定成员的登录密码（写入安全审计日志）。

```json
{ "password": "********" }
```

#### `GET /api/users/{id}/audit-logs`

获取指定成员近期的操作审计轨迹（开户、改密、登录、建单等）。

#### `GET /api/users/activity-summary?from=&to=`

成员与账号页的 KPI 与登录活动柱状图。数据由 `users`、`audit_logs` 聚合，不能由浏览器用示例日期计算；V1.0 不含异地登录的 AI 风险判定。

```json
{
  "range": { "from": "2026-08-17T00:00:00Z", "to": "2026-08-18T00:00:00Z" },
  "kpis": { "active_members": 8, "new_members": 1, "login_count": 24, "disabled_members": 0 },
  "login_buckets": [{ "ts": "2026-08-17T09:00:00Z", "count": 3 }]
}
```

---

### 3.4 会话（方案 A，M1 团队协作增量）

新会话默认 `visibility="private"`，仅 `owner_id` 可访问。创建者可切为
`team`，表示当前单一内部团队的正常成员均可读写；本期不是邀请制成员表。
`owner_id` 不因协作者发言而改变。会话删除是**软删除**：会话列表、历史和
WS 不再可访问，但 `messages`、`ws_events`、tasks、reports 均保留审计记录。

V1.76（F3/G5）会话可绑定用户工作区（`workspace_id`/`scope_path`）：绑定 =
创建时固化（运行期不可变），仅属主可绑、**绑定会话强制 `private`**（写授权
不随 `team` 可见性开放）；已绑定会话不可转 `team`。绑定后 read/write/edit/
bash 的沙箱根 = 工作区 scope（模型数据域即工作区）。

- `private`：只有 owner 可读写；
- `team`：所有正常成员可浏览、发送消息和连接同一会话；
- 分享设置、取消分享和软删除：只有 owner；
- 确认卡：只有 `pending_confirm_author_id` 对应成员可确认、拒绝或提交 patch；任务
  仍归确认卡作者创建；
- 带 `session_id` 的 `POST /api/tasks` 会锁住会话；存在待确认卡时统一返回
  `CONCURRENCY`，不得绕过该卡抢占活动任务；
- `DELETE` 遇到生成中的 Harness、待确认卡、`queued`/`running`/
  `awaiting_case_confirm` 任务时返回 `VALIDATION`，要求先停止、确认/取消或等待终态。

#### `GET /api/sessions`

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "帮我下一单 Benchmark",
      "owner_id": "uuid",
      "visibility": "private",
      "workspace_id": "uuid" | null,
      "workspace_name": "评测素材" | null,
      "scope_path": null | "cases/round1",
      "can_manage": false,
      "can_delete": false,
      "updated_at": "2026-09-21T12:00:00Z",
      "active_task": { "id": "uuid", "kind": "benchmark", "status": "running" }
    }
  ],
  "total": 3
}
```

`active_task`：该会话当前非终态任务（含压测子任务），无则 `null`。
`can_manage` / `can_delete` 只在当前成员为 owner 时为 `true`。

#### `POST /api/sessions`

请求：`{ "title": "新会话", "visibility": "private" }`；`visibility` 省略时为
`private`。响应包含 GET 列表项的 `owner_id`、`visibility`、权限字段和时间。

V1.76（F3/G5）可选绑定工作区：`{ "title": "…", "visibility": "private",
"workspace_id": "uuid", "scope_path": "cases/round1" }`——`workspace_id`
省略 = 未绑定（legacy 临时工作区，行为与 V1.75 一致）；`scope_path` 省略/
空 = 工作区根。绑定约束：`visibility` 必须 `private`；工作区须存在、未注销且
为当前用户属主；scope 段防穿越校验；任一不满足返回 `VALIDATION`
（fail-closed，不回落 legacy）。绑定创建时固化、运行期不可变，无换绑端点。

空会话，不创建 task。

#### `PUT /api/sessions/{id}/sharing`

仅 owner。请求和响应：

```json
{ "visibility": "team" }
```

将 `team` 改回 `private` 后，服务端立即以关闭码 `4404` 关闭协作者 WS，避免继续接收
瞬态正文流。正在执行的任务不因分享设置变化而取消。V1.76：已绑定工作区的会话
（`workspace_id` 非空）转 `team` → `VALIDATION`（写授权不随团队可见性开放）。

#### `PUT /api/sessions/{id}/title`

仅 owner。修改会话标题，写入安全审计日志（`session_title_update`）。

请求：

```json
{ "title": "自定义会话标题" }
```

规则：`title` 为 1-200 字符非空字符串，成功返回 200 与 `SessionOut` 完整对象。

#### `DELETE /api/sessions/{id}`

仅 owner，成功 `204 No Content`。这是软删除，不级联物理删除历史消息、事件、任务或
报告；已删除或无权访问均返回 `404 NOT_FOUND`，禁止返回“删除成功”的假响应。

#### `GET /api/sessions/{id}/messages`

历史回放（REST）。实时增量只走 WS。  
`messages` item：`id, role: user|assistant|system, content, attachments[], author_id?, author?, client_message_id?, latency_ms?, created_at`。
`attachments[]` 新消息为 `{file_id, filename, size, content_type?, content_url}`；历史存量若文件元数据不可恢复则保留原始 `file_id`，不回传内部存储路径。
其中 `author` 为 `{id,username,display_name?}`；用户消息必填，assistant/system 为 `null`。  
`latency_ms` 仅 `role=assistant` 非空：该交付句从本轮 `user_message` 入 Harness 到交付的墙钟耗时（毫秒），
前端在气泡下方展示「耗时 x 秒」；`user`/`system` 与无耗时历史消息为 `null`。
`events` **必带**（否则刷新丢工具卡 / 思考卡）。  
`pending_confirm`：当前未 ack 的确认卡（TaskSpec）或 `null`；
`pending_confirm_author_id` / `pending_confirm_author` 标识唯一可操作者；前端优先该字段做成可编辑卡，`events` 里的 `confirm` 只作只读回放。
`context_meter`：模型窗口仪表，刷新必须用服务端数字，禁止按 messages 表总条数自己减。`window` 固定 20；`/20` 只约束 `messages` 段；`skills` / `summary` 为 0/1 标志；`compacted` 为 bool 标志当前会话是否已执行 `/compact` 压缩（前端据此展示压缩徽标，与 `compact_summary` 文本字段互补）。

```json
{
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "/benchmark 对比两模型",
      "attachments": [],
      "author_id": "uuid",
      "author": { "id": "uuid", "username": "alice", "display_name": "Alice" },
      "client_message_id": "browser-uuid",
      "created_at": "2026-08-19T12:00:00Z"
    }
  ],
  "events": [
    {
      "event_id": 1,
      "event": "thought",
      "task_id": null,
      "payload": { "text": "规划：基准评测", "stage": "plan", "skill_id": "skill-benchmark" },
      "ts": "2026-08-19T12:00:01Z"
    }
  ],
  "pending_confirm": null,
  "pending_confirm_author_id": null,
  "pending_confirm_author": null,
  "compact_summary": null,
  "context_meter": {
    "messages": 8,
    "skills": 0,
    "summary": 0,
    "headroom": 12,
    "window": 20,
    "total_tokens": 6720,
    "max_tokens": 200000,
    "messages_tokens": 5520,
    "skills_tokens": 0,
    "free_tokens": 193280,
    "used_percent": 3.4,
    "mcp_tools_count": 2,
    "mcp_tools_max": 28,
    "compacted": false
  }
}
```

实现列（Alembic，不单独 GET 摘要原文，避免把压缩提示词泄漏到浏览器）：
`sessions.visibility`、`sessions.deleted_at`、`sessions.pending_confirm` JSONB、
`sessions.pending_confirm_author_id`、`sessions.compact_summary` TEXT、
`sessions.compact_keep_from`（messages.id），以及 `messages.author_id` /
`messages.client_message_id`。算法见 Agent 说明书 §16.6。

`messages.role=assistant` 只存**已验证的最终交付句**（澄清、闲聊、「已入队」、「已压缩」、「已停止生成」、只读摘要）。Plan、ReAct/reflect 内部控制、工具观察与 `progress` 都不写入 `messages`；Plan、工具和确认分别只由其对应卡片表达。

---

#### `GET /api/agent/prefs`

当前成员的跨会话下单偏好。只读；无 PUT。写入仅发生在 `confirm_ack.ok=true` 且任务已入队之后（服务端写 `settings` 键 `agent_prefs:{user_id}`）。

```json
{
  "last_kind": "benchmark",
  "last_profile_ids": ["uuid"],
  "last_dataset_id": "uuid",
  "last_kb_id": null,
  "last_gold_qa_id": null,
  "last_with_stress": false,
  "updated_at": "2026-08-19T12:00:00Z"
}
```

无记录时各字段 `null`（`last_profile_ids` 为 `[]` 或 `null` 均可，前端当缺失）。失效资产 ID 规划侧当 missing，不得编造。闲聊、取消确认、`/compact` 不写。

---

#### `GET /api/agent/metrics`

进程内只读快照：native 交错流与 ToolBatch 调度度量（登录成员可读，与 `GET /api/mcp/metrics` 同鉴权）。**不含**助手正文、工具参数、Observation、API Key。不落库；多副本各自独立。不新增 WebSocket 字段，`segment_id` 仍不进入公共契约。

```json
{
  "stream": {
    "rounds": 12,
    "invoke_fallbacks": 1,
    "first_delta_avg_ms": 180,
    "tool_call_parse_avg_ms": 420,
    "incomplete": 0,
    "incomplete_ratio": 0.0,
    "cancelled": 1,
    "upstream": 0,
    "associate_errors": 0
  },
  "batch": {
    "count": 4,
    "duration_avg_ms": 90,
    "parallel_waves": 1,
    "wave_size_avg": 2,
    "max_wave_size": 3
  },
  "rollout": {
    "native_stream_enabled": true,
    "parallel_enabled": false,
    "parallel_profile_allowlist": [],
    "parallel_disabled": false,
    "parallel_disable_reason": null,
    "consecutive_incidents": 0,
    "failure_threshold": 5,
    "cooldown_s": 30.0
  }
}
```

`rollout.parallel_disabled=true` 表示进程内脚踢线暂时关闭只读并行（连续 `UPSTREAM` / 关联错乱达阈值）；冷却后自动恢复。运维回滚并行仍关 `AGENT_PARALLEL_TOOL_BATCH_ENABLED` 或清空 `AGENT_PARALLEL_TOOL_BATCH_PROFILE_IDS`；回滚 P1 流式关 `AGENT_NATIVE_STREAM_ENABLED`。关闭开关**不得**改写已落库事件。

---

#### `GET /api/slash-commands`

自定义斜杠（下区「我的命令」）。**系统 15 条命令不走本接口**，前端本地注册表即可。

M2 已交付：成功 200。无命令时返回 `items=[]`（能力已启用，不是未启用桩）。禁止 localStorage 冒充已保存。

```json
{
  "items": [
    {
      "id": "uuid",
      "name": "smoke",
      "hint": "冒烟评测",
      "template": "帮我下一单基准评测，抽样 20 条",
      "created_by": "uuid",
      "created_at": "2026-08-19T12:00:00Z"
    }
  ],
  "total": 1
}
```

#### `POST /api/slash-commands`

body：`{ "name", "hint", "template" }`。  
`name`：`^[A-Za-z][A-Za-z0-9_-]{0,31}$`，且不与系统 15 条重名（禁止中文 name）。  
`template`：1–2000 字符，仅预填用户输入框，永远不当 system。含「跳过确认」「改系统提示词」或去空白后等于 `/bypass` → `VALIDATION`，不保存。  
成功 201，返回创建对象。改删仅 `created_by` 为当前用户。

#### `DELETE /api/slash-commands/{id}`

仅创建者；否则 `UNAUTHORIZED`。系统命令无 id，不可删。

选中自定义命令后展开 `template` 进输入框，发送仍是 WS `user_message`，不能加新工具、不能跳过确认卡。

---

### 3.5 文件

#### `POST /api/files`  multipart

字段 `file`。单文件 ≤20MB；扩展名见 §1.4。磁盘 `./data/files/{id}`，PG 存路径与 sha256。

```json
{
  "id": "uuid",
  "filename": "cases.xlsx",
  "size": 12345,
  "sha256": "...",
  "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}
```

超限 `VALIDATION`。Agent 附件：先本接口，再把 `id` 放进 `user_message.attachments[]`。

Agent 收到 `user_message` 后会校验每个 `file_id` 属于当前发言人，再将可解析的 Markdown、文本、PDF、DOCX、XLSX 正文以受限长度注入本轮模型上下文；图片按视觉内容块注入。数据库保存的用户 `content` 保持原文，附件解析内容只存在于模型请求中，不回显到用户消息气泡。

#### `GET /api/files/{id}`

元数据，同 POST 响应。不回文件二进制。

#### `GET /api/files/{id}/content`

登录后返回文件二进制（`Content-Disposition: inline`），供浏览器图片、PDF、文本预览，以及 Office/表格/音频打开或下载。未登录 `UNAUTHORIZED`；不存在 `NOT_FOUND`。路径不回显内部存储位置。Agent 音色克隆短工具的 `content_url` 指向本接口。

---

### 3.6 协议档

响应 **永不** 含 Key，即使 PUT 刚写入。空字符串 Key = 不修改。

#### 模型思考模板与预注册验证（V2.2，2026-09-15）

V2.2 修订（替代 V2.1 的模型族硬限制和超时说明）：供应商与协议是模板兼容边界，模型名称只决定候选推荐顺序，未知型号、部署 ID 可以选择同供应商模板验证。分别提供开关、枚举、数值、预算、自适应与固定开启方言；开关仅暴露 off/high（界面显示关闭/开启），可选数值模板的平台 low/medium/high/max 映射为 1/33/67/100（不按具体型号默认启用），枚举模板不制造重复档位。模板版本变化后旧探测失效，ProfileOut.reasoning_probe_status 返回 unverified。预算被上下限夹紧后同参的档位只保留一个（优先默认档），避免重复探测和伪强度。ProfileOut 和 AgentLoop options 的 profile 增量 `reasoning_mode`（none/switch/effort/budget/fixed，legacy 为 null），用于真实显示控件语义。

探测最多五档并发，使用拟保存的输出上限以确保预算参数与正式调用一致（取代 2,048 token 截断），每档有最长 30 秒整体截止时间并取消未完成流，连接清理最多额外一秒。开启必须有推理证据；关闭如仍有推理证据则失败；没有正常完成、仅截断或没有正文也不能算通过。没有推理证据表示本次未确认，不等于供应商不支持。结果只能证明该配置请求成功并取得可观测证据，不能证明供应商没有忽略某个强度字段。

页面按供应商与协议取得受控模板，模型名称只用于推荐排序。后端保持供应商与协议隔离；未知型号也可以选择模板并验证。后端用拟保存的 URL、模型 ID、协议、Key 和输出上限并发探测，最多五档，每档整体截止时间最长 30 秒，清理连接另有最多一秒限时。

关闭思考仅要求请求正常完成。开启思考除正常完成外，必须出现 reasoning 增量或正数推理用量；否则该档位以 `NO_REASONING_EVIDENCE` 失败，不能仅因兼容网关返回普通文本就开放思考强度。探测元数据只保存证据类别（`reasoning_delta`、`reasoning_usage` 或 `request_completed`），不保存任何思考正文或原始上游响应。

`reasoning_template_id`、`reasoning_probe` 是协议档的非敏感配置元数据。`reasoning_probe` 只保存验证时间、模板版本、通过的档位和安全错误分类，禁止保存 API Key、上游正文、思考内容、请求头或请求体。模型、端点、协议、输出上限或模板改变时必须使验证结果失效；此时 AgentLoop 的 `allowed_efforts` 为空，不能用未验证的强度发起请求。旧行没有模板时继续走既有 legacy 解析，避免升级改变已存在模型的行为。

#### `GET /api/profiles/reasoning-templates`

参数：`provider`（供应商标识）、`protocol`（`openai_chat` / `openai_responses` / `anthropic_messages`）和必填 `model`（目标模型 ID）。返回当前组合可选择的静态模板摘要：`id,name,provider,protocol,mode,allowed_efforts,default_effort,description,version`。模板是平台受控的参数适配器目录，不接收任意 JSON 请求覆盖，也不回传密钥。

#### `POST /api/profiles/probe-create`

请求体与 `POST /api/profiles` 相同，另含必填 `reasoning_template_id`。服务端先验证 URL 和模板兼容性，再执行真实验证；返回 `{ok,profile?,probe,message}`。`ok=true` 时 `profile` 是已写入的脱敏协议档；`ok=false` 时 `profile` 为 `null`，不会创建任何协议档或环境变量。前端的新建与批量添加入口必须调用本接口。

#### `POST /api/profiles/{id}/probe-update`

请求体与 `PUT /api/profiles/{id}` 相同，另含必填 `reasoning_template_id`。使用拟更新的连接配置验证；验证失败时原协议档及环境变量保持不变，成功后原子更新。前端编辑模型、端点、协议、输出上限或模板时必须调用本接口。

原 `POST /api/profiles` / `PUT /api/profiles/{id}` 保留给 legacy 协议档兼容和非模型字段更新；若上述影响思考验证的字段改变，服务端清空已有验证结果，不能静默沿用旧能力。

协议档的 `base_url`、`model` 和 `api_key` 由 API 后端脚本写入服务器受控环境文件，数据库只保留
协议档 ID、名称、协议、用途和上下文窗口等元数据。每个协议档使用独立变量，变量名为：

```text
AI_PROFILE_<PROFILE_ID_NORMALIZED>_BASE_URL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_MODEL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_API_KEY
AI_PROFILE_<PROFILE_ID_NORMALIZED>_EMBEDDING_BASE_URL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_EMBEDDING_MODEL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_EMBEDDING_API_KEY
AI_PROFILE_<PROFILE_ID_NORMALIZED>_RERANKER_BASE_URL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_RERANKER_MODEL
AI_PROFILE_<PROFILE_ID_NORMALIZED>_RERANKER_API_KEY
```

其中 `PROFILE_ID_NORMALIZED` 将非字母数字字符替换为下划线并转为大写，因此多个供应商可以同时存在，
不会互相覆盖。服务器既有的 `LLM_API_KEY`、`LLM_MODEL`、`OPENAI_BASE_URL`、`ANTHROPIC_BASE_URL`
仅作为旧单模型环境配置兼容别名；切换 Agent 协议档时由后端同步。环境文件由 Compose 挂载给 `api`（可写）
和 `worker`（只读），后端在文件锁保护下原位刷新并 `fsync`，失败时按快照回滚。

#### `GET /api/profiles`

全员可列（无 Key），供确认卡和 RAG 上下文工程使用。除主模型外，Embedding 与 Reranker
端点均为可选；响应只返回 URL、模型标识和 `has_*_api_key` 布尔值，不返回任何 Key。
item：`id, name, protocol, base_url, model, usages[], context_window, max_output_tokens, tool_call_mode,
embedding_base_url, embedding_model, has_embedding_api_key, reranker_base_url, reranker_model,
has_reranker_api_key, created_at`

#### `POST /api/profiles`  已登录成员

```json
{
  "name": "gpt-test",
  "protocol": "openai_chat",
  "base_url": "https://api.example.com",
  "model": "gpt-4.1",
  "api_key": "sk-...",
  "embedding_base_url": "https://embedding.example.com/v1",
  "embedding_model": "text-embedding-3-large",
  "embedding_api_key": "ek-...",
  "reranker_base_url": "https://reranker.example.com/v1",
  "reranker_model": "bge-reranker-v2-m3",
  "reranker_api_key": "rk-...",
  "usages": ["target"],
  "tool_call_mode": "legacy",
  "max_output_tokens": 8192
}
```

`anthropic_messages` 可另存 `anthropic_version`（默认 `2023-06-01`）。变更写审计；API Key 不进入数据库，
`has_api_key`、`has_embedding_api_key`、`has_reranker_api_key` 仅表示环境文件中是否存在对应 Key。
Embedding 与 Reranker 的 URL、模型和 Key 与主模型使用相同的“按协议档隔离、受控环境文件写入、空 Key 保留旧值”规则；
更新时只提交需要修改的字段。三类 Key 仅在各自地址同源（协议、主机、有效端口一致）时允许留空保留；跨源变更且存在旧 Key 时，保存、测试并更新、获取模型列表均返回 `VALIDATION`，要求显式填写新 Key。Embedding/Reranker 未设置独立地址时，以主模型地址作为凭据复用边界。获取模型列表自动读取环境凭据仅限已配置的同源端点，禁止按域名子串或协议向任意主机兜底。

`max_output_tokens` 为 Agent 单回合模型输出上限（映射到上游 `max_tokens` / `max_output_tokens`），取值 256–131072，默认 `8192`；仅影响 `usages` 含 `agent` 的对话调用，不影响 benchmark、judge、用例生成等离线调用。

`tool_call_mode` 仅允许 `native` / `legacy`，默认 `legacy`：

- `native`：仅在管理员已验证目标网关支持 Function Calling 后显式选择。API 按 `protocol` 映射并发送原生 `tools`，流式接收正文增量与完整 ToolCall；**一次上游响应在发出 ToolCall 后即结束**，平台执行工具并回填 `tool_result` 后才会发起下一次模型请求。工具结果依赖的正文不可能出现在同一条上游响应中。参数不完整不得进入 ToolNode；
- `legacy`：默认模式。API 不向上游发送 `tools`，仅使用严格 `react.v1` JSON 兼容分支；适用于尚未验证 Function Calling 的兼容网关；
- 切换模式只影响 Agent ReAct 工具路径，不影响 benchmark、judge、Embedding 或 Reranker 调用。

#### `PUT /api/profiles/{id}` / `DELETE /api/profiles/{id}`

修改或删除协议档（正在被 Agent 后端引用的协议档禁止删除，写审计）。

#### `POST /api/profiles/{id}/check`

使用实际对话同一流式适配器发送 ping；复用已保存输出上限、模板及已验证默认思考档。30 秒内收到首个非空正文/思考片段或合法 stop/length 终态即确认连通并关闭流；不再发送 max_tokens=1。该检查不代替完整思考和工具能力验证，超时仅表示本次探测未通过。响应：

```json
{ "ok": true, "latency_ms": 120 }
```
或 `{ "ok": false, "code": "UPSTREAM", "message": "401 from upstream" }`（日志与响应严禁携带 API Key）。

环境文件不存在、不可写、格式错误或调用时缺少对应 Key，统一返回 `VALIDATION` / `INTERNAL`，不得把文件内容
或凭据原文返回浏览器。

#### `POST /api/profiles/fetch-models` / `POST /api/profiles/models`

按输入的 `protocol`、`base_url`、可选 `api_key` / `profile_id` 获取远程模型目录。响应
`{ "ok":true, "models":[...], "total":N }`；每项至少含 `id`、`name`、`owned_by`，若上游声明
可选请求字段则额外返回：

```json
{
  "id": "grok-4.6",
  "name": "Cursor Grok 4.6",
  "owned_by": "cursorapi",
  "parameters": [
    { "id": "effort", "values": ["Low", "Medium", "High"] },
    { "id": "fast", "values": ["false", "true"] }
  ]
}
```

`parameters` 只是端点目录提供的模型规格能力，平台不猜测或硬编码其字段。对 CursorAPI，选择值后保存为
`grok-4.6[effort=Medium,fast=true]` 并在每次请求中作为 `model` 原样发送；`thinking` 仅影响 Cursor
侧推理计算，CursorAPI 当前不会把它的过程映射为 OpenAI 流式 `reasoning_content`，前端不得显示为已支持。

---

### 3.6.1 原生基础工具与 MCP 扩展目录（只读）

#### `GET /api/mcp/tools`

获取当前智能体环境中平台 allowlist 的**MCP 扩展目录**（只读）。`read`、`write`、`edit`、`bash`、`web_search`、`web_fetch` 与对话拆解 `task` 不属于目录：模型以原生 Function Calling 生成 ToolCall，ToolNode 完成 Schema、权限、附件门禁后，直接交 `NativeToolExecutor` 在线程池执行，不产生 MCP catalog/provider 路由开销。

默认已挂载的 MCP 扩展为评测任务桥 `platform.tasks`；启用媒体配置后，目录额外出现 `media.generation.image.generate`、`media.generation.video.create`、`media.generation.video.status`。目录只展示元数据，**不展示任何 MCP Server 连接命令、环境变量、工作目录或凭据**，也不展示内部 handler 细节。`code_snippet` 字段与 `GET /api/mcp/tools/{name}/code` 端点已于 V1.65 移除（原为手写示意代码且与真实 handler 不符）；前端「源码实现」视图改为引导按 `source_file`/`handler_function` 在代码仓库中查看真实实现。

`platform.tasks` 三工具只入 PG 队列或查询，**不等待 Worker 终态**：`task.create` 校验通过后直接入队返回 `queued` + `task_id`；`task.status` 只读当前状态不轮询；`task.cancel` 行锁取消非终态任务。真实进度/报告/错误由 Worker 写入 `task_events`/`ws_events` 转发。

```json
{
  "items": [
    { "name": "platform.tasks.task.create", "short_name": "task.create", "permission": "write" },
    { "name": "platform.tasks.task.status", "short_name": "task.status", "permission": "read" },
    { "name": "platform.tasks.task.cancel", "short_name": "task.cancel", "permission": "write" }
  ],
  "total": 3
}
```

未来扩展项的 `name` 为唯一 `tool_id`（`{server_id}.{short_name}`）；必填字段为 `name`、`desc`、`permission`（`read`/`write`）、`enabled`、`source`，可选 `tool_id`、`server_id`、`short_name`、`display_name`、`risk_level`、`execution_mode`、`timeout_s`、`requires_confirmation`、`supports_streaming`。MCP 扩展只能由平台部署和 allowlist 注册，浏览器与模型均不得提供 Server 命令、连接串或凭据。

原生基础函数定义（随 Agent 模型请求的 `tools` 字段下发，不提供浏览器 REST 调用）：

| 函数 | 用途与上限 | 执行/结果边界 |
| --- | --- | --- |
| `read(path, offset?, limit?)` | workspace 相对路径；0-based 分页；最多 2,000 行、600,000 字符、20MB 文件 | 单次流式扫描；模型可见片段 ≤600,000 字符，未读完带 `next_offset`（可回填为下次 `offset`）；ToolCard 显示行号与完整行预览（上限 `TOOL_PREVIEW_MAX_CHARS`，默认与模型窗口对齐，见 V1.45） |
| `write(path, content)` / `edit(path, old, new)` | 新建最多 2MB UTF-8 文件 / 精确单次替换 | `write` 使用 O_EXCL 防覆盖竞争；`edit` fsync 后 `os.replace` 原子提交；不回显写入正文 |
| `bash(command)` | 会话 workspace 内的短命令 | 始终经 bwrap：无网络、唯一可写目录、资源上限、超时整树清理；引擎不可用 fail-closed |
| `web_search(query, limit?)` | 关键词 ≤500 字符、1–10 条 | API 容器用环境变量中的 Firecrawl REST Key；未配置返回 `VALIDATION`，不伪造结果；结果结构化并脱敏 |
| `web_fetch(url, format?)` | 仅公开 http/https 文本页 | 首次和每次重定向均执行 DNS/IP SSRF 校验；优先 Firecrawl Markdown，未配置时降级为安全直接文本抓取；正文不进 WS 持久事件 |
| `task(goal, steps)` | 1–12 个 `pending/in_progress/completed` 步骤 | 只生成当前回合任务清单和 ToolCard；**不创建 `Task` 行、不入队、不调用 Worker、不替代 `confirm_ack`** |

浏览器不能创建、删除或指定任意第三方 MCP Server，也不得请求 `/api/mcp/servers*`。本期唯一远程服务是固定 Compose 私网地址 `http://media-mcp:8002/mcp` 的媒体 MCP；API 以 Streamable HTTP 执行 `initialize → tools/list → tools/call`，上游密钥仅在媒体服务保存。

#### `GET /api/mcp/media-config`

返回媒体 MCP 的脱敏配置：

```json
{
  "enabled": true,
  "compatible_base_url": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
  "image_model": "qwen-image-3.0-pro",
  "video_model": "happyhorse-1.1-i2v",
  "request_timeout_s": 180,
  "has_api_key": true
}
```

`has_api_key` 只表示服务端已保存凭据，响应不包含密钥。`enabled=false` 时 AgentLoop 不向模型注入媒体工具。

#### `PUT /api/mcp/media-config`

请求体可增量更新 `enabled`、`compatible_base_url`、`api_key`、`image_model`、`video_model`、`request_timeout_s`。兼容模式地址必须为无用户名、无查询串的 HTTPS `.../compatible-mode/v1`；`request_timeout_s` 为 10–600。`api_key` 留空或省略表示保留现值，不能通过该接口清除。启用前必须已具备兼容模式地址和 API Key。成功后写 `AuditLog(action="media_mcp_config_update")`，当前 API 实例刷新媒体工具目录。

媒体 MCP 工具：`image.generate(prompt, reference_images?, size?, count?, prompt_extend?)` 同步返回临时图片地址；`video.create(prompt, first_frame, resolution?, duration?, watermark?)` 只提交 HappyHorse 图生视频异步任务并返回上游任务 ID；`video.status(upstream_task_id)` 查询状态，成功时含临时视频地址。本期不创建平台媒体 `Task`、不归档结果、不新增 WS 事件，也未实现上游取消。

#### `GET /api/mcp/metrics`

获取内部 MCP Host 的**调用度量与服务器熔断状态**（只读，进程内快照）。按 `tool_id` 记录调用计数与耗时，按 `server_id` 维护失败熔断：`INTERNAL`/`TIMEOUT`/`UPSTREAM` 连续失败 ≥ 阈值（默认 5）即 `open`，冷却期（默认 30s）后自动恢复 `closed`；熔断 open 期间 `tool_call` 以 `VALIDATION`（「服务器工具暂时不可用（熔断）」）快速拒绝，不进入执行器。

```json
{
  "tools": [
    { "tool_id": "platform.tasks.task.status", "total": 12, "success": 11, "failure": 1, "timeout": 0,
      "avg_latency_ms": 8, "last_latency_ms": 6, "last_error_code": null }
  ],
  "circuits": [
    { "server_id": "platform.tasks", "state": "open", "consecutive_failures": 5,
      "failure_threshold": 5, "cooldown_s": 30.0, "opened_at": 1756080000.0 }
  ],
  "summary": { "total_calls": 12, "total_failures": 1, "total_timeouts": 0, "open_servers": ["platform.tasks"] }
}
```

只读展示，不含任何请求参数、工具结果原文或凭据。任务创建（MCP `task.create` 与 REST `POST /api/tasks` 共用）受每用户活动任务配额 `max_active_tasks_per_user`（默认 5）约束，超限返回 `CONCURRENCY` 并写 `AuditLog(action="task_quota_rejected")`。

---

### 3.6.2 Agent 技能与 Prompt 编排（V1.58 受控）

技能文件统一存放于运行时 `skills/<skill_id>/SKILL.md`（容器默认 `/data/skills`）。文件头部必须恰为 `id`、`name`、`kind`、`version`、`enabled`、`summary` 六个字段，并以 `## 工作流` 开始正文。目录阶段只读取固定上限的头部生成 Skill Hint；仅在本轮规划选中 `skill_id` 后读取完整正文。所有读取先验证目标 `SKILL.md` 存在；`skill-rag` 仍因引擎未接入保持 `enabled=false`，不得编辑为启用。

管理端只有既有已登录成员可使用下列 `/api/admin/*` 接口；每次写入均写 `AuditLog`，审计明细只记录技能 ID、修订指纹或字符数，绝不保存技能/提示词正文或凭据。会话沙箱中的 `read/write/edit` 只能作用于会话工作区，不能通过这些工具修改运行时 `skills/` 或 Prompt 配置。

#### `GET /api/admin/skills`

返回技能轻量目录，不返回工作流正文：

```json
{
  "items": [{"id":"skill-benchmark","name":"基准评测","kind":"benchmark","version":"1.0","enabled":true,"summary":"执行大模型基准评测"}]
}
```

#### `GET /api/admin/skills/{skill_id}`

管理员预览单个 `SKILL.md` 完整文本，返回 `{ "id", "content", "revision", "metadata" }`。文件不存在返回 `NOT_FOUND`；头部或正文不符合上述统一规格返回 `VALIDATION`。

#### `PUT /api/admin/skills/{skill_id}`

body：`{ "content":"...", "expected_revision":"16位修订指纹" }`。服务端先验证 ID、文件存在、固定头部、`kind` 与平台任务类型、启用状态和正文，再以原子写入保存。`expected_revision` 不匹配返回 `CONCURRENCY`，前端必须重新预览后再提交。

#### `GET /api/admin/agent-prompts/{profile_id}` / `PUT /api/admin/agent-prompts/{profile_id}`

每个 `usages` 包含 `agent` 的协议档均预留独立的 Prompt 管理入口。GET 返回只读 `base_prompt`（核心角色、安全、确认卡、长短任务和密钥保护）以及该协议档当前 `overlay`。PUT body 为 `{ "overlay":"..." }`，只可保存 12,000 字符以内、无疑似密钥字段的补充提示词；空字符串清除该协议档补充提示词。核心 `base_prompt` 不可写，运行时始终由 Harness 生成，且它优先于任何 `overlay`。不存在的协议档返回 `NOT_FOUND`，非 Agent 用途协议档返回 `VALIDATION`。

---

### 3.6.3 Agent Worker 目录（只读，V1.66）

`GET /api/agents`：返回混合引擎静态 Worker 目录（H0 `AgentRegistry` 投影）。所有已登录成员可读；目录仅描述同一 LangGraph 图内的工具视野与能力边界，**不代表模型正在调用**，不含 API Key、协议客户端或 LLM 实例；`model_profile_id` 只持有协议档 ID（`null` 表示沿用会话当前协议档）。注册表在启动期完成 `allowed_tools ⊆ ToolRegistry`、`skill_ids ⊆ SKILL_CATALOG` 校验，strict 模式下不通过则进程拒绝启动。

```json
{
  "agents": [
    {
      "agent_id": "worker.general",
      "display_name": "通用助手",
      "capabilities": ["general"],
      "allowed_tools": ["read", "web_search", "web_fetch", "task"],
      "skill_ids": [],
      "max_permission": "read",
      "budget": {},
      "model_profile_id": null,
      "description": "通用对话与只读探索：读文件、联网检索、会话任务看板"
    }
  ]
}
```

H1 阶段该目录仅用于诊断与联调观测；`discover` 收窄工具视野自 H3 起生效，`worker.sandbox`（`code` 权限）在 HITL 就绪前不得被生产路径选中。

---

### 3.7 数据集工作台

#### `GET /api/datasets` / `GET /api/datasets/{id}`

```json
{
  "id": "uuid",
  "name": "smoke-20",
  "version": 3,
  "status": "draft | active",
  "active_version_id": "uuid?",
  "folder_id": "uuid?",
  "row_count": 20,
  "pending_complete_count": 2,
  "metric": "contain",
  "column_schema": [{ "key": "difficulty", "name": "难度", "type": "string", "sort_order": 1 }],
  "created_by": "uuid?",
  "created_at": "..."
}
```

#### `POST /api/datasets`

```json
{ "name": "smoke-20", "metric": "contain" }
```

#### `GET /api/dataset-folders` / `POST /api/dataset-folders` / `PUT /api/dataset-folders/{id}` / `DELETE /api/dataset-folders/{id}`

数据集目录树是业务数据而非前端偏好。folder item：`id, name, parent_id?, sort_order, created_at`；删除非空目录返回 `VALIDATION`，前端必须先移动或删除其中数据集。

#### `PUT /api/datasets/{id}`

可改 `name`、`metric`、`folder_id`、`column_schema`。`column_schema` 为自定义列定义数组（每项 `key,name,type,required?,sort_order`），数据行扩展值保存到对应 key；已有报告不受影响，对比仍看任务快照。

#### `DELETE /api/datasets/{id}`

删除仅限没有 `active_version_id` 的草稿数据集；已发布数据集返回 `VALIDATION`，以保留版本、导入和历史任务的可追溯关系。

#### `POST /api/datasets/{id}/upload`  multipart `file`

JSONL 或 CSV UTF-8；列 `question,reference,context?`；≤50MB、≤2 万行。覆盖后 `version += 1`。非法行可拒整文件 `VALIDATION`。已有 `active_version_id` 的数据集返回 `VALIDATION`，必须创建新的受控导入版本。

#### 公开基准目录、独立导入与发布（V1.55）

目录治理由全员同权成员维护，但采用**不同成员复核**，没有管理员角色或绕过接口：

- `POST /api/dataset-catalog-entries`、`PUT /api/dataset-catalog-entries/{entry_id}`：登记或修改来源 draft。输入为 `name, upstream_owner, official_project_url, allowed_domains[], purpose?, evidence_refs?`；仅提报成员可改 draft。
- `POST /api/dataset-catalog-entries/{entry_id}/releases`、`PUT /api/dataset-catalog-releases/{release_id}`：登记固定 release draft。`manifest.artifacts[]` 的每项必须有无凭据 HTTPS `url` 和 SHA-256；`source_revision` 不得是 `main/master/latest`；同时提供 `license.status`、`allowed_splits`、`filter_schema:{version:1,fields:{...}}`、固定 `parser_id/parser_version`、`task_family` 和 `support_status`。标记为 `supported` 时，`parser_id` 必须已由 Worker 注册；`review_required` 与 `planned` 仍可登记待实现 parser，但不得批准为可导入。
- `POST /api/dataset-catalog-releases/{id}/submit-review`、`/approve`、`/block`、`/resolve-block`：请求体为 `{note?}`（解除封禁还含 `decision:"approved"|"blocked"`）。批准与解除封禁不能由提报者完成；解除封禁还不能由原封禁者完成。

`GET /api/dataset-catalog` **只**返回 `active` 来源下 `approved` release，绝不在请求时访问 Hugging Face、GitHub 或第三方站点。可选 query 为 `scenario,task_family,language,license_status,test_availability,support_status,q`。release 的 `metadata` 可提供 `scenarios,language,test_availability,estimated_rows`；响应同时返回 `license_status`、风险标签、允许 split、固定 parser 及 manifest 哈希。

`POST /api/dataset-imports` 只接受已批准目录的 ID 与受限筛选，绝不接受任意 URL、Cookie、Header、Token、脚本或路径：

```json
{
  "catalog_entry_id": "uuid",
  "release_id": "uuid",
  "splits": ["test"],
  "filter_schema_version": 1,
  "filters": {"subject": "computer_network"},
  "target_name": "C-Eval-计算机网络-test",
  "folder_id": "uuid?"
}
```

也可用 `target_dataset_id` 指向已有容器（若同时传 `target_name` 必须一致）。服务端校验 release/许可证/任务支持状态、split 和 filter schema，冻结 release manifest、来源允许域名、parser 版本与筛选条件，按 `manifest_hash + splits + filters + parser_version + dataset_id` 生成幂等指纹并返回 HTTP 202。目标数据集存在未完成导入时返回 `CONCURRENCY`。

`DatasetImport` 不是评测 `Task`，不写确认卡或报告。状态为 `queued | downloading | validating | parsing | review_ready | failed | rejected | published`；`GET /api/dataset-imports/{id}` 返回 `id,dataset_id,status,stage,attempt,max_attempts,manifest_hash,staging_revision?,summary,error?,creator_id,reviewer_id`。`POST /api/dataset-imports/{id}/retry` 仅允许 `failed` 且错误码为 `UPSTREAM` 或 `TIMEOUT`、且未超过尝试上限的作业；`POST /api/dataset-imports/{id}/reject` 要求非提报成员拒绝 `review_ready` 作业。全程不新增 WS 事件。

Worker 按 `FOR UPDATE SKIP LOCKED` 领取导入，写入独立 15 分钟 lease 与 attempt；过期 lease 在尝试上限内重新排队，超过上限以 `TIMEOUT` 收束。当前只支持受控 `jsonl-qa-v1` 和 `csv-qa-v1` parser；每个来源行或制品必须携带可验证 split，下载必须通过 HTTPS、冻结域名/重定向和私网地址检查，并校验单制品 50MB 上限与 SHA-256。

#### staging 行与不可变发布

`GET /api/datasets/{dataset_id}/rows?view=staging&import_id={import_id}` 在 `review_ready`（及只读的 `published/rejected`）状态返回 staging 行。每行都有稳定 `id`、`row_no`、三元组字段、`warnings`、`provenance` 和解析扩展列，响应包含 `staging_revision`。

`PUT /api/datasets/{dataset_id}/rows?view=staging&import_id={import_id}` 的请求体为 `{expected_staging_revision,rows:[{id,q?,r?,c?,...}]}`。仅非提报成员可保存；服务端锁定导入批次，校验 revision 与稳定行 ID，保存后重算行内容哈希并递增 revision；不允许按可变 `row_no` 直接发布。

`POST /api/datasets/{dataset_id}/publish-import` 的请求体为：

```json
{
  "import_id": "uuid",
  "expected_staging_revision": 3,
  "accepted_row_ids": ["stable-row-uuid"],
  "note": "复核通过"
}
```

发布者必须不同于导入提报者。服务端在一个事务中锁定 dataset/import，校验 revision 和选择行；选择行还必须具备非空 `question/reference`、冻结 split，且不得出现同 split 重复或跨 split 泄漏，之后才创建不可变 `DatasetVersion/DatasetVersionRow`，更新 `Dataset.active_version_id`、行数与状态为 `active`，并把 import 标记为 `published`。正式版本只能读取，已有 `active_version_id` 的数据集禁止手工上传、正式行编辑或直接删除；缺省 `GET rows?view=active` 读取 `DatasetVersionRow`。

#### `GET /api/datasets/{id}/rows?pending_complete=true`

```json
{
  "items": [
    { "row_no": 3, "question": "", "reference": "x", "context": null, "pending_complete": true, "source_case_id": "uuid" }
  ],
  "total": 2
}
```

`pending_complete=true` 的行 **不进评分分母**。

#### `PUT /api/datasets/{id}/rows`

批量保存表格行与自定义扩展列（如 `tags`、`difficulty`、`precondition` 等）。

```json
{
  "rows": [
    { "row_no": 1, "q": "如何修改结算账户？", "r": "进入设置完成短信验证...", "c": "已绑定手机", "tags": "账户", "difficulty": "中等" }
  ]
}
```

#### `POST /api/datasets/ai-generate`

根据场景描述、种子样本扩写、PRD 文档提取或缺失字段补全，返回**未落库候选行**；前端允许人工删改后，必须再走 `PUT /api/datasets/{id}/rows` 保存。该接口不得暗中写入数据集版本。

```json
{
  "dataset_id": "uuid",
  "mode": "scene | seed | doc | fill_missing",
  "instruction": "生成跨境支付高频问答与边界风控问答",
  "source_text": "可选的 PRD / OpenAPI 文本",
  "seed": "可选的种子样本摘要",
  "rows": [],
  "max_count": 10,
  "model": "gpt-4.1",
  "temperature": 0.5
}
```

`fill_missing` 时 `dataset_id` 和待补全 `rows[]` 必填；其余模式至少提供 `instruction`、`source_text` 或 `seed` 之一。响应固定为：

```json
{
  "items": [
    { "row_no": 1, "q": "问题", "r": "标准答案", "c": "上下文", "tags": "支付", "difficulty": "中等" }
  ]
}
```

---

### 3.8 用例工作台

#### `GET /api/case-sets` / `GET /api/case-sets/{id}`

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "status": "generated | confirmed | cancelled",
  "generated_count": 40,
  "confirmed_count": 0,
  "folder_id": "uuid?",
  "column_schema": [{ "key": "owner", "name": "负责人", "type": "string", "sort_order": 1 }],
  "checks": [
    { "level": "error", "code": "no_core_positive", "message": "无核心正向用例" }
  ],
  "expires_at": "2026-09-24T12:00:00Z",
  "cases": []
}
```

`checks` 给确认页红字。`expires_at` = 进入 `awaiting_case_confirm` + 72h。

case item 包含：`id, strategy, priority, module, name, precondition, steps, expected, test_type, mapped, pending_complete` 及自定义扩展列。

#### `POST /api/case-sets`

创建新用例集。请求可含 `name, folder_id?, column_schema?`；`column_schema` 规则同数据集自定义列。

#### `GET /api/case-folders` / `POST /api/case-folders` / `PUT /api/case-folders/{id}` / `DELETE /api/case-folders/{id}`

用例目录树是业务数据而非前端偏好。folder item：`id, name, parent_id?, sort_order, created_at`；删除非空目录返回 `VALIDATION`。

#### `PUT /api/case-sets/{id}`

更新 `name`、`folder_id`、`column_schema`。已确认的用例集不可修改其策略、检查结果或目标映射，只允许返回 `VALIDATION`，避免破坏版本快照。

#### `PUT /api/case-sets/{id}/cases`

批量保存表格用例项与自定义列数据（即点即改后实时持久化）。

```json
{
  "cases": [
    { "id": "c-001", "strategy": "正向", "priority": "P0", "module": "登录", "name": "账密正确登录", "expected": "进入工作台", "precondition": "账号正常" }
  ]
}
```

#### `POST /api/case-sets/{id}/confirm`

确认用例入库，生成正式数据集版本快照。任务状态由 `awaiting_case_confirm` 转换为 `succeeded`。

```json
{ "ok": true, "mapping_target": "dataset | gold_qa", "target_id": "uuid" }
```

采纳率口径：`confirmed_count / generated_count`。

#### `POST /api/case-sets/{id}/cancel`

废弃用例集，任务置为 `cancelled`。

#### `POST /api/case-sets/{id}/map`

批量映射用例到目标基准数据集或知识库黄金问答。

```json
{ "target": "dataset | gold_qa", "target_id": "uuid", "case_ids": ["c-001", "c-002"] }
```

`target=dataset` 时：问句←用例名称、预期←expected、前置←context；缺 `question` 或 `reference` 的行进入目标集 `pending_complete`（不进评分分母）；**全部**映射行写 `source_case_id`，并在 `extras.source_case_set_id` 记录用例集 ID。`target=gold_qa` 时缺 `expected_doc_ids` 的项仅参与答案侧评分（M3；当前返回 `VALIDATION`）。目标 ID 类型不匹配返回 `VALIDATION`。

#### `POST /api/case-sets/ai-generate`

根据 PRD / OpenAPI / Excel 文档，按 6 大策略精细配比（正向 40% / 反向 25% / 边界 15% / 等价类 10% / 状态迁移 5% / 场景 5%）智能生成候选用例集。

```json
{
  "source_doc_id": "可选，已上传文件 ID",
  "source_text": "可选，PRD / OpenAPI 原文；与 source_doc_id 至少填一项",
  "strategy_weights": { "positive": 40, "negative": 25, "boundary": 15, "equivalence": 10, "state": 5, "scenario": 5 },
  "complexity": "medium",
  "max_count": 45
}
```

该接口只返回候选，不创建用例集：

```json
{
  "items": [
    { "strategy": "正向", "priority": "P0", "module": "收银台", "name": "余额支付成功", "expected": "订单核销成功", "precondition": "账户余额充足", "test_type": "核心业务" }
  ]
}
```

前端采纳后按 `POST /api/case-sets` → `PUT /api/case-sets/{id}/cases` 两步落库；任何一步失败都不得显示“创建成功”。

#### `POST /api/case-sets/{id}/ai-fill`

行级 AI 补全（原型用例工作台「AI 补全断言 / 补全属性」的落地路径补全，非新产品）。对用例集中**已存在**的用例行补全缺失字段（`expected` 断言、`precondition`、`test_type` 及已声明的自定义扩展列），返回**未落库候选值**；前端人工确认后必须再走 `PUT /api/case-sets/{id}/cases` 保存。已确认（`confirmed`）的用例集拒绝补全，返回 `VALIDATION`。

```json
{
  "case_ids": ["c-001", "c-002"],
  "instruction": "可选，补全侧重点说明",
  "fields": ["expected", "precondition"]
}
```

`case_ids` 必填且必须全部属于该用例集，否则 `VALIDATION`；`fields` 缺省时补全所有缺失字段。响应固定为：

```json
{
  "items": [
    { "id": "c-001", "expected": "进入工作台首页", "precondition": "账号已完成实名认证", "test_type": "核心业务" }
  ]
}
```

#### `GET /api/case-sets/import-template`

下载平台标准列 Excel 模板（`用例集` + `填写说明` 两个工作表）。响应文件流。登录后可用。

#### `POST /api/case-sets/{id}/import?mode=append|replace`

`multipart/form-data`，字段名 `file`。仅 `.xlsx` / `.xlsm`；`.xls` 返回 `VALIDATION` 提示另存。单文件 ≤10MB，有效用例 ≤2000 条。已确认或已废弃的用例集拒绝导入。

`mode` 缺省 `append`：追加写入，Excel「用例编号」若属于本集则更新该行，否则插入；`replace` 先清空本集全部用例再写入。

表头识别（列顺序不限，可出现在前 20 行）：

1. **platform**：平台导出列（用例编号、策略、优先级、模块、用例名称、前置条件、步骤、预期结果、测试类型）
2. **standard**：testcase-tools 标准列（用例编号、所属模块、用例标题、优先级、用例类型、前置条件、测试步骤、预期结果）
3. **simple**：简化列（模块、名称、步骤、预期）；缺策略默认「正向」，缺优先级默认 P1

无用例名称的数据行计入 `skipped_count`。「已映射」「待补全」列忽略。未识别的额外列写入扩展字段并并入 `column_schema`。

```json
{
  "ok": true,
  "format": "platform | standard | simple",
  "mode": "append | replace",
  "imported_count": 12,
  "skipped_count": 1,
  "generated_count": 13,
  "checks": []
}
```

#### `GET /api/case-sets/{id}/export?fmt=xlsx|xmind`

`fmt` 必填。响应文件流。Excel 8+。xlsx 固定列含用例编号，可再导入做往返。

---

### 3.9 知识库与黄金 QA 工作台

#### `GET /api/kb` / `POST /api/kb` / `GET /api/kb/{id}` / `PUT /api/kb/{id}` / `DELETE /api/kb/{id}`

```json
{
  "id": "uuid",
  "name": "default",
  "kind": "lightrag",
  "doc_count": 12,
  "is_core": false,
  "capabilities": { "projection": false, "rerank_compare": false },
  "owner_id": "uuid"
}
```

`kind`：`lightrag`（原生 query，支持切块）| `external_chat`（外部 RAG 服务本身挂在 profile，仅 `chat/completions`）。
`capabilities` 必含 `projection`、`rerank_compare` 两个布尔值；V1.0 都为 `false`。前端在 `false` 时保留原型区域但展示能力未启用，不可画示例投影或重排结果。`PUT` `{ "is_core": true }` 标为核心库写审计。

#### `POST /api/kb/{id}/documents`  multipart `file`

上传文档建索引；后端生成 `doc_id` UUID 写入 LightRAG metadata，自动执行分块与向量化。响应 `{ "doc_id", "filename", "status": "indexed" }`。

#### `GET /api/kb/{id}/documents`

返回当前知识库文档及索引状态：`{ "items": [{ "doc_id", "filename", "size", "status" }] }`。`status` 为 `indexing | indexed | failed`；列表不内嵌文本或切块。

#### `GET /api/kb/{id}/documents/{doc_id}/chunks?chunk_size=512&overlap=64`

返回服务端按请求参数生成的切块预览，供原型的切块流使用：

```json
{ "items": [{ "chunk_id": "uuid#c01", "tokens": 486, "text": "..." }] }
```

该接口只读；调整 `chunk_size` / `overlap` 不得在浏览器用样本文本伪造预览。

#### `DELETE /api/kb/{id}/documents/{doc_id}`

删除指定文档及其向量切块索引。

#### `POST /api/kb/{id}/query`

执行 LightRAG 原生 4 模式检索测试（Playground），返回 Top-K 切块、相似度得分与评测指标。V1.0 不返回实验性的投影或 rerank 比对结果。

```json
{
  "query": "退款多久到账？",
  "mode": "hybrid | local | global | naive",
  "k": 5
}
```

响应：

```json
{
  "items": [
    { "chunk_id": "d-01#c03", "doc_name": "product-manual.pdf", "similarity": 0.87, "text": "...", "hit": true }
  ],
  "metrics": { "hit_rate": 0.80, "mrr": 0.74, "recall": 0.85, "contain": 0.83 }
}
```

#### `GET /api/kb/{id}/gold-qa` / `POST /api/kb/{id}/gold-qa`

黄金 QA 上传与维护。列 `question, reference, expected_doc_ids[]?`；覆盖上传后 `version += 1`。无 expected_doc_ids 的样本不进 Hit Rate 评估分母。支持通过大模型自动从已索引文档中抽取问答对并自动关联切块。

---

### 3.10 任务

`POST /api/tasks` 的 JSON **等于** 确认卡 payload（§6），再加可选 `session_id`。

```json
{
  "session_id": "uuid",
  "kind": "benchmark",
  "profile_ids": ["uuid"],
  "dataset_id": "uuid",
  "run": {},
  "with_stress": false
}
```

成功：

```json
{
  "id": "uuid",
  "status": "queued",
  "kind": "benchmark",
  "parent_task_id": null
}
```

规则：

- 未通过字段校验 → 400 `VALIDATION`，**不入队**（与确认卡未 ack 同等）。  
- 会话存在待确认卡 → 409 `CONCURRENCY`，必须由确认卡作者确认或取消后再创建。
- 会话已有非终态任务（含压测子任务）→ 400 `VALIDATION`（占槽），前端应已禁用按钮。  
- 平台 `max_running_tasks` 满 → **仍** `queued`（3.4），可附 `warning: "CONCURRENCY"` 字段（可选）。  
- `kind=stress` 一般由 worker 在质量 `succeeded` 且 `with_stress=true` 时创建；人手 POST 须带 `parent_task_id`，且父任务必须 succeeded。  
- 一任务一种 `kind`。V1 禁止 Benchmark+RAG 混单。
- `kind=benchmark` 且目标数据集存在 `active_version_id` 时，服务端在创建事务中锁定数据集并把 `dataset_version_id`、`dataset_version_no` 写入 `config` 快照；后续发布或 staging 编辑不影响该任务。

#### `GET /api/tasks?status=&kind=&offset=&limit=`

全员。item：`id, kind, status, progress, dataset_id, kb_id, parent_task_id, creator_id, created_at, report_id?`

`progress`：`{ percent?, done, total, message }`

#### `GET /api/tasks/summary?from=&to=`

任务中心 24h 趋势、六态计数与可追溯诊断摘要。`from/to` 均为 ISO 8601；未传时返回最近 24h。服务端从 `tasks/task_events` 聚合，前端不得自行合成趋势或“AI 诊断”。

```json
{
  "range": { "from": "2026-08-17T00:00:00Z", "to": "2026-08-18T00:00:00Z" },
  "status_counts": { "queued": 2, "running": 1, "succeeded": 8, "failed": 1, "cancelled": 0, "awaiting_case_confirm": 0 },
  "series": [{ "ts": "2026-08-18T09:00:00Z", "queued": 1, "running": 1, "succeeded": 2, "failed": 0 }],
  "diagnosis": [{ "code": "UPSTREAM_SPIKE", "message": "上游 5xx 在 10 分钟内升高", "task_ids": ["uuid"] }]
}
```

#### `GET /api/tasks/{id}`

详情 + `config` 快照（确认卡 JSON）+ `events`（`task_events` 时间线：`at, level, message`）。

#### `POST /api/tasks/{id}/cancel`

```json
{ "ok": true, "status": "cancelled" }
```

权限：任务创建者。
评测/RAG/用例：当前样本结束后停。  
压测：**立即**停发。  
前端 Dialog 文案必须按 kind 分流，接口本身一个。

#### `POST /api/tasks/{id}/rerun`

新任务拷 `config`，新 `id`，`queued`。不复活旧行。

#### `POST /api/tasks/{id}/approve-stress`  M4

`{id}` 为 **压测子任务** 或质量任务（实现须能解析到对应 `kind=stress` 子任务）。  
会签人 ≠ 创建者（`prod` 发压须另一名正常成员确认）。
未会签：子任务保持 `queued`，`NEED_APPROVAL`；质量报告仍保留。写审计。

#### `GET /api/tasks/{id}/stress-series`  M4

`{id}` 为压测任务。

```json
{
  "task_id": "uuid",
  "points": [
    { "ts": "2026-11-20T08:01:00Z", "qps": 12.3, "rt_ms": 210, "error_rate": 0.01 }
  ]
}
```

供 Chart.js。**禁止**把本数组塞进 WS `progress`。Grafana 用同一 `task_id` 对 `job=ai-eval-stress`。

---

### 3.11 报告中心

#### `GET /api/reports?kind=&task_id=&offset=&limit=`

获取评测报告列表（支持根据评测类型 kind 过滤）。

```json
{
  "items": [
    {
      "id": "r-bm-1",
      "title": "Benchmark 报告 · smoke-20 v3",
      "kind": "benchmark",
      "task_id": "e5f2b8",
      "child_stress_report_id": "r-st-1",
      "created_at": "2026-08-15T06:02:00Z"
    }
  ],
  "total": 1
}
```

#### `GET /api/reports/{id}`

登录 Cookie 或 `?share=` 未过期免登访问。  
`?fmt=md` → `text/markdown` 导出 Markdown 报表。

JSON 公共头：

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "child_stress_report_id": "uuid?",
  "parent_report_id": "uuid?",
  "kind": "benchmark",
  "created_at": "...",
  "snapshot": { "dataset_version": 3, "metric": "contain", "profile_ids": [] },
  "baseline_id": null,
  "degraded": false
}
```

**benchmark** 另含：`scores[]`（每 profile 主指标、exact、rouge_l、fail_rate、latency、judge 得分及分维度 breakdown）、`judge_info`（裁判模型与评语归因）、`sample_items[]`。  
**rag** 另含：`hit_rate_at_k`、`mrr`、`recall_at_k`、`k`、`answer_contain`、`modes[]`、`hit_denominator_note`（无 expected_doc_ids 样本不进分母）、`degraded`（≥5pp 相对基线）。  
**stress** 另含：`qps` `rt` `error_rate` `ttft_ms?` `tpot_ms?` `tokens_per_s?` `sla_p99_ms?` `sla_met?`（未填 SLA 则不出现 `sla_met`）`knee?` `est_cost_usd`、`time_series[]`。

#### `GET /api/reports/{id}/samples?filter=all|diff|fail&offset=&limit=`

获取样本级逐题比对与 Bad Case 归因列表，含 `p1/p2` 模型预测内容、相似度切块、Judge 裁判评语与 Raw 请求/响应报文。

#### `POST /api/reports/{id}/share`

```json
{ "url": "https://.../reports/{id}?share=token", "expires_at": "..." }
```

生成公开只读链接，有效期 7 天，免登录访问。

#### `POST /api/reports/{id}/baseline`

冻结当前任务为基线版本（写操作审计）。

```json
{ "frozen": true, "task_id": "uuid" }
```

Benchmark：同 dataset 版本 + 主指标才能对比 Δ 差值。  
RAG：同 kb + gold 版本。  
解冻 `{ "frozen": false }` 同样写审计。

---

### 3.12 设置与审计

#### `GET /api/admin/settings`

已登录成员可 GET；敏感密钥不回显。

```json
{
  "agent_profile_id": "uuid",
  "agent_reasoning": {
    "enabled": true,
    "effort": "medium"
  },
  "max_running_tasks": 3,
  "max_inflight_model_calls": 8,
  "default_max_usd": 5,
  "stress": {
    "host_whitelist": ["10.0.0.8"],
    "max_qps": 500,
    "max_duration_s": 1800,
    "price_per_1k_tokens": 0.002
  },
  "notify": {
    "wecom": false,
    "email": false,
    "webhook": false
  }
}
```

`agent_reasoning` 由 Agent 新回合读取。`enabled=true` 时请求模型生成 reasoning，并最多投影一条固定过程摘要到 `thought` 折叠卡；助手正文仍只走 `assistant_delta` / `assistant_message`。上游 reasoning 无论中文、英文或包装格式，均不得原样出站：它可能含未执行动作或错误中间判断，服务端统一下发短摘要到 `thought.stream=think` 与 `think_final`。`effort` 支持 `low`、`medium`、`high`、`xhigh`、`max`，具体可用值由上游模型决定；普通不支持推理控制的模型不会发送未知专用字段。Gemini 3.x 通过 OpenAI 兼容接口时，适配器发送 `extra_body.google.thinking_config.thinking_level` 与 `include_thoughts=true`，`xhigh/max` 映射为 Gemini 的 `high`；返回的 `reasoning_content`、`reasoning`、`thought` 或 `thinking` 增量统一归入 `thought`。关闭时网关过滤 reasoning 增量，支持显式关闭的模型同时发送关闭参数；Gemini 3.x 即使关闭展示，也不额外请求 thought summary。该配置不暴露隐藏思维链，不改变公共事件头中的 `session_id` / `task_id`。

`notify` 的 URL/Token 仅 PUT 写入、GET 只给布尔或掩码。M1 可只返回 `agent_profile_id` 与并发默认；其余 M4 补齐。

#### `PUT /api/admin/settings`

全员同权（部分配置字段）。白名单 / 单价 / 密钥相关变更写入审计日志。

#### `GET /api/admin/audit-logs?from=&to=&offset=&limit=`

查询平台合规审计日志。item：`at, actor_id, action, target, detail`（无 Key）。  
action 至少包含：`login_failed` `role_change` `key_change` `baseline_freeze` `baseline_unfreeze` `whitelist_change` `prod_approve` `prod_stress`。

---

### 3.12.1 压测安全治理与白名单

#### `GET /api/admin/stress/settings` / `PUT /api/admin/stress/settings`

维护压测全局安全阈值（默认 QPS 上限、最大发压时长、60s 错误率 ≥ 50% 熔断阈值、Token 计费单价）。

#### `GET /api/admin/stress/whitelist` / `POST /api/admin/stress/whitelist` / `DELETE /api/admin/stress/whitelist/{id}`

维护目标发压 Host 白名单（支持 IP、域名、Port 以及 scope 环境范围匹配：`test / staging / prod`）。

```json
{
  "id": "wl-01",
  "host": "model-gateway.internal",
  "scope": "test,staging,prod",
  "creator": "admin",
  "created_at": "2026-08-14"
}
```

未在白名单中的目标禁止发压，直接返回 `WHITELIST` 阻断错误码。

#### `GET /api/admin/stress/usage`

获取近 7 天峰值 QPS 时序数据、阈值触碰率及月度累计开销。

#### `GET /metrics`

Prometheus 内置可观测性指标端点（内网 HTTP GET），输出前缀为 `ai_eval_stress_`，携带 `env, model, task_id` 标签。

---

### 3.12.2 用户域工作区（V1.75，F1/G1；V1.82 起承接原 §3.12.2 编号）

> **V1.82 功能下线登记**：原 §3.12.2「管理端工作区管理（会话沙箱文件夹，V1.57）」整节移除——
> `/api/admin/workspaces` 五个接口（列表 / 磁盘统计 / 会话文件展开 / 会话沙箱清理 / 孤立目录清理）
> 与前端管理页一并下线，工作区生命周期统一由用户域「我的工作区」承载（会话绑定语义不变）。


用户工作区 = 用户自管数据域（目录 `data/workspaces/<id>`，与 legacy 会话目录同根共存）。V1.76（F3/G5）会话绑定已接线：`POST /api/sessions` 携带 `workspace_id/scope_path` 创建绑定会话（仅 private、创建时固化、无换绑端点；见 §3.4），运行期沙箱根由 `resolve_session_sandbox` 解析为工作区 scope。鉴权：仅属主；写入均写 AuditLog（`workspace_create/rename/delete/purge/folder_create`、解绑 `workspace_unbind` 随 purge、绑定 `session_workspace_bind`）。

#### `GET /api/workspaces?include_deleted=&offset=&limit=`

列出当前用户工作区（默认仅活跃行）。响应 `{items:[{id,name,owner_id,created_at,updated_at,deleted,folder:{file_count,total_bytes,updated_at}|null}],total}`。

#### `POST /api/workspaces` body `{name}`

新建工作区（表 + 数据目录原子创建）；`name` 每属主**活跃**唯一（部分唯一索引；软删同名行不占名——复活语义随 F3 的 legacy 导入）。

#### `PUT /api/workspaces/{id}` body `{name}`

改名（活跃行；活跃重名 → `VALIDATION`）。

#### `DELETE /api/workspaces/{id}?purge=`

注销（默认）= 软删（置 `deleted_at`，目录保留并进入 legacy 清理面；未来绑定会话 resolve 按行态 fail-closed）。`purge=true`：须先注销；行锁（全局锁序 workspace → sessions）内先**显式解绑**全部 `sessions.workspace_id` 引用（审计；FK `ON DELETE RESTRICT` 兜底，**禁用 SET NULL**——静默回落违背 fail-closed）再删目录树与行；存在活跃（未软删）绑定会话 → `CONCURRENCY`。非属主 → `UNAUTHORIZED`。

#### `GET /api/workspaces/{id}/files?path=`

一层目录列表（目录/文件/链接分类，不递归不跟随链接）：`{entries:[{name,kind:"dir"|"file"|"link",size,updated_at}],total}`。`path` 为相对 scope，段级校验（拒 `.`/`..`/分隔符）+ 逐段 `realpath` 前缀重验（符号链接逃逸 → `VALIDATION`）。

#### `POST /api/workspaces/{id}/files` body `{path,name}`

在已存在父目录下新建单段文件夹（幂等）；`name` 校验同目录段规则。

#### `GET /api/workspaces/{id}/files/raw?path=&download=`

获取工作区内指定文件的原始二进制/流式内容。
- 参数：`path`（必须，相对路径，段级校验防穿越）；`download`（可选布尔，默认 `false`）。
- 行为：
  - 当 `download=false`（默认）时，`Content-Disposition` 为 `inline`，并根据文件后缀识别准确的 MIME 类型（如 `video/mp4`、`video/webm`、`audio/mpeg`、`image/png`、`application/pdf` 等；未知按 `application/octet-stream`）。支持浏览器内置原生音视频播放器在线播放与 HTTP 206 Partial Content（Range 分段请求，拖拽进度秒开）。
  - 当 `download=true` 时，`Content-Disposition` 为 `attachment; filename="..."`，强制触发浏览器下载。
- 权限：仅工作区属主；非属主 → 401/403；文件不存在 → 404；路径越界/符号链接 → 400 `VALIDATION`。

#### `POST /api/workspaces/{id}/files/upload`（`multipart/form-data`）

向工作区指定目录下上传文件。
- 表单参数：
  - `file`: 上传的文件二进制（`UploadFile`）。
  - `path`: 目标父目录相对路径（可选，默认为空字符串即工作区根目录）。
- 校验与行为：
  - 路径与文件名安全校验：拒相对越界（`..`、`/`、反斜杠、空文件名），只允许在合法父目录下写入；
  - 配额核验：写入前统计工作区现存大小 + 上传文件字节，若超过用户工作区配额（默认 1GiB）则直接以 400 `QUOTA_EXCEEDED` 拒绝，防止磁盘耗尽；
  - 写入工作区对应物理目录，若同名文件存在则覆盖；
  - 记录合规审计日志 `workspace_file_upload`。
- 成功响应：
```json
{
  "name": "demo.mp4",
  "path": "videos/demo.mp4",
  "size": 10485760,
  "updated_at": "2026-09-13T13:40:00"
}
```

---

### 3.13 调度内核与 Worker 节点管理

#### `GET /api/dispatch/overview`

获取调度中心大盘指标与内核雷达状态。

```json
{
  "online_workers": 8,
  "total_workers": 10,
  "queue_depth": 3,
  "avg_dispatch_cost_ms": 81,
  "assigned_today": 126,
  "strategy": "负载均衡",
  "max_running_tasks": 4,
  "heartbeat_interval_ms": 500
}
```

#### `GET /api/dispatch/workers`

获取全部 Worker 执行节点池状态列表。

```json
{
  "items": [
    {
      "id": "worker-01",
      "name": "GPU-Node-A1",
      "caps": ["benchmark", "judge"],
      "state": "busy",
      "load_percent": 62,
      "ram_usage": "4.8GB/16GB",
      "current_task": "a1f3c2 · smoke-20 v3 (shard 2/5)",
      "weight": 100
    }
  ]
}
```

#### `POST /api/dispatch/workers`

注册新 Worker 执行节点：`{ "id", "name", "caps": [], "weight": 100 }`。

#### `PUT /api/dispatch/workers/{id}`

修改节点状态或权重（如维护下线、排空 `draining`、更新能力标签）：`{ "state", "weight", "caps" }`。

#### `PUT /api/dispatch/config`

更新分发策略与全局并发容量：`{ "strategy": "负载均衡" | "优先级抢占" | "亲和性", "max_running_tasks": 4 }`。

#### `GET /api/dispatch/events?after_id=&limit=`

调度中心的分配日志流。按单调 `id` 升序返回，`after_id` 缺省时返回最近记录；轮询只拉增量。日志由调度器/worker 写入，浏览器不得生成或改写。

```json
{
  "items": [
    {
      "id": 1042,
      "at": "2026-08-18T10:22:00Z",
      "event": "assigned | started | draining | succeeded | failed",
      "task_id": "uuid?",
      "worker_id": "worker-01?",
      "message": "任务已分配至 GPU-Node-A1"
    }
  ],
  "next_after_id": 1042
}
```

---

## 4. WebSocket（F-AGT-01 / 02）

### 4.1 连接

1. `POST /api/auth/ws-ticket`  
2. `GET /ws/agent?ticket={ticket}&session_id={uuid}&last_event_id={n}`  
   - 首次：前端**先** `POST /api/sessions` 再带 `session_id`；可无 `last_event_id`。无 `session_id` 时服务端可建空会话（兼容），会话列表与 `/new` 仍以 REST 为准。  
   - 重连：必须带 `session_id` + `last_event_id`，服务端从 `ws_events` **补发** `event_id > last_event_id` 的事件。  
3. 关闭码：短票非法/过期 **4401**；会话不存在、已软删除或当前成员无权访问 **4404**；正常断开 **1000**。前端 4401 重新领票，4404 停止重连旧会话并回到会话列表。
4. **禁止** `?token=` 长期 JWT。

心跳：30s；传输层 ping/pong。应用层服务端可发 JSON `pong`。前端不发 JSON `ping`。

Harness 回合必须丢到后台 Task，**不得**在 `receive` 循环里 `await` 整轮规划（否则 `/stop` 进不来）。长任务只入队，由 Worker 写 `progress` / `report` / `error`。

### 4.2 公共头（服务 → 前端）

```json
{
  "event": "thought",
  "session_id": "uuid",
  "task_id": null,
  "event_id": 42,
  "ts": "2026-09-21T12:00:00Z",
  "vocab_version": "event.v1",
  "payload": {}
}
```

`event_id` 在会话内单调递增。`task_id` 在入队后才有。`vocab_version`（V1.71，可选字段、服务端恒发）：当前事件词汇表版本（见 §4.3 词汇表版本语义与演进纪律）；旧客户端按「忽略未知字段」原则可安全跳过，**无前端改动**。

### 4.3 服务 → 前端（V1.64 当前事件）

**词汇表版本语义与演进纪律（V1.71 起，V1.75 现值 `event.v5`）**：本节事件表 +
api/worker 直产事件（`confirm_ack` / `tool_approval_ack` / `task_cancelled` /
`session_title` / `clarify_ack` / `approval_terminal` / `context_trim`）的
词汇表唯一事实源为 `backend/shared/event_vocab.py`（api/worker 共用）。当前
版本 `vocab_version = "event.v5"`（公共头 §4.2 恒发）。**增删持久事件 kind
必须递增版本**（`event.v1` → … → `event.v5`），演进理由随本文件修订记录
留档——V1.72 新增 `clarify_ack`（#1 回执）升 `event.v2`；V1.73 新增
`approval_terminal`（#3 审批终态）升 `event.v3`；V1.74 新增 `context_trim`
（#2 窗口裁剪留痕）升 `event.v4`；V1.75 新增 `fabrication`（原生工具 P3
编造对账审计）升 `event.v5`；未经契约评审不得新增/恢复事件 kind。历史
`ws_events` 无版本行按当前版本解释（只读兼容）；服务端转发护栏：未知 kind /
版本不符默认告警并跳过，`event_vocab_strict=true` 时 fail-closed 拒收并落
`error`。

| event | payload | 前端渲染 |
| --- | --- | --- |
| `user_message` | `{id,role:"user",content,attachments,author,client_message_id?,created_at}`；持久化并可回放 | UserBubble |
| `assistant_delta` | `{role:"assistant",text}`；瞬态、不占 event_id | AssistantBubble 流式增量 |
| `assistant_message` | `{id,role:"assistant",text,reply_latency_ms?,created_at}`；持久化并可回放 | AssistantBubble |
| `response.completed` | `{finish_reason:"stop"\|"cancelled"\|"error",role:"assistant"}`；混合引擎开启时额外携带 `engine`（`"direct"\|"chat"\|"workflow"\|"agent"`）、`router_confidence`（0–1）、`router_reason`（脱敏理由）三个可选审计字段；V1.67 起 `engine="agent"` 时另携带 `agent_id`（Worker ID，见 §3.6.3）；持久化并可回放 | 结束流式状态；`engine` 即实际执行引擎（V1.67：workflow=W0–W7 DAG，agent=TAOR） |
| `tool_call` | `{call_id,name,arguments}`；V1.67 恢复：orchestrator 发起 Act 时产出，`arguments` 为脱敏摘要（值截断/路径取末段/对象折叠），**不含敏感全文**；持久化并可回放 | ToolCard：按 `call_id` 关联，展示名称与参数摘要、等待结果 |
| `tool_result` | `{call_id,name,ok,truncated,redacted,data?,error?,source?,latency_ms}`；V1.67 恢复：工具终态受控投影，`data` 仅含 `display_data` 摘要、失败 `error` 为脱敏原因（禁止堆栈/密钥/绝对路径/上游原文），**不含 Observation 全文**（Observation 只作模型输入，不进入 WS 持久事件/消息历史/检查点正文）；持久化并可回放 | ToolCard 终态：成功/失败状态与摘要 |
| `progress` | `{percent,done,total,message}`；Worker 任务进度 | ProgressDock |
| `report` | `{report_id}`；Worker 报告就绪 | ReportCard |
| `task_cancelled` | `{status:"cancelled",kind}`；公共头必须带 `task_id`，持久化并可回放 | 关闭对应 ProgressDock，并结束取消中状态 |
| `confirm` | TaskSpec（§5 / §6）+ 非 TaskSpec 元数据 `confirm_author:{id,username,display_name?}`；持久化并可回放。**V1.67 恢复**：仅混合引擎开启且 `engine=workflow` 时由 Workflow 子图 W5 产出；同一会话同一时刻至多一张待确认卡（落库 `sessions.pending_confirm`） | ConfirmCard 可编辑卡；仅 `confirm_author.id` 成员可确认、取消或提交 patch |
| `confirm_ack` | `{ok:true,task_id:"uuid",message}` 或 `{ok:false,message}`；持久化并可回放（V1.67 恢复） | 更新最近一张 ConfirmCard 的确认/取消状态；`ok=true` 后由 ProgressDock 承接任务进度 |
| `clarify` | `{id,questions:[{id,question,header?,options:[{label,description?}],multi_select,required,type:"radio"\|"checkbox"\|"text"}]}`；持久化并可回放。**V1.72 转正（PRD 既有范围）**：仅混合引擎开启且 `engine=agent` 时由 `ask_user_question` 图内 `interrupt()` 产出（≤8 题三题型，用户一次作答）；`meta`（`schema_version`/`confirm_type="clarify"`/`thread_id`/一次性 `resume_nonce`/`owner_id`/`created_at`）只落库 `sessions.pending_confirm`，**不广播**给前端；与 `confirm` / `tool_approval` 三类卡共用单行互斥（同一时刻至多一张） | ClarifyCard：仅命令原发起成员作答并提交；作答后回合按 `answers[]` 续跑 |
| `clarify_ack` | `{ok:true,id}`；持久化并可回放。**V1.72 新增**：服务端在 `clarify_reply` 清卡提交后的回执（resume 至多一次语义与 `tool_approval_ack` 同构） | ClarifyCard 盖章已提交（乐观态确认），回合随后续事件续跑 |
| `tool_approval` | `{id,call_id,name,command,reason,risk_level,sandbox_scope,allowed_decisions}`；持久化并可回放。**V1.70 恢复 / V1.77（F5）语义收敛**：仅混合引擎开启且 `engine=agent` 时由图内 `interrupt()` 产出——词表与静态裁决删除后（V1.75/G4）无文本型生产者；V1.77 起为 **bash read-only 档拒写升档卡**（read-only 只约束 bash，绑定会话文件工具仍可写——§6.1.1 口径；`reason="escalation"`，`tool_result` 先落 `error_code=DENIED` 帧，approve 后同命令以 workspace-write 重放恰好一次；受 `agent_escalation_approval_enabled` 门控，默认关）；`meta`（`schema_version`/`confirm_type`/`thread_id`/`resume_nonce`/`owner_id`/`created_at`）只落库 `sessions.pending_confirm`，**不广播**给前端；同一会话同一时刻至多一张待审批卡（与 `confirm` / `clarify` 互斥，落同一 `pending_confirm` 行锁）。V1.73：卡 TTL `agent_approval_ttl_seconds`（config，默认 3600）过期后失效，失效判定以 `meta.created_at` 幂等兜底（不依赖扫描进程存活性） | ApprovalCard：仅命令原发起成员可 `approve|reject`，确认前不调用 Runner；expired/cancelled 失效态禁操作 |
| `approval_terminal` | `{approval_id,outcome:"expired"\|"cancelled"\|"voided"\|"recovery_failed",card_type?,reason?}`；持久化并可回放。**V1.73 新增 / F5-G6 扩展 / V1.78 增 `card_type`**：审批卡终态——api 后台 TTL 扫描对过期卡清卡并广播 `expired`；`/stop` 放弃悬挂审批卡时广播 `cancelled`（`rejected` 仍由 `tool_approval_ack(action="reject")` 承载，不新增重复 kind）；**`voided`（检查点缺失作废）**：ack 行锁内预检线程不可恢复 → 清卡 + 作废终态 + error（不静默放行不留卡残留）；**`recovery_failed`**：resume 恢复回合失败 → 终态广播（卡已先行清空）。V1.78：payload 增可选 `card_type`（`"approval"`\|`"clarify"`，缺省 `"approval"` 兼容旧事件）——`recovery_failed` 对澄清卡恢复失败同样广播并携带 `card_type="clarify"`（前端路由至 ClarifyCard `failed` 终态），`expired`/`voided`/`cancelled` 恒为审批卡；卡清后 ack 一律拒绝且不 resume | ApprovalCard 失效态四终态按钮禁操作；ClarifyCard V1.78 增 `failed` 终态（恢复失败只读展示） |
| `context_trim` | `{reason:"compact"\|"tail_window",dropped,kept,in_scope_total,keep_from_id?,limit}`；持久化并可回放。**V1.74 新增（服务端留痕为主，前端不渲染）**：回合装配模型上下文时发生窗口裁剪（compact `keep_from` 截断 / 末 20 条尾窗截断）即落一条；payload 仅元信息，**不含被裁消息原文**（观察纪律） | 不渲染（审计/回放一致性用） |
| `session_title` | `{title,source:"ai"}`；持久化并可回放 | 同步会话标题 |
| `error` | `{code,message}`；异常消息必须脱敏 | ErrorStrip + Toast |
| `fabrication` | `{claim,repairs}`；持久化并可回放。**V1.75 新增（原生工具 P3，服务端审计为主，前端不渲染）**：reflect 编造对账检测——收尾答复声明「发送确认卡/创建入队任务」但本回合无对应工具成功执行记录，提示修正一次后仍复现 → 判 reject 时落一条审计留痕；payload 仅声明类别与已用修复次数，不含答复正文 | 不渲染（审计/对账用） |
| `pong` | `{}`；瞬态 | 不渲染 |

Agent 图（V1.67，H3）产生 `tool_call` / `tool_result`（ToolCard 摘要）；V1.70（H5）起 `engine="agent"` 危险 bash 另产生 `tool_approval`（审批卡）；V1.72 起 `ask_user_question` 另产生 `clarify`（澄清卡，B 路线与审批卡同构）。不产生 `thought`、`tool_progress`、`tool_output_delta`、`plan` 或其确认/回复事件（无生产者）。历史 `ws_events` 中 V1.63 之前的旧事件（含旧 ToolCard 形态与 V1.62 旧澄清卡）仍不由前端渲染，本版起新会话内产生的新 `tool_call` / `tool_result` / `clarify` 正常渲染并随历史回放。`task_cancelled` 是收包循环的任务控制事件，不属于 Agent ToolCall。

Workflow 阶段叙述（V1.68，H2）：`engine=workflow` 时 W5 发卡与 W7 收尾各产出一条用户可读的 `assistant_message` 阶段叙述；单回合多条、`response.completed` 仍为整轮结束。叙述不是 Observation 原文，不得粘贴工具结果。W0 技能零命中或并列命中时以错误提示就地收尾（非法/已禁用技能同路径），**不**恢复 `clarify` 事件、不写 `pending_confirm`、不占任务槽。

Router 审计字段（V1.66 起，V1.67 语义升级）：`response.completed` 的 `engine` / `router_confidence` / `router_reason` 仅在 `hybrid_engine_enabled=true` 时出现，旧客户端忽略未知字段即可，断线补发按 `last_event_id` 原样回放。`engine` 由图内 Router 节点一次性写入、本轮不可变；V1.67 起 `workflow` 与 `agent` 均已真实执行（`engine` 即执行引擎，前端可据此渲染 TAOR 工具卡）；`agent` 分支收尾 payload 另带 `agent_id`。取消 / 异常收尾路径（`finish_reason="cancelled"|"error"`）若 Router 已执行，同样携带三个审计字段。`router_reason` 为脱敏短文本（≤120 字符），禁止包含 Observation、密钥、完整提示词或上游原文。

#### 4.3.1 原生工具契约（V1.62 表结构，V1.67 起 H3 Agent TAOR 重新接线）

V1.67（H3）起，`engine="agent"` 分支经 `discover` 按 Worker 白名单（§3.6.3 `allowed_tools`，仅 ToolRegistry 注册全名）注入工具视野后真实执行下表原生工具，`tool_call` / `tool_result` 事件与 ToolCard 按 §4.3 恢复。工具链固定为 Schema → 门禁 → 权限 → 并发 → 脱敏；`platform.tasks.task.*` 长任务桥不进入任何 Worker 视野（仅 Workflow W6 调用）。`worker.sandbox` 的 `bash`（code 权限）在 H5 批次 2（`PgCheckpointer` 生产切换 + 网关粘性路由 + 重启恢复演练 + 安全评审）完成前不可被 discover 选中，下表保留为受控执行基础设施与未来扩展契约。

| 工具 | 输入 Schema（必填；可选） | 成功 `tool_result.data` 安全投影 | 执行权限边界 | 失败恢复 |
| --- | --- | --- | --- | --- |
| `read` | `path`；`offset?`/`next_offset?`、`limit?≤2000` | `read.path/total_lines/start_line/end_line/next_offset/preview` | 仅会话工作区相对路径；≤20MB；模型正文≤600,000 字符；浏览器预览≤`TOOL_PREVIEW_MAX_CHARS`（默认与窗口对齐） | 仅 `TIMEOUT` 可修复重试；路径/分页错误提示相对路径或 `next_offset` |
| `read_image` | `file_path` | `read_image.path/media_type/size_bytes/width/height` | 仅会话工作区相对路径；仅 PNG/JPEG/GIF/WebP，≤4MB；图片二进制仅作为**当前回合**模型 tool-result 图文块，持久事件、恢复快照与 ToolCard 均只保存元数据摘要 | 不自动重试；格式、大小或路径无效时改用受支持图片或正确相对路径 |
| `glob` | `pattern`；`path?` | `glob.query/count/truncated/preview` | 仅工作区普通文件；不含 `/` 的 pattern 匹配任意层级文件名；排除 `.git/.hg/.svn`、`node_modules`、`__pycache__` 与符号链接；最多 500 条 | 不自动重试；缩小 `path` 或使用更具体 `pattern` |
| `grep` | `pattern`；`path?`、`include?` | `grep.query/count/truncated/preview` | 仅工作区普通文本文件；Python 正则，返回 `path:line:text`；跳过二进制、版本库、依赖缓存与符号链接；最多 500 条或 60,000 字符 | 不自动重试；缩小 `path`/`include`/正则范围 |
| `write` | `path`、`content` | `write.path/bytes_written/lines_written/preview` | 仅会话工作区；≤2MB；排他新建 + fsync，绝不覆盖已有文件 | 不自动重试；文件存在时改用新路径或先 `read` 后 `edit` |
| `edit` | `path`、`old`、`new` | `edit.path/replacements=1/old_length/new_length` | 仅会话工作区；原子替换；`old` 必须匹配 | 不自动重跑；不匹配时返回邻近行脱敏建议，先 `read` 再调整 |
| `bash` | `command` | `bash.exit_code/preview/preview_truncated` | 独立 Runner 的一次性 bwrap（档位只声明文件效果）：read-only 档 scope 只读 bind，写入被内核拒（EROFS）→ `tool_result` 错误码 `DENIED` 且自动产生 `reason="escalation"` 升档卡（V1.77/F5，approve 后同一命令以 workspace-write 重放恰好一次；`agent_escalation_approval_enabled` 默认关）；workspace-write 档 scope 可写。无网络、唯一可写工作区、CPU/内存/进程/墙钟限制恒开启 | 仅 `TIMEOUT` 表示可缩小范围后再试；`DENIED` 且升档被拒 → 失败观察；沙箱不可用与档位拒绝绝不降级或自动重跑 |
| `web_search` | `query`；`limit?≤10` | `search.query/results` | 仅服务端配置搜索服务；Key 不入事件/日志 | `TIMEOUT`/`UPSTREAM` 可调整关键词后重试一次 |
| `web_fetch` | `url`；`format?=markdown\|text` | `web.url/title/format/preview/preview_truncated/preview_limit_chars` | 仅公开 HTTP(S)；每次 DNS 与重定向都做 SSRF 校验；禁止凭据、内网、回环和保留地址；模型正文≤60,000 字符；浏览器预览≤`TOOL_PREVIEW_MAX_CHARS`（默认 600,000，与 `read` 对齐——卡片所见即模型真实读取内容）；正文提取：Firecrawl（已配置时）→ trafilatura → 内置 `_TextExtractor` 降级链 | 仅 `TIMEOUT`/`UPSTREAM` 可重试；SSRF/非法 URL 不重试 |
| `task` | `goal`、`steps[]` | `task.goal/steps[]` | 仅内存清单，不写库、不入队、不绕过确认卡 | 补齐目标/有限步骤后重试 |

`task.create/status/cancel` 仍是 MCP 长任务桥：会话/用户/任务归属由平台注入，`task.create` 受活动任务占槽和“先评后压”门禁，且只入队/查询/取消，绝不在对话回合等待 Worker 终态。

实时输出规则：`bash` 由 Runner 在 bwrap stdout 产生完整行时逐行转发；`read` 读取时按完整行块转发；`write` 仅在原子写入成功后转发与最终结果相同的受控内容预览。所有瞬态输出按 `call_id` 关联，累计最多 `TOOL_PREVIEW_MAX_CHARS` 字符（默认 600,000，见 V1.45）；浏览器不得把它写入本地历史、持久事件或日志。断线期间的增量不补发，客户端继续等待同一 `call_id` 的最终 `tool_result`。

失败恢复字段：`recovery.retryable` 只表示可在修复参数后再次发起调用，**不代表平台自动重试副作用工具**；`max_auto_repairs` 是 Agent reflect 的有界修复上限；`repair_hint` 必须脱敏，禁止出现堆栈、SQL、密钥、绝对路径或上游原文。

共享流规则：`assistant_delta`、`tool_progress` 与 `tool_output_delta` 仅向同一 `team` 会话内的**在线**成员广播；
`thought.stream="think"` 只发送给本轮发起连接，不向协作者广播，且只能是单条固定过程摘要；不得按推理字词持续推送。工具进度与工具输出增量允许按间隔或完整行合并后再发，避免一字一帧；这些瞬态增量不落库、
不占单调事件号；中途加入/断线重连者从后续增量继续看。若产生 `thought.stream="think_final"`，它只用于服务端审计与当前回合摘要，历史 UI 必须忽略；`response.completed` 仍是整轮结束。
`clarify`、`tool_approval`、`tool_approval_ack`、`plan`、`confirm`、`confirm_ack` 为持久化事件（落库 `ws_events`、占 event_id），向同一会话所有在线成员广播，断线重连按 `last_event_id` 补发。V1.70 起 `tool_approval` / `tool_approval_ack` 由 H5 持久化 HITL 重新产生；V1.72 起 `clarify` 由 `ask_user_question`（engine=agent）重新产生（与 `confirm` / `tool_approval` 三类卡共用 `pending_confirm` 单行互斥，行锁清卡 + 一次性 `resume_nonce` + resume 至多一次）；`plan` 仍无生产者（待后续评审）。
旧客户端可继续识别 `message` / `done`，但服务端不再发送这两个含义不明确的事件名。
当前 Compose 只有单 API 副本，assistant_delta 广播为进程内 Hub；多 API 副本时必须改为进程外
Pub/Sub，不能假定跨进程实时可见。

MCP/平台短工具中文名（ToolCard 标题；原生基础工具 `read` / `write` / `edit` / `bash` / `web_search` / `web_fetch` / `task` 直接显示英文 `name`）：

| name | 标题 |
| --- | --- |
| `model.list` | 列出协议档 |
| `dataset.list` | 列出数据集 |
| `kb.list` | 列出知识库 |
| `task.get` | 查询任务 |
| `report.get` | 读取报告 |
| `task.create` | 创建评测任务 |
| `task.status` | 查询任务状态 |
| `task.cancel` | 取消评测任务 |
| `testcase.confirm` | 确认用例入库 |
| `dispatch.overview` | 调度概览 |
| `audio.speech_recognition` | 语音识别转写 |
| `audio.speech_synthesis` | 语音合成 |
| `audio.voiceclone` | 音色克隆配音 |
| `image.generate` | Qwen Image 生图 |

长工具不由 Agent 进程跑完；前端只收 `progress` / `report` / `error`。

#### 4.3.2 会话标题 AI 生成契约（V1.51）

触发条件（三者同时满足）：会话 `title` 仍为默认值「新会话」、本轮上行 `user_message.text` 非空、
该会话当前没有进行中的标题生成任务。触发后由 API 进程**后台 fire-and-forget** 生成，不阻塞
收包循环与对话回合（标题不是关键路径）。

模型调用复用 Agent 协议档（`Setting.agent_profile_id`），输入为第一条用户消息（截断至 500 字符），
输出采用**弱结构化 + 代码侧强校验**：

- 提示词约定模型只输出单一 JSON 对象 `{"title": "标题"}`（6–20 字、概括意图不逐字复制、跟随用户
  语言、无标点结尾）；不依赖三协议原生 `response_format`/`json_schema`（能力不一致）；
- 代码侧解析管线：剥代码围栏 → 截取首个 `{` 到末个 `}` → `json.loads` → `title` 字段类型校验 →
  压缩空白与成对包裹引号 → 40 字硬截断；
- 任何失败（未配置协议档 / 上游 4xx5xx / 超时 / 契约不符 / 空标题）统一降级为**首条消息压缩空白后
  前 18 字**（与前端乐观占位同规则），仅记服务端日志，不发出 `session_title`、不向前端报错。

成功路径：先落库 `sessions.title`（行锁复查仍为「新会话」，不覆盖用户已改标题），再广播持久事件
`session_title`（§4.3）。前端在事件到达前可继续展示本地乐观截断标题，刷新后以服务端为准。

### 4.4 前端 → 服务（V1.72 当前）

```json
{ "event": "user_message", "payload": { "text": "帮我下一单 Benchmark", "attachments": [ { "file_id": "uuid" } ], "client_message_id": "browser-uuid" } }
```

```json
{ "event": "cancel_task", "payload": { "task_id": "uuid" } }
```

```json
{ "event": "tool_approval_ack", "payload": { "id": "toolcall_xxx", "action": "approve" } }
```

```json
{ "event": "clarify_reply", "payload": { "id": "call_xxx", "answers": [ { "id": "q1", "selected": ["OpenAI"], "custom": "" } ] } }
```

当前上行为 `user_message` / `confirm_ack` / `cancel_task` / `tool_approval_ack` / `clarify_reply` 五类；`/stop` 作为 `user_message.payload.text` 以 `/stop` 开头时由收包循环即时处理。`cancel_task` 成功后服务端发送 `task_cancelled`，前端只能在该持久化回执到达后结束取消中状态。

`confirm_ack`（V1.67 恢复，仅在 `sessions.pending_confirm` 存在时有意义）：

- `ok=false`：不入队，仅清卡并回 `{ok:false,message:"已取消确认"}`。
- `ok=true`：先抢占会话回合租约，`patch` 与 `pending_confirm` 深合并后按 §5 二次校验；通过后清卡并提交，再以 `workflow_confirm` 注入重放回合，**入队唯一经 W6**（`enqueue_long_task`），W7 收尾。仅 W6 写入真实 `task_id` 才发送 `confirm_ack.ok=true`；回放未入队则恢复 `pending_confirm` 并发送 `error`，卡保持可再次确认。
- 权限与重复：仅 `pending_confirm_author_id` 对应成员可提交（他人 `UNAUTHORIZED`）；重复确认或已无待确认卡返回 `VALIDATION`（「无待确认卡」），并发已处理为 `CONCURRENCY`，均不重复入队。
- 前端提交 patch 前必须剥离 `confirm_author` 元数据。

`tool_approval_ack`（V1.70 恢复，仅在 `sessions.pending_confirm` 存在且 `meta.confirm_type="tool_approval"` 时有意义）：

- `action` 仅接受 `"approve"` 或 `"reject"`，`id` 必须匹配最近一张待审批卡；仅命令原发起成员（`pending_confirm_author_id`）可提交，他人 `UNAUTHORIZED`。
- 服务端在 `pending_confirm` 行锁事务内校验 owner / 卡种 / `id` / action 后**先清卡提交**（一次性 `resume_nonce` 消费即失效），再以原中断回合的 `thread_id` 经 `Command(resume=...)` 恢复 ToolNode；**resume 至多一次**——重复 ack / 并发 ack 在清卡后行锁读空 → `VALIDATION`（「无待审批卡」），不再次唤醒图。
- `approve`：ToolNode 放行执行（本机无 bwrap 时工具失败观察，H4 失败阶梯接管）；`reject`：ToolNode 收到拒绝不执行命令，产出 `ok=false` 观察，回合正常收尾。确认前与拒绝后均不得调用 Runner。
- 服务端回执为持久化 `tool_approval_ack` 事件，payload `{action, approval_id}`，向同一会话所有在线成员广播。

`clarify_reply`（V1.72 转正——PRD 前端 → 服务上行清单自始包含澄清问答，属契约恢复而非范围扩张；仅在 `sessions.pending_confirm` 存在且 `meta.confirm_type="clarify"` 时有意义）：

- 多题 `answers[]` 结构（一次作答）：`{id, answers:[{id, selected?:[label…], custom?:string}]}`；`id` 必须匹配最近一张待澄清卡，`answers[]` 逐题对齐澄清卡 `questions[]`（`id` 必须存在；radio/checkbox 的 `selected` 取值须为 `options[].label`；text 填 `custom`）；任一校验失败 → `error`(`VALIDATION`)，卡保留可重答。
- 服务端在 `pending_confirm` 行锁事务内校验 owner / 卡种 / `id` / answers 后**先清卡提交**（一次性 `resume_nonce` 消费即失效），再以原中断回合的 `thread_id` 经 `Command(resume=...)` 恢复 ToolNode 放行（resume 至多一次）；重复/并发 `clarify_reply` 在清卡后行锁读空 → `VALIDATION`（「无待澄清卡」），不再次唤醒图。
- 澄清卡不建任务、不入队、不占任务槽（仅 agent 子图工具提问中断；恢复后按答复续跑，回合终态仍由 `response.completed` 收口）。
- 服务端回执为持久化 `clarify_ack` 事件（payload `{ok:true,id}`），向同一会话所有在线成员广播。

> 下方斜杠规则与 V1.62 示例为历史资料；V1.72 起 `clarify_reply` 已转正为现行上行（见上文 `clarify_reply` 段），旧 `{id, answer}` 单文本结构不再接受（现行结构为多题 `answers[]`，前端按 ClarifyCard 问卷一次作答）。

```json
{ "event": "confirm_ack", "payload": { "ok": true, "patch": { "with_stress": false } } }
```

```json
{ "event": "cancel_task", "payload": { "task_id": "uuid" } }
```

```json
{ "event": "clarify_reply", "payload": { "id": "uuid", "answer": "用户回复文本或所选 option" } }
```

```json
{ "event": "tool_approval_ack", "payload": { "id": "toolcall_xxx", "action": "approve" } }
```

规则：

- `client_message_id` 可选，非空时最长 128 字符；同一会话同一键重复发送只回显已保存消息，不会启动第二轮 Harness。
- 同一会话同一时刻最多一张待确认卡（落库 `sessions.pending_confirm`，禁止只靠进程内字典）；仅 `confirm_author` 可以确认、拒绝或提交 patch，前端提交 patch 必须剥离该元数据。
- `clarify` 与 `confirm` / `tool_approval` 三类卡互斥语义（V1.72 B 路线，替代 V1.62「不写 `pending_confirm`、进程内追踪」历史语义）：澄清卡同样落库 `sessions.pending_confirm`（`meta.confirm_type="clarify"`）单行互斥（同一时刻至多一张），行锁 + 一次性 `resume_nonce` + resume 至多一次与审批卡同一套纪律；澄清卡不建任务、不入队、不占任务槽（仅 agent 子图 `ask_user_question` 提问中断，作答后按 `answers[]` 续跑原回合）。`clarify_reply.id` 必须匹配最近一张待澄清卡，否则清卡后行锁读空 → `error`(`VALIDATION`)。
- `tool_approval_ack` 只接受 `action=approve|reject`，`id` 必须匹配最近一张危险工具确认卡，且仅命令原发起成员可提交。服务端先持久化回执、再以同一 `thread_id` 的 `Command(resume=...)` 恢复 ToolNode；确认前和拒绝后均不得调用 Runner。该暂停状态与 `clarify` 同为单 API 副本/按会话粘性路由前提。（V1.70 恢复为现行上行事件，详见上文 `tool_approval_ack` 段。）
- `cancel_task` 权限与 REST cancel 相同；斜杠 `/cancel` 只取消**本会话**非终态任务。  
- 斜杠（含 `/stop`）走 `user_message`；V1.72 当前上行事件为 `user_message` / `confirm_ack` / `cancel_task` / `tool_approval_ack` / `clarify_reply` 五类。
- Direct 路径（`/help`、未知斜杠、图内防御提示）在业务事件后必须再发 `response.completed`：`/help` 为 `finish_reason=stop`，校验/防御为 `error`。`/cancel` `/stress` `/stop` `/compact` 由 `ws.py` 拦截的真实入口按各自事件收尾，不走 Direct。
- `/stop`：中止本轮 Harness 生成，不取消已 queued/running 任务；abort 为**会话级**（双标签同停）。共享会话仅本轮发起成员可执行。
- `/compact`：会话级上下文副作用，仅会话 owner 可执行。
- 会话已有非终态任务（含压测子任务）：新回合**不得**再发 `confirm`；未 ack 的旧卡确认按钮禁用。  
- 对话路径**不得**发出 `kind=stress` 确认卡。`/stress` = 质量任务卡且 `with_stress=true`。  
- Agent 进程禁止同步执行 `benchmark.run` / `rag.evaluate` / `testcase.generate` / `stress.run`。

---


## 4A. Agent Loop WebSocket v2（V1.81，2026-09-09）

本节按《AgentLoop后端架构设计》V0.6 §11 登记，独立于 §4 legacy 协议。
`SessionOut.engine_version` 仍可返回 `"legacy" | "agent_loop_v2"`，用于历史记录审计；
`POST /api/sessions` 仅接受且默认 `agent_loop_v2`，服务端固定写入该值。禁止通过
WS 或更新接口切换历史会话引擎，也不能创建新的 legacy 会话。
`/ws/agent/v2?ticket=...` 服务 AgentLoop；旧 `/ws/agent` 只允许显式携带既有
legacy 会话 ID，缺失 ID 必须关闭 4400，不能隐式创建会话。
沿用登录 Cookie 换取的单次短票，校验类型、jti、有效期、用户禁用状态与 auth_version；
失败关闭 4401。会话不可见/删除关闭 4404。不接受客户端 actor、凭据、沙箱路径。

### 4A.1 上行与协商

连接返回 `hello`、`capabilities`；客户端首个会话操作为 `subscribe`，以
`protocol_version=2` 明确协商。每连接至多订阅一个会话，换会话须先退订。
公共头严格为 `{protocol_version:2,type,request_id,session_id,data}`；
未知字段、旧 last_event_id、非整数游标、版本不匹配均拒绝，不回落旧协议。
request_id/session_id/交互标识为非空字符串，长度不超过 128；nonce 不超过 512。
单帧 UTF-8 上限 64 KiB；JSON 重复键、NaN/Infinity、隐式类型转换均拒绝。
客户端时钟不参与鉴权、TTL 或事件排序。

| type | data（未注明可选即必填） |
| :--- | :--- |
| subscribe | `after_cursor:int>=0=0, view:"semantic"="semantic"` |
| unsubscribe | 空对象 |
| turn.submit | `client_message_id, content`；可选 `attachment_refs:string[]=[], profile_id, reasoning_effort:off/low/medium/high/xhigh/max, agent_id`；`profile_id` 只能是平台协议档 ID，`agent_id` 只能是平台内置专家 ID（缺省/未知回落默认专家，V1.89），附件只接受平台引用，不接受路径、模型地址、密钥或任意供应商参数 |
| turn.cancel | `turn_id` |
| approval.respond | `interaction_id, turn_id, turn:int>=1, attempt_id, call_id, nonce, decision:allow/deny/always` |
| question.respond | 同上交互身份，改为 `answers:[{question_id,answer,custom?:string}]`（非空、问题 ID 不重复；custom 最长 16000 字符） |
| task_confirmation.respond | 同上交互身份，另 `spec_hash, decision:confirm/reject` |
| trace.subscribe | `after_seq:int>=-1=-1, catalog_etag?:string`；事实 seq 从 0 起，与 cursor 不同 |
| trace.unsubscribe | 空对象 |
| ping | `client_time?:string` |

`command.accepted/rejected` 使用 request_id 关联，data 包含接受结果或安全
`code/message`；accepted 不代表模型、工具完成。状态变更回执必须在事实/卡决定提交后发出。
幂等键为服务端 actor_user_id + session_id + request_id，摘要为规范 type/session_id/data
的排序 JSON SHA256（UTF-8，紧凑分隔，无 NaN，算法版本 1）。
同键同摘要返回既有回执，同键不同摘要拒绝；turn.submit 另以 client_message_id 去重。
幂等和接受事实处于同一 PG 事务；WS 不用内存缓存替代数据库唯一约束。
审批/回答/确认必须在事务内验证 owner、当前 turn/attempt/call、nonce、TTL、
spec_hash（任务确认）；重连和回放均不得重做工具或入队。
turn.cancel 只请求指定 Agent 回合停止，最终以 turn.end 确认为准，不能取消 Worker 任务。

### 4A.2 下行与字段隔离

2026-09-09 事实目录补充（catalog_version=3）：登记 Store 实际写入的
`runtime/command`，data 为 `{fingerprint,data,correlation}`；这是持久命令回执，
不是原始命令请求，不产生额外语义 cursor 或回放触发的 command.accepted。
`assistant/attempt_start` 增补可选 `history_selection`（algorithm、indices、
message_count、input_fingerprint）及 `fingerprint_algorithm="dsh-json-v1"`。
indices 为对 `history_upto_seq` 所界定的派生消息列表的零基有序选择，不是事实 seq。
旧事实可省略新增字段；传输版本仍为 2，stream 目录保持 v2.1。
上述追踪字段仅供已授权 trace；普通 assistant.start 继续只公开 header/history 引用。
runtime/command 的 trace 仅投影 fingerprint、接受结果身份和关联字段；原始 request、
请求凭据、header、opaque 状态与未登记扩展不得透传。事实目录 schema 本身不含凭据。

统一信封为 `{protocol_version:2,type,durability,session_id?,ts,correlation,data}`。
persistent 必须有 session_id 与正整数 cursor；transient/control 禁止 cursor。
request_id 仅 command.accepted/rejected 携带。
correlation 只接受 turn_id/turn/step/attempt_id/call_id/call_seq/task_id/source_seq；
source_seq 仅引用 Agent 事实，不替代 session_stream cursor。

| durability | type |
| :--- | :--- |
| persistent | user.message、turn.start/end、step.start/end、assistant.start/message/end/retry、tool.call/dispatch/result、task_plan.updated、approval.requested/resolved、question.requested/resolved、task_confirmation.requested/resolved、execution.quarantined/reconciled、task.queued/progress/report/end、session.updated、context.trimmed、runtime.error |
| transient | assistant.text.delta、assistant.reasoning.delta、trace.chunk |
| control | hello、capabilities、schema.catalog、command.accepted/rejected、subscribed、replay.completed、resync.required、pong、trace.event |

语义字段采用白名单投影；工具内容与原始参数保留在事实存储，tool.result 仅发送
name/status/synthetic/display/error_code/exit_code 等展示字段，六态为
succeeded/failed/denied/cancelled/not_started/outcome_unknown。
assistant/message 事实稳定产生 assistant.message 和 assistant.end 两个 projection_kind；
失败/放弃 assistant/attempt 产生 assistant.end，不能依赖瞬态 end。
assistant.message 的工具列表只投影调用身份和名称，不携带 args/arguments_raw。
失败的 assistant.end 可选携带 error_code（平台标准码）和 error_message（固定中文安全摘要）；
额度耗尽为 BUDGET_EXCEEDED，上下文超限为 VALIDATION，限流、鉴权、模型不可用与服务异常为 UPSTREAM。
错误只发送平台标准错误码与固定安全摘要；未知异常不得外发原文、SQL 或 traceback。
system、protocol_state、provider_options、密钥、请求头和原始上下文不进入普通语义或 trace 帧。

每连接发送前重查 ACL；无权看交互的 persistent 帧以相同 cursor 的
`data:{restricted:true}` 占位；reasoning 字段/增量需独立授权。
trace 需显式订阅和 trace ACL，即使控制者也不自动拥有；发送事实的独立诊断副本，
保留脱敏后的参数形状与 schema/producer/correlation，通用递归凭据脱敏叠加事件敏感路径，
继续剔除 system/protocol_state/raw/header/原始历史/异常原文/nonce；不等于开放内部请求正文。
trace.event 的 `data:{source:"history"|"runtime",event:{seq,type,ts,data}}` 使用 after_seq，
不更新 semantic cursor；撤权立即停止 trace，撤销会话可见性关闭连接。

### 4A.3 快照、背压与运行时边界

attach 在建立回放前检查持久开放回合；只在已成功取得释放的 PostgreSQL writer lock
后补齐 `turn.end(reason="interrupted")`，锁仍被存活实例持有时只回放而不接管。随后注册
瞬态接收，再在一致性快照读高水位 H 和最早保留 cursor。
subscribed 返回 `{cursor:H}`；合法游标只回放 (after_cursor,H]，然后
replay.completed `{cursor:H}`，再发送连续的 >H 已提交前缀。
持久读取按 cursor 排序并校验连续性，重复行去重；不能依通知先后推进 cursor。
不存在、超水位、早于保留窗口的游标返回 resync.required：
`{cursor:H,snapshot:<H对应的授权状态>}`，本次停止回放与写命令；
客户端替换快照后重新 subscribe(after_cursor=H)，不得再追加 <=H 历史。
重放不调用 execute_command；增量丢失由最终 assistant.message 校正。

每连接有界发送队列和分页读取；优先丢瞬态，持久/控制帧仍超限时关闭 4408，
send 超时同样关闭 4408。Runtime 的事实提交不等待网络。
断连/退订调用 detach；仅释放并取消该连接实际控制的活动回合，观察者不取消，
重连/重复命令不自动抢占旧控制权。接收循环只等短事务接受结果，不 await 整轮图。

### 4A.5 前端展示增量（V1.81，2026-09-09）

- `GET /api/sessions/agent-ui` 返回草稿能力；`GET /api/sessions/{id}/agent-ui` 复验会话可见性与 v2 引擎。响应 `version=1, enabled, profile, profiles, agent, agents, allowed_efforts, default_effort, permissions{write,trace,reasoning,interactions,settings}, controller{active,owned_by_actor}, attachments`。`profile` 与 `profiles[]` 同形，均只包含 `id,name,version,model,protocol,allowed_efforts,default_effort`；服务端逐档通过同一 resolver 校验，绝不返回 base_url、API Key 或供应商参数。顶层 `allowed_efforts/default_effort` 保留为默认协议档兼容字段。controller 不授予当前连接控制权。
- V1.89：`agent` 为当前选中的专家 ID（已有会话取最近一轮 `user/message` 事实的 `extensions.expert_id`，无记录回落默认专家 `general`；草稿恒为默认），`agents[]` 为可选专家投影，每项仅 `id,name,description,badge,default`——**不返回**专家提示词正文与工具视野。专家由平台内置（随代码版本分发），`agent_id` 缺省或传未知值时服务端回落默认专家，不因该可选字段失败；专家只收窄工具范围，不改变权限、错误契约与任务状态机。
- 每次 `turn.submit` 都以提交的 `profile_id` 与 `reasoning_effort` 重新解析协议档；协议档不存在、未声明 Agent 用途、无有效凭据或思考档位不支持时返回 `VALIDATION`。前端本地偏好只能辅助预选，不能替代服务端解析。
  - V1.83：省略 `reasoning_effort` 时，若全局思考偏好不被该模型支持，使用经 resolver 验证的 `off`，`agent-ui.default_effort` 和实际请求保持一致。显式提交不支持的档位仍返回 `VALIDATION`。DeepSeek/Qwen 的 Anthropic 兼容请求在 `off` 时实际发送 `thinking.type=disabled`；收到的空签名思考块按兼容模型无损保留，不强套 Claude 非空签名规则，跨模型回放校验仍有效。
  - V1.85：Anthropic 兼容 DeepSeek V4 flash/pro（含日期版本）公开共同有效档位 `off/high/max`，开启时发送 `thinking.type=enabled` 与 `output_config.effort`，不把别名映射伪装成独立强度。Qwen3.6 Flash（含日期版本）使用 `thinking.budget_tokens` 表达五档预算，沿用平台 20%/40%/60%/75%/80% 比例、最低 1024 token；从总输出预留中扣除思考预算后下发正文 `max_tokens`，总预算不增加。输出预留不足时只公开 off。其他模型保持原能力边界；前端仅按服务端候选渲染，只有一个候选时明确显示不可调节。
  - 传输边界：模型配置管理走 REST，浏览器回合走 `/ws/agent/v2`；平台到模型根据协议档使用 HTTP(S) POST + SSE（Anthropic `/v1/messages`、OpenAI Chat `/chat/completions` 等），不将浏览器 WS 地址作为模型接口。思考强度随 `turn.submit` 冻结，经同一 resolver 转成 SDK 请求体。
- `attachments{upload_suffixes,inline_suffixes,image_suffixes,max_bytes,max_image_bytes,content_required}`：上传、模型内联和图片能力分开；模型实际是否支持视觉仍以供应商为准。附件正文不能为空；音频和旧 Office 仅元信息。历史附件按 `file_id` 使用已有 `/api/files/{id}` 和 `/content` 授权接口，不公开磁盘路径。
- `tool.call/result.data.display` 为 ToolDisplay v1：`version,title,registry_name,wire_name,arguments_preview,result_preview,target,format,truncated,unavailable_reason`，预览最多 12000 字符。参数按工具字段白名单生成，失败仅公开错误码；未知工具有明确缺失说明，不开放任意内部结果。V1.94 仅对原生 `task` 追加可选 `task:{goal:string,steps:[{title:string,status:"pending"|"in_progress"|"completed"}]}`；前端抽屉只消费该结构化投影，不能从预览文本猜测或关联 Worker `task_id`。
- `assistant.start.data.request_summary` 提供实际 `model,provider,protocol,profile_id,profile_version,reasoning_effort,max_tokens,input_fingerprint,tools[{name,description,parameters}],context_meter`。其中 `parameters` 是本次真实发送给模型的受限 JSON Schema 根对象，`description` 是注册工具描述；前端轨迹的 Schema 页直接消费此快照，旧事实中的 `parameters_schema` 仅作只读兼容。context_meter 为实际请求的同源序列化估算，字段 `basis,estimated,profile_version,input_fingerprint,history_upto_seq,capacity,input_tokens,reserved_output_tokens,breakdown`；`basis="serialized_request.v2"` 时 `breakdown` 为 `system_prompt,conversation_messages,tools,mcp,skill,memory_files` 的非负整数映射，六项严格合计 `input_tokens`。Skill/记忆文件未实际注入时必须为 `0`；旧事实缺统计时为 null，不显示为 0。
- `assistant.message.data.reasoning_preview` 为持久思考正文，仅 reasoning ACL 允许时发送。禁止出现在普通 trace 或撤权后的快照里。可选 `usage` 仅保留上游归一化 token 字段；可选 `latency_ms` 是该模型流的真实毫秒耗时，不含工具执行。缺字段表示上游未返回，前端不得补造。`question.resolved` 增 `outcome,answers`（仍受 interactions ACL）。
- 恢复快照增加有序 `timeline`（完整语义信封，受逐帧 ACL）；与 H 和当前用户权限在同一行锁事务读取。旧分组投影保留，记录增 `first_cursor`，新 reader 以 timeline 为权威，禁止重复追加 messages。
- `question.respond.answers[].answer` 接受字符串或字符串数组；多选使用标签数组，包含逗号的标签不切分。旧字符串多选仍兼容逗号编码。数组只允许用于 checkbox，多选规范化后复用 validate_answers。V1.96 新增可选 `custom:string<=16000`：它是“其他，请填写”的独立文本，允许与 checkbox 的已登记标签并存，绝不作为未登记 label 参与选项校验；旧客户端缺省该字段时行为不变。
- 同一连接对相同 session 再次 subscribe 仅重启读取流，保留控制权；跨会话须退订。附件元数据与内容接口复验上传者或可见会话引用权限，未知/无权限统一 NOT_FOUND。

### 4A.4 主服务注入契约

路由从 `app.state.loop_service` 获取 `app.agent.loop_service.LoopService`。
主服务 main.py 已接入 LoopService 生命周期。缺服务关闭 1013，不启用内存回退实现。
WS 类型定义在 `routers/ws_v2.py`：`WsAccess(write,trace,reasoning,interactions)`、
`StreamSnapshot(cursor,earliest_cursor=1,state={})`、`Command`、
`CommandReceipt(data,correlation={})`。下列方法均 async：

| 方法 | 返回/责任 |
| :--- | :--- |
| authenticate(ticket:str) | str，复用旧短票消费及用户校验，返回服务端 actor ID |
| authorize(actor_id,session_id) | WsAccess；复用 session ACL，验证引擎版本；权限变化实时读取 |
| attach(actor_id,session_id,connection_id,on_transient) | 注册 Callable[[dict],None]；仅在取得已释放 writer lock 时结算硬重启遗留回合，绝不转移存活控制权 |
| snapshot(actor_id,session_id) | StreamSnapshot；state 经授权，与 cursor 同一数据库快照 |
| read_stream(session_id,after_cursor,limit) | list[dict]，完整 persistent 信封、按已提交 cursor 升序 |
| read_trace(session_id,after_seq,limit) | list[dict]，规范事实、按 seq 升序 |
| execute_command(actor_id,connection_id,command) | CommandReceipt；行锁事务幂等接受、校验控制权/交互、调用 Runtime 快速 start_turn/cancel；不 wait 整轮 |
| detach(actor_id,session_id,connection_id) | 幂等注销瞬态订阅；仅 owner connection 请求 Runtime.cancel |

`app.agent.events.project_fact(fact)` 返回除 cursor 外完整 persistent 信封列表（含稳定 projection_kind）；稳定 projection_kind 与源事实 ID 联合去重。
主服务在事实同事务分配 cursor，用
`persistent_frame(session_id,cursor,projection,ts=...)` 形成 session_stream 信封。
非展示事实不投影，trace 另从事实分页读取。状态、消息投影、seq/cursor 由 PG
会话行锁事务统一提交；不新增第二套数据库访问层。

### V1.80 修改代码文件与作用清单

| 文件 | 作用 |
| :--- | :--- |
| backend/api/app/routers/ws_v2.py | 新 v2 严格命令解析、可注入服务、回放、背压、逐连接 ACL |
| backend/api/app/routers/sessions.py | 新会话固定 AgentLoop，并输出脱敏的可选协议档及逐档思考能力 |
| backend/api/app/agent/loop_wiring.py | 每回合按 profile_id 重新校验 Agent 用途、凭据、模型和思考强度 |
| backend/shared/models.py / backend/api/migrations/versions/8f9a2c4d6e01_新会话默认使用agentloop.py | 会话数据库默认值改为 agent_loop_v2，保留历史 legacy 行 |
| backend/api/app/agent/events.py | v2 事实投影、信封、诊断脱敏纯函数 |
| backend/api/tests/test_loop_ws*.py | v2 契约、回放、幂等服务边界、权限与断连回归 |
| backend/api/app/harness/contracts/loop_events.py | 源完整事实目录、schema descriptor、producer、correlation 与缓存 ETag；平台新增事实登记 |
| backend/api/app/harness/security/loop_redaction.py | 源通用递归敏感字段、凭据值和 JSON Pointer 路径脱敏；ordinary 与 trace 分开 |
| docs/AI测试与评估平台-API.md | V1.80 固化 AgentLoop 单入口、协议档安全投影与逐回合模型选择契约 |

### V1.81 修改代码文件与作用清单

| 文件 | 作用 |
| :--- | :--- |
| backend/api/app/agent/loop_service.py / routers/ws_v2.py | 安全重连恢复：释放 writer lock 后结算 interrupted，存活实例不被接管 |
| backend/api/app/agent/loop_wiring.py | 所选协议档 overlay 的核心优先、动态缓存边界和读取期安全校验 |
| backend/api/app/harness/execution/task_tools.py | Agent task.create 与 REST 的共享协议档使用口径一致 |
| backend/api/tests/test_loop_wiring.py / test_loop_integration_pg.py / test_loop_tools_task_prepare.py | 恢复锁竞争、后续回合、overlay 与共享协议档回归 |
| .github/workflows/ci.yml | 三组 Loop PostgreSQL 夹具与 Runner Ubuntu 回归 |


## 5. 任务规格 TaskSpec（`POST /api/tasks` 与内部 `task.create` 共用）

字段名不得改。必填语义随 `kind` 变化（PRD 5.1.2）。

```json
{
  "kind": "benchmark",
  "profile_ids": ["uuid"],
  "dataset_id": "uuid",
  "kb_id": null,
  "gold_qa_id": null,
  "rag_mode": ["hybrid"],
  "run": {
    "sample_size": 1000,
    "concurrency": 4,
    "timeout_s": 60,
    "retry": 1,
    "temperature": 0,
    "max_tokens": 1024,
    "system_prompt": "",
    "k": 5,
    "use_judge": false
  },
  "with_stress": false,
  "stress": {
    "env": "test",
    "qps": 10,
    "duration_s": 120,
    "sla_p99_ms": null
  },
  "case_source": { "file_id": "uuid" }
}
```

| 字段 | 必填 | 校验 |
| --- | --- | --- |
| `kind` | 是 | 四选一；前端只读展示 |
| `profile_ids` | benchmark：1–5；rag 外部 Chat：恰好 1 | 内置 LightRAG 评测可不填 profile |
| `dataset_id` | benchmark | |
| `kb_id` + `gold_qa_id` | rag | 内置或外挂都要黄金 QA |
| `rag_mode` | rag 且 LightRAG | 1–4 个，默认 `["hybrid"]` |
| `run` | benchmark / rag | 默认见 PRD 5.2.2；`concurrency` ≤ 平台 inflight |
| `run.k` | 否 | 仅 rag 有意义，默认 5，1–20 |
| `run.use_judge` | 否 | 默认 false；true 时用用途含 `judge` 的协议档 |
| `with_stress` | benchmark / rag | 默认 false |
| `stress` | `with_stress=true` | `env,qps,duration_s`；`sla_p99_ms` 可选 |
| `case_source` | testcase | `{file_id}` 或 `{text}`，二选一 |
| `parent_task_id` | 人手创建 stress 时 | 父任务须 succeeded |

`prod` + 压测：响应或 confirm payload 可带只读 `approvers: [{id,name}]` 供卡上展示；未会签不得 running。

`stress.qps` ≤ settings.max_qps（默认 500），`duration_s` ≤ max_duration_s（默认 1800）。未填 `sla_p99_ms` 时报告不出「是否达标」。

纯对话 Agent 当前不创建任务。人手 `POST /api/tasks` 或未来恢复 ToolNode 后的内部 `task.create` 都必须按本节校验；压测由质量任务 `succeeded` 且 `with_stress=true` 时 Worker 派生，手动创建 `kind=stress` 仍须 `parent_task_id`。

REST 前端预填与后端 TaskSpec 默认值必须保持一致（`sample_size=1000`、`temperature=0`、`max_tokens=1024`、`qps=10`、`duration_s=120`、`sla_p99_ms=null`）。Worker 夹紧：`sample_size = min(请求值, 1000, 行数)`。

---

## 6. 内部 MCP 执行基础设施（浏览器只读）

`platform.tasks` 当前注册 `task.create` / `task.status` / `task.cancel`，用于未来恢复 ToolNode 时的受控任务队列桥。V1.64 Agent 不调用 MCP 或原生工具；`GET /api/mcp/*` 只展示已注册基础设施和健康状态，不能表示浏览器或当前 Agent 可执行。`task.create` 与本节 TaskSpec 共用 Pydantic 校验，`task.cancel` 对终态幂等返回现状。

> 下表其余工具为历史扩展规划，当前未挂载，不能伪装为可调用。

| 工具 | 类型 | 入参 | 出参 | 阶段 |
| --- | --- | --- | --- | --- |
| `model.list` | 短 | — | `{items:[{id,name,protocol,model}]}` 无 Key（`model` 仅供展示） | M1 |
| `dataset.list` | 短 | — | `{items:[{id,name,version,row_count}]}` | M2 |
| `kb.list` | 短 | — | `{items:[{id,name,doc_count}]}` | M3 |
| `task.status` | 短 | `task_id` | 当前 `status`、`progress`、`report_id`（只读，不等待终态） | M1 |
| `report.get` | 短 | `report_id` | 摘要 + 下载路径 | M2 |
| `task.create` | 短 | TaskSpec（`kind` 必填） | `{status: queued, task_id, kind}`；经门禁直接入队，会话/用户归属平台注入 | M1 |
| `task.cancel` | 短 | `task_id` | 取消非终态；终态幂等返回现状 | M1 |
| `dispatch.overview` | 短 | — | Worker 数 / 队列 / 策略（与 `GET /api/dispatch/overview` 同源摘要） | M1 迷你轨 |
| `audio.speech_recognition` | 短 | `file_id`（本轮 wav/mp3 音频，由系统绑定）；`language?`（`auto|zh|en`，默认 `auto`） | `{transcript, language, model, file_id, filename, content_type, size}`；禁止回传音频 Base64 | 对话同步 |
| `audio.speech_synthesis` | 短 | `text`（必填；模型未给时从用户原话剥离「帮我输出音频」等命令前缀/引号/冒号后抽取朗读稿）；`mode?`（`preset|voicedesign`）；`style?`；`model?`；`voice?` | `{file_id, filename, content_type, size, model, mode, content_url}`；`content_url` 为 `/api/files/{id}/content`，禁止回传音频 Base64 | 对话同步 |
| `audio.voiceclone` | 短 | `text`（朗读稿，必填）；`file_id`（本轮 wav/mp3 参考音，缺省取本轮最后一段音频附件）；`style?`（可选语气） | `{file_id, filename, content_type, size, content_url}`；禁止把音频 Base64 写入 `tool_result` | 对话同步 |
| `image.generate` | 短 | `prompt`（文本或本轮图片附件） | `{file_id, filename, content_type, size, content_url}`；禁止回传图片 Base64 | 对话同步 |
| `testcase.generate` | 长 | `file_id` 或 `text` | `case_set_id` | M2 |
| `testcase.confirm` | 短 | `case_set_id, edits?` | 状态 succeeded | M2 |
| `benchmark.run` | 长 | TaskSpec 评测段 | `report_id` | M2（M1 mock） |
| `rag.evaluate` | 长 | TaskSpec RAG 段 | `report_id` | M3 |
| `stress.run` | 长 | `parent_task_id` + `stress` | `report_id` | M4 |

V1.64 Agent 不调短工具：原生 `task` 与 MCP `task.create/status/cancel` 均为已注册但未接线的执行基础设施。恢复 ToolNode 前，任务只能通过 REST 控制面或 WS `cancel_task` 管理；长工作仍仅由 Worker 执行，API 进程不得同步运行 benchmark、RAG、testcase 或 stress。

JSON Schema 冻结点：短工具 M1 W4；音频工具输入以本节为准，结果只回安全文本/文件元数据；评测长工具 M2 W6；RAG M3 W10；stress M4 W13。禁止新增 REST 代理或浏览器直连上游音频服务。

---

## 7. 压测进程指标（浏览器不调用）

`GET {stress}/metrics`  
内网；Basic 或 IP 白名单；**不**暴露公网；**不**走 Cookie。

- 前缀 `ai_eval_stress_`  
- label：`env,model,task_id`  
- Prometheus `job=ai-eval-stress`  
- 任务结束后 10min 停止该 `task_id` 序列  

前端曲线只用 `GET /api/tasks/{id}/stress-series`。

---

## 8. 按里程碑必须可联调的接口

| 阶段 | 必须就绪 | 门禁相关 |
| --- | --- | --- |
| M0 | `GET /api/health` | Compose |
| M1 | 认证、me、users、files、profiles、check、sessions（含 messages+events+pending_confirm+context_meter）、tasks CRUD/cancel/rerun、WS 全事件、settings（agent_profile_id）、`GET /api/agent/prefs` | 对话下单 mock；断线补发；协议档 |
| M2 | datasets、rows、case-sets confirm/export/map(dataset)、reports、share、baseline、budget 停、slash-commands 完整 CRUD | 对比报告；待补全；表单 POST /tasks；自定义斜杠 |
| M3 | kb、docs、gold-qa、map(gold_qa)、RAG 报告字段、Judge 可选 | Hit Rate@5 |
| M4 | settings.stress/notify、approve-stress、stress-series、解读只读 report_id | 先评后压；Grafana 同 task_id |

---

## 9. 明确不提供的接口（V1.0）

| 不要做 | 原因 |
| --- | --- |
| 对外 Open API / 长期 API Token | F-CM-08 V1.1 |
| `/api/chat/completions`、把 LightRAG 伪装成 Chat | F-RAG-01 |
| 改系统提示词、外部 MCP 管理、Ask/Plan（指产品级 Ask/Plan 功能，非 Harness 内部 `plan` 事件/PlanArtifact 下发） | PRD 4.2 |
| 未经契约评审新增 WS 上行或事件 kind（斜杠必须走 `user_message`；V1.72 上行事件为 `user_message` / `confirm_ack` / `cancel_task` / `tool_approval_ack` / `clarify_reply` 五类，新增/恢复以上行须先经契约评审并在 §4.4 留档） | F-AGT-02 |
| 删除会话 | PRD 未要求 |
| 独立审计页对应的写操作以外的产品 UI | 仅 `GET /api/admin/audit-logs` |
| 浏览器直连 MCP 或 `/metrics` | 安全边界 |
| Postman / Markdown 接口解析专用上传类型 | 用例输入 P1 |

---

## 10. 前端实现约束（对应设计规范）

1. `frontend/src/api/http.ts` 只封装本文 §3 路径；`ws.ts` 只封装 §4。  
2. `schemas/confirmCard.ts` 与 §5 同一份类型与默认值，供 ConfirmCard 与 `/datasets` `/kb` 抽屉。  
3. 错误码文案用 §1.3，不硬编码第二套。  
4. 不发明本文没有的 query 参数来「先用着」。缺字段提 PR 改本文。  
5. ContextMeter 只读 `GET .../messages` 的 `context_meter`；自定义斜杠只打 `/api/slash-commands`，禁止 localStorage / admin settings 冒充。

## 11. 后端实现约束

1. OpenAPI（内部）从本文生成或手写，但 **对外不发布**（非 F-CM-08）。  
2. Worker 与 Agent 调同一 MCP，不另做一套 REST 给 worker 跑评测（worker 可进程内调）。  
3. 协议档 URL、模型 ID、API Key 写入按 profile 隔离的受控环境文件；GET 不回显；日志与 `agent_trace` 不落 Key / Cookie / 密码。
4. 状态机与取消语义见 PRD 3.3；先评后压由 worker 创建子任务，不要求前端二次 `POST /api/tasks` kind=stress（`prod` 除外走会签）。  
5. 业务失败只抛 `AppError`（十码）；WS 与 REST 同一错误体。未捕获异常归一 `INTERNAL`，堆栈只进日志。  
6. `api` 进程禁止 `time.sleep` 评测、禁止同步跑长 MCP、禁止在 `confirm_ack` 里等到 Worker 终态；Harness 不得阻塞 WS `receive` 循环。  
7. 待确认卡落 `sessions.pending_confirm`，禁止只靠进程内 `_PENDING_CARDS`。

---

## 附录 A  一致性检查记录（V1.3）

检查对象：PRD V1.6.3、设计规范 V1.2、总计划 V1.0、前端计划 V1.3、后端计划 V1.3、本文。

### A.1 PRD 5.9 摘要 vs 本文

| 5.9 原文 | 本文 | 一致？ |
| --- | --- | --- |
| login/logout | §3.2 | 是 |
| GET/POST users | + PUT、status、reset-password、activity summary | 补全（F-CM-03 停用/重置密/活动聚合） |
| GET/POST files | + GET `{id}` | 补全 |
| CRUD profiles | + check | 补全（规范连通性） |
| CRUD datasets / case-sets / confirm | + upload/rows/map/export | export 在 5.4.1；map 在 5.4.2 |
| CRUD kb / documents / gold-qa | + 删文档、gold upload、is_core | 补全（PRD 2.1） |
| tasks POST/GET/cancel/rerun | + approve-stress、stress-series | 补全（F-ST） |
| reports GET/share | + fmt=md、baseline、share query | md/基线在功能表 |
| admin settings GET/PUT | 字段分 M1/M4 | 是 |
| ws-ticket + GET /ws/agent | §4 | 是 |

5.9 **未列**、本文有、且计划已承认的补全：`/api/health`、`change-password`、`/api/auth/me`、`/api/sessions*`、`audit-logs`。均为正文已有能力的落地路径，不是新产品。

### A.2 WebSocket vs PRD 5.1.3 / 规范 §7

事件名集合完全一致。上行仅三条。`progress` 四字段，不扩展曲线。心跳 30s、短票、`last_event_id` 补发：一致。

### A.3 TaskSpec vs PRD 5.1.2 / 规范 §6

必填列一致。本文仅 **增加可选** `run.k`、`run.use_judge`（计划已声明冻结方式），不改必填语义。

### A.4 错误码 vs PRD 5.5 / 规范 §7.3

十个 code 一致；文案与规范一字对齐。

### A.5 前端计划 §3.1 vs 本文 §2

原前端表有、本文保留。本文多出并需回写计划的：

- `GET /api/auth/me`  
- `PUT /api/users/{id}`、`POST /api/users/{id}/reset-password`（计划写“停用/重置密”未写路径）
- 会话方案 A 从「周三二选一」改为冻结  
- `POST /api/datasets/{id}/upload`、`GET .../rows`  
- `POST /api/case-sets/{id}/map`  
- `POST /api/kb/{id}/gold-qa`
- `DELETE /api/kb/{id}/documents/{doc_id}`
- `GET /api/files/{id}`  
- `GET /api/files/{id}/content`  

后端计划多出的 `GET /api/admin/audit-logs`、`GET /api/health`：前端不强制调用，一致。

### A.6 角色 vs PRD 2.1

单一 `member` 可访问 V1.0 工作台与配置；分享免登录仅只读报告；`prod` 须非创建者会签；任务取消限创建者：一致。

### A.7 内部边界

MCP 浏览器不调：与 PRD 3.1、前端计划「禁止把 MCP 当 REST」一致。  
`/metrics` 浏览器不调：与 F-ST-04、前端 F-ST-04「正确不排」一致。

### A.8 发现的文档间隙（检查时已在本文冻结，计划需回写）

1. 登录后刷新身份：PRD 未写 `GET /api/auth/me`，SPA + Cookie 必需 → 本文补全。  
2. 用户停用/重置密：5.9 只有 GET/POST users → 拆 PUT 与 reset-password。
3. 会话 REST：计划二选一 → 冻结方案 A。  
4. 数据集覆盖上传、待补全行、用例映射：功能有、5.9 无独立路径 → 本文给出。  
5. `CONCURRENCY`：PRD 超限保持 queued，与「错误码」并存 → 本文规定默认仍创建 queued，不把该码当创建失败。

检查结论：本文与 PRD 功能无冲突；与 5.9 的差异均为已声明补全。前端计划 / 后端计划已回写为「以 API V1.3 为准」（会话方案 A、`run.k`、`run.use_judge`、`GET /api/auth/me`、目录/摘要/调度事件）。

### A.9 V1.4 Agent 增量（相对 V1.3）

自 Agent 说明书 V1.1 回写，**不是**新产品范围（仍是 F-AGT-01/02/03/04/06 的落地路径与可选 payload）：

| 增量 | 本文位置 |
| --- | --- |
| `GET .../messages` 必带 `events`，增 `pending_confirm` `context_meter` | §3.4 |
| `GET /api/agent/prefs`（只读，ack 后服务端写） | §3.4 |
| `GET/POST/DELETE /api/slash-commands`（M2 CRUD） | §3.4 |
| `thought`/`tool_result` 可选 `latency_ms`；`thought` 可选 `stage` `skill_id` | §4.3 |
| WS 关闭码 4401/4404；`/stop` 走 `user_message` | §4.1 / §4.4 |
| 对话不得发 `kind=stress` 确认卡；短工具含 `dispatch.overview` | §5 / §6 |
| 能力未启用 = `VALIDATION` 400，禁止 409 冒充 | §1.3 |

---

## 12. 原型数据源与真实联调约定（V1.3，开发前必读）

本节以 `Web-Prototype/` 现状为准，解决原型中“页面看起来有数据”与“浏览器确实调到了 API”混在一起的问题。它不改变 PRD 功能范围，也不要求本次修改业务项目代码。

### 12.1 三类数据必须分开

| 类型 | 可以包含 | 存放/使用规则 | 不可以包含 |
| --- | --- | --- | --- |
| 静态 UI 配置 | 路由、导航、状态/指标枚举、文案、颜色令牌、表头、表单默认约束 | `assets/app.js` 的枚举和页面布局；随前端包发布 | 业务实体、KPI、任务、报告、用户、协议档、白名单 |
| 显式 Mock | `MOCK_SEED` 中的示例业务实体和 Mock 响应 | 仅 URL `?data=mock` 或 `localStorage.ae_data_mode=mock` 时载入；仅用于走查/视觉验收 | 作为 API 失败后的自动回退；用于演示“已联调” |
| 实时 API 数据 | 所有业务实体、列表、详情、图表序列和可写表单 | 默认模式；统一经 `assets/api.js` → `/api`；响应写入页面缓存后渲染 | `localStorage` 长期 token、将失败替换为假成功 |

`Web-Prototype/assets/api.js` 的默认模式是 `live`。网络失败、非 2xx、未登录均向调用页抛出结构化错误；不得退回 `MOCK_SEED`。顶栏的“实时 API / 示例 Mock”标识是验收证据，不是可随意隐藏的装饰。

### 12.2 原型启动与接口地址

| 场景 | 地址/操作 | 预期 |
| --- | --- | --- |
| 同域开发 | `http://<web-host>/...`，反代 `/api` 到 API 服务 | 默认实时调用，Cookie 使用 `credentials: include` |
| 分离开发 | 页面 URL 加 `?apiBase=http://localhost:8000/api`（或启动前设置 `window.AE_CONFIG.apiBase`） | REST 指向该服务；后端须允许准确 Origin 和凭据 CORS |
| 视觉走查 | 页面 URL 加 `?data=mock` | 仅加载 `MOCK_SEED`；顶栏显示“示例 Mock” |
| 不可接受 | 直接双击 `file://` 后把异常吞掉 | 页面必须显示加载失败；不能声称已接 API |

临时兼容说明：当前后端已有的 `GET` 列表有些直接返回数组，而本契约冻结 `{items,total}`。原型客户端会把“顶层数组”归一为列表对象，避免阻塞本轮走查；这不是后端长期豁免。M1 完成后所有列表必须按 §1.1 返回分页对象。

### 12.3 当前实现审计（2026-08-18，只读检查）

下表是对当前 `backend/api/app/routers/` 的实现覆盖检查，不代表目标契约已经完成；本次未修改这些项目代码。

| 域 | 已有实现 | 与 V1.3 的关键缺口 | 首个阻塞里程碑 |
| --- | --- | --- | --- |
| 健康、认证 | health；login/logout/me/ws-ticket | 改密接口、Cookie 名/12h 口径、续期与统一错误体未对齐 | M1 |
| 成员 | 无 `users` router | 成员列表、状态、重置密码、审计查询全部缺失 | M1 |
| 会话/Agent | WS 会建立会话并发最小确认卡 | `/api/sessions` 及消息回放缺失；WS 事件/重放/上行协议未完整对齐 | M1 |
| 协议档 | profiles 的 list/create/delete | get/update/check、用途/密钥不回显、审计与统一列表响应缺失 | M1 |
| 任务 | create/list/get/cancel/rerun | TaskSpec 校验、分页对象、events、worker 状态机与权限口径未完整对齐 | M1–M2 |
| 数据集 | list/create/delete | 详情、版本上传、行 CRUD、AI 生成、统一响应缺失 | M2 |
| 用例、报告 | 无对应 router | 全部接口与实体缺失（2026-08-18 起用例域按 §3.8 落地，含行级 `ai-fill` 补全） | M2 |
| KB/RAG | 独立 LightRAG `/health`、`/query` 骨架 | 平台 `/api/kb*`、文档、黄金 QA、报告关联缺失 | M3 |
| 调度 | `dispatch` router（overview/workers/config/events）已按 §3.13 落地 | 调度事件由 worker 执行侧写入；压测治理白名单/会签/曲线缺失 | M1/M4 |
| MCP、Skills | `GET /api/mcp/tools` 只读清单已落地 | 外部 MCP 与自定义技能按 §3.6.1/§3.6.2 保持能力未启用 | M1 |

结论：原型的接口名称此前大部分已列出，但不能视为“已接入”。本节与后端计划的 M0–M4 清单共同作为实现差距清单。

### 12.4 原型 API 客户端冻结项

| 项 | 冻结处理 | 后端配合 |
| --- | --- | --- |
| 任务重跑 | `tasks.rerun(id)` → `POST /api/tasks/{id}/rerun`；不得在浏览器拼造旧任务配置 | 后端从旧任务快照复制并生成新 ID |
| 会话删除 | owner 调 `DELETE /api/sessions/{id}`，成功 204；只软删除 | 有生成、待确认卡或非终态任务时返回 `VALIDATION`，历史任务/报告仍在任务中心保留 |
| 上传 | `FormData` 不设置 JSON Content-Type；数据集走 `/datasets/{id}/upload`，KB 走 `/kb/{id}/documents` | 返回文件/版本/异步处理状态，不能只返回 `{ok:true}` |
| WS | 从 REST 短票换取连接；支持 `session_id` 与 `last_event_id` | 不接受长期 token；按 §4 补发事件 |
| 缓存 | `AE.DB` 只是一页内响应缓存，实时模式初始为空 | 写操作成功后返回资源或前端重新拉取；禁止依赖原型样本 ID |

### 12.5 页面联调最小验收

| 页面 | 首次真实读 | 最小真实写 | 通过条件 |
| --- | --- | --- | --- |
| login | `GET /auth/me`（刷新后） | login / change-password | Cookie 生效，刷新仍能识别身份 |
| agent | sessions、profiles、datasets/KB | 创建会话、确认卡 `POST /tasks` | 断线重连后按 event_id 补发，不伪造任务成功 |
| tasks | `GET /tasks` | cancel / rerun | 筛选、详情、状态均来自服务器；重跑 ID 改变 |
| datasets / cases | 各自列表和详情/行 | 上传、保存、确认/映射 | 刷新后版本和编辑结果仍存在 |
| report | reports、samples、stress-series | share / baseline | 无报告时显示空/错误态，不能用静态报告顶替 |
| kb | KB、文档、黄金 QA | 上传、查询、黄金 QA 覆盖 | 检索结果中的 doc ID 可追溯 |
| 管理与调度 | profiles/settings/workers/whitelist | check、更新治理、白名单 | 敏感字段不回显；变更可审计 |

### 12.6 原型逐页还原新增契约（V1.3）

以下接口和字段补齐的是原型已经可见、但此前未被明确为真实数据的状态。它们的实现批次、表和测试以两份开发计划的 §11.7 / §12.7 为准。

| 页面状态 | 冻结契约 | 实时模式规则 |
| --- | --- | --- |
| 调度分配日志 | `GET /api/dispatch/events?after_id=&limit=` | 只增量读取调度器写入的事件；无事件即空日志，不显示示例流 |
| 任务趋势与诊断 | `GET /api/tasks/summary?from=&to=` | 后端聚合状态趋势与可追溯规则诊断；不返回无来源的生成式文案 |
| 数据集目录/扩展列 | `/api/dataset-folders*`；dataset `folder_id,column_schema` | 目录、列和行值写后必须刷新仍存在；候选生成结果不属于资源 |
| 用例目录/扩展列 | `/api/case-folders*`；case set `folder_id,column_schema` | 目录、列、72h 与确认状态由服务端返回；不得用前端倒计时决定终态 |
| KB 实验区 | KB item `capabilities.projection/rerank_compare` | V1.0 返回 `false`；前端展示能力说明，不能用 Mock 散点或重排对照补位 |
| 协议档四 Tab | `GET /api/mcp/tools`；profiles/settings | 仅内置工具清单可读；外部 MCP 和自定义技能/Prompt 的写操作在 V1.0 返回 `VALIDATION` 的能力未启用说明 |
| 成员活动 | `GET /api/users/activity-summary?from=&to=` | KPI/活动由审计聚合；异地登录 AI 风险不在 V1.0 返回范围 |

能力未启用使用 HTTP **400**，错误体遵循 §1.3：`{ "code": "VALIDATION", "message": "该能力未纳入 PRD V1.0", "fields": { "feature": "disabled" } }`。禁止用 409。前端将其渲染为页面内受控说明，不显示为成功 Toast，也不回退 Mock。

---

## 13. 本次修订代码文件与作用清单（2026-08-21）

**V1.14（2026-08-21）— 语音合成朗读稿抽取与 TTS 意图词表扩充**

`audio.speech_synthesis` 当模型未显式给出朗读稿时，从用户原话剥离「帮我输出音频 / 朗读一下」等命令前缀与引号、冒号后抽取播报文本，避免把整句命令当朗读稿；`SPEECH_SYNTHESIS_HINTS` 扩充「输出音频 / 生成音频 / 读出来 / 念出来 / 帮我朗读」等中文表达。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/mimo_audio.py` | 新增 `extract_tts_text` 朗读稿抽取（引号/冒号/命令前缀剥离）；`arguments_for_speech_synthesis` 模型未给朗读稿时从原文抽取 |
| `backend/api/app/agent/plan.py` | `SPEECH_SYNTHESIS_HINTS` 扩充「输出音频/生成音频/输出语音/转成音频/读出来/念出来/帮我朗读」等词 |
| `backend/api/tests/test_mimo_audio.py` | 新增朗读稿抽取与参数绑定单测 |

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/agent/harness.py` | 保存完整 `think_final` 思考快照；确认/取消确认卡写入 `confirm_ack` 事件 |
| `backend/api/app/agent/context.py` | 从持久化事件恢复技能与短 MCP 工具计数，刷新 ContextMeter 不归零 |
| `backend/api/app/routers/sessions.py` | 历史接口返回 `compact_summary`，恢复压缩后的模型上下文 |
| `frontend/src/views/Agent.vue` | 回放思考快照、确认回执与历史工具资产，并修正确认卡状态 |
| `frontend/src/api/types.ts` | 补齐 `confirm_ack` 事件和 ContextMeter 扩展字段类型 |
| `backend/api/app/profile_env.py` | 按 profile 生成环境变量名，在 bind mount 文件上加锁刷新/删除/回滚 URL、模型 ID、API Key |
| `backend/api/app/routers/profiles.py` | 协议档 CRUD 改为环境文件存储，旧密文迁移，连通性检查读取环境参数 |
| `backend/api/app/routers/admin.py` | 切换 Agent 协议档时同步兼容 `LLM_*` 环境别名 |
| `backend/api/app/llm/` | Agent 调用优先读取 profile 环境变量，兼容旧全局 LLM 环境变量 |
| `backend/worker/app/profile_env.py` | Worker 只读共享环境文件并隔离多供应商配置 |
| `backend/worker/app/benchmark.py` / `backend/worker/app/testcase.py` | 评测与用例生成调用改读环境文件参数 |
| `docker-compose.yml` / `.env.example` | API 可写、Worker 只读挂载服务器 `.env`，新增 `PROFILE_ENV_FILE` |

**V1.8（2026-08-20）— 助手回复耗时展示**

| 文件 | 作用 |
| --- | --- |
| `backend/shared/models.py` | `messages.latency_ms` 字段：assistant 交付句回复耗时（毫秒） |
| `backend/api/migrations/versions/cf9e2d5b7a01_助手消息增加回复耗时字段.py` | Alembic 迁移：新增 `messages.latency_ms` 列 |
| `backend/api/app/agent/harness.py` | 回合计时：`_ROUND_STARTED_AT` contextvar 记录回合起点，`_deliver_sentence` 计算耗时并写入 Message，交付 thought 终帧带 `reply_latency_ms` |
| `backend/api/app/routers/sessions.py` | `GET /sessions/{id}/messages` 返回 `messages[].latency_ms` |
| `frontend/src/api/types.ts` | `SessionMessage` 补 `latency_ms` 字段 |
| `frontend/src/views/Agent.vue` | 历史回放/实时交付帧把 `latency_ms` 落到助手气泡，气泡下方展示「耗时 x 秒」 |
| `frontend/src/styles/base.css` | 新增 `.reply-latency` 耗时角标样式 |

**V1.8（2026-08-20）— 用例 Excel 导入导出**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/case_excel.py` | Excel 三种表头解析与模板生成 |
| `backend/api/app/routers/cases.py` | `import-template` / `import`；映射回写 context 与 source_case_id |
| `backend/api/tests/test_case_excel.py` | 导入解析与模板往返单测 |
| `frontend/src/components/modals/ImportCasesExcelModal.vue` | 用例工作台 Excel 导入弹窗 |
| `frontend/src/views/Cases.vue` | 导入导出入口、目录持久化、72h 按 expires_at 展示 |
| `frontend/src/api/http.ts` / `frontend/src/api/types.ts` | 导入、模板、目录树客户端 |

**V1.9（2026-08-20）— 音色克隆短工具**

对话附件上传 wav/mp3 后，Agent 调用内部短工具 `audio.voiceclone`（MIMO `mimo-v2.5-tts-voiceclone`，OpenAI `chat/completions` 兼容）。合成音频落盘，`tool_result` 只回 `file_id` 与 `content_url`，浏览器经 `GET /api/files/{id}/content` 播放。环境变量 `MIMO_TTS_BASE_URL` / `MIMO_TTS_API_KEY` / `MIMO_TTS_MODEL` 注入 API 容器，禁止把 Key 写入仓库或日志。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/voiceclone.py` | MIMO 调用、参考音校验、规划注入 |
| `backend/api/app/agent/mcp_tools.py` / `defaults.py` / `routers/mcp.py` | 短工具名单与执行 |
| `backend/api/app/agent/plan.py` / `react.py` / `harness.py` | 注入工具、传入本轮附件、独立线程执行、交付句 |
| `backend/api/app/routers/files.py` | 允许 wav/mp3；实现 `GET /{id}/content` |
| `backend/api/app/config.py` / `.env.example` / `docker-compose.yml` | MIMO TTS 环境变量 |
| `backend/api/tests/test_voiceclone.py` | 规划注入与假上游落盘单测 |
| `frontend/src/views/Agent.vue` | 附件白名单、工具卡播放器 |

**V1.10（2026-08-20）— 独立 Qwen Image MCP 工具中心可见性**

独立 Qwen Image stdio MCP 曾作为 `/api/mcp/tools` 注册项展示；V1.11 起，平台改为直接在 API Agent Host 的内部 `mcp_tools` 中执行 `image.generate`，不再依赖额外 stdio MCP 进程。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/mcp.py` / `backend/api/tests/test_dispatch.py` | 注册并校验 `image.generate` 的工具中心可见性 |
| `frontend/src/api/mockData.ts` / `frontend/src/views/AdminProfiles.vue` | 增加图像生成领域与工具中心展示 |
| `frontend/src/components/modals/McpToolModal.vue` | 增加图像生成工具契约详情 |

**V1.11（2026-08-20）— Qwen Image 内部短工具接入**

Qwen Image 通过与 `audio.voiceclone` 相同的 Agent 内部短工具链路执行：规划阶段识别图像生成意图，React 阶段在独立线程中调用上游，参考图只从本轮图片附件选择，生成结果落盘到 `files` 表并通过同源 `content_url` 返回。URL、Key、模型 ID 和超时从环境变量 `QWEN_IMAGE_API_URL`、`QWEN_IMAGE_API_KEY`、`QWEN_IMAGE_MODEL`、`QWEN_IMAGE_TIMEOUT_SECONDS` 注入。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/imagegen.py` | Qwen Image 请求、图文 content 组装、响应解析、图片落盘与规划注入 |
| `backend/api/app/agent/defaults.py` / `mcp_tools.py` / `react.py` / `plan.py` / `harness.py` | 注册、线程隔离执行、自然语言规划注入和交付句 |
| `backend/api/app/config.py` / `docker-compose.yml` / `backend/api/app/routers/files.py` | 环境变量注入和图片附件白名单 |
| `frontend/src/views/Agent.vue` / `frontend/src/styles/base.css` | 图片附件上传、工具结果预览与下载 |
| `backend/api/tests/test_imagegen.py` | 图文请求、规划注入、落盘和线程执行单测 |

**V1.12（2026-08-21）— 协议档 Embedding / Reranker 配置**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/schemas.py` | 增加 Embedding / Reranker 的 URL、模型标识与 API Key 输入字段；响应只返回配置公开值和密钥存在性布尔值 |
| `backend/api/app/profile_env.py` | 为两类附加模型生成隔离环境变量，沿用加锁、fsync、回滚和只写不回显规则 |
| `backend/api/app/routers/profiles.py` | CRUD 写入和读取两类附加端点配置，更新时保留未提交的既有密钥 |
| `backend/worker/app/profile_env.py` | Worker 只读解析 Embedding / Reranker 环境变量 |
| `frontend/src/api/http.ts` / `frontend/src/components/modals/ProfileModal.vue` / `frontend/src/views/AdminProfiles.vue` | 协议档新增 Embedding / Reranker 可选配置表单、列表标识，并按空值保留规则提交；客户端请求类型同步收紧 |
| `frontend/src/api/types.ts` | 补齐协议档附加模型配置与脱敏状态字段 |
| `backend/api/tests/test_profile_env.py` / `backend/api/tests/test_profile_schemas.py` | 覆盖多端点环境变量隔离、删除回滚及请求校验 |

**V1.15（2026-08-22）— Agent 骨架重置**

旧 Agent、Harness、模型调用层和 Runtime 实现已清空，避免旧实现与新设计并存。`/ws/agent`、Agent 偏好、MCP 工具清单以及数据集/用例 AI 候选入口暂由 API 保留路径但返回统一的 `VALIDATION` 能力未启用错误；核心 CRUD、Worker、数据库模型与迁移不受本次重置影响。后续实现边界以 [`AI测试与评估平台-Agent重设计工作区.md`](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E9%87%8D%E8%AE%BE%E8%AE%A1%E5%B7%A5%E4%BD%9C%E5%8C%BA.md) 为准。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/`、`harness/`、`llm/`、`runtime/` | 仅保留包边界文件，等待模型调用层、Harness 与 Agent 范式重新评审 |
| `backend/api/app/routers/ws.py` | 拒绝旧 Agent WebSocket 会话，防止新旧运行时并存 |
| `backend/api/app/routers/agent_prefs.py` / `mcp.py` | 保留路由形状，返回重建设计占位 |
| `backend/api/app/routers/datasets.py` / `cases.py` | 暂停模型生成入口，不调用旧模型客户端 |
| `backend/api/tests/` | 移除依赖旧 Agent/Harness/MCP 实现的测试，保留平台核心测试 |

**V1.16（2026-08-23）— LangGraph Agent 与 WebSocket 最小链路**

在 V1.15 清空旧运行时的基础上，新增唯一的 LangGraph 单轮 Agent 图和 WebSocket 桥接。`/ws/agent` 重新支持短票鉴权、会话创建/可见性校验、`last_event_id` 事件补发、`user_message` 后台回合、`message` / `thought` / `error` / `pong` 事件；正文与推理增量分别使用 `thought.stream=chunk|think`，回合结束保存 `think_final` 和助手交付句。`confirm_ack`、`cancel_task`、MCP、人工确认和长任务仍返回 `VALIDATION` 能力未启用错误，不在本期恢复。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/graph.py` | LangGraph 单轮 Agent 图，仅组合 `ModelGateway` |
| `backend/api/app/routers/ws.py` | WebSocket 短票、会话事件、后台 Agent 回合和流式投影 |
| `backend/api/app/session_connections.py` | 单 API 副本下的持久化事件与正文增量广播 |
| `backend/api/app/llm/gateway.py` | 保持流式取消异常的受控传播 |
| `backend/api/tests/test_agent_graph.py` | Agent 图非流式与流式回归测试 |

**V1.18（2026-08-23）— 标准 response 生命周期事件**

用户回显不再复用 `message`，回合结束不再使用语义模糊的 `done`。服务端统一发送
`user_message`、`thought`、`assistant_delta`、`assistant_message`、`response.completed`、
`error`、`pong`；旧 `message` / `done` 仅由前端兼容历史事件，不再由服务端新写入。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | 发送独立用户回显和 `response.completed`，保留公共头中的 `session_id` / `task_id` |
| `frontend/src/api/types.ts` | 增加新事件类型并保留历史事件兼容 |
| `frontend/src/views/Agent.vue` | 分离用户、思考、助手增量、最终消息和完成状态 |
| `backend/api/tests/test_ws_protocol.py` | 回归验证用户回显事件与完成事件公共头 |

**V1.20（2026-08-23）— Gemini 思考摘要兼容**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/adapters.py` | 为 Gemini OpenAI 兼容流式请求发送 `thinking_config.include_thoughts`，映射思考强度，并归一化 `thinking` 思考增量 |
| `backend/api/tests/test_adapters.py` | 回归验证 Gemini 思考参数与思考增量分类 |

**V1.19（2026-08-23）— Agent 思考摘要与强度设置**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/admin.py` | 增加 `agent_reasoning.enabled/effort` 默认值与校验；不涉及数据库迁移 |
| `backend/api/app/routers/ws.py` | 每个 Agent 回合读取思考设置并写入 `ModelConfig` |
| `backend/api/app/llm/contracts.py` / `gateway.py` | 扩展模型调用契约，并在关闭时过滤 reasoning 流 |
| `backend/api/app/adapters.py` | 映射 OpenAI Chat/Responses、Mimo 和 Anthropic 的思考参数 |
| `frontend/src/views/AdminProfiles.vue` / `frontend/src/api/types.ts` / `frontend/src/api/mockData.ts` | 增加管理页思考开关、强度选择和类型夹具 |
| `backend/api/tests/test_adapters.py` / `backend/api/tests/test_llm_graph.py` | 回归验证思考参数映射与关闭过滤 |

**V1.23（2026-08-24）— Agent 多附件上传与预览**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/files.py` | 扩展 Agent 附件白名单，允许图片与 DOC/DOCX 文件；沿用 20MB 限制和同源内容接口 |
| `backend/api/tests/test_files.py` | 覆盖图片、Markdown、PDF、Word、Excel 扩展名校验及非法格式拒绝 |
| `frontend/src/api/http.ts` | 文件上传响应类型补充可选 `content_type`，用于本地预览识别 |
| `frontend/src/components/agent/AttachmentPreview.vue` | 新增图片缩略图、PDF/文本预览、Office 类型卡片和打开/下载入口 |
| `frontend/src/views/Agent.vue` | Agent 输入区支持多附件选择、拖拽上传、上传状态、附件移除与消息内预览卡片 |

**V1.24（2026-08-24）— Agent 附件上下文与历史预览修复**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/attachments.py` | 校验附件归属、补齐历史预览元数据，并解析文本、PDF、DOCX、XLSX 与图片模型内容块 |
| `backend/api/app/routers/ws.py` / `backend/api/app/routers/sessions.py` | 将附件注入模型窗口，用户消息保存安全元数据，历史回放返回可预览字段；支持附件-only 用户消息 |
| `backend/api/app/adapters.py` | 将内部图文内容块分别转换为 OpenAI Chat、Responses 与 Anthropic Messages 格式 |
| `frontend/src/views/Agent.vue` / `frontend/src/components/agent/AttachmentPreview.vue` | 将附件按钮与待发送预览放入输入框，用户气泡中把附件置于提示词上方并保持紧凑预览 |
| `frontend/src/components/ProviderLogo.vue` / `frontend/src/api/types.ts` | StepFun 图标对齐图二，历史附件类型支持安全元数据 |
| `backend/api/tests/test_agent_attachments.py` | 覆盖文档正文注入、图片内容块和三协议图文转换 |

**V1.32（2026-08-25）— 原生基础工具直连与 MCP 扩展收敛**

基础工具从内部 MCP Host 迁回模型原生 Function Calling 的受控直连路径：
`read`、`write`、`edit`、`bash`、`web_search`、`web_fetch`、`task` 均不经 MCP
catalog/provider；`GET /api/mcp/tools` 只保留评测/RAG 扩展目录，当前展示
`platform.tasks.task.create/status/cancel`。既有 WebSocket `tool_call`、`tool_result`、`call_id` 与错误码不变。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/context.py` / `native.py` | 抽离运行时上下文，新增基础工具直连的异步、超时与取消边界。 |
| `backend/api/app/harness/execution/registry.py` / `toolnode.py` / `agent/graph.py` | 以 `transport=native|mcp` 分流；默认图不再构建基础工具 MCP Host。 |
| `backend/api/app/harness/execution/dispatch.py` | 流式 read、排他/原子写入、Runner/bwrap 命令链检查、Firecrawl 搜索、安全网页抓取和会话内 task 清单。 |
| `backend/api/app/config.py` / `.env.example` / `docker-compose.yml` | 新增仅 API 容器可见的 `FIRECRAWL_API_URL` / `FIRECRAWL_API_KEY`。 |
| `backend/api/app/routers/mcp.py` / `frontend/src/views/AdminProfiles.vue` | MCP 清单只展示 `platform.tasks` 与未来扩展，不混入原生基础工具。 |
| `frontend/src/components/agent/ToolCard.vue` | 基础工具中文标题与 read/web/task 的受控结果投影。 |
| `backend/api/tests/test_harness_execution.py` / `test_harness_mcp.py` | 覆盖基础直连不进 MCP、Firecrawl、SSRF、任务拆解、原子读写和扩展 MCP 回归。 |

**V1.33（2026-08-25）— 单回合多条 assistant_message**

同一回合可落多条阶段叙述与最终交付句；`response.completed` 仍为整轮结束。
可选 `interim=true` 不结束生成态。清单复用 `plan.slots.steps`，不新增事件名。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3 `assistant_message` 允许多条 + `interim` |
| `backend/api/app/agent/react.py` | native 同轮正文+ToolCall 先发阶段叙述 |
| `frontend/src/views/Agent.vue` | 按事件序另开助手气泡；渲染 plan 步骤清单 |

**V1.34（2026-08-25）— 原生工具模型可见结果上限**

所有原生 ToolCall 回传模型的单条正文统一 ≤8,000 字符，避免大文档/长 bash/网页正文拖垮下一轮预填充。`read` 字符窗口与该上限对齐；未读完时 `model_text` 携带 `next_offset`。浏览器 `tool_result.data` 预览仍 ≤500 字符。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/context/observation.py` | 冻结 `MODEL_TOOL_RESULT_MAX_CHARS=8000` |
| `backend/api/app/harness/execution/dispatch.py` / `sandbox.py` / `registry.py` | read/web/bash 窗口对齐；read 大文件按块统计剩余行 |
| `backend/api/app/agent/react.py` / `toolnode.py` | 回传截断 + 工具/模型耗时与 payload 字符数追踪 |

**V1.35（2026-08-25）— 确认卡、短票 Redis、真实压测下发**

LangGraph `reflect` 在规划 `delivery=confirm` 且复核通过后发出确认卡（默认 `sample_size=1000` / `temperature=0` / `max_tokens=1024`），对话路径不得 `kind=stress`。WS 短票 `jti` 使用 Redis `SET NX` + JWT 剩余 TTL，进程重启后未过期票据不可复用；Redis 不可用时回退进程内存。压测由 Worker HTTP 下发 `stress` 容器，取消立即停发，报告 `time_series` 供 `GET /api/tasks/{id}/stress-series`。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/confirm_spec.py` / `app/agent/reflect.py` | 从规划拼装 TaskSpec 并在 reflect 发出 `confirm` |
| `backend/api/app/ws_tickets.py` / `app/routers/ws.py` | 短票单次消费与确认卡作者元数据 |
| `backend/worker/app/stress.py` / `backend/stress/main.go` | Worker 下发真实发压、可取消、写曲线 |
| `docker-compose.yml` | Worker `STRESS_URL=http://stress:19090` |

**V1.36（2026-08-25）— ContextMeter 服务端计算**

`GET /api/sessions/{id}/messages` 的 `context_meter` 按 `recent_window`（末尾 20 条 user/assistant）+ 协议档 `context_window` + 常驻 Skill Hint + `compact_summary` 计算 token 与窗口占比。不再返回 `null`；前端圆环只读该对象。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/context/meter.py` | `compute_meter` / `estimate_tokens` |
| `backend/api/app/routers/sessions.py` | 历史接口下发真实 `context_meter` |
| `frontend/src/components/agent/ContextMeter.vue` | 已压缩徽标；圆环底色略加深 |
| `docs/AI测试与评估平台-Harness-上下文工程层.md` | V0.4.2 校准计量已接线 |

**V1.37（2026-08-26）— read 防重复与 ToolCard 行级预览**

相同 `path+offset` 的 `read` 只执行一次（JSON ReAct 与原生 ToolCall 同一守卫）。预览按完整行截取，上限 `TOOL_PREVIEW_MAX_CHARS`（默认与模型窗口对齐）；`next_offset` 可作为下次 `offset` 别名。ToolCard 展示输入字段、行号与 Markdown 渲染。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/react.py` | 原生路径 OR-4；`READONLY_REPEAT_LIMIT=1`；`next_offset` 归一 |
| `backend/api/app/harness/execution/dispatch.py` / `registry.py` | 完整行预览、内容预算预留、`next_offset` 别名 |
| `frontend/src/components/agent/ToolCard.vue` | 字段/行号/命令/文件内容 + MarkdownView |
| `frontend/src/utils/toolCard.ts` | 成功后默认展开的工具名单 |
| `docs/AI测试与评估平台-API.md` | §4.3 `read` 预览契约 |

**V1.39（2026-08-26）— 下单偏好与自定义斜杠落地**

`GET /api/agent/prefs` 改为读取 `settings.agent_prefs:{user_id}`；仅 `confirm_ack.ok=true` 且任务已入队后写入。`GET/POST/DELETE /api/slash-commands` 完成 M2 CRUD（按用户存 `settings.slash_commands:{user_id}`），空列表表示已启用无命令。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/memory/preference.py` | 偏好投影、入队后抽取允许字段 |
| `backend/api/app/harness/memory/slash_store.py` | 自定义斜杠校验与存取 |
| `backend/api/app/routers/agent_prefs.py` / `slash_commands.py` | REST 入口 |
| `backend/api/app/harness/orchestration/confirm.py` | 入队成功写偏好 |
| `frontend/src/components/agent/SlashPalette.vue` | 添加/删除我的命令 |

**V1.40（2026-08-26）— `/cancel` / `/stress` 解禁**

斜杠仍全部走 `user_message`，除 `tool_approval_ack` 外没有第五种上行事件（V1.70 上行四类：`user_message` / `confirm_ack` / `cancel_task` / `tool_approval_ack`）。`/cancel` 由 `ws.py` 拦截后取消本会话非终态任务（权限同 REST cancel），下发 `task.cancel` 的 `tool_result`。`/stress` 发出质量任务确认卡且 `with_stress=true`，`kind` 不得为 `stress`；空槽用偏好预填。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | `/cancel` `/stress` 收包循环拦截 |
| `backend/api/app/harness/orchestration/confirm_spec.py` | `build_slash_stress_spec` |
| `backend/api/app/agent/routing.py` | HELP_TEXT 与图内防御提示 |
| `frontend/src/agent/slashRegistry.ts` | 解禁 `/cancel` `/stress` |
| `frontend/src/components/agent/ConfirmCard.vue` | 以内联卡为事实源合并确认卡 |

**V1.41（2026-08-26）— 确认卡丢掉已删除资产 ID**

`/stress` 与偏好预填可能带上已硬删除的协议档 ID，chip 列表没有对应项，用户点不掉；`confirm_ack` 入队后 Worker 报「协议档不存在或已删除」。发卡与入队前按现网表过滤；前端选项加载后再滤一遍未 ack 卡。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/confirm.py` | `drop_stale_asset_ids`：入队前丢掉已删除资产 |
| `backend/api/app/routers/ws.py` | `/stress` 发卡前同样过滤 |
| `frontend/src/views/Agent.vue` | 现网列表过滤偏好/规划预填的失效 ID |

**V1.42（2026-08-26）— Direct `/help` 补 `response.completed`**

`response.completed` 仍是整轮结束（§4.3）。Direct 不经 reflect，此前 `/help` 只发 `assistant_message`，协议探针与等待 completed 的客户端会超时。Direct 所有出口在业务事件后追加本轮唯一 completed：`/help` 为 `stop`，未知斜杠与图内防御提示为 `error`。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/routing.py` | Direct 出口追加 `response.completed` |
| `backend/api/tests/test_agent_routing.py` | `/help` / 未知斜杠 / 图内防御断言末帧 completed |
| `docs/AI测试与评估平台-Harness-编排层.md` | V0.4.6：Direct 收尾对齐 Chat/ReAct |

**V1.43（2026-08-26）— 思考链合并与 completed 收尾顺序**

上游 reasoning 按字增量时，`thought.stream=think` 允许按间隔合并后再发。有思考链时持久事件顺序为交付句 → `think_final` → `response.completed`。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/think_stream.py` | 思考增量合并器 |
| `backend/api/app/routers/ws.py` | 合并下发 think；think_final 插入 completed 之前 |
| `backend/api/tests/test_think_stream.py` | 首帧立即下发、后续按间隔合并 |

**V1.44（2026-08-26）— ToolCall 真实流式、权限与恢复契约**

`tool_call` 必须先持久化，随后才允许同 `call_id` 的 `tool_progress`、`tool_output_delta` 出现；两个增量事件只给在线会话成员，不落库、不补发。`tool_result` 保持唯一持久化终态，失败结果携带脱敏 `recovery`。浏览器输出只来自注册表定义的安全投影，单次调用最多 `TOOL_PREVIEW_MAX_CHARS` 字符（默认与模型窗口对齐），禁止回传模型上下文之外的内容（如未脱敏错误、密钥、绝对路径）。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/registry.py` / `policy.py` | 声明并校验工具描述、输入/输出 Schema、权限边界与恢复策略。 |
| `backend/api/app/agent/react.py` / `harness/execution/toolnode.py` | 先创建 ToolCall，再经 custom 通道下发进度与安全输出，最终写入 ToolResult。 |
| `backend/api/app/routers/ws.py` | 将工具瞬态帧仅广播给在线同会话成员。 |
| `backend/api/app/harness/execution/dispatch.py` / `sandbox.py` / `backend/runner/main.py` / `backend/shared/sandbox_kernel.py` | read/write/bash 的安全投影及 bash Runner NDJSON 转发。 |
| `frontend/src/views/Agent.vue` / `components/agent/ToolCard.vue` / `api/types.ts` | ToolCard 阶段加载、行级实时输出、恢复建议和 `call_id`/`seq` 关联。 |
| `backend/api/tests/test_harness_execution.py` / `test_sandbox_runner_client.py` / `backend/runner/tests/test_runner.py` | 覆盖契约登记、ToolNode 流、Runner NDJSON 转发。 |

**V1.45（2026-08-26）— 思考链不暴露隐藏 CoT**

`thought.stream=think` / `think_final` 只承载可展示摘要。上游英文隐藏思维链由服务端替换为短中文摘要；中文思考原文保留。不新增对外字段。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/think_stream.py` | `sanitize_reasoning` / `ReasoningDisplayFilter` |
| `backend/api/app/routers/ws.py` | 流式与 think_final 走摘要过滤 |
| `backend/api/tests/test_think_stream.py` / `test_harness_probe_l2.py` | 隐藏 CoT 替换与探针拒绝原文 |

**V1.46（2026-08-26）— native 内容块交错流：ToolCall 结束当前上游响应**

不新增事件名或字段。`native` 首轮与回填后回合均流式推送 `assistant_delta`；完整 `tool_call` 只在该次上游响应结束后持久化。一次 ToolCall 终止当前上游响应，结果回填后才发起下一请求。同轮多调用仍串行；`legacy` 行为不变。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §3.5 `tool_call_mode`、§4.3 `call_id` 规则补充响应结束语义 |
| `backend/api/app/agent/react.py` | native 首轮改走 `gateway.stream()` |
| `backend/api/tests/test_agent_react.py` / `test_llm_graph.py` / `test_adapters.py` | 首轮交错流与三协议 text→tool_call 夹具 |

**V1.47（2026-08-26）— Agent 交错流灰度度量**

新增 `GET /api/agent/metrics`：进程内首 delta / ToolCall 解析延迟、批次并发、取消与不完整流比例。不含正文与参数。不新增 WS 事件或 `segment_id`。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §3.4 `GET /api/agent/metrics` |
| `backend/api/app/harness/execution/stream_metrics.py` / `stream_policy.py` | 脱敏计数、协议档白名单、并行脚踢线 |
| `backend/api/app/routers/agent_prefs.py` | 只读度量入口 |
| `backend/api/tests/test_stream_rollout.py` | 白名单、脚踢冷却、快照不含载荷 |

**V1.48（2026-08-26）— 同轮多调用默认串行，灰度只读并行**

覆盖 V1.46「同轮多调用仍串行」的绝对表述。默认仍串行；灰度开启后仅 `read` / `web_search` / `web_fetch` 可同波并行。模型 `role=tool` 回填始终按原始 `call_id` 顺序。关联错乱与 `UPSTREAM` 每模型回合只记一笔终态，避免成功流把脚踢计数清零。不新增 WS 事件。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3 `call_id` 规则：默认串行 + 灰度只读并行 |
| `backend/api/app/agent/react.py` | 每回合只记一笔流式终态；关联错乱可累计脚踢 |
| `backend/api/tests/test_stream_rollout.py` / `test_agent_react.py` | 连续 associate_error 触发脚踢；流式空 call_id 两轮 rounds=2 |

**V1.49（2026-08-27）— 协议档新增 max_output_tokens 输出上限**

协议档新增 `max_output_tokens`（256–131072，默认 `8192`，存量数据回填 8192 保持既有行为）。WS Agent 模型调用从当前 Agent 协议档读取该值作为 `max_tokens`，不再硬编码 8192；长文档总结/导出类任务可调大，避免回答在输出上限处被上游截断。不影响离线评测、裁判与用例生成调用。不新增 WS 事件。

| 文件 | 作用 |
| :--- | :--- |
| `backend/shared/models.py` / `migrations/versions/e7a1c3f52b48_*.py` | `protocol_profiles.max_output_tokens` 列与迁移 |
| `backend/api/app/schemas.py` / `app/routers/profiles.py` | 创建/更新/响应支持新字段 |
| `backend/api/app/routers/ws.py` | Agent 模型配置从协议档读取输出上限 |
| `frontend/src/components/modals/ProfileModal.vue` / `src/api/types.ts` | 协议档表单与类型支持新字段 |


**V1.51（2026-08-27）— 会话标题 AI 生成与 session_title 持久事件**

修复会话标题不持久化：此前前端仅在首发消息后本地截断改标题，服务端永远是「新会话」，刷新即丢。
现在默认标题会话在首条用户消息落库后，由 Agent 协议档后台生成标题（弱结构化输出，见 §4.3.2），
先落库 `sessions.title` 再广播持久事件 `session_title`，团队协作成员实时同步。失败统一降级为
消息截断，不阻塞对话回合。无数据库迁移。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3 `session_title` 事件、§4.3.2 标题生成契约 |
| `backend/api/app/agent/title.py` | 标题生成提示词、结构化输出解析管线、截断兜底 |
| `backend/api/app/routers/ws.py` | 首条消息后 fire-and-forget 触发、行锁落库、广播事件 |
| `backend/api/tests/test_agent_title.py` | 解析契约、降级链路与触发编排单测 |
| `frontend/src/api/types.ts` | `WsServerEvent` 联合类型新增 `session_title` |
| `frontend/src/views/Agent.vue` | 事件同步侧边栏标题（实时 + 后台会话两入口） |


**V1.52（2026-08-28）— web_fetch 长文完整性与卡片预览优化**

修复 `web_fetch` 抓取知乎专栏等长文时正文被截半、卡片仅显示 500 字符预览的问题：
模型正文预算 8,000→60,000 字符（`web_fetch` 专属 `WEB_FETCH_MAX_CHARS`，与全局单条
工具结果 8,000 解耦，超限仍带 `truncated` 诚实标记，`web_search` 拼接摘要维持 8,000）；
ToolCard 预览从固定 500 字符改为与 `read` 同源对齐 `TOOL_PREVIEW_MAX_CHARS`（默认
600,000，按完整行截取），上限随 `web.preview_limit_chars` 下发，前端提示不硬编码数字；
web_fetch Markdown 结果卡片新增「渲染/源码」双视图。直接抓取路径 HTML 字节窗口
256KB→1MB。不新增 WS 事件名。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3.1 `web_fetch` 安全投影字段与正文/预览预算契约 |
| `backend/api/app/harness/execution/dispatch.py` | 新增 `WEB_FETCH_MAX_CHARS` 正文预算；`WebFetchResult` 预览对齐 `preview_char_limit()` 并下发 `preview_limit_chars`；直抓字节窗口 1MB |
| `backend/api/app/agent/react.py` | Observation 注入层为 `web_fetch` 分配 60,000 字符预算（`_observation_inject_budget`） |
| `backend/api/tests/test_harness_execution.py` / `test_agent_react.py` | 长文预算不截半、超限诚实标记、预览上限下发与注入预算回归 |
| `frontend/src/components/agent/ToolCard.vue` | 预览上限提示兼容 `web.preview_limit_chars`；web_fetch Markdown「渲染/源码」切换 |


**V1.53（2026-08-28）— web_fetch 直抓路径接入 trafilatura 正文提取**

优化爬虫脚本：直抓路径（未配置 Firecrawl 时的降级）此前用朴素 HTML 全文本展开，
导航、页脚与脚本噪声全部混入正文，且链接图片尽失。现接入 GitHub 开源库
[adbar/trafilatura](https://github.com/adbar/trafilatura)（`requirements.txt` 固定 2.2.0，
懒加载）：以可读性算法识别文章主体，丢弃噪声并保留标题层级、链接、图片与表格，
Markdown 输出与 Firecrawl 对齐。提取真实产出 Markdown 时才声明 `format=markdown`，
降级路径诚实保持 `text`。未安装依赖、提取失败或无正文时降级回内置 `_TextExtractor`，
全部失败仍报 `UPSTREAM`。SSRF 校验（入口 + 每次重定向）、1MB 受控字节窗口、
60,000 字符正文预算与卡片预览契约均不变。不新增 WS 字段。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §4.3.1 web_fetch 正文提取降级链契约 |
| `backend/api/requirements.txt` | 新增 `trafilatura==2.2.0` 依赖 |
| `backend/api/app/harness/execution/dispatch.py` | `_load_trafilatura` 懒加载、`_extract_article_with_trafilatura` 正文级提取与 `_fetch_direct` 降级链 |
| `backend/api/tests/test_harness_execution.py` | stub 路径/未安装降级/异常降级/真实提取集成四类用例 |


**V1.54（2026-08-28）— 基准数据集目录与异步导入契约**

数据集页新增“导入公开基准”的受控目录入口。页面只查询已审核目录并提交固定 release、允许 split 和受限过滤条件；服务端创建独立 `DatasetImport` 作业，下载、制品校验、解析、去重和 staging 写入由 Worker 执行。作业完成后 staging 行自动在目标数据集表格展示，只有审核发布才生成可评测版本。该版本不新增 WebSocket 事件，未修改运行时代码或数据库。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | §3.7 新增目录查询、异步导入、作业查询/重试、staging 行和审核发布契约 |
| `docs/AI测试与评估平台-PRD.md` | V1.14 新增 Benchmark 目录导入、staging 表格与 M3 验收要求 |
| `docs/AI测试与评估平台-测试数据集与黄金集采集技术方案.md` | V2.1 补充页面场景、内容筛选、首批目录、Worker 与表格保存设计 |

**V1.55（2026-08-28）— 目录治理、导入租约与不可变发布实现**

目录与 release 增加提报、不同成员复核、封禁和封禁解除 API；导入作业在独立队列领取，使用 `SKIP LOCKED`、短 lease、attempt 与回收策略。staging 读写使用 `import_id + stable row id + staging_revision`，发布使用同一 revision 和非提报成员门禁，原子创建 `DatasetVersion`。benchmark 创建时冻结版本，Worker 仅读取冻结行；不新增 WS 事件。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/dataset_catalog.py` | 目录/release 治理、导入/重试/拒绝、原子发布 API |
| `backend/api/app/routers/datasets.py` | staging 表格读写和已发布数据集的不变性保护 |
| `backend/worker/app/dataset_import.py`、`backend/worker/app/main.py` | 独立导入领取、租约回收、受控下载/解析、staging 写入 |
| `backend/api/app/routers/tasks.py`、`backend/worker/app/benchmark.py` | 任务版本冻结与正式版本读取 |
| `backend/api/app/schemas.py`、`backend/api/app/main.py` | V1.55 请求模型和路由注册 |

**V1.56（2026-08-29）— 收紧 staging 审核与发布质量门禁**

staging 保存改为仅允许非提报成员执行，并写入最小审核审计。发布前校验必填
`question/reference`、冻结 split、同 split 重复和跨 split 泄漏。目录中只有 Worker
已注册 parser 的 release 才可标记为 `supported`，避免目录展示与实际执行能力漂移。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/shared/dataset_import.py` | API 与 Worker 共用的受控 parser 注册表 |
| `backend/api/app/routers/dataset_catalog.py` | supported parser 准入与发布行质量校验 |
| `backend/api/app/routers/datasets.py` | staging 独立审核人门禁与审核保存审计 |
| `backend/worker/app/dataset_import.py` | 缺少来源 split 的行 fail-closed，并冻结 split 溯源 |
| `backend/api/tests/test_dataset_import_governance.py`、`backend/worker/tests/test_dataset_import.py` | 审核隔离、发布校验、parser 准入与 split 缺失回归 |

**V1.57（2026-08-29）— 管理端工作区分页与磁盘统计**

`GET /api/admin/workspaces` 接入 §1.1 分页约定（`offset`/`limit`、`{items,total}`），新增
`keyword` / `folder` / `deleted` 服务端过滤与整体聚合 `stats`；文件夹扫描仅对当前页会话执行，
避免会话与文件过多时全量 `os.walk` 拖慢首屏。新增 `GET /api/admin/workspaces/stats` 返回全部
工作区磁盘总字节，由前端在列表渲染后异步加载 KPI。列表响应由全量数组改为分页对象，
前端工作区管理页同步改为服务端分页筛选。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/workspaces.py` | 列表分页 / 过滤 / 聚合与 `_match_session`、`_paginate_entries` 纯函数；新增 `/stats` 磁盘总字节端点 |
| `backend/api/tests/test_admin_workspaces.py` | 过滤与分页切片单测、未登录 401 回归 |
| `frontend/src/api/types.ts` | `WorkspaceOverview` 增加 `total/offset/limit/stats`，新增 `WorkspaceStats` |
| `frontend/src/api/http.ts` | `admin.listWorkspaces` 透传分页与过滤参数，新增 `admin.workspaceStats` |
| `frontend/src/views/AdminWorkspaces.vue` | 服务端分页筛选（n-pagination + 防抖搜索），KPI 改读聚合统计与后台磁盘统计 |
| `docs/AI测试与评估平台-API.md` | V1.57：§3.12.2 补录工作区接口契约 |

**V1.58（2026-08-30）— Agent Skill 文件与协议档 Prompt 管理**

`GET /api/admin/skills` 只返回统一 `SKILL.md` 的固定头部；单文件预览与编辑通过
`/api/admin/skills/{skill_id}` 完成。读取前验证文件存在，编辑必须带回修订指纹，并由服务端验证
ID、任务类型、启用状态与工作流格式后原子保存。`GET/PUT /api/admin/agent-prompts/{profile_id}`
为每个 Agent 用途协议档提供独立补充提示词入口；核心系统提示词只读，补充层不记录正文且不能覆盖核心规则。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/admin.py` | 新增受审计的 Skill 文件目录/预览/编辑和协议档 Prompt 读写接口 |
| `backend/api/app/harness/skills/storage.py` | 技能文件存在校验、头部解析、全文按需加载、修订指纹与原子写入 |
| `backend/api/app/agent_prompt_settings.py` / `harness/prompts/system.py` | 协议档补充提示词持久化与核心策略优先级 |
| `frontend/src/api/http.ts` / `frontend/src/api/types.ts` | 对应管理端请求与类型契约 |

**V1.59（2026-08-30）— CursorAPI 模型请求字段适配**

模型目录接口保留并返回端点声明的 `parameters`。管理端在选择模型后提供动态字段选择，值编码为
`model[param=value]` 保存；这是 CursorAPI 的模型参数协议，不能改写为 OpenAI 请求体字段。模型标识含该
规格时，适配器不再附带 `reasoning_effort`。原生 Function Calling 维持既有 `native` 模式；仅在上游实际
发送摘要/思考增量时才投影思考卡。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/adapters.py` / `backend/api/tests/test_adapters.py` | 保留模型参数目录并确保 CursorAPI 规格不混入 OpenAI reasoning 字段 |
| `backend/api/tests/test_fetch_models.py` | CursorAPI 目录参数回归测试 |
| `frontend/src/api/types.ts` / `frontend/src/api/http.ts` | 模型目录参数类型与请求响应契约 |
| `frontend/src/components/modals/FetchModelsModal.vue` / `ProfileModal.vue` | 展示可选字段并生成 `model[param=value]` |
| `frontend/src/components/ProviderLogo.vue` | 使用 xAI 官方 Grok Logomark 原始路径 |

**V1.60（2026-08-31）— LangGraph 危险 bash 人工确认与过程卡收敛**

危险 bash 在执行器副作用前调用 LangGraph `interrupt()`：ToolCall 已落库后，浏览器收到
持久化 `tool_approval` 卡，原发起成员可确认或拒绝；确认回执以同一 `thread_id` 恢复原
ToolNode，拒绝不执行命令并返回可识别的 `tool_result.status="rejected"`。同时任何模型
reasoning 都只投影固定过程摘要，原生工具轮次在确认没有 ToolCall 前不再流出模型正文。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/dispatch.py` / `feedback/rules.py` | 定义 bash 风险判定、保留提权/网络/远程连接硬拒绝（含嵌套 shell 与包装写法），并将工作区删除/修改纳入 HITL |
| `backend/api/app/harness/execution/toolnode.py` | 在 bwrap Runner 前暂停、校验 approve/reject 后恢复或安全拒绝 |
| `backend/api/app/routers/ws.py` | 持久化确认卡/回执、校验原发起成员并恢复同一 LangGraph 检查点 |
| `backend/api/app/agent/react.py` / `agent/think_stream.py` | 禁止工具前草稿正文与原始 reasoning 出站，避免假性成功和思考卡泛滥 |
| `frontend/src/components/agent/ToolApprovalCard.vue` / `ToolCard.vue` / `views/Agent.vue` | 展示风险命令、确认/拒绝操作及 ToolCard 等待确认/已拒绝状态 |
| `frontend/src/api/ws.ts` / `api/types.ts` | 定义 `tool_approval_ack` 上行与两个新增持久化事件 |
| `backend/api/tests/test_bash_hitl.py` / `test_ws_clarify.py` / `test_harness_execution.py` / `test_think_stream.py` / `test_agent_react.py` / `test_stream_p3_integration.py` | 覆盖中断、确认恢复、拒绝不执行、WS 鉴权、过程摘要和 ToolCall 草稿延迟投影回归 |

**V1.61（2026-08-31）— 混合范式过程投影收敛**

Plan-and-Solve、ReAct 和 reflect 均保留在同一 LangGraph 图内，但其内部控制不得竞争
对话呈现：Plan 只产生 PlanCard，工具只产生 ToolCard，危险 bash 只产生确认卡；JSON
ReAct 的 `thought`、Plan/reflect 阶段事件和含 ToolCall 响应的模型正文草稿均不写事件、
不写消息。每回合最多显示一条无业务结论的固定过程摘要；历史重放忽略 `thought`。工具
终态之后才允许持久化 `assistant_message` 最终交付。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/agent/react.py` | 删除 JSON ReAct `thought` 事件与 ToolCall 前阶段正文；`done=true` 必须另取自然语言最终答案，不能复用内部 `thought` |
| `backend/api/app/agent/plan_solve.py` / `reflect.py` | 删除 Plan/reflect 的阶段 thought，仅保留 Plan、确认、工具终态与最终结果 |
| `frontend/src/views/Agent.vue` | 历史回放跳过 `thought`；实时阶段仅更新生成状态，单回合最多一张过程摘要卡 |
| `backend/api/tests/test_agent_react.py` / `test_agent_routing.py` / `test_agent_multiturn.py` | 回归验证三种范式不泄漏内部过程、工具前无草稿、工具后再生成最终交付 |
| `docs/AI测试与评估平台-PRD.md` / `AI测试与评估平台-Agent开发文档.md` | 同步 PRD V1.18、Agent 文档 V1.5.26 与事件边界 |

**V1.62（2026-08-31）— 工具确认抽屉**

危险 bash 的 `tool_approval` 保持持久化与可重放，但浏览器只将最新未确认项渲染为
Composer 上方抽屉；点击确认或取消即收回，消息流只保留关联 ToolCard 的“等待确认”状态。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `frontend/src/views/Agent.vue` | 将危险命令确认移至 Composer 上方抽屉，确认/取消后立即收回，历史重放同步恢复未处理抽屉 |

**V1.64（2026-09-02）— 任务工具契约收敛与取消回执**

`platform.tasks.task.create` 先使用 REST 同源的 `TaskCreate` 校验 TaskSpec，再执行会话占槽、配额与父任务状态门禁；避免缺少 `run`、协议档或 `stress` 段的任务进入 Worker。WS `cancel_task` 成功后持久化 `task_cancelled`，前端据此结束取消中状态；REST 与 MCP 的终态取消均幂等返回当前任务。纯对话 Agent 仍不注入工具定义，工具中心只表示已注册的执行基础设施。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/task_tools.py` / `registry.py` | MCP TaskSpec 同源校验，并补齐 run/stress/case_source Schema。 |
| `backend/api/app/routers/tasks.py` / `routers/ws.py` | 统一终态取消幂等语义，WS 改发 `task_cancelled`。 |
| `frontend/src/api/types.ts` / `views/Agent.vue` | 接收 `task_cancelled` 并可靠收尾任务进度坞。 |
| `backend/api/app/routers/mcp.py` / `frontend/src/views/AdminProfiles.vue` | 明示工具已注册但当前纯对话 Agent 未接线。 |
| `backend/api/tests/test_task_tools.py` / `test_task_permissions.py` | 覆盖 MCP 完整 TaskSpec 门禁与终态取消幂等。 |

**V1.66（2026-09-03）— 混合引擎 H1 Router 审计契约**

`response.completed` payload 在 `hybrid_engine_enabled=true` 时新增可选 `engine` / `router_confidence` / `router_reason` 审计字段：`engine` 为 Router 分流结论（本轮唯一写入点、不可变），H1 阶段 `workflow` / `agent` 降级按 `chat` 执行并经 `router_reason` 标注；取消 / 异常收尾路径在 Router 已执行时同样携带。L0 纯函数零模型调用、可复现性 100%；L1 CoT 仅在置信度低于阈值（默认 0.7）且开关开启时触发一次 `router.v1` JSON 短调用（计入回合预算），任何失败回落 L0、L0 无结论回落 `chat`。`direct` 仅承认收包循环既有 `/stop`，图内其余斜杠为防御性拒绝（`finish_reason="error"`、零模型调用）。新增 `GET /api/agents` Worker 只读目录（§3.6.3）。不新增 WS 事件名，不恢复 `thought` / `tool_*`；主开关关闭时 payload 与 V1.65 完全一致。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | 本版契约：§4.3 事件表与 Router 审计字段说明、§3.6.3 Worker 目录、头部版本与变更记录 |
| `backend/api/app/agent/router_node.py` | 新增 Router 节点壳：L0 确定性打分纯函数、L1 `router.v1` 短调用与全量回落链、direct 防御节点 |
| `backend/api/app/agent/graph.py` | `hybrid_engine_enabled` 双拓扑：关闭保持 `START → chat_stream → END`；开启接入 `router` 条件边四路分流（H1 降级）；新增 `router_audit_from_update` |
| `backend/api/app/agent/routing.py` | `chat_stream` 收尾 `response.completed` 在 `engine` 存在时附带三个审计字段 |
| `backend/api/app/harness/memory/state.py` | `GraphState` 新增 `engine` / `router_confidence` / `router_reason` / `agent_id` / `allowed_tools` / `workflow_step`（既有 `mode` 不重命名不驱动） |
| `backend/api/app/harness/prompts/protocols.py` / `prompts/__init__.py` | 新增 `router.v1` 协议 Schema 与 `parse_router` 严格解析并导出 |
| `backend/api/app/routers/ws.py` | 取消 / 异常收尾路径携带 Router 审计三元组（O2 信号采集载体） |
| `backend/api/app/routers/agents.py` | 新增 `GET /api/agents` 只读目录（静态注册表脱敏投影） |
| `backend/api/app/main.py` | 注册 `/api/agents` 路由 |
| `frontend/src/api/types.ts` | `ResponseCompletedPayload` 类型同步（可选审计字段） |
| `backend/api/tests/test_hybrid_h1_router.py` | L0 五次一致性、阈值两侧、L1 回落矩阵、S1 零工具、开关关闭快照回归、direct 零模型调用、目录端点投影 |

**V1.69（2026-09-03）修复代码文件与作用清单：**

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/orchestration/router.py` | 收窄工作流意图识别，避免概念问答误入队；识别“先评后压”复合意图。 |
| `backend/api/app/agent/router_node.py` | 保留带本地读取前置步骤的 Agent 路径；将已启用的 L1 `skill_id` 传入 Workflow。 |
| `backend/api/app/agent/workflow_nodes.py` | 优先采纳 L1 技能、只提取显式资源标识，并生成 `with_stress=true` 的质量评测任务规格。 |
| `backend/api/app/routers/ws.py` | 确认重放在清卡前预占回合；仅 W6 真实入队后发送成功回执，失败时恢复确认卡。 |
| `backend/api/tests/test_hybrid_h1_router.py`、`test_hybrid_h2_workflow.py`、`test_hybrid_h2_confirm_card.py`、`test_hybrid_e2e_h0_h3.py` | 覆盖误路由、L1 技能传递、显式槽位、先评后压与确认卡恢复的回归场景。 |

**V1.68（2026-09-03）— 混合引擎 Workflow 确认卡恢复（H2 批次 2）**

`confirm` / `confirm_ack` 事件自 V1.63 骨架化移除后恢复（语义与 V1.62 一致，产出来源改为 Workflow 子图 W5 `await_confirm`，随批次 1 的 `workflow_nodes.py` 落地）；`confirm_ack` 上行恢复接受（§4.4 三类上行，§9 同步）。W5 首次到达时发卡并收尾本轮（`confirm` + 阶段叙述 + `response.completed(stop)`），用户确认后在同一 `sessions.pending_confirm` 行锁事务内完成 owner 校验、并发检测、patch 深合并、TaskSpec 同源校验与清卡，再以 `workflow_confirm` 注入重放回合——**入队唯一经 W6**（`enqueue_long_task`），W7 收尾并回 `confirm_ack{ok,task_id,message}`。未批准/取消只清卡不入队；重复确认或无待确认卡返回 `VALIDATION`（「无待确认卡」），并发已处理为 `CONCURRENCY`，绝不重复入队。仅 `hybrid_engine_enabled=true` 且 `engine=workflow` 时可达，主开关关闭时行为与 V1.66 完全一致。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | 本版（V1.68）契约：§4.3 恢复 confirm/confirm_ack 事件行与 Workflow 阶段叙述说明、§4.4 恢复 confirm_ack 上行语义、§9 上行枚举同步、头部版本与变更记录（V1.67 为 H3 工具事件契约） |
| `backend/api/app/agent/workflow_nodes.py` | W5 扩展：无确认上下文时发卡（confirm 事件 + 叙述 + completed）并以 `workflow_failed` 短路 W6；回执缺失必填时补 completed(error)；抽 `_completed_payload` 与 W7 共用 |
| `backend/api/app/agent/graph.py` | 新增 `enqueued_task_id_from_update`（供 ws 层回执带回 W6 入队结果） |
| `backend/api/app/routers/ws.py` | `_run_turn` 注入 `db_factory`/`session_id`/`user_id`/`session_probe`/`workflow_confirm`；confirm 事件落 `pending_confirm`（行锁 + confirm_author）；`confirm_ack` 上行经行锁事务后派生重放回合（入队唯一经 W6） |
| `frontend/src/components/agent/ConfirmCard.vue` | 从 V1.62 历史恢复确认卡组件（字段与 `agent/defaults.py` / §5 双端同步） |
| `frontend/src/api/ws.ts` / `api/types.ts` | `confirm_ack` 上行与 confirm/confirm_ack 事件类型恢复 |
| `frontend/src/views/Agent.vue` | 确认卡渲染、ack 交互、历史回放与 `pending_confirm` 覆盖、选项预装 |
| `backend/api/tests/test_hybrid_h2_confirm_card.py` | 新增 10 例：W5 发卡收尾、默认值对齐、confirm_id 互斥、回执重放入队、必填缺失不回环、ack 行锁事务（owner/重复/校验保留卡/深合并清卡/取消） |

**V1.70（2026-09-03）— 混合引擎 H5 持久化 HITL 批次 1（契约先行）**

`tool_approval`（服务→前端，持久化）与 `tool_approval_ack`（前端→服务，恢复回执）自 V1.63 骨架化移除后恢复为现行事件。危险 bash 在执行副作用前由图内 `interrupt()` 暂停，ToolCall 已落库后浏览器收到持久化 `tool_approval` 卡；服务端在 `sessions.pending_confirm` 行锁事务内校验 owner/卡种/`id`/action 后**先清卡提交**（一次性 `resume_nonce` 消费即失效），再以原中断回合的 `thread_id` 经 `Command(resume=...)` 恢复 ToolNode，**resume 至多一次**。审批卡 JSONB 带 `meta`（`schema_version=1`/`confirm_type="tool_approval"`/`thread_id`/`resume_nonce`/`owner_id`/`created_at`），广播 `tool_approval` 时剥离 `meta`。`tool_approval_ack` 上行 payload `{id, action:"approve"|"reject"}`，服务端回执 payload `{action, approval_id}`。确认前与拒绝后均不得调用 Runner；该暂停状态为单 API 副本/按 `session_id` 粘性路由前提。**批次 2（`PgCheckpointer` 生产切换 + 网关粘性路由落地 + 重启恢复演练 + `worker.sandbox` 安全评审）未完成前，`worker.sandbox` 的 `bash` 仍不可被 discover 选中**。本版为契约先行，仅修改 API.md；对应代码与测试在 H5 批次 1 PR（#211）已合入，批次 2 代码待后续 PR。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-API.md` | 本版（V1.70）契约先行：§4.3 新增 `tool_approval` 事件行、§4.4 恢复 `tool_approval_ack` 上行语义与四类上行枚举、§4.3.1 `worker.sandbox` 注释更新为批次 2 前置、§9 上行枚举同步、头部版本与变更记录 |

**V1.78（2026-09-09）— 审批卡终态按卡型归类 + 配额/文案评审修订（G6 评审 M1–M3）**

`approval_terminal` payload 增可选 `card_type`（缺省 approval 兼容旧事件）：`recovery_failed` 对澄清卡恢复失败同样广播并携带 `card_type="clarify"`；`expired`/`voided`/`cancelled` 恒为审批卡（payload 统一带 `card_type="approval"`）。错误码 `DENIED`（403）口径收敛为 bash 只读档拒写（read-only 只约束 bash，§6.1.1 口径）；配额卷水位核算失败 fail-closed 拒写。G6b（配额/终态）与 M1–M3 合并登记于本版（V1.78）；G6a 升档审批主体此前随 #235 合入 main（其契约见错误码表与事件表，此处不重复登记）。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/ws.py` | `_start_card_resume` 增 `card_type`（approval/clarify），recovery_failed 广播携带；expired/voided/cancelled 终态 payload 统一带 `card_type="approval"` |
| `backend/api/app/harness/execution/quota.py` | 卷水位核算失败返回 -1 哨兵 → fail-closed 拒写（原 fail-open 放行，M2） |
| `backend/shared/sandbox_kernel.py` / `backend/api/app/errors.py` / `backend/api/app/harness/execution/toolnode.py` | DENIED 消息与升档卡 `sandbox_scope` 文案口径收敛（bash read-only 档；去开关依赖的升档指引，M1） |
| `frontend/src/views/Agent.vue` / `frontend/src/components/agent/ClarifyCard.vue` | approval_terminal 按 `card_type` 路由（实时 + 历史回放）；ClarifyCard 增 `clarifyDone='failed'` 终态展示；canActClarify 排除 failed |
| `backend/api/tests/test_approval_terminal.py` / `test_workspace_quota.py` | 新增 recovery_failed 卡型归类（clarify/approval 各一）与水位核算失败 fail-closed 用例 |
| `docs/AI测试与评估平台-API.md` | 本版（V1.78）契约修订 + V1.77 追溯登记（头部引用块、错误码表、§4.3 事件表） |

### V1.79 修改代码文件与作用清单（2026-09-09）

`agent/loop_presentation.py`、`agent/events.py`、`agent/loop.py`、`agent/loop_wiring.py`：安全预览、持久思考与实际请求统计；`agent/loop_service.py`、`routers/ws_v2.py`：问答标签数组与重同步控制权；`harness/memory/agent_events.py`：授权有序快照；`harness/contracts/loop_events.py`：目录 v4；`routers/sessions.py`：草稿/会话 UI 能力；`routers/files.py`：上传者或可见会话引用访问；`frontend/src/api/agentLoop*` 与 `agent/loop`/`components/agent/loop`：新前端 reader 与命令接线。完整阶段状态见前端重写计划 §11。

**V1.82（2026-09-09）— 管理端工作区下线 + 智能体新建工作区**

管理端「工作区管理」整体下线（产品决策，无迁移路径——legacy 目录遗留由运维按数据卷直接处置，
不再提供在线孤儿清理）；用户域工作区契约不变并重编号为 §3.12.2。智能体草稿会话绑定面板新增
「新建工作区」入口（即建即绑）。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/routers/workspaces.py` | 删除（管理端 `/api/admin/workspaces` 路由整文件下线） |
| `backend/api/app/main.py` | 移除 `workspaces.router` 注册与导入 |
| `backend/api/app/workspace_service.py` | 删除 `orphan_direct_children`，头注同步 |
| `backend/api/tests/test_admin_workspaces.py` | 删除（随路由下线） |
| `backend/api/tests/test_user_workspaces.py`/`test_sandbox_review_fixes.py` | 移除 admin 导入与孤儿/管理端目录定位测试 |
| `frontend/src/views/AdminWorkspaces.vue` | 删除（管理端工作区页面） |
| `frontend/src/router/index.ts`/`frontend/src/layouts/MainLayout.vue` | 移除 `/admin/workspaces` 路由与侧边栏菜单 |
| `frontend/src/api/http.ts`/`frontend/src/api/types.ts` | 移除 `api.admin.*` 工作区接口与专属类型（保留 `WorkspaceFolder`） |
| `frontend/src/views/Agent.vue` | 草稿绑定面板新增「新建工作区」（`createDraftWorkspace` 即建即绑） |
| `docs/AI测试与评估平台-API.md` | V1.82：§3.12.2 下线登记、原 §3.12.3 重编号、版本与清单更新 |

**V1.83（2026-09-09）— Agent 消息链路兼容修复**

无新增 REST/WS 字段与数据库迁移。默认思考偏好不支持时解析到 off；显式选择仍严格校验。DeepSeek/Qwen Anthropic 流按兼容模型接收空签名，off 显式下发。具体证据与验证边界见 [消息链路兼容修复](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E6%B6%88%E6%81%AF%E9%93%BE%E8%B7%AF%E5%85%BC%E5%AE%B9%E4%BF%AE%E5%A4%8D.md)。

| 修改代码文件 | 作用 |
| --- | --- |
| `backend/api/app/agent/loop_wiring.py` | 默认偏好与显式档位分开校验 |
| `backend/api/app/llm/providers/anthropic.py`、`options.py` | 兼容空签名的收流/回填与真实 off 参数 |
| `frontend/src/utils/requestId.ts`、`api/agentLoopWs.ts`、`components/agent/loop/AgentWorkspace.vue`、`AgentComposer.vue` | HTTP 消息/附件/命令标识，超时与原请求重试 |
| `frontend/vite.config.js`、`frontend/.env.example` | REST/WS 同源开发代理配置 |
| `backend/api/tests/test_loop_profile_selection.py`、`test_loop_llm.py`、`test_loop_llm_sdk.py`；`frontend/tests/requestId.test.mjs`、`agentLoopWs.test.mjs`、`e2e/agentLoop.spec.ts` | 回归配置、真实 SDK/Runtime、HTTP 浏览器与超时场景 |

**V1.84（2026-09-09）— 废除首次登录强制改密机制**

产品决策：移除「首次登录强制改密」全链路。开户、重置密码与引导成员不再置 must_change_password=true；登录不再被强制改密 Modal 拦截；users.must_change_password 列与响应字段保留（恒 false，兼容历史行与请求体）。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/shared/models.py` | User.must_change_password 默认值 true → false（列保留） |
| `backend/api/app/schemas.py` | UserCreate.must_change_password 默认 true → false（字段保留兼容） |
| `backend/api/app/routers/users.py` | 开户恒 false；reset-password 不再置 true |
| `backend/api/app/routers/auth.py` / `app/main.py` | change-password 不再维护标记；bootstrap 恒 false |
| `frontend/src/views/Login.vue` | 删除强制改密弹窗/状态/拦截分支/提交函数 |
| `frontend/src/layouts/MainLayout.vue` / `frontend/src/stores/auth.ts` | 改密弹窗收敛普通形态；移除 mustChangePassword getter |
| `docs/AI测试与评估平台-API.md` / `docs/AI测试与评估平台-PRD.md` / `AGENTS.md` | V1.84 契约与产品语义登记 |

**V1.85（2026-09-09）— 思考滑块与兼容模型请求参数**

无新增 REST/WS 字段。`allowed_efforts` 与实际调用继续共用 resolver；DeepSeek V4 开放 off/high/max，Qwen3.6 Flash 开放预算档位。传输边界、厂商依据和线上验证限制见 [消息链路兼容修复 V1.1](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E6%B6%88%E6%81%AF%E9%93%BE%E8%B7%AF%E5%85%BC%E5%AE%B9%E4%BF%AE%E5%A4%8D.md)。

| 修改代码文件 | 作用 |
| --- | --- |
| `backend/api/app/llm/providers/options.py`、`llm/loop_contracts.py` | 兼容 effort/预算映射，限制 output_config 结构 |
| `frontend/src/components/agent/loop/ThinkingControl.vue` | 单候选明确不可调节 |
| `backend/api/tests/test_loop_profile_selection.py`、`test_loop_llm.py`、`test_loop_llm_sdk.py`、`frontend/tests/e2e/agentLoop.spec.ts` | 验证 UI 候选、WS 档位、SDK HTTP 参数与换档后的工具回填 |

**V1.89（2026-09-10）— 工作区图片与文件搜索工具**

`read_image`、`glob`、`grep` 为 AgentLoop 已接线的原生只读工具。它们只访问会话绑定的工作区：
搜索跳过版本库、依赖缓存与符号链接；图片只支持≤4MB 的 PNG/JPEG/GIF/WebP，图片数据只在
当前模型回合传递，绝不写入 WS、ToolCard、事件日志或恢复快照。

| 实际修改文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/execution/registry.py` | 注册三项工具、字段 Schema、只读权限、输出投影与恢复提示 |
| `backend/api/app/harness/execution/dispatch.py` | 统一 realpath 工作区边界；实现图片头解析和受限图文块、glob/grep 遍历与结果上限 |
| `backend/api/app/harness/execution/loop_tools.py` / `scheduler.py` | 将图片图文块仅回填给当前模型请求，持久终态仍保存安全文字摘要 |
| `backend/api/app/agent/loop_wiring.py` / `harness/execution/loop_bridge.py` | 将三项工具加入 AgentLoop 白名单与只读并行调度集合 |
| `backend/api/tests/test_harness_execution.py` / `test_loop_tools.py` | 覆盖注册、图片字节不落日志、工作区/VCS 边界与无效输入 |
| `docs/AI测试与评估平台-API.md` | V1.89：§4.3.1 原生工具契约与本清单 |

**V1.90（2026-09-10）— 原生工具输出 Schema 闭合校验**

工具注册期进一步约束受限 JSON Schema：同层 `required` 中每个字段必须在同层
`properties` 声明，拼写错误或不可满足的 Schema 一律以 `VALIDATION` 拒绝登记。运行期
`output_schema` 校验对象统一为浏览器对外的 `display` 投影；含 `model_text`、图文块、
溯源等内部字段的外层包装不属于输出契约。`read_image`、`glob`、`grep` 的成功展示投影均
设为闭合对象，固定字段缺失、类型不符或多余字段均归一为 `INTERNAL`，不向浏览器泄露内部结果。

| 修改文件 | 作用 |
| --- | --- |
| `backend/api/app/harness/execution/registry.py` | 校验 `required ⊆ properties`，闭合三项原生工具的展示输出 Schema |
| `backend/api/app/harness/execution/dispatch.py` | 按 `to_tool_data().display` 执行输出 Schema 校验，隔离模型内部回填字段 |
| `backend/api/tests/test_harness_execution.py` | 覆盖无效 required、图片图文外层与闭合展示投影 |
| `docs/AI测试与评估平台-API.md` | V1.90：登记 Schema 闭合校验规则 |

**V1.91（2026-09-10）— 工具 Schema 轨迹快照**

`assistant.start.data.request_summary.tools[]` 对齐 DeepSeek Harness 的原生工具定义：
`name`、`description`、`parameters`。`parameters` 为 JSON Schema 根对象，不再把
`parameters_schema` 暴露为新的 v2 轨迹字段；前端轨迹页默认在工具记录打开 Schema 标签，
以工具描述和可折叠 JSON Schema 展示本轮真实快照。为保证历史回放可读，旧快照仍接受
`parameters_schema` 作为仅前端的兼容回退。

| 修改文件 | 作用 |
| --- | --- |
| `backend/api/app/agent/loop_presentation.py` | 生成 DSH 外形的工具请求快照 |
| `backend/api/tests/test_loop_presentation.py` | 固化 `name/description/parameters` 轨迹契约 |
| `frontend/src/components/agent/loop/TraceWorkspace.vue` | 优化事件时间线、工具详情与 Schema 面板，并兼容旧快照 |
| `frontend/tests/agent-loop-style-preview.html` | 使用新工具快照格式提供轨迹样式预览 |
| `docs/AI测试与评估平台-API.md` | V1.91：§4A 字段契约与本清单 |

**V1.93（2026-09-11）— AgentLoop 任务工具命名兼容与状态卡片**

`task.create`、`task.status`、`task.cancel` 的注册表短名、模型 Function Calling
安全 wire 名和 MCP 目录全名由同一后端命名契约统一。模型请求保持
`platform_task_create/status/cancel`，调度器仅接受该名称、注册表短名或已登记的
`platform.tasks.task.create/status/cancel`，并始终使用同一个 `ToolDef` 的输入/输出
JSON Schema 与 MCP `tool_id`；未知别名不得推断为平台工具。调用事实的 `name` /
`wire_name` 保留模型原始回传，`registry_name` 固定为短名。前端 Task 卡片读取这些已
脱敏工具展示字段，再按返回的 `task_id` 关联持久 `task.queued/progress/report/end` 事实；
Worker 事实覆盖一次调用快照，不新增浏览器 WS 字段。

| 实际修改文件 | 作用 |
| --- | --- |
| `backend/api/app/harness/execution/task_contract.py` | 固化任务工具三层名称与只读归一函数，不复制 JSON Schema。 |
| `backend/api/app/harness/execution/loop_bridge.py` / `scheduler.py` | 为本轮模型注册安全 wire 名，受控接纳三种既有名称并保持原始 wire 审计。 |
| `backend/api/app/agent/loop_presentation.py` | 三种任务名称投影同一字段白名单与安全展示短名。 |
| `frontend/src/agent/loop/taskPresentation.ts` / `components/agent/loop/TaskRunCard.vue` | 从安全预览和 Worker 事实构建实时 Task 卡片。 |
| `backend/api/tests/test_loop_tools.py` / `test_loop_presentation.py` / `frontend/tests/agentLoop.test.mjs` | 覆盖 Schema 同源、三名称路由、脱敏展示及前端状态关联。 |

**V1.95（2026-09-11）— 原生 task 会话规划快照**

原生 `task` 采用 DeepSeek Harness `todo_write` 的会话规划语义：模型每次提交完整
`steps` 列表，成功写入的最后一个 `task_plan.updated` 即为该 Agent 会话当前计划。该事件
包含 `plan:{goal,description,steps,counts}`，与同一 `tool.result` 在一个事务提交；它必须引用
同一回合、步骤、attempt、调用和 `tool.call` 序号，且快照必须逐字等于成功 `task` 的规范参数。
因此失败调用或 `tool.call` 草稿不会覆盖已生效计划。浏览器只消费该持久事件构建
`TaskStateDrawer`，断线重连和状态快照均按事件流回放；工具轨迹保留展示价值，但不是计划状态源。

| 实际修改文件 | 作用 |
| --- | --- |
| `backend/api/app/harness/execution/{dispatch,scheduler}.py` | 规范任务快照、限制顺序规划单活跃步骤，并把 task 成功结果与快照作为一组提交。 |
| `backend/api/app/harness/memory/agent_events.py` / `harness/contracts/loop_events.py` / `agent/events.py` | 登记、校验并投影 `task_plan/updated` 事实。 |
| `frontend/src/{api/agentLoopTypes.ts,agent/loop/reducer.ts,components/agent/loop/AgentWorkspace.vue}` | 只按权威规划事件更新和恢复抽屉，不再读取工具调用草稿。 |
| `backend/api/app/routers/mcp.py` | 修正工具目录中已过期的 task handler、字段与管线描述。 |
| `backend/api/tests/test_loop_tools_pg.py` / `test_loop_presentation.py` / `frontend/tests/agentLoop.test.mjs` | 覆盖原子提交、失败不覆盖、重连回放及前端投影。 |

**V1.98（2026-09-13）— 用户工作区音视频流式预览播放与文件上传**

用户工作区新增影院级音视频播放器与全格式文件上传能力：
`GET /api/workspaces/{id}/files/raw` 引入 `download: bool = false` 参数与完整音视频 MIME 映射，默认 `inline` disposition 配合 Starlette FileResponse 提供的 HTTP 206 Range 支持，实现音视频在浏览器端秒开拖拽与流式播放；
新增 `POST /api/workspaces/{id}/files/upload` 端点与前端拖拽/工具栏上传，支持多格式文件直接写入工作区，受目录防穿越与磁盘配额检查约束并记录审计日志。前端新增 `WorkspaceVideoViewer` 影院级播放器，支持时间轴拖拽、倍速播放（0.5x–2.0x）、音量记忆、全屏、画中画（PiP）、快进/快退快捷键与错误容错回退。

| 实际修改文件 | 作用 |
| --- | --- |
| `backend/api/app/workspace_service.py` | 新增 `save_workspace_file_bytes` 写入函数，封装目录规范化、安全校验与文件写入 |
| `backend/api/app/routers/user_workspaces.py` | `get_raw_file` 增加 `download` 参数与 MIME 映射支持 inline 播放；新增 `upload_workspace_file` 端点 |
| `backend/api/tests/test_user_workspaces_files.py` / `test_user_workspaces.py` | 覆盖文件上传工具函数、raw/upload 未认证安全阻断与单测用例 |
| `frontend/src/api/http.ts` | 新增 `getRawFileUrl` (带 download 参数) 与 `uploadFile` API 客户端方法 |
| `frontend/src/components/workspace/WorkspaceVideoViewer.vue` | 新增影院级视频播放器组件，支持进度控制、音量记忆、倍速、全屏与元数据展示 |
| `frontend/src/views/UserWorkspaces.vue` | 接入视频播放器、音视频文件图标识别、工具栏上传按钮及文件树拖拽上传能力 |
| `docs/AI测试与评估平台-API.md` | V1.98：§3.12.2 接口契约更新与修订清单 |

## 2026-09-09 协议档供应商与完整 URL 优化

详见 [协议档供应商思考适配](AI测试与评估平台-协议档供应商思考适配.md) V1.0：十个供应商新建入口、真实模型品牌图标、只读能力投影及 `full_url` 字段以该节定义为准。管理页和编辑弹窗删除思考强度设置，仅在对话输入框选择；AgentLoop 按供应商能力初始化，不再继承 legacy 全局思考偏好。完整 URL 开启后不追加版本或协议后缀，后台主模型调用使用同一规则。

**V1.99（2026-09-13）— AgentLoop 模型错误安全摘要**

模型 SDK 的结构化状态码和错误类别只用于服务端分类，不透传上游正文。失败的
`assistant.end` 可选增加 `error_message`，与已有 `error_code` 一起显示在对应模型
回复下方：额度或余额耗尽为 `BUDGET_EXCEEDED`，输入超过模型上下文限制为
`VALIDATION`，限流、认证失败、模型不可用、连接失败与服务端异常为 `UPSTREAM`。
每类场景只发送固定的中文处理建议；API Key、供应商错误正文、请求参数和堆栈不进入
事实、回放或浏览器事件。该字段为既有事件的可选增量，旧客户端可以忽略。

| 实际修改文件 | 作用 |
| --- | --- |
| `backend/api/app/llm/loop_contracts.py` | 从安全结构化错误字段识别额度、上下文、限流、认证与模型状态，并生成平台码和固定摘要。 |
| `backend/api/app/agent/loop.py` / `agent/events.py` | 将模型内部分类收敛为平台错误码，并在失败 `assistant.end` 白名单投影 `error_message`。 |
| `frontend/src/components/agent/loop/AgentWorkspace.vue` | 在失败的模型回复下展示错误码和安全中文处理建议。 |
| `backend/api/tests/test_loop_llm.py` / `test_loop_ws_protocol.py` / `frontend/tests/agentLoop.test.mjs` | 覆盖分类、脱敏投影与前端回放状态。 |
| `docs/AI测试与评估平台-API.md` | V1.99：记录失败 `assistant.end` 的错误字段和映射口径。 |



### V2.2 修改代码文件与作用清单（审查日期：2026-09-15）

| 文件 | 作用 |
| --- | --- |
| backend/api/app/llm/providers/reasoning_templates.py、llm/loop_contracts.py | 按供应商方言编码并允许受控整数强度；模型名称只作推荐 |
| backend/api/app/profile_probe.py、profile_reasoning.py | 正反向证据、结束状态、总截止时间、同参去重及模板版本失效 |
| backend/api/app/schemas.py、routers/profiles.py、routers/sessions.py | reasoning_mode 与待验证状态、安全失败原因 |
| frontend/src/api/types.ts、api/agentLoopTypes.ts | 对应增量字段类型 |
| frontend/src/components/agent/loop/ThinkingControl.vue、AgentComposer.vue | 按真实模式展示控件 |
| frontend/src/components/modals/ProfileModal.vue | 模型变更与批量推荐 |
| backend/api/tests/test_reasoning_templates.py、test_loop_profile_selection.py | 参数与探测回归、响应字段边界 |

完整实现边界及官方来源见[模型思考模板自动继承实施方案 V1.3](./AI测试与评估平台-模型思考模板自动继承实施方案.md)。

### V2.4 修改代码文件与作用清单（审查日期：2026-09-15）

本次不改变 REST 或 WS JSON 字段，只扩充协议档目录数据及其受控模板。新建协议档按
供应商和协议分别填充 Base URL；NVIDIA NIM 的 Anthropic 地址必须填写实际部署根地址。

| 文件 | 作用 |
| --- | --- |
| `frontend/src/utils/profileVendors.ts`、`components/modals/ProfileModal.vue` | 登记供应商协议矩阵，切换协议时同步 URL、模型与模板，并禁用官方未提供的组合 |
| `backend/api/app/llm/providers/reasoning_templates.py`、`anthropic.py`、`catalog.py` | 增加 DeepSeek/NIM Messages 模板、兼容思考块回放和 MiniMax 中国区域名识别 |
| `frontend/tests/profileVendors.test.mjs`、`backend/api/tests/test_reasoning_templates.py` | 覆盖官方 URL、协议支持、模板请求字段与托管服务识别 |
| `docs/AI测试与评估平台-PRD.md`、`AI测试与评估平台-协议档供应商思考适配.md` | 固化 V1.26 产品规则和 V1.1 官方依据 |

## V2.5 专家协作 P0 内部契约登记（2026-09-15）

对应 PRD V1.27。以下是原生 AgentLoop 的内部扩展接缝，**未新增可调用的 REST/WS 命令、模型工具或前端事件**。`agent.list/spawn/status/wait/result/cancel` 仍待 P1 契约冻结与实现，不能依据方案名称尝试调用。

### 身份与日志

| 概念 | 内部契约 |
| --- | --- |
| `FactLog` | `session_id`、`append(kind, data)`、`read()`；追加返回含 `seq/ts/type/data` 的已提交事实；序号和历史仅属于本日志 |
| `RuntimeLog` | 在事实端口上增加 `actor_id`、`command_context`；持久日志可继续通过 `begin_turn` 原子接收输入；主 `SessionLog` 保持原实现 |
| 子运行日志 | 另有不可变的非空 `run_id`；P0 只有测试替身，生产存储与事务守卫未实现 |
| 授权身份 | `session_id` 始终为真实所属会话，工具 ACL 不得用运行键代替 |
| 执行身份 | 内部审批/图命名空间按 `session_id + run_id` 分离；运行缓存采用二元组；主运行不带 `run_id`，保持旧键 |
| 子运行发布 | Runtime 的进程内订阅携带 `run_id`；不直接进入主会话 WS 流，后续须经过持久 outbox 和主写者投影 |

### 生命周期与预算

- `TurnDependencies.children` 是可选的回合所有权对象，非客户端字段。为空时保留既有行为；非空时，图正常终态与 Runtime 取消/异常收尾均先收拢子任务。
- `TurnChildren.start` 先检查是否收尾及累计创建上限，再构造协程。关闭幂等，重复取消不跳过子任务的异步清理。任务已结束不代表业务成功，最终运行结果仍须由 P1 状态机验证。
- `BudgetedAdapter` 包装已授权、冻结配置的原适配器，保留唯一 AgentLoop 的重试策略。每个运行必须使用服务端分配的稳定身份，并共享同一个 `ModelCallBudget` 对象；未装配该对象的既有会话不受新限额影响。
- 额度耗尽使用内部 `collaboration_call_budget`，对外仍为既有 `BUDGET_EXCEEDED`；协作关闭后禁止新请求，使用 `CONCURRENCY`。这些错误不可重试，不能新增第十一种平台错误码。
- 当前计数在进程内有效，进程重启后不能据此恢复调用或重新分配预算；后续持久预留、未知用量处理、总金额上界及权限相交需另行冻结和验收。

### 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/harness/contracts/fact_log.py` | 抽出日志端口与独立运行命名空间 |
| `backend/api/app/agent/loop.py`、`runtime.py`、`collaboration_scope.py` | 同一图中的回合归属、审批域和取消收尾 |
| `backend/api/app/agent/model_budget.py` | 共享调用次数/并发限制，无新的重试循环 |
| `backend/api/app/harness/execution/scheduler.py`、`approval.py` | 工具执行身份透传和审批路由隔离 |
| `backend/api/tests/test_subagent_foundations.py` | P0 并发与取消实验；验证状态详见技术方案 §22 |

## V2.6 专家协作 P1 契约（2026-09-16）

### 模型调度工具

主回合选择 `general` 专家且 `agent_subagents_enabled=true` 时，模型可见以下六个工具。模型 wire 名由平台把点号转为安全名称（如 `agent.spawn` → `platform_agent_spawn`），事实中的 `registry_name` 保留短名。子运行不注入这些工具，因此 P1 最大委派深度固定为 1。

| 工具 | 必填输入 | 语义 |
| --- | --- | --- |
| `agent.list` | 无 | 返回可调度专家的公开摘要 |
| `agent.spawn` | `expert_id,goal,output_contract` | 原子创建实例和首次运行，立即返回 `collaboration_id/instance_id/run_id/status` |
| `agent.status` | `run_ids[1..8]` | 按输入顺序返回状态与结果可用性 |
| `agent.wait` | `run_ids[1..8]` | `mode=any\|all`，`timeout_seconds=0..30`；等待不占模型请求槽 |
| `agent.result` | `run_id` | 返回终态成果；未终态时 `available=false` |
| `agent.cancel` | `run_id,reason` | 先持久化取消请求与回执，再停止本地运行 |

`agent.spawn` 与 `agent.cancel` 使用服务端注入的 `caller_run_id + call_id` 作为幂等身份。同一身份和相同参数返回原回执；不同参数返回 `CONCURRENCY`。首期每协作最多 8 个实例、3 个并发模型流、80 次模型调用、每个专家 20 次调用；主 Agent 与子 Agent 共用调用账本。该硬限制只针对调用次数，不表示 token 或金额硬预算。

子运行权限取主会话、平台白名单和专家声明交集，且因 P1 没有子运行人工审批通道，只注入当前档位可以自动执行的工具：tier1 为文件/图片只读与 glob/grep，tier2/tier3 才可按既有档位规则获得写改和公开网页能力。不开放 `bash`、人工交互、Worker 任务或继续委派。每个运行使用会话沙箱下 `.subagents/<run_id>` 独立目录。子日志只写 `agent_run_events`，不会把专家历史合并进主会话模型历史。

### REST 查询与停止

| 方法与路径 | 返回/输入 | 权限 |
| --- | --- | --- |
| `GET /api/sessions/{session_id}/collaborations?limit=20` | `{items: AgentCollaborationSummary[]}` | 沿用会话可见性 |
| `GET /api/collaborations/{collaboration_id}` | 协作、预算和 `runs[]` 安全投影 | 沿用父会话可见性 |
| `GET /api/agent-runs/{run_id}/events?after_seq=-1&limit=100` | 独立运行事实分页 | 沿用父会话可见性 |
| `POST /api/collaborations/{collaboration_id}/cancel` | `{reason}` → `{accepted,run_ids}` | 仅父会话创建者 |
| `POST /api/agent-runs/{run_id}/cancel` | `{reason}` → `{accepted,run_id}` | 仅父会话创建者 |

协作状态为 `running/succeeded/failed/cancelled`；运行状态为 `queued/running/succeeded/failed/cancelled`。页面通过持久 REST 投影恢复并在活动期短轮询，因此刷新或 WS 重连不会生成重复实例。P1 仍是前台同进程执行：主回合终态前会停止并等待未完成子任务；跨进程租约恢复、后台续跑、信箱和共享工作项属于 P2/P3。

### V2.6 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/shared/models.py`、`backend/api/migrations/versions/f70e5a53bd54_新增专家协作与子运行事实表.py` | 五类持久实体及 Alembic 自动生成迁移 |
| `backend/api/app/agent/{collaboration.py,subagent_log.py,subagent_tools.py}` | 调度器、独立事实日志与六工具契约 |
| `backend/api/app/agent/loop_wiring.py`、`harness/execution/loop_bridge.py` | 主回合工具装配、权限交集、共享预算和协作回调 |
| `backend/api/app/routers/collaborations.py` | 会话可见投影、事实分页与停止入口 |
| `frontend/src/components/agent/loop/CollaborationPanel.vue`、`AgentWorkspace.vue`、`api/{http.ts,types.ts}` | 协作面板、轮询恢复、成果和停止操作 |
| `backend/api/tests/test_subagent_collaboration.py` | 并行实例、幂等回执、日志隔离与工具目录回归 |

## V2.7 专家协作 P1 审查修复（2026-09-16）

- `agent_subagents_enabled=false` 同步移除模型可见 `agent.*`，默认助手仍可使用既有工具与普通对话。
- `agent.spawn` 创建事务锁定协作行；整组取消锁存或本回合资源已关闭时，新请求返回 `CONCURRENCY`，不创建实例/运行。已有调用身份先按 V2.6 校验并返回原回执，不因取消破坏幂等。
- P1 协作状态为当前已创建运行的汇总，不等于父回合终态。同一主回合分批调度时，允许的新运行与协作 `running/finished_at=null` 原子提交；有活动运行时保持 `running`。整组取消禁止后续新派发，单个专家取消不锁存整组。
- 主回合正常、取消及异常收尾在运行时 drain 后冻结调用账本并写入最终快照，包含最后一次主模型汇总调用；查询字段保持 V2.6 不变。

### V2.7 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/agent/loop_wiring.py` | 开关白名单与当前回合资源接线 |
| `backend/api/app/agent/collaboration.py` | 行锁取消门禁、分批状态恢复与预算结算 |
| `backend/api/tests/test_loop_wiring.py`、`test_subagent_collaboration.py` | 六项装配、取消、状态、正常/取消预算回归 |

## V2.8 专家交付与评测计划连接契约（拟议，2026-09-16）

对应 PRD V1.30、[专家协作方案 V0.8 §13.7–§13.11](AI测试与评估平台-专家Subagent与多Agent协作技术方案.md)和[基准测试方案 V0.5 §15.5–§15.6](AI测试与评估平台-大模型基准测试方法与榜单建设方案.md)。以下仅冻结设计方向和字段语义，尚未实施；**不新增 REST/WS 路径，不修改现有 `agent.spawn`、`agent.result`、`task.create` 输入/输出 schema 或 `tasks.kind` 枚举**。实施时先补传输绑定、完整 JSON Schema、字段上限、鉴权、迁移与错误用例，再开放调用。

### V2.8.1 共用引用与身份（拟议）

受控制品引用采用 `{kind,id,version,hash}`：`kind` 为登记的制品类型，`id` 为服务端稳定身份，`version` 为明确版本字符串，`hash` 为固定规范化算法计算的内容摘要；不接受 `latest`、任意 URL/服务器路径或纯展示标题。种类、版本和 hash 必须与服务端登记对象一致，不能信任模型自报。正式数据仍沿用 `evaluation_asset_manifest.v1` 的 case/资产/用途身份，引用只是定位包装，不替换其中的稳定任务身份。

制品服务负责实际内容保存、规范化编码和 hash 算法登记；嵌套大清单使用可读取的受控引用，不能只传摘要与条目数。每次解引用复验用户、父会话、材料用途和消费阶段；不存在与不可见统一使用现有 `NOT_FOUND` 语义。未知 schema、缺必需字段、引用版本/hash 不符或不支持能力返回 `VALIDATION`；参数身份冲突使用 `CONCURRENCY`。旧回执可回放但内容读取仍需当前授权，不能用 hash 代替访问控制。

`collaboration_id/run_id` 标识专家准备或分析，`plan_id` 标识评测计划，`task_id` 标识 Worker 业务执行，`report_id + revision` 标识报告修订，必须分别存储关联，不能彼此冒用。身份与验证/审批元数据由服务端注入。

### V2.8.2 expert_deliverable.v1（拟议内部对象）

| 字段 | 类型/语义 |
| --- | --- |
| `schema_id` | 固定字符串 `expert_deliverable.v1` |
| `deliverable_id`、`revision` | 服务端稳定 ID 与正整数修订号；内容修改生成新修订，不覆盖旧正文 |
| `kind` | `benchmark_blueprint / data_manifest_candidate / scoring_policy_draft / report_analysis` |
| `producer` | `{collaboration_id,run_id,expert_id}`，从真实执行身份注入；不能用模型传参冒充其他专家 |
| `scope` | `{evaluation_mode,scenario_ids}`；模式取 `model/rag_system/agent_system`，仅登记已实现适配器的模式才可执行 |
| `based_on_refs` | 上游交付、用户需求制品、已发布资产或报告的精确引用数组；生产前校验允许范围 |
| `content_ref` | 正文受控引用；服务端按 `kind` 对解引用正文进行结构、类型与证据完整性校验 |
| `validation` | 服务端记录 `{status,validator_version,issues}`，status 为 `pending/validated/rejected`；只是交付校验，不代表数据发布、用户批准或入榜 |

正文分型要求：蓝图包含测量目标/模式/场景/能力/指标候选/预算/排除项；候选数据清单包含蓝图引用、来源/许可/用途、条目/来源组、独立验证与覆盖缺口；评分草案包含评分器或 rubric、分档/转换/证据/缺失/复核/校准；报告分析包含固定报告引用、指标与样本引用、结论及不确定性。必须落实对应的严格正文 schema 后才将验证状态设为 `validated`，不能仅凭合法 JSON、专家 `succeeded` 或一句“已完成”通过。

数据专家只产生候选；发布资产由采集侧按其审核策略形成。报告分析只产生解释制品；正式原分、复核分和人工改判保留独立评分记录。专家作者不能自己写服务端验证状态、审核者或批准时间。

### V2.8.3 evaluation_plan.v1（拟议内部对象）

| 字段 | 类型/语义 |
| --- | --- |
| `schema_id` | 固定字符串 `evaluation_plan.v1` |
| `plan_id`、`revision`、`digest` | 服务端稳定 ID、正整数修订、规范化摘要；批准与执行绑定同一三元组 |
| `session_id`、`created_by` | 从当前授权会话和操作者注入；计划/任务关联必须处于同一允许范围，不能通过替换模型参数转移归属 |
| `evaluation_mode`、`suite_ref` | 被测对象模式与冻结套件版本；系统评测不混入纯模型榜 |
| `asset_manifest_ref`、`sample_manifest_ref` | 已发布资产和实际样本身份/顺序/重复安排的制品引用；不能以行号或数量替代稳定样本清单 |
| `target_snapshot_refs` | 授权目标安全配置引用数组，含实际模型/协议/版本及运行参数；不包含密钥，使用用途为 `target` |
| `execution_policy_ref` | 提示、适配器版本、上下文/工具、采样、输出/思考、重试/重复、超时与停止策略 |
| `scoring_policy_ref` | 评分器/rubric、裁判安全配置与 `judge` 用途、原始量纲/转换、证据、校准、复核和无效分处理 |
| `aggregation_policy_ref` | 场景权重、分母、失败/缺失处理、统计方法、业务验收与入榜资格；不得临时重分配缺失权重 |
| `budget_policy_ref` | 分阶段、分资源的额度/soft-hard 模式/可证明上界与停止语义；未知费用明确标记 |
| `lineage_refs` | 已验证专家交付精确版本数组；直接表单创建的合法计划可为空，不能为凑字段伪造专家运行 |
| `approval` | 服务端的批准人、批准时间和批准对象摘要；用户确认后生成，不由模型填写 |

计划 `digest` 覆盖 schema、计划身份/修订及除 `digest/approval` 外全部执行相关内容和精确引用；审批元数据单独审计，避免摘要自引用。规范化算法随 schema 注册，制品正文以被绑定 hash 校验。修改任何被覆盖内容都产生新修订，旧批准不迁移到新版本。

### V2.8.4 确认、提交、取消与报告（拟议行为）

1. 计划服务检查交付、发布资产、执行与评分能力、用途权限及预算配置，生成待确认的不可变版本。用户确认绑定 `plan_id/revision/digest`，沿用既有交互授权与互斥机制；具体传输字段待实现登记，不将这些字段提前塞入现有工具请求。
2. 入队前复验必要条件。计划版本的提交回执、业务任务和关联在同一事务提交，唯一约束防重复确认产生两个任务；会话已有活动任务仍受既有并发限制。计划—任务持久模型/迁移尚未创建。
3. 第一批只编译已实现的文本能力到 `kind=benchmark`；模式、评分、重复或取样未支持时拒绝，不降级为默认行为。目标凭据运行时受控解析，已撤销授权不因计划获批而绕过。
4. 准备协作终止不取消已创建 Worker 任务；取消业务任务使用既有 `task.cancel`。取消锁存与旧回执重放沿用 V2.7，不用旧协作重新派发。
5. Worker 记录执行、评分、统计与报告引用；准备回合不等待任务结束。后续用户回合从固定报告版本启动新的分析协作，刷新只恢复状态；自动后台唤醒不在本契约内。
6. 仅评分规则改变且满足复用条件时，新评分修订可引用原执行输出；目标输入或执行约束改变必须重跑。正式排名还须 B3 的同组条件、完整性与资格门禁。

### V2.8 修改代码文件与作用清单

本次只修改说明文档：本文件登记拟议语义，PRD 登记目标范围，专家协作方案说明调度/隔离/交付，基准方案说明执行/统计/验收。未修改代码、请求 schema、数据库、运行提示词或既有报告口径。

## V2.9 评测准备专家与受控成果（2026-09-16）

本节落实 V2.8 的准备阶段子集：新增 `benchmark-designer`（`benchmark_blueprint`）、`benchmark-data-curator`（`data_manifest_candidate`）、`benchmark-scoring-designer`（`scoring_policy_draft`）。只起草 `evaluation_mode=model` 的文本评测；不发布数据，不批准计划，不执行评分。报告专家、报告版本引用和计划入队仍待 J2/J3。

### V2.9.1 调用与持久化

- 保留六个 `agent.*` 工具。`agent.spawn` 增量可选 `input_refs`（默认 `[]`，最多 4 个，不可重复），每项严格为 `{kind:"expert_deliverable",id,version:"1",hash}`；`id` 长度 1–128，hash 格式 `sha256:` 加 64 位小写十六进制。其余参数仍按 V2.7。普通专家不接受非空引用；数据、评分专家至少需要一份蓝图。
- 只读取**当前父会话**内 `succeeded` 且交付 `validated` 的成果；跨会话或不可见统一 `NOT_FOUND`。派发、实际消费和成果终态落库前复验会话访问、引用种类、版本、摘要与用途。不接受文件路径、URL、数据集、隐藏答案、正式报告引用；这些类型为 `VALIDATION`，不是静默忽略。
- `AgentRunEvent` 内部 `preparation/contract` 事件在创建 run/回执的同一事务写入服务端交付 ID、角色、引用和有效专家提示词快照。事件详情接口不投影快照正文。子运行通过服务器构造的独立用户消息读取完整材料，不读取父/兄弟工作目录。有效专家提示词的 SHA-256 在 `expert.prompt_version` 可见，实际运行使用冻结的同一文本；协议档 overlay 仍遵循现有运行时解析。
- 不新增表或列。每次准备运行最多生成一个独立交付，独立 UUID 存于既有 `AgentRun.result`。本批 `revision=1`；返工生成新运行、新交付 ID，可引用旧成果但不覆盖旧正文。**稳定 ID 下的递增修订链尚未实现**，不对外接受其他版本。
- 主 Agent 从 `agent.result` 取得 `result.reference` 后传入下一位专家。不得自行拼装 hash。只接受阶段为准备、模式为 model 的这三种交付；输入总量最多 64 KiB（规范化 UTF-8），超限明确拒绝，不截断。用户消息中的原始文本不获得“已校验引用”的身份。

### V2.9.2 模型提交与服务端验收

准备专家最终回复必须是单个 JSON 对象 `{scope,body}`，不得带代码围栏或额外字段。输入/输出正文均以 Pydantic 严格 schema 校验（类型不转换，所有对象 `extra=forbid`）；精确 JSON Schema 由 `agent.list` 返回的 `submission_schema` 和子运行的系统约束提供，唯一来源 `agent/preparation.py`。通用限制：文本去除首尾空白后非空、短文本不超过 2,000 字、长文本不超过 8,000 字、列表不超过 32 项（候选最多 100 项），最终回复最多 64 KiB；拒绝重复 JSON 键、非有限数、重复身份和未知字段。

| 对象 | 必需正文与语义校验 |
| --- | --- |
| scope | `evaluation_mode="model"`，`scenario_ids` 为 1–16 个唯一场景 ID（字母/数字/下划线/短横线，1–64 字符）；后续交付场景须被输入蓝图覆盖 |
| blueprint body | `measurement_goal,capabilities,metrics,budget,exclusions,assumptions`；指标包含唯一 `id,description,direction(higher/lower)`；预算包含 `max_samples(1–10000),max_target_calls(1–100000),max_judge_calls(0–100000),cost_limit_usd(非负有限数或null)`；未知成本使用 null，目标调用额度不得小于样本数 |
| data body | `sources,candidates,coverage_gaps`；来源包含唯一 `source_id,uri,license,provenance,intended_use(development/candidate)`；候选包含唯一 `case_id,source_id,group_id,scenario_id,input,evidence_locator,verification_plan`，来源/场景必须能匹配；URI 只记录 http(s) 来源，不自动下载、不证明许可有效；不接受标准答案、已审核或已发布字段 |
| scoring body | `scorer(exact_match/regex/llm_rubric),dimensions,normalization,evidence_requirements,missing_policy(zero/review),review_triggers,calibration_plan`；每个维度 `id,weight,anchors`，权重为 (0,1] 且总和为 1，锚点必须恰好覆盖 `score=0,0.5,1` 及非空 description；这是草案，不能据此声称 Worker 已支持该评分策略 |

`validated` 只表示结构、内部引用和声明的证据定位字段完整；不代表来源真伪、许可审核、答案正确、rubric 已校准、用户批准或入榜合格。主 Agent 不得把该标记解释为事实审核结论。

### V2.9.3 结果投影与错误

旧 `result.content/finish_reason/complete` 保留。准备专家在模型正常结束且结构验收通过时追加：

- `deliverable`：V2.8 `expert_deliverable.v1` 信封；`producer` 和 `based_on_refs` 来自派发快照，`scope` 经过校验，`validation={status:"validated",validator_version:"preparation.v1",issues:[]}`。
- `body`：校验后的正文；`deliverable.content_ref={kind:"expert_deliverable_body",id:deliverable_id,version:"1",hash}`，仅由结果一并读取，不能作为 `input_refs` 类型。
- `reference`：`{kind:"expert_deliverable",id:deliverable_id,version:"1",hash}`。正文 hash 覆盖 body；交付 hash 覆盖 `{deliverable,body}`。算法为 `preparation-json.v1`：Python JSON `sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False` 后编码 UTF-8 再 SHA-256，无时间戳参与。该算法不是跨语言 RFC 8785 声明。

验收失败：run 为 `failed`、`error_code=VALIDATION`、`complete=false`；`result.validation={status:"rejected",validator_version:"preparation.v1",issues:[{path,code}]}`，最多 20 项，不回显异常栈/校验输入；不产生 `reference`。取消/运行失败也不能发布可复用成果。终态写入只执行一次，迟到结果不能改写。

`agent.list` 的准备专家增量返回 `deliverable_kind` 和 `submission_schema`；网页目录仅返回 `deliverable_kind`。已有协作详情与 `agent.result` 投影增量字段；前端显示“结构校验通过（草稿）/交付校验失败”、类型、交付 ID、引用数量和问题路径。页面刷新只读取数据库，不重新派发。

### V2.9 修改代码文件与作用清单

- `agent/experts.py`、`expert_prompts/benchmark_*.md`：三类准备专家与最小工具范围。
- `agent/preparation.py`：严格正文 schema、受控引用、规范摘要、服务端成果验收与交付投影。
- `agent/collaboration.py`、`agent/subagent_tools.py`、`agent/loop_wiring.py`：派发契约、材料投影、冻结专家提示与终态验收。
- `frontend/src/api/types.ts`、`components/agent/loop/CollaborationPanel.vue`：草稿验收状态和可追溯引用展示。
- `backend/api/tests/test_benchmark_preparation.py`：真实持久化与调度链路、越权/篡改/伪造/取消回归；供应商调用使用替身，真实模型试点另行验收。


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


### V2.11 Responses 工具与供应商思考兼容审查（2026-09-17）

Ollama Responses 增加 `ollama-responses-effort-v1` 模板，将统一档位映射到 `reasoning.effort` 的 none/low/medium/high/max。OpenAI Chat 与通用 Responses 模板版本升至 3：早期推理型号最高映射 high，GPT-5.1-Codex-Max 及后续型号/未知兼容端点验证 xhigh 候选，探测对相同参数去重。旧模板版本的探测不能继续授权档位，需要重新验证；REST/WS 字段及事件不变。供应商保存前探测只验证文本/思考能力，不保证实际模型的工具支持。详细范围及官方依据见《协议档供应商思考适配》V1.3。

修改代码文件与作用清单：`backend/shared/reasoning.py` 共用最高档映射；`backend/api/app/llm/providers/{reasoning_templates,options}.py` 提供 Ollama Responses 模板与版本校验；`backend/api/app/responses_adapter.py` 同步映射；`backend/api/tests/test_responses_protocol.py` 覆盖多工具回填、异常禁止调度与 SDK 参数；`frontend/src/components/ProviderLogo.vue` 与 `assets/providers/{newapi,ollama}.svg` 补齐完整供应商图标。


### V2.12 协议档原生工具往返验证（2026-09-17）

`POST /api/profiles/probe-create` 和 `POST /api/profiles/{id}/probe-update` 在思考验证通过且 usages 包含 agent 时，选模板默认的已通过档位（否则首个通过档位）执行最多两次模型调用：请求固定的无副作用探测函数、回填随机结果并要求准确复述。必须有完整调用身份、合法参数、可回放的推理状态和成功终态；文本自称支持工具不算成功。两次请求共用 30 秒上限；文本/思考阶段仍为最多五档并发及 30 秒上限。探测总时限为 55 秒（工具阶段使用剩余时间，另预留资源清理），低于 REST 代理默认的 60 秒；前端探测请求超时调整为 70 秒。

`probe` 增加 `tool_probe: {status: passed|failed|skipped, effort?: string, error_code?: string}`，沿用 reasoning_probe JSON 存储；只存安全状态，不存模型正文、随机值或密钥。未选择 Agent 用途或思考验证失败时为 skipped。工具验证失败不抹去已通过的思考档位，不阻止保存评测用协议档；message 明确警告原生工具未通过，前端用警告反馈。此结果不是运行时授权或全档位能力保证，不修改工具装配开关。

ProfileOut 新增只读 `tool_probe_status: unverified|passed|failed|skipped`，默认 unverified。旧配置和已失效思考验证不能显示工具已通过；更换 API Key 或 anthropic_version 同样使旧探测失效；编辑页显示状态以支持重新验证。工具模式 legacy 也不跳过检测，它并非原生 tools 的运行时禁用开关。

修改代码文件与作用清单：`profile_tool_probe.py` 实现无副作用工具往返；`profile_probe.py` 调度与安全结果；`routers/profiles.py`、`schemas.py` 投影状态和提示；前端 `api/{types,http}.ts`、`components/modals/ProfileModal.vue` 显示结果及超时；相关测试验证真实 SDK 和错误路径。


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


### 添加失败的诊断修复（2026-09-17）

保存前探测的 `attempts[].error_code` 增补安全分类：`AUTH_FAILED`（密钥或权限）、`MODEL_OR_ENDPOINT_UNAVAILABLE`（模型或接口）、`RATE_LIMITED`（限流）、`UPSTREAM_UNAVAILABLE`（上游服务）、`CONNECTION_FAILED`（连接）、`PARAMETERS_REJECTED`（协议或参数）、`INVALID_RESPONSE`（流格式）、`INCOMPLETE_RESPONSE`（未正常结束）。额度不足继续使用 `BUDGET_EXCEEDED`。这些是探测明细分类，不改变 REST 十大错误码；不回显上游错误正文、密钥或提示词。任何验证全部失败的档仍不保存。

修改代码文件与作用清单：`backend/api/app/profile_probe.py` 保留 SDK 已脱敏的具体故障类别；`backend/api/app/routers/profiles.py` 显示可操作的修正提示；`backend/api/tests/test_newapi_reasoning.py` 通过真实 SDK 注入错误状态，核对分类及秘密不外泄。


## 连通检查与 New API Responses 一致性修复（2026-09-17）

列表连接测试沿用实际对话的 build_adapter / resolve_request，不再走旧非流式 call_protocol，不再把输出上限强设为 1，也不丢失保存的思考模板。使用 profile_reasoning 投影的已验证默认档位与实际输出上限；模板未验证或失效时返回 VALIDATION 并要求重新测试。探活等待首个有效正文、思考片段或合法终态，整段上限仍为 30 秒并关闭流及连接池。探活成功只说明本次模型接口可响应，不写回思考档位或工具能力。失败前端显示服务端安全 message，状态文案改为“测试未通过”，避免把参数拒绝、等待超时统称网络断开。

GPT-5.6（含 sol/terra/luna 及快照）的统一最高档发送原生 max；已知旧型号继续 high/xhigh。New API Chat/Responses 模板版本升至 3，OpenAI Chat/通用 Responses 模板升至 4，旧探测结果须重新验证后开放档位，避免使用旧 xhigh 回执宣称 max 已验证。依据：https://developers.openai.com/api/docs/models/gpt-5.6-terra 。

Responses 识别 response.reasoning_text.delta 与已有摘要增量，保留供应商返回的协议状态，不生成或推断隐藏推理。工具调用、加密推理回放与正常结束规则不变。依据：https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_reasoning_text_delta_event.py 。

修改代码文件与作用清单：
- backend/api/app/profile_check.py、routers/profiles.py：复用运行时适配器的单次流式探活与清理。
- backend/shared/reasoning.py、backend/shared/responses.py、backend/api/app/llm/providers/{options,reasoning_templates}.py：原生 max 映射、版本失效与增量识别。
- frontend/src/api/{types,http}.ts、views/AdminProfiles.vue、components/modals/CheckResultModal.vue：保留并展示安全诊断。
- API 探活/Responses 回归测试：真实 SDK 请求、连接清理、档位映射与安全诊断；前端类型检查验证诊断字段贯通。

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


## V2.16 New API Responses 空终态兼容（2026-09-18）

部分兼容网关会按流式事件发送 `response.output_text.done` 或 `response.refusal.done`，却在 `response.completed.response.output` 返回空数组。平台只在完成状态为 `completed`、终态 `output=[]`、没有工具调用、正文恰为一个 `(output_index=0, content_index=0)` 内容块，并且完成正文严格覆盖此前全部增量时，以完成正文重建最小助手消息快照。该快照仅用于文本续聊和持久回放；不生成、推断或保存隐藏推理。

工具调用、多个正文/拒绝块、非空终态、缺少完成正文、完成正文与增量不一致、`incomplete` 终态及工具状态缺失都继续返回响应协议错误。工具能力仍须通过独立的原生工具往返验证，不能因文本兼容而显示为已支持。该限制与 [OpenAI Responses 流式事件契约](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create) 对终态输出和正文完成事件的要求保持一致。

修改代码文件与作用清单：
- `backend/shared/responses.py`：记录并核验正文完成事件；仅在严格限定的单文本空终态下重建助手输出。
- `backend/api/tests/test_responses_protocol.py`：覆盖完成正文重建、缺少完成正文拒绝、工具状态拒绝及 SDK 流式回归。

## V2.17 Responses 终态完整性审查修复（2026-09-18）

空终态补齐前核验流中全部已观察到的输出项与内容块，包括 `output_item.added/done` 和 `content_part.added/done`。额外消息、推理项、工具项或内容块不能被静默丢弃；正文完成事件必须与消息项及内容块的完成快照一致。非空终态同样复核这些证据。重复完成事件只允许相同内容，消息身份或类型漂移、正文完成后的增量均拒绝，不发布成功终态或回放状态。

缺少供应商消息 ID 时，补齐快照不再生成 `responses-fallback-0`。回放阶段将无 ID 的文本消息转为普通助手消息，同时兼容已持久化的旧固定 ID，避免多轮请求携带重复的伪造身份。真实供应商 ID、工具及推理快照保持原样回放；不新增 REST/WS 字段或数据库迁移。

修改代码文件与作用清单：
- `backend/shared/responses.py`：跟踪并校验输出项、内容块和身份；禁止冲突完成事件覆盖；补齐消息不伪造 ID。
- `backend/api/app/llm/providers/responses.py`：无 ID 及旧固定 ID 历史转换为普通助手消息。
- `backend/api/tests/test_responses_protocol.py`：覆盖额外输出、快照冲突、重复完成、身份变化及真实 SDK 连续三轮新旧历史回放。
