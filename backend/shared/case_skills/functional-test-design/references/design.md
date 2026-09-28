# 需求就绪与测试设计

改编自上游 test-plan-template.md。先提取范围、角色、前置条件、业务规则和预期结果，再形成风险优先的测试点目录。

- 一个测试点对应一个可验证行为；引用需求中连续、原样的短句作为 source_quote，不能杜撰引用。
- 识别正向、失败、边界、权限、重试/中断恢复、持久化与状态变化。只依据文档实际涉及的场景设计。
- risk 使用 high / medium / low；资金、权限、数据变更和关键主流程通常优先。
- 已知限制写入 constraints；不确定规则写入 questions，必要假设写入 assumptions 并保持显式。
- expected 描述可观察结果；没有依据时为空，不能自创业务规则。
- 测试点可供用户修改和选择；此阶段不展开完整操作步骤、不生成用例、不宣称已覆盖全部需求。

输出一个 JSON 对象：
{"summary":"测试范围","assumptions":[],"questions":[],"test_points":[{"title":"测试点","module":"模块","source_quote":"需求原文","risk":"high","expected":"已知结果","strategies":["positive","negative"],"constraints":"约束或待澄清事项"}]}

最多 24 个测试点；ID 由平台分配，不能指定持久用例 ID。
