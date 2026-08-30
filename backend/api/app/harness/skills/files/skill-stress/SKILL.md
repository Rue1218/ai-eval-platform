---
id: skill-stress
name: 压测
kind: stress
version: 1.0
enabled: true
summary: 执行共享压测
---
## 工作流

1. 对话路径不得发 kind=stress 确认卡。
2. 压测仅在质量任务 succeeded 且 with_stress=true 时由系统派生。
3. 用户口头要求压测时，应引导先完成质量评测（先评后压）。
