# 用例 Skill 二次开发

版本：V1.1 ｜ 审查日期：2026-09-28

本项目将需求转为人工可执行的功能测试用例，最终保存为待确认草稿。本次将原提示词式生成改为真实的文件技能加载，并把页面生成流程拆为需求分析、测试设计、候选审核三个阶段。

## 开源来源与保留方式

选择 [jaktestowac/awesome-copilot-for-testers / designing-functional-tests](https://github.com/jaktestowac/awesome-copilot-for-testers/tree/8910672e674853caf0e68dbffc59c39869990203/skills/designing-functional-tests)，采用 MIT 许可证。固定提交 `8910672e674853caf0e68dbffc59c39869990203`，不在请求期间拉取上游最新版。

`backend/shared/case_skills/upstream/designing-functional-tests/` 保留原 `SKILL.md`、两份 resources 模板、原仓库 LICENSE 和 `ORIGIN.json`。清单记录仓库、提交、文件路径及逐文件 SHA-256；回归测试验证原件未被二次开发修改。`.gitattributes` 关闭原件目录的换行转换，保证 Windows 检出后仍保持原始校验值。项目适配版本位于独立的 `functional-test-design/` 目录，并复制完整许可证。

保留上游需求就绪检查、风险优先设计、原文假设区分、单一行为与可观察预期、人工用例模板；适配为中文平台字段、六策略配比、草稿审核流程。上游自动化交接建议不进入本项目生成范围。

## 渐进披露的实际入口

| 当前需求 | 加载文件 | 执行入口 |
| --- | --- | --- |
| 发现技能 | SKILL.md 的 YAML 头部 | `/generation-skills` 或 `case.skill(section=catalog)` |
| 选择技能工作流 | SKILL.md 正文 | `case.skill(section=workflow)` / 生成服务加载器 |
| 需求分析 | references/design.md | `/ai-design` / Worker 第一阶段 |
| 展开人工用例 | references/cases.md | `/ai-generate` / Worker 第二阶段 |
| 边界、等价类 | references/inputs.md | 仅相关策略权重大于 0 时读取 |
| 状态、场景 | references/flows.md | 仅相关策略权重大于 0 时读取 |
| 对话辅助审核 | references/review.md | `case.skill(section=review)`，用户仍需独立确认入库 |

目录阶段不会读取技能正文或参考文件。模型没有文件路径权限，只能请求登记章节。页面及 Worker 共用 `shared.case_skill` 与 `shared.case_design`；提示词中不会常驻全部参考资料。测试通过记录实际文件读取路径验证这个边界。

## 数据与运行约束

- 分析产生不超过 24 个测试点，平台分配 `TP-NNN` ID 并计算来源 SHA-256。引用必须是需求原文中真实存在的连续片段。
- 页面允许调整测试点并选择生成范围；修改来源后必须重新分析。生成接口再次校验来源和引用。
- 候选需绑定所选测试点，未知关联和重复项被过滤；需求引用与风险由设计快照回填。按整数配额控制数量，不用重复内容凑数。
- 页面两次调用各使用现有 HTTP 模型预算；对话 Worker 两阶段共享 280 秒总调用时限，阶段间复验取消及租约，不自动重放模型请求。
- 不确定业务预期留空并标记待澄清。生成失败保留已有候选；采纳保存草稿与确认入库是独立操作。历史任务和报告继续只读。
- 技能资源缺失或头部损坏时，在模型调用前返回明确的资源不可用错误；目录仍然只检查元信息，不提前读取参考资源。Excel 导出将需求引用、用例内容与自定义表头写为纯文本，避免原文被解析为公式。

## 维护与验证

调整设计方法应修改对应参考资源；字段契约变动先同步 API/PRD、解析校验和前端类型。上游升级需单独核对许可证、保存新提交与哈希，评审差异后再更新适配版本，不能用在线地址覆盖运行资源。

本地验证（2026-09-28）：API 全量 2454 passed / 99 skipped，相关组 167 passed；Worker 全量 102 passed；前端单元测试 124 passed，用例页浏览器回归 44 passed，Agent 页面回归 29 passed。Ruff 检查 API app/tests 与 shared（排除既有测试临时目录）、前端 typecheck/build、Skill 格式与上游 SHA-256 校验通过；前端 lint 为 0 errors，仍有 206 warnings，构建有现有大包提示。供应商响应在回归中被隔离模拟，未据此宣称生产模型联调或线上部署完成。

修改代码文件与作用清单：

- `backend/shared/case_skill.py`：目录、固定章节、阶段加载。
- `.gitattributes`：上游原件关闭换行转换，跨平台保留 SHA-256 校验值。
- `backend/shared/case_design.py`：设计结构、来源校验、候选追溯与去重。
- `backend/shared/casegen.py`：共享提示词与精确策略配额。
- API `schemas.py/routers/cases.py`、Worker `testcase.py`：两条生成入口共用技能。
- Harness 注册表、权限表及 Agent 提示词：模型按需读取 `case.skill`。
- `frontend/src/composables/useCaseGeneration.ts`：来源与请求状态，失败保留候选。
- `CaseGenerationStudio.vue/CaseCandidateReview.vue/Cases.vue`：三阶段工作台、审核及用例库关联。
- API `test_case_skill.py/test_cases_audit.py`、Worker `test_testcase.py`、前端 `casesAudit.spec.ts`：分层加载、来源权限、取消与交互回归。
