# AgentLoop 轨迹业务记录检查器核对（2026-09-09，V0.11）

## V0.11 轨迹字段与交互核对

**Findings**

- 浏览器功能核对未发现 P0/P1/P2 问题。筛选、三泳道、业务记录行、右侧标题、状态、动态页签、概览字段和关联链均已按参考实现的语义结构恢复。
- 参考图显示等待中的 `shell` 授权；实现截图使用隔离夹具中的已允许 `read` 授权，因此状态和工具名属于测试数据差异。
- 平台继续只展示 WS v2 已授权字段。系统提示词、请求头与协议内部状态不会为了视觉一致性被补到浏览器端。

**Source visual truth**

- `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-994b79e6-e289-4799-b236-9d3dbd0b1215.png`：整体布局、四类筛选、输入/模型/工具三泳道与生命周期详情。
- `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-7440a20f-3ddc-4c2d-8db6-e8639c603474.png`：模型请求快照字段与动态页签。
- `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-d7017140-d561-4591-a2f6-cdac3bebc16e.png`：助手消息用量、耗时和关联链。
- `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-a57866e0-1702-4128-9d35-7012a0411c08.png`：授权记录的参数、结果、来源、计时与数据包页签。

**Implementation evidence**

- `artifacts/trace-inspector-after.png`：生产 `TraceWorkspace.vue` 在 1280×720 下挂载隔离内存事件的最终截图。
- In-app Browser 无障碍树确认筛选只有“全部、生命周期、模型、工具、授权”；已允许授权的动态页签为“概览、参数、结果、来源、计时、数据包”。
- 关联链只显示同一模型请求快照、同一工具调用和当前授权记录。

**Open Questions**

- 参考截图为 988×626 的源应用授权等待态，实现截图为 1280×720 的隔离组件授权完成态。两者已在同一次图像检查中比较结构和字段，但缺少同视口、同数据状态的源应用运行截图，因此不能把本轮标记为逐像素视觉验收通过。

**Fidelity surfaces**

- Fonts and typography：保留平台字体，复用参考页 11px 紧凑工具栏、行与详情字号层级。
- Spacing and layout rhythm：44px 工具栏、50px 三泳道、30px 记录行、430px 桌面详情栏与参考 CSS 一致。
- Colors and visual tokens：紫色选中态、蓝/绿/紫/橙轨迹颜色及浅紫详情提示与参考实现一致。
- Image quality and asset fidelity：本页面没有位图素材；线段、徽标与状态均由 CSS 渲染。
- Copy and content：事件枚举已转换为中文业务标题；动态页签和业务概览字段按记录类型变化。

**Implementation Checklist**

1. 已恢复参考页四类筛选与三泳道。
2. 已拆分模型请求快照和助手消息提交。
3. 已补齐工具、授权、模型请求和助手消息的动态详情字段。
4. 已保留脱敏复制与授权数据边界。

final result: blocked

---

# AgentLoop 原始样式核对（2026-09-09，V0.8）

## V0.8 居中双边悬停拖拽核对

**Findings**

- 已修复 [P1]：上一版壳层右侧停靠，只提供左侧拖拽线，且进入中央内容区也会显示。现在壳层以 `margin: 0 auto` 居中，左右各有独立透明边缘命中区；中间内容区不触发可见线。
- 未发现新的 P0/P1/P2 布局问题。鼠标实时悬停的浏览器自动化坐标能力不可用，已通过事件实现和桌面布局测量核对位置与边界；仍需由用户在实际鼠标下复核阴影观感。

**Source visual truth**

- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-44bef841-14f6-4fb6-bf39-a0e2ac920836.png`，80×117 px：细灰绿色竖线带柔和玻璃阴影，约 80–100px 高。

**Implementation evidence**

- In-app Browser：`http://localhost:5174/agent?data=mock`，1440×900 CSS px，device scale factor 1，新建 Mock 欢迎态、桌面宽度。
- 运行时测量：共享壳层左/右为 402px / 1302px，宽度 900px；其中输入框左/右也为 402px / 1302px。左右命中区分别为 388–416px 与 1288–1316px，覆盖壳层边缘。
- 无障碍树暴露两个独立分隔线：“向左拖拽调整对话内容宽度”与“向右拖拽调整对话内容宽度”。
- `npm run typecheck` 通过；本地页控制台错误为空。

**Fidelity surfaces**

- Fonts and typography：本次未改变字体、字号、字重、行高或文案。
- Spacing and layout rhythm：消息区和输入框同宽并居中，左右边缘命中区均为 28px，可见线为固定 96px 高。
- Colors and visual tokens：默认透明；可见线使用低不透明度白色玻璃底、灰绿色 2px 细线和柔和阴影。
- Image quality and asset fidelity：本次没有图片、图标或素材变动。
- Copy and content：本次没有文案变动。

**Open Questions**

- 源图只提供局部边缘线，未提供页面整体状态；浏览器策略也不能把局部源图与实现截图放在同一比较输入。因此无法完成逐像素视觉比较。

**Implementation Checklist**

1. 已实现居中共享壳层和左右双边拖拽。
2. 已将可见阴影线限制为边缘命中区，并使其随鼠标纵向位置移动。
3. 已完成 TypeScript 和浏览器布局验证。

final result: blocked

## V0.7 共享对话壳层调宽核对

**Findings**

- 已修复 [P1]：上一版把可调宽区域仅包住消息列表，输入框位于壳层外，且显示右缘大面积玻璃卡片。现在 `AgentWorkspace.vue` 将输入框移入消息区所属的 `loop-chat-shell`，两者由同一 `width` 控制；把手位于左缘，拖动与方向键的宽度方向均已对应左侧边界。

**Source visual truth**

- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-7f1ee97a-0688-4173-8e50-8baad01a8704.png`，1172×885 px：细竖向拖拽线在内容列左缘，消息区与输入框共享左右边界。

**Implementation evidence**

- In-app Browser：`http://localhost:5174/agent?data=mock`，1280×720 CSS px，device scale factor 1，新建 Mock 会话、浅色欢迎态、桌面宽度。
- 无障碍树中“对话内容区域”同时包含欢迎态消息、消息输入框和“拖拽调整对话内容宽度”分隔线，证明三者同属共享壳层。
- 聚焦后截图显示固定高度的左缘细线；没有整块对话卡片边界。对话列外框与输入框外框左边均为 563px，输入文字相对壳层内缩 16px。
- `npm run typecheck` 通过。浏览器页未报告应用控制台错误。

**Fidelity surfaces**

- Fonts and typography：本次未改变文字字体、字号、字重或副本；与参考图的中文字体和文案不是同一页面状态，未作等价判断。
- Spacing and layout rhythm：消息区和输入框改为共同宽度与共同右缘；左缘只保留 104px 高拖拽线，命中区不形成可见胶囊。
- Colors and visual tokens：默认透明，聚焦/悬停时使用低不透明度白色与灰绿色细线；未为壳层添加卡片背景。
- Image quality and asset fidelity：本次没有图片、图标或素材变动。
- Copy and content：本次没有文案变动。

**Open Questions**

- 用户截图为 1172×885 px 的另一页面状态，当前实现截图为带平台导航的 1280×720 px 欢迎态；浏览器策略阻止将两张图片置于同一比较输入，无法完成要求的逐像素并列判断。

**Implementation Checklist**

1. 已将消息区和输入框置入同一个 `loop-chat-shell`。
2. 已将桌面拖拽点改为壳层左缘的固定高度细玻璃线。
3. 已验证可访问分隔线及 TypeScript 类型检查。

final result: blocked

## V0.6 输入焦点与内容宽度核对

final result: blocked — 已能打开用户提供的两张截图和本地实现截图，但浏览器策略拒绝打开用于并列比较的 `data:` 页面。依据 `product-design/design-qa/SKILL.md`，两张图必须放在同一比较输入中；未绕过该策略，因此不能把本轮截图核对标为通过。

### Source visual truth

- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-d962b9ea-47bd-4db1-82d6-faef06e9ef37.png`：输入文本域出现的蓝色内框，用户要求隐藏。
- `C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-741cde78-b3e8-421f-8ba5-5d42601a59ab.png`：欢迎态对话内容区域的默认无框状态。

### Implementation evidence

- `artifacts/agentloop-conversation-default-1046x647.png`：In-app Browser 在 1046×647 CSS px、device scale factor 1 的 AgentLoop 欢迎态截图；内容列默认透明，输入栏没有蓝色内框。
- `artifacts/agentloop-conversation-resize.png`：1440×900 CSS px 的桌面悬停/分隔线状态截图；右缘玻璃把手及固定高度边界可见。
- 浏览器无障碍树确认分隔线名称为“拖拽调整对话内容宽度”；键盘 ArrowLeft 已将宽度从 860px 调整至 836px。文本域的计算样式为 `border: 0`、`outline: none`、`box-shadow: none`。

### Findings

- 无 P0/P1/P2 实现问题。图 1 的蓝色内框被主动移除，属于用户明确要求的有意差异。
- [P3] 参考图没有提供悬停玻璃态，玻璃透明度与把手高度按用户文字要求实现，后续可根据新的悬停参考图继续微调。

### Comparison history

- V0.6：参考图与 1046×647 实现截图均已在 In-app Browser 打开；尝试创建仅包含两张已授权截图的并列核对页被浏览器 URL 策略拒绝，未采用其他路径规避限制。

### Implementation checklist

- [x] 隐藏文本域蓝色 outline、border 和 shadow。
- [x] 默认隐藏对话内容列边界，悬停/聚焦/拖拽时显示玻璃边界。
- [x] 桌面端提供右缘鼠标拖拽、键盘左右键和本地宽度偏好。
- [x] 窄屏固定全宽并隐藏拖拽把手。

## 当前结果与范围

final result: blocked — 仅源截图逐像素比对受阻。浏览器拒绝打开参考文件的 file:// URL；未改用其他浏览器或转发原页面来绕过该限制。源 HTML 的 CSS 已通过文件读取核对，生产组件的计算样式与交互已在 In-app Browser 验证。不能将以下实测记录称为两张截图的视觉一致性验收。

依据 product-design/design-qa/SKILL.md：“If either artifact cannot be opened, captured, or compared, write `design-qa.md` with `final result: blocked`”。此限制不代表已经完成的代码修改和本地交互检查失败。

## 已修正的差异

- [P1] 轨迹沿用了绿色状态、自定义尺寸和卡片式详情。本轮采用原页紫色状态、44px 工具栏、30px 行、56px 序号、430px 桌面详情栏及键值/预览/关联区域。
- [P1] 思考卡片缺少粒子层，额外说明行改变卡片高度；恢复源结构与两层 22 粒子。
- [P2] Naive UI raw 弹层仍有方形 shadow；计算样式确认问题后显式去除，复测为 none。
- [P2] 平台全局焦点规则给 range 增加方框；保留源拇指焦点样式，清除 range 自身 box-shadow。

## 实现证据

- 独立入口：http://localhost:5173/tests/agent-loop-style-preview.html；生产 Vue 组件，内存演示数据，无外部调用。
- 桌面 1440×900：`artifacts/agentloop-trace-reference-styles.png`、`artifacts/agentloop-effort-reference-styles.png`。
- 手机 375×812：`artifacts/agentloop-reference-styles-mobile.png`；document scrollWidth 与 viewport 均为 375。
- 卡片测量：272×121.5px，radius=16px，padding=14px 14px 13px，粒子数=22，外层阴影=none。
- 轨迹测量：行=30px、首列=56px、工具栏=44px、详情=430px；分类前景 rgb(69,70,170)、背景 rgb(240,241,255)。
- 字体：两个组件隔离为源 Inter/Segoe UI Variable Text/Microsoft YaHei UI 字体栈；标题、正文、等宽序号分别保留源字号与字重。
- 布局：移除源未有的说明行和轨迹统计工具条；窄屏详情接在列表下。平台输入栏独立占位，不复制源重复的 102px 预留。
- 颜色与素材：使用源 CSS 色值、渐变及原有代码粒子，无新增位图和占位素材；内容仍为平台授权数据。
- 交互：已用浏览器检查选中记录、预览 Tab、滑块 Home/End 从关闭到最高档；详情和滑块均无横向页面溢出。

## 历史记录（V0.3，不作为本轮完整验收结论）

## Source visual truth

- C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-9717797f-aac6-4661-9bde-dfd4ad392c21.png：紧凑输入栏参考图。
- deepseek-harness-py/static/index.html：浅色思考强度触发器、滑块轨道、档位文案和键盘交互参考。

## Implementation evidence

- Codex In-app Browser：http://127.0.0.1:5173/agent?data=mock
- 视口：876 × 720 CSS px，device scale factor 1。
- 状态：新建 AgentLoop 草稿，DeepSeek 协议档，思考高强度。
- 该浏览器截图仅由 In-app Browser 运行时提供，未暴露可写入仓库的本地截图文件。

## Comparison

同一 876 px 宽度下核对参考图和实现截图：实现使用白底、细灰边、18 px 圆角和紧凑两行布局；上行是参考图中的提示文本，下行依次为添加附件、ProviderLogo、模型名/下拉、思考控制、上下文状态和圆形发送按钮。输入栏固定在 AgentLoop 工作台可视区域底部，不会被欢迎区推出视口。

思考控制复用 DeepSeek Harness 的浅色仪表盘、档位色彩和 range 滑块结构。选择协议档后，滑块只显示该档允许的档位；键盘 Home/End、滚轮和 Escape 均作用于当前控制，切换只影响下一轮请求。

## Findings

- 无 P0/P1/P2 视觉或交互问题。
- 无 P3 遗留项。

## Primary interactions tested

- 协议档弹层显示 AgentLoop 可用档位，选择兼容协议档后提交 profile_id。
- 思考控制可打开、切换档位、键盘 Home/End、滚轮调节，Escape 回到触发按钮。
- 发送按钮在空草稿时禁用，有内容且会话就绪时可发送。
- 876 × 720 视口下输入栏保持可见。

final result: passed

## V0.9 上下文来源分布核对

- Source visual truth: `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-4e1774ce-3d7d-4a70-beea-2c160809ed01.png`, `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-12d7dca7-b370-46ae-809c-5ed97fc5126a.png`, `C:/Users/Toneya/AppData/Local/Temp/codex-clipboard-a7be2f2d-7c39-4b13-b254-16c7051b1c02.png`
- Implementation target: `frontend/src/components/agent/loop/LoopContextMeter.vue`
- Intended state: authenticated AgentLoop session with a completed model attempt and `context_meter.breakdown`.
- Rendered evidence: local Vite application reached `/login`; the Agent workspace is unavailable without an authenticated session.
- Viewport and density: not comparable because the target control is not present on the unauthenticated page.

### Findings

- [P1] The authenticated AgentLoop context meter could not be captured.
  Evidence: the local application rendered its login route, while the target control only appears after an AgentLoop attempt has written `request_summary.context_meter`.
  Impact: visual fidelity against the supplied reference cannot be confirmed from browser evidence.
  Fix: open an authenticated Agent session after deployment, send one message, then compare the compact ring and opened meter popover with the supplied references.

### Implementation Checklist

- Verify the six colored source rows and the gray output-reserve segment with a real AgentLoop request.
- Verify the compact ring and opened popover at desktop and narrow viewport widths.

final result: blocked
