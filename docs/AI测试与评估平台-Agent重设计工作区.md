# AI 测试与评估平台 Agent 重设计工作区

> 版本：V0.2
> 状态：模型调用层首个实现完成，Harness 与 Agent 范式仍冻结
> 审查日期：2026-08-22

## 当前边界

旧 Agent、Harness、模型调用层与运行时实现已从本分支移除，避免旧路径与新设计并存。以下目录仅保留包边界文件，暂不承载实现：

- `backend/api/app/agent/`
- `backend/api/app/harness/`
- `backend/api/app/llm/`
- `backend/api/app/runtime/`

API、Worker、数据库模型、迁移和前端平台能力保持不变。Agent WebSocket、Agent 偏好、模型生成候选数据、模型生成用例等入口在重建设计期间明确返回能力暂不可用，不再调用旧实现。

## 首个落地决策：LangGraph 模型调用层

模型调用层已采用 LangGraph 实现最小单节点调用图，代码位于
`backend/api/app/llm/`，具体契约与边界见
`docs/AI测试与评估平台-模型调用层LangGraph重设计.md`。该层只负责一次模型调用、三协议适配和流式事件投影，尚未接入 Agent WebSocket、Harness、工具或任务队列。

## 待重新确定的两项设计

1. Harness：定义输入输出契约、工具执行边界、事件模型、取消与错误归一化；
2. Agent 范式：确定单轮调用、ReAct、计划/反思等能力是否需要，以及它们与 Harness 的依赖关系。

在三项设计完成并评审前，不恢复旧 Agent 代码，不新增并行实现，不新增数据库迁移。

## 修改代码文件与作用清单

本次重置清理旧 Agent/Harness/LLM/Runtime 实现、相关测试与阶段文档；本轮新增 LangGraph 模型调用层契约、网关、依赖和单测。核心 API、Worker、数据库和前端未删除。
