# Harness WebSocket 协议探针（harness-ws-probe）

> 对 `http://<host>:8000/ws/agent?ticket=...` 做**黑盒抓包 + 契约断言**的工具：不依赖前端、不依赖后端内部实现，只按 API.md V1.62 的 WS 事件契约收发帧，并用 `ExpectMatcher` 对帧做白名单 / 单调性 / 时序 / 字段级断言。

| 项 | 内容 |
| :--- | :--- |
| 定位 | Harness WS 协议回归探针（L0/L1/L2 三级场景） |
| 契约来源 | [`docs/AI测试与评估平台-API.md`](../../docs/AI测试与评估平台-API.md) §4（WS 事件、上行枚举、关闭码 4401/4404） |
| 双轨模式 | `--scripted` 进程内对等端（离线、CI 可用） + live 连真实服务（部署后回归） |
| 落盘产物 | `traces/*.jsonl` 双向抓包（已脱敏，gitignore 不提交） |

## 1. 目录结构

```
tools/harness-ws-probe/
├── harness_ws_probe/
│   ├── client.py         # WS 客户端：Cookie 登录、短票、五类上行、4401/4404 关闭码
│   ├── recorder.py       # TraceRecorder：双向帧录制（dir up/down、事件号、时间戳），落盘 jsonl
│   ├── expect.py         # ExpectMatcher：事件白名单 / event_id 严格递增 / 上行枚举 / 回合契约
│   ├── redact.py         # 抓包脱敏：ticket、system_prompt 等一律 <redacted>
│   ├── protocol.py       # 协议常量（禁止的旧事件名、五类上行、瞬态帧定义）
│   ├── scripted.py       # ScriptedProbe：进程内对等端，不连真实服务
│   ├── scenarios/        # L0 握手/斜杠/幂等/断线重放、L1 确认卡入队、L2 chat 契约
│   └── __main__.py       # CLI 入口
├── run-live.ps1 / run-live.sh   # 一键跑 live 全套（连真实服务，落抓包证据）
└── traces/               # 抓包产物（*.jsonl 已 gitignore）
```

## 2. 快速开始

### 2.1 离线自检（scripted，不需要任何服务）

```powershell
# 在 backend/api 目录（依赖 pytest/httpx/websockets 已装）：
cd backend/api
python -m pytest tests/test_harness_probe_l0.py tests/test_harness_probe_l1.py tests/test_harness_probe_l2.py -q

# 或直接用 CLI 的 scripted 模式跑 L0/L1/L2 全套：
cd tools/harness-ws-probe
python -m harness_ws_probe --scripted --suite all
```

### 2.2 在线回归（live，连真实 API 服务）

前置条件：

1. 服务在线：`http://127.0.0.1:8000`（或服务器 `http://47.119.132.83:8000`）；
2. **L2 chat 场景需要已配置 Agent 协议档**（traces 中 `model_name=qwen3.6-flash` 即为已配置状态），否则该用例失败即红；
3. L1 入队会真实创建 `sample_size=1`、`with_stress=false` 的 queued 任务，属正常回归行为。

```powershell
# 方式一：一键脚本（默认 127.0.0.1:8000，可带参覆盖）
cd tools/harness-ws-probe
./run-live.ps1                     # 或 ./run-live.sh http://127.0.0.1:8000 admin admin123

# 方式二：直接跑 pytest（等价）
cd backend/api
$env:HARNESS_PROBE_BASE = "http://127.0.0.1:8000"
python -m pytest tests/test_harness_probe_live.py -v

# 方式三：CLI live（更灵活的抓包诊断）
cd tools/harness-ws-probe
python -m harness_ws_probe --base http://127.0.0.1:8000 --suite all --allow-enqueue --trace-dir traces
```

## 3. CLI 参数

| 参数 | 说明 |
| :--- | :--- |
| `--base` | 服务 HTTP 地址，默认 `http://127.0.0.1:8000` |
| `--user` / `--password` | 登录账号，默认 `admin` / `admin123` |
| `--insecure` | 跳过 TLS 证书校验（https 自签场景） |
| `--suite` | `l0` / `l1` / `l2` / `chat` / `all`，默认 `l0` |
| `--prompt` | chat 套件的用户句，可重复；缺省跑自我介绍与平台能力两句 |
| `--allow-enqueue` | 允许 L1 真实入队（`/stress` → 确认卡 → `confirm_ack`） |
| `--dump` | 打印人类可读帧时间线 |
| `--trace-dir` | 抓包落盘目录，默认 `traces/` |
| `--scripted` | 不连真实 API，跑进程内对等端（与 pytest 同一套场景） |

## 4. live 自动化（部署后回归证据）

pytest live 套件（`backend/api/tests/test_harness_probe_live.py`）把 L0/L1/L2 在线场景做成**可一键触发的自动化回归**：默认跳过，设置 `HARNESS_PROBE_BASE` 即启用；任一契约断言失败即红（退出码非 0），并自动把本次双向抓包脱敏落盘到 `traces/live-<时间戳>.jsonl` 作为证据。

| 环境变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `HARNESS_PROBE_BASE` | 无（必填才启用） | 服务 HTTP 地址 |
| `HARNESS_PROBE_USER` | `admin` | 登录用户名 |
| `HARNESS_PROBE_PASSWORD` | `admin123` | 登录密码 |
| `HARNESS_PROBE_INSECURE` | 空 | `=1` 时跳过 TLS 校验 |
| `HARNESS_PROBE_TRACE_DIR` | `tools/harness-ws-probe/traces/` | 抓包证据落盘目录 |

覆盖场景（与 CLI live 同一套场景，断言更严）：

- **L0**：非法票 4401 / 不存在会话 4404 关闭码、非法上行 → `VALIDATION`、空会话 `/cancel`、`/stress` 确认卡取消、`/help` 正文、`client_message_id` 幂等、断线按 `last_event_id` 重连补发（不含瞬态帧）；
- **L1**：`/stress` → 确认卡 → `confirm_ack(ok=true, sample_size=1)` → 返回 `task_id`；
- **L2**：真实模型一轮对话，断言 `think_final` 先于 `response.completed`、无一字一帧、无隐藏思维链。

## 5. traces 语义

- 每帧一行 JSONL：`dir`（上行/下行）、`t_ms`（相对毫秒）、`event`、`event_id`（持久帧）、`persistent`、`raw`（**已脱敏**的原始帧）；
- `persistent=false` 的帧（`think` 增量、`assistant_delta`、`pong`）为瞬态帧，不占事件号；
- 抓包默认脱敏：`ticket`、`system_prompt` 等敏感字段落盘为 `<redacted>`，禁止明文凭据进入产物；
- `traces/*.jsonl` 已被 `.gitignore` 排除，仅作本地/服务器回归证据，不提交仓库。

## 6. 契约断言点（ExpectMatcher）

| 断言 | 内容 |
| :--- | :--- |
| `public_headers` | 下行帧必须带 `{event, session_id, task_id, event_id, ts, payload}` 公共头 |
| `event_whitelist` | 禁止旧事件名（如 `message`），未知下行事件即失败 |
| `event_ids_monotonic` | 持久帧 `event_id` 严格递增 |
| `no_forbidden_uplink` | 上行只能是五类：`user_message` / `confirm_ack` / `cancel_task` / `clarify_reply` / `tool_approval_ack` |
| `error(code, text)` | 错误帧归一为 10 大错误码 + 场景文案 |
| `chat_turn_contract` | `response.completed` 收尾；有思考链时 `think_final` 必须先于它；禁止一字一帧；禁止隐藏思维链（`Here's a thinking process`） |
| `replay_no_transient` | 断线重连补发不得包含瞬态帧（`assistant_delta` 等） |

## 7. 测试归属

- **探针自身契约测试**：`backend/api/tests/test_harness_probe_l0/l1/l2.py`（默认跑 scripted 对等端，不依赖服务，已纳入 CI 全量 pytest）；
- **live 在线回归**：`backend/api/tests/test_harness_probe_live.py`（默认跳过，`HARNESS_PROBE_BASE` 启用，一键脚本见 §2.2）。

## 8. 常见问题

| 现象 | 处理 |
| :--- | :--- |
| `scripted 通过` 乱码 | Windows 控制台 GBK 显示问题，不影响判定（退出码 0） |
| live 的 `/help` 失败被跳过 | 未配 Agent 协议档时沿用 CLI 容错语义，其余场景不受影响 |
| live 的 L2 chat 失败 | 检查协议档是否已配置、模型端是否可达（`--dump` 查看帧） |
| 连接被关 4401 | 短票过期，重新登录领票（探针已自动处理） |
| 连接被关 4404 | 会话不存在/共享被收回，换新会话重试 |
