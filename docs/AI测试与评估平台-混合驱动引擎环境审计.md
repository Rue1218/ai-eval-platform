# AI 测试与评估平台 — 混合驱动引擎前置环境与现状审计

> 📦 **历史归档（2026-09-11）**：本文为历史设计稿 / 规划，其中提及的 `agent/react.py`、`plan_solve.py`、`reflect.py`、`clarify.py` 等模块已删除或演进，仅作决策留痕；请勿按本文直接立项。

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | 混合驱动引擎（Hybrid Agent Engine）前置环境与现状审计 |
| 版本 | V1.3 |
| 审查日期 | 2026-09-03 |
| 文档性质 | **只读审计基线 + 后续状态校正**（不修改源码、配置、迁移与依赖） |
| 审计对象 | `backend/api/app/agent/`、`backend/api/app/harness/`、`backend/api/app/llm/`、`backend/api/app/routers/{ws,tasks,mcp}.py`、`backend/worker/app/`、`frontend/src/` |
| 审计基线 | 分支 `codex/fix/task-tool-contracts`，HEAD `95a8608 fix(task): 收敛任务工具契约与取消回执`。**本文全部行号为该基线快照值**（合入 main 后个别引用已漂移 ±数十行，如 `subagent_type` L794→L833），实施/评审时一律以**符号名为准**，行号仅供快速定位 |
| 下游文档 | [`docs/AI测试与评估平台-混合驱动引擎架构.md`](./AI测试与评估平台-混合驱动引擎架构.md)（混合驱动引擎架构需求） |
| 上游权威 | `docs/AI测试与评估平台-PRD.md`（产品范围）、`docs/AI测试与评估平台-API.md`（REST/WS 契约）、`docs/AI测试与评估平台-Agent开发文档.md`（当前链路）、`AGENTS.md`（工程红线） |

> **一句话结论**：本平台**不是**「缺少 Harness 的裸 LangGraph 项目」，而是**「Harness 六层基础设施已高度成熟、但编排层被 V1.6.0 骨架化主动拆除」**的项目。混合驱动引擎的主要工作量不在「从零构建 Plan/ReAct/Reflect」，而在**「重新接线 + 补齐 Router 分流、Agent Registry、缓存边界三处真实空白」**。

---

## 1. 环境探测（Environment Detection）

### 1.1 语言运行时

| 运行时 | 探测命令 | 实测结果 | 判定 |
| :--- | :--- | :--- | :--- |
| Python | `python --version` | **3.14.6** | 满足（`langgraph 1.2.10` 要求 ≥3.10；`__pycache__` 产物为 `cpython-314`，与宿主一致） |
| Node.js | `node --version` | **v24.5.0** | 满足（Vite 7 / vue-tsc 要求 ≥20） |
| npm | `npm --version` | **11.16.0** | 满足 |
| Go | `go version` | **go1.26.5 windows/amd64** | 仅服务 `backend/stress/`（go-stress-testing 发压引擎），与 Agent 引擎无关 |
| 宿主 OS | — | win32 10.0.26200（PowerShell） | **风险项**：`bwrap` 沙箱与 `runner` 容器只能在 Linux/Docker 内验证，本机不可全链路自测 |

> **关注点**：Python 3.14 为较新版本。`langgraph==1.2.10` 已可运行（测试 658 例可收集），但引入新依赖（如 `langchain` 主包、`langsmith`、`mcp`）时需逐个确认 3.14 wheel 可用性，避免源码编译失败。

### 1.2 密钥与配置探测

**配置单一事实源**：`backend/api/app/config.py`（`Settings(BaseSettings)`，85 行，`env_file=".env"`，`extra="ignore"`）。全仓库**只有这一个** Settings 类。

模型侧密钥专项核查（**不输出任何真实值**）：

| 期望配置 | 是否存在 Settings 字段 | 实际状态 |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | **无独立字段** | 仅在 `app/profile_env.py` 中作为 fetch-models 探测**别名**读取（L396 附近） |
| `ANTHROPIC_API_KEY` | **无独立字段** | 同上（L401 / L473 附近） |
| `LANGCHAIN_API_KEY` | **不存在** | 全仓库无引用 |
| `LANGSMITH_*` / `LANGCHAIN_TRACING_V2` | **不存在** | 无 LangSmith 追踪接入 |
| `LANGGRAPH_*` | **不存在** | 仅存在 PyPI 包 `langgraph==1.2.10`，无 LangGraph Platform / Cloud 配置 |
| `LLM_API_KEY` / `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` | 非 Settings 字段 | `profile_env.py` L236–239 声明为**全局兼容别名**；本机 `.env` 未出现 |

**模型 API Key 的真实存储路径（双轨，迁移中）**：

1. **主路径（现行）** — 协议档受控环境文件：`app/profile_env.py` 以协议档 ID 生成稳定变量名 `AI_PROFILE_{NORMALIZED_ID}_{BASE_URL|MODEL|API_KEY}`（L65–78），在 bind mount 的 `.env` 上**加锁刷新**；`docker-compose.yml` L105–106 将 `./.env` 挂载到 api 容器 `/run/config/.env`（可写），L177 对 worker 只读挂载。
2. **遗留路径（兼容）** — DB Fernet 加密列：`backend/shared/models.py` L216–234 `ProtocolProfile.encrypted_key`；加解密在 `app/security.py` L56–73（`KEY_ENCRYPTION_KEY` 为空时从 `SECRET_KEY` 派生 Fernet）。`routers/profiles.py` L100–102 / L320–322 新建与更新时**优先写 env 文件并清空 `encrypted_key`**。

> **矛盾点 C-1（文档漂移）**：`AGENTS.md` §5.2 第 3 条仍表述「API Key 必须用 Fernet 加密存储」，而代码主写入路径已迁移到挂载 `.env` 的 `AI_PROFILE_*`。混合引擎设计时**必须以 `profile_env.py` 为事实源**，否则新增 Worker Agent 取密钥会走到已废弃的 DB 列。

**其余关键配置项状态**（默认值 → 本机 `.env`）：

| 配置项 | 默认值 | 本机状态 | 对混合引擎的意义 |
| :--- | :--- | :--- | :--- |
| `agent_checkpointer` | `memory` | 已配置 = `memory` | **断点续跑当前不可用**（进程内存，重启即失） |
| `agent_native_stream_enabled` | `True` | 已配置 = `true` | native Function Calling 流式已开 |
| `agent_parallel_tool_batch_enabled` | `False` | 已配置 = `false` | **只读工具并行已实现但默认关闭** |
| `max_parallel_tool_calls` | `3` | 默认 | 并行度上限 |
| `harness_memory_short_term_enabled` | `False` | 未显式设置（取默认） | **Redis 短期记忆 Port 关闭** |
| `harness_memory_ttl_seconds` | `86400` | 默认 | — |
| `redis_url` | `redis://localhost:6379/0` | 已配置 | Redis 当前**仅**用于 WS 短票 |
| `sandbox_engine` | `bwrap` | 默认 | bash 走独立 `runner` 容器；`off` 时 fail-closed |
| `sandbox_runner_url` | `http://runner:8001` | compose 注入 | 沙箱内核已从 api 剥离 |
| `tool_preview_max_chars` | `600_000` | 默认 | ToolCard 预览上限 |
| `max_active_tasks_per_user` | `5` | 默认 | 长任务配额熔断 |
| `key_encryption_key` | `""` | **未配置** | 走 `SECRET_KEY` 派生，生产需独立配置 |
| `firecrawl_api_key` / `mimo_*_api_key` / `qwen_image_api_key` | `""` | **未配置** | `web_search` 未配 Key 时返回 `VALIDATION`（fail-closed，符合红线） |

### 1.3 依赖管理探测

依赖文件清单：`backend/api/requirements.txt`、`backend/api/requirements-dev.txt`、`backend/worker/requirements.txt`、`backend/lightrag/requirements.txt`、`frontend/package.json`、`backend/api/pyproject.toml`（仅 pytest/ruff 配置）、`backend/runner/pyproject.toml`。

AI / Agent 相关依赖实测：

| 包 | api | worker | 版本固定 | 代码中是否真实 import |
| :--- | :--- | :--- | :--- | :--- |
| **langgraph** | `==1.2.10` (L15) | `==1.2.10` (L8) | 是 | **是**（8 处，见下表） |
| **langchain-core** | 未显式声明 | 未显式声明 | 传递依赖 | 间接（由 langgraph 拉入），无直接 import |
| **langchain**（主包） | 未声明 | 未声明 | — | **否**（全仓库无 `import langchain`） |
| **langsmith** | 未声明 | 未声明 | — | **否** |
| **openai** | `==2.53.0` (L16) | — | 是 | 是（`app/adapters.py` L26–29） |
| **anthropic** | `==0.122.0` (L17) | — | 是 | 是（同上） |
| **mcp**（PyPI 官方 SDK） | 未声明 | 未声明 | — | **否**。项目的「MCP」是**内部自建模块** `app.harness.execution.mcp` + `/api/mcp/*` REST 目录，**不是** Model Context Protocol 官方实现 |
| redis | `==5.2.1` (L14) | — | 是 | 是（仅 `ws_tickets.py`） |
| sqlalchemy | `==2.0.36` | `==2.0.36` | 是 | 是 |
| fastapi / pydantic / pydantic-settings | `0.115.6` / `2.10.4` / `2.7.0` | — | 是 | 是 |
| cryptography | `==44.0.0` | `==44.0.0` | 是 | 是（Fernet） |
| websockets | `==14.1` | — | 是 | 是 |

`langgraph` 真实 import 落点：

| 文件 | 行号 | 用途 |
| :--- | :--- | :--- |
| `backend/api/app/agent/graph.py` | L17 | Agent 骨架图 `StateGraph / START / END` |
| `backend/api/app/agent/routing.py` | L14 | `get_stream_writer` 流式增量 |
| `backend/api/app/llm/gateway.py` | L14–15 | ModelGateway 内部小图（invoke / stream 各一张） |
| `backend/api/app/harness/execution/toolnode.py` | L19–21 | 工具节点、`interrupt()` |
| `backend/api/app/harness/memory/checkpoint.py` | L20–28 | Memory / Pg Checkpointer |
| `backend/worker/app/eval_graph.py` | L18 | **Worker 侧独立评测流水线图**（benchmark 执行） |
| `backend/api/tests/test_bash_hitl.py` | L7–8 | HITL interrupt 测试 |
| `backend/api/tests/test_checkpointer.py` | L3 | 检查点测试 |

> **矛盾点 C-2（术语碰撞，高危）**：需求中的「MCP 工具接入（Github MCP / SQLite MCP）」与本平台既有「MCP」是**同名异物**。平台 MCP 为内部受控目录，且 `AGENTS.md` 六大红线第 1 条明文**禁止外部 MCP**。混合引擎设计必须显式区分二者并给出「若要引入外部 MCP，须先改 PRD/API.md」的前置门。

### 1.4 项目结构探测

根目录（`ls -Force`）：`.claude/ .git/ .github/ artifacts/ backend/ deploy/ docs/ frontend/ product-site/ tools/ Web-Prototype/ .env .env.example .gitattributes .gitignore AGENTS.md baota_root_ca.crt design-qa.md docker-compose.yml README.md`

需求中点名的关键路径逐一核对：

| 期望路径 | 存在性 | 实际情况 |
| :--- | :--- | :--- |
| `langgraph.json` | **不存在** | 未使用 LangGraph CLI / Platform 部署形态；图在 FastAPI 进程内手工编译 |
| `specs/` | **不存在** | V1.1 起本文档直接归档 `docs/`（`AI测试与评估平台-` 前缀命名合规，C-9 已关闭，无需迁移） |
| 根 `src/` | **不存在** | 仅 `frontend/src/`（71 文件） |
| 根 `config/` | **不存在** | 配置收敛在 `backend/api/app/config.py` |
| `.claude/` | **存在** | 仅 `.claude/settings.local.json`（IDE 本地设置，非 Agent 指令） |
| `CLAUDE.md` | **不存在** | 项目指令由根 `AGENTS.md` 承担（面向开发者与编码 Agent，**不注入运行时 Agent 系统提示词**） |
| `AGENTS.md` | **存在** | 工程规范与六大红线 |
| Skill `.md` 文件 | **存在，4 个** | `backend/api/app/harness/skills/files/skill-{benchmark,testcase,rag,stress}/SKILL.md` |

`backend/api/app/harness/` 目录结构（源码，排除 `__pycache__`）：

```text
harness/
├── context/       上下文工程层：assembly / window / meter / compact / observation
├── contracts/     跨层契约层：NodeEvent / PlanArtifact / TaskState / ToolDescriptor / SkillHint
├── execution/     执行层：registry / dispatch / sandbox / toolnode / batch / policy / mcp / task_tools
├── feedback/      反馈层：rules(门禁) / observation 归一 / review
├── llm/           占位（1 行 __init__.py；真实网关在 app/llm/）
├── memory/        记忆层：state(GraphState) / checkpoint / working / episodic / compressed / semantic
├── orchestration/ 编排层：router / plan / confirm / budget / gates
├── prompts/       提示词层：system / protocols / safety
├── security/      跨层安全：auth / secrets 脱敏
└── skills/        技能体系：registry / storage / workflows / files/*/SKILL.md
```

---

## 2. 现状梳理（Read-Only Audit）

### 2.1 状态机审计：LangGraph 图定义

**生产 Agent 图（唯一活跃图）**——`backend/api/app/agent/graph.py` L48–57：

```48:57:backend/api/app/agent/graph.py
    def _build_graph(self):
        """构建骨架图：路由 → 纯对话流式节点 → 结束。"""
        graph = StateGraph(GraphState)
        graph.add_node("chat_stream", self._make_chat_node())
        graph.add_edge(START, "chat_stream")
        graph.add_edge("chat_stream", END)
        # 阶段 3：Checkpointer 按 thread_id 隔离回合（M3-D4 恢复语义）
        if self._checkpointer is not None:
            return graph.compile(checkpointer=self._checkpointer)
        return graph.compile()
```

| 指标 | 实测值 |
| :--- | :--- |
| 节点数（Node） | **1**（`chat_stream`） |
| 边数（Edge） | **2**（均为无条件边：`START→chat_stream`、`chat_stream→END`） |
| 条件边（Conditional Edge） | **0** |
| 注入模型的工具定义 | **0**（`routing.py` 固定 `tools=()`） |
| `interrupt()` 处理 | **0**（`ahas_pending_interrupt` 恒返回 `False`，graph.py L108–110） |
| `recursion_limit` | 32（`_prepare_run_config`，L122） |
| 检查点 | 已挂载但默认 `InMemoryCheckpointer`，每回合独立 `thread_id`，`_discard_thread` 为空占位 |
| 子图 | 无 |

**另有两张非 Agent 图**（不属编排，勿混淆）：`app/llm/gateway.py` 内 `_ModelCallState` 小图（HTTP 协议适配）；`backend/worker/app/eval_graph.py`（Worker 评测流水线）。

### 2.2 State 类型审计

**位置**：`backend/api/app/harness/memory/state.py`（153 行）。**类型**：`TypedDict, total=False`（非 dataclass / Pydantic），配 `assert_serializable()` 反射断言全字段 `json.dumps` 安全。

`GraphState` 共 **25 个字段**，其中 3 个带 append reducer（`_append_events` / `_append_observations` / `_append_native_messages`）。骨架图实际只写 3 个字段：

| 字段 | 类型 | 语义 | 骨架图使用 |
| :--- | :--- | :--- | :--- |
| `request` | `SerializableRequest` | ModelRequest 投影（**剔除 `api_key` 与 `should_abort`**） | **✅ 使用** |
| `pending_events` | `Annotated[list[NodeEvent], append]` | 节点产出的 WS 事件意图，ws.py 图外消费 | **✅ 使用** |
| `response` | `Mapping` | ModelResponse 投影（text / usage / latency_ms） | **✅ 使用** |
| `mode` | `AgentMode = Literal["chat","direct","react","plan_solve"]` | 路由模式，供条件边读 | ❌ 预留 |
| `plan` | `object \| None` | `PlanArtifact` 投影 | ❌ 预留 |
| `observations` | `Annotated[list, append]` | 工具观察累积（OR-4 重复检测依赖全历史） | ❌ 预留 |
| `pending_tool` / `pending_tools` / `pending_tool_batch` | `Mapping` / `list` / `Mapping` | 当前 ToolCall、队列、同轮批次 | ❌ 预留 |
| `native_messages` | `Annotated[list, append]` | 原生 assistant/tool 往返消息 | ❌ 预留 |
| `stop_flag` / `turn_failed` | `bool` | 条件边停止 / ReAct 硬错误 | ❌ 预留 |
| `repeat_retry` | `bool` | OR-4 重复只读调用首次纠正标记 | ❌ 预留 |
| `replan_count` / `force_replan` / `replan_reason` | `int` / `bool` / `str` | **有界重规划三件套（上限 2）** | ❌ 预留 |
| `step_fail_count` | `int` | 失败阶梯：同一步连续失败计数 | ❌ 预留 |
| `parse_retries` | `int` | ReAct 协议解析纠正重试 | ❌ 预留 |
| `budget` | `Mapping[str,int]` | count-only 预算投影 | ❌ 预留 |
| `clarify_answer` / `clarify_id` | `str \| None` | 澄清卡 `interrupt()` 恢复 | ❌ 预留 |
| `verdict` | `ReflectVerdict = Literal["pass","clarify","reject","retry","repair"]` | **Reflection 结论** | ❌ 预留 |
| `task_state` / `task_state_observation_count` | `Mapping` / `int` | 结构化任务状态机投影与消费游标 | ❌ 预留 |
| `session_tasks` | `list` | 会话内任务看板（不写 PG tasks 表） | ❌ 预留 |

**关键设计不变量（必须继承，不可推翻）**：

- `api_key` **不入** `SerializableRequest.config`（`_CONFIG_KEYS` 白名单仅 10 项），节点从 `RunnableConfig.configurable` 或 DB 即时注入 `ModelGateway`；
- `should_abort` 回调**不入 State**，走 `configurable["abort"]["should_abort"]`；
- `pending_events` 图内 append、**图外清空**，恢复检查点时必须清空以避免事件重放（重放只走 `ws_events`）。

> **重要发现**：`GraphState` 是**为完整混合图设计的 Schema**，而非骨架图的 Schema。`replan_count`、`force_replan`、`verdict="repair"`、`step_fail_count` 这些字段的存在，直接证明 **Plan / Reflect / Replan 曾经完整实现并运行过**。

### 2.3 模式冲突识别：当前是纯 ReAct、纯 Workflow，还是混合？

**结论：当前生产运行时既不是 ReAct 也不是 Workflow，而是「退化为单轮纯对话（Chat-only）」；但代码库里保留着一套完整度约 70% 的混合范式库代码。**

`docs/AI测试与评估平台-Agent混合范式与架构完善.md` **V0.3.3**（2026-08-26）记载的**已落地**状态为：

```text
START → routing
          ├─ direct ─────────────── END
          ├─ chat_stream ────────── END
          └─ plan_solve → react_agent ⇄ tools → reflect
                                                  ├─ pass    → END
                                                  ├─ repair  → react_agent（失败阶梯首档）
                                                  ├─ clarify → interrupt()
                                                  └─ retry   → planner（有界重规划 ≤2）
```

该文档明确 P0 / P0+ / P1 / P2 **全部「已落地」**：LLM Planner 一次短调用产 `plan.v1` JSON、L0 关键词降级、`MAX_REPAIRS=1` / `MAX_REPLANS=2` 常量、`verdict=clarify` 挂 `interrupt`、中间阶段叙述（API.md V1.33）。

随后 `ce02684 refactor(agent): Agent 骨架化：移除范式与思考链，收敛为纯对话图` **主动拆除**了上述编排。拆除边界实测：

| 组件 | 源文件 | 状态 | 生产调用方 |
| :--- | :--- | :--- | :--- |
| `agent/react.py` / `plan_solve.py` / `reflect.py` / `clarify.py` | — | **已删除** | — |
| `harness/orchestration/react_loop.py` | 源文件已删，仅剩 `__pycache__/react_loop.cpython-314.pyc` | **死产物** | 无 |
| `harness/orchestration/router.py`（105 行，`decide_mode` / `detect_plan_intent`） | 保留 | **库完整，死连** | **`app/` 内零调用** |
| `harness/orchestration/plan.py`（176 行，`build_plan` L0 规划） | 保留 | **库完整，死连** | 仅测试 |
| `harness/orchestration/confirm.py`（228 行） | 保留 | **库完整，死连** | 仅测试 |
| `harness/prompts/protocols.py`（182 行，`parse_react` / `parse_plan` / `parse_reflect`） | 保留 | **库完整，死连** | 仅测试 |
| `harness/execution/toolnode.py`（544 行，含 `interrupt()` 与并行波次） | 保留 | **库完整，死连** | 仅测试构造图 |
| `harness/execution/registry.py`（1256 行） / `dispatch.py`（1264 行） / `sandbox.py` | 保留 | **完整可用** | `/api/mcp/*` 目录 + 测试 |
| `harness/feedback/review.py` | **保留但已收窄**（39 行三档简版：`ReflectVerdict = pass/clarify/reject`，注释明确「不定义 reflect_node」；`REFLECT_SCHEMA` enum 同为三档，五档 `verdict` 仅残留于 `state.py` 类型注释） | **库函数（简版）** | **零调用（含测试）**，仅 `feedback/__init__.py` re-export |

> **矛盾点 C-3（真实冲突，非功能重叠）**：这不是「两套并存的循环」冲突（`AGENTS.md` 禁止第二条 Harness 循环，现网确实只有一条），而是**「基础设施与编排层的接线断裂」**。混合引擎的正确姿势是**恢复接线并升级**，而非新写一套。若忽视此点重新实现，将直接触碰红线第 5 条「禁止全量无意义重写」。

**功能重叠（可容忍，非冲突）**：`harness/orchestration/router.py::decide_mode`（确定性关键词路由）与需求 §2.1 的「LLM 长思维链 Router」职责重叠。既有文档 §10-Q3 / §6-8 明确裁决「**不用 LLM 替代 `decide_mode` 做每次分流**」。此为**设计意图冲突**，需在架构文档中显式裁决（见 `docs/AI测试与评估平台-混合驱动引擎架构.md` ADR-1）。

### 2.4 工具与调度审计

**工具注册表数据结构** — `harness/execution/registry.py` L47–80，`ToolDef` 为 `@dataclass(frozen=True, slots=True)`，**19 个字段**：

```46:80:backend/api/app/harness/execution/registry.py
@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str
    description: str
    parameters_schema: Mapping[str, object]
    permission: str
    timeout_s: float
    handler: Callable[..., object]
    output_schema: Mapping[str, object] = field(default_factory=dict)
    permission_policy: ToolPermissionPolicy = ToolPermissionPolicy()
    recovery_policy: ToolRecoveryPolicy = DEFAULT_RECOVERY_POLICY
    transport: Literal["native", "mcp"] = "mcp"
    risk_level: Literal["read", "modify", "network", "code", "long"] = "read"
    execution_mode: Literal["short", "long"] = "short"
    requires_confirmation: bool = False
    supports_streaming: bool = False
    contextual: bool = False
    concurrency_class: Literal["read_only", "path_scoped", "exclusive", "session_exclusive"] = "exclusive"
    requires_prior_result: bool = False
```

**与 Claude Code 工具生命周期标志的语义映射**（需求 §2.4 的 `isReadOnly` / `isDestructive` / `isConcurrencySafe`）：

| Claude Code 标志 | 本平台等价 | 判定 |
| :--- | :--- | :--- |
| `isReadOnly` | `risk_level == "read"` + `permission_policy.workspace == "read"` | **✅ 已满足**（语义等价，命名不同） |
| `isDestructive` | `risk_level ∈ {"modify","code"}` + `requires_confirmation` + `dispatch.py` bash 破坏性命令分类 | **✅ 已满足，且比 Claude Code 更细**（bash 三分类：只读 / 变异 / 破坏性 → `bash_approval_reason`） |
| `isConcurrencySafe` | `concurrency_class ∈ {"read_only","path_scoped","exclusive","session_exclusive"}` | **✅ 已满足，且更细**（四档 + 资源键冲突检测，非布尔） |
| 结果大小阈值 | 见下表 | **✅ 已满足** |
| 权限校验 | 四层纵深（见下） | **✅ 已满足** |

**结果大小阈值实测**：

| 场景 | 阈值 | 位置 |
| :--- | :--- | :--- |
| 模型可见工具结果 | 8 000 字符（`MODEL_TOOL_RESULT_MAX_CHARS`） | `harness/context/observation.py` L15 |
| `read` 窗口 | 2 000 行 / 600 000 字符 | `harness/execution/dispatch.py` L49–55 |
| `web_fetch` | 60 000 字符 | `dispatch.py` L64 |
| ToolCard 浏览器预览 | `settings.tool_preview_max_chars`（默认 600 000） | `harness/execution/policy.py` L78–80 |
| WS 流式块 | `TOOL_STREAM_CHUNK_CHARS = 800` | `policy.py` L75 |

**权限校验四层纵深**：

1. 注册表层：未注册工具 → `AppError(VALIDATION)`（`registry.py` L131–135），且注册时校验参数/输出 Schema 属于已实现关键字子集（`_SUPPORTED_SCHEMA_KEYWORDS`，9 个关键字）；
2. 策略层：`ToolPermissionPolicy`（`workspace: none|read|write`、`network: none|public_only`、`require_owned_attachment`、`require_session_task_owner`、`confirmation_required`）；
3. 门禁层：`harness/feedback/rules.py::check_gates` **8 类确定性门禁**（长工具入队、白名单、bash 黑名单、kind 合法性、必填槽、附件归属、活动任务占槽、先评后压）；
4. 执行层：`dispatch.py` bash 命令分类 + `sandbox.py` 经 `runner` 容器 bwrap（`engine=off` 时 **fail-closed**）；`task_tools.py` 中 `session_id` / `user_id` **仅由平台上下文注入，模型不可伪造**。

**并行 / 串行策略**（`harness/execution/batch.py`，210 行）：`PARALLEL_ELIGIBLE_NAMES = {read, web_search, web_fetch}`；`select_execution_wave()` 按 `concurrency_class` 与资源键做冲突检测；写 / bash / 任务类**强制串行**；bash 非只读 → `toolnode.py` L351–383 触发 `interrupt()` 人工确认。**受 `agent_parallel_tool_batch_enabled=False` 灰度门关闭**。

**默认注册工具集**（`build_default_registry()`，L403+）：`read` / `write` / `edit` / `web_search` / `web_fetch` / `bash` / `task` / `TaskCreate|TaskGet|TaskUpdate|TaskList`（会话看板） / `ask_user_question` / `platform.tasks.task.{create,status,cancel}`（`transport=mcp`）。

**REST/WS 调度面**：

| 面 | 文件 | 关键端点 / 事件 |
| :--- | :--- | :--- |
| 任务控制面 | `routers/tasks.py` | `POST /api/tasks`(L81) / `GET /api/tasks`(L183) / `summary`(L203) / `{id}`(L215) / `cancel`(L234) / `rerun`(L267) / `approve-stress`(L319) / `stress-series`(L368) |
| 工具目录（只读） | `routers/mcp.py` | `GET /api/mcp/tools`(L468) / `all-tools`(L476) / `health-check`(L500) / `tools/{name}/code`(L580) / `metrics`(L610)。L11–12 注释明确「当前 Agent 为纯对话骨架，MCP 目录不代表模型正在调用工具」 |
| Agent 通道 | `routers/ws.py` | `WS /ws/agent`(L1151)。入向 2 类：`user_message`（`/stop` 前缀走 L1254–1263 中断）、`cancel_task` |

**WS 事件全集**（前端 `frontend/src/api/types.ts` L880–893，12 个）：`user_message` / `message` / `assistant_delta` / `assistant_message` / `response.completed` / `done` / `progress` / `report` / `task_cancelled` / `error` / `session_title` / `pong`。其中 `assistant_delta` 与 `pong` 为**瞬态帧**（不落库、不占事件号）；Worker 跨进程事件转发白名单为 `progress` / `report` / `error`（须带 `task_id`，`ws.py` L434）。

> **注**：`tool_call` / `tool_result` / `thought` / `confirm_card` / `clarify_card` / `plan` 等事件已随骨架化从前端类型中移除。混合引擎恢复工具链路时，**必须先改 `docs/AI测试与评估平台-API.md` 再改代码**（红线第 1 条）。

**长短任务分离（已满足）**：`tasks` 表状态机 `queued → running → succeeded|failed|cancelled`（testcase 另有 `awaiting_case_confirm`）；`backend/worker/app/main.py` L220–272 主循环以 `SELECT ... FOR UPDATE SKIP LOCKED` 领取，受 `settings.max_running_tasks`（默认 3）闸门；`uq_tasks_active_session` 部分唯一索引保证同会话任务串行。执行器入口：`run_benchmark(task_id)`（benchmark.py L472）、`run_testcase(task_id)`（testcase.py L136）、`run_rag(task_id)`（rag.py，V1.2 修正：**真实执行**，LightRAG 优先 + 本地关键词兜底，报告须 `degraded`/`engine_counts` 标注）、`run_stress(task_id)`（stress.py，V1.2 修正：**已对接真实压测引擎**，见 C-11）。

### 2.5 上下文管理审计

**系统提示词构建** — `harness/prompts/system.py`（59 行）：五段固定策略（角色 / 安全 / 确认卡 / 长短任务 / 密钥保护）+ 受控槽 `SystemVars(skill_hints, session_owner, agent_prompt_overlay)`；占位符白名单校验，**禁止用户文本注入**（PR-4）。

两处装配（**当前重复构建**）：

1. `routers/ws.py` L838–843 预构建 `system_prompt`（含 `skill_hint_lines()` 与 DB 中的 `agent_prompt_overlay`）；
2. `agent/routing.py` L42–56 节点内以 `serializable["system"]` 为主、`build_system_prompt` 为 fallback，再调 `assemble()`。

**装配顺序（CX-4，固定）** — `harness/context/assembly.py` L60–73：

```text
Persona → 【可见技能】Skill Hint → 【当前技能工作流】→ 【会话摘要】→ 【当前阶段】→ messages
```

骨架路径不传 `skill_workflow`、`stage_input`、`tool_defs`。

**Progressive Disclosure（已满足）**：`skills/registry.py::list_hints()` 只读 SKILL.md 固定头部产出 Hint（名称+一句话）；完整工作流经 `skills/workflows.py::load_skill_workflow(skill_id)` **按需加载且明令不写入 GraphState**；未启用技能（`skill-rag`）返回 `VALIDATION`。这与 Claude Code 的 Skills 渐进披露**机制等价**。

**上下文度量与压缩**：

| 组件 | 文件 | 状态 |
| :--- | :--- | :--- |
| 消息窗口 | `context/window.py` | ✅ 末尾 20 条 user/assistant，`compact_keep_from` 截断 |
| Token 估算 | `context/meter.py` | ✅ CJK / 英文启发式 `estimate_tokens` |
| ContextMeter 只读 API | `routers/sessions.py::build_session_context_meter` | ✅ 前端 `GET /api/sessions/{id}/messages` 消费 |
| Compact 压缩 | `context/compact.py` | ⚠️ **`summarize()` 为确定性截断**，注释写明「LLM 压缩待接入」 |
| 压缩持久化 | `memory/compressed.py` | ✅ 写 `sessions.compact_summary` |

**缓存边界（Cache Boundary）—— 完全缺失**：全 `backend/api` 无 `cache_control`、无 Anthropic prompt caching、无 OpenAI prompt cache 相关实现。当前每轮把 Persona + Skill Hint + 摘要重新拼成**一整块** `system` 字符串下发（`assemble()` L70 `"\n\n".join(sections)`），静态段与动态段**无边界标记，物理上不可缓存**。

**CLAUDE.md 式指令分层 —— 部分缺失**：存在根 `AGENTS.md`（面向开发者/编码 Agent，**不进运行时提示词**）与 DB 中的 `agent_prompt_overlay`（会话/协议档级 overlay），但**没有**「全局级 / 用户级 / 项目级」三层优先级与不可覆盖核心段的显式声明。

### 2.6 记忆层审计

| 记忆层 | 实现 | 存储 | 状态 |
| :--- | :--- | :--- | :--- |
| 回合态（Working） | `memory/working.py` + `GraphState` | Checkpointer（memory / PG） | ✅ |
| 情景（Episodic） | `memory/episodic.py` | PostgreSQL `ws_events` | ✅ |
| 压缩摘要（Compressed） | `memory/compressed.py` | PG `sessions.compact_summary` | ✅（摘要算法待升级） |
| 语义（Semantic） | `memory/semantic.py` | — | ❌ **占位，`retrieve` 直接抛 `VALIDATION`**（fail-closed，符合红线） |
| 短期（Redis） | — | — | ❌ **无源文件**；`config.py` 仅留开关 `harness_memory_short_term_enabled=False` |
| 检查点表 | `memory/checkpoint.py`（488 行） | PG `harness_checkpoints` | ✅ 表结构就绪，**默认不启用** |

Redis 当前唯一用途：`routers/ws_tickets.py` 的 WS 短票 `SET NX`（5 分钟单次票），**不是** Harness 记忆层。

### 2.7 数据模型与测试基线

**模型单一事实源**：`backend/shared/models.py`（api 与 worker 共用，`api/app/models.py` 仅 re-export）。关键表：

- `tasks`（L477–519）：`id` / `session_id` / `parent_task_id` / `kind` / `status` / `config`,`progress`,`result`(JSONB) / `report_id` / `created_by` / `claimed_by_worker_id`,`claim_expires_at`,`attempt` / `cancel_requested_at` / 四个时间戳；
- `task_events`（L522–533）：`id` / `task_id` / `event` / `level` / `message` / `payload`(JSONB) / `ts`；
- `ws_events`（L198–213）：`id` / `session_id` / `task_id` / `event_id`（会话内单调） / `event` / `payload`(JSONB) / `ts`；
- `protocol_profiles`（L216–234）：含遗留 `encrypted_key`。

**测试基线**：`backend/api/tests/` 共 **65 个** `test_*.py`，`pytest --collect-only -q` 收集 **658 例**。Agent / WS / Task / MCP 相关子集约 **134 例**，重点覆盖：`test_harness_execution.py`(57) / `test_task_tools.py`(26) / `test_harness_context.py`(22) / `test_harness_mcp.py`(16) / `test_checkpointer.py`(15) / `test_harness_metrics.py`(14) / `test_llm_graph.py`(12) / `test_stream_rollout.py`(10) / `test_ws_turn_concurrency.py`(7) / `test_bash_hitl.py`(6) / `test_agent_multiturn.py`(6) / `test_agent_graph.py`(2)。

> **缺口**：路由分流、Plan 产物、Reflection 判决、有界重规划的测试文件（`test_agent_routing.py` / `test_harness_phase4.py`）已随骨架化移除；恢复编排时须重建。

---

## 3. 差距矩阵：目标混合引擎 vs 当前实现

图例：**✅ 已满足**（可直接复用） / **🟡 需重构**（库代码存在，需接线或升级） / **🔴 缺失**（需新建）

### 3.1 需求 §2.1 双引擎驱动（Router 分流）

| 需求项 | 判定 | 依据与工作量 |
| :--- | :--- | :--- |
| 顶层 Router 节点 | 🟡 需重构 | `orchestration/router.py::decide_mode` 库完整但**零生产调用**；需重新加入图并从「4 范式分流」升级为「Workflow / Agent 双引擎分流」 |
| Router 使用长思维链（CoT）判别 | 🔴 缺失（且**与既有裁决冲突**） | 既有文档明令「不用 LLM 替代 `decide_mode`」。须在 ADR 中裁决为**混合 Router**：确定性特征先行，仅低置信度时才调一次模型 |
| Workflow 子图 | 🔴 缺失 | 无 DAG 子图；但 `SKILL.md` 工作流正文与 `check_gates` 可作为 DAG 节点素材 |
| Agent 子图 | 🟡 需重构 | `plan.py` / `protocols.py` / `toolnode.py` / `review.py` 齐备，缺图与边 |

### 3.2 需求 §2.2 Agent 子图（Orchestrator-Worker + TAOR）

| 需求项 | 判定 | 依据与工作量 |
| :--- | :--- | :--- |
| Orchestrator 极简（代码只驱动循环） | ✅ 已满足（理念） | 既有文档 §2.1 已冻结「LLM 当受控微服务，外层循环由代码控制」；`toolnode.py` 即哑执行器 |
| TAOR（Think→Act→Observe→Repeat） | 🟡 需重构 | 平台已冻结为 **OTA（Observe→Think→Act）**，语义等价、顺序表述不同；`observations` append reducer 与 `native_messages` 回灌机制在库中完整 |
| Plan 节点 | 🟡 需重构 | `orchestration/plan.py::build_plan`（L0 关键词降级）完整；LLM 规划节点 `plan_solve.py` **已删除**，需重写节点壳（约 150 行） |
| Reflection 节点 | 🟡 需重构 | `feedback/review.py` 仅 39 行三档简版（`pass/clarify/reject`、零调用），**无 L1/L2/L3 分级实现**；`reflect.py` 节点已删除；五档 `ReflectVerdict`（含 `repair`）仅残留 `state.py` 类型注释——需**恢复性扩展**判决逻辑与 `REFLECT_SCHEMA` / `parse_reflect`（C-10） |
| Replan（有界重规划） | 🟡 需重构 | `replan_count` / `force_replan` / `replan_reason` / `step_fail_count` 字段与 `MAX_REPAIRS=1` / `MAX_REPLANS=2` 阈值语义均有记载，需重建条件边 |
| **Agent Registry（能力标签 + 工具集）** | 🔴 **完全缺失** | 无 `AgentRegistry` 类；`task` 工具 schema 中 `subagent_type` 明确标注「仅展示，不启子代理」（`registry.py` L794 附近）。`ToolRegistry` 可作实现范本 |
| Worker 内嵌 ReAct | 🟡 需重构 | ReAct 双协议（`legacy` 严格 JSON / `native` Function Calling）在 `protocols.py` + `stream_policy.py` 中完整 |
| **多 Agent 并发编排** | 🔴 缺失（且**受红线约束**） | `AGENTS.md` 禁止第二条 Harness 循环。须裁决为「**单图内 Worker 子图**（同一 `LangGraphAgent` 入口）」，不是独立进程级多 Agent |

### 3.3 需求 §2.3 Workflow 子图（规则导向 + Skill 绑定）

| 需求项 | 判定 | 依据与工作量 |
| :--- | :--- | :--- |
| 硬编码 DAG | 🔴 缺失 | 需新建；LangGraph `StateGraph` 无条件边即可表达 |
| Skill 动态加载（`.md` 注入） | ✅ **已满足** | `skills/workflows.py::load_skill_workflow` + `assemble(skill_workflow=...)` 即 Progressive Disclosure；4 个 SKILL.md 就位 |
| Skill 未启用 fail-closed | ✅ 已满足 | `assert_skill_enabled` → `VALIDATION`，`skill-rag` 禁止 mock |
| 确定性保障（不可跳跃回溯） | 🟡 需重构 | `check_gates` 8 类确定性门禁可直接复用为 DAG 节点前置断言 |
| Workflow 节点内局部 ReAct 但不越权 | 🔴 缺失 | 需新增「受限 ReAct」概念：`select_tool_defs(planned_only=True)` 已提供**工具视野收窄**的基础设施 |

### 3.4 需求 §2.4 生产级机制

| 需求项 | 判定 | 依据与工作量 |
| :--- | :--- | :--- |
| **上下文缓存边界** | 🔴 **完全缺失** | 无 `cache_control`；`assemble()` 把静态段与动态段 `join` 成单块字符串。需改造为分段返回 + 适配器落 `cache_control`（`adapters.py`） |
| 工具生命周期标志 | ✅ **已满足（且更细）** | `risk_level` / `execution_mode` / `concurrency_class` / `requires_confirmation` / `permission_policy` / `recovery_policy`，见 §2.4 映射表 |
| 读工具并行 / 写工具串行 | 🟡 需重构（**代码已成，开关关闭**） | `batch.py::select_execution_wave` + `agent_parallel_tool_batch_enabled=False`。属灰度开量而非开发 |
| 权限校验 | ✅ 已满足 | 四层纵深防御 |
| 结果大小阈值 | ✅ 已满足 | 五档阈值 |
| Checkpointer 断点续跑 | 🟡 需重构（**代码已成，默认 memory**） | `PgCheckpointer` 488 行就绪；切换须评审多副本粘性路由 |
| 人工审批（Interrupt / HITL） | 🟡 需重构 | `toolnode.py` bash HITL 与 `ask_user` 已用 `langgraph.types.interrupt()`，有 6 个测试用例；但**生产图不含 ToolNode**，`ws.py` 无 `resume` 调用，`ahas_pending_interrupt` 恒 `False` |
| 事件溯源 | ✅ 已满足 | `ws_events` 单调 `event_id` + `last_event_id` 断线补发；`task_events` 任务时间线 |
| CLAUDE.md 式指令优先级 | 🟡 需重构 | 有 `AGENTS.md`（不进运行时）与 `agent_prompt_overlay`（会话级），缺三层优先级与核心段不可覆盖声明 |

---

## 4. 重构前必须解决的矛盾点（阻塞项）

| 编号 | 矛盾 | 影响 | 建议裁决 | 拍板方 |
| :--- | :--- | :--- | :--- | :--- |
| **C-1** | `AGENTS.md` 称 API Key 走 DB Fernet（§5.2 第 3 条），代码主路径已迁移到挂载 `.env` 的 `AI_PROFILE_*` | 新 Agent/Worker 取密钥可能走废弃列 | 以 `profile_env.py` 为事实源；回写 `AGENTS.md` §5.2 第 3 条 | 架构 |
| **C-2** | 需求的「外部 MCP（Github / SQLite）」与平台内部 MCP 同名异物，且红线禁止外部 MCP | 直接触碰六大红线第 1 条 | 混合引擎**默认不接外部 MCP**；预留 `ExternalMCPGateway` 接口但 fail-closed，启用须先改 PRD + API.md | 产品 + 架构 |
| **C-3** | 编排层被骨架化拆除，但基础设施完整；库代码「死连」 | 若重新实现将触碰红线第 5 条「禁止全量无意义重写」 | 采取「**恢复接线 + 增量升级**」路线，禁止另起 Harness | 架构 |
| **C-4** | 需求要求 Router 用 LLM 长思维链；既有文档明令「不用 LLM 替代 `decide_mode`」 | 设计意图直接冲突 | 混合 Router：确定性特征优先，低置信度才调一次短模型，失败降级 L0 | 架构 |
| **C-5** | 需求的「多 Agent Orchestrator-Worker」vs 红线「不新增第二条 Agent 循环」 | 架构合法性 | Worker 实现为**同图内子图**，共用唯一 `LangGraphAgent` 与 `ModelGateway` | 架构 |
| **C-6** | 恢复工具链路需要 `tool_call` / `tool_result` / `thought` / `plan` 等 WS 事件，但骨架化已从 API.md 与前端类型中移除 | 红线第 1 条「新字段必须先改 API.md」 | 每阶段**先改 API.md、再改代码、再改前端** | 契约负责人 |
| **C-7** | `agent_checkpointer=memory` 时 HITL 审批与断点续跑事实上不可用 | 需求 §2.4 无法验收 | 引入 HITL 的阶段必须同步切 `PgCheckpointer` 并解决多副本粘性路由 | 运维 + 架构 |
| **C-8** | 死产物 `orchestration/__pycache__/react_loop.cpython-314.pyc`（源文件已删） | 误导审计与潜在导入歧义 | 清理 `__pycache__` 并确认 `.gitignore` 覆盖 | 任一实施 PR 顺带 |
| **C-9** | 文档路径规范：`AGENTS.md` §1.4 要求设计文档归档于 `docs/AI测试与评估平台-<主题>.md` | 原产出于 `specs/`，与规范冲突 | **✅ 已关闭（V1.1）**：本文与架构文档均已直接归档 `docs/` 且命名合规，`specs/` 不存在，无需迁移 | 文档负责人 |
| **C-10** | 反馈层 reflect 库随骨架化**收窄而非仅拆除**：`review.py` 仅 39 行三档简版（`pass/clarify/reject`、零调用含测试），`REFLECT_SCHEMA` / `parse_reflect` enum 同为三档，五档 `verdict`（含 `repair`/`retry`）仅残留于 `state.py` 类型注释 | 架构文档原把 H4 判为「库完整、只需重建节点壳」，实际需**恢复性扩展**判决逻辑与协议 schema/parser，H4 工作量被低估 | 审计基线修订后，H4 范围改为「扩展 `review()` 至五档 + `REFLECT_SCHEMA`/`parse_reflect` 补 enum + 重建 `reflect` 节点壳」，并同步更新架构文档 ADR-9 复用清单 | 架构 |
| **C-11** | 状态地图漂移：`AGENTS.md` §1.5（V1.2）与本文 V1.1 均称 rag「**必须失败**（LightRAG 未接入，禁止 mock）」、stress「骨架 mock」，而两执行器已于 2026-08-25（`ada0bb4` / `ee8adc1`）**真实落地**：`rag.py`（LightRAG 优先 + 本地关键词兜底，可 succeeded）与 `stress.py`（对接 `stress:19090` 引擎） | 基于过时前提的差距矩阵与 H 阶段判断失真（如「rag 任务必须失败」实为可成功）；rag 兜底报告此前 `degraded` 恒 `None`，引擎来源不可区分 | 以代码为事实源回写 `AGENTS.md` §1.5/§5.2/§6（升 V1.3）与本文；代码侧 rag 报告补 `degraded`/`engine_counts` 诚实标注（已随本 V1.2 对应修复落地） | 文档负责人 + 架构 |

---

## 5. 审计结论

1. **基础设施成熟度高**：Harness 分层基础设施（`context` / `contracts` / `execution` / `feedback` / `memory` / `orchestration` / `prompts` / `security` / `skills` 九子包 + `llm` 占位）源码合计数千行，658 例测试，工具元数据与权限纵深**超过** Claude Code 公开设计的粒度。
2. **唯一真实断点在编排层**：生产图为 1 节点 / 0 条件边 / 0 工具 / 0 interrupt，而 `GraphState` 25 字段中 22 个是为完整混合图预留的。
3. **三处真正的新建工作**：**Agent Registry**（能力标签与发现）、**上下文缓存边界**（`cache_control` 分段）、**Workflow 硬编码 DAG 子图**。
4. **两处「开开关」即得的能力**：只读工具并行（`agent_parallel_tool_batch_enabled`）、断点续跑（`agent_checkpointer=postgres`）。
5. **合法性前置**：C-2 / C-5 / C-6 三项涉及产品红线与对外契约，必须先裁决与回写文档，再落代码。
6. **反馈层 reflect 库已收窄而非完整保留（V1.1 修正，C-10）**：`review.py` 39 行三档简版、零调用（含测试），`REFLECT_SCHEMA` enum 三档，五档 verdict 仅残留于 `state.py` 类型注释——「恢复接线」清单须把反馈层列为**恢复性扩展**（判决逻辑 + 协议 schema/parser + 节点壳），H4 工作量相应上调。

详细架构设计、ADR、State 设计、Mermaid 流转图与测试策略见 [`docs/AI测试与评估平台-混合驱动引擎架构.md`](./AI测试与评估平台-混合驱动引擎架构.md)。

---

## 修改代码文件与作用清单

本文档为**只读审计**，未修改任何源码、配置、依赖或数据库迁移。

- `docs/AI测试与评估平台-混合驱动引擎环境审计.md`（新增）：V1.0 记录环境探测（运行时 / 密钥 / 依赖 / 结构）与现状审计（状态机 / State / 工具调度 / 上下文 / 记忆 / 测试），输出差距矩阵与 9 项阻塞矛盾点。

**V1.2 变更（状态地图纠偏，配合代码修复）**：按代码评审发现修正两处过时断言并新增矛盾 C-11——
1. **rag 状态修正**：原「rag 必须失败（LightRAG 未接入，禁止 mock）」不成立——`run_rag` 真实执行器（`rag.py`，2026-08-25 `ada0bb4` 落地），LightRAG 未配置/不可达/空返回时回退本地关键词检索并真实计算指标写报告置 `succeeded`；
2. **stress 状态修正**：原「骨架 mock（M4 替换）」不成立——`stress.py`（`ee8adc1`）已对接 `stress:19090` 真实引擎（Host 白名单、SLA 判定、取消停发、报告 upsert）；
3. **报告诚实性补强**：rag 报告原 `degraded` 恒 `None`，本地兜底结果与 LightRAG 结果不可区分——随代码修复（`shared/kb.py` 新增 `retrieve_with_source`，`rag.py` 报告写入 `degraded`/`degraded_note`/`engine_counts`）后如实标注；
4. **C-11 入表**：矛盾点清单扩至 11 项（C-1…C-11），裁决「以代码为事实源回写 AGENTS.md §1.5/§5.2/§6（V1.3）与本文」；
5. 头部「阻塞矛盾 9 项」语境同步更新（C-10/C-11 为 V1.1/V1.2 新增）。

**V1.1 变更（评审修订，纯文档）**：按架构评审意见修订以下六项——
1. **反馈层判定修正（新增 C-10）**：实测 `harness/feedback/review.py` 仅 39 行、`ReflectVerdict` 三档（`pass/clarify/reject`）、**零调用（含测试）**，且 `prompts/protocols.py` `REFLECT_SCHEMA`/`parse_reflect` enum 同为三档——五档 `verdict`（含 `repair`/`retry`）仅残留于 `state.py` 类型注释。原「三级验证库函数保留（仅测试）」表述不成立，反馈层是**随骨架化收窄**而非「库完整死连」，需恢复性扩展；
2. **字段计数修正**：`GraphState` 实为 **25 个字段**（原写 24），相应「骨架图仅用 3 个 / 预留 22 个」；
3. **行号快照说明**：表头标注全部行号为基线 `95a8608` 快照值（合入 main 后已漂移，如 `subagent_type` L794→L833、`build_default_registry` L403→L437），实施以符号名为准；
4. **C-9 关闭**：两文档已直接归档 `docs/` 且命名合规（`AI测试与评估平台-` 前缀），`specs/` 不存在，删除「保留 specs/ 作为交付」的过时建议；
5. **C-1 引用修正**：`AGENTS.md` 无 §5.2.3 小节，改为 §5.2 第 3 条；
6. **分层口径统一**：§5 结论不再以「六层（列 9 子包）」混称，统一为「分层基础设施（九子包 + `llm` 占位）」。

**V1.3 状态校正（2026-09-03）**：本文前述差距矩阵与结论仍严格对应审计基线 `95a8608`，不回写为当前实现，避免把历史证据伪装成现状。基于当前 `main=11f5753` 的 H4/H5 检查，补充以下实施状态：

1. H4 Reflection 五档判决、失败阶梯与回合级上限已由 PR #210 合入；H4 与 H5 的图级联调测试已具备。
2. H5 批次 1 已由 PR #211 合入，H5 批次 2 已由 PR #213 合入：API.md V1.70、图内 `interrupt()`/`Command(resume=...)`、审批卡 `meta`、严格 PG 启动门禁与 `/api/health` 实例标识均已落地。
3. 本轮收尾修复补齐审批卡真实 `owner_id`、缺失 `resume_nonce` 的 fail-closed 校验，以及多 API 副本 Compose 的 `ports: !reset []` 覆盖契约。
4. H5 仍未达到正式发布条件：生产 `AGENT_CHECKPOINTER=postgres` 切换、Linux/Docker 重启恢复演练和 `worker.sandbox` 安全评审尚未形成可验收证据；网关粘性路由已补配置，但仍需 Linux/Docker 多副本实证。

| 当前证据 | 位置 |
| :--- | :--- |
| H4/H5 定向联调与部署契约测试 | `backend/api/tests/test_hybrid_h4_reflection.py`、`test_hybrid_h5_hitl.py`、`test_hybrid_h5_batch2.py`、`test_h5_deployment_contract.py` |
| H5 Linux/Docker 收尾演练方案 | `docs/AI测试与评估平台-H5持久化HITL收尾演练.md` |
