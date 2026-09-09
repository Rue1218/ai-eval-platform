# AI 测试与评估平台 — Agent 消息链路兼容修复

> 版本：V1.1 ｜ 审查日期：2026-09-09 ｜ 状态：补充思考滑块与模型请求审查；修复后线上验收待部署及 qa-test 凭据线下交付。

## 1. 已定位的故障

| 环节 | 证据与影响 | 修复 |
| --- | --- | --- |
| HTTP 浏览器 | 在 `http://47.119.132.83/admin/profiles` 实测 `isSecureContext=false`、`crypto.randomUUID=undefined`、`getRandomValues=function`。此前单独修 WS 请求 ID 未覆盖消息与附件 ID。 | 三处统一使用安全随机 UUID 工具。 |
| 首次 WS 订阅 | 原实现 15 秒后只移除 watcher，没有解除草稿提交态；socket 写入失败也未检查返回值。 | 等待超时显式结束提交状态；保留冻结请求；迟到回放不自动补发，用户可用原 ID 重试。 |
| 默认模型 | 线上 `agent-ui.profile=null`，但 `profiles` 中 DeepSeek、Qwen、StepFun 均可在 off 模式使用。全局思考偏好令默认档解析失败。 | 仅省略档位时回退到受支持的 off；显式不支持档位仍拒绝。 |
| Anthropic 兼容流 | 独立 WS 会话收到 15 个 reasoning delta 后，以 `provider_protocol` 结束，未收到正文。适配器把兼容流空签名判为非法；阿里云官方规范明确允许空签名。 | DeepSeek/Qwen 按已授权模型允许空签名，原样持久化并回填；Claude 与跨模型检查保留。 |
| 思考关闭 | 兼容协议的 off 原先不发送 thinking 参数，供应商仍可能按默认设置返回思考。 | 对 DeepSeek/Qwen 实际发送 `thinking: {type: disabled}`。 |
| 思考滑块 | Anthropic 能力判断只接受 Claude，服务器 DeepSeek/Qwen 的 `allowed_efforts=[off]`，range 两端同为 0；V1.0 的 off 回退未补齐可调档位。 | 同一 resolver 增加已知兼容型号的实际参数映射；单候选时禁用 range 并说明原因。 |
| 本地代理 | `localhost:8000` 是 Python `BaseHTTP/0.6` 静态服务器，登录 501、health 404；Vite 原来把 API/WS 都代理到它。仅改目标但不改 WS Host 时远端仍返回 404。 | `API_PROXY_TARGET` 统一配置 REST/WS，两者均转换 Host；本工作区 `.env.local` 接入用户指定服务器，health 返回 200，WS 收到 hello v2。此文件不提交。 |

前次线上失败记录位于独立测试会话 `400479be-25c4-4bcb-a068-5ba49fe6eadf`。只发送测试文本，未执行工作区修改或评测入队。V1.1 审查按最新规范只允许 qa-test 跑测；用户确认本机无该账号凭据，本轮未复用此前管理员测试会话。不能把本地夹具通过当作线上已修复。

## 2. 与参考工程的链路对应

`deepseek-harness-py` 的 `app/ws/handler.py → AgentRuntime.submit → app/agent/graph.py` 驱动七节点循环：`pre_step → model → tools → close_step → decide_next`，重试走 `retry_wait`，收尾走 `finalize_turn`。工具结果追加到消息历史，下一次模型请求消费完整的 assistant tool call 与 tool result。

平台保持同一循环职责，外围改为认证短票、平台协议档与 PostgreSQL 事实日志：

1. `AgentWorkspace` 冻结消息、附件、协议档和档位；REST 创建会话后移交草稿。
2. `AgentLoopWebSocket` 获取短票，连接 `/ws/agent/v2`，完成 capabilities、subscribe 与 replay 后发送 `turn.submit`。
3. `ws_v2` 校验命令；`LoopService` 完成权限、写者租约与幂等校验，再装配回合依赖。
4. `authorized_profile` 读取管理页相同的 `ProtocolProfile`，经 `_profile_connection` 读取受控配置；默认档才允许历史全局别名。浏览器只提交 ID。
5. `resolver → SDK adapter → AssistantAttempt` 负责协议参数、流解码、工具参数拼装和完整性检查；原始状态进入事实日志。
6. 工具经平台调度器、审批、工作区和沙箱执行；完整结果返回下一模型 step。评测仍只入队交由 Worker。
7. WS 持久事件与瞬态增量投影至前端；收到受理回执或 user.message 后才清理原草稿。

本修复没有复制源项目的匿名 WS、环境密钥或裸 shell，也未更换平台业务工具。兼容性改动集中在浏览器 transport 与协议适配边界。

## 3. 规范依据

- [阿里云 Anthropic-compatible Messages](https://www.alibabacloud.com/help/en/model-studio/anthropic-api-messages)：流式 `signature_delta.signature` 可为空；关闭思考显式传 `thinking.type=disabled`；工具结果与调用 ID 对应。
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)：默认开启思考，调用方需显式发送开关。
- 平台 API V1.83 §4A：现有字段不扩充；默认档位回退与显式请求拒绝区分处理。

兼容空签名不等于把任意模型视为 Claude，也不允许跨模型复用签名状态。

### 3.1 V1.1 传输与思考参数审查

| 调用 | 实际传输 |
| --- | --- |
| 管理页读取/保存协议档 | HTTP REST `/api/profiles`；配置写入受控存储 |
| 浏览器提交回合、接收流与工具事件 | `/ws/agent/v2` WebSocket，HTTPS 页面使用 wss |
| Agent 调用 Anthropic 兼容模型 | SDK `messages.create(stream=True)`，HTTP(S) POST `/v1/messages`，SSE 响应 |
| Agent 调用 OpenAI Chat/Responses | SDK `chat.completions.create` / `responses.create`，HTTP(S) POST，SSE 响应 |

浏览器只发送协议档 ID 和枚举档位；模型地址和密钥由 `authorized_profile → _profile_connection` 从管理端同源配置装配，没有模型 WebSocket 地址或任意请求体透传入口。

- DeepSeek V4 flash/pro（含日期版）：本次公开跨官方/百炼共同有效的 off/high/max。开启传 `thinking.type=enabled` 和 `output_config.effort=high|max`，关闭不残留 output_config。低/中/xhigh 在不同供应商处存在别名差异，本次不作为独立强度公开。
- Qwen3.6 Flash（含日期版）：沿用百炼仍支持的 `thinking.budget_tokens`，五档预算按平台总输出预留的 20%/40%/60%/75%/80% 计算，最低 1024 且小于总量。此型号正文与思考预算分开计数，故下发的正文 max_tokens 扣除思考预算，避免突破平台总预留。该预算参数在官方文档中标注即将废弃；本次未给没有明确 effort 支持声明的旧型号套用新型号配置。
- 其他 Qwen、StepFun 等维持原能力校验。单候选不是可调节控件；界面会解释当前配置仅支持一个档位。
- SDK 请求体测试验证真实 HTTP 方法、路径、stream 开关、逐档参数、工具回填与下一轮切回 off；浏览器测试验证真实鼠标拖动、Home/End 键和 turn.submit 的 profile_id/reasoning_effort 一致。它们不替代供应商线上验收。

## 4. 验证记录

- 前端单测 16 项通过，包含安全随机标识、socket 写入竞态、冻结请求及回放。
- 浏览器 8 项通过，包含无 randomUUID 的创建/附件/消息/工具回执、首次订阅超时、原 ID 重试、移动端与 IME。
- 真实 Anthropic SDK、本地 HTTP 替身、真实七节点 Runtime：DeepSeek/Qwen 两组均完成工具回填、最终回复和第二轮历史回放。工具调度结果为受控夹具，不代表真实供应商或 Linux Runner 验收。
- API 全量：1249 passed、69 skipped；跳过项包含未配置隔离 PostgreSQL 的条件集成测试，不计作通过。
- CI 后端（隔离 PostgreSQL、Python 3.12）：1299 passed、19 skipped，包含本地跳过的数据库集成场景。
- Worker 全量：50 passed；Ruff、前端 typecheck/build 通过。构建只有既有大 chunk 提示。
- 首次 CI 的 HTTP 附件用例发现新建会话能力加载竞态；附件入口现等待能力就绪，拖入时尚未就绪会明确提示重试，测试也等待真实配置完成再上传。
- 本地真实浏览器通过开发代理登录服务器（200），收到 hello/capabilities/subscribed 与完整持久回放及 replay.completed，页面异常数为 0。该检查只回放前述测试会话，没有重新调用模型。

V1.1 本轮回归：API 1263 passed / 69 skipped（本机未配置隔离 PostgreSQL）；Worker 50 passed；前端单测 16、浏览器 11 项通过，typecheck/build 与 Ruff 通过。浏览器覆盖两种实际型号的拖动、键盘调节、单候选提示和 WS 参数；真实 SDK 用例覆盖 off/high/max、工具后续请求、下一回合关闭思考。本轮未认证访问生产模型配置或发起线上 LLM 请求。

首轮 Linux CI 的 Qwen 拖动用例停在 xhigh：测试未等待弹层缩放结束便读取坐标，并把离轨道末端 15px 当作跨浏览器固定终点。已改为等待控件位置稳定并拖至轨道边缘，保留最高档及 WS 参数断言；不以重跑或放宽断言掩盖失败。

## 5. 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `frontend/src/utils/requestId.ts` | HTTP/HTTPS 共用的安全随机 UUID v4。 |
| `frontend/src/api/agentLoopWs.ts` | 请求 ID 与 socket 写入竞态处理。 |
| `frontend/src/components/agent/loop/AgentWorkspace.vue` | 消息 ID、订阅超时、错误提示与冻结请求重试。 |
| `frontend/src/components/agent/loop/AgentComposer.vue` | 附件 ID 使用同一生成器。 |
| `frontend/vite.config.js`、`frontend/.env.example` | REST 与 WS 共用开发代理目标。 |
| `backend/api/app/agent/loop_wiring.py` | 默认思考偏好与兼容协议档解析。 |
| `backend/api/app/llm/providers/anthropic.py` | 兼容空签名流和历史回填，保留 Claude 校验。 |
| `backend/api/app/llm/providers/options.py` | 关闭思考时真实下发兼容协议参数。 |
| `frontend/tests/requestId.test.mjs`、`agentLoopWs.test.mjs`、`e2e/agentLoop.spec.ts` | 前端故障回归。 |
| `backend/api/tests/test_loop_profile_selection.py`、`test_loop_llm.py`、`test_loop_llm_sdk.py` | 配置、SDK 解码与多步循环回归。 |

### V1.1 修改代码文件与作用清单

| 文件 | 作用 |
| --- | --- |
| `backend/api/app/llm/providers/options.py` | DeepSeek effort 与 Qwen 预算映射，保持总输出预留 |
| `backend/api/app/llm/loop_contracts.py` | 仅登记 output_config.effort，维持持久请求字段限制 |
| `frontend/src/components/agent/loop/ThinkingControl.vue` | 单候选禁用并说明原因 |
| `backend/api/tests/test_loop_profile_selection.py`、`test_loop_llm.py`、`test_loop_llm_sdk.py` | 能力/授权一致性、型号与预算边界、真实 SDK 多步及换档回归 |
| `frontend/tests/e2e/agentLoop.spec.ts` | 使用与服务器相同型号的夹具验证拖动到 WS 参数 |
