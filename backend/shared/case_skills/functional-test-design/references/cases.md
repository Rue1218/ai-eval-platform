# 人工用例结构

改编自上游 manual-test-cases-template.md，适配平台用例库字段和中文交付。

- 每条用例绑定一个 test_point_id，复用选中测试点的 ID。
- name 表达待验证行为，module / feature_point 定位模块和功能点。
- precondition 只写执行前必须成立的状态与准备数据，不把测试步骤塞入前置条件。
- steps 写成逐行编号的具体操作；expected 写出与操作对应、可观察的结果，避免仅写“正常”或“成功”。
- strategy 仅使用正向、反向、边界、等价类、状态迁移、场景。未分配配额的策略不生成。
- priority 使用 HX 核心、FHX 非核心、BJ 边界问题、YC 异常、ZD 中断、BL 遍历，不将上游 High/Medium/Low 直接写入平台优先级字段。
- 需求未给出确定预期时不要编造；expected 留空，test_type 标记“待澄清”。
- 每条用例只验证一个明确行为，feature_point 要能追溯到需求；不为达到数量上限堆砌重复用例。

每次只输出一个 JSON 数组，不要输出解释文字或代码围栏。每项含 test_point_id、name、module、feature_point、strategy、priority、precondition、steps（可执行操作步骤）、expected、test_type。
