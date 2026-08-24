# Agent 附件上传与预览设计 QA

## Source visual truth

- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-8b697373-554f-4fb8-90bc-1a8da7e5a612.png`（输入区参考，807 × 93）
- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-8164fc5a-2d9d-42cb-8bb3-17aafc5c2293.png`（附件缩略图参考，727 × 85）

## Implementation evidence

- `C:/Users/Administrator/Desktop/ai-eval-platform/artifacts/agent-composer-default.png`
- `C:/Users/Administrator/Desktop/ai-eval-platform/artifacts/agent-attachments-preview.png`
- URL：`http://localhost:5173/agent?data=mock`
- 视口：1280 × 720 CSS px，device scale factor 1
- 状态：Agent 空会话；第二张实现截图为已选择 1 张 PNG + 1 份 Markdown、上传完成的附件预览状态

## Comparison

### Full-view evidence

实现保留了现有 Agent 页面结构与截图中的输入区视觉语言：白色圆角输入卡、细边框、底部操作行、模型选择和圆形发送按钮。附件状态下，输入区上方增加紧凑的附件卡片，不遮挡输入和发送操作。

### Focused-region evidence

附件预览区域逐项核对：PNG 使用真实本地缩略图；Markdown 使用 `MD` 类型卡片并显示文件名和大小；卡片右上角提供移除入口。点击图片进入同源放大预览，点击 Markdown 进入文本预览弹层；Office 格式走类型卡片与打开/下载入口，不伪造浏览器无法原生渲染的内容。

## Findings

- 无 P0/P1/P2 视觉或交互问题。
- P3：截图中的模型名是示例 `gemini-3.5-flash-lite`，实现显示当前协议档模型名；这是现有动态模型选择行为，不属于本次附件功能的视觉偏差。

## Primary interactions tested

- 文件选择器支持 `multiple=true`，一次选择 PNG + Markdown。
- 图片缩略图和文档类型卡片在上传完成后正确展示。
- Markdown 文本预览弹层可打开，图片放大预览弹层可打开并关闭。
- 带附件消息发送后，消息气泡保留附件预览卡片与文件名。
- 控制台 error 级别日志为 0；本地未启动 API 时的 WS 重连 warning 不影响 Mock 页面附件交互。

## Comparison history

1. 初始实现：发现上传完成后卡片仍显示“上传中”，原因是异步更新直接修改了未经过 Vue 响应式代理的暂存对象。
2. 修复：通过 `stagedFiles` 中的响应式条目更新 `id/uploading/error`，并兼容 `previewUrl/contentType` 字段。
3. 修复后复验：多选上传、缩略图、Markdown 预览、图片放大预览和带附件发送均通过；无 P0/P1/P2 遗留项。

## Implementation checklist

- [x] 图片/文档格式白名单与 ≤20MB 校验
- [x] 多附件选择和拖拽上传入口
- [x] 图片缩略图与图片放大预览
- [x] PDF/文本预览及 Office 类型卡片
- [x] 上传状态、移除、失败提示
- [x] 发送时仅提交已上传的 `file_id`

final result: passed
