# 混合驱动引擎 H0–H3 预发启用与 Smoke 清单

> 配套文档：`AI测试与评估平台-混合驱动引擎架构.md`（V1.4）、`AI测试与评估平台-混合驱动引擎开发计划.md`（V1.3，§5 阶段发布与回滚）、`AI测试与评估平台-API.md`（V1.68）。
> 自动化联调基线：`backend/api/tests/test_hybrid_e2e_h0_h3.py`（9 例，PR #206 合入，main `a1c63f0`）。
> 适用环境：预发（staging）/测试环境；生产放量前须完成本清单并保留观测证据。

---

## 1. 目标与范围

在预发环境启用 `hybrid_engine_enabled=true`，以浏览器端真实交互验证 H0–H3 已合入能力（PR #202/#203/#204/#206）：

- H1 Router 四路分流（direct / chat / workflow / agent）与 `engine` 审计；
- H2 Workflow W0–W7 确定性 DAG + WS 直连确认卡（发卡 → 回执 → **W6 唯一入队**）；
- H3 Agent TAOR 单图内循环（plan → discover → orchestrator⇄tools）+ ToolCard；
- 红线守卫：`worker.sandbox` 不可 discover、`skill-rag`/直接压测 fail-closed、越权工具 VALIDATION、Observation 不进事件。

Windows 本机（无 Docker/PG）无法执行浏览器 smoke，自动化面已由 `test_hybrid_e2e_h0_h3.py` 覆盖；本清单为真实环境执行面。

## 2. 前置条件

| # | 条件 | 检查方式 |
| :-- | :--- | :--- |
| P1 | main 已合入 #202/#203/#204/#206，镜像/版本 ≥ 对应 commit | 部署产物 commit |
| P2 | PG 可连接；`api` 启动日志无 Agent Registry fail-fast（`agent_registry_strict` 默认 true，allowed_tools 未注册会阻止启动） | `docker compose logs api` |
| P3 | Agent 协议档已配置（`agent_profile_id` 设置 + 协议档 base_url/model/Key），`/api/agents` 可列出 4 个 Worker | `GET /api/agents` |
| P4 | 测试会话/账号可登录，数据集与协议档各 ≥1 条（确认卡补槽用） | 管理端 |
| P5 | `AGENT_CHECKPOINTER=memory`（H5 前保持；postgres 检查点未评审不开） | api env |

## 3. 预发开关清单

配置项均定义于 `backend/api/app/config.py`（`Settings`，`.env`/环境变量覆盖，无前缀、字段名即变量名）。**全部默认安全关闭**；预发只开主开关与可选 L1 CoT，其余保持默认。

| 环境变量 | 默认 | 预发建议 | 说明 |
| :--- | :--- | :--- | :--- |
| `HYBRID_ENGINE_ENABLED` | `false` | **`true`** | 主开关；关闭即完整回退骨架化纯对话（灰度回滚出口，见 §7） |
| `HYBRID_ROUTER_COT_ENABLED` | `false` | `true`（可选，先 false 验证纯 L0 再开） | Router L1 CoT；false 时纯 L0 确定性分流（零模型、可复现） |
| `HYBRID_ROUTER_CONFIDENCE_THRESHOLD` | `0.7` | 保持 | L0 置信度低于此值才触发 L1 |
| `AGENT_REGISTRY_STRICT` | `true` | 保持 | AgentDef 引用未注册工具时启动 fail-fast |
| `PROMPT_CACHE_ENABLED` | `false` | 保持 false（H0 缓存边界未灰度） | 提示词分段缓存；false 时字节级兼容 |
| `AGENT_CHECKPOINTER` | `memory` | 保持 `memory` | H5 前禁 postgres |

**注入点（部署侧）**：`docker-compose.yml` 的 `api` 服务 `environment:` 目前**未透传** `HYBRID_*` / `PROMPT_CACHE_ENABLED`（现有 `AGENT_CHECKPOINTER`/`AGENT_NATIVE_STREAM_ENABLED` 已透传）。启用步骤：

1. 在 api 服务 `environment:` 追加：
   ```yaml
   HYBRID_ENGINE_ENABLED: ${HYBRID_ENGINE_ENABLED:-false}
   HYBRID_ROUTER_COT_ENABLED: ${HYBRID_ROUTER_COT_ENABLED:-false}
   HYBRID_ROUTER_CONFIDENCE_THRESHOLD: ${HYBRID_ROUTER_CONFIDENCE_THRESHOLD:-0.7}
   ```
2. 宿主 `.env` 或部署编排注入 `HYBRID_ENGINE_ENABLED=true`；
3. 仅需重启 `api` 服务（无数据库迁移、无 schema 变更、worker 无需重启——确认卡入队后由既有 Worker 消费）。

**前端**：无开关。ToolCard/ConfirmCard/引擎审计渲染按事件自适应（V1.67/V1.68 契约），旧客户端忽略未知字段。

## 4. 启用后验证（健康检查）

| 步骤 | 操作 | 预期 |
| :--- | :--- | :--- |
| S1 | `docker compose up -d api`；观察启动日志 | 无 fail-fast；无 Registry 校验告警 |
| S2 | `GET /api/agents` | 4 个 Worker（general/diagnose/dataset/sandbox 只读目录） |
| S3 | 打开 Agent 页，新会话发普通问答 | 纯对话正常（引擎开关不影响 chat 字节级行为） |
| S4 | `ws_events` 表中查看 `response.completed` | 开关开启后含 `engine` / `router_confidence` / `router_reason` 三审计字段 |

## 5. Smoke 用例清单（浏览器端）

对照自动化用例见 `test_hybrid_e2e_h0_h3.py`。每例记录：日期/执行人/结果（PASS/FAIL/备注）。

| # | 场景 | 操作 | 预期结果 | 对照自动化 |
| :-- | :--- | :--- | :--- | :--- |
| U1 | H0 纯对话回归 | 新会话发送“什么是 pass@1？” | 流式气泡正常；无工具卡/确认卡；回合完成态正常 | `test_h0_chat_full_ws_pipeline_without_engine`（负向：无 engine 字段需开关关闭环境；预发开态下查 completed 带 `engine=chat`） |
| U2 | H1 direct | 发送 `/help` | 气泡“暂不支持该命令…”，回合结束；无模型调用 | `test_h1_direct_slash_engine_audit` |
| U3 | H2 发卡 | 发送“对数据集 D 用 profile-A 跑一次基准评测” | 叙述“任务单已生成（请补齐必填项后确认）”+ ConfirmCard（kind=基准评测、默认值预填、缺失提示“被测协议档”）+ 回合完成；**任务列表无新任务** | `test_h2_workflow_issues_confirm_card` |
| U4 | H2 确认入队 | 在 ConfirmCard 补齐协议档/数据集 → “确认并运行” | 卡收回；任务进度坞出现 queued 任务；完成后进度 100%；可打开报告 | `test_h2_confirm_replay_enqueues_once_via_w6` |
| U5 | H2 取消确认 | 同 U3 后点“取消” | 卡收回；**无新任务** | `test_confirm_h2_direct`（reject 不入队） |
| U6 | H2 卡占会话 | U3 的卡未处理时，再发一条评测请求 | 服务端 error“会话存在待确认任务，请先确认或取消”；原卡不被覆盖 | `test_ws_confirm_h2`（发卡失败降级 error） |
| U7 | H2 歧义澄清 | 发送“先跑基准评测再发起压测” | 澄清气泡（“检测到多个评测意图…请明确”），回合结束；用户回复单个意图后正常走流程 | W0 clarify 用例（`test_hybrid_h2_workflow`） |
| U8 | H2 门禁 fail-closed | 发送“发起一次压测” | error“压测任务须由质量评测成功派生（先评后压）”；发送 rag 相关请求 → “知识库评测（RAG）未接入” | `test_dag_rag_and_direct_stress_fail_closed` |
| U9 | H3 TAOR 工具回合 | 发送“排查一下 <某报告/数据集> 失败原因”（需 read 沙箱已接线；未接线时见 §6 遗留 L1） | plan 后出现 ToolCard（read 执行 → 结果状态），最终正文回答 | `test_h3_agent_taor_plan_discover_done`、`test_h3_agent_read_observation_failure_then_done` |
| U10 | H3 越权防御 | 后台观测：模型请求视野外工具（bash 等） | error“非法工具调用…（不在本轮视野内）”，回合不崩溃、无工具执行 | `test_h3_agent_out_of_view_tool_fail_closed` |
| U11 | 跨引擎连续多轮 | 同一会话依次：概念问答 → 评测（发卡确认）→ 排查 | 每轮 completed 的 `engine` 依次 chat / workflow / agent；确认卡与工具卡正确呈现 | `test_multi_turn_engine_switching_on_one_session` |
| U12 | 刷新与回放 | U11 完成后刷新页面并重开会话历史 | 消息完整；旧事件（V1.63 前形态）不渲染；本会话新产生的 confirm/tool 事件按新契约渲染或合理折叠 | API.md §4.3 回放规则 |

## 6. 已知遗留（执行前知悉）

| # | 事项 | 影响 | 状态 |
| :-- | :--- | :--- | :--- |
| L1 | `ws._run_turn` 未注入工具沙箱（`configurable["sandbox"]`）——H3 Agent 在真实 WS 回合的 `read`/`write` 等文件工具会失败（十层链拒绝并回灌失败观察，回合不崩溃） | U9 的 read 成功路径不可达 | 联调发现（PR #206 已固化该行为）；待用户文件沙箱体系接线修复 |
| L2 | ConfirmCard 表单补齐必填资产依赖管理端预置 profile/dataset；W1 槽位抽取（LLM）未落地 | 用户需在卡上/管理端补槽 | 规划中 |
| L3 | `thought`/`tool_progress`/`tool_output_delta` 无生产者（H3 范围外） | ToolCard 无中间流式进度 | 设计如此 |
| L4 | 生产放量前须完成 §5 全用例 + O2 采样 ≥ 建议量（开发计划 §2.2 H6 后决策） | 放量判据 | 待预发执行 |

## 7. 回滚与判据

- **即时回滚**：置 `HYBRID_ENGINE_ENABLED=false` → 重启 api → 恢复骨架化纯对话（字节级兼容，无数据迁移）。已入队任务不受开关影响，由 Worker 正常消费。
- **回滚触发**（任一）：U1/U2 回归失败；U3–U12 出现服务端异常（回合 INTERNAL、事件缺失、completed 缺失）；错误率/延迟异常（对比开关前基线）；确认卡链路出现重复入队或绕过 W6 的痕迹。
- **放量判据**：§5 全用例 PASS ≥ 2 轮（不同账号/数据集）、无 §7 触发项、O2 采样记录完整后，再按开发计划 §5（H2–H4 先在测试/预发启用 → 选择内部协议档灰度）推进生产灰度。

## 8. 执行记录

| 日期 | 环境 | 执行人 | 结果 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| （待执行） | 预发 | | | |
