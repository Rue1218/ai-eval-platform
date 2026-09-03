# AI 测试与评估平台 — H5 持久化 HITL 收尾演练

| 项 | 内容 |
| :--- | :--- |
| 版本 | V1.0 |
| 审查日期 | 2026-09-03 |
| 适用环境 | Linux + Docker Compose |
| 前置提交 | H5 批次 2 `11f5753` 及本收尾分支变更 |
| 结论 | 配置与路由已具备；真实生产切换、重启恢复和 sandbox 放行仍须 Linux/Docker 证据 |

本文只记录 H5 收尾的可重复操作与验收证据，不把 Windows 本机测试结果当作 Linux/Docker 运行证据。

## 1. 生产配置与启动门禁

在服务器项目目录的 `.env` 中设置以下值；不要把真实数据库密码、API Key 或服务器 `.env` 提交到仓库：

```dotenv
AGENT_CHECKPOINTER=postgres
AGENT_HITL_STRICT_PG=true
HYBRID_ENGINE_ENABLED=true
AGENT_INSTANCE_ID=
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

### 3.1 制造待审批状态

1. 使用两个同一会话成员建立 Agent WS；
2. 在混合引擎 `agent` 路径提交一个会触发危险 bash 审批的请求；
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
