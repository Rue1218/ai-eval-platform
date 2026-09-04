# AI 测试与评估平台 — H5 持久化 HITL 收尾演练

| 项 | 内容 |
| :--- | :--- |
| 版本 | V1.1 |
| 审查日期 | 2026-09-04 |
| 适用环境 | Linux + Docker Compose |
| 前置提交 | H5 批次 2 `11f5753` + 演练开关（`agent_drill_sandbox_enabled`）合入 |
| 结论 | 重启恢复演练已执行（2026-09-04，见 §6）；多副本粘性演练与 sandbox 命令执行链接线（会话工作区注入）仍待完成后才能评审放行 |

本文只记录 H5 收尾的可重复操作与验收证据，不把 Windows 本机测试结果当作 Linux/Docker 运行证据。

## 1. 生产配置与启动门禁

在服务器项目目录的 `.env` 中设置以下值；不要把真实数据库密码、API Key 或服务器 `.env` 提交到仓库：

```dotenv
AGENT_CHECKPOINTER=postgres
AGENT_HITL_STRICT_PG=true
HYBRID_ENGINE_ENABLED=true
AGENT_INSTANCE_ID=
# 仅本演练环境（制造审批卡）置 true；演练结束置回 false 并重启
AGENT_DRILL_SANDBOX_ENABLED=true
```

Compose 会把这些值显式注入 API。`deploy/deploy.sh` 在构建前检查：混合引擎开启时必须同时满足 PostgreSQL 检查点和严格启动门禁；否则部署立即失败。API 启动时仍会再次执行同一门禁。

部署后检查迁移和实例标识：

```bash
docker compose exec -T api alembic current
docker compose exec -T api alembic upgrade head
curl -fsS http://127.0.0.1/api/health
```

健康检查结果必须包含非空 `instance_id`。迁移版本必须包含 `harness_checkpoints`、`harness_checkpoint_writes` 及 `metadata_type` 列。

## 2. 网关粘性路由

前端 Nginx 的 `/ws/` 使用 `session_id` 一致性哈希，`api` 使用 Docker DNS 动态解析；REST `/api/` 使用同一动态 upstream 但不绑定会话。多副本演练使用：

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose-h5-multi-api.yml \
  up -d --build --scale api=2
```

在同一个会话中记录：

1. 两次 `/api/health` 返回的 `instance_id` 集合；
2. Agent WS 建连、产生 `tool_approval` 后断开重连时的 `session_id` 与 `last_event_id`；
3. 两次健康检查和 WS 重连期间，审批卡仍只有一张，且没有第二次 `tool_call`。

若 API 副本扩容时仍需从宿主机直连 `:8000`，不要使用该覆盖文件；它会移除 API 的宿主机端口，统一通过 web 的 80 端口进入，避免副本端口冲突。

## 3. Linux/Docker 重启恢复演练

> **演练开关（必须先合入并理解）**：生产注册表把 `worker.sandbox` 从 discover
> 静态排除（`backend/api/app/harness/orchestration/agents.py`，fail-closed），
> 因此正常生产下模型**永远无法**触发危险 bash 审批。为制造待审批状态，本演练
> 需在演练环境把 `AGENT_DRILL_SANDBOX_ENABLED=true` 写入 `.env` 并重启 api——
> 该开关默认 `false`（config.py / .env.example），只放行 discover 选中
> `worker.sandbox`，**不等于** sandbox 放行评审结论；演练结束必须置回
> `false` 并重启。双闸结构：即使开关打开，intent 词表（
> `taor_nodes._capabilities_from_intent` 的「运行脚本 / 执行命令 / 跑脚本 /
> 运行代码 / 执行 bash」触发词）命中的 `run_script` 能力请求才会选中
> sandbox；混合能力请求仍保守回落 `worker.general`。

### 3.1 制造待审批状态

1. 使用两个同一会话成员建立 Agent WS；
2. 在混合引擎 `agent` 路径提交一个**含 code 触发词**的请求（如「排查一下
   测试环境异常，然后运行脚本定位问题」——含「运行脚本」触发 `run_script`
   能力，演练开关打开后 discover 选中 `worker.sandbox`）；
3. 确认已收到持久化 `tool_approval`，记录 `session_id`、审批卡 `id` 和当前 `last_event_id`；
4. 在 API 重启前确认 runner 没有执行该命令：

```bash
docker compose logs --since 2m runner
```

### 3.2 重启 API 并恢复

```bash
docker compose restart api
until curl -fsS http://127.0.0.1/api/health >/dev/null; do sleep 2; done
docker compose logs --since 2m api
```

API 恢复后，用原会话和原审批卡提交一次 `tool_approval_ack`：

```json
{"id":"<approval-id>","action":"approve"}
```

服务端从 PostgreSQL 的 `pending_confirm.meta.thread_id` 恢复原图回合；客户端不自行生成或修改 `thread_id`。随后检查：

- 原审批卡被清除，恢复只发生一次；
- runner 只出现一次对应执行；
- WS 按 `last_event_id` 补发时不重复插入或重放 `pending_events`；
- 同一审批卡再次 ack 返回统一 `VALIDATION` 或并发错误，且不再次执行命令；
- 非命令原发起成员 ack 被拒绝，审批卡和 runner 状态不变。

### 3.3 证据记录

每次演练至少保存以下脱敏证据：

| 证据 | 要求 |
| :--- | :--- |
| Compose 配置 | `docker compose config` 中 API 为 `postgres/strict`，runner 仅在 `sandbox_net` |
| 数据库迁移 | `alembic current` 与 `metadata_type` 存在性 |
| 副本标识 | `/api/health` 的两个不同 `instance_id` |
| 中断恢复 | 重启前后的 `session_id`、审批 `id`、事件游标和最终 `response.completed` |
| 幂等性 | 重复 ack、并发 ack、非 owner ack 的错误码与 runner 日志 |

日志和导出结果中不得包含密码、API Key、Cookie、完整提示词、命令参数或工作区文件内容。

## 4. `worker.sandbox` 安全评审

当前结论为“受控基础设施已加固，尚未批准从 `discover.excluded` 放行”：
`AGENT_DRILL_SANDBOX_ENABLED`（默认 `false`）只允许演练环境临时选中
`worker.sandbox` 制造审批卡，**演练结束必须置回 `false`**——置回前不得把
本演练证据当作生产放行结论：

- `worker.sandbox` 继续静态排除，Agent 不可发现选择；
- runner 无宿主机端口，只加入 Compose 的 `internal: true` `sandbox_net`，API 是唯一业务侧调用方；
- API 与 runner 均执行命令阻断和工作区校验，执行体使用 bubblewrap 的用户、PID、网络、IPC、UTS 隔离及只读系统绑定；
- runner 仍使用 `privileged`、`SYS_ADMIN` 和 `seccomp:unconfined`，这是当前 bwrap 运行前提，也是必须在 Linux 上实测和复核的高风险项；
- 未完成 Linux/Docker 重启恢复、扩容粘性验证和权限边界评审前，不得删除 `discover.excluded`，不得把 `bash` 加入生产 Agent 能力白名单。

## 5. 修改代码文件与作用清单

| 文件 | 作用 |
| :--- | :--- |
| `docker-compose.yml` | 注入 H5 配置、连接 API 与 runner 专用内网、隔离 runner 默认业务网 |
| `deploy/deploy.sh` | 部署前校验混合引擎必须使用 PostgreSQL/严格门禁及 runner 网络隔离 |
| `deploy/docker-compose-h5-multi-api.yml` | 提供 Linux/Docker 多 API 副本演练覆盖 |
| `frontend/nginx.conf` | 按 `session_id` 对 WS 做一致性哈希并动态解析 API 副本 |
| `frontend/Dockerfile` | 固定支持 `resolve` upstream 的 Nginx 版本 |
| `backend/api/tests/test_h5_deployment_contract.py` | 覆盖 Compose、Nginx 与多副本覆盖文件的静态契约 |
| `docs/AI测试与评估平台-混合驱动引擎开发计划.md` | 更新 H5 收尾状态与实现记录 |
| `docs/AI测试与评估平台-Agent开发文档.md` | 更新检查点、网关与 sandbox 状态 |
| `docs/AI测试与评估平台-API.md` | 同步 H5 V1.70 的生产前提与当前实现状态 |
| `backend/api/app/harness/memory/checkpoint.py` | PgCheckpointer.put_writes 幂等 upsert（演练发现修复，#217） |

## 6. 演练执行记录（V1.1）

### 2026-09-04 · Linux/Docker 重启恢复演练（47.119.132.83，main `fbe3e1d`）

**通过项**

| # | 步骤 | 结果 |
| :-- | :--- | :--- |
| 1 | H5 生产配置全开（postgres + strict + hybrid + drill）启动 | 启动门禁通过，无 fail-fast；`/api/health` 返回非空 `instance_id` |
| 2 | 制造待审批状态（§3.1） | `AGENT_DRILL_SANDBOX_ENABLED=true` 时 discover 选中 `worker.sandbox`；真实图（PG 检查点）中 orchestrator Act `bash touch /tmp/...` → `tool_approval` interrupt（id/call_id/command 完整）落检查点 |
| 3 | API 重启（容器重启，跨进程） | runner 日志确认命令未执行；重启后健康 |
| 4 | 恢复执行（§3.2） | 新进程按原 `thread_id` 从 PG 检查点 `Command(resume={action:approve})` → `tool_result` 仅 1 次（不重放中断前事件）→ `response.completed` 收尾 |
| 5 | 重复 resume 幂等 | 同一 thread 再次 resume → 零事件零执行（resume 至多一次） |

**发现与修复**

| # | 发现 | 处置 |
| :-- | :--- | :--- |
| 1 | `PgCheckpointer.put_writes` 无 upsert：跨进程恢复回合重复写入唯一键冲突 `UniqueViolation`（断线重试/重复 resume 不可安全重放；InMemory 路径不暴露） | 已修复：`ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) DO UPDATE` 幂等覆盖（PR #217，合入 `fbe3e1d`） |
| 2 | 审批放行后 bash 在 runner 层仍被 fail-closed 拒绝：`sandbox_dir` 非合法会话工作区（图级/ws 回合均未注入会话工作区） | 会话工作区接线已完成（PR #219：ws 回合注入 `configurable["sandbox"]["dir"]` 与 `assets.file_ids`）并经 **二次演练闭环通过（2026-09-04）**：注入会话工作区后 bash 审批 → resume approve → runner bwrap 真实执行成功（`tool_result ok:true`、文件落盘工作区）。演练后 `AGENT_DRILL_SANDBOX_ENABLED` 已置回 `false` |

**收尾确认**：`AGENT_DRILL_SANDBOX_ENABLED` 已置回 `false` 并重启验证（容器内 `false`）；演练会话、检查点与工作区数据已清理。

### 2026-09-04（补）· P0 二次演练（sandbox 真实执行闭环，main `6e90e38`）

| # | 步骤 | 结果 |
| :-- | :--- | :--- |
| 1 | 会话工作区注入（PR #219 后） | 图级回合 `configurable["sandbox"]["dir"]` = 会话工作区（runner 同卷可访问） |
| 2 | 制造审批卡 | discover 选中 `worker.sandbox`；`bash "touch p0-flag.txt && echo P0-OK"` → `tool_approval` interrupt（sandbox_scope 随卡） |
| 3 | resume approve（裸 dict，与 ws.py 同构） | 校验通过 → **runner bwrap 沙箱真实执行**：`tool_result {ok:true, stdout:"P0-OK", exit_code:0, source:"sandbox:bash"}`，`p0-flag.txt` 落盘工作区 |
| 4 | 收尾 | drill 开关置回 `false`；演练检查点/工作区已清理 |

> 注：演练过程同时确认 LangGraph resume 传参契约——恢复值须以 `resume=<裸 dict>`（或经 ws.py 现有封装）传入，包装成 `Command` 对象直接传入会因节点输入类型不符而失败；H5 恢复协议以 ws.py 实现为唯一事实源。

**未完成（阻断发布项保留）**：多副本粘性路由演练（§2，`scale api=2`）、runner bwrap 权限边界复核（§4 高风险项）；bash 真实执行已闭环，但**生产放行 worker.sandbox 仍需完成上述两项后的正式权限边界评审**。
