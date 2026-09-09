---
id: skill-benchmark
name: 基准评测
kind: benchmark
version: 1.0
enabled: true
summary: 执行大模型基准评测
---
## 工作流

1. 确认协议档、数据集与评测模型槽位；缺槽发确认卡，不得直接入队。
2. 确认卡 kind=benchmark；sample_size 默认 1000。
3. 用户确认后由 Worker 执行两类协议调用、规则评分、预算熔断、断点续跑。
4. 对话内禁止同步跑完评测，禁止伪造 succeeded。
