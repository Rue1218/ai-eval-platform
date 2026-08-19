# AI 测试与评估平台 — Agent 子系统：大模型接入与耗时技术方案

| 属性 | 内容 |
| :--- | :--- |
| **文档名称** | Agent 子系统大模型接入与耗时技术方案 |
| **文档版本** | V1.2 (全量审查与修改记录归档) |
| **基线参考** | 《AGENTS.md》最高规范、《Agent开发文档》§6 / §4.6 / §5.2.1 / §16.7、API.md V1.4、PRD 6.2 |
| **责任模块** | 后端 `backend/api/app/llm.py` + `ws.py` + `adapters.py` + 前端 `frontend/src/*` |
| **审查日期** | 2026-08-19 |

---

## 1. 方案背景与设计边界

本技术方案针对评测平台 Agent 子系统的 **「大模型接入」** 与 **「三层耗时感知」** 进行完整的架构设计、接口契约冻结与落地指导，对应 Task 编号 `AGT-LLM-01` 与 `AGT-LLM-02`。

### 1.1 核心设计目标
1. **单一 Agent 驱动模型**：由系统全局设置 `settings.agent_profile_id` 绑定唯一的模型协议档，驱动 Agent 意图识别、规划拆解与页面 AI 候选生成；
2. **多层精准耗时感知**：从大模型调用、短 MCP 工具执行到整轮回合交互，提供毫秒级耗时计量与统一格式化展示；
3. **严格安全与脱敏防护**：API Key 经 Fernet 加密存储、接口绝不回显，控制台日志与异常彻底脱敏；
4. **思考过程与折叠体验**：支持大模型深度思考链与正文分离，思考卡在生成完成 800ms 后自动收起；
5. **统一错误码归一化**：上游异常、网络中断、请求超时等严格归一化为 10 大标准错误码，绝不将原生堆栈暴露给前端。

### 1.2 红线禁令（核心约束）
- ❌ **严禁用户端自由切换模型**：ChatHead 顶栏与 Composer 输入框右侧固定为只读展示 `Agent · {模型名}`，严禁提供模型切换下拉框或思考强度滑杆；
- ❌ **严禁明文暴露凭据**：严禁在 `agent_trace`、错误信息、REST 响应或 WS 事件中出现 API Key、Cookie、Password；
- ❌ **严禁伪造成功与虚假耗时**：未配置协议档时必须明确报错（`VALIDATION` 400），耗时必须取自真实 `latency_ms`，严禁本地前端制造伪装耗时；
- ❌ **严禁在 WS/API 进程跑长任务**：模型调用仅用于短交互（超时 ≤ 30s），耗时评测与压测一律交由 Worker 异步消费。

---

## 2. 架构拓扑与交互时序

```text
浏览器 (/agent & 工作台)
  │── REST: GET /api/admin/settings ────► 获取当前生效 agent_profile_id 对应模型名（只读展示）
  │── WS: /ws/agent?ticket= ────────────► 接收 thought / tool_result 事件（带 latency_ms）
                                                │
                                                ▼
FastAPI Agent Host
  │── 1. resolve_agent_profile(db) ────► 读取 settings.agent_profile_id，查询 protocol_profiles
  │── 2. decrypt_secret(...) ───────────► 解密 API Key（内存即用即毁）
  │── 3. call_protocol(...) ────────────► 发起网络请求并记录 t0~t1 耗时 (latency_ms)
  │── 4. AgentCallResult ───────────────► 封装 text, latency_ms, usage
  │── 5. agent_trace(...) ──────────────► 输出脱敏日志到 stderr
                                                │
                                                ▼ HTTP POST (30s 超时)
外部大模型网关 / 供应商 (OpenAI Chat / Responses / Anthropic Messages)
```

---

## 3. 大模型接入层设计

### 3.1 协议档检索与单模型绑定 (`backend/api/app/llm.py`)

Agent 复用平台的 `protocol_profiles` 协议档系统，通过系统设置项指定驱动源。

```python
"""Agent 协议档检索与单模型绑定逻辑。"""
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session

from .agent.log import agent_trace
from .errors import AppError, ErrorCode
from .models import ProtocolProfile, Setting


@dataclass(frozen=True)
class AgentProfilePublicInfo:
    """Agent 驱动模型对外公开信息（只读、脱敏）。"""

    profile_id: str
    name: str
    model: str
    protocol: str


def resolve_agent_profile(db: Session) -> ProtocolProfile:
    """读取 settings.agent_profile_id 指向的 Agent 协议档。
    
    未配置或已被删除时抛出 VALIDATION (400)，严禁伪造默认模型。
    """
    row = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = row.value if row else None
    if not profile_id:
        raise AppError(ErrorCode.VALIDATION, "未配置 Agent 协议档，请先在协议档页指定 Agent 核心驱动")

    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档不存在或已删除，请重新指定")
    if not profile.encrypted_key:
        raise AppError(ErrorCode.VALIDATION, "Agent 协议档未配置 API Key")
    return profile


def get_agent_profile_public_info(db: Session) -> AgentProfilePublicInfo | None:
    """获取当前生效的 Agent 模型公开信息供界面只读展示；未配置时返回 None。"""
    try:
        profile = resolve_agent_profile(db)
        return AgentProfilePublicInfo(
            profile_id=str(profile.id),
            name=profile.name,
            model=profile.model,
            protocol=profile.protocol,
        )
    except AppError:
        return None
```

### 3.2 三协议统一调用与结构化返回

底层支持三协议调用：
1. `openai_chat`（POST `/v1/chat/completions`）；
2. `openai_responses`（POST `/v1/responses`）；
3. `anthropic_messages`（POST `/v1/messages`）。

#### 结构化出参定义：
```python
@dataclass(frozen=True)
class AgentCallResult:
    """Agent 大模型调用统一出参。"""

    text: str              # 模型返回正文或 JSON 字符串
    latency_ms: int        # 毫秒级耗时
    usage: dict            # prompt_tokens, completion_tokens, total_tokens
    raw: dict              # 原始响应体（截断保存）
```

#### 模型同步调用封装：
```python
CALL_TIMEOUT_S = 30.0  # 默认短调用 30s，交互式意图识别可收紧至 12s

def call_agent_model(
    db: Session,
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout_s: float = CALL_TIMEOUT_S,
) -> AgentCallResult:
    """经三协议统一适配器调用 Agent 模型并返回包含耗时的结构化结果。"""
    profile = resolve_agent_profile(db)
    agent_trace(f"模型调用开始 protocol={profile.protocol} model={profile.model} timeout={timeout_s}s")

    try:
        result = call_protocol(
            protocol=profile.protocol,
            base_url=profile.base_url,
            model=profile.model,
            api_key=decrypt_secret(profile.encrypted_key),
            messages=[{"role": "user", "content": user}],
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            anthropic_version=profile.anthropic_version,
            timeout_s=timeout_s,
        )
        text = result.text.strip()
        if not text:
            raise AppError(ErrorCode.UPSTREAM, "Agent 模型返回空内容")

        agent_trace(f"模型调用完成 latency={result.latency_ms}ms chars={len(text)}")
        return AgentCallResult(
            text=result.text,
            latency_ms=result.latency_ms,
            usage=result.usage,
            raw=result.raw,
        )
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"模型调用内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "Agent 模型调用失败") from exc
```

---

## 4. 三层耗时体系与格式化规范

### 4.1 三层耗时定义

| 层次 | 统计对象 | 来源 | 事件承载 | 界面展示位置 |
| :--- | :--- | :--- | :--- | :--- |
| **模型层耗时** | 单次请求大模型的网络与推理时长 | `call_protocol` 返回的 `latency_ms` | `thought.payload.latency_ms` | 思考卡标题栏右侧，如 `1.2s` |
| **工具层耗时** | 单个短 MCP 工具的执行耗时 | `mcp_tools` 执行前后计时差 | `tool_result.payload.latency_ms` | 工具卡标题栏右侧，如 `45ms` |
| **本轮总耗时** | 发出用户消息到交付的总耗时 | 规划耗时 + 工具耗时 + 复核耗时之和 | 前端运行时累加 | 阶段 pill 旁或回合统计 |

### 4.2 耗时格式化冻结标准（§16.7）

所有界面展示的耗时必须统一按如下算法进行格式化：

$$\text{Display}(ms) = \begin{cases} 
\text{“}\{ms\}\text{ms”} & \text{if } ms < 1000 \\
\text{“}\{\text{round}(ms / 1000, 1)\}\text{s”} & \text{if } ms \ge 1000 
\end{cases}$$

#### 格式化函数实现 (`frontend/src/utils/format.ts`)：
```typescript
/**
 * 统一耗时格式化函数（开发说明书 §16.7）
 * @param ms 毫秒数（支持 0ms；无效或负数返回空字符串）
 */
export function formatLatency(ms?: number | null): string {
  if (ms === undefined || ms === null || isNaN(ms) || ms < 0) {
    return ''
  }
  if (ms < 1000) {
    return `${Math.round(ms)}ms`
  }
  return `${(ms / 1000).toFixed(1)}s`
}
```

---

## 5. 思考链（Reasoning）与卡片交互规范

### 5.1 思考过程处理
- **无 token 级流式事件**：避免海量高频 WS 包冲击系统；
- **Reasoning 处理**：若上游返回推理链，先发送一条包含思考内容的思考卡（`thought`），再发送正文思考卡；
- **800ms 自动折叠**：思考卡在 `done=true` 之后保持展示 **800ms**，随后平滑折叠为一行，用户可点击展开/收起。

### 5.2 事件契约示例

#### 思考卡事件 (`thought`)
```json
{
  "event": "thought",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "event_id": 12,
  "ts": 1724073600000,
  "payload": {
    "text": "规划：基准评测。先列出协议档和数据集，再组确认卡。",
    "latency_ms": 1250,
    "stage": "plan",
    "skill_id": "skill-benchmark"
  }
}
```

#### 工具卡事件 (`tool_result`)
```json
{
  "event": "tool_result",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "event_id": 14,
  "ts": 1724073601500,
  "payload": {
    "name": "model.list",
    "ok": true,
    "latency_ms": 48,
    "data": {
      "items": [
        { "id": "11111111-1111-1111-1111-111111111111", "name": "GPT-4o", "protocol": "openai_chat", "model": "gpt-4o" }
      ]
    }
  }
}
```

---

## 6. 异常处理与脱敏追踪

### 6.1 10 大错误码归一化映射

| 触发场景 | 归一化错误码 | 对外返回 message | HTTP 映射 |
| :--- | :--- | :--- | :--- |
| 未配置 Agent 协议档 | `ErrorCode.VALIDATION` | `"未配置 Agent 协议档，请先在协议档页指定 Agent 核心驱动"` | 400 |
| 协议档被删除或未配置 Key | `ErrorCode.VALIDATION` | `"Agent 协议档不存在或未配置 API Key"` | 400 |
| 上游 4xx / 5xx / 连接中断 | `ErrorCode.UPSTREAM` | `"Agent 模型调用失败"` | 502 |
| 模型调用超过指定超时 | `ErrorCode.TIMEOUT` | `"Agent 模型调用超时"` | 504 |
| 模型返回空白字符 | `ErrorCode.UPSTREAM` | `"Agent 模型返回空内容"` | 502 |
| 其它代码异常 | `ErrorCode.INTERNAL` | `"Agent 模型调用失败"` | 500 |

### 6.2 日志脱敏与 `agent_trace` 规范
- **输出位置**：`stderr`，格式前缀 `[agent] `；
- **允许输出**：`protocol`、`model`、`latency_ms`、`chars`、`code`；
- **严禁输出**：API Key、Bearer Token、Cookie、Password、完整 Prompt 内容。

```python
# 正确示例
agent_trace(f"模型调用完成 protocol={profile.protocol} model={profile.model} latency={result.latency_ms}ms chars={len(text)}")
```

---

## 7. 前端组件改动说明

1. **`ThoughtCard.vue`**：
   - 增加 `latencyMs?: number` 属性并在头部渲染 `formatLatency(latencyMs)`；
   - 监听 `done` 状态变化，使用 `setTimeout(..., 800)` 触发折叠动画；
2. **`ToolCard.vue`**：
   - 增加 `latencyMs?: number` 属性并在头部渲染；
   - 副标题固定为 `MCP · 短工具`；
3. **`Composer.vue` & `Agent.vue`**：
   - 顶栏与输入框只读展示 `Agent · {模型名}`；
   - 移除 `Agent.vue` 中原有的模型自由切换下拉菜单（`n-dropdown`）。

---

## 8. 测试验证矩阵

| 用例 ID | 测试项 | 前置条件 | 预期结果 |
| :--- | :--- | :--- | :--- |
| `test_agent_llm_success` | 正常模型调用与耗时记录 | Mock 协议档返回文本与耗时 | `AgentCallResult` 包含有效 `text` 与 `latency_ms > 0` |
| `test_agent_llm_missing_profile` | 未配置协议档报错 | `settings.agent_profile_id` 为空 | 抛出 `AppError(VALIDATION)` |
| `test_agent_llm_upstream_error` | 上游 502 错误归一 | Mock 上游 HTTP 500 异常 | 捕获并抛出 `AppError(UPSTREAM)`，不泄露堆栈 |
| `test_agent_llm_timeout_error` | 上游超时归一 | Mock 触发 socket 超时 | 捕获并抛出 `AppError(TIMEOUT)` |
| `test_agent_llm_key_redaction` | 日志无敏感密钥泄露 | 注入带 `sk-test-secret` 的 Key | 校验 `agent_trace` 输出不包含该密钥字符串 |

---

## 9. 修改代码文件与作用清单（全量审查与记录）

经完整代码审查与回归验证，本次 Agent 大模型接入、意图拆解、耗时体系打通与控制台日志增强共涉及以下 **11 个代码与测试文件** 的修改与新建：

### 9.1 后端服务层 (`backend/api/`)

| 序号 | 代码文件路径 | 变更类型 | 核心作用与改动说明 |
| :--- | :--- | :---: | :--- |
| 1 | `backend/api/app/llm.py` | **修改** | **Agent 核心大模型接入层**：<br>1. 实现 `resolve_agent_profile(db)`：从 `settings.agent_profile_id` 解析唯一绑定的驱动协议档，未配置时统一抛出 `AppError(VALIDATION)`（400）；<br>2. 实现 `get_agent_profile_public_info(db)`：提取公开只读脱敏信息（ID/名称/模型名/协议名）；<br>3. 定义 `AgentCallResult` 出参数据结构（包含 `text`, `latency_ms`, `usage`, `raw`）；<br>4. 实现 `call_agent_model` 与 `call_agent_model_detailed`：经由三协议统一适配器发起调用，精确计量端到端毫秒耗时并完成日志安全脱敏；<br>5. 异常严格归一化为 10 大标准错误码（`VALIDATION`/`UPSTREAM`/`TIMEOUT`/`INTERNAL`）。 |
| 2 | `backend/api/app/adapters.py` | **修改** | **三协议适配器与流式模型调用层**：<br>1. 增强 `stream_protocol` 中 `delta_of` 的思考字段自适应提取：同时兼容 `reasoning_content`、`reasoning` 与 `thought` 字段名，全面覆盖 DeepSeek、Mimo、Qwen、Ollama 等各品牌推理模型的思考链解析；<br>2. 增强非思考流式与单块（non-SSE）响应兜底机制，保障上游网关不丢字。 |
| 3 | `backend/api/app/routers/ws.py` | **修改** | **WebSocket 智能体双向通信与意图分发中枢**：<br>1. **解除回复长度限制**：重构 `_LLM_SYSTEM` 系统提示词，移除「一句话简洁回复」强制约束，明确指示模型严格按照用户要求的篇幅（如 500 字）展开，严禁在回复中暴露「输出结构化JSON」等元指令话术；<br>2. **流式 Token 与超时扩容**：将 `_stream_llm_plan` 的 `max_tokens` 从 512 扩大至 4096，`timeout_s` 扩大至 45.0s，避免推理模型在长思考链（Reasoning）后耗尽 Token 截断正文；<br>3. **纯文本降级容错**：`_parse_llm_json` 增加非 JSON 纯文本自动提取为 `chat` 意图机制，确保模型输出自然语言时绝不丢字、不报错；<br>4. **全链路真实耗时透传**：在 `_call_tool`、`_stream_llm_plan`、`_handle_user_message` 与 `_handle_rule_intent` 中全面计算并下发 `latency_ms` 字段至 `thought` 终帧与 `tool_result` 事件；<br>5. **历史上下文消息去重**：从数据库加载前 20 条历史时排除刚落库的当前用户消息，避免 Prompt 中历史尾部重复灌入当前消息；<br>6. **意图分类分流**：区分 `chat` 闲聊问候与 `benchmark`/`testcase`/`rag`/`report`，闲聊仅自然语言交互，绝不出确认卡、不调短工具；<br>7. **控制台断点日志追踪**：在 WS 接收、流式分发、工具调用、耗时计算各关键节点打齐脱敏的 `agent_trace`。 |
| 4 | `backend/api/tests/test_agent_llm.py` | **新建** | **大模型接入与耗时计算自动化单测**：包含 9 个专项单测，覆盖模型正常调用、耗时返回、未配置协议档报错、上游 502/超时归一化、敏感密钥脱敏校验以及公开信息接口验证。 |
| 5 | `backend/api/tests/test_ws_agent.py` | **修改** | **WebSocket 智能体单测套件**：更新 `_parse_llm_json` 容错单测（包含纯文本回退 chat 意图），新增 `test_classify_intent_chat_vs_benchmark` 意图分类测试。 |

### 9.2 前端展现层 (`frontend/src/`)

| 序号 | 代码文件路径 | 变更类型 | 核心作用与改动说明 |
| :--- | :--- | :---: | :--- |
| 6 | `frontend/src/views/Agent.vue` | **修改** | **Agent 对话主工作台视图**：<br>1. **模型下拉切换器**：将顶部 `chat-head` 与输入框底部的模型胶囊升级为 `<n-dropdown>` 下拉菜单，点击可即时查看接入模型列表并一键切换 Agent 驱动模型，切换后自动持久化到后台；<br>2. **DevTools 控制台彩色日志**：在 `handleWsEvent` 和 `handleSendClick` 中增加 WebSocket 收到事件、思考流式、助手回复交付、短工具调用/结果的完整控制台彩色调试日志输出；<br>3. **思考卡耗时与折叠**：思考卡根据 `item.latency_ms` 显示 `formatLatency` 耗时徽章（如 `16.2s`），并在思考完成后 800ms 自动平滑折叠；<br>4. **打字机平滑续播**：打字机 `typewriteTo` 根据全文长度自适应提速逐字推进。 |
| 7 | `frontend/src/api/ws.ts` | **修改** | **WebSocket 客户端底层通信类**：在 `onopen` 与 `onclose` 生命周期中增加连接状态就绪与断开的彩色控制台打印。 |
| 8 | `frontend/src/components/agent/ThoughtCard.vue` | **修改** | **思考卡独立组件**：接收 `latencyMs` 属性并格式化展示耗时徽章，支持折叠展开与 800ms 自动收起动画。 |
| 9 | `frontend/src/components/agent/ToolCard.vue` | **修改** | **短 MCP 工具卡独立组件**：接收 `latencyMs` 属性展示短工具执行耗时，副标题统一为 `MCP · 短工具`。 |
| 10 | `frontend/src/utils/format.ts` | **修改** | **前端统一格式化工具库**：实现并导出 `formatLatency(ms)` 统一耗时格式化函数（`<1000ms` 显示 `Xms`，`≥1000ms` 显示 `X.Xs`）。 |
| 11 | `frontend/src/schemas/confirmCard.ts` | **修改** | **确认卡数据模型与默认值定义**：确认卡默认参数全面对齐 PRD 5.2.2 与 §16.1（`sample_size: 1000, concurrency: 4, temperature: 0, max_tokens: 1024, stress.duration_s: 120, stress.qps: 10`）。 |

---

## 10. 方案落地与自动化测试验证总结

- **后端单元测试**：全量 174 项 Pytest 自动化测试全部通过（通过率 100%）；
- **代码静态扫描**：`ruff check .` 0 警告 0 错误通过；
- **前端生产构建**：`npm run build` Vite 生产打包 0 错误通过；
- **发布状态**：代码已全部合入 `main` 分支并推送到远程仓库，通过 GitHub Actions CD 自动部署至生产环境。
