# AI 测试与评估平台 — 工作区与沙箱设计方案

> 版本:V0.6.1（定稿候选） | 状态:G5（F3）落地登记；**F5 核心代码开发完成（升档审批 G6a + 配额/终态 G6b，feat/sandbox-g6-quota 链）**，放行仍待 F4 灰度（S3 观察期满后部署决策） | 日期:2026-09-08
> 范围：仅设计文档，不改代码。评审通过后按 §10 分期实施。
> V0.6.1（2026-09-08）：G6/F5 代码落地登记（两个链式 PR，全部开关后/默认关，
> 生产零行为变化）——**G6a（feat/sandbox-g6-escalation）**：DENIED 错误码全链
> （HTTP 403 + kernel EROFS 证据识别 → api 归一）；toolnode 自动升档卡
> （`agent_escalation_approval_enabled` 默认关；denied 帧 + interrupt
> reason=escalation → approve 以 workspace-write 重放恰好一次，reject 走失败
> 阶梯，防环）；AppError 保码修复；`ToolExecutionContext.sandbox_mode` 档位
> 接缝；失败阶梯排除 escalation 中间帧（MAJ-9②）。**G6b（本稿）**：磁盘配额
> §6.6 代码（`workspace_quota_bytes` 默认 1GiB + `sandbox_volume_watermark_bytes`
> 默认 512MiB；写前检查 TTL 缓存 du + 卷水位熔断优先；挂点 = dispatch 直写
> write/edit 净增 + workspace-write bash 写前；VALIDATION 码不触发升档链）与
> M-R3-7 终态落地（ack 行锁内检查点预检 `_approval_resume_probe` → 缺失清卡
> + `voided` 终态 + error；resume 恢复失败 → `recovery_failed` 终态广播；前端
> ApprovalCard/Agent.vue 四终态成组扩展；API.md approval_terminal outcome 修订）。
> 门禁 api 949/runner 18/worker 50。
> 与《沙箱执行方案重设计》V0.6.1 的关系：本稿正式化其 D7 并修订 D2/D3（词表全删 → 文件效果档位 + 拒写升档）；D1 降权（V0.6.1 PoC 勘误形态）、D4 并发、D6 放行 DoD（扩 7 项）继续有效；组合路线图见 §10 G1–G6。
> V0.6（2026-09-07）：**G5 = F3 会话绑定接线落地登记**——`POST /api/sessions` 增量 `workspace_id/scope_path`（创建固化、仅 private、属主校验 + `ensure_workspace_scope` 目录就绪、AuditLog `session_workspace_bind`）；新增 `resolve_session_sandbox` 唯一沙箱解析入口（§5 校验链落地：绑定失效 fail-closed 不回落 legacy），替换 ws.py 注入点；已绑定转 team 拒绝（BLK-4）；`SessionOut` 绑定字段 + `workspace_name`；前端草稿「绑定工作区」预选 + 列表/顶栏绑定展示（初版仅根 scope）；API.md V1.76 / AGENTS V2.0 契约留档。附件 staging 仍落 legacy（绑定会话附件归属随绑定迁移留评审，见 §12 待决点 8）。F4 read-only 档灰度（§9.1 判据 + 部署翻转 `sandbox_bash_default_mode`）与 G6/F5 未交付。
> V0.5（2026-09-07）：**G4 = F2 落地登记**——§6.2 policy 契约与 runner 前缀校验（`resolve_workspace_path`）、bind mode 化（read-only/workspace-write）、§6.3 四处词表与静态裁决全删（含 sudo 残余项，依据按 G2 定稿形态改述，见 §6.3② 标注）、toolnode 直通（升档卡 F5 接入）、runner 双端 fail-closed 测试（policy 缺失/mode 非法 VALIDATION）；图级 tool_approval interrupt 端到端用例转 F5 升档卡接入恢复（test_bash_hitl/test_hybrid_h5_hitl 改写为直通回归，卡协议 ws 层用例保留）；门禁 api 881/runner 17/worker 50。
> V0.4.1（2026-09-07，历史）：第三轮终审补丁——**M-R3-6** 软删组合闭合：孤儿判定与守卫②按行态区分（仅活跃行受保护）、purge 事务内显式解绑、§7.2 导入 = 复活路径（旧会话自动恢复续用，MAJ-1 真闭环）、§9 口径对齐；**M-R3-7** 作废终态改「行锁内清卡 + `voided` 终态 + error + AuditLog」（对齐 expired 先例，消除卡残留与双终态）；契约组补 V1.75 范围清单/纪律句/卡归类统一/回归锁断言/`allowed_decisions` 漂移校正；§6.6 熔断规格句；陈旧 approve 用例与重新发起引导；勘误（彼稿版本引用 V0.6、§6.6 元注释、§10 F5 彼稿限定）。
> V0.4（2026-09-07，历史）：P5 复审收尾 + 裁决点落地（软删/同根/DELETE；见评审记录 §8）。

---

## 1. 背景与问题（现状勘察）

| # | 问题 | 事实 |
| :--- | :--- | :--- |
| P1 | 特权容器空转：`runner` 以 privileged + seccomp:unconfined 常驻，但 `worker.sandbox` 因安全评审未完成被 discover 排除，bash 在 agent 引擎实际不可达 | `docker-compose.yml`、`exec_policy.resolve_worker_visible` |
| P2 | 评审闭环缺失：被「安全评审」卡住（两轮版本仍挂未完成），无 DoD/无放行阶梯/无回滚判据 → 僵局 | AGENTS V1.7–V1.8 |
| P3 | 裁决规则三份碎片（前缀黑名单 / token 正则+词表 / runner 二次拦截），语义互有出入易漂移 | `sandbox_kernel.BASH_BLOCK_PREFIXES`、`dispatch.py`、runner |
| P4 | 无并发/配额控制（runner 无线程上限、api 无 bash 闸门） | `runner/main.py` |
| P5 | 逃逸面与收益失衡：bwrap 逃逸 = 容器 root = 宿主级风险；隔离正确性押在「评审正确性」而非最小权限结构 | `runner/Dockerfile` |
| P6 | 纵深顺序倒置：安全兜底押在「对模型输出做字符串静态分析」上，而非内核边界 | dispatch 裁决链 |
| P7 | 工作区无产品实体：工作区 = 平台按会话自动建的文件夹（用户不能命名/组织/跨会话复用），前端仅管理员清理视图，无创建端点、无归属概念 | `workspace.py`、`routers/workspaces.py`、`AdminWorkspaces.vue` |

**产品诉求（本轮评审方向）**：不再把「一个会话一个自动文件夹」当作唯一形态；用户可**新建多个工作区、工作区内新建文件夹**，沙箱隔离单元随之演进，且沙箱放行要形成可评审、可回滚的闭环。

## 2. 目标与非目标

### 2.1 目标
1. 工作区成为用户自管实体：多工作区、工作区内文件夹、属主与管理员分级管理；会话可按需绑定。
2. 默认行为不变：未绑定会话走 legacy 临时工作区（今日逐字节一致）；`sandbox_bash_mode=none` 默认 fail-closed。
3. 裁决层收敛：删除字符串词表碎片，准入语义改为「文件效果档位 + 审批升档」单一模型。
4. 沙箱放行闭环：档位化 + 灰度阶梯 + 明确 DoD（复用重设计稿 D6），与执行体降权（D1）、并发配额（D4）配套。

### 2.2 非目标
- 不注册宿主任意目录（服务端容器化部署，浏览器无宿主目录访问；工作区树 = 平台数据卷内受控树）。
- 不做跨用户工作区共享（初版仅属主 + 管理员）。
- 不引入全访问档位、微虚机/gVisor 等新隔离技术。
- 不新增 WS 事件 kind / 上行（红线按 §8/§9 纪律）；REST 增量（`/api/workspaces/*`、`SessionCreate` 字段）属 HTTP 契约增量，按 API.md 版本纪律经契约评审留档（MAJ-10）。

## 3. 设计总览

两个**正交**问题，分开设计与评审：

| 层面 | 问题 | 结构 |
| :--- | :--- | :--- |
| W 实体层 | 数据域归谁（用户建什么、目录长什么样） | `workspaces` 表 + `data/workspaces/<uuid>/` 目录树 |
| B 绑定层 | 会话在哪个数据域内运行（与 W 解耦） | `sessions.workspace_id` + `scope_path`，创建时固化 |
| E 执行层 | 命令在数据域内能做什么（文件效果档位） | `sandbox_bash_mode`（none/read-only/workspace-write）+ 逐调用策略 |
| A 管理面 | 用户/管理员怎么操作 W/B | 用户域 CRUD + 目录浏览；admin legacy/清理 |

关键洞察：**read/write/edit/bash 四类工具早已全部以注入的 `sandbox_dir` 为唯一文件根**（`dispatch._resolve_safe_path`、toolnode 默认注入）——换绑定单元与档位语义都不改工具层，侵入面小。

## 4. 工作区模型（W）

### 4.1 实体与目录

```
表：workspaces: id(uuid PK) | owner_id(FK users) | name | created_at | updated_at
                | deleted_at(可空)         ← V0.4（M-R3-5 裁决）：注销 = 软删标记
    sessions 增列: workspace_id(FK workspaces, 可空, ON DELETE RESTRICT)
                | scope_path(text, 可空)
目录：data/workspaces/<uuid>/          ← 平台 mkdir 创建（uuid 防穿越，沿用现有
    └── <folder>/…                        会话目录同款校验纪律）
    data/workspaces/<session_id>/…    ← legacy 临时工作区（存量/未绑定，语义不变）
```

- 目录 id 用 uuid 引用（路径可随卷迁移而不失效）；目录结构即事实，文件夹不建表。
- `name` 每属主唯一（纯 UX，可评审放宽）。
- **注销 = 软删（M-R3-5 裁决，V0.4）**：注销不 DELETE 行，仅置 `deleted_at`（行保留 → 会话 FK 引用不触发 RESTRICT；resolve 校验行态 → VALIDATION「工作区已注销」，fail-closed 成立）；`purge=true` 才真删行 + 删目录。`ON DELETE SET NULL` 明确否决（绑定静默清空 = 静默回落 legacy，违背 §5 fail-closed 承诺）。
- **purge 与行态（V0.4.1，M-R3-6 闭合）**：purge 事务内**先显式解绑全部引用**（行锁内 `UPDATE sessions SET workspace_id=NULL, scope_path=NULL WHERE workspace_id=<ws>` + AuditLog「workspace_unbind」——resolve 已因行态软删 fail-closed 在先，解绑无静默回落语义），再删行删目录；FK RESTRICT 仍作最后兜底（解绑遗漏即失败）。孤儿判定与删除守卫②**按行态区分**：仅 `deleted_at IS NULL` 活跃行受保护；软删工作区目录进入 legacy 清理面（§7.3，管理员可清理/导入）——避免「purge 与 orphan 双路径锁死」目录滞留。

### 4.2 生命周期与权限

| 操作 | 语义 |
| :--- | :--- |
| 创建 | 事务内建表 + `mkdir`（目录创建失败回滚）；属主 = 当前用户；写审计 |
| 改名 | per-owner 唯一校验；写审计 |
| 注销（DELETE） | **软删（V0.4 裁决）**：置 `deleted_at`，行与目录保留；绑定会话 resolve 报「工作区已注销」（§5）；目录入 legacy 清理面（§7.2/§7.3）。写审计 |
| purge（`DELETE ?purge=true`） | 真删行 + 删目录树；二次确认；事务内**先显式解绑全部引用（UPDATE + AuditLog）再删**（FK RESTRICT 兜底，V0.4.1）；仅管理员/属主（权限随 F1 定）；写审计 |
| 浏览/建文件夹 | 见 4.3；新建文件夹写审计 |
| 绑定会话 | 仅属主（及管理员）的会话可绑定；运行期 scope 不可变（§5） |
| 清理 | 管理员可清理 legacy/孤儿目录（孤儿守卫见 §7.3）；写审计（AuditLog 沿用） |

**删除守卫（B2 + MAJ-7 竞态闭合 + V0.4.1 行态区分）**：注销（软删）无文件风险；`purge`/管理员清理/孤儿删除（`delete_orphan`）前必须同时满足：① 目标工作区无**活跃绑定会话**（`sessions.workspace_id` 指向且会话未删除；purge 事务内显式解绑后自满足）；② 目标目录名不在**活跃（`deleted_at IS NULL`）** `workspaces.id` 集合内——软删行目录入 legacy 清理面（防孤儿误判连带 + 防双路径滞留，§7.3）；③ **竞态闭合与锁序**——删除端点先取 `workspaces` 行 `FOR UPDATE`、后取相关 `sessions` 行（**全局锁序：workspace 行 → sessions 行**；绑定固化路径与 purge 同序，approve/回执/TTL 扫描仅锁 sessions 单行不构成环），事务内删除动作前**二次集合复检**（快照后新提交的绑定/工作区同样命中拒绝）；④ 活跃回合判定注记：复用进程内回合租约（`_SESSION_TURNS`）为**单副本内存语义**（与 BLK-3/H5 批次 2 粘性路由绑定），多副本落地前仅覆盖本副本——F1 none 档内先行无碍，升级条件在 AGENTS/§10 G6 标注。审计：CRUD/purge/解绑/清理/建文件夹均写 AuditLog（R3）。

### 4.3 文件浏览 API（用户域，与 admin 域分离）

新增 `prefix=/api/workspaces`（鉴权：属主/管理员），**扫描与统计逻辑从 admin 路由抽公共 service 模块复用**（避免两份 os.walk 语义漂移）：

| verb | 用途 |
| :--- | :--- |
| `GET /api/workspaces` | 我的工作区列表（name/文件数/大小/最近活动） |
| `POST /api/workspaces {name}` | 新建工作区 |
| `PUT /api/workspaces/{id} {name}` | 改名 |
| `DELETE /api/workspaces/{id}?purge=` | 注销（默认保留文件，purge 二次确认删目录） |
| `GET /api/workspaces/{id}/files?path=rel` | 一层目录列表 + 父链（沿用 `_MAX_FILES` 纪律，path 规范化防穿越） |
| `POST /api/workspaces/{id}/files {path, name}` | 新建文件夹（单段名，拒 `.`/`..`/分隔符/符号链接逃逸） |

不引入文件上传/下载：文件由会话工具直接落盘产生，天然在工作区树内；前端文件浏览复用现有查看 modal 模式并**收敛为同一「一层 + 父链」目录进入式视图**（admin 会话文件页同步迁移，消除平铺/分层两种 UX 并存，M4）。

### 4.4 前端

- 「我的工作区」页（普通用户导航）：列表 + 新建/改名/注销 + 进入文件浏览 + 新建文件夹；工作区行显示占用与最近活动。
- 会话配置（适配草稿模式，MAJ-6）：前端「新建会话」现为本地草稿、首条消息发送时才落库（无创建对话框）。落地形态 = **会话设置面板**（会话列表/会话内入口）：**首条消息发送前**可配置「绑定工作区」（工作区下拉 + scope 相对路径输入，默认根）、bash 档位（默认 read-only，可授予 workspace-write）与「绑定即授权本会话读写该 scope」提示；首条发送落库后绑定/档位**固化不可变**，会话内只读展示。草稿阶段未配置 = legacy 临时工作区（行为不变）。
- 管理员页保留并叠加 owner 列（legacy 清理、全量视图）；**绑定会话无自有目录**——admin「会话文件」按钮对该类会话跳转其工作区浏览（MIN-12）。

## 5. 会话绑定（B）

- **固化语义（草稿适配）**：会话绑定在**首条消息发送落库时固化**（前端草稿模式下无创建请求，见 §4.4）；`SessionCreate` 增量字段 `workspace_id` + `scope_path`（可空）；缺省 = legacy 临时工作区（现有 `ensure_session_workspace` 兜底，行为零变化）。绑定写入会话行后**运行期不可变**（换绑 = 新建会话，§12-5）。
- **唯一解析入口**：`resolve_session_sandbox(session) -> 绝对路径（realpath 规范化后，供 bind）`，校验链：属主匹配 → 工作区行存在且 `deleted_at` 为空（**行态校验，软删即失效**，V0.4）→ 目录存在 → `realpath` 逐段解析后仍位于 `workspaces` 根前缀内（**符号链接逃逸拒绝**）→ 拒 `.`/`..` 段。
- **绑定失效与续用（MAJ-1 闭合，V0.4.1 复活路径）**：工作区软删后 → VALIDATION fail-closed（不回落裸目录），数据保留于目录；**「legacy 导入」= 复活软删行（清 `deleted_at`，F3 交付，§7.2）——原 uuid/原名恢复后，仍存续的旧绑定会话（行在）自动恢复 resolve 通过，真正「续用」**；purge/目录缺失 → 数据已删，仅引导重建。会话保持可对话，工具文件操作报错按上述路径之一引导。
- **共享并发模型（BLK-1 定稿）**：属主**本人**的多会话可绑定同一 scope（共享写、自担并发）；跨用户共享写禁止。「活跃会话独占」作为可选开关按需增补（不默认）。F3 起**绑定会话强制 private**：禁止 `visibility=team` 会话绑定工作区；已绑定会话拒绝经 sharing 更新转 team（BLK-4——防其他成员经 team 会话驱动写或自批升档）。
- **runner 复核（MAJ-5/MAJ-9③）**：runner 解析 `policy.workspace_root` 后执行同一套前缀 + realpath 校验（替换 `is_valid_session_workspace` 的「root 直接子目录」限制，接受嵌套 scope），并 **bind realpath 解析后的最终路径**（非入参原串，防 resolve→bind 窗口符号链接换链）；runner 不信任 api 传参。
- **升档审批主体 = 工作区属主/会话创建者**（绑定强制 private 后二者合一）：approve 校验卡 owner 维度（实现 = 卡 author，`assert_confirm_owner` 现有校验点），非属主成员 → 拒绝（WS `unauthorized` 错误事件；REST 绑定面才用 HTTP 403，M-R3-3）；审批动作落 AuditLog（§8.2）。

## 6. 沙箱执行策略（E）

### 6.1 文件效果档位

| 档位 `settings.sandbox_bash_mode` | 文件效果（沙箱内） | 默认/触发 | 覆盖原 |
| :--- | :--- | :--- | :--- |
| `none` | bash fail-closed（`worker.sandbox` 不 discover） | **部署默认** | off |
| `read-only` | scope/宿主不可写（持久 bind 只读）；沙箱内 `/tmp`、`/run`、`/dev` 为可写 tmpfs（易失，HOME=/tmp） | 会话默认档（放行后） | workfile（更强） |
| `workspace-write` | 绑定 scope 可写 + 沙箱内临时区可写 | 会话档位授予（首条前）/ 拒写升档按次（§6.4） | mutating |

**语义要点**：档位只声明**持久文件效果**——read-only 下沙箱临时区（`/tmp`/`/run`/`/dev`）仍可写（shell 管道/heredoc/临时文件），对宿主持久数据零写入（MIN-4/R3-S1 口径）；网络隔离（`--unshare-net`）、进程/资源边界由 bwrap 结构承担且**恒开启**，与档位正交。

### 6.1.1 绑定授权与工具层关系（M1 修订）

- **写授权主体 = 绑定**：绑定工作区的会话 = 用户显式授权该会话读写该 scope。文件工具（`write_file`/`edit`）受参数 schema + scope 路径前缀约束（单文件写入/差异编辑），属受控接口，在该授权下免逐次审批（与现状一致，语义不变）。**绑定会话强制 private（§5），写授权不随 team 可见性向其他成员开放（BLK-4）。**
- **bash 档位只约束 bash**：bash 是任意程序执行面（rm/mv/管道/循环/任意路径），故单独以档位 + 升档审批约束。「read-only」档的只读口径指 **bash 只读**——绑定会话内文件工具仍可写，二者不矛盾：工具受接口约束、bash 受内核约束；UI 文案与提示按此口径表述。
- 若产品需要「文件工具也严格只读」的会话（如只读回放/评审），列为后续评审（文件工具档位化），本版不承诺。
- 未绑定 legacy 会话：文件工具写各自临时目录（现状不变）；bash 档位由部署默认（none → 放行后 read-only）。

### 6.2 逐调用策略与 runner 接口

- 新增单一解析函数 `resolve_bash_policy(session, approved)` → `{mode, workspace_root}`；工具层每次 bash 调用经此解析（会话档位 > 部署默认；审批升档仅当次）。
- runner `/run` 请求体改为携带 `{command, policy{mode, workspace_root}, timeout_s, limits, max_output_chars}`：runner **按 mode 组装 bind**（read-only → scope `--ro-bind`；workspace-write → `--bind`），**不再接收任何词表/黑白名单字段**；api 客户端 `sandbox.py` payload 同步改造。
- **runner 校验替换（MAJ-5，F2/F3 显式工作项）**：runner 内 `is_valid_session_workspace`（仅收 root 直接子目录 + UUID 全匹配）替换为 policy 前缀 + realpath 逐段校验——接受嵌套 scope（`{root}/<ws_uuid>/<folder>/…`），拒符号链接逃逸，**bind realpath 后最终路径**（MAJ-9③）。**接口兼容与混布（双向 fail-closed，R1-5/R2-P2-4）**：api/runner 要求同版发布；① 新 api + 旧 runner → 旧 runner 不识别 `policy`（且新 api 不再发送 `sandbox_dir` 键）→ 路径校验失败 VALIDATION，不静默降级（runner 集成断言：policy-only 载荷 → VALIDATION）；② 新 runner + 旧 api → 请求缺 `mode`/`policy` → runner **默认拒绝**（fail-closed，不按 read-only 猜测）。回滚顺序见 §10（先回 runner 镜像 tag）。
- `sandbox_dir` 概念并入 `policy.workspace_root`；read/write/edit 工具仍以同一 scope 为根（与 bash 共用数据域，权限天然一致）。改名/语义迁移影响面（F2 DoD 机械清单，R1）：toolnode 默认注入、registry `_read/_write/_edit/_bash` handler、dispatch `_resolve_safe_path` 调用点、context/mcp provider 取值——落地时保留 `sandbox_dir` 兼容别名以降低回归面。

### 6.3 删除字符串词表的理由

四处碎片（P3；评审 BLK-2 补全第四处）全部删除，准入不再对命令文本做静态分析：

1. **删除对象清单**：① `feedback/rules.py` 的 `BASH_BLOCK_PREFIXES` + `check_gates` 内联 bash 门禁分支（**toolnode 每次 bash 调用先过 gate**，早于 block/approval 判定）及其单测（`test_harness_feedback.py` 门禁用例）；② `sandbox_kernel.BASH_BLOCK_PREFIXES`（连同其误导性注释「批准后必须放行、runner 不得硬拒」——与 runner 现状无条件硬拒矛盾，一并修正）；③ `dispatch.py` 词表/正则（`bash_block_reason`/`bash_approval_reason` 静态词表路径）；④ runner `check_bash_blocklist` 调用。四处实现语义不等价（前缀 startswith vs 段切分正则；runner 拒集 ⊂ dispatch 拒集）——单一化等价性矩阵需补「前缀 vs 段切分」差异样例（如 `bash -c 'curl …'`），避免行为回退。
2. **物理边界已覆盖其目标（B1：前置为 D1/S3 降权后的目标形态）**：`curl/wget/ssh/nc/scp`（`--unshare-net` 无网络，与降权无关、即时成立）、`rm/chmod/chown`（宿主目录只读 bind，破坏只限于沙箱视图且 `--tmpfs` 遮蔽敏感路径）、`sudo`（沙箱内非 root 无特权放大——**现状沙箱内为 userns root（`_build_bwrap_argv` 未设 `--uid/--gid`），该项仅在 S3 落地后成立**）。**过渡期（S3 前）**：`sudo` 前缀拦截保留为唯一残余词表项，**落点 = api 裁决层 `bash_block_reason` 仅保留 sudo 前缀一条**（其余词表与 gate 分支全删）；S3 合入后连同残余项一并删除（联动 §10 F2 依赖）。
   > **G4（F2）落地改述（V0.5，2026-09-07）**：S3（G2）已合入部署，四处词表（含 sudo 残余项）按 §6.3 全删。依据按 G2 PoC 定稿形态改述（见 B 稿 D1 勘误块）：沙箱内 userns root 的宿主视角 = 容器 root，容器 cap 窄化（默认 caps + SYS_ADMIN）与 no-new-privileges 下 `sudo`/setuid 均无容器/宿主级特权放大——原「沙箱内非 root」目标形态已被 PoC 否决（非 root USER 下 `--cap-add` 不生效），删除判定改为按上述定稿形态成立，残余风险表与 §11 演练 4 口径同步（B 稿 V0.6.1）。
3. **词表层不可靠且是漂移源（P6）**：字符串匹配既不完整（同义变体/拼接绕过/`bash -c` 嵌套）又难以维护（四处语义互有出入）。
4. **破坏性操作准入改述（BLK-5）**：准入 = **档位授予（首条前一次性决策）+ 拒写升档审批（按次人工）** 两层——不再声称「档内破坏命令由审批把关」：`workspace-write` 会话内针对 scope 的破坏命令直接执行，风险由「授予决策 + 绑定会话 private + 属主自担 + 审计」承担（§11）；`read-only` 下内核拒写 + 升档卡为唯一写入口。UX 兜底（无网络工具白等超时）由工具 schema 说明与结果文案提示承担。

### 6.4 审批 = 拒写升档放行（B3 闭环定稿；复用 `tool_approval` 协议框架，语义修订经 §8.2 契约组成组留档）

- **会话档位授予**：创建会话时属主选择档位——绑定工作区的会话可授予 `workspace-write`（绑定 = 显式写授权，见 6.1.1）；其余会话 bash 默认 `read-only`（none 为部署默认，放行阶梯见 §10）。
- **升档触发（read-only 会话，事件源已定义）**：bash 写 scope 被内核拒写（EROFS）→ `tool_result` 附 denied 标记与升档提示（§6.5）→ **ToolNode 自动 interrupt 生成升档卡**（复用 `tool_approval` 协议与 H5 resume 链路；卡 payload 含原命令 + `reason=escalation` + 目标档位）。静态判定（`bash_approval_reason` 词表路径）删除后，卡仍可达。
- **放行语义**：approve → `pending_confirm` 行锁清卡（一次性 `resume_nonce` 消费即失效）→ 以原 `thread_id` 的 `Command(resume=...)` 恢复 ToolNode，**同一命令以 `workspace-write` 重放一次**（resume 至多一次语义天然匹配，不会重复审批/重复放行）；reject → 清卡，回合按失败观察续跑，不重放。
- **粒度**：升档按次（单命令单卡），会话档位不变；频繁写场景应首条前即授予写档（审批疲劳缓解）。`dispatch` 不再做逐命令静态裁决；词表与 gate 分支删除后 `bash_block_reason` 仅余 sudo 残余项（§6.3）。
- **审批主体（BLK-4）**：升档卡 owner = 工作区属主/会话创建者（绑定会话 private 后二者合一）；实现维度 = 卡 `author`（`pending_confirm_author_id`，现有校验点 `assert_confirm_owner`），非属主成员 approve → 拒绝（WS `unauthorized` 错误事件；REST 绑定面才用 HTTP 403——措辞统一，M-R3-3）；approve/reject 落 AuditLog（action/user_id/workspace_id/call_id/thread_id，§8.2）。
- **TTL 与终态（MIN-8）**：升档卡受 `agent_approval_ttl_seconds`（默认 3600s）约束，过期 → `approval_terminal=expired`（V1.73 语义）不重放（fail-closed）；UI 卡倒计时为新增项（现 ApprovalCard 无倒计时，入契约组，R2-P3-6）。
- **多 tool_result（MAJ-9②，V0.4 收敛）**：同一 call_id 可产生 N 条持久 tool_result（denied 失败 → approve 重放 → 成功；重放再拒写再出卡可更多）——前端 ToolCard 按 call_id **按事件序收敛于最后一条**（现实现天然末写覆盖），历史回放/REST 快照同为 event_id 线性序；§9 补 N=3 用例。
- **重放再失败（MIN-16）**：approve 后重放若失败（非拒写）→ 正常失败观察、回合收尾；再次拒写 → 重新出卡；resume 一次性不复活。
- 与 `confirm`（W5 任务确认）/ `clarify` 三类卡互斥语义不变（共用 `pending_confirm` 单行）。

**跨重启语义（BLK-3，V0.3 修订 + V0.4 检测点 + V0.4.1 清卡修正）**：升档卡恢复依赖图检查点（`Command(resume=...)` 按 `thread_id` 取检查点）。**F5/G5 放行硬前置 = H5 批次 2 完成**（PG checkpointer 生产切换 + 网关粘性路由 + 重启恢复演练通过；见 §10 G6 与评审记录 BLK-3）。此前按**单副本内存语义**交付：api 进程重启或检查点容量淘汰导致恢复失败时**不得静默**。**检测点（M-R3-1 + V0.4.1 M-R3-7 修正）**：approve 在 `pending_confirm` 行锁内**预检检查点存在性**——缺失则**行锁内清卡**（清卡与终态广播同事务，对齐 expired 先例：先清后广播），再落 `voided` 终态 + `error` + AuditLog（事件终态即行态清算；**不清卡将导致卡残留占 `pending_confirm` → 新卡不可落、会话不可软删、只能 /stop 逃生且产生双终态**——否决）；**事件序：终态先发、error 后发**（对齐 expired 现有序）。作废后用户重新发起升档链路 = 新回合重发命令 → 试跑拒写 → 新卡，error 文案含引导。作废终态的 `approval_terminal` outcome 值（新增 `voided`/`recovery_failed`，区别于 expired/cancelled——前端现对未知 outcome no-op，必须成组扩展）入 §8.2 契约组与 API.md V1.75；clarify/confirm 恢复失败是否同样「不静默」（三类卡共用 `_start_card_resume` 同一只记日志路径）**在 F5 契约组首项产出明确结论**（委办设限）。

### 6.5 失败事实与归因

- **拒写事实结构化注入（MAJ-9①）**：denied 由 runner 按 mode 结构化返回（`/run` 响应契约字段 `sandbox:{mode, denied}`，**非 stderr 特征文本匹配**——与删词表层立场一致；EROFS 特征仅作旧 runner 兜底日志）→ `tool_result` 附 `[sandbox: file access denied under read-only mode]`，且 ToolNode 随即自动出升档卡（§6.4，无需模型显式请求）；reject 后回合内模型可见失败观察。none 档（bash 不可达）下不存在拒写路径，无标记无卡。
- **runner 引擎故障与命令失败分开归因**：现有三码（TIMEOUT/VALIDATION/INTERNAL）与「沙箱引擎不可用」fail-closed 文案已闭环，保留不变；`probe` 保留 enforcement 上报字段（当前唯一后端 bwrap 恒 full，字段为将来多后端预留）。

### 6.6 磁盘配额与容量（MAJ-8，D6 硬门槛成员）

`workspace-write` 常态化后，绑定会话可在共享 data 卷无限写 → 平台级 DoS 面（现有限制仅内存/进程/CPU/墙钟）。承诺：

- 每工作区配额（config `workspace_quota_bytes`，默认 1GiB）：写入路径（resolve 或用户域 service）写前用量检查，超限 → 单命令失败/档位拒写（明确文案）；周期扫描容量告警（agent_trace/日志）；admin 页展示占用率。**实现事实声明**：数据卷无内核级目录配额（非 xfs prjquota 部署）时，配额为**软上限**（写前检查 + 记账/`du` 缓存，避免每写全量 walk）——文件工具直写路径（api 侧 `write_file_safe`/`edit_file_safe`，`_resolve_safe_path` 之后统一挂检查）与 bash 写路径共用同一检查函数。
- **卷级水位熔断（M-R3-4，V0.4 + V0.4.1 规格句）**：写前检查无法拦截单命令洪水（如 `dd`/循环写一次填满卷）——补共享卷水位熔断：剩余空间 < 阈值（如 512MiB，config `sandbox_volume_watermark_bytes`）→ `workspace-write` 档整体拒写（fail-closed，明确文案与告警）。**实现规格**：① 熔断判定**优先于**每工作区配额判定（全局最后防线）；② 只挂写路径（workspace-write 写检查与文件工具直写检查），**不触碰 read-only 试跑、读工具与 none 档**（逻辑天然如此，明文保证）；③ 已授予写档会话的直接失败文案示例：「沙箱卷空间不足（水位熔断），请稍后重试或联系管理员」。演练 5.1 判据改为「水位熔断触发、同机服务不拖垮」，单命令洪水为有界残余（上限 = 卷水位）。
- 配额验证入 D6 硬门槛（灰度期验证拒绝路径）+ 压测与红队「沙箱写满数据卷」用例（彼稿 §11 演练 5.1）。

## 7. 迁移与兼容

### 7.1 legacy 临时工作区
存量会话无 `workspace_id` → legacy：目录路径与解析规则不变，行为与今日一致，零迁移（目录拓扑口径与《重设计》V0.6 §3.1 统一（自 V0.5 起）：持久目录 = `data/workspaces/<session_id>`，沙箱内 `/work` 即该目录的挂载点，**无中间子层**——MAJ-3）。

### 7.2 legacy 目录导入 = 复活路径（MAJ-1，V0.4.1 M-R3-6 定稿，F3 交付）
管理页/属主页对 legacy 目录（含已注销工作区遗留目录）提供「导入」：**首选复活**——目录名 = 旧行 uuid（§4.1），恢复软删行（清 `deleted_at`，可选改名；同 owner name 唯一时软删行占名不构成冲突——复活为原行），**不移动文件**；仍存续的旧绑定会话（行在）自动恢复 resolve 通过（§5 续用真闭环）。**新建**仅用于全新目录（新 uuid + 新行）。复活/新建均写审计；孤儿清单与导入共用同一目录清单视图（§7.3）。

### 7.3 legacy 目录管理与孤儿守卫（B2/MAJ-7 + V0.4.1 行态区分）
管理端 orphan 清单/清理**转正为 legacy 目录管理**（覆盖：无主 orphan + **软删工作区遗留目录**）；admin 页工作区行显示 owner 与行态（活跃/已注销）。**孤儿判定**：目录名 ∉ 全会话 id ∪ **活跃（`deleted_at IS NULL`）** `workspaces.id`（现状仅排除会话 id——工作区 uuid 目录必被误判 orphan 且 `delete_orphan` 可删，属高危；软删行目录因无行态保护入清理面，防双路径滞留）；`delete_orphan` 对活跃 `workspaces.id` 内目录拒绝并执行删除竞态守卫（行锁 + 二次复检 + 活跃回合判定，§4.2 删除守卫段）；admin orphan 区新增「活跃工作区」计数与跳转。备选结构方案（目录独立子树物理分流）见 §12 待决点 6（已裁决采纳同根，备选仅存档）。

### 7.4 隔离口径
前端「会话间互不可见」说明条与 API.md 口径改为：**legacy 会话互不可见；绑定会话的隔离单元是工作区**（文档化修订，非协议变更）。

## 8. 契约与红线影响

1. **WS 零变化口径（MAJ-10）**：不新增 WS 事件 kind / 上行（红线 §9 适用）；REST 增量属 HTTP 契约增量——`/api/workspaces/*` 新端点、`SessionCreate` 增量字段（`workspace_id`/`scope_path`）与 sharing 守卫（绑定会话禁转 team）按 API.md 版本纪律经契约评审留档（**「零变化」不覆盖 REST**，MAJ-10/R3-S7）。
2. **契约组清单（BLK-5/R2 + V0.4 扩展 M-R3-1/2/3，F5 PR 时成组执行）**：
   ① `tool_approval` 卡语义修订为「拒写升档放行」（§6.4）——改写落点为 **API.md §4.3 `tool_approval` 行 + §4.3.1 bash 行**（§9 红线表无此句，引用修正）：「确认前不调用 Runner」段按「read-only 试跑 → 拒写 → 卡 → 放行重放」改写；+ 前端 ApprovalCard 文案/行为对照表 + 双执行（失败/成功）可见性 UI 验收 + **ApprovalCard 倒计时新增项**；
   ② 卡 schema 白名单**先扩再断言**——精确表述：`reason` **键已在** allowed（`{id,call_id,name,command,reason,risk_level,sandbox_scope}`，ws.py 实据）；`reason` 由 toolnode 改产 `escalation` 是**值变**不需扩键；真正会被剥离的是**目标档位等新键**（须先扩白名单）；`meta.schema_version` 升版评估（三类卡消费端不读数字分支则零影响）；
   ③ `approval_terminal` outcome 扩展（M-R3-1 + V0.4.1 M-R3-7）：新增 `voided`/`recovery_failed`（区分 expired/cancelled 的「卡未消费即终态」语义，事件序为「已 approved → 作废」）——值枚举、事件序（**行锁内清卡与终态同事务、终态先 error 后**，对齐 expired 先例；否决「不清卡作废」——卡残留将阻塞新卡与会话软删并产生双终态）、前端 `approvalDone` 分支（现对未知 outcome no-op，须成组扩展）、回放断言，全部入 API.md V1.75；`_start_card_resume` 恢复失败现仅记日志——「行锁内预检 + 清卡 + voided 终态」为 F5 新代码（§6.4）；clarify/confirm 恢复失败是否一并「不静默」（三类卡共用同一只记日志路径）在 F5 契约组首项产出明确结论；
   ④ `tool_result` 结构化字段（M-R3-2①）：denied 以 `data.sandbox:{mode, denied}` 结构化落 `tool_result` payload（不止 runner `/run` 契约），前端/回放/审计按字段区分「拒写可升档」与真错误——避免重蹈文案特征判定；前端 ToolCard 未知字段兼容断言；
   ⑤ **`tool_approval` 词汇表注册显式修复**（M-R3-2② + V0.4.1 成组）：现状 `event_vocab.py` `NODE_EVENT_KINDS`/`_EMITTER_ONLY_KINDS` 均不含 `tool_approval`（卡事件经 ws.py interrupt 直产并持久化回放，漂移有运行时后果：转发护栏按 unknown 跳过补发行）——F5 前补注册；**归类成组**：与同构 `clarify`（同为图 interrupt 直产、api 侧落库广播，现归 `NODE_EVENT_KINDS`）统一归类并更新 event_vocab 注释的直产清单（覆盖 interrupt 直产面）；**判定登记**：属漏登补录（非增删 kind，API.md §4.3 自 V1.70 已列、生产已有存量行）→ **不触发 event 版本递增**，判定理由写入 API.md V1.75 修订记录；**回归锁**：`test_event_vocab.py` 注册表断言补 `tool_approval`/`approval_terminal`（现缺——本次漂移未被 CI 拦截的直接原因）；API.md §4.3 直产事件枚举句（漏列 tool_approval）同步修正；
   ⑥ API.md 升 V1.75 留档——**版本行内容清单（V0.4.1）**：WS 语义修订（§4.3 `tool_approval` 行 + §4.3.1 bash 行 + §4.3 事件枚举句）+ REST 增量（API.md §3：用户域工作区端点、`SessionCreate` 字段、sharing 守卫）+ outcome 枚举（③）+ `tool_result` 结构化字段（④）+ 词汇表补录判定句（⑤）+ 顺带校正现存文档-实现漂移（`allowed_decisions` 在 API.md §4.3 payload 列但被 `_persist_pending_approval` 白名单剥离；`_persist_pending_approval` docstring 白名单漏 `sandbox_scope`）；升档 approve/reject 落 AuditLog（action/user_id/workspace_id/call_id/thread_id）；AGENTS 状态地图同步（档位/绑定/守卫/配额）。
3. bash 可达性与 discover：以 `settings.sandbox_bash_mode != none` 为前提（默认 none，fail-closed 不变）；放行阶梯与 DoD 沿用《重设计》V0.6 D6（**7 项硬门槛** = D6-1~7（含磁盘配额验证）；workspace-write 档另加 **H5 批次 2 完成**为硬前置，见彼稿 D6 段）。
4. 词汇表纪律（事件版本化）：本设计不新增 kind；`tool_approval` 注册漂移修复见本组⑤（F5 契约组显式执行，不再「顺带」）。**payload 纪律句（V0.4.1，S-4）**：kind 不变、payload 值域/结构变更（如 outcome 扩展）→ **不升 event 版本**，须 API.md 修订行 + §4.3 表行 + 消费端成组三者同步留档——拟写入 event_vocab docstring 成文（随⑤补注册同 PR）。

## 9. 测试、演练与放行 DoD

- 复用：彼稿 D6 放行 DoD、彼稿 §10 测试矩阵（含并发压测）、彼稿 §11 红队演练（3/3.1 跨工作区与符号链接、3.2 换链、5.1 写满卷）；**回归基线显式化（R1-7）**：api 854（AGENTS V1.8）/worker 50 passed/前端 typecheck+build。
- 工作区专项（F1/F3 单测与集成）：
  - `resolve_session_sandbox`：绑定/缺省/无权限/注销后失效等分支；scope 规范化 + 符号链接逃逸 + 前缀越权（api 与 runner 双侧）；`.`/`..` 段拒绝；
  - 目录浏览 API：`path` 穿越/超层/不存在；新建文件夹单段名校验；文件数上限纪律；
  - 共享绑定：属主多会话同 scope 集成用例；跨用户绑定 403；**team 会话绑定拒绝 / 已绑定会话转 team 拒绝（BLK-4 回归锁）**；
  - legacy：存量会话解析回归（行为零变化断言）；legacy 导入（§7.2）挂接后会话可继续绑定；
  - **runner 侧（MAJ-5/MAJ-9③）**：嵌套 scope（`{root}/<ws_uuid>/<folder>`）bind 通过；符号链接换链（resolve→bind 窗口替换链接指向卷外）→ 拒绝（bind realpath 后路径）；
  - **删除竞态（MAJ-7）**：删除 × 并发绑定、删除 × 活跃回合并发 → 拒绝且不误删。
- 升档闭环（F5 集成，B3 回归锁）：拒写（结构化 denied）→ 自动升档卡 → approve → 同命令以 workspace-write 重放**恰好一次**（resume 至多一次断言）；reject → 不重放、回合续跑；**N 条 tool_result 按 call_id 事件序收敛于最后一条（MAJ-9②，含 N=3 用例）**；**TTL 过期 → expired 终态不重放（MIN-8）**；**重启/容量淘汰恢复失败 → 清卡前预检 → error + 卡作废终态（BLK-3/M-R3-1，终态先 error 后的事件序断言 + 前端 approvalDone 新分支）**；重放再失败 → 失败观察收尾（MIN-16）；卡互斥回归（与 confirm/tool_approval/clarify 共用 `pending_confirm` 单行）；**非属主 approve → 拒绝（unauthorized 错误事件）（BLK-4/M-R3-3）**。
- 孤儿守卫与生命周期（F1 回归锁，B2/R4 + V0.4.1 行态）：**活跃**工作区目录不被判 orphan；`delete_orphan` 拒绝活跃 `workspaces.id` 内目录；**软删工作区目录入清理面（可清理/可复活）**；复活（清 deleted_at）后旧绑定会话 resolve 恢复（§7.2 回归）；purge 事务内显式解绑（AuditLog `workspace_unbind`）后删行删目录成功、FK RESTRICT 兜底无泄漏。
- **陈旧 approval_id（V0.4.1，S-5 回归锁）**：迟到 approve（旧 approval_id）→ 行锁内校验拒绝且**不误清新卡**（服务端防线已存在：行锁 + 卡存在性 + `card.id == approval_id` 强匹配）；前端 approve 即置 disabled 防重复。

### 9.1 灰度放行量化判据（MAJ-2，入 F4/F5 与《重设计》D6）

| 指标 | F4（read-only 灰度 7 天）通过阈值 | F5（workspace-write）加项 |
| :--- | :--- | :--- |
| 安全/逃逸告警（彼稿 §11 演练 + 运行日志） | 0 | 0 |
| runner 引擎故障（INTERNAL/不可用） | 0 | 0 |
| bash tool_result 失败率（含 denied） | ≤ 放行前基线 +5pp 且不单调上升 | 同左 |
| 升档卡静默丢失 / 恢复失败无终态 | — | 0（BLK-3 审计终态生效） |
| 磁盘配额触发误伤（非写满场景被拒） | — | 0 |
| 用户投诉 / 回滚请求 | 0 | 0 |

## 10. 分期实施（每步独立 PR，可回滚）

| 阶段 | 内容 | 依赖 | 说明 |
| :--- | :--- | :--- | :--- |
| F1 | `workspaces` 表 + 用户域 CRUD/目录浏览/建文件夹（抽公共扫描 service + 孤儿守卫 + 删除竞态）+ 前端「我的工作区」页 | 无 | **none 档内先行**：纯文件管理，会话未绑定也可用 |
| F2 | `resolve_bash_policy` + runner bind mode 化 + **runner 校验替换**（§6.2）+ 删四处词表（含 gate 分支，§6.3） | **G2（S3 降权先行或同批）**；S3 前 `bash_block_reason` 仅余 sudo 残余项 | 纯重构，none 默认下无行为变化（先行回归） |
| F3 | 会话绑定接线：首条固化 + `resolve_session_sandbox` + private 强制/sharing 守卫 + 会话配置 UI（§4.4）+ legacy 导入（§7.2）+ 口径修订 | F1（数据面可在 G4 前并行开发；合入依赖 G4 runner 校验面） | — |
| F4 | `read-only` 档灰度（内部会话 7 天） | F2+F3+G2 | 放行判据见 §9.1；DoD 沿用 D6 |
| F5 | `workspace-write` 档 + 升档审批（§6.4）+ 契约组（§8.2）+ 磁盘配额与水位熔断验证（§6.6） | F4 稳定 7 天（§9.1）+ **G2 + H5 批次 2 完成（BLK-3）** | 配额/演练见 §9/彼稿 §11 |

**组合路线图（与《重设计》V0.6 对齐，M2 重排；S1/D3 的 `bash_verdict` 单一化取消——由 F2 词表全删彻底取代）**：

| 里程碑 | 内容 | 组成 |
| :--- | :--- | :--- |
| G1 | 工作区实体与管理面 | F1（无外部依赖，先行） |
| G2 | runner 降权 + seccomp（D1）+ 空转观察 7 天 | 重设计 S3（F2/F4/F5 硬前置） |
| G3 | 并发配额（D4） | 重设计 S2（与 G2 可并行） |
| G4 | 策略化重构：policy 解析 + bind mode 化 + runner 校验替换 + 删四处词表 | F2（依赖 G2） |
| G5 | 会话绑定 + read-only 档灰度 | F3 + F4（依赖 G4；F3 数据面可并行开发） |
| G6 | workspace-write 档 + 升档审批 + 契约组 | F5（依赖 G5 稳定 + G2 + H5 批次 2 完成 + D6） |

回滚：任何一步异常 → `settings.sandbox_bash_mode=none` 恢复 fail-closed（一行 .env）；G2/G3 回滚 = 部署前一镜像 tag（deploy.sh 按 tag 支持）；**接口混布回滚 = 先回 runner 镜像 tag 再回 api（§6.2）**；F1/F3 数据面回滚 = 停用绑定开关（会话回落 legacy），表/列保留兼容。

## 11. 风险

| 风险 | 缓解 |
| :--- | :--- |
| 属主多会话共享 scope 互相覆盖（F3/F5） | 共享仅属主本人（自担，BLK-1 定稿）；绑定会话 private；需要时增补「活跃会话独占」可选开关 |
| 符号链接逃逸 / resolve→bind 窗口换链 | realpath 逐段前缀重验 + **bind realpath 后最终路径**（api + runner 双侧）+ 演练 3.1/换链用例 |
| 误删工作区目录 / 孤儿误判连带删除 | 注销默认不删文件；purge/清理删除竞态守卫（行锁 + 二次复检 + 活跃回合判定，§4.2/§7.3）；仅属主/管理员；审计留痕 |
| 档内破坏命令误执行（workspace-write 授予后无逐命令把关） | 准入 = 授予（一次性）+ 拒写升档（按次）两层（BLK-5）；授予决策 UI 明示风险 + 绑定 private + 审计 |
| team 会话横向越权（成员借绑定会话写/自批） | 绑定强制 private + sharing 守卫 + 审批主体 = 属主（BLK-4，§5/§6.4） |
| 升档卡跨重启静默丢失 | F5 硬前置 H5 批次 2（PG checkpointer + 演练）；此前单副本语义 + error/卡作废审计终态（BLK-3，§6.4） |
| 磁盘写满共享卷（workspace-write 常态化 DoS） | 每工作区配额 + 写前检查 + 周期告警（§6.6）；入 D6 与压测/演练 |
| 审批疲劳 / 误批 | 首条前授予档位减少打扰；卡展示命令原文 + 属主身份校验；TTL 倒计时 |
| 档位误配（直接开 workspace-write） | DoD 硬门槛 + 灰度判据（§9.1）；config 注释与 AGENTS 状态地图留档 |
| 无网络工具白等（词表删除后） | 工具 schema 明示「沙箱内无网络」；结果文案提示；超时上限既有 |

## 12. 评审待决点

1. ~~共享并发模型~~ **已定稿（BLK-1）**：属主本人多会话共享允许（自担并发）；跨用户共享写禁止（绑定强制 private）。「活跃会话独占」可选开关不默认，按需增补。
2. ~~审批接线~~ **已定稿**：会话档位制 + 拒写升档（§6.4，V0.2 起确认）；逐命令审批参照物已随彼稿 V0.6 D5 取代标注消失（R1-2 关闭）。
3. `name` per-owner 唯一 vs 允许重复（纯 UX；F1 PR 前定即可）。
4. ~~DELETE 语义~~ **部分定稿**：注销 = 软删已定（V0.4，M-R3-5 裁决）；剩余开放 = purge 触发权限（是否下放属主「清空/真删」或仅管理员）——随 F1 一并定稿（正文当前语义 = purge 需二次确认 + 守卫有效）。
5. 运行中「换绑」会话是否需要（初版 = 新建会话；后续单独排期）。
6. ~~工作区目录布局~~ **已裁决（V0.4）：采纳同根共存 + 孤儿守卫**（§7.3 守卫与 §9 用例即为定稿依据）；若未来改独立子树分流，需新评审并出返工清单（§4.1/§7.3/§9/F1/admin 视图连带）。
7. **文件夹层级/命名规则（承接彼稿附录 B-6，R1-3）**：`scope_path` 允许深度/字符集/层级上限？是否开放文件夹改名/移动（初版建议：仅创建 + 删除 + 改名，移动留后续）？——F3 实现前须定，正文无需返工。
8. **附件 staging 归属（G5/F3 落地登记，开放）**：绑定会话的附件仍落 legacy `{root}/{session_id}/attachments/`（与工作区 scope 分离，模型 read 工具不可见）；是否迁移附件落点（工作区树内 `attachments/` 或 scope 内）+ 存量附件迁移策略——随 F4 评审或独立小项排期，正文引用与 API.md V1.76 已标注。
