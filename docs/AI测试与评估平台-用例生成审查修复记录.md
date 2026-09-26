# AI 测试与评估平台 — 用例生成审查修复记录

| 项目 | 内容 |
| --- | --- |
| 版本 | V1.0 |
| 审查日期 | 2026-09-26 |
| 代码基线 | `9753cd4`，修复前已 fetch 并核对最新 `origin/main` |
| 修复分支 | `codex/fix-testcase-audit` |
| 契约 | PRD V1.43 / API V2.23 |

## 1. 范围与缺陷

目标是修复审查中已复现的缺陷，为“需求文档生成带步骤、预期结果的功能测试用例，并导出 Excel”保全既有流程。没有增加自动执行测试脚本、专家后台续跑或直接向已发布数据集追加行的产品能力。

| 问题 | 修复方向 |
| --- | --- |
| PRD 生成请求字段不符合后端契约 | 使用 source_text、strategy_weights、max_count；模型配置沿用 Agent 协议档 |
| 策略别名使筛选/覆盖率失真、客户端提前超时 | 统一六策略名称并兼容旧别名；两种 AI 请求和 API 代理等待调整为 130 秒 |
| 保存不带原 ID、丢失前置条件与扩展字段 | 保留真实身份与完整字段，服务端结果回写新行 ID；允许清空最后一行 |
| 保存失败仍确认/切换、迟到响应串集 | 保存结果门禁、目标绑定、请求序号、编辑快照 |
| 导出只有成功提示 | 调用已有导出接口并下载实际 Blob，失败不报成功 |
| 来源文件越权与无扩展名 Excel 误解析 | 创建、重跑和消费前按上传者授权；Excel 按元数据识别并以流读取 |
| 默认配比覆盖请求配比、模型字段冒充身份 | 校验六策略百分比，同源配额裁剪，丢弃模型身份与状态字段 |
| 映射写入正式版本不可见的旧表、重复映射 | 已发布目标返回 VALIDATION；旧式未发布数据集加锁幂等映射 |
| 确认与超时扫描产生矛盾终态 | CaseSet→Task 一致锁序，持锁后复核截止时间与状态 |
| Worker 重启遗留 running 占满队列 | 使用已有租约字段领取及独立续租，过期明确失败且不自动重发调用；提交回收后尽力请求停止外部压测 |
| Agent/重跑生产压测复用或漏写会签 | 新任务重置批准、Worker 发压前复核非创建者会签 |
| 无会话历史任务重跑绕过个人配额 | 创建和重跑共享配额门禁，并保留会话待确认卡阻挡 |
| 配额行锁与数据集发布外键锁可能形成死锁 | 成员配额采用 FOR NO KEY UPDATE，在串行化计数的同时允许用户外键引用 |

## 2. 验证

修复前新增任务入口回归为 8 failed / 1 passed，覆盖文件越权、配额、待确认卡及旧会签复用；6 个 Cases 浏览器回归均在旧实现失败，覆盖生成请求、编辑往返、保存失败、读取乱序、保存中新编辑和下载。补充的六策略覆盖及 AI 超时回归同样先失败再修复。

修复后最终结果：

| 检查 | 结果 |
| --- | --- |
| API 全量 pytest | 2093 passed / 79 skipped，46.23 秒 |
| Worker 全量 pytest | 76 passed，5.89 秒 |
| API / shared Ruff、修改过的 Worker 文件 Ruff | 通过 |
| 前端单元测试 | 119 passed |
| 前端完整 Playwright | 46 passed，其中本轮新增 11 项 |
| 前端 lint | 0 errors / 220 warnings |
| 前端 typecheck / build | 通过；构建仍有既有 vendor 大包提示 |
| git diff --check | 通过 |

API 仍有依赖弃用提示及既有图节点类型提示。79 项跳过不计为通过。本节记录本地验收结果，合并和部署结果以对应 PR / Actions 记录为准。

## 3. 验证边界

本地测试使用仓库 Python 3.12、隔离数据库或测试替身，以及真实 Vue 页面配合隔离 HTTP 夹具。不调用真实模型、生产压测或生产数据，不把本地通过视为发布完成。SQLite 验证状态和事务代码路径，不证明 PostgreSQL 行锁在多进程竞争下的实测结果。新增租约只负责中断任务明确收尾，不自动重发结果未知的供应商操作。

本机无 Nginx / Docker，未执行 nginx -t 或容器验证。外部压测停止是尽力请求，网络故障时仍需核查引擎执行结果；失败终态不等于外部执行已经停止。

旧版 Worker 没有租约，升级时禁止旧版/新版同时消费同一数据库；混跑会把旧版无租约的 running 行按遗留任务失败收尾。标准单实例 Compose 原位重建会先退出旧进程再启动新进程，无需提前手动停止服务；部署脚本会保留人工停止的服务，提前停止反而可能使更新后仍未启动。API/Worker 必须使用同一版本代码。

现有部署排空仅覆盖 Agent 回合，不等待 Worker 任务完成。升级时仍在执行的旧 Worker 任务会中断，随后按上述规则明确失败；需要核查结果后人工决定是否重跑。

## 4. 修改代码文件与作用清单

- `backend/api/app/task_policy.py`、`routers/tasks.py`、`harness/execution/{task_tools,worker_bridge}.py`：入队授权、配额及生产会签一致性。
- `backend/api/app/routers/cases.py`、`schemas.py`、`backend/shared/casegen.py`：用例来源、状态锁、保存/映射与生成结果约束。
- `backend/worker/app/{main,task_state,benchmark,testcase,stress}.py`：领取心跳、过期收尾、停止后续批次、来源复验和生产会签防御。
- `frontend/src/views/Cases.vue`、`frontend/src/api/{http,types}.ts`、`frontend/nginx.conf`：生成、编辑、保存、确认、切换、策略名称、请求等待和文件下载。
- API/Worker 新增回归、`frontend/tests/cases-audit-fixture.html`、`frontend/tests/e2e/casesAudit.spec.ts`：对应缺陷复现与修复验收。
- PRD V1.43 / API V2.23：更新现有契约与交付边界。
