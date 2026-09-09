# AI 测试与评估平台 — AgentLoop 后端实施记录

> 版本：V0.3 ｜ 审查日期：2026-09-09 ｜ 状态：AgentLoop 单入口、协议档选择、重启恢复和共享评测档已完成本地回归；服务器端真实供应商/Linux Runner 联调待验收。

## 0.3 审查修复记录

本版落实审查发现的四项缺口。v2 `attach` 在回放前读取持久开放回合，只有取得已经释放的 PostgreSQL advisory writer lock 后才补写 `turn.end(reason="interrupted")`；锁仍被存活 API 实例持有时只订阅，不转移控制权。恢复完成立即释放临时 writer，下一次 `turn.submit` 仍经正常租约获取路径执行。

每回合请求装配会读取所选 Agent 协议档的补充提示词。核心系统提示词保持首段并可缓存，补充提示词使用动态不可缓存段；读取时再次校验密钥和接管性文本，防止历史脏配置进入模型请求或缓存。`task.create` 对评测档、裁判档沿用平台全员同权目录，`created_by` 仅记录审计来源，不再误作使用权限。

CI 同时向 API 测试传入 `LOOP_TEST_DATABASE_URL`、`LOOP_STORE_TEST_DATABASE_URL`、`LOOP_TOOLS_TEST_DATABASE_URL`，并增加 Ubuntu Runner job。GitHub Hosted Runner 未提供可写 cgroup v2 委派根，因此真实进程树终止用例仍按条件跳过；这不替代服务器 Linux Runner 演练。

## 1. 实施结果与边界

新 Agent 路径独立使用 `deepseek-harness-py` 的七节点循环与源字段语义，覆盖模型多轮调用、工具回填、并行/屏障、重试、审批、取消和恢复。平台原有工具、业务门禁、协议档、Worker 与数据库继续复用。

LLM 调用层对新路径重写为异步三协议适配：OpenAI Chat Completions（含 DeepSeek 配置）、OpenAI Responses、Anthropic Messages。保留必要的供应商内容块、签名/协议状态、usage、finish、reasoning 和图文字段。旧 `llm/gateway.py`、`adapters.py`、`llm_client.py` 的业务调用继续保留；新路径不再经过旧的 react.v1 文本解析、TAOR 或图 interrupt 审批。

WS 为独立 `/ws/agent/v2`，支持严格命令、订阅快照、PG 游标补发、瞬态 chunk 和受限 trace。新旧 endpoint 以不可中途切换的会话 `engine_version` 隔离。浏览器投影与模型事实分离；同一事务提交事实、卡片、UI 消息、投影、隔离记录与命令回执。

回合完整 drain 后释放专用 PG 写者连接，下一轮重新 claim 并读取持久事实，避免闲置会话耗尽连接池。同一控制连接的运行时可以保留会话内持续授权；断连或身份变化清除授权。请求模板切换思考强度同步更新开关和供应商派生字段；真实请求头、消息选择索引与输入指纹一同记录。

前端工作台已统一使用 v2；新会话固定为 agent_loop_v2，历史 legacy 行仍保留审计与显式回放。AGENT_LOOP_ENABLED 已删除；结果未知的执行仍不得因前端状态或回合终态而释放工作区 guard。

## 2. 配置与启用顺序

1. 使用项目 Python 3.12 与 `backend/api/requirements.txt`、`requirements-dev.txt` 锁定依赖。全局旧版 SDK 不能代替项目环境。
2. 在目标部署执行正常 Alembic 流程：从 `backend/api` 运行 `python -m alembic upgrade head`。本次新增迁移为 `8f9a2c4d6e01`，上游 `77586e897dae`；不要手工创建生产表。
3. 为平台设置有效 Agent 协议档，保留现有环境文件凭据加载规则。新建会话自动使用 AgentLoop；输入栏只从 agent-ui 返回的脱敏 profiles 中选择模型和思考档位。
4. v2 客户端复用 REST 短票认证，按 API.md V1.81 连接、订阅和发送 `turn.submit`。每次提交可带 `profile_id` 与 `reasoning_effort`，服务端重新校验；`request_id` 标识命令，`client_message_id` 标识用户输入；同一幂等 ID 不得改正文。
5. 如果使用 bash，API 和 Runner 配置相同的非空 `RUNNER_INTERNAL_TOKEN`，保持内部网络隔离；Runner 还需 Linux cgroup v2 的专用可写委派根 `RUNNER_CGROUP_ROOT`。目录在容器内必须位于 `/sys/fs/cgroup` 下，并有可创建子组和读取/写入必要控制文件的权限。

当前 compose 只接入变量，没有自动替宿主机建立 cgroup 委派。推荐为 Runner 分配专用 systemd 委派子树，仅将该子树挂入容器，并在实际 Docker/cgroup namespace 配置下验证创建子组、进程迁入、`cgroup.kill` 与 `cgroup.events populated=0`。不要将整个宿主 cgroup 树可写暴露给 Runner 或沙箱。缺少可信委派时新 bash 返回失败，不降级到裸 subprocess。

主要参数：`AGENT_LOOP_MAX_STEPS=16`、`AGENT_LOOP_MODEL_MAX_RETRIES=2`、`AGENT_LOOP_MODEL_RETRY_DELAY_SECONDS=0.25`、`AGENT_LOOP_MAX_PARALLEL_TOOL_CALLS=4`、`AGENT_LOOP_APPROVAL_TIMEOUT_SECONDS=300`。直接进程可经环境变量配置；Compose 不再映射 AgentLoop 启用开关。

## 3. 本地验证记录

本轮使用独立 PostgreSQL 实例 `127.0.0.1:55439/looptest`，与平台实际数据库隔离。迁移从旧模型基线自动生成并在该库执行。PG 测试通过显式 `LOOP_TEST_DATABASE_URL`、`LOOP_TOOLS_TEST_DATABASE_URL`、`LOOP_STORE_TEST_DATABASE_URL` 指向测试库；没有这些变量时相关测试会跳过，不能据此声称验证了 PG。

| 验证项 | 最终结果与边界 |
| :--- | :--- |
| API 全量，Python 3.12.13 + 项目锁定依赖，三个 PG 变量均设置 | **1273 passed / 23 skipped / 0 failed**；跳过的条件用例不计为通过 |
| Runner 全量，同一解释器 | **47 passed / 2 skipped**；Windows 无法执行 Linux 条件用例 |
| Worker 全量，同一解释器，`PYTHONPATH=.;..` | **50 passed** |
| API/Runner/shared Ruff、改动 Python 编译、`git diff --check` | 通过 |
| 前端 `npm run typecheck`、`npm run build` | 通过；构建仍有既有大 chunk 提示；前端代码未变 |
| Alembic 增量 | 隔离 PG 已执行 `77586e897dae`；限定本次五个表的 `alembic check` 无新升级操作 |
| 原生文件闭环 | 可控模型驱动真实 Runtime、ToolBridge、临时文件和 PG；覆盖读→审批修改→再读→回答、第二轮、重复提交和回放 |
| 协议/取消/恢复 | 真实 SDK 解码本地协议响应；覆盖 reasoning/工具参数/供应商状态、取消前缀、停止证据、恢复补偿与事务故障 |

本轮修复了回归发现的闲置会话占用 PG 连接、模板切换思考档位不同步、Windows 3.12 协议档保存、测试依赖遗漏及取消用例时限过短等问题。最终全量结果来自修复后的同一次运行，未将先前分组测试数量累加。新增 `jsonschema==4.26.0` 仅为事件 catalog 的开发测试依赖，不加入生产镜像。

可复验命令（PowerShell，在 `backend/api`；URL 指向已隔离、已迁移的测试库）：

```powershell
$env:LOOP_TEST_DATABASE_URL='postgresql://looptest@127.0.0.1:55439/looptest'
$env:LOOP_TOOLS_TEST_DATABASE_URL=$env:LOOP_TEST_DATABASE_URL
$env:LOOP_STORE_TEST_DATABASE_URL=$env:LOOP_TEST_DATABASE_URL
python -m pytest -q --disable-warnings --tb=short
python -m ruff check . ../shared
```

完整场景定位：`test_loop_integration_pg.py` 使用可控模型、真实 Runtime/PG/ToolBridge/文件和 WS handler；`test_loop_llm_sdk.py` 使用真实 SDK 解码本地伪造协议响应。这两者均不表示已向真实供应商发送请求。`test_loop_store_recovery.py` 包含数据库写者连接失效、事务回滚和事实重建；Runner 测试的 Linux 条件用例不能由 Windows mock 取代。

## 4. 上线前验收与组件处置

| 项目 | 本轮处理 / 后续验收 |
| :--- | :--- |
| 原七节点、调度、消息、恢复 | 已迁入代码并增加回归；功能基线为源工作区当前实现 |
| 平台工具和业务中间层 | 保留 ToolRegistry、Native/MCP、配额/ACL、工作区、task prepare/enqueue、Worker |
| 旧网关、模型发现、评测适配器 | 保留：仍有既有业务调用，不因 Agent 路径重写而整体删除 |
| 旧 TAOR、react.v1、Workflow 图恢复 | 新路径不装配；旧引擎仍可使用，未无依据删掉共享代码 |
| 源 CLI、独立静态页面、JSONL 生产写入、全套源工具 | 不迁入；生产持久化语义由 PG 实现 |
| 源尚未实现的 steer/反思/自动续写 | 不新增，不作为迁移遗漏 |
| 真实模型与评测 | 仍需三协议实际凭据驱动工具闭环、图文/签名/cache，以及真实 Worker 评测报告验收 |
| Linux Runner | 仍需容器/bwrap/cgroup 的进程树取消、失联后持续写入、跨重启隔离和可信对账演练 |
| 前端 v2 | 已接入单入口会话、协议档菜单、思考控制和重连快照；真实供应商、Linux Runner、权限撤回和隔离故障仍待服务器证据 |
| 多 API 副本 | PG 写者排他不等于运行中任务自动接力；上线仍需验证会话路由、实例故障与恢复策略 |

未知执行的 guard 必须保留，只有绑定原实例代次和请求指纹的可信终止证据才可对账释放；API 进程异常留下的本地/旧执行 guard 暂无面向用户的手动解锁 API，运维需先证明实际进程已停止，不能直接清表放行。

## 5. 修改代码文件与作用清单

详见 [架构设计 §16.3](AI测试与评估平台-AgentLoop后端架构设计.md#163-修改代码文件与作用清单)。本次同步 API、数据库、Agent 开发、Harness 契约/记忆/执行/安全文档，并改造前端输入栏、模型菜单和思考控制。

V0.3 新增：`backend/api/app/agent/loop_service.py` 与 `routers/ws_v2.py` 固化安全重连恢复语义；`loop_wiring.py` 接入协议档专属 overlay；`task_tools.py` 对齐共享协议档权限；`test_loop_wiring.py`、`test_loop_integration_pg.py`、`test_loop_tools_task_prepare.py` 与 `frontend/tests/agentLoop.test.mjs` 添加回归；`.github/workflows/ci.yml` 覆盖三组 PostgreSQL Loop 测试和 Runner job。无数据库迁移、REST 字段或 WS 命令字段变化。

回归中额外修复 `backend/api/app/profile_env.py` 在 Windows Python 3.12 缺少 `os.fchmod` 时无法保存模型协议档的问题：仅在该能力存在时使用，保留文件创建权限及路径 chmod。`test_profile_env.py` 增加缺少该 API 的回归。`test_harness_execution.py` 的既有公网工具测试固定 DNS 桩，与已固定的 HTTP 响应配套；未改生产 SSRF 校验。`test_loop_rollout.py` 验证新会话固定 AgentLoop、创建/列表引擎字段和旧 WS 不会隐式创建会话。

`backend/api/requirements-dev.txt` 新增 schema 校验测试依赖。临时 PG 仅用于本轮验证，结束后停止；复验前需另行准备隔离测试库，不能把业务库填入测试变量。

## 6. 源工作区核对指纹

源 HEAD 为 `2b5eed88cee71a45d039ca81e6f5b9a649d09806`，迁入基线包含其已有未提交修改；2026-09-09 记录以下实际文件 SHA-256，定位本次核心实现版本。工具实现继续取自平台，源工具目录不整体复制。

| 源路径 | SHA-256 |
| :--- | :--- |
| `app/agent/graph.py` | `37978328FDCF26F1DC0A19855F8F9A0F08789830322E926D630B2E5C2F20E7D5` |
| `app/agent/runtime.py` | `BA80C2EE95B500D662107A5C5CC6CA6CD2F59AAF05AF19250BBBB4DC540B774A` |
| `app/agent/tool_calls.py` | `1B24926B7273FD0409A4ACC2028BDCD932F54A3D930D0331733EAAB3307A6CDC` |
| `app/agent/stream.py` | `066E9D6AADD2C2A1DCA5BF06B838A83C54C169706CA3E646C69E7B934560EB5D` |
| `app/llm/base.py` | `28E76130408C3560E3922741947B8001334941C9202C9C2E8C1E722FA011E47E` |
| `app/llm/openai_adapter.py` | `EE35DF45691CDBDB6E6277A8EBF2BD0197442285608C06D507E01C250C636D6B` |
| `app/llm/anthropic_adapter.py` | `AF53C8F9B5A264787CE205A3FD502EDFE90653DB58593DDFD4875A711FB4E9BE` |
| `app/session/messages.py` | `13F37B34CF96F1BD9CE41A0E8F696CABAF82D45A4FA8038158EE7B0C153D6544` |
| `app/session/recovery.py` | `DF73A8509FBE0BEF51975D6289AF63B65DD4522390E270A097BA6E4211F800DE` |
