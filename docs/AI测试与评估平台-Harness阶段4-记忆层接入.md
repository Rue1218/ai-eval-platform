# AI 测试与评估平台 — Harness 阶段 4：记忆层接入

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 阶段 4 — 记忆层接入 |
| 版本 | V1.3 |
| 审查日期 | 2026-08-22 |
| 文档性质 | **施工中分析与交付状态文档**；当前仅完成第一批可单测的基础组件，未勾验收前禁止把 Redis/pgvector 当「已经迁完六层」 |
| 对应目标架构 | 架构文档 §2.1 / §3.1 / §5.2 / §5.3 / §5.4（消息表溯源列） |
| 前置阶段权威 | 阶段 0 已冻结 `MemoryPort` / `MemoryQuery` / `CompiledContext`（`trace_id` 必填）；阶段 3 仍未通过审查，待修项不因本阶段启动而失效 |
| 产品/协议裁决 | API.md `GET /api/sessions/{id}/messages` 的 `context_meter` 字段冻结；PRD 确认卡默认值不变 |
| 分支 | `feat/harness-memory-port` |
| 启动裁决 | 用户于 2026-08-22 明确授权受控启动阶段 4；该授权不解除阶段 3 的未验收结论，阶段 4 在完成自身验收前不得合入 `main` |
| 后续 | LightRAG / RAG 评测 **不在本阶段**；独立评审。禁止创建 `long_term_lightrag.py` |

---

## 1. 从架构文档抽出的需求（为什么先做阶段 4）

架构 §5.3 原文：

> 阶段 4  记忆层接入（Redis 短期状态 + PG 长期归档 + pgvector 知识检索），context/ 换用 MemoryPort

前三阶段可以仍让 `agent/context.py` 直接 `query(Message)`。本阶段要回答的产品问题：

**Context 工程只做本轮可见性决策（召回后的压缩、重排、窗口）；存取与检索只经 MemoryPort。换 Redis 或换 pgvector 实现时，窗口策略代码不动。对外 ContextMeter 看起来与现在一样。**

```text
用户目标 + 会话状态
  → Context 构造 MemoryQuery（含非空 trace_id、租户/会话/ACL）
  → MemoryPort.retrieve / append / forget
  → 压缩 → 重排 → WindowManager
  → CompiledContext（公开 token 账本）
  → 编排只消费 CompiledContext，不 import redis/sqlalchemy
```

`kind=rag` 在 LightRAG 未评审接入前 **不得** mock `succeeded`。`agent/lightrag_stub.py` 留在 api 层。

---

## 2. 现状差距

| 架构要求 | 现网 / 阶段 3 后 | 阶段 4 要补 |
| :--- | :--- | :--- |
| Context 不 import 存储 SDK | [`context.py`](backend/api/app/agent/context.py) 直接查 `Message` | `compiler.py` 只依赖 `MemoryPort` |
| Redis 短期态、幂等键、TTL | compose 已有 `redis` 服务；Harness 未用 | `short_term_redis.py`；Key 含 `trace:{trace_id}` |
| PG 对话归档带溯源 | 消息表无 `origin_trace_id` | Alembic 补 `source_id` / `version` / `origin_trace_id` |
| pgvector 知识检索 | 镜像含扩展；业务未建知识向量表 | `knowledge_store.py`；不新开向量库容器 |
| `MemoryQuery.trace_id` 非空 | 阶段 0 已强制 | 所有 retrieve/append 必须传入 |
| ContextMeter REST | `messages/skills/summary/headroom` 等已对前端 | **字段冻结**；内部 ledger 不得改对外 JSON |
| abort registry 多副本 | 仍在进程内 dict（阶段 2 裁决） | **本阶段不把 `/stop` registry 改 Redis**，除非另开扩容任务 |

阶段 0 目录空壳里的 `memory/*.py` 此时才允许填实现；此前必须保持空壳。

---

## 3. 需求分析

### 3.1 功能需求

| ID | 需求陈述 | 来源 | 优先级 |
| :--- | :--- | :--- | :--- |
| R4-1 | Context 只经 `MemoryPort.retrieve/append/forget`，生产代码不 import `redis` / `sqlalchemy` / LightRAG | §1.1、§2.1 | P0 |
| R4-2 | `MemoryQuery` 必须含租户/用户/会话/ACL/意图/`trace_id`（非空） | §3.1、阶段 0 MemoryQuery | P0 |
| R4-3 | 检索先 ACL/删除过滤，再相似度；无 `source_id` 不得当高可信事实 | §3.1 | P0 |
| R4-4 | Redis：回合状态、会话索引、幂等键；TTL；Key 含 `trace:{trace_id}` | §3.5、§5.2 | P0 |
| R4-5 | PG `conversation_store`：长期对话归档，带 `origin_trace_id` / `origin_span_id` | §5.2、§5.4 | P0 |
| R4-6 | pgvector `knowledge_store`：向量检索 + metadata 过滤；与业务数据同库 | §5.2 | P0 |
| R4-7 | `forget(source_id)` 后相关摘要失效，不得再注入窗口 | §3.1 压缩失效规则 | P0 |
| R4-8 | WindowManager：System/用户输入不可降级；Lost-in-the-Middle 最小布局（System 最前、observation 靠近用户问题、无 `source_id` 不进知识槽） | §3.1 阶段 C | P0 |
| R4-9 | `CompiledContext` 公开 token 账本；超额按槽位策略淘汰。对外 ContextMeter 键不变 | §3.1 账本表、API.md | P0 |
| R4-10 | ContextMeter REST 字段与现网一致 | API.md、前端只读该结构 | P0 |
| R4-11 | 单测用内存 Port，不强制本机 Redis/PG | 阶段 0 N0-4 精神 | P0 |
| R4-12 | 禁止 `long_term_lightrag.py`；`kind=rag` 不得 mock succeeded | §5.1、AGENTS.md | P0 |
| R4-13 | `retrieve` 拒绝空 `tenant_id`/`user_id`/`session_id`（阶段 0 类型允许空串，本阶段收紧行为，不改字段名） | §3.1、阶段 0 债务 | P0 |
| R4-14 | `llm/usage.py`：编排侧 token 用量回填 `TokenLedger`；`context/` 仍禁止 import `harness.llm` | §2 树 `usage.py`、§1.1 LLM 归属 | P1 |
| R4-15 | 完整五信号 rerank（authority/freshness/diversity…）允许先用启发式；禁止「按向量分原样塞中部」 | §3.1 阶段 C | P1 |

### 3.2 非功能需求

| ID | 需求 | 验收口径 |
| :--- | :--- | :--- |
| N4-1 | 基础设施只走 compose + Alembic + CD | 禁止服务器手工 apt redis / 手建扩展 |
| N4-2 | 审计三表（阶段 2）不迁 Redis | grep 无 redis 写 turns/spans/diagnostics |
| N4-3 | 中文注释；密钥不进记忆文本与日志 | AGENTS.md |
| N4-4 | Redis 不可用时的降级：单测内存实现；生产是否硬失败另裁——**生产缺 Redis 应 UPSTREAM/INTERNAL，不得静默空记忆当成功召回** | 避免幻觉 |

### 3.3 约束与裁决

1. **SDK 只出现在 `harness/memory/`。** `context/` 连类型提示都不要引入 `redis.Redis`。
2. **不把 `/stop` 会话表迁 Redis。** 那是多副本扩容，与记忆层不是同一需求。
3. **不把 `persona.py` 人设改成必须读 YAML** 才能对话（可并行，非本阶段门禁）。
4. **消息表改列必须 Alembic**，禁止手工 ALTER。
5. **对外 ContextMeter 字段冻结**；内部 `TokenLedger` 可以更细，但 `as_dict()` 键名以现网为准。
6. **召回 → 压缩 → 重排** 全在 Context；Memory 不知道 token 预算。
7. LightRAG 容器即使在 compose 里，本阶段也不得新建适配器文件、不得把 RAG 任务标成功。
8. **阶段 4 合入后仍为空壳（禁止顺手填）**：`execution/mcp/`、`file_sandbox.py`、`security/policy|consent|secrets`、`long_term_lightrag.py`、`planner-output.schema.json` 业务逻辑。
9. **生成式压缩若用模型**：必须经编排持有的 `harness/llm`（或现网 `app.llm` 再导出），claims 必须带 `source_id`；Context 包自己不得 import LLM。本阶段优先抽取式，生成式为超限兜底。

---

## 4. 细分功能点

### F4-1 MemoryPort 实现组合

- **输入**：阶段 0 Protocol。
- **处理**：`CompositeMemoryPort`：短期 Redis + 长期 PG；测试 `InMemoryMemoryPort`。
- **输出**：同一套 retrieve/append/forget。
- **验收**：Context 单测只注入内存 Port。

### F4-2 Redis 短期记忆

- **输入**：回合态、幂等键、`trace_id`。
- **处理**：`short_term_redis.py`；TTL；Key 格式含 `trace:{trace_id}`。
- **验收**：TTL 过期后 retrieve 不再命中；生产代码不在 context 包。
- **不做**：Redis Cluster、把审计表塞进来。

### F4-3 对话归档

- **输入**：本轮消息 / 摘要。
- **处理**：`conversation_store.py` 写 PG；补溯源列。
- **验收**：Alembic 可逆；记录能按 `origin_trace_id` 回放。

### F4-4 知识向量

- **输入**：已授权知识文档。
- **处理**：pgvector 表 + metadata 过滤。
- **验收**：无独立向量库容器；ACL 失败的文档不进结果。

### F4-5 forget / 撤权

- **输入**：`source_id`。
- **处理**：短期删除 + 长期标记/删除 + 摘要失效。
- **验收**：forget 后再 compile 不得出现该来源高可信项。

### F4-6 Context 编译器

- **输入**：用户目标、`MemoryPort`、当前 ToolResult。
- **处理**：召回 → 压缩 → 重排 → 窗口；输出 `CompiledContext`。最小布局：System+Schema 不可降级；用户输入不可降级；本轮 observation 靠近用户问题；无 `source_id` 的文本不进知识槽。
- **验收**：`context/` 文件 grep 无 `import redis` / `from sqlalchemy` / `from app.harness.llm`。
- **不做**：编译器里调 LLM 做「无来源摘要当事实」。

### F4-6b MemoryQuery 收紧

- **输入**：阶段 0 允许空 `tenant_id` 的模型。
- **处理**：`retrieve`/`append` 实现层拒绝空租户/用户/会话；可补 validator，类型名不变。
- **验收**：缺会话 id 的 query 不得返回「成功但空列表」冒充无命中。

### F4-7 ContextMeter 适配

- **输入**：现网 `context_meter()`。
- **处理**：内部可用 ledger 增强；`as_dict()` 对外键保持。
- **验收**：前端 ContextMeter 无需改字段。

### F4-8 现网 context.py 再导出

- **输入**：`run_compact`、`window_rows`、routers。
- **处理**：产品 API（`/compact`）继续走 `app.llm` 再导出调模型；窗口数据改经 Port。
- **验收**：`tests` 里 compact / messages 接口绿。

---

## 5. 怎么实现

### 5.1 依赖方向

```text
允许：  context/*  → contracts.memory、contracts.context、contracts.trace
允许：  memory/*   → redis、sqlalchemy、pgvector
允许：  orchestration → CompiledContext（不访问 Port 实现）
禁止：  context/*  → redis / sqlalchemy / lightrag / app.models（若必须读表，说明边界没切干净）
禁止：  新建 memory/long_term_lightrag.py
```

`agent/context.py` 迁完后只留再导出或薄适配给 REST。

### 5.2 实现顺序

1. 从已含阶段 3 的 `main` 拉分支。
2. Alembic：消息溯源列 + 知识向量表。
3. `InMemoryMemoryPort` 单测先绿（retrieve/append/forget/trace 必填）。
4. Redis 短期 + PG 归档 + pgvector。
5. compiler / window / provenance / rerank；ledger。
6. `context.py` / compact 接线；ContextMeter 兼容。
7. grep 隔离 + 全量 API/Agent 测试。

**当前进度（2026-08-22）**：已完成第 3 步的内存 Port 基础测试，以及第 5 步的纯 Context 编译、窗口、溯源和重排基础实现；Redis 适配器已写入骨架代码，但尚未完成依赖声明、集成测试和运行时装配。第 2、4、6、7 步仍未完成。

### 5.3 代码落点

| 功能点 | 文件 |
| :--- | :--- |
| F4-1 | `memory/ports.py` |
| F4-2 | `memory/short_term_redis.py`、`retention.py` |
| F4-3 | `memory/conversation_store.py`；`app/models.py` + Alembic |
| F4-4 | `memory/long_term_pgvector.py`、`knowledge_store.py` |
| F4-5 | `forget` 实现于各 store + compiler 丢弃失效摘要 |
| F4-6 | `context/compiler.py`、`window_manager.py`、`summarizer.py`、`reranker.py`、`provenance.py`、`policies.py` |
| F4-7 / F4-8 | `agent/context.py` 再导出；`routers/sessions.py` 不改 JSON 键 |

`harness/app.py` 此时才允许装配 Redis/PG Port；**仍然禁止**在 `__init__` 缓存 `TraceContext`。

---

## 6. 技术难点与对策

### 难点 1：Context 为了省事 import Session

现网 `window_rows` 就在 `context.py` 里查库。

**对策**：查库逻辑进 `conversation_store`。Context 只收 `list[MemoryRecord]`。PR 用 grep 门禁。

### 难点 2：Redis 故障被当成「没有记忆」

空结果会被模型当成事实缺口去猜。

**对策**：生产 retrieve 失败抬升为 `UPSTREAM`/`INTERNAL`（观察级可记内部枚举），禁止返回空列表冒充「召回成功但无命中」。单测内存 Port 除外。

### 难点 3：token 账本 vs ContextMeter 两套数字

**对策**：对外 REST 继续现网 `as_dict()`。Ledger 只给编排/内部审计。不要改前端字段名。

### 难点 4：摘要变成无来源知识

**对策**：压缩产物必须带 `source_id`；`forget` 后丢弃。禁止把 compact 摘要当 knowledge 写入向量库除非有明确 source。

### 难点 5：与阶段 2 审计表职责重叠

**对策**：turns/spans/diagnostics 仍只 PG。Redis 只放可过期回合态与幂等键。

### 难点 6：compose 已有 Redis，但本地 pytest 无 Redis

**对策**：默认内存 Port；集成测标记 `redis` skip。CI 阶段 4 可加 service，但不作为单元测试前置。

### 难点 7：空壳提前实现的回潮

阶段 0 曾误写 Redis 客户端后又收回。

**对策**：本阶段才填 `short_term_redis.py`。若发现阶段 1–3 PR 混入 Redis，必须回滚到空壳。

### 难点 8：窗口布局被标成 P1 后，MemoryPort 只包一层 `query(Message)`

那样阶段 4 名义迁完、Lost-in-the-Middle 仍不存在。

**对策**：最小布局列为 P0 验收。完整五信号 rerank 可以启发式，但不能把无来源长文本塞进窗口中部。

### 难点 9：`usage.py` 归属编排还是 Context

账本在 `CompiledContext`，调用权在编排。

**对策**：P1。若做：`orchestration` 读 `llm/usage` 后写入 ledger 字段；`context/` 不 import `llm/`。可不做则 ledger 先用估算 tokenizer，不得为此让 Context 调模型。

---

## 7. 验收清单

- [ ] `harness/context/` 生产代码不 import redis / sqlalchemy / LightRAG
- [ ] `MemoryQuery` 缺 `trace_id` 无法构造
- [ ] 内存 Port 单测覆盖 retrieve/append/forget
- [ ] 有 Redis 时 TTL 过期；forget 后不再注入
- [ ] Alembic 溯源列 + 知识表可逆
- [ ] 最小窗口布局：System 在前、observation 靠近用户问题、无 source_id 不进知识槽
- [ ] retrieve 空租户/会话不得冒充召回成功
- [ ] ContextMeter REST 字段与现网一致
- [ ] 无 `long_term_lightrag.py`；rag 任务不得 mock succeeded
- [ ] 审计三表仍在 PG；`/stop` registry 仍未伪装成已多副本
- [ ] `execution/mcp/`、`security/`、`file_sandbox` 仍未被活路径引用
- [ ] `ruff` + 相关 pytest 全绿

---

## 7.1 当前代码审查结论（V1.3）

本次仅审查 `feat/harness-memory-port` 相对 `origin/main` 的第一批实现；`ruff` 通过，`tests/harness/memory/test_memory_context.py` 的 4 项单测通过。该结果不构成阶段 4 验收，以下问题必须在合入前处理：

1. **P1：未接入活路径。** `compile_context()`、`CompositeMemoryPort` 和 `RedisMemoryPort` 没有被 `app/agent/` 或运行时装配引用，现网仍直接使用 `agent/context.py` 的数据库查询；因此记忆与窗口能力尚未对真实请求生效。
2. **P1：历史消息角色被改写。** `window_manager.py` 当前把除 system/session_state 外的所有 `ContextItem` 都输出为 `user`，未来接入后会把 assistant 历史和工具 observation 错当用户消息，破坏对话语义。
3. **P1：会话记录的归属校验可被缺失 metadata 绕过。** `is_record_visible()` 将缺少 tenant/user/session 的字段视作允许；对 conversation 记录而言，一条没有归属 metadata 的记录会被任意已通过 Query 校验的租户、用户和会话召回。必须按记录类型强制最小归属字段，并补跨租户/跨会话的拒绝测试。
4. **P1：Redis 适配器不可部署。** `RedisMemoryPort.from_url()` 依赖 `redis` 包，但项目依赖清单尚未声明该运行依赖，也没有 Redis TTL / 故障路径测试。
5. **P2：撤权容错不一致。** Redis `forget()` 遇到一条损坏的序列化记录会整体失败；retrieve 已选择跳过损坏记录，两处行为应统一，并记录受限服务端诊断。

上述问题与阶段 3 的待修项彼此独立；阶段 3 仍不得合入，阶段 4 也不得因基础组件已存在而提前合入。

---

## 8. 本阶段交付后（V1.0 六层首期闭环）

```text
六层运行时：契约 + 单调用 + 强制追踪取消 + 可选并行 + MemoryPort
仍不包含（见总册覆盖矩阵）：LightRAG、多副本 abort、MCP Transport / file_sandbox、
security/ 三文件、reflect/plan 迁入、persona YAML、外部 MCP 生态、自定义系统提示词
```

新 REST/WS 字段仍必须先改 API.md。后续 RAG 接入单独评审，不得在本阶段文档里开口子。

---

## 修改代码文件与作用清单

V1.3：根据已推送的第一批阶段 4 实现与代码审查更新真实交付状态。已实现内存 Port、Redis 适配器骨架、纯 Context 编译和基础单测；未实现运行时接线、PG/pgvector、Alembic、ContextMeter 对齐与 Redis 集成测试，且存在本章 §7.1 的合入阻塞项。

| 文件 | 作用 |
| :--- | :--- |
| `backend/api/app/harness/contracts/memory.py` | 收紧检索归属和 trace 校验契约 |
| `backend/api/app/harness/memory/ports.py`、`retention.py`、`short_term_redis.py` | 内存/组合 Port、保留期和 Redis 短期适配器骨架 |
| `backend/api/app/harness/context/compiler.py`、`window_manager.py`、`policies.py`、`provenance.py`、`reranker.py`、`retriever_facade.py`、`summarizer.py` | 纯 Context 召回、筛选、压缩、重排和窗口构建 |
| `backend/api/tests/harness/memory/test_memory_context.py` | 内存 Port 与基础窗口单测 |
| `docs/AI测试与评估平台-Harness阶段4-记忆层接入.md` | V1.3：施工实际状态、审查阻塞项和代码作用清单 |
