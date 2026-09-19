# AI 测试与评估平台 — 项目审查与修复记录

| 项目 | 内容 |
| --- | --- |
| 版本 | V1.1 |
| 审查日期 | 2026-09-19 |
| 代码基线 | `39a7596`，审查开始时最新 `origin/main` |
| 修复分支 | `codex/fix-project-audit` |
| 接口契约 | API V2.22；既有产品范围内修复 |

## 1. 范围与方法

审查开始时工作区干净，原分支 `feat/web-workspace-video-preview` 相对远端为 1 个独有提交、落后 41 个提交。保留原分支，从最新主干创建本轮分支。2026-09-19 合并前再次 fetch，远端仍为 `39a7596`，没有新增提交或冲突；交付经功能分支与 PR，CI/CD 结果以合并后的工作流记录为准。

采用关键链路静态检查、全量现有回归、新缺陷复现与修复后验证。重点阅读了文件/工作区访问、认证与任务路由、Worker 领取及终态写入、WS v2 命令校验、AgentLoop 预算与回合依赖、专家协作取消锁及部署配置。本次不是逐行穷尽全部源文件的安全认证，也未访问生产账号或调用真实模型。

## 2. 当前架构核对

| 范围 | 代码职责与核对结果 |
| --- | --- |
| Vue 工作台 | REST 资源管理、WS v2 事件 reducer/transport、文件编辑及媒体预览；本轮缺陷主要集中在工作区异步状态 |
| FastAPI 控制面 | 认证、属主/可见会话权限、协议档、任务入队与文件接口；文件响应缺少内容隔离已修复 |
| AgentLoop | 模型/工具循环、回合级依赖、持久事实与恢复补偿；保留当前 WS v2/多协议契约，未重写编排 |
| Worker | PostgreSQL 队列领取；benchmark/testcase/rag/stress 分发；执行器独立 Session，终态写入重新加锁检查 running |
| Runner / 媒体 MCP | 受控沙箱与独立工具服务；本轮仅修 Runner 测试的 Windows 替身兼容性 |
| 构建与部署 | 分服务构建、镜像发布及排空保护；只执行本地脚本测试/语法检查 |

## 3. 已修复问题

| 级别 | 问题与可观察影响 | 修复与证据 |
| --- | --- | --- |
| P1 | 原始工作区 HTML/SVG 和团队可见 HTML 附件同源 inline 返回，直接打开可获得平台页面的脚本上下文 | 两条文件响应加 `Content-Security-Policy: sandbox`、`nosniff`；未知 MIME 用 octet-stream；响应测试同时确认媒体 206 Range 正常 |
| P1 | 切换工作区先更新 v-model 再确认，点“留在当前”后旧文件仍显示，但保存目标已变为新工作区 | 确认前保持模型与 DOM 原值，确认后清理旧文件再切换；浏览器校验取消后保存仍发往原工作区 |
| P1 | 上传整文件读入内存、异步端点执行同步磁盘操作；直接覆盖发生中途失败时会破坏原文件 | 同步路由由线程池执行；每块最多 1MiB，临时文件完成后原子替换；超限/读取失败保全原文件；同工作区 HTTP 上传配额检查使用行锁串行化 |
| P2 | 文件/目录请求乱序会覆盖当前选择，图片/视频预取可在关闭后写入旧 Blob | 请求序号与工作区 ID 双重校验，关闭/卸载使请求失效；浏览器复现先发后到的读取 |
| P2 | 保存完成时用最新编辑内容清空 dirty，实际未提交的新编辑被误标为已保存；Ctrl+S 经组件事件与冒泡重复提交 | 保存固定内容快照与文件身份，增加进行中守卫；浏览器验证保留 dirty、每次保存只有一个 HTTP 请求 |
| P2 | 工作区列表忽略 offset/limit，每次全量读取并扫描目录；直接落实后端分页又会使前端漏项 | SQL 分页、稳定排序及独立 total；当前页才扫描目录；选择器逐页读取，SQL 与浏览器双侧回归 |
| P2 | 容量栏固定 100MB，与默认 1GiB 及自定义配额不符 | API 先登记 `quota_bytes`，后端按配置投影、前端按实际值显示；旧后端不提供字段时仅显示已用量 |
| P2 | 批量上传循环逐次读取当前工作区，可跨工作区落盘；下载先拉完整 Blob，额外占用大文件内存 | 上传固定目标、阻止重复上传并在 finally 复位，避免覆盖未保存编辑；下载使用已有 attachment URL |
| P3 | Runner 已模拟进程却依赖 Windows 缺失的 SIGKILL；熔断测试依赖真实 60ms sleep，出现偶发失败 | 仅修测试替身与可控时钟，生产沙箱/熔断实现不变 |

应用复制阶段的额外缓冲由整文件大小降到块大小量级；未做生产内存压测，不给出未经测量的吞吐或延迟提升比例。

## 4. 验证证据

- 后端新增回归先在旧实现失败，再在修复后通过。5 个新增浏览器场景放回未修改 `HEAD` 时全部失败：取消切换得到 w2、旧文件覆盖新文件、dirty 消失、列表漏项和重复保存；恢复修复后通过。
- 全局 Python 3.14 基线出现 63 项供应商 SDK 相关失败。按仓库固定依赖建立 `.venv` Python 3.12 后，同一主干基线为 **2045 passed / 79 skipped**，没有为本地环境差异修改供应商业务代码。
- 最终 API：**2059 passed / 79 skipped**，Ruff 通过。新增 14 项覆盖 SQL 分页、内容隔离、分块读取、覆盖配额、失败保全及 Range。
- Worker：**51 passed**；Runner：**41 passed / 2 skipped**；媒体 MCP：**5 passed**。
- 部署单元测试：**18 passed**；`deploy.sh`、`auto-deploy-watch.sh`、`drain-agents.sh` 的 Bash 语法检查通过。
- Stress：`go test ./...` 通过编译，该包没有测试文件，不视为真实发压验收。
- 前端 ESLint：**0 errors / 222 warnings**（主要为既有 any）；**类型检查通过、119 项 Node 测试通过、生产构建通过**。合并前完整浏览器回归 **35 passed**（30 项既有、5 项新增）。浏览器使用真实 Vue 页面与隔离 HTTP/WS 夹具，不把夹具等同真实供应商闭环。
- 合并前再次运行 API/Worker/Runner 门禁；Runner 首次出现一例 Windows 本地 HTTP `WinError 10053`，单例及全量复跑均通过，未据此修改生产 HTTP 行为。

## 5. 未验证与后续边界

1. PostgreSQL 专属行锁/恢复测试未配置隔离数据库，Linux 命名空间测试受 Windows 环境限制；它们计入 skipped，不能宣称多进程上传锁或真实沙箱隔离已经实测。
2. 本地审查未执行真实模型调用、数据库迁移、LightRAG 集成或压力测试；合并后的 CI、部署与健康检查须独立核对，不能由本地通过推断。
3. multipart 文件在进入路由前可能已经被框架缓存到临时磁盘；本次限制的是应用复制阶段内存及工作区最终文件大小。全入口配额、代理请求体限制、Agent/HTTP 同时写入与文件系统 TOCTOU 不属于本次已验证保证。
4. 工作区目录统计仍是递归扫描；选择器为保持既有完整目录语义会逐页加载全部工作区。真正的大规模磁盘统计缓存/独立选择器分页需按测量与产品交互单独设计。
5. 前端已有大体积分包提示（Mermaid、Naive UI、ECharts），本次不通过放宽告警阈值掩盖问题；后续应结合实际首屏加载与图表使用路径测量再拆包。

## 6. 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/routers/user_workspaces.py` | SQL 分页、实际配额、上传行锁/线程池与原始响应隔离 |
| `backend/api/app/workspace_service.py` | 有界流复制、原子替换、失败清理 |
| `backend/api/app/routers/files.py` | 用户附件 CSP/nosniff |
| `backend/api/tests/test_workspace_audit.py` | 14 项新增后端回归 |
| `backend/api/tests/test_user_workspaces_files.py` | 既有二进制文件测试迁移为流接口 |
| `backend/api/tests/test_native_tools_p1.py` | 熔断测试使用确定性时钟 |
| `backend/runner/tests/test_kernel_cancellation.py` | POSIX 进程替身跨平台兼容 |
| `frontend/src/api/http.ts`、`frontend/src/api/types.ts` | 工作区列表分页兼容与配额类型 |
| `frontend/src/views/UserWorkspaces.vue` | 工作区/文件异步归属、保存、上传、下载与容量展示 |
| `frontend/tests/e2e/workspaceAudit.spec.ts`、`frontend/tests/workspace-audit-fixture.html` | 5 项浏览器回归及页面夹具 |
| `docs/AI测试与评估平台-API.md` | V2.22 契约、错误码校正与修订清单 |
