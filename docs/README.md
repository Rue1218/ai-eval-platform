# 文档索引

> 版本：V1.2 ｜ 审查日期：2026-09-14
> 本目录保留 38 份设计与契约文档。**权威优先级**：根目录 `AGENTS.md`（实现状态地图）> 本目录核心契约 > 其他设计稿。
> 含历史实现引用（`agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等已删除模块）的文档已在文首加维护标注，请以标注为准。
> 引用路径失效检查：`python tools/check-doc-links.py`。

## 核心契约（权威）

| 文档 | 说明 |
| --- | --- |
| [API.md](./AI测试与评估平台-API.md) | 前后端接口契约（WS v2 帧、REST、错误码）；JSON 以本文为准 |
| [PRD.md](./AI测试与评估平台-PRD.md) | 产品需求（功能唯一权威） |
| [Agent 开发文档](./AI测试与评估平台-Agent开发文档.md) | Agent 运行时说明书（AgentLoop 单入口） |
| [设计规范](./AI测试与评估平台-设计规范.md) | 错误码文案、确认卡字段名、调度中心规范 |
| [数据库设计](./AI测试与评估平台-数据库设计.md) | 表结构与迁移约定 |
| [内部 MCP 与工具契约设计规范](./AI测试与评估平台-内部MCP与工具契约设计规范.md) | 工具契约与命名规范 |

## Harness 层设计

| 文档 | 说明 |
| --- | --- |
| [六层架构](./AI测试与评估平台-Harness-六层架构.md) | 总览与分层职责 |
| [跨层契约层](./AI测试与评估平台-Harness-跨层契约层.md) / [跨层安全](./AI测试与评估平台-Harness-跨层安全.md) | 跨层约束 |
| [记忆层](./AI测试与评估平台-Harness-记忆层.md) / [上下文工程层](./AI测试与评估平台-Harness-上下文工程层.md) / [提示词工程层](./AI测试与评估平台-Harness-提示词工程层.md) | 数据与提示词 |
| [编排层](./AI测试与评估平台-Harness-编排层.md) / [执行层](./AI测试与评估平台-Harness-执行层.md) / [反馈层](./AI测试与评估平台-Harness-反馈层.md) | 编排与执行 |
| [技能体系](./AI测试与评估平台-Harness-技能体系.md) / [运行时基础设施](./AI测试与评估平台-Harness-运行时基础设施.md) / [协议探针](./AI测试与评估平台-Harness-协议探针.md) | 支撑能力 |
| [Harness 需求文档](./AI测试与评估平台-Harness需求文档.md) | 需求基线 |

## 沙箱与工作区（现行方案）

- [工作区与沙箱设计方案](./AI测试与评估平台-工作区与沙箱设计方案.md)
- [沙箱方案-G2G3 实施评估与 PoC 结论](./AI测试与评估平台-沙箱方案-G2G3实施评估与PoC结论.md)
- [沙箱执行方案重设计](./AI测试与评估平台-沙箱执行方案重设计.md)（含废弃稿标注）
- [工作区与沙箱方案-团队评审记录](./AI测试与评估平台-工作区与沙箱方案-团队评审记录.md)
- [Agent 原生工具装配方案](./AI测试与评估平台-Agent原生工具装配方案.md) / [P1 冒烟清单](./AI测试与评估平台-原生工具装配-P1冒烟清单.md)

## 实施与联调记录

- [AgentLoop 后端实施记录](./AI测试与评估平台-AgentLoop后端实施记录.md) / [AgentLoop 后端架构设计](./AI测试与评估平台-AgentLoop后端架构设计.md) / [AgentLoop 前端重写与联调计划](./AI测试与评估平台-AgentLoop前端重写与联调计划.md)
- [H5 持久化 HITL 收尾演练](./AI测试与评估平台-H5持久化HITL收尾演练.md)
- [混合引擎 H0H3 预发 Smoke 清单](./AI测试与评估平台-混合引擎H0H3预发Smoke清单.md)

## 接入规范与设计草案

- [模型思考模板自动继承实施方案](./AI测试与评估平台-模型思考模板自动继承实施方案.md)：V1.0 待实施；供应商与协议模板自动继承、模型级覆盖、请求快照与验收，不代表已生效接口。
- [MCP 接入与媒体生成规范](./AI测试与评估平台-MCP接入与媒体生成规范.md)：V0.3，Streamable HTTP 媒体 MCP、协议档模型配置、AgentLoop 图片/视频预览；媒体任务持久化和资产归档待实现。

## 已删除的历史方案（Git 留档）

> 以下 19 份文档原已被本索引列为历史归档，本次从工作目录删除。链接固定到清理前的 Git 提交，仅供追溯旧决策，不作为现行实施依据。
> 尚存文档中的旧文件名、章节号和版本号可能属于历史叙述；需查阅原稿时使用以下链接。当前 Agent 实现查阅 AgentLoop 系列和 API 契约。

- **Agent 系列**：[内容块交错流式调用规划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E5%86%85%E5%AE%B9%E5%9D%97%E4%BA%A4%E9%94%99%E6%B5%81%E5%BC%8F%E8%B0%83%E7%94%A8%E8%A7%84%E5%88%92.md) / [混合范式与架构完善](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E6%B7%B7%E5%90%88%E8%8C%83%E5%BC%8F%E4%B8%8E%E6%9E%B6%E6%9E%84%E5%AE%8C%E5%96%84.md) / [框架 LangGraph 与 WebSocket 重设计](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E6%A1%86%E6%9E%B6LangGraph%E4%B8%8EWebSocket%E9%87%8D%E8%AE%BE%E8%AE%A1.md) / [消息链路兼容修复](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E6%B6%88%E6%81%AF%E9%93%BE%E8%B7%AF%E5%85%BC%E5%AE%B9%E4%BF%AE%E5%A4%8D.md) / [优化遗留项与 SDK 迁移方案](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E4%BC%98%E5%8C%96%E9%81%97%E7%95%99%E9%A1%B9%E4%B8%8ESDK%E8%BF%81%E7%A7%BB%E6%96%B9%E6%A1%88.md) / [重设计工作区](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Agent%E9%87%8D%E8%AE%BE%E8%AE%A1%E5%B7%A5%E4%BD%9C%E5%8C%BA.md)
- **Harness 系列**：[团队开发与联调规划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-Harness%E5%9B%A2%E9%98%9F%E5%BC%80%E5%8F%91%E4%B8%8E%E8%81%94%E8%B0%83%E8%A7%84%E5%88%92.md) / [dsh 借鉴与 AgentHarness 改进方案](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-dsh%E5%80%9F%E9%89%B4%E4%B8%8EAgentHarness%E6%94%B9%E8%BF%9B%E6%96%B9%E6%A1%88.md) / [dsh 借鉴与 AgentHarness 开发计划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-dsh%E5%80%9F%E9%89%B4%E4%B8%8EAgentHarness%E5%BC%80%E5%8F%91%E8%AE%A1%E5%88%92.md)
- **引擎系列**：[混合驱动引擎架构](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E6%B7%B7%E5%90%88%E9%A9%B1%E5%8A%A8%E5%BC%95%E6%93%8E%E6%9E%B6%E6%9E%84.md) / [环境审计](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E6%B7%B7%E5%90%88%E9%A9%B1%E5%8A%A8%E5%BC%95%E6%93%8E%E7%8E%AF%E5%A2%83%E5%AE%A1%E8%AE%A1.md) / [开发计划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E6%B7%B7%E5%90%88%E9%A9%B1%E5%8A%A8%E5%BC%95%E6%93%8E%E5%BC%80%E5%8F%91%E8%AE%A1%E5%88%92.md) / [模型调用层 LangGraph 重设计](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E6%A8%A1%E5%9E%8B%E8%B0%83%E7%94%A8%E5%B1%82LangGraph%E9%87%8D%E8%AE%BE%E8%AE%A1.md) / [ReAct 与 MCP 工具调用重构方案](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-ReAct%E4%B8%8EMCP%E5%B7%A5%E5%85%B7%E8%B0%83%E7%94%A8%E9%87%8D%E6%9E%84%E6%96%B9%E6%A1%88.md)
- **SessionState 系列**：[结构化任务状态机升级方案](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-SessionState%E7%BB%93%E6%9E%84%E5%8C%96%E4%BB%BB%E5%8A%A1%E7%8A%B6%E6%80%81%E6%9C%BA%E5%8D%87%E7%BA%A7%E6%96%B9%E6%A1%88.md) / [与任务看板修改文件清单](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-SessionState%E4%B8%8E%E4%BB%BB%E5%8A%A1%E7%9C%8B%E6%9D%BF%E4%BF%AE%E6%94%B9%E6%96%87%E4%BB%B6%E6%B8%85%E5%8D%95.md)
- **计划系列**：[开发计划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E5%BC%80%E5%8F%91%E8%AE%A1%E5%88%92.md) / [前端开发计划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E5%89%8D%E7%AB%AF%E5%BC%80%E5%8F%91%E8%AE%A1%E5%88%92.md) / [后端开发计划](https://github.com/Rue1218/ai-eval-platform/blob/45a7f49260c37b986d19c3b880e5d2d9cf1a1692/docs/AI%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%84%E4%BC%B0%E5%B9%B3%E5%8F%B0-%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91%E8%AE%A1%E5%88%92.md)

## 其他

- [测试数据集与黄金集采集技术方案](./AI测试与评估平台-测试数据集与黄金集采集技术方案.md)
- [上下文双圆环与容量度量技术方案](./AI测试与评估平台-上下文双圆环与容量度量技术方案.md)
- [协议档供应商思考适配](./AI测试与评估平台-协议档供应商思考适配.md)
- [原型图设计方案](./AI测试与评估平台-原型图设计方案.md)
- [备用自动部署方案](./AI测试与评估平台-备用自动部署方案.md)

## 修改文件与作用清单（V1.1）

- 删除上述 19 份已归档的旧方案与开发计划，历史内容保留于 Git。
- 更新本索引的数量、历史文档入口和追溯说明。
- 将保留 Markdown 文档中指向已删除文件的链接改为固定提交链接，保留原有标题与历史章节定位。
- 保留核心契约、AgentLoop、Harness 分层文档、沙箱安全方案及尚未确认废弃的设计稿；本次不改变产品范围或实现状态。

## 修改文件与作用清单（V1.2）

- 新增模型思考模板自动继承方案入口，计数更新为 38 份；应用代码与现行契约不变。
