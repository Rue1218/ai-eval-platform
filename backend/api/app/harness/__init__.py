"""Harness 新运行时：六层模块（契约/记忆/提示词/上下文/编排/执行/反馈/安全/技能）。

- ``contracts``：NodeEvent/PlanArtifact 等跨层契约（M7）；
- ``memory``：GraphState 主体 + 工作/情景/压缩/偏好记忆 + Checkpointer（M3）；
- ``prompts``：系统策略与阶段输出协议（M1）；
- ``context``：窗口算法/装配/observation 脱敏/compact/meter（M2）；
- ``orchestration``：路由/预算/门禁/规划/确认卡（M4）；
- ``execution``：工具注册表/绑定/分发/长任务桥接（M5）；
- ``feedback``：规则门禁/归一/模型核对/失败预算/事件隔离（M6）；
- ``security``：递归脱敏与确认卡行锁（M8）；
- ``skills``：技能目录与启用门禁（M10）。

各子包自带 re-export；本包不聚合顶层导出，避免循环依赖。
"""
