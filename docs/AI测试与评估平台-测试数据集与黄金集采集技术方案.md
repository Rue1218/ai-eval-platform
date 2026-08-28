# AI 测试与评估平台 — 测试数据集与黄金集采集技术方案 (V2.2)

> **版本**：V2.2<br>
> **审查日期**：2026-08-28<br>
> **状态**：方案制定中（V2.2 完成目录治理、导入队列、并发发布、成员同权双人复核和 M3 对齐；待按 M3 实施）<br>
> **关联契约**：PRD.md V1.15；API.md V1.55。目录筛选、目录/release 审核、导入作业、staging 行、发布门禁和任务版本锁定以 PRD/API 为准；新增数据模型、Worker 与前端实现须在 M3 生成迁移并补齐测试

---

## 1. 目标、范围与裁决

平台要建设的是可复现的**模型测试数据集**与可验证的 **RAG 黄金集**，不是通用网页采集系统。所有外部内容在进入评测前都是候选资产；只有经过来源、授权、完整性和人工审核后，才可以发布为不可变的正式版本。

本方案覆盖两条链路：

1. **公开测试数据集采集**：从官方仓库、Hugging Face 固定修订、官方发布页或成员上传的已授权归档文件，获取 MMLU、C-Eval、GSM8K、IFEval 等标准基准的原始制品，转为平台数据集行；
2. **RAG 黄金集采集**：从已授权且已索引的知识文档快照生成或人工录入问题、参考答案和证据锚点，用于检索质量、答案正确性与模型忠实度评测。
3. **基准数据集页自动导入**：用户在 `/datasets` 选择平台维护的公开基准目录并发起导入；Worker 获取固定制品、生成行级 staging，完成后自动显示在该数据集的表格列表，审核发布前不进入评测分母。

**V2.0 明确不做**：

- 不做任何社交媒体平台、账号、评论、视频或站内搜索抓取；
- 不做登录态、Cookie、签名、反爬绕过、下载器 sidecar 或平台专用适配器；
- 不将网络搜索摘要、模型自由生成文本、第三方未校验镜像或未经审核的文档直接写入正式数据集或黄金集；
- 不将公开 benchmark 的训练集、开发集或测试集用于提示词样例、黄金答案生成或模型训练；
- 不在 API 进程下载大文件、解压归档或运行代码评测。耗时导入必须进入受控 Worker 作业。

### 1.1 核心设计原则

| 原则 | 约束 |
| :--- | :--- |
| 权威优先 | 作者官方发布页/仓库是来源真相；Hugging Face 是优先分发与加载渠道，评测框架仅是执行适配渠道 |
| 制品可复现 | 每次导入固定 source revision、归档文件 SHA-256、解析器版本、切分、提示词和评分器版本；禁止跟随远端 `main` 静默更新 |
| 候选隔离 | 下载、解析、AI 生成的内容先进入 staging/review，审核发布才生成 `DatasetVersion` 或 `GoldQaVersion` |
| 证据优先 | Benchmark 的 reference 与 RAG 黄金答案都必须有可回查来源；RAG 的证据必须绑定不可变 KB 文档快照和范围 |
| 职责分离 | 下载/解析器只处理制品，非提报成员审核来源/release/发布，Worker 只按锁定版本评测；被测模型、候选生成模型和 Evidence Judge 不得自评 |
| 最小化处理 | 只存评测所需的题目、答案、来源清单与最小证据；敏感内容、未授权内容和不必要个人信息不入正式资产 |

---

## 2. 资产分层与采集来源

### 2.1 资产模型

```text
外部标准数据源 / 已授权知识文档
             │
             ▼
    来源登记与授权校验（draft）
             │
             ▼
   不可变制品快照 / KB 文档快照
             │
     ┌───────┴────────┐
     ▼                ▼
标准数据集解析      黄金 QA 候选生成/录入
     │                │
     ▼                ▼
数据集候选行       问题 + 答案 + 预期证据
     └───────┬────────┘
             ▼
       人工审核与发布
             │
   ┌─────────┴─────────┐
   ▼                   ▼
DatasetVersion      GoldQaVersion
   │                   │
   └── Task.config 锁定版本 ──► Worker / 报告
```

| 资产 | 定义 | 是否可直接评分 |
| :--- | :--- | :--- |
| 数据源登记 | 逻辑来源及其官方地址、许可证、用途边界、提报/审核身份 | 否 |
| 来源制品快照 | 已下载的 ZIP/JSONL/CSV/Parquet 等原始文件及完整性信息 | 否 |
| 导入批次 | 一次解析、规范化、校验产生的 staging 行与异常清单 | 否 |
| Benchmark 数据集版本 | 已审核、可按确定性指标评分的不可变行快照 | 是 |
| KB 文档快照 | 已授权文档的规范化文本、哈希和索引版本 | 否 |
| RAG 黄金集版本 | 已审核的题目、答案、可回答性和预期证据快照 | 是 |

### 2.2 合法采集来源与优先级

| 来源类型 | 允许方式 | 固定信息 | 用途限制 |
| :--- | :--- | :--- | :--- |
| 官方 GitHub/Git 仓库 | 固定 tag 或 commit 的 release/归档文件 | `repository_url`、commit/tag、release URL、文件 SHA-256 | 仅按上游许可证使用；仓库代码不等同于数据许可证 |
| Hugging Face Dataset | 使用明确数据集 ID 与 commit revision 下载制品 | dataset ID、revision commit、config/split、文件 SHA-256 | 禁止 `trust_remote_code`；镜像失效时回查官方来源 |
| 官方项目网站/对象存储 | 成员登记固定下载地址或官方校验和 | 发布页、下载 URL、版本号、校验和、发布时间 | 先确认版权、地域和再分发限制；非提报成员复核 |
| 成员上传 | 上传已获授权的原始制品 | 上传人、授权凭证引用、原始文件 SHA-256、导入说明 | 仅内部可控数据；不得把不明来源文件伪装为公开基准；非上传人复核后才能发布 |
| 已授权 KB 文档 | 既有 KB 导入和索引链路生成 `KbDocumentSnapshot` | document ID、snapshot ID、内容哈希、索引状态、授权范围 | 仅用于黄金 QA；不能以网页 URL 替代文档快照 |

网络搜索只能用来**发现**官方项目入口；搜索摘要、第三方转载页和社区网盘不是正式制品源。发现候选后，提报成员必须回到作者官方仓库、发布页或许可证文件登记来源，另一成员复核后才可批准 release。

---

## 3. 总体架构

### 3.1 标准数据集采集链路

```text
成员提报数据源 → 非提报成员复核 release
        │  校验来源、许可证、适用任务、版本与切分
        ▼
数据源登记（draft）
        │
        ▼
受控导入 Worker
  ├─ 下载固定制品 / 接收成员已授权上传
  ├─ 限制域名、大小、MIME、压缩层数与解压后总大小
  ├─ 校验上游校验和与本地 SHA-256
  └─ 写入不可变制品快照与导入审计
        │
        ▼
纯本地解析适配器
  ├─ JSONL / CSV / Parquet / 官方专用结构
  ├─ 映射 question/reference/context/options/extras
  ├─ 校验 split、标签、字段类型、重复与敏感信息
  └─ 产生 staging 行及拒绝原因
        │
        ▼
人工审核 → 发布 DatasetVersion → 任务锁定版本
```

导入 Worker 不从模型传入的 URL、Header、Cookie、路径或脚本执行下载；其来源只能是已批准 release 的冻结 manifest。每个解析适配器是**纯本地函数**，只读取已冻结的制品字节或临时受控文件，不自行联网、不调用模型、不修改正式数据集。

### 3.2 黄金集采集链路

```text
已授权文档导入 → KbDocumentSnapshot → 索引完成
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
            人工编写黄金 QA                    AI 辅助生成候选（未落库）
                   │                                     │
                   └────────── 证据定位与交叉校验 ───────┘
                                      │
                                      ▼
                     双人审核 / 例外审计 / 发布版本
                                      │
                                      ▼
                 GoldQaVersion + expected_evidence 快照
```

黄金 QA 不是“从外网下载一个问答集”。它只能使用已经授权、已解析、已索引且存在 `KbDocumentSnapshot` 的文档。每道题必须标明：

- `answerability`：`answerable`、`insufficient_evidence` 或 `conflicting_evidence`；
- `expected_doc_ids[]`：`answerable` 题必填；
- `expected_evidence[]`：`doc_id + document_snapshot_id + start/end + text_sha256`，范围相对不可变规范化文本解释；
- `reference`：由证据逐事实支撑的简洁答案，而非模型推测；
- `valid_until?`：适用于时效性事实；超过有效期必须新建修订版本。

---

## 4. 标准数据集导入设计

### 4.1 目录与 release 治理清单

任一成员可提报数据源与 release，另一名成员审核批准；“提报人/审核人”仅是审计身份，不形成管理员 RBAC。来源记录描述稳定的上游身份，release 记录一次不可变的可下载制品与解析方式。它们是导入判断与审计依据，不是模型可编辑提示词。

```json
{
  "display_name": "C-Eval",
  "source_kind": "huggingface | git_release | official_http | upload",
  "official_project_url": "https://...",
  "distribution_url": "https://...",
  "source_revision": "commit/tag/release",
  "license": "SPDX 或上游原文引用",
  "license_evidence_ref": "官方许可证文件或授权凭证引用",
  "usage_scope": "internal_evaluation_only",
  "task_family": "multiple_choice | generation | instruction_following",
  "allowed_splits": ["validation", "test"],
  "expected_artifacts": [{"url": "https://...", "path": "...", "sha256": "...", "size_bytes": 0, "mime_type": "application/json"}],
  "parser_id": "ceval_v1",
  "parser_version": "1.0.0",
  "filter_schema": {"version": 1, "fields": {"subjects": {"type": "enum[]"}, "max_rows": {"type": "integer", "min": 1, "max": 20000}, "sampling_seed": {"type": "integer"}}, "source_order": "source_record_id_asc"},
  "notes": "测试标签公开性、上游限制与已知污染风险"
}
```

`source_revision`、制品 SHA-256、`parser_id/parser_version`、切分、`filter_schema` 和许可证在批准后不可修改；修正信息只能新建 release、来源制品快照和新的 `DatasetVersion`。只写“latest”“main”“最新版本”或只留一个 Hugging Face 页面 URL 的登记不能进入导入队列。

来源状态为 `draft | active | suspended | archived`；release 状态为 `draft → reviewing → approved`，或 `blocked | superseded`。仅 `active + approved + license.allowed` 的组合能出现在目录。所有成员可创建草稿、提交审核和紧急暂停 release；批准、许可证例外、解除暂停与发布必须由非提报成员执行。暂停会阻止新导入；确认封禁后，关联正式版本变为 `deprecated`，只允许历史报告读取。每一次转移记录 manifest 哈希、许可证证据引用、操作者、提报人、审核意见和时间。

### 4.2 受控下载与制品安全

1. **允许列表**：只允许已审核数据源中的 HTTPS 下载地址和固定镜像域名；下载前后均记录最终 URL，重定向仍执行域名校验；
2. **资源边界**：设置单制品大小、总制品大小、解压后总大小、压缩嵌套层数、单文件数量和作业时限，超限失败为 `VALIDATION` 或 `TIMEOUT`；
3. **格式边界**：按魔数和 MIME 校验制品类型，拒绝可执行文件、符号链接逃逸、路径穿越和未知压缩格式；解压目标限定在作业唯一临时目录；
4. **完整性**：优先验证作者发布的校验和；无上游校验和时计算平台 SHA-256 并标记 `upstream_checksum_missing`，需要人工确认后才能发布；
5. **凭据边界**：受限数据集的访问令牌只由服务器密钥管理供导入 Worker 读取，绝不存入数据源 manifest、数据库行、日志、报告或浏览器；
6. **网络与执行边界**：下载器不执行制品内代码、不启用远端自定义加载器；当前产品不登记或导入代码任务制品。

### 4.3 解析与标准化

平台不试图用一个通用 CSV 映射覆盖所有基准。每个 `parser_id` 均定义输入格式、允许切分、标准字段、评分前置条件和测试样例：

| 任务族 | 标准字段 | 评分前置条件 | 典型风险 |
| :--- | :--- | :--- | :--- |
| 多选 | `question, options[], answer_key, subject` | 选项顺序、输出提取、few-shot 模板固定 | 将自由文本误解析为选项、公开 test 污染 |
| 数学 | `question, reference, solution?` | 最终答案提取与数学等价归一化版本固定 | 直接字符串比较误伤等价答案 |
| 开放生成 | `question, reference, context?` | 确定性指标或受控 Judge profile 固定 | Judge 偏差、风格掩盖事实错误 |
| 指令遵循 | `prompt, constraints[]` | strict/loose 规则实现及版本固定 | 把不可验证主观要求算作通过 |

解析完成后的 staging 校验至少包括：行数与上游清单一致、必填字段、标签域、切分合法性、答案唯一性、JSON/CSV 编码、题目/参考答案去重、跨 split 泄漏和制品哈希一致性。错误行不得静默删除；导入报告必须给出行号、错误类别和原始制品快照 ID。

### 4.4 测试标签与数据污染处理

- 上游 test 标签未公开或要求官方提交的基准，只能导入 dev/validation 做内部回归，结果必须标注为“非官方 test”；
- 公开多年且可能进入预训练的数据集保留为**历史可比指标**，不应用于声称模型依赖外部上下文；
- 动态或按期更新的数据集必须以发布日期和制品哈希作为独立版本，不能合并为一个浮动数据集；
- `train`、`dev`、`validation`、`test` 不得混入同一个正式评测版本。任何样本用于提示词示例、few-shot 上下文或训练时，都必须在该评测版本的 manifest 中显式记录；
- 公开基准不自动成为业务黄金集。业务真实性和 RAG 忠实度只能由已授权知识库与私有/受控测试文档验证。

### 4.5 基准数据集页的自动导入

#### 4.5.1 页面与导入作业边界

`/datasets` 是导入入口，但**不是爬虫执行位置**。页面只能读取数据集目录、提交经选择的导入请求、轮询状态和展示 staging 行；下载、解压、解析、哈希校验和去重均在 Worker 中执行。导入作业是独立的 `DatasetImport` 队列记录，不复用评测 `Task`，更不能假装成已完成 benchmark 任务。

```text
数据集页「导入公开基准」
        │
        ▼
数据集目录筛选 + 查看来源清单
        │  选择 release、split、目标名称与目录
        ▼
POST /api/dataset-imports → 202 Accepted
        │
        ▼
Worker: 下载 → 校验 → 解析 → staging
        │
        ├─ failed：页面显示归一错误码、失败阶段和可重试提示
        └─ review_ready：自动刷新目标数据集表格，展示 staging 行和质量摘要
                                       │
                                       ▼
                         审核并发布 → DatasetVersion → 可创建评测任务
```

导入请求必须选择平台已批准的 `catalog_entry_id + release_id`；用户不能直接输入任意下载 URL、请求头、Token、解析脚本或压缩包内路径。自定义来源需先由成员提报，再由非提报成员复核 release；批准后才能在页面导入。

#### 4.5.1.1 独立导入队列与恢复语义

`DatasetImport` 不是 `tasks` 表的别名，而是具有不可变 `manifest_hash` 与唯一 `request_fingerprint` 的独立队列主记录；`DatasetImportAttempt` 保存每次执行的 `attempt_no`、阶段、租约、错误和开始/结束时间。Worker 以 `FOR UPDATE SKIP LOCKED` 领取 `queued` 主记录，在写入 `lease_token`、`lease_owner`、`lease_expires_at` 前不得开始下载；平台设置 `max_running_dataset_imports=1` 作为初始上限，后续仅通过受审计设置调整。

每次阶段提交必须携带当前 attempt 与 lease，避免过期 Worker 覆盖新结果。租约过期后回收器清理该 attempt 的不完整 staging，再将同一 immutable manifest 重排；只要尚未达到 `max_attempts` 即可恢复，超过上限才以 `TIMEOUT` 置为 `failed`。`UPSTREAM` 和 `TIMEOUT` 允许显式重试；许可证、格式、split、过滤条件、配额和解析器不匹配均为 `VALIDATION`，必须新建/修订 release，不能以重试掩盖。完成 staging 与状态转为 `review_ready` 必须同一事务提交。

#### 4.5.2 页面场景划分

| 场景 | 用户动作 | 后端行为 | 页面结果 |
| :--- | :--- | :--- | :--- |
| 快速导入官方基准 | 选择目录中的 C-Eval、MMLU、GSM8K 等已批准 release | 读取固定 manifest，创建幂等独立导入作业 | 数据集容器显示导入进度，不覆盖已有 active 版本 |
| 按能力发现数据集 | 按语言、任务族、评分方式、许可状态、测试标签可用性筛选 | 仅检索平台目录元数据，不触网 | 卡片显示适用场景、版本、来源、风险和预计样本数 |
| 导入指定切分 | 选择 `validation` 或公开 `test`，可选 subject/子集 | 校验该 release 允许的 split 与许可证 | 只导入选中范围，并在表格中标记 split |
| 导入后人工检查 | 查看行表、来源信息、解析告警和抽样预览 | staging 行仍与 active 版本隔离 | 可删除/修订不合格行或整体拒绝导入 |
| 发布为评测集 | 非提报成员选择稳定行 ID 并审核发布 | 锁定 import/dataset，校验 staging revision 后原子创建 `DatasetVersion` | 原子切换 `active_version_id`，可用于确认卡 |
| 失败或重复导入 | 查看失败原因或再次点击同一 release | 返回同一进行中/已完成作业，或按策略重试 | 不生成重复行；失败显示 `VALIDATION`/`UPSTREAM`/`TIMEOUT` |

目录中不展示“任意网页抓取”入口。`从 URL 导入`若未来开放，第一步也只能创建 `draft` 数据源登记，经过来源、许可证与制品清单审批后才能出现“开始导入”按钮。

#### 4.5.3 表格保存语义

为同时满足“自动保存到表格列表”和“未经审核不得评分”，数据集容器与导入作业分离：数据集是 `draft | active | archived`，导入作业是 `queued | downloading | validating | parsing | review_ready | published | failed | rejected`。因此已有正式版本的数据集可以同时展示新的 staging 导入，既不影响正在运行任务，也不把新行提前纳入评测。

| 导入状态 | 表格可见性 | 是否可编辑 | 是否进入评测 |
| :--- | :--- | :--- | :--- |
| `queued` / `downloading` / `validating` / `parsing` | 显示来源卡和作业进度，不显示不完整行 | 否 | 否 |
| `review_ready` | 显示 staging 行，行首展示 split、来源和解析告警 | 仅审核修订 | 否 |
| `published` | active 视图显示已发布行和不可变版本号 | 可创建新的 draft/staging，不得改写已发布版本 | 是（仅 active_version） |
| `failed` / `rejected` | 保留失败摘要或审计，不显示为可评分表格 | 否 | 否 |

Worker 在 `review_ready` 时将规范化结果写入以 `import_id` 关联的 staging 行表，因此用户无需下载再上传，刷新页面仍能看到表格。读取返回 `staging_revision`；修改行必须提交稳定 `row_id + expected_staging_revision`，成功后 revision 递增。发布只接受 `import_id + expected_staging_revision + accepted_row_ids[]`，并由非提报成员执行；服务端锁住 import 与 dataset，原子冻结**审核通过的 staging 行**到 `DatasetVersionRow`。revision 不匹配、行已被修改或作业已发布均返回 `CONCURRENCY`，未选中、解析失败和拒绝行不能混入版本。每行至少保存 `source_release_id`、`artifact_sha256`、`source_record_id`、`split`、`parser_id` 和 `parser_version`，供表格抽屉查看，不将冗长原始制品内容送入模型上下文。

#### 4.5.4 内容筛选和场景标签

目录筛选不是按标题关键词“搜网页”，而是按受审计的结构化元数据组合：

| 筛选维度 | 示例值 | 作用 |
| :--- | :--- | :--- |
| 能力场景 | 通用知识、科学推理、数学、多步推理、指令遵循、中文 | 帮助用户构成覆盖矩阵，禁止用单一总分替代分项；RAG 忠实度只来自已授权 KB 黄金集 |
| 任务族/评分器 | 多选 exact、数学等价、规则校验、受控 LLM Judge | 只展示当前平台已支持的任务族；代码、多模态和对话偏好不纳入当前产品目录 |
| 语言与地域 | 中文、英文、多语种、中国特定知识 | 防止把中文场景误用英文基准代替 |
| 来源与许可 | 官方/镜像、`allowed`/`review_required`/`blocked`、是否可再分发 | `blocked` 条目不可发起导入；许可证例外需非提报成员复核 |
| 测试可用性 | public test、validation only、官方提交、动态 release | 防止把无标签 test 当作本地正式 test |
| 可信度风险 | 历史污染高、测试标签受限、动态更新、Judge 偏差 | 在导入确认页和报告中持续展示 |
| 规模与成本 | 预计行数、媒体大小、是否需要 Worker/GPU/Judge | 超过团队配额时禁止或拆分导入 |

默认策略为：只显示 `allowed` 且平台已支持的条目；默认选择 `validation` 或公开 `test`，绝不选择 `train`；默认预估样本数不超过当前数据集上限，超大数据集要求选择 subject、子集或抽样规则。抽样种子、过滤表达式和来源 release 进入导入 manifest，确保同一导入可复现。

### 4.6 首批目录与解析器策略

首批目录不追求“收录所有 benchmark”，而是选择评分可复现、许可证可确认且当前平台可支持的任务族：

| 目录条目 | 场景 | 默认导入范围 | 解析/评分策略 | 目录状态 |
| :--- | :--- | :--- | :--- | :--- |
| C-Eval | 中文通用知识与推理 | 公开 test 或 validation，按学科可选 | 四选一，选项与答案键固定 | `supported` |
| MMLU / MMLU-Pro | 通用知识与推理 | test/validation，按学科可选 | 多选概率或严格选项提取 | `supported`，标记历史污染风险 |
| ARC-Challenge | 科学推理 | Challenge split | 四选一精确匹配 | `supported` |
| GSM8K | 多步数学 | test | 最终数值提取 | `supported` |
| IFEval | 指令遵循 | 官方输入集 | strict/loose 规则校验 | `supported` |
| TruthfulQA | 开放域真实性 | 推荐的固定 MC 配置 | 多选精确匹配；生成式 Judge 另行启用 | `supported` |
| GPQA、AGIEval、CMMLU、MATH | 专家/考试/中文/竞赛数学 | 固定 release 的受许可子集 | 需目录条目各自的 parser 与许可门禁 | `review_required` |
| HumanEval、MMBench、OCRBench、MT-Bench、AlpacaEval | 代码、多模态、对话偏好 | 不导入 | 不创建目录 release 或解析器；后续须先修改 PRD 与评测契约 | `out_of_scope` |

`supported` 仅表示可在平台本地导入和评分，不表示消除训练污染或可替代业务黄金集。CMMLU 等带非商业或再分发限制的数据集必须由目录许可证状态控制，不能因技术可下载就显示为可导入。

---

## 5. 黄金集构建与忠实度设计

### 5.1 候选生成与审核

人工录入和 AI 辅助生成都只能创建 `draft` 候选。AI 候选生成器必须输出问题、参考答案、逐事实证据范围、可回答性和不确定性；它不能发布版本，也不能补造不存在的证据。

审核者按以下顺序验收：

1. 文档授权、快照、索引状态和证据范围均存在；
2. 问题不依赖未提供的外部知识，且与 `answerability` 一致；
3. `reference` 的每个原子事实均被证据支持；对时效信息确认 `valid_until`；
4. `answerable`、证据不足和冲突证据三类题均有明确的期望行为；
5. 同源文档、近重复问题和改写题不跨 dev/test；
6. 高风险、时效或冲突样本由两名审核者独立通过。单人例外必须写入原因、操作者和时间。

### 5.2 正确性与忠实度双轴

| 维度 | 回答的问题 | 最低判断依据 |
| :--- | :--- | :--- |
| 数据可信度 | reference 在该版本是否真实、完整、仍有效 | 来源/文档快照、授权、哈希、证据、审核与有效期 |
| 答案正确性 | 模型答案是否与 reference 一致 | 任务确定性评分器或受控 Judge |
| 模型忠实度 | 模型本轮输出是否只由允许证据支持 | 原子主张与 `expected_evidence` 的支持关系 |

Evidence Judge 只能在服务端读取被测回答和该题允许的证据。它必须返回受控 JSON：

```json
{
  "verdict": "supported | unsupported | conflicted | abstained | needs_review",
  "confidence": 0.0,
  "claims": [{"text": "原子主张", "verdict": "supported", "evidence_refs": ["snapshot/span"]}]
}
```

被测 profile、候选生成 profile 和 Evidence Judge profile 必须不同。主 Judge 置信度低于 `0.85`、证据范围不存在或双 Judge 分歧时标记 `needs_review`，不进入自动忠实度分母。报告至少分开给出 `answer_correctness`、`claim_support_rate`、`unsupported_claim_rate`、`abstention_precision`、`abstention_recall` 和 `needs_review_rate`。

---

## 6. 版本、审计与治理

### 6.1 不可变性

数据源、制品、导入批次、正式数据集和黄金集的版本关系如下：

```text
DatasetCatalogEntry
  └─ DatasetCatalogRelease（不可变 manifest、许可证证据、parser/filter schema）
       └─ DatasetSourceArtifact（实际制品哈希）
            └─ DatasetImport / DatasetImportAttempt / DatasetImportRow
                 └─ DatasetVersion / DatasetVersionRow

KbDocumentSnapshot
  └─ GoldQaVersion / GoldQaVersionItem / expected_evidence
```

`DatasetRow` 与 `GoldQaItem` 应只是当前编辑视图；正式评测应只读 `DatasetVersion(Row)` 与 `GoldQaVersion(Item)`。创建任务时服务端应在同一事务读取 `Dataset.active_version_id` 或黄金集当前版本，并把 `dataset_version_id/gold_qa_version_id`、内容哈希、评分器版本、KB 文档快照写到 `Task.config`；请求方不得指定或覆盖该版本，Worker、重跑、报告和基线不得回读可编辑行或远端来源。新增数据模型与 Alembic 迁移是 M3 的首个实现门禁。

### 6.2 生命周期与双人复核

| 对象 | 状态 | 关键规则 |
| :--- | :--- | :--- |
| 目录来源 | `draft | active | suspended | archived` | 只有 `active` 来源可携带可导入 release；来源身份变更新建条目 |
| 目录 release | `draft → reviewing → approved`，或 `blocked | superseded` | release manifest 审核后不可改；批准/解除暂停人不得为提报人；`blocked` 立即阻止新导入 |
| 导入作业 | `queued → downloading → validating → parsing → review_ready → published`，或 `failed | rejected` | attempt/lease 决定可恢复性；只有 `review_ready` 能审核发布 |
| 数据集容器 | `draft | active | archived` | `active_version_id` 是唯一可评测入口；存在新 staging 时仍可保持旧 active 版本 |
| 数据集/黄金集正式版本 | `active | deprecated` | `deprecated` 仅保留历史报告，不得新建或重跑；版本内容永不原地修改 |
| 黄金候选 | `draft | reviewing | accepted | rejected` | 高风险/冲突证据依旧需两名审核者独立通过 |

发布者必须不同于 release/导入提报人。撤回、错误修订和有效期到期均要创建新版本并标记旧版本；历史报告保留版本 ID、内容哈希、评分口径和最小审计记录，禁止静默重写旧报告。

### 6.3 许可证、隐私与保留

1. 许可证检查是发布门禁，不是备注字段；特别是 `NC`、`SA`、受限测试、禁止再分发和数据用途限制，均需在导入前由非提报成员依据许可证/授权证据复核；需要法务确认时记录其证据引用与结论，不以“管理员”身份绕过复核；
2. 公开可下载不表示允许重新分发。平台默认只保留评测需要的最小制品和元数据，并在 UI/导出中遵守上游限制；
3. 含个人信息、未成年人信息、秘密、凭据或无关敏感文本的文档不得进入黄金集；
4. 数据制品、文档快照、审核理由与导入日志分别应用保留策略。正文清理后，历史报告保留哈希、版本和审计摘要，不能声称仍可恢复原文；
5. 所有下载令牌、上传授权文件和服务器凭据均只在受控后端使用，严禁进入日志、WS 事件、报告或模型上下文。

---

## 7. 安全、可靠性与可观测性

| 维度 | 设计 |
| :--- | :--- |
| 长短任务分离 | 成员登记/复核为短事务；下载、校验、解压、解析、去重和候选生成由 Worker 执行，API 不等待终态 |
| 队列一致性 | `DatasetImport` 与 `DatasetImportAttempt` 使用行锁、租约、attempt 上限和过期回收；阶段提交必须校验 lease，staging 完成与 `review_ready` 同事务 |
| 下载防护 | HTTPS/域名允许列表、每跳重定向校验、资源上限、内容类型与 SHA-256 校验；拒绝脚本执行与路径逃逸 |
| 产品边界 | 代码、多模态和对话偏好测试集不进入当前目录/导入/评测范围；未来若扩展，必须先修改 PRD、API 和执行安全方案 |
| 失败语义 | 来源/授权/格式问题为 `VALIDATION`，上游 4xx/5xx 为 `UPSTREAM`，作业超时为 `TIMEOUT`；禁止用空数据或 mock 成功降级 |
| 日志 | 仅记录数据源 ID、版本、制品哈希前缀、导入行数、错误码和耗时；不记录题目正文、答案、下载 Token、授权材料或完整 URL 参数 |
| 可观测性 | 记录下载成功率、校验失败率、解析拒绝率、审核采纳率、跨 split 重复率、版本可复现率与黄金可评测率 |

---

## 8. 测试策略

| 层级 | 必测场景 | 验证方式 |
| :--- | :--- | :--- |
| 来源登记 | 缺官方地址、revision、制品哈希、许可证证据、允许切分或 filter schema 时拒绝；提报人不能批准自己的 release | API/服务单测 |
| 下载制品 | 重定向越界、哈希不符、过大压缩包、路径穿越、未知 MIME | 下载器单测与恶意 fixture |
| 导入队列 | 重复请求复用、两个 Worker 竞争领取、租约过期、旧 attempt 回写、达到尝试上限 | 数据库并发集成测试 |
| 解析器 | 每个 parser 的标准行、空字段、标签错误、编码错误、题目重复、split 泄漏 | 固定离线制品 fixture |
| 版本冻结 | 修改当前编辑行或远端数据后，已建任务读取同一版本快照；发布时 revision 过期、重复发布和自审均被拒绝 | API + Worker 集成测试 |
| 黄金证据 | 缺文档快照、范围漂移、空 `expected_doc_ids`、冲突证据伪装为确定答案 | KB/Gold fixture |
| 忠实度 | 正确但无证据、证据不足时拒答、冲突时保留、Judge 分歧 | 受控 KB + Judge 桩 |
| 许可证治理 | `NC`、禁止再分发、授权撤回和过期版本不能发布/新建任务 | 审核状态机测试 |
| 回归 | 所有测试离线运行，不依赖远端 HF、GitHub、官方站点或可变排行榜 | CI 固定制品与哈希 |

---

## 9. 分期实施计划

| 里程碑 | 内容 | 前置条件 |
| :--- | :--- | :--- |
| **M0：契约闭环** | 已完成 PRD/API/本方案的目录/release 双人复核、独立 `DatasetImport` 队列、租约恢复、staging revision 发布和任务版本锁定设计 | 三份文档交叉审查通过 |
| **M1：平台基础** | 账号、协议档、会话与任务基础能力；本方案不新增目录、导入或黄金集实现 | 平台 M1 门禁通过 |
| **M2：手工数据集基线** | CSV/JSONL 手工数据集、规则评分、报告/基线与版本化的既有 M2 范围；本方案不新增公开目录导入 | 平台 M2 门禁通过 |
| **M3：目录导入与 RAG 黄金集** | 数据模型/Alembic、目录/release 管理、Worker 下载器与独立队列、首批受支持 parser、staging 审核/原子发布、任务版本锁定；KB 快照、黄金 QA、Hit Rate 与忠实度复核 | M0 通过；RAG/KB 真实可用；来源许可证证据已确认 |
| **后续产品版本** | 代码、多模态、对话偏好或新的任务族 | 必须先更新 PRD/API 并通过专项安全与评分评审；不属于当前 M3 |

每个里程碑单独分支与 PR。新增数据模型必须修改 `backend/shared/models.py` 并生成 Alembic 迁移；不得通过路由层临时 JSON 拼装快照，也不得把导入作业伪装为已成功评测任务。

---

## 10. 风险与处置

| 风险 | 等级 | 处置 |
| :--- | :--- | :--- |
| 数据集镜像或默认分支变化导致结果漂移 | 高 | 固定 revision、制品 SHA-256、解析器版本与正式数据集版本 |
| 上游许可证与内部/商用用途冲突 | 高 | 发布前许可证门禁；不清楚即 `rejected`，不以“公开可下载”推定许可 |
| 公开 test 已被模型训练污染 | 高 | 标注历史可比性；引入动态集和私有/受控 KB 集，不将其当作 RAG 忠实度证据 |
| 后续任务族被误纳入当前目录 | 高 | 目录只允许 PRD 已支持的任务族；代码、多模态和对话偏好必须先走新的产品/安全评审 |
| LLM Judge 与被测模型存在同源偏差 | 高 | profile 分离、低置信度二审、分歧人工复核，报告分列而非单一总分 |
| Benchmark 与黄金集混用 | 高 | 数据源用途、任务族、版本和权限隔离；正式黄金集只引用 KB 文档快照 |
| 答案标签、公式或选项解析错误 | 中 | parser fixture、上游行数/哈希核验、人工抽样和新版本修订 |
| 大文件导入拖垮 API 或磁盘 | 中 | Worker 队列、制品资源上限、临时目录清理与失败可重试 |

---

## 11. 修改代码文件与作用清单（V2.2 预期实施清单）

> 本次仅完成文档重构与契约表述对齐，未修改运行时代码、数据库或接口实现。下表是后续按里程碑实施的预期清单。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-测试数据集与黄金集采集技术方案.md` | V2.2：目录/release 双人复核、导入 attempt/租约、staging revision、版本冻结、许可证与忠实度设计 |
| `docs/AI测试与评估平台-PRD.md` / `docs/AI测试与评估平台-API.md` | 数据源、不可变 release manifest、导入队列、并发发布与任务快照的产品/API 唯一真相 |
| `backend/shared/models.py` + Alembic migration | M3 新增目录/release/review、制品快照、导入/attempt/staging、审核和版本关联模型；禁止手改数据库 |
| `backend/worker/app/`（新增导入执行器） | M3 受控下载、校验、解压、解析、lease 续约/回收与 staging 作业；不在 API 进程执行 |
| `backend/api/app/routers/datasets.py` / 新增目录治理路由 | M3 来源/release 登记与复核、导入状态、候选审核、原子版本发布的 REST 边界 |
| `backend/api/app/dataset_import/`（新包） | 纯本地 parser、manifest 校验、制品安全与字段规范化 |
| `frontend/src/views/Datasets.vue`、`frontend/src/api/http.ts`、`frontend/src/api/types.ts` | “导入公开基准”抽屉、目录筛选、导入作业轮询、staging 表格、来源抽屉与审核发布按钮 |
| `backend/worker/app/benchmark.py` / RAG 执行器 | 仅读取任务锁定的 `DatasetVersion` / `GoldQaVersion`，报告回显内容哈希与评分口径 |
| `backend/api/tests/`、`backend/worker/tests/` | 下载/解析 fixture、版本锁定、黄金证据、许可证状态和忠实度回归测试 |

---

## 12. V2.0 修改记录

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-测试数据集与黄金集采集技术方案.md` | 由原“社媒平台内容抓取适配”方案重构为“测试数据集与黄金集采集”方案；删除所有社交媒体、登录态、签名、下载器 sidecar 与站内搜索设计，新增标准数据集制品导入、解析、审核、版本、授权和黄金集证据化闭环 |

---

## 13. V2.1 修改记录

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-测试数据集与黄金集采集技术方案.md` | 补充基准数据集页的目录筛选、场景划分、独立异步导入、staging 表格保存与发布语义；明确首批目录条目与任务族边界 |
| `docs/AI测试与评估平台-PRD.md` | V1.14 将目录导入、staging 表格和审核发布纳入 Benchmark 功能与 M3 验收范围 |
| `docs/AI测试与评估平台-API.md` | V1.54 定义目录查询、导入作业、staging 行、重试与发布接口；未修改运行时代码或数据库 |

---

## 14. V2.2 修改记录

| 实际修改文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-测试数据集与黄金集采集技术方案.md` | 完成来源/release 治理、成员同权双人复核、独立导入 attempt/租约、稳定 staging ID/revision、版本锁定和 M3 对齐；移除代码/多模态/对话偏好进入当前产品的表述 |
| `docs/AI测试与评估平台-PRD.md` | V1.15 固化目录治理、队列恢复、并发发布和 M3 范围 |
| `docs/AI测试与评估平台-API.md` | V1.55 固化目录治理接口、导入 Worker 队列约束、staging 乐观并发和任务/报告版本快照 |
