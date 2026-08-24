# Agent 附件、输入框与供应商图标设计 QA

## Source visual truth

- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-18de2ff8-a6a9-4848-aed4-b95c2a4b9820.png`（图一：错误的圆底图标，36 × 29 px）
- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-01c82cb7-15e3-4e1b-a10f-d9f22d6f58d5.png`（图二：目标黑色阶梯标记，26 × 27 px）

## Implementation evidence

- `C:/Users/Administrator/Desktop/ai-eval-platform/artifacts/agent-composer-attachment-context.png`（输入框内待发送附件）
- `C:/Users/Administrator/Desktop/ai-eval-platform/artifacts/agent-message-attachment-above-text.png`（发送后消息附件位于正文上方）
- `C:/Users/Administrator/Desktop/ai-eval-platform/artifacts/agent-attachment-design-qa-comparison.png`（参考图二与实现截图组合对比）
- URL：`http://127.0.0.1:5173/agent?data=mock`
- 视口：1280 × 720 CSS px，device scale factor 1
- 状态：Mock Agent 会话；先验证输入框内已上传 1 张 PNG，再发送文本+附件并滚动到用户消息回显状态
- 参考图像素未做密度缩放；实现截图为浏览器 CSS 视口 1280 × 720、device scale factor 1

## Comparison

### Full-view evidence

实现保留了现有 Agent 页面结构与截图中的输入区视觉语言：白色圆角输入卡、细边框、模型选择和圆形发送按钮。添加附件按钮缩小到 22 × 22 px 并进入输入行；待发送附件卡片位于输入框内部、正文上方。发送后同一附件仍由用户消息气泡渲染，且位于用户提示词上方。

### Focused-region evidence

附件预览区域逐项核对：PNG 使用真实本地缩略图并显示文件名/大小，发送后的缩略图没有消失，消息结构中附件节点先于正文节点。图二的黑色阶梯标记对应 `ProviderLogo.vue` 的 StepFun 官方路径，已移除图一的圆形白底；当前 Mock 协议档数据未包含 StepFun 条目，因此该品牌 key 以组件资产审查为主。

## Findings

- 无 P0/P1/P2 视觉或交互问题。
- P3：当前 Mock 页面显示 Anthropic 模型，StepFun 不在 Mock 列表中；真实协议档返回 StepFun 模型后会复用同一 `ProviderLogo` 图形分支。

## Primary interactions tested

- 文件选择器支持 `multiple=true`，实际选择 PNG 并完成 Mock 上传。
- 添加按钮 DOM 位于 `.composer-card .composer-input-row` 内，尺寸为 22 × 22 px。
- 待发送附件 DOM 位于 `.composer-card .attach-stage` 内，且 stage 位于 textarea 之前。
- 带附件消息发送后，用户消息先渲染附件卡片再渲染提示词气泡；附件缩略图、文件名和大小仍可见。
- 控制台 error 级别日志为 0；本地未启动 API 时仅有预期的 WS 重连 warning，不影响 Mock 页面交互。

## Comparison history

1. 初始实现：附件预览在输入框外，用户消息中位于正文下方；附件发送后服务端只保存裸 `file_id`，模型窗口没有读取附件。
2. 修复：将附件 stage 放回 composer，缩小并内置添加按钮，重排用户消息节点；服务端增加文件归属校验、文档/图片上下文投影和历史预览元数据。
3. 修复后复验：输入框内预览、发送后附件位序、图片缩略图保留、三协议图文转换和前端构建均通过；无 P0/P1/P2 遗留项。

## Implementation checklist

- [x] 图片/文档格式白名单与 ≤20MB 校验
- [x] 多附件选择和拖拽上传入口
- [x] 图片缩略图与图片放大预览
- [x] PDF/文本预览及 Office 类型卡片
- [x] 上传状态、移除、失败提示
- [x] 发送时仅提交已上传的 `file_id`，服务端将附件安全元数据落入消息回放
- [x] 文本、PDF、DOCX、XLSX 和图片附件进入模型上下文
- [x] StepFun 紧凑 Logo 对齐图二黑色阶梯标记

final result: passed
