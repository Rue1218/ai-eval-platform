# AI 测试与评估平台 — Harness 分阶段实施总册

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness 分阶段实施总册 |
| 版本 | V1.3 |
| 审查日期 | 2026-08-21 |
| 用法 | 每个阶段先读对应施工文档的五块分析（与阶段 0 同一模板），再开分支写代码。架构文档第七至十一章只做需求索引 |

权威目标架构仍是 [`docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md`](docs/AI测试与评估平台-Harness六层ReAct核心架构设计.md)。本总册只负责「按阶段开工」，不新增对外协议。

| 阶段 | 文档 | 分支 | 一句话 | 分析状态 |
| :--- | :--- | :--- | :--- | :--- |
| 0 | [阶段0-契约骨架](docs/AI测试与评估平台-Harness阶段0-契约骨架.md) V1.2 | `feat/harness-contracts` | 契约 + tracing；活路径不动 | 五块分析完成；代码已落地，待合入 |
| 1 | [阶段1-单调用路径](docs/AI测试与评估平台-Harness阶段1-单调用路径.md) V1.2 | `feat/harness-single-call` | 编排/执行/反馈接管单工具循环 | 五块分析完成；**尚未写代码** |
| 2 | [阶段2-链路追踪与取消](docs/AI测试与评估平台-Harness阶段2-链路追踪与取消.md) V1.1 | `feat/harness-trace-cancel` | 强制 trace/cancel + 三张审计表 | 五块分析完成；**尚未写代码** |
| 3 | [阶段3-并行与流式收尾](docs/AI测试与评估平台-Harness阶段3-并行与流式收尾.md) V1.1 | `feat/harness-parallel-stream` | 批次并行能力默认关；流式终态 | 五块分析完成；**尚未写代码** |
| 4 | [阶段4-记忆层接入](docs/AI测试与评估平台-Harness阶段4-记忆层接入.md) V1.1 | `feat/harness-memory-port` | MemoryPort + Redis/pgvector；不接 LightRAG | 五块分析完成；**尚未写代码** |

规则：

1. 一阶段一分支一 PR；合入后删旧双实现。
2. 全程 WS / REST 以 API.md 为准，禁止私自加字段。
3. 后一阶段不得重定义前一阶段冻结的类型名与行为；要改先改对应阶段文档。
4. 阶段 0 必须先合入 `main`，再拉阶段 1 分支；禁止在 `feat/harness-contracts` 上续堆阶段 1–4。

开工顺序：先确认阶段 0 代码合入 → 按阶段 1 文档写代码 → 2 → 3 → 4。
