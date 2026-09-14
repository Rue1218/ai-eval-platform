**Findings**

- [P1] 缺少可持久化的同画布比较图，无法完成截图级比对。
  Location: 本地轨迹样式预览。
  Evidence: 已在 Codex In-app Browser 打开预览并核对 `read` 工具的 Schema 状态，但当前工具没有将该截图保存为本地文件；也无法把它与用户源图置入同一比较输入。
  Impact: 可确认页面实际渲染和交互，但无法把本轮称为通过的视觉验收。
  Fix: 在可保存截图的浏览器环境，以相同视口导出源图和工具 Schema 面板，再生成一张并列比较图。

**Open Questions**

- 源图为 1647 × 709 像素的桌面轨迹页面；本次预览应在相同桌面宽度、工具 `read` 已选中且 Schema 标签激活的状态进行比较。

**Implementation Checklist**

- [x] 后端 `request_summary.tools[]` 改为 `name`、`description`、`parameters`。
- [x] 轨迹页面为工具事件默认打开 Schema，并保留旧 `parameters_schema` 回放兼容。
- [x] 加入工具标题、描述、可折叠 JSON Schema、关闭详情与事件数提示。
- [x] 执行后端契约测试、前端类型检查和前端单元测试。
- [ ] 在可用浏览器中完成同视口截图比较。

**Follow-up Polish**

- [P3] 视觉环境恢复后，可按实际截图微调 Schema 字体密度与右侧详情栏宽度。

## 比较记录

- 源视觉真相：`C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-faa83de3-8ea7-4304-a209-6297d4dfda62.png`，1647 × 709 像素。
- 实现截图：Codex In-app Browser 当前任务内已渲染，未提供可持久化本地路径；1280 × 720 CSS 像素、device scale factor 1。
- 目标视口：源图 1647 × 709 像素；实现以 1280 × 720 CSS 像素进行运行时核对，未做密度归一化。
- 状态：桌面端、工具 `read` 已选中、Schema 标签激活，并展开 `properties.path`。
- 全视图比较证据：运行时截图显示筛选栏、三泳道、事件行和右侧详情；缺少并列比较输入。
- 局部区域比较：浏览器无障碍树确认 Schema 展示 `type="object"`、`properties.path.type="string"` 与 `description="要读取的文件路径"`；缺少可保存的局部截图用于与源图并列。
- P0/P1/P2 迭代记录：首次 QA 受环境阻断，尚未产生可执行的视觉差异迭代。

final result: blocked

## 2026-09-11 工作区弹层与 Task 卡片复核

**比较依据**

- 源视觉真相：`C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-9627e622-b3a6-4e5a-9b38-ef26d5d3bf79.png`，1035 × 197 像素；红、蓝标记用于说明工作区触发器、弹层落点与输入框的相对区域。
- 实现快照：`frontend/test-results/workspace-popover-task-card-ux.png` 与 `frontend/test-results/task-run-card-task-card-ux.png`，1280 × 720 CSS 像素、device scale factor 1。
- 比较状态：桌面端默认工作区已绑定；弹层刚进入时保留轻微透明度/模糊过渡，Task 卡展示 `platform.tasks.task.create` 返回与 Worker `task.progress=42` 事件。

**核验结果**

- 工作区触发器打开时向上平移 8px，箭头同步翻转；真实浏览器坐标断言确认位移至少为 6px。
- 弹层从触发器下方进入输入框上方的预留区域，未覆盖输入框操作区；入场动画的浏览器计算样式为 `workspace-popover-enter`（Vue 作用域后缀已兼容）。
- Task 卡通过 MCP 完整名称映射到 `task.create`，并以真实 Worker 事件呈现任务标识、执行状态、42% 进度和调用详情入口。
- Playwright 复核通过：工作区弹层、上移动效、入场动画、MCP 名称映射与 Worker 进度联调均已在同一真实浏览器会话验证。

**P0/P1/P2 迭代记录**

- 无 P0/P1/P2 可执行差异。源图中的 `147` 为动态工作区名称；实现保留实际工作区名称，不硬编码该测试数据。

final result: passed

## 2026-09-14 专家提示词技能页复核

**比较依据**

- 源视觉真相：用户提供的 `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-a2e8ca4c-d08e-4bdc-817d-5fef1432c5eb.png`；目标状态为管理端「Agent 技能」卡片视图。
- 实现截图：不可用。Codex In-app Browser 在两次重试中均返回 `nodeRepl.fetch request failed`，没有可用于同输入比较的浏览器渲染快照。
- 目标状态：桌面端 Agent 技能页，展示内置技能卡片及新增的专家提示词分区；测试用例设计专家打开有效提示词编辑弹窗。

**Findings**

- [P1] 浏览器提供端不可用，无法生成与源图同状态的实现截图。
  Location: 管理端「Agent 技能」页。
  Evidence: 两次 In-app Browser 枚举均未返回浏览器或标签页，并报告 `nodeRepl.fetch request failed`。
  Impact: 已完成的类型检查、构建启动和组件逻辑不能代替截图级视觉验收。
  Fix: 浏览器恢复后，以相同桌面视口打开「Agent 技能」，捕获技能卡片与专家提示词弹窗，再与源图做全视图及局部对照。

**Required fidelity surfaces**

- 字体与排版：尚缺浏览器截图，无法核验卡片标题、说明和按钮的实际换行。
- 间距与布局：代码沿用现有技能卡片网格与令牌；尚缺运行时画面验证。
- 颜色与视觉令牌：代码复用现有 `--c-profiles`、卡片边框和状态标签；尚缺实际渲染对照。
- 图片与资产：本次分区没有新增图像、Logo 或自定义图标。
- 文案与内容：专家名称、状态和操作文案来自后端受控目录；尚缺浏览器状态验证。

**Implementation Checklist**

- [x] 在技能页列出专家角色与提示词覆盖状态。
- [x] 提供专属提示词的查看、编辑、修订冲突提示与恢复内置操作。
- [x] 完成后端定向回归和前端类型检查。
- [ ] 在浏览器可用后完成同视口截图对照。

**Comparison history**

- 本次首次比较：未得到实现截图；未进行 P0/P1/P2 视觉修复迭代。

final result: blocked
