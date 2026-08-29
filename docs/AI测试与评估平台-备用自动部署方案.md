# AI 测试与评估平台 — 备用自动部署方案（GitHub Actions 用量受限回退链路）

> **文档地位**：本文件是平台部署链路的配套技术方案，规定 GitHub Actions CD 因用量上限停摆时，
> 生产环境 `47.119.132.83` 的备用自动化部署机制。与 [`AI测试与评估平台-API.md`](AI测试与评估平台-API.md) 无契约交集。
> 版本：V1.0 ｜ 审查日期：2026-08-29

---

## 1. 背景与目标

- **主链路**：推送 `main` → GitHub Actions CI → CD 构建变化服务的 GHCR 镜像 → `appleboy/ssh-action` 登录服务器 → 执行 `deploy/deploy.sh` 拉取镜像、平滑滚动更新。
- **故障场景**：GitHub 组织/账号触发 **Actions 用量上限**（免费额度分钟数耗尽或计费额度封顶）后，工作流不再运行——代码合入 `main` 后生产不再更新，且无告警。
- **目标**：提供一条**不依赖 GitHub Actions** 的自动化部署备用链路，一键启用、一键回切，且与主链路共用同一套部署脚本与安全边界（生产只跟 `main`）。

## 2. 方案选型

| 候选方案 | 结论 | 理由 |
| :--- | :--- | :--- |
| **服务器侧轮询 origin/main（本方案）** | ✅ 采用 | Actions 用量上限不影响 `git fetch`；无需在服务器新开公网入口；无需新增任何密钥；复用 `deploy/deploy.sh` 既有互斥锁与本地构建回退路径 |
| GitHub Webhook → 服务器部署接口 | ❌ 不采用 | 需在公网新开 HTTP 端点并管理签名密钥，扩大攻击面；与「单一研发团队内部平台」定位不符 |
| 本地手动 SSH 触发 | ⚠️ 仅作兜底 | 不满足"自动化"要求；保留为应急手段（与现有手动部署方式一致） |

## 3. 架构与流程

```text
GitHub main（新提交）
        │ git fetch（SSH 部署密钥，不受 Actions 用量影响）
        ▼
宝塔面板「计划任务」（每 5 分钟）
  └─ deploy/auto-deploy-watch.sh
       │ ① 读 .deploy-mode 开关（actions=仅巡检 / local=备用部署）
       │ ② 对比 HEAD 与 origin/main
       │ ③ mode=local 且有新提交 → DEPLOY_COMMIT=<sha> bash deploy/deploy.sh
       │      └─ deploy.sh 未传 IMAGE_* → 服务器本地构建（差异构建 + 平滑滚动 + 互斥锁）
       │ ④ 健康检查：GET /api/health + GET /（重试 150s）
       │ ⑤ 结果写 logs/auto-deploy.log；可选推送企业微信机器人
       ▼
     上线成功 / 告警（含回滚命令）
```

关键设计：

1. **部署本体零新代码**：备用链路只负责「发现新提交 + 触发」，镜像构建、滚动更新、PostgreSQL 升级前备份、镜像清理全部复用 `deploy/deploy.sh` 未传 `IMAGE_PREFIX/IMAGE_TAG/GHCR_*` 时的既有服务器本地构建路径（该路径此前仅作手动部署兜底，逻辑已在生产验证）。
2. **模式开关互斥**：`.deploy-mode=actions` 时巡检只记录不部署，避免与主链路双写部署基准；`local` 时才真正接管。
3. **精确提交部署**：巡检传入 `DEPLOY_COMMIT=<origin/main sha>`，`deploy.sh` 检测目标提交已在本地对象库后跳过重复 fetch（规避 GitHub SSH 偶发的通道拒绝问题），并重载该提交版本的部署脚本。
4. **观察性**：`mode=actions` 期间若日志连续出现「待部署」而 Actions 无成功记录，即为主链路停摆信号，提示切换 `local`。

## 4. 模式开关与切换 SOP

开关文件：`/opt/ai-eval-platform/.deploy-mode`（未跟踪文件，`git reset --hard` 不会覆盖；缺失视为 `actions`）。

```bash
# 启用备用链路（Actions 用量上限后执行）
echo local > /opt/ai-eval-platform/.deploy-mode

# 回切主链路（Actions 恢复后执行；建议先确认 Actions 近期有成功 Deploy 记录）
echo actions > /opt/ai-eval-platform/.deploy-mode

# 手动立即部署一次（忽略开关与"已是最新"判断，宝塔计划任务页点"执行"亦可）
bash /opt/ai-eval-platform/deploy/auto-deploy-watch.sh --force
```

切换影响说明：

| 时机 | 行为 |
| :--- | :--- |
| 启用 `local` 后首个巡检周期（≤5 分钟） | 自动部署 `origin/main` 最新提交（服务器本地构建，web 构建约 9 分钟，期间旧容器持续服务） |
| `local` 期间 Actions 意外恢复 | 双链路可能先后部署，`deploy.sh` 互斥锁保证串行且最终一致；仍应尽快回切 `actions` |
| 回切 `actions` | 巡检恢复只读；下一段代码由 Actions 主链路接管 |

## 5. 宝塔面板接入（三选一）

脚本随仓库分发，先确保服务器已更新到包含 `deploy/auto-deploy-watch.sh` 的提交（随主链路部署一次即可，或手动 `git pull`）。

### 5.1 方式 A：宝塔 AI / bt_agent_mcp 工具（推荐）

宝塔 AI 内置或 `bt_agent_mcp` 插件接入后，用其通用 Bash 工具执行一次 crontab 写入（幂等）：

```bash
( crontab -l 2>/dev/null | grep -v 'auto-deploy-watch.sh' ; \
  echo '*/5 * * * * /bin/bash /opt/ai-eval-platform/deploy/auto-deploy-watch.sh >> /opt/ai-eval-platform/logs/auto-deploy-cron.log 2>&1' ) | crontab -
```

随后用文件工具确认 `/opt/ai-eval-platform/deploy/auto-deploy-watch.sh` 存在且有执行位。

### 5.2 方式 B：宝塔面板 UI 添加计划任务

1. 面板 → **计划任务** → **添加任务**；
2. 任务类型：**Shell 脚本**；任务名称：`ai-eval 备用自动部署巡检`；
3. 执行周期：**N 分钟 → 5 分钟**；
4. 脚本内容：

```bash
bash /opt/ai-eval-platform/deploy/auto-deploy-watch.sh
```

5. 保存后点「执行」验证一次，再「查看日志」确认输出（巡检正常时每轮一行）。

### 5.3 方式 C：SSH 直接写 crontab（无面板时）

同方式 A 的命令，以 root 执行。

## 6. 可选：部署结果通知

企业微信群机器人（钉钉自定义机器人 text 消息兼容同一结构）：

```bash
# /opt/ai-eval-platform/.auto-deploy.env（chmod 600，不入库）
DEPLOY_NOTIFY_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
# 若宝塔 Nginx 与平台 Web 端口冲突，按真实端口覆盖健康检查地址
# WEB_HEALTH_URL=http://127.0.0.1:8080/
```

部署成功、失败、健康检查不通过、`git fetch` 连续失败四种事件均会推送；Webhook 地址只从该文件读取，不写入日志（遵守 AGENTS.md §5.2.1 凭据不落日志红线）。

## 7. 失败排查与回滚

| 现象 | 排查 |
| :--- | :--- |
| 日志出现「待部署」但一直未切换 | 主链路已停摆，按 §4 启用 `local` |
| `git fetch 连续 3 次失败` | 服务器到 GitHub SSH 连通性：`ssh -T git@github.com`；检查部署密钥 |
| `deploy.sh 退出非 0` | 查看 `logs/auto-deploy.log` 尾部构建输出；常见为本地构建内存不足（web 构建默认 `NODE_BUILD_MEMORY=1536`，低内存机器需先停非关键容器） |
| 健康检查 150 秒未通过 | `docker compose logs -n 100 api` / `web`；确认 `/api/health` 可达；若宝塔 Nginx 占用 80 端口，改 `.auto-deploy.env` 的 `WEB_HEALTH_URL` |
| 需要回滚上一版本 | `cd /opt/ai-eval-platform && git reset --hard <旧提交> && bash deploy/deploy.sh`（旧提交可用 `git reflog` 或告警消息中的 `PREV_SHA` 定位） |

## 8. 约束与边界

1. **生产只跟 `main` 不变**：备用链路只部署 `origin/main`，与 AGENTS.md §4「功能分支不部署生产」一致；
2. **不新增服务器公网入口**：纯出站轮询，无需放行新端口（SSH 22 与既有服务端口维持现状）；
3. **部署互斥**：巡检层 `flock -n`（`.auto-deploy.lock`）防巡检堆积；部署层复用 `deploy.sh` 的 `.deploy.lock` 防双链路并发构建；
4. **宝塔 Nginx 与平台 Web 共存**：若面板 Nginx 占用 80，平台 Web 需改绑其他端口并同步修正 `WEB_HEALTH_URL`（端口规划属运维操作，不在本方案展开）；
5. **本方案不改动 CI**：Actions 恢复后无需任何代码变更，回切开关即可。

---

## 修改代码文件与作用清单（V1.0，2026-08-29）

| 文件 | 作用 |
| :--- | :--- |
| `deploy/auto-deploy-watch.sh` | 备用自动部署巡检脚本：模式开关读取、git fetch 重试、HEAD 与 origin/main 对比、触发 `deploy.sh` 服务器本地构建、健康检查、可选企业微信通知、日志轮转与巡检互斥 |
| `docs/AI测试与评估平台-备用自动部署方案.md` | 本方案：选型、架构、宝塔三种接入方式、切换/回切/回滚 SOP 与边界约束 |
