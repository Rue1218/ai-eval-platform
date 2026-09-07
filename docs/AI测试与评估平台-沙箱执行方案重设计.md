# AI 测试与评估平台 — 沙箱执行方案重设计（评审稿）

> 版本:V0.6（定稿候选） | 状态:P5 复审通过（有条件），收尾完成待归档 | 日期:2026-09-07
> 范围：仅设计文档，不含代码改动。评审通过后按 §12 组合路线图立项实施。
> V0.6（2026-09-07）：P5 复审收尾对齐彼稿 V0.4——D7 内废止编号引用修正（S6 → G1/G5）；worker 回归基线口径（50 passed）；附录 B-6 承接彼稿 §12-7；彼稿契约组扩展（V0.4 §8.2：outcome 扩展/词汇表注册修复/tool_result 结构化字段）为执行面所属，本稿 §7/§8 引用不变。
> V0.5（2026-09-07，历史）：按《团队评审记录》P3 与彼稿 V0.3 对齐——D2/D3/D5/D7 标注「已被取代」；D6 扩 7 项；基线 api 854；排期对齐 G1–G6。
> 依据：`docker-compose.yml` runner 服务、`backend/shared/sandbox_kernel.py`、`backend/runner/main.py`、`backend/runner/Dockerfile`、`backend/api/app/harness/execution/{dispatch,sandbox}.py`、`harness/feedback/rules.py`、`harness/security/exec_policy.py`、`harness/orchestration/agents.py`、`deploy/deploy.sh`、AGENTS.md V1.8（H5 批次 2 未完成项、api 854 基线）。

---

## 1. 现状与问题清单（2026-09-07 实勘察）

| # | 问题 | 事实 |
| :--- | :--- | :--- |
| P1 | **特权容器空转**：`runner` 以 `privileged + seccomp:unconfined + SYS_ADMIN` 常驻，但 `worker.sandbox` 因安全评审未完成被 discover 静态排除（fail-closed），bash 在 agent 引擎**实际上线即不可达**——高危部署形态长期运行却零业务负载 | `docker-compose.yml` runner 段；`exec_policy.resolve_worker_visible`；AGENTS V1.8「批次 2 未完成」 |
| P2 | **评审闭环缺失**：功能被「安全评审」卡住（H5 批次 2 起），无 DoD/无放行阶梯/无回滚判据 → 评审无限期拖延的僵局（无法证明安全 → 不放行 → 无法在生产观察 → 无法证明安全） | AGENTS V1.7–V1.8 两轮仍挂「未完成」 |
| P3 | **能力边界过宽**：bash 是「任意程序执行面」，只靠「黑名单 + 只读词表 + 人工确认」约束；黑名单/词表/正则**三份碎片**（`sandbox_kernel.BASH_BLOCK_PREFIXES` 前缀式、`dispatch.py` token 正则 + 段落切分 + 只读/破坏/变更词表），语义互有出入、易漂移 | 上述三文件 |
| P4 | **无并发/配额控制**：runner 为 `ThreadingHTTPServer`（无线程上限），api 侧无 bash 并发闸门；异常/事故可瞬时占满 runner（容器级仅 mem_limit 兜底），拖垮同机其他服务 | `runner/main.py` |
| P5 | **逃逸面与收益失衡**：bwrap 逃逸 = 容器 root（privileged）= 宿主级风险；嵌套容器化沙箱的隔离正确性完全依赖「评审正确性」而非最小权限结构 | `runner/Dockerfile`、compose |
| P6 | **纵深顺序倒置**：把「能否执行」的关键裁决放在 api 侧提示词驱动 + 双端字符串规则，而真正能兜底的是内核边界；规则层复杂度过高（对模型输出做静态安全分析本身不可靠） | `dispatch.bash_approval_reason` |
| P7 | **工作区无产品实体**：工作区 = 平台按会话自动创建的文件夹 `data/workspaces/<session_id>`（用户无法命名/组织/跨会话复用/自行清理）；前端仅管理员「会话·沙箱文件夹」清理与查看视图，无创建端点、无归属概念——与「用户管理自己的评测素材与产物」的产品预期不符 | `routers/workspaces.py`（list/stats/files/delete）、`AdminWorkspaces.vue`、`workspace.py` |

## 2. 目标与非目标

**目标**
1. 消除 P1/P5：runner 不再以全特权形态常驻空转；隔离边界回到「最小权限结构 + 可测清单」。
2. 打破 P2 僵局：以**能力分档 + 放行阶梯 + 明确 DoD** 代替「全有或全无」评审。
3. 收敛 P3：**删除全部字符串词表碎片（四处，含 `feedback/rules.py`/`check_gates` 门禁），准入改为文件效果档位 + 拒写升档单一模型**（取代原「单一解析器 + 白名单」设想——彼稿 §6.3，已定稿）。
4. 补齐 P4：runner/api 双侧并发配额可配置、可观测、有压测。
5. 默认行为不变：`settings.sandbox_bash_mode=none`（现状 fail-closed）为出厂默认；所有用户可感知变化在开关门内。

**非目标**
- 不用 gVisor/Firecracker/K8s 隔离（见 §附录 A）。
- 不恢复「任意命令免审」或「黑名单制任意执行」。
- 不把 runner 并入 api 进程（保持攻击面分离）。
- 本稿不实施任何代码改动。

## 3. 现状架构回顾

### 3.1 文件与沙箱拓扑（两层正交，先澄清再重设计）

**持久层：一个会话一个文件夹**（api 与 runner 共享同一 `data/` 挂载；V0.5 拓扑勘误——持久目录为 `data/workspaces/<session_id>`，**无中间子层**，`/work` 是沙箱内挂载点而非持久子目录，MAJ-3）：

```
data/workspaces/<session_id>/   ← 会话唯一文件夹（UUID/安全短标识直接子目录，
                                      is_valid_session_workspace 强校验：root 直接
                                      子目录 + 非符号链接；跨调用累积产物都在此）
```

**执行层：每次 bash 调用 = 一个一次性 bwrap 沙箱**（秒级启动、无常驻进程）：

```
模型 bash "…" → api sandbox client(HTTP) → runner(ThreadingHTTPServer)
  → bwrap --bind data/workspaces/<session_id> → /work（唯一可写）
       + ro-bind 系统目录 + --tmpfs /tmp,/run + --unshare-user/pid/net
       + ulimit(内存/进程/CPU) + 墙钟超时 killpg
  → 命令结束 → 沙箱进程销毁（--die-with-parent，整树回收）
```

沙箱本身**无状态、无文件归属**——它只是「该会话文件夹的只读系统视图 + 可写
`/work`」的瞬时外壳；同文件夹可被多次短暂沙箱视图先后包裹（并发时多沙箱共享
同一宿主文件夹，进程内无互斥——P4 缺口来源）。api 与 runner 容器共享同一
`data` 目录树，沙箱内所见即 runner 视角的该会话文件夹。

### 3.2 请求链

```
模型(agent) → toolnode(bash) → 逐调用 policy 解析(档位/升档, 彼稿 §6.2/§6.4)
    → api HTTP(/run,/run/stream, policy{mode,workspace_root}) → runner(降权容器, 固定并发)
    → shared.sandbox_kernel.run_sandboxed(bwrap 一次性沙箱: unshare-user/pid/net
      + 最小ro-bind + 按 mode bind scope(只读或可写) + ulimit + 墙钟超时 killpg)
```

**重设计演进**：上述「会话自动文件夹」拓扑在 §5 D7 用户工作区模型下演进为
「用户自建工作区/文件夹 + 会话绑定」，未绑定会话仍走临时自动工作区（行为
与今日一致）；沙箱执行体变化见 D1–D4——隔离单元语义从「会话 = 数据域」变为
「工作区 = 数据域、会话 = 绑定者」，工具层注入点不变故侵入面小（D7）。

## 4. 重设计总览

### 4.1 设计原则

1. **物理边界优先、规则层后置**：隔离正确性由内核/容器结构承担（可测、可证明），提示词与字符串规则只做「UX 裁决」（要不要问人），不再承担安全兜底。
2. **最小权限结构**：runner 降权、rootfs 只读、seccomp profile 显式化；任何逃逸路径都要求「突破两层以上独立机制」。
3. **能力分档而非一切或全无**：按文件效果档位分档，评审按档进行（档位定义见彼稿 §6.1，本稿不再重复定义）。
4. **无词表层**：命令准入不做字符串静态分析（原「收敛为一个解析器 + 白名单」设想已被彼稿 §6.3「删四处词表」彻底取代——BLK-2）。

### 4.2 分层结构（新）

**实体层（D7）与 L0–L4 正交**：工作区/文件夹是「数据域归属」问题（W 层，见 §5 D7，
含 API/UI/权限/绑定），L0–L4 是「命令准入与执行」问题；两者独立评审、独立灰度。

```
W0 实体层    workspaces 表 + data/workspaces/<uuid>/ 目录树（用户建工作区/文件夹；详见彼稿）
L0 产品层    settings.sandbox_bash_mode ∈ {none(默认), read-only, workspace-write}   ← 彼稿 §6.1
L1 裁决层    逐调用 resolve_bash_policy（会话档位 > 部署默认；升档仅当次）——无词表无静态裁决
L2 桥接层    api sandbox client（并发闸门、超时、幂等重试上限；policy{mode,workspace_root} 契约）
L3 执行体    runner（降权容器 + 固定并发 + 只读 rootfs + seccomp profile + 校验替换见彼稿 §6.2）
L4 内核      shared.sandbox_kernel（bwrap 一次性沙箱，最小 bind 清单可测）
```

## 5. 关键决策

### D1：runner 降权（P1/P5）

**现状**：`privileged + seccomp:unconfined + SYS_ADMIN` + root 运行。
**新形态（实施分两步，每步可单独合入/回滚）**：

| 项 | 现状 | 目标 | 依据 |
| :--- | :--- | :--- | :--- |
| privileged | true | **移除** | bwrap 需要 mount ns 与 userns：`--cap-add=SYS_ADMIN` + 允许 `clone(CLONE_NEWUSER\|CLONE_NEWNS…)` 的 seccomp profile 即够，不再给全部设备访问 |
| seccomp | unconfined | **自定义 profile**（允许白名单 syscalls + userns/mount 子集；禁 raw socket、ptrace、perf、模块加载等） | profile 与镜像同源提交、CI 校验 |
| cap_drop | 无 | `ALL` 后仅加 `SYS_ADMIN` | 最小化 |
| 运行用户 | root | **非 root（USER runner）**；沙箱内 `--uid/--gid` 显式固定非 0 | 沙箱内进程无特权放大 |
| rootfs | 可写 | `/` 只读 + `/tmp`/`/run` tmpfs 可写 | 逃逸后落盘受限 |
| no-new-privileges | 未设 | 设 | 防 setuid 提权 |

**验收**（DoD 项）：降权后 `probe_sandbox` 通过；全部 `backend/shared/sandbox_kernel` 单测与 runner 集成用例通过；§11 演练清单通过。

### D2：能力分档与放行阶梯（P2）——【已被《工作区与沙箱设计方案》V0.3 §6.1 取代，本节仅存历史】

原「off/workfile/mutating + 只读白名单程序集 + 变更集逐命令审批」设计**已废弃**：彼稿 §6.1 定稿为文件效果三档 `settings.sandbox_bash_mode ∈ {none, read-only, workspace-write}`（none 默认 fail-closed 不变；read-only = scope/宿主只读、沙箱临时区可写；workspace-write = scope 可写，准入 = 首条前档位授予 + 拒写升档按次）。本节的「workfile 白名单程序集」与「mutating 逐命令审批」不再实施。放行阶梯（read-only 档灰度 → workspace-write 档）见彼稿 §9.1 量化判据与本稿 D6。

### D3：裁决单一化（P3）——【已被彼稿 V0.3 §6.3 取代，本节仅存历史】

原「新建 `bash_verdict.py` 单一解析器 + 白名单三态」设想**已废弃**：彼稿 §6.3 定稿为**删除全部四处字符串词表碎片**（① `feedback/rules.py` `BASH_BLOCK_PREFIXES` + `check_gates` 门禁分支（toolnode 每次 bash 先跑）及单测；② `sandbox_kernel.BASH_BLOCK_PREFIXES`（含误导注释）；③ `dispatch.py` 词表/正则；④ runner `check_bash_blocklist` 调用）——拒绝由内核文件效果边界承担；过渡期（S3 前）`bash_block_reason` 仅保留 sudo 前缀残余项，S3 后全删（BLK-2）。等价性回归用例承接至彼稿 §9。

### D4：并发与配额（P4）

- runner：`ThreadingHTTPServer` → `ThreadPoolExecutor(max_workers=4)` + 每请求等待队列（超时 429 语义返回，不无限排队）；`/health` 暴露当前负载（running/queued）。
- api：bash 客户端增加**每会话并发闸门**（同一会话至多 1 个 bash 在途，其余 409/排队提示）；与 runner 并发上限构成双层。
- 配置入 `settings`：`sandbox_max_concurrency`（runner 侧由 runner env 注入，与 mem_limit 匹配：512m / 4 workers / 每 worker ulimit 256MB 推导上限可算）——与本稿档位开关（彼稿 `settings.sandbox_bash_mode`）命名风格一致（扁平蛇形）。
- 压测用例（§10）：4 worker 下并发 16 请求 → 排队不 OOM、健康检查不降级。

### D5：审批 = 拒写升档放行——【已被彼稿 V0.3 §6.4 取代，本节仅存历史】

原「审批卡只回答是否允许变更动作、放行该 call_id 进入执行」设计**已演进为彼稿 §6.4 的拒写升档闭环**：read-only 会话 bash 写 scope → runner 结构化 denied → 自动升档卡（复用 `tool_approval` 协议框架 + resume 至多一次）→ approve 以 workspace-write 重放同命令恰好一次；reject 不重放续跑。语义修订（含 API.md §4.3.1「确认前不调用 Runner」段改写、卡 schema 白名单先扩、`meta.schema_version` 评估、ApprovalCard 文案）成组经彼稿 §8.2 契约组留档（API.md V1.75）；升档审批主体 = 工作区属主（BLK-4）；TTL/终态/跨重启语义见彼稿 §6.4。

### D6：评审放行 DoD（P2 闭环，取代「批次 2 无限期」）

`worker.sandbox` 从「不可选」到「read-only 档放行」需同时满足（V0.5 修订：档位语义对齐彼稿，判据引用彼稿 §9.1，基线 854）：

1. D1 降权形态合入且生产运行 ≥7 天无逃逸/异常告警（`sandbox_bash_mode=none` 下容器空转观察：无新增能力，仅验证降权形态稳定）；
2. §10 测试矩阵全绿（含 runner 集成、并发压测、seccomp 冒烟）；
3. §11 红队演练全部「未逃逸/已阻断」（记录到 `docs/` 演练报告并留档）；
4. `read-only` 档灰度：内部/演练会话（`agent_drill_sandbox_enabled=true` 会话集）7 天，按彼稿 §9.1 量化判据评估（bash 失败率 ≤ 基线 +5pp 且不单调上升、安全/引擎告警 0、无投诉）→ 达标后默认会话放行；
5. 全量回归（api 854/worker 50 passed 基线，AGENTS V1.8 口径）与前端 typecheck/build 通过；
6. API.md §4.3/AGENTS.md 状态地图更新（能力档位、开关、DoD 记录）；
7. **磁盘配额验证（彼稿 §6.6）与「写满数据卷」演练通过**（workspace-write 常态化的平台级 DoS 面闭环）。

`workspace-write` 档放行在 `read-only` 稳定 ≥7 天后再评，并**加硬前置：H5 批次 2 完成（PG checkpointer 生产切换 + 网关粘性路由 + 重启恢复演练通过）——升档卡跨重启恢复承诺依赖（BLK-3）**；契约组（彼稿 §8.2）同步执行。

### D7：用户工作区模型 —— 沙箱绑定单元从「会话自动文件夹」改为「用户工作区/文件夹」

**现状（P7）**：工作区 = 会话自动文件夹 `data/workspaces/<session_id>`（`workspace.py`，
UUID 强校验），前端仅管理员「会话·沙箱文件夹」清理/查看（`routers/workspaces.py`
list/stats/files/delete，无创建端点、无 owner）。利好：read/write/edit/bash 全部以
注入的 `sandbox_dir` 为根（`dispatch._resolve_safe_path` / toolnode 默认注入），
**换绑定单元不改工具层**。

**目标形态**：

```
data/workspaces/
├── <ws_uuid>/                 ← 用户工作区（workspaces 表：id/name/owner_id/…）
│   ├── <dir>/…                ← 用户新建文件夹（即文件系统目录，不建表）
│   └── …
└── <session_id>/…             ← 未绑定会话的临时自动工作区（现状兜底，含存量）
```

- 会话绑定：`sessions.workspace_id`（可空）+ `scope_path`（工作区内相对子目录，默认根）；
  **null/null = 临时自动工作区**（`ensure_session_workspace` 兜底，`none` 档与未选择绑定时与
  今日逐字节一致）。运行期 sandbox_dir = `workspaces/<ws_uuid>/<scope_path>`，经唯一
  入口 `resolve_session_sandbox(session)` 解析；绑定缺失/无权限 → VALIDATION
  （fail-closed，不回落裸目录）。
- 新建文件夹 = 工作区目录树内 `mkdir`（无独立表，目录即事实；文件浏览沿用现有
  `/{session_id}/files` 的寻址模式改按 workspace 寻址）。

**关键决策**：

1. **路径校验新规则**（替换 `is_valid_session_workspace` 的「root 直接子目录」限制）：
   `abspath(scope)` 必须位于 `abspath(workspace_root)` 前缀内，且逐段 `realpath`
   后重验前缀（符号链接逃逸拒绝），仍拒 `.`/`..` 段；**runner 侧同规则再验一遍**
   （runner 不信任 api 传参，沿用现状双重校验思路）。
2. **共享工作区并发（V0.5 修订，BLK-1）**：原「独占绑定（同 scope 第二会话 409）」**已被彼稿 §5 定稿取代**——属主本人多会话可绑定同一 scope（共享写、自担）；跨用户共享写禁止（绑定会话强制 private，BLK-4）；「活跃会话独占」仅作可选开关按需增补。删除竞态与行锁串行化见彼稿 §4.2/§7.3。
3. **权限最小面**：工作区属主 = 创建用户（`owner_id`）；owner 会话可绑定；**绑定会话强制 private（禁止 team 会话绑定/转 team，BLK-4）**；管理员全量
   可见/可清理（Admin 页保留，叠加 owner 列）；**不做成员共享**（防权限面膨胀）。
4. **API/UI 增量**：工作区 CRUD（POST/GET/DELETE + 每 owner name 唯一）+ 文件夹
   创建/浏览（复用文件列表端点模式）+ 前端「我的工作区」页（建工作区/建文件夹/
   浏览/删除，删除前孤儿与绑定中检查）。路由挂靠现有 `workspaces.py` 扩展或独立
   模块——**V0.6：随 G1（彼稿 F1）评审定**（原「S6」编号已废止）。
5. **契约与红线影响**：现状「一个会话一个工作区、会话间互不可见」语义**仅对未绑定
   会话保留**；绑定后隔离单元是工作区——多会话可见同一文件夹是用户显式选择的
   预期行为。前端说明条/API.md 中「会话间互不可见」表述**V0.6：随 G5（彼稿 F3）
   同步改口径**（原「S6」编号已废止；文档化修订，非协议变更）。删会话不删工作区
   （反之亦然——注销 = 软删，彼稿 V0.4 §4.1）；orphans 清理只作用于未绑定的
   legacy 目录。
6. **数据模型**：新增 `workspaces` 表；`sessions` 增可空列 `workspace_id` /
   `scope_path`（Alembic 一次迁移，**不迁移存量**——存量目录即 legacy 临时工作区，
   语义不破损）；legacy 导入与孤儿守卫见彼稿 §7.2/§7.3。
7. **与档位正交**：工作区模型只回答「数据域归谁」，不回答「命令能否执行」（档位 =
   彼稿 §6.1 `sandbox_bash_mode`）；两者独立评审、独立灰度。

> D7 其余细节（路径校验新规则、API/UI 增量、契约口径、拓扑与目录形态）以彼稿
> §4–§7 为准；本稿 D7 仅保留职责边界与修订登记，不再重复实现描述。

## 6. 迁移与回滚

- **迁移顺序（V0.5 对齐彼稿 §10 G1–G6，每步独立 PR/镜像 tag，可单独回滚）**：
  1. G1 = 彼稿 F1（工作区实体与管理面，none 档内先行）→ PR；
  2. G2 = 本稿 S3：D1 降权（Dockerfile/compose/seccomp profile；`none` 下空转验证 7 天）→ PR；
  3. G3 = 本稿 S2：D4 并发配额（runner 替换线程模型 + api 闸门；与 G2 可并行）→ PR；
  4. G4 = 彼稿 F2：policy 解析 + runner bind mode 化 + **runner 校验替换（彼稿 §6.2）** + 删四处词表（依赖 G2；S3 前 `bash_block_reason` 仅余 sudo 残余项）→ PR；
  5. G5 = 彼稿 F3+F4：会话绑定（private 强制/legacy 导入）+ read-only 档灰度（彼稿 §9.1 判据 + 本稿 D6）→ PR + CD；
  6. G6 = 彼稿 F5：workspace-write 档 + 升档审批 + 契约组（硬前置：G2 + H5 批次 2 完成）。
- **回滚**：任何一步异常 → `settings.sandbox_bash_mode=none`（恢复 fail-closed，一行 .env + `docker compose up -d api`）；降权/并发改动回滚 = 部署前一镜像 tag（deploy.sh 已按 tag 支持）；**runner/api 接口混布回滚 = 先回 runner 镜像 tag（彼稿 §6.2）**。

## 7. 默认行为与契约影响

- 默认 `settings.sandbox_bash_mode=none`：`bash` 工具 fail-closed 文案、`worker.sandbox` discover 排除、审批卡不可达——**与今日逐字节一致**（AGENTS V1.8 承诺保持）。
- 契约影响：**WS 事件 kind/上行零变化**；`tool_approval` 语义修订（拒写升档）经彼稿 §8.2 契约组成组留档（API.md V1.75、卡 schema 白名单先扩、ApprovalCard 行为对照）；REST 增量（工作区端点、`SessionCreate` 字段、sharing 守卫）按 API.md 版本纪律经契约评审（彼稿 §8）；新增 `settings.sandbox_bash_mode`/`workspace_quota_bytes` 与 runner 环境变量登记（按现有 config 登记纪律）。
- 前端：审批卡/错误条文案沿用现有组件（文案随契约组更新）；**「前端无改动」声明撤回**——会话配置（草稿模式适配：首条前设置面板绑定/档位）与「我的工作区」页为彼稿 §4.4 交付面（MAJ-6）。

## 8. 可观测性

- 指标（agent_trace / 结构化日志）：bash 请求量按档位（none/read-only/workspace-write）、denied/升档分布（彼稿 §6.5 结构化 `sandbox:{mode,denied}`）、runner 排队/超时、磁盘配额触发率（彼稿 §6.6）；灰度判据见彼稿 §9.1；
- 事件：不新增 WS kind（服务端留痕为主）；denied 标记/升档提示复用 `tool_result` 文案（彼稿 §6.5）；
- 演练报告按 §11 归档（docs/），灰度结论随 AGENTS 状态地图更新；
- 契约留档时核对 `tool_approval`/`clarify` 等直产 kind 与词汇表注册一致性（彼稿 §8-4）。

## 9. 残余风险

| 风险 | 缓解 |
| :--- | :--- |
| bwrap 自身漏洞/配置缺陷 | 降权容器 + seccomp + 非 root 多层兜底；逃逸后仍无网络（internal net）、rootfs 只读、落盘受限 |
| 档内破坏命令误执行（workspace-write 授予后无逐命令把关） | 准入两层 = 授予（一次性）+ 拒写升档（按次）（彼稿 §6.3-4/BLK-5）；授予 UI 明示风险 + 绑定 private + 审计 |
| 模型诱导审批通过危险变更 | 升档卡展示命令原文 + 属主身份校验（BLK-4）；read-only 默认；授予决策一次性人工 |
| 分档开关误配（直接开 workspace-write） | DoD 硬门槛 + 灰度判据（彼稿 §9.1）+ 开关注释警告；`workspace-write` 需显式二次确认（config 注释 + AGENTS 记录） |
| 并发上限引入 429 影响长任务 | 排队而非拒绝（限时等待）；每会话闸门保证一致性；压测定标 |
| 多会话共享 scope 互相破坏 | 属主内共享（自担）定稿；绑定 private；「活跃会话独占」可选开关（BLK-1） |
| team 会话横向越权（成员借绑定会话写/自批升档） | 绑定强制 private + sharing 守卫 + 审批主体 = 工作区属主（BLK-4，彼稿 §5/§6.4） |
| 升档卡跨重启静默丢失 | workspace-write 放行硬前置 H5 批次 2；此前单副本语义 + error/卡作废审计终态（BLK-3，彼稿 §6.4） |
| 符号链接逃逸 / resolve→bind 窗口换链 | 路径逐段 realpath 前缀重验 + bind realpath 后最终路径（api + runner 双侧）；演练 3.1/换链用例 |
| 磁盘写满共享卷（workspace-write 常态化 DoS） | 每工作区配额 + 写前检查 + 周期告警（彼稿 §6.6）；入 D6-7 与演练 |
| 工作区误删 / 删除竞态 | 注销默认不删文件；purge/清理行锁 + 二次复检 + 活跃回合判定（彼稿 §4.2/§7.3）；仅 owner/管理员；审计 |

## 10. 测试矩阵（DoD 依据）

- 单元：`sandbox_kernel` 既有全套保留；**词表删除等价性回归**（承接彼稿 §9：四处实现拒绝样例集在删除后不劣化——「前缀 vs 段切分」差异样例如 `bash -c 'curl …'`；gate 门禁用例迁移为「拒绝由内核/档位承担」断言）；
- 集成（runner）：`/run` 正常/超时/**policy 档位 bind（read-only ro-bind / workspace-write rw-bind）**/结构化 denied 字段、并发 16 压测（无 OOM、健康不降级）、非法路径/畸形请求/**未知或缺失 mode 默认拒绝（fail-closed，彼稿 §6.2）**；
- 降权验收：容器内 `probe_sandbox`、`sandbox_bash_mode=none` 空转 7 天无异常（日志留档）；
- 回归：api 全量（854 基线，AGENTS V1.8）/ worker 全量（50 基线）/ 前端 typecheck+build；
- CI：新增 runner seccomp/profile 冒烟 job（可选）。
- 工作区模型（彼稿 §9 承接）：`resolve_session_sandbox` 绑定/缺省/无权限/注销后失效分支；scope 规范化 + 符号链接逃逸 + 前缀越权（api 与 runner 双侧）；**runner 嵌套 scope（`{root}/<ws>/<folder>`）bind 与换链拒绝（彼稿 §6.2/MAJ-5）**；属主共享/跨用户 403/team 绑定拒绝（BLK-4）；删除 × 绑定/回合竞态（彼稿 §4.2）；legacy 导入与目录不回归。

## 11. 红队演练清单（放行前必过，产出演练报告）

1. 沙箱内读取宿主 `/run/config/.env`（供应商 Key）→ 不可见（tmpfs 遮蔽验证）；
2. 沙箱内访问网络（curl/ping/dns）→ 全部失败（unshare-net + internal 网双层）；
3. 沙箱内读写**其他工作区 / 未绑定会话文件夹 / 根目录** → 拒绝（绑定 scope 前缀强校验 + 唯一可写）；
3.1. 沙箱内符号链接逃逸（链接目标指向工作区外或其他工作区）→ 拒绝（realpath 后前缀重验）；
3.2. **resolve→bind 窗口换链**（并发会话在 api 校验后、runner bind 前替换 scope 内符号链接指向卷外）→ 拒绝（bind realpath 后最终路径，彼稿 §6.2/MAJ-9③）；
4. 沙箱内提权尝试（sudo/setuid/chroot 逃逸尝试）→ 阻断/无特权放大（S3 降权后验证非 root 语义）；
5. 沙箱内 DoS（fork 炸弹/内存占满/死循环）→ ulimit + 墙钟超时 killpg 回收，宿主无影响；
5.1. **沙箱内写满数据卷**（workspace-write 反复写/单命令洪水写共享 data 卷）→ 每工作区配额拒写 + **卷级水位熔断兜底**（写前检查拦不住单命令洪水；剩余空间低于水位阈值 → workspace-write 整体拒写，fail-closed），同机服务不拖垮（彼稿 §6.6 M-R3-4，D6-7；V0.6 判据随彼稿 V0.4.1 同步）；
6. runner 容器逃逸演练（假设 bwrap 被突破）：rootfs 只读、非 root、seccomp 下横向移动受限（internal 网络无出网）；记录可复现步骤与结论。

## 12. 实施排期建议（评审通过后另行立项）

| 里程碑 | 内容 | 依赖 | 建议 PR 粒度 |
| :--- | :--- | :--- | :--- |
| ~~S1~~ | ~~D3 `bash_verdict` 单一化~~ **取消**——由彼稿 F2（删四处词表）彻底取代 | — | — |
| S2 | D4 并发配额（runner 线程池 + api 闸门） | 无（与 S3 并行） | `feat(agent): runner concurrency caps` |
| S3 | D1 runner 降权 + seccomp + 空转观察 7 天 | 无 | `security(agent): de-privilege sandbox runner`（none 空转观察） |
| — | G1 = 彼稿 F1：工作区实体/CRUD/前端（none 档内先行） | 独立 | `feat(workspace): user workspaces & folders` |
| — | G4 = 彼稿 F2：policy + bind mode 化 + runner 校验替换 + 删四处词表 | S3 | `refactor(agent): file-effect policy, drop blocklists` |
| — | G5 = 彼稿 F3+F4：会话绑定（private/导入）+ read-only 灰度 | G4 + S3 + D6 | `feat(agent): session-workspace binding & read-only tier` |
| — | G6 = 彼稿 F5：workspace-write + 升档审批 + 契约组 | G5 稳定 7 天 + S3 + H5 批次 2 | `feat(agent): workspace-write & escalation` |

> V0.5 说明：本稿 S1–S7 旧编号已废止（S1 取消；S4/S5 由彼稿 F4/F5 取代；S6/S7 由彼稿 F1/F3 取代）；本稿责任阶段仅保留 S2/S3（D4/D1 执行体侧），其余以彼稿 F 系列与 G 里程碑为排期真源（彼稿 §10）。

## 附录 A：不采纳方案与理由

| 方案 | 理由 |
| :--- | :--- |
| gVisor/Firecracker/微虚机 | 新增基础设施与运维面，当前负载（低配 16G/512m 预算）下收益/成本失衡；bwrap 多层降权已覆盖主要威胁模型 |
| 移除 bash 只留 read/write/edit 工具 | 评估场景确有批量统计/管道/格式过滤需求，read 单文件模型表达不了（词表删除后由档位 + 内核边界约束，彼稿 §6.3） |
| runner 并入 api 容器（放弃独立执行体） | 攻击面合并回 api（api 含 Key/会话面），违反「执行体最小暴露」原则，否决 |
| 维持 privileged+unconfined 仅补文档 | 不解决 P1/P5 结构性问题，否决 |

## 附录 B：评审待决点（V0.5 状态更新）

1. D1 非 root + 自定义 seccomp profile 的实现风险是否可接受（bwrap 在非特权+no-new-privileges 下的可用性需 S3 先做 PoC）——**开放，S3 前置 PoC**；
2. ~~`workfile` 白名单集是否足够支撑真实评测场景~~ **已关闭**：词表/白名单设计废弃（彼稿 §6.3），需求样本改用于 read-only 档灰度观察（彼稿 §9.1）；
3. 并发默认值（4 workers / 每会话 1 在途）是否与现有负载假设匹配——**开放，S2 压测定标**；
4. ~~`mutating` 档放行护栏~~ **已演进**：workspace-write 放行 = 授予 + 拒写升档两层（彼稿 §6.4）+ D6-7（配额）与 H5 批次 2 硬前置；
5. ~~D7 工作区并发模型~~ **已关闭（BLK-1）**：属主内多会话共享允许、跨用户禁止、绑定强制 private（彼稿 §5）；
6. D7 文件夹层级深度/命名规则（scope_path 允许深度？限制层级与字符集？是否开放改名/移动）——**开放**，承接至彼稿 §12-7（V0.6 显式化，F3 实现前定）。
