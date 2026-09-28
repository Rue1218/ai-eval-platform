---
id: skill-testcase
name: 用例生成
kind: testcase
version: 1.0
enabled: true
summary: 根据需求生成待确认测试用例
---
## 工作流

1. 确认需求文本或来源文件；缺少来源时先澄清，不猜测需求规则。
2. 确认目标条数（1–80，默认 45）与六策略配比（整数百分比合计 100，默认 40/25/15/10/5/5）；未指定时使用默认值，不自行编造需求规则。
3. 确认卡 kind=testcase 可带 max_count、strategy_weights；后台按同一参数生成并保存到用例集草稿，72h 内由用户在用例页审核。
4. 不得在对话进程内同步生成完整用例集。
