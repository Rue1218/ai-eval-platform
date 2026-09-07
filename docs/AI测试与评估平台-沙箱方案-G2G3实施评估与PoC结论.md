# AI 测试与评估平台 — G2/G3 实施评估与 PoC 结论

> 版本:V0.1 | 日期:2026-09-07 | 状态:评估结论（G2 形态修订待落地；G3 可并行实施）
> 关联：B《沙箱执行方案重设计》V0.6（D1=S3、D4=S2）；A《工作区与沙箱设计方案》V0.4.1（组合路线图 G2/G3 → G4）
> PoC 环境：生产服务器 `47.119.132.83`（Docker 26.1.3，项目 `/opt/ai-eval-platform`，runner 镜像 `ghcr.io/rue1218/ai-eval-platform-runner:e5087e3`）——仅以一次性 `docker run` 实验容器验证，**未触碰生产容器**。

## 1. G2（runner 降权）PoC 矩阵

bwrap 冒烟口径：`probe` = `--unshare-user --ro-bind / /`；`run` = 全参数（unshare-user/pid/net/ipc/uts + ro-bind 系统目录 + `--proc/--dev/--tmpfs` + bind scope → `/work` + bash 写测）。

| 阶段 | 容器形态 | probe | run | 关键错误 |
| :--- | :--- | :--- | :--- | :--- |
| A 基线 | privileged + seccomp unconfined（现状） | ✅ | ✅ | — |
| B | 去 privileged + cap_drop ALL + SYS_ADMIN + 默认 seccomp | ❌ | ❌ | `setting up uid map: EPERM`（cap_drop ALL 缺 SETUID 系 → userns map 失败） |
| B2–B4 | 去 privileged + cap_drop ALL + SYS_ADMIN + seccomp/AA unconfined 各组合 | ❌ | ❌ | 同 B（cap_drop ALL 形态 userns 不可用，与 seccomp/AA 无关） |
| C/E（nonroot） | `--user 10001` + SYS_ADMIN + unconfined | ✅ | ❌ | probe ✅；`pivot_root/mount proc: EPERM`——**Docker `--user` 下 cap_add 不生效（CapEff=0）**，userns root 无挂载能力；no-new-privileges/read-only 非变量 |
| T2/T3 | root + cap_drop ALL + SYS_ADMIN+SETUID+SETGID + 默认 seccomp | ❌ | ❌ | uid map EPERM（cap_drop ALL 副作用，SETUID 补上仍失败） |
| T4/T5 | root + 默认 caps + SYS_ADMIN + 默认 seccomp | ❌ | ❌ | 越过 uid map → `pivot_root: EPERM`（默认 seccomp 拦） |
| T6/T7 | root + 默认 caps + SYS_ADMIN + **seccomp unconfined**（AA 默认）± read_only/tmpfs/nnp | ✅ | ❌ | probe ✅；`Can't mount proc on /proc: EPERM`——**仅 `--unshare-pid` + `--proc` 组合失败**（bwrap 0.12.0） |
| NO_PID 变体 | 同 T6，argv 去 `--unshare-pid` | ✅ | ✅* | 全部挂载（proc/dev/tmpfs/bind）+ 沙箱内写 `/work` 通过（*手工测试 PATH 瑕疵，kernel 有 `--setenv PATH` 无碍） |

## 2. 结论（对 B 稿 D1 的 PoC 勘误）

1. **移除 `privileged` 可行**：形态 = 容器 root + **默认 caps 集 + SYS_ADMIN** + `seccomp=unconfined`（显式保留；自定义最小 profile 因默认 profile 拦截 userns/pivot_root 链不适用，列为后续强化）+ `read_only` rootfs + tmpfs `/tmp`/`/run` + `no-new-privileges`（T7 全绿）。
   - 收益：去掉 privileged 消除设备全访问与 `SYS_MODULE/SYS_RAWIO/SYS_PTRACE` 等超集（默认 caps 仅 +SYS_ADMIN 的窄集），配合 read_only/nnp 达到 B 稿 D1 主要目标；残余面 = 默认 caps（SETUID 等）保留（userns 映射需要）。
2. **「非 root USER runner」否决（PoC）**：Docker `--user` 下 `--cap-add` 不生效（CapEff=0），nonroot 无挂载能力，bwrap 全 unshare 不可用。→ B 稿 D1 表「运行用户 root → 非 root」**勘误为「容器 root + 默认 caps 最小化」**；B 附录 B-1 关闭（PoC 已做，结论如上）。
3. **`--unshare-pid` 取舍**：非特权（含 root T6）下 `--unshare-pid` + `--proc` 组合在 bwrap 0.12/Docker 26 不可用（mount proc EPERM；升级 bwrap ≥1.0.4 可再验证，列为可选强化）。**落地：`sandbox_kernel` argv 移除 `--unshare-pid`**——`--proc` 呈现容器 pid ns 级视图（仅 runner 容器自身进程，无宿主/跨容器进程；沙箱 userns root 对容器内他进程无 ptrace 权限，防护语义保持）。威胁面变化登记：B 稿 §11 演练 3「宿主进程不可见」口径改「容器级 pid ns 视图」。
4. **目录属主编排不再需要**（容器 root 保留，无 chown 联动）；F1 workspaces 目录不受影响。
5. 部署侧：compose runner 段按上述形态修改；镜像重建沿用 deploy.sh（backend/runner 与 shared 变更联动 + tag 回滚）；空转观察 `sandbox_bash_mode=none` ≥7 天（D6-1）后按 D6 阶梯放行 read-only。

## 3. G3（并发配额，B 稿 S2/D4）实施方案（可并行开发，不依赖 G2）

| 面 | 内容 |
| :--- | :--- |
| runner | `ThreadingHTTPServer` 全局 `BoundedSemaphore(RUNNER_MAX_WORKERS=4)`：请求入口限时等待（默认 5s）→ 超时 429 + 错误码 `BUSY`（api 映射 CONCURRENCY）；`/health` 扩 `{running, queued, max_workers}` |
| api | bash 客户端每 scope 闸门：模块级 `dir→threading.Lock` 映射（锁注册表防泄漏），同目录并发 bash 等待（超时 30s → CONCURRENCY「该工作区已有 bash 执行」）——防同 scope 并行写互踩；与 runner 全局上限双层 |
| config/env | `settings.sandbox_max_concurrency`（文档/观测）；runner `RUNNER_MAX_WORKERS` env |
| 测试 | runner：并发 8×慢命令 → 实测并发 ≤4 全 200；超时窗口 429 用例；health 字段断言。api 闸门：同 scope 双线程串行断言 + 超时 CONCURRENCY |

## 4. 后续
- G3 代码实施 + 门禁（本文件同 commit 或紧随）。
- G2 落地 = 仓库 compose/Dockerfile/sandbox_kernel argv 修订 → CI 构建 → 服务器部署（deploy.sh）→ 空转观察；验证清单：T7 形态容器内 `probe_sandbox=True` + `/run` echo 通过 + `read_only` 生效（容器内写 / 失败、/tmp 可写）。
- G4（F2 policy 化 + 删词表）依赖 G2 完成（sudo 残余删除前置）与 runner 校验替换（并入 F2）。
