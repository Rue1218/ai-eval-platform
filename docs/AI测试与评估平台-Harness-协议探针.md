# AI 测试与评估平台 — Harness WebSocket 协议探针

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | Harness WebSocket 协议探针 |
| 版本 | V0.3 |
| 审查日期 | 2026-08-26 |
| 文档性质 | 模块设计 + 联调验收工具说明书 |
| 适用模块 | `tools/harness-ws-probe/`（黑盒 WS 客户端） |
| 上游权威 | API.md V1.44 §4；PRD 事件名与错误码；Harness 编排层确认卡 / 斜杠 / 思考链规则 |

> **阅读关系**：本文描述如何用与浏览器相同的四类上行 JSON 抓取 `/ws/agent` 下行公共头与事件，断言 Harness 行为。不新增对外 REST/WS 字段。内部函数单测仍由 `test_ws_protocol.py` / `test_confirm_ack.py` 负责。

---

## 1. 定位

探针是第三层验收，介于函数 mock 与浏览器 UI 之间：

| 层 | 工具 | 看到什么 |
| :--- | :--- | :--- |
| 函数 | `backend/api/tests/test_ws_*.py` | 处理器入参出参 |
| **协议** | **本工具** | 真实上下行帧、公共头、短票、补发 |
| UI | Playwright / 手工 | 卡片与文案 |

只做三件事：发 API.md §4.4 四类上行、记录全部下行、按契约断言。不依赖 Vue，不抓 DevTools。

---

## 2. 架构

```text
login + ws-ticket
        │
        ▼
 ProbeClient ──► /ws/agent
        │
        ▼
 TraceRecorder（jsonl，已脱敏）
        │
        ▼
 ExpectMatcher（§4.2–§4.4）
```

- 上行仅 `user_message` / `confirm_ack` / `cancel_task` / `clarify_reply`；场景「禁第五种事件」走显式 `send_raw`。
- 应用层不发 JSON `ping`。
- 瞬态帧：`pong`、`assistant_delta`、`thought.stream=think`。不推进 `last_event_id` 去重。
- 关闭码：`4401` 重新领票，`4404` 停连。

---

## 3. 场景分档

| 档 | 是否打模型 | 覆盖 | 默认 |
| :--- | :--- | :--- | :--- |
| L0 契约 | 否（收包循环拦截 / 校验） | 短票、关闭码、第五种事件、`/help` `/cancel` `/stress`、取消确认卡、幂等键、重连补发 | CI 必跑 matcher；真连接走 CLI 或 `HARNESS_PROBE_BASE` |
| L1 编排 | 否（确认卡路径） | `confirm_ack` 入队（强制 `sample_size=1`、`with_stress=false`） | 需 `--allow-enqueue` |
| L2 真模型 | 是 | 闲聊思考链：`think_final` 在 `response.completed` 之前；禁止一字一帧；禁止隐藏 CoT 原文 | `--suite l2` / `--suite chat` |

L0 八条：

1. 非法 ticket → 4401；不存在的 `session_id` → 4404
2. `{event: slash}` → `error` + `VALIDATION`
3. `/help` → `assistant_message` 含 cancel/stress，再 `response.completed`
4. `/cancel` 空会话 → `VALIDATION`「没有可取消」
5. `/stress` → `confirm.kind` ∈ `{benchmark,rag}`，`with_stress=true`，`kind != stress`
6. `confirm_ack {ok:false}` → 盖章、无 `task_id`、无后续 `progress`/`report`
7. 同一 `client_message_id` 连发两次，只有一轮 `response.completed`
8. 重连带 `last_event_id`：只补发更大持久事件，不含 `assistant_delta`

---

## 4. 运行

在已安装 API 依赖的环境（含 `httpx`、`websockets`）：

```text
cd tools/harness-ws-probe
python -m harness_ws_probe --base http://127.0.0.1:8000 --suite l0
python -m harness_ws_probe --base https://47.119.132.83 --insecure --suite l0 --dump
python -m harness_ws_probe --base https://47.119.132.83 --insecure --suite l2
```

Pytest：`backend/api/tests/test_harness_probe_l0.py` 用 Scripted 对等端跑同一套场景 + matcher（不依赖 PG）。对真实 API：

```text
set HARNESS_PROBE_BASE=http://127.0.0.1:8000
pytest tests/test_harness_probe_l0.py -k live
```

生产默认不入队。L1 必须 `--allow-enqueue`。

---

## 5. 脱敏

traces 不写 Cookie、ticket、API Key、完整系统提示词。`raw` 落盘前经过 `redact.py`。

---

## 6. 修改代码文件与作用清单

| 文件 | 操作 | 作用 |
| :--- | :--- | :--- |
| `docs/AI测试与评估平台-Harness-协议探针.md` | 新增 V0.1 → 修订 V0.2 → 修订 V0.3 | V0.2：L2 闲聊思考链顺序与一字一帧。V0.3：L2 拒绝隐藏 CoT 原文。 |
| `tools/harness-ws-probe/harness_ws_probe/expect.py` | 修改 | `chat_turn_contract` 拒绝 `Here's a thinking process` |
| `backend/api/tests/test_harness_probe_l2.py` | 修改 | 隐藏 CoT 用例 |
| `tools/harness-ws-probe/harness_ws_probe/` | 新增 | 客户端、录制、期望、L0/L1/L2 场景、CLI |
| `backend/api/tests/test_harness_probe_l0.py` | 新增 | L0 契约套件 |
| `backend/api/tests/test_harness_probe_l1.py` | 新增 | L1 入队门禁套件 |
| `backend/api/tests/test_harness_probe_l2.py` | 新增 | L2 思考链契约套件 |
