# AI 测试与评估平台 — 备用自动部署方案（GitHub Actions 用量受限回退链路）

> **文档地位**：本文件是平台部署链路的配套技术方案，规定 GitHub Actions CD 因用量上限停摆时，
> 生产环境 `47.119.132.83` 的备用自动化部署机制。与 [`AI测试与评估平台-API.md`](AI测试与评估平台-API.md) 无契约交集。
> 版本：V1.4 ｜ 审查日期：2026-09-12

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
5. **自动降权（V1.1）**：仓库属主与 GitHub 部署密钥的分布存在两种拓扑——`deploy/server-setup.sh` 方案下属主为 `deploy` 用户（密钥在 `/home/deploy/.ssh`）；宝塔托管的服务器实测为 root 属主、无 `deploy` 用户（密钥在 `/root/.ssh`）。脚本两种拓扑均兼容：root 启动时若存在 `deploy` 用户则先修正 `logs/` 属主再 `sudo -u deploy -H` 降权重入（避免 root 的 git 操作把仓库对象写成 root 属主、破坏 `deploy` 身份主链路的后续部署），否则保持 root 原样执行。
6. **按部署基准自愈（V1.2）**：「是否有待部署提交」以 `.deploy-success-sha`（上次成功部署标记）而非工作区 HEAD 为基准对比 origin/main——HEAD 在 `deploy.sh` 的 `git reset` 阶段就会前进到目标提交，若部署中途被打断（SSH 断开、远程后台任务超时强杀等），按 HEAD 对比会误判「无需部署」而永不自愈；按标记对比则下一轮巡检（≤5 分钟）自动续跑剩余构建与滚动更新，且 `deploy.sh` 的差异构建以标记为基准，续跑只重建未完成部分。

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

部署成功、失败、健康检查不通过、`git fetch` 连续失败四种事件均会推送；Webhook 地址只从该文件读取，不写入日志（遵守 AGENTS.md §5.2.1 凭据不落日志红线）。注意 `.auto-deploy.env` 与 `.deploy-mode` 若由 root 创建，需保证 `deploy` 用户可读（默认 644 即可；`.auto-deploy.env` 建议同时 `chmod 600` 并 `chown deploy:deploy`）。

## 7. 失败排查与回滚

| 现象 | 排查 |
| :--- | :--- |
| 日志出现「待部署」但一直未切换 | 主链路已停摆，按 §4 启用 `local` |
| `git fetch 连续 3 次失败` | 服务器到 GitHub SSH 连通性：`ssh -T git@github.com`；检查部署密钥 |
| `deploy.sh 退出非 0` | 查看 `logs/auto-deploy.log` 尾部构建输出；常见为本地构建内存不足（web 构建默认 `NODE_BUILD_MEMORY=1536`，低内存机器需先停非关键容器） |
| 健康检查 150 秒未通过 | `docker compose logs -n 100 api` / `web`；确认 `/api/health` 可达；若宝塔 Nginx 占用 80 端口，改 `.auto-deploy.env` 的 `WEB_HEALTH_URL` |
| 需要回滚上一版本 | `cd /opt/ai-eval-platform && git reset --hard <旧提交> && bash deploy/deploy.sh`（旧提交可用 `git reflog` 或告警消息中的 `PREV_SHA` 定位） |
| 部署进程被中途打断（SSH 断开 / 远程后台任务超时强杀） | 无需干预：下一轮巡检按 `.deploy-success-sha` 基准自动续跑（V1.2）；构建失败的轮次旧容器持续服务 |

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
| `deploy/auto-deploy-watch.sh` | 备用自动部署巡检脚本：模式开关读取、git fetch 重试、HEAD 与 origin/main 对比、触发 `deploy.sh` 服务器本地构建、健康检查、可选企业微信通知、日志轮转与巡检互斥；root 启动时自动 `sudo -u deploy` 降权重入（V1.1） |
| `docs/AI测试与评估平台-备用自动部署方案.md` | 本方案：选型、架构、宝塔三种接入方式、切换/回切/回滚 SOP 与边界约束 |

**V1.1（2026-08-29）— 复查修正属主冲突并完成宝塔接入**

宝塔计划任务默认以 root 运行；若仓库属主为 `deploy` 用户（server-setup 方案），root 的
`git fetch/reset` 会把 `.git` 对象写成 root 属主且无部署密钥，备用链路自身失败并连累
`deploy` 身份的主链路部署。修正为：root 启动时先修正 `logs/` 属主，再 `sudo -u deploy -H`
降权重入本脚本（`DEPLOY_WATCH_REEXEC` 防循环）；仓库属主为 root（宝塔托管服务器实测
拓扑，无 `deploy` 用户）时保持 root 原样执行。另打磨：`.deploy-mode` 缺失时不再向
cron 日志输出重定向报错、`git fetch` 静默化；巡检脚本已在服务器经宝塔 MCP 落地并注册
root crontab 计划任务（每 5 分钟），试跑巡检通过。

**V1.2（2026-08-29）— 按部署基准自愈中断的部署**

首轮备用部署在服务器本地构建（web 约 30 分钟，2 核 / 1.6GB 内存 swap 争抢）期间被远程
后台任务的 30 分钟超时强杀，`deploy.sh` 的 `git reset` 已推进工作区 HEAD 但容器未更新，
原脚本按 HEAD 对比 origin/main 会误判「无需部署」导致永不自愈。修正：待部署判断改为
`.deploy-success-sha`（上次成功部署标记）对比 origin/main，标记落后即自动续跑；续跑时
`deploy.sh` 差异构建仍以标记为基准，只重建未完成部分。同步补充排错表「部署被中途打断」
自愈说明。

## 9. 构建与传输优化（V1.3）

本轮检查涵盖 `.github/workflows/deploy.yml`、`deploy/deploy.sh`、备用巡检脚本、
Compose 与六个业务 Dockerfile。主链路已有按服务的 GHA 层缓存，生产机只拉取镜像；
备用链路已逐服务串行构建，不再通过增加服务器构建并发提速。

### 9.1 已确认的基线

- [Deploy 34603425193](https://github.com/Rue1218/ai-eval-platform/actions/runs/34603425193)
  （2026-09-11，提交 `e8f0bf3`）从创建到结束约 200 秒；Web 构建任务 84 秒，
  其中构建与推送步骤 51 秒、Vite 26.10 秒；SSH 部署步骤 93 秒。
- 该次生产日志显示，Web 的一个 1.908 MB 层下载约一分钟。原 Dockerfile 将整个
  `dist` 放在一层，业务文件变化时未变的 vendor 文件也随该层重新传输。
- API / Worker / Runner 构建上下文均为 `backend/`，原 `api/.dockerignore` 与
  `worker/.dockerignore` 不位于上下文根，也不是 Dockerfile 专属忽略文件，因此不生效。
- 前端原 `NODE_BUILD_MEMORY` 在 npm 安装前声明；改变堆上限会使后面的依赖层失效。
  原安装使用 `npm install`；Python 安装显式禁用下载缓存。

### 9.2 实施内容与边界

1. API / Worker / Runner 分别新增 `Dockerfile.dockerignore`，路径相对 `backend/`，
   只纳入镜像所需源码与共享包，排除测试、环境文件、虚拟环境和本地缓存。
   文件位于既有服务路径下，现有 CI 和服务器差异计算会自动选中对应服务。
2. 前端改用 `npm ci` 严格按锁文件安装；npm 与三份 Python 镜像的 pip 下载目录
   使用 BuildKit cache mount，下载文件不进入镜像层。内存和版本参数均放在依赖安装后。
   Cache mount 在同一个持久构建器上累积；**GHA 后端默认不导出 cache mount 内容**，
   Actions 跨任务仍主要依赖既有 `cache-from/cache-to type=gha,mode=max` 层缓存。
3. 将 `dist/assets/vendor-*` 移到独立目录，并在运行阶段先复制 vendor 层，再复制
   其余 `dist`。最终 URL 与文件内容不变；vendor 内容稳定时只需传输应用层。
   首次切换分层布局仍需拉取新层，依赖变更时 vendor 层也会更新。
4. 两处 Compose 拉取默认使用 `--parallel 2`，可由进程环境变量
   `DEPLOY_PULL_PARALLEL` 覆盖为正整数。该限制是**服务级并发**，不限制单个镜像
   内的层下载数、CPU 或总内存；资源更紧时可设为 1，可能延长全量拉取时间。
   服务器本地 Vite 堆上限维持 1536 MB，不将已有 OOM 阈值调低。
5. CI 保留 Runner 每次准备镜像的恢复兜底；不改变镜像引用恢复、停止/暂停状态保留、
   数据库升级备份或清理策略。新增独立脚本检查任务，不连接生产。

实现依据：[Docker 构建上下文](https://docs.docker.com/build/concepts/context/)、
[缓存优化](https://docs.docker.com/build/cache/optimize/)、
[GHA 缓存边界](https://docs.docker.com/build/ci/github-actions/cache/)、
[Compose 并发选项](https://docs.docker.com/reference/cli/docker/compose/)。

### 9.3 本地验证与生产验收

- Bash 语法检查、YAML 解析、部署静态资源分层回归用例、现有 H5 部署契约检查通过。
- 用 Docker 同源的 `moby/patternmatcher v0.6.0` 核验三份忽略规则：实际 COPY 输入保留，
  环境文件、测试和缓存排除。当前本地后端文件总量约 18.94 MB；规则纳入 API
  1.93 MB、Worker 0.23 MB、Runner 0.12 MB。此为文件集合统计，不是实测 Docker 传输量。
- 隔离目录执行锁文件安装、前端 typecheck 与 1536 MB 堆上限构建。
  构建产物约 6.73 MB，其中独立 vendor 文件约 5.47 MB（81.18%），其余约 1.27 MB。
  在隔离副本修改业务文案、版本号和时间后再次构建，3 个 vendor 文件哈希不变；
  执行 Dockerfile 拆分命令并合并两层后，46 个真实产物逐字节一致，4 个入口资源引用均存在。
  这是未压缩文件大小，不能直接换算生产下载耗时或声称部署提速比例。
- 合入后生产验收（V1.4 更新）：服务器侧首轮实测已完成（见 §9.4，2026-09-12，`d42a5b46`）；
  第二轮 Web 更新的 vendor 层 digest 对比、Actions 侧逐步骤耗时与逐层下载字节仍待后续部署补录。

### 9.4 生产验收实测（V1.4，2026-09-12，d42a5b46）

PR #305 合入后由 GitHub Actions 主链路完成生产部署：web / api / worker / runner / lightrag
五个镜像更新为 `d42a5b46` 不可变 tag（stress 本轮无代码变更），`.deploy-success-sha=d42a5b46`，
api / runner 容器 healthy、健康接口 200；lightrag 容器保持用户主动停止状态（镜像已就绪，
按部署脚本「停止/暂停状态保留」策略未滚动）。

**部署时间线（服务器侧，CST）**

| 阶段 | 时间 | 说明 |
| :--- | :--- | :--- |
| CD SSH 登录 / 精确提交同步 | 13:50:09 / 13:50:14 | `git reset` 到 `d42a5b46` 完成 |
| 镜像拉取与本地解包 | 13:50:22 – 14:17:19 | 约 27 分钟；期间 dockerd 记录 2 次 `unexpected EOF` 下载中断并自动重试（14:05:16、14:16:56），未影响最终结果 |
| 业务容器滚动重建 | 14:17:55 – 14:18:18 | runner → api → web → worker，约 23 秒 |
| 完成标记写入 | 14:18:19 | SSH 部署窗口合计 ≈ 28m05s（13:50:14 起算） |

**本轮实际重传的镜像层**（口径：diff 目录 mtime 落在部署窗口内的层，即本次真正解包/下载的层；
大小为未压缩字节，MiB）

| 服务 | 重传层数 | 未压缩合计 | 主要层 |
| :--- | ---: | ---: | :--- |
| web | 2 | 6.42 MB | vendor 5.21 MB + 应用 1.21 MB（nginx 及基础层全部复用 2026-09-04 解包，零重传） |
| api | 7 | 205.2 MB | `pip install` 层 203.34 MB（其余为 shared/app 等小层） |
| worker | 3 | 105.8 MB | `pip install` 层 105.54 MB |
| runner | 1 | 0.02 MB | 单层极小更新 |
| lightrag | 7 | 86.0 MB | apt 11.40 + 40.46 MB、`pip install` 34.18 MB |
| **合计** | **20** | **403.4 MB** | |

- 约 395 MB（98%）是三个 Python 服务的 apt/pip 依赖层：本轮 Dockerfile 变更（pip 缓存挂载等）
  使这些层 digest 更新，触发一次性整层重传；依赖不变时层 digest 稳定，后续轮次预计回落到
  runner/web 量级的小增量（本轮 runner 仅 0.02 MB 已验证增量拉取机制）。
- **Web 分层在生产镜像中成立**：vendor 层
  `sha256:ba91fe365171658fa1858a64855d5c009629250b0ce6e1e45cd639230d9f2876`（5.21 MB）、
  应用层 `sha256:031f6d80ca91118cbb9e903e4098e28b97687fcedd9ff078661b74e8526a7cc1`（1.21 MB）。
  下一轮仅改业务代码时应只重传应用层——**第二轮对比待下一次 Web 更新后按同口径补录**。
- 镜像未压缩总大小：web 51.3 / api 326.7 / worker 226.1 / runner 132.3 / lightrag 161.0 MB；
  清单 digest 随部署记录（如 web `sha256:8b68ad47892e2dc3315fa02509e44593506b634b7f6917f26a18c9370487625d`）。
- 耗时对比：本轮 SSH 部署 ≈ 28m05s，高于 §9.1 基线轮（`e8f0bf3`，SSH 步骤 93 秒），
  差异即上述一次性大层重传叠加受限带宽；不代表流水线常态回退。

**资源快照（部署完成后空闲态，14:40；主机 2 核 / 1.6 GB）**

- 内存 used 1003 MB / total 1671 MB，available 667 MB；swap：磁盘 `/www/swap` 563 MB、
  zram 1024 MB 用满；磁盘 17 GB / 40 GB（46%）；load average 1.10。
- `docker stats --no-stream`：web 1.7 MB、api 15.7 MB、worker 59.8 MB、runner 2.9 MB、
  postgres 9.2 MB、redis 2.7 MB。
- 部署期间峰值无法回溯采样（stats 为实时指标）；下一轮部署时应实时采集。

**测量方法与遗留**

- 「本轮重传层」由镜像 `RootFS.Layers`（diff_id）× overlay2 layerdb（cache-id / size）交叉，
  取 diff 目录 mtime 落在部署窗口内的层；容器起停取 `docker inspect .State.StartedAt`；
  下载中断证据取 journald `dockerd` 日志。
- 压缩传输字节与 Actions 侧逐步骤耗时不在服务器落盘（仓库私有，服务器无 Actions API 访问）：
  需从该轮 Actions「Deploy to server」步骤日志补录；下一轮对比时同步记录 vendor 层 digest。

## 修改代码文件与作用清单（V1.3，2026-09-12）

| 文件 | 作用 |
| :--- | :--- |
| `frontend/Dockerfile` | 锁文件安装、npm 下载缓存、内存参数后移、vendor 与应用静态资源分层 |
| `frontend/.dockerignore` | 排除测试、浏览器报告和日志，避免无关文件触发源码层更新 |
| `backend/{api,worker,lightrag}/Dockerfile` | pip 下载缓存移到 BuildKit cache mount |
| `backend/{api,worker,runner}/Dockerfile.dockerignore` | 在正确上下文生效的各服务文件筛选规则 |
| `deploy/deploy.sh` | 限制镜像拉取并发，修正与实际行为不符的旧构建说明 |
| `deploy/tests/test_build_artifacts.py` | 执行真实 Dockerfile 拆分命令，验证资源路径与内容完整、无 vendor 场景 |
| `.github/workflows/ci.yml` | 持续检查部署 Shell 语法与静态资源分层 |

**V1.4（2026-09-12）— d42a5b46 上线轮生产验收实测**

V1.3 合入后由 GitHub Actions 主链路完成部署（当日 14:18 完成，web/api/worker/runner/lightrag
更新为 `d42a5b46`）。本版为纯文档修订：§9.3 末尾的「合入后应对比…」待办收口为已采集服务器侧
首轮实测，新增 §9.4（部署时间线、本轮实际重传层清单、Web vendor/应用层 digest 基线、
资源快照与测量口径）；第二轮 vendor 层对比与 Actions 侧逐步骤耗时/逐层下载量标记为待补录。
