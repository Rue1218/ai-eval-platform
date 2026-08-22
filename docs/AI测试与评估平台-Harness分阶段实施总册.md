# AI 测试与评估平台 — Harness 分阶段实施总册

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 分阶段实施总册 |
| 版本 | V1.5 |
| 审查日期 | 2026-08-22 |
| 用法 | 每个阶段先读对应施工文档的五块分析（与阶段 0 同一模板），再开分支写代码。架构文档第七至十一章只做需求索引；**第十二章为覆盖矩阵与挂起项** |

权威目标架构仍是 [`docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md`](docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md)。本总册只负责「按阶段开工」与「首期覆盖边界」，不新增对外协议。

| 阶段 | 文档 | 分支 | 一句话 | 分析状态 |
| :--- | :--- | :--- | :--- | :--- |
| 0 | [阶段0-契约骨架](docs/AI测试与评估平台-Harness阶段0-契约骨架.md) V1.3 | `feat/harness-contracts` | 契约 + tracing；活路径不动 | 验收完成，已合入 `main` |
| 1 | [阶段1-单调用路径](docs/AI测试与评估平台-Harness阶段1-单调用路径.md) V1.3 | `feat/harness-single-call` | 编排/执行/反馈接管单工具循环 | 验收完成，已合入 `main` |
| 2 | [阶段2-链路追踪与取消](docs/AI测试与评估平台-Harness阶段2-链路追踪与取消.md) V1.3 | `feat/harness-trace-cancel` | 强制 trace/cancel + 三张审计表 | 验收完成，已合入 `main` |
| 3 | [阶段3-并行与流式收尾](docs/AI测试与评估平台-Harness阶段3-并行与流式收尾.md) V1.3 | `feat/harness-parallel-streaming` | 批次并行能力默认关；流式终态 | 验收完成（105 项 Harness 回归通过），待合入 `main` |
| 4 | [阶段4-记忆层接入](docs/AI测试与评估平台-Harness阶段4-记忆层接入.md) V1.2 | `feat/harness-memory-port` | MemoryPort + Redis/pgvector；不接 LightRAG | 五块分析完成（V1.2 窗口布局升 P0、收紧 MemoryQuery）；**尚未写代码** |

规则：

1. 一阶段一分支一 PR；合入后删旧双实现。
2. 全程 WS / REST 以 API.md 为准，禁止私自加字段。
3. 后一阶段不得重定义前一阶段冻结的类型名与行为；要改先改对应阶段文档。
4. 阶段 0 必须先合入 `main`，再拉阶段 1 分支；禁止在 `feat/harness-contracts` 上续堆阶段 1–4。
5. **目标架构全量 ≠ 首期五阶段。** 第二章项目树与第四章 MCP、第六章 `security/` 中未列入下表「首期归属」的条目，禁止在阶段 1–4 PR 里顺手实现。

开工顺序：先确认阶段 0 代码合入 → 按阶段 1 文档写代码 → 2 → 3 → 4。

---

## 首期覆盖矩阵（对照架构第一至六章）

此表回答「五阶段合入 `main` 之后，目标架构还剩什么」。阶段施工文档不得假装这些挂起项已经有主。

| 架构条目 | 出处 | 首期归属 | 说明 |
| :--- | :--- | :--- | :--- |
| Trace / Cancel / ToolCall / ErrorClass / MemoryPort 类型 + `normalize` Fail-fast | §2.2、§3.5、§6.2 | 阶段 0 | 已落地 |
| 单调用 Parser / Facade / 观察回填 / `harness/llm` 正文 | §5.1、§5.3 | 阶段 1 | 现网四项多媒体工具经注册表分派，**不搬** `imagegen.py` 等正文 |
| 强制 `trace`/`cancel`、`/stop`、Alembic 三表、结构化日志带 trace | §2.2、§4.4、§5.4 | 阶段 2 | 100ms SLO **不含**尚未存在的 MCP CancelledNotification |
| `ParallelFacade`、正确 `merge_batch`、`FINALIZING_STREAM` | §3.2.1、§3.2.2 | 阶段 3 | 运行默认仍串行 |
| Context 只经 MemoryPort；Redis 短期 + PG 归档 + pgvector | §2.1、§3.1、§5.2 | 阶段 4 | 窗口最小布局为本阶段 P0，不是可选项 |
| MCP `stdio` / Streamable HTTP / WebSocket custom、`session_pool`、`eval_core` 适配器 | §4.1 | **挂起** | 现网短工具不是 MCP JSON-RPC；§5.3 五阶段未列此项 |
| `file_sandbox.py` 与任意路径拒绝 | §4.2 | **挂起** | 现网多媒体工具无通用文件根 |
| 长任务完整控制面：`pending` + `idempotency_key` + Worker 订阅进度 | §4.3 | **挂起** | 阶段 1 只包装 `assert_short_tool`；入队仍走现网 `long_tasks.py` |
| `security/policy.py` `consent.py` `secrets.py` | §6.1 | **挂起** | 确认卡继续 api 层 `AppError`（§6.3）；不在阶段 1–4 迁入 |
| `reflect.py` / `plan.py` 迁入 `orchestration/` | §5.1 | **挂起** | 阶段 1 明确不迁复核门禁 |
| `persona.py` → `prompts/system.yaml`；`planner-output.schema.json` | §1.3、§5.1 | **挂起** | 阶段 0 只落 ReAct Schema |
| LightRAG 适配器、`kind=rag` 真评测 | §5.1、§5.2 | **挂起** | 禁止创建 `long_term_lightrag.py` |
| 多副本 `/stop` registry 迁 Redis | 驾驭工程说明 | **挂起** | 阶段 2/4 均禁止借记忆层做 abort 表 |

---

## 阶段之间容易漏掉的裁决（开工前必读）

1. **架构预算表数字不得当运行默认。** `HARNESS_MAX_REACT_STEPS=6` / `TURN_DEADLINE_S=60` 与产品 4/5/180s 冲突；阶段 2 只接入键名，未设 env 时行为仍是产品常量。指纹 / 连续可重试 / 上下文重建的**执行语义**默认关闭，避免悄悄改现网循环次数。
2. **阶段 0 Schema 不能直接吃架构 §3.2.1 示例。** 现网/阶段 0 要求顶层必填 `thought`/`tool`/`arguments`/`done`；架构批次示例只有 `thought`+`tool_calls`+`done`。阶段 3 必须改成 `oneOf`（单调用 \| 批次），禁止在阶段 1 提前放宽。
3. **§5.1「两项多媒体」过时。** 现网是四项：`image.generate`、`audio.voiceclone`、`audio.speech_recognition`、`audio.speech_synthesis`（含 `mimo_audio.py`）。阶段文档以四项为准。
4. **`ErrorClass` 枚举已在阶段 0 齐，行为按阶段摊。** `MISSING_TOOL` / `DONE_TOOL_CONFLICT` / `PARALLEL_POLICY_VIOLATION` / `BUDGET_EXHAUSTED` 的回填语义分别在阶段 3 / 3 / 3 / 2（仅内部记录，默认不改对外停工具形状）。
5. **挂起项出现在空壳目录里不等于已实现。** `execution/mcp/`、`security/`、`file_sandbox.py` 在阶段 4 结束后仍应是空壳或未引用。

---

## 本次文档变更范围

V1.5：同步阶段 0–2 已合入状态与阶段 3 已完成、待合入状态；阶段 4 和目标架构挂起项不变。

| 文件 | 作用 |
| :--- | :--- |
| `docs/AI测试与评估平台-Harness分阶段实施总册.md` | 更新首期阶段真实交付进度 |
| `docs/AI测试与评估平台-Harness阶段3-并行与流式收尾.md` | 记录阶段 3 验收、实现范围与验证命令 |
