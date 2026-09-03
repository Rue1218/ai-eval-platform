"""H0–H3 阶段联调（进程级：真实 ws._run_turn + 真实 LangGraph 图 + 桩 DB/模型）。

覆盖跨阶段连续旅程（开发计划 §5 联调/预发清单的自动化形态，Windows 本机
无 Docker/PG 时替代浏览器 smoke 的执行面）：

- H0：开关关闭纯对话回合完整事件流（assistant_message + completed，无 engine）；
- H1：direct（斜杠防御）/ workflow / agent 分流与 engine 审计（completed 三件套）；
- H2：workflow 回合 W0–W5 发卡（confirm 事件 + 图内 completed），确认回执重放
  回合（workflow_confirm 注入）W5 放行 → **W6 唯一入队** → W7 收尾；
- H3：agent TAOR 回合（plan → discover → orchestrator done）与越权工具
  fail-closed（非法工具 VALIDATION，无工具事件）；
- 跨引擎多轮连续性（同一会话 chat → workflow → agent）。

桩面仅限：DB（SessionLocal 返回内存桩：记录 Task/Message 落库与 commit）、
模型网关（invoke/stream 双 API 脚本）、协议档快照（_selected_model_config）、
事件落库（_emit_persistent 收集）。图、收包翻译、节点、十层链全部真实。
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent import LangGraphAgent
from app.config import settings
from app.llm import ModelConfig, ModelResponse, ModelStreamEvent
from app.models import Task
from app.routers import ws

# ─── 桩 ───


class _SessionRow:
    """AgentSession 行桩：pending_confirm 可读写（确认卡行锁写回）。"""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.user_id = "u-e2e"
        self.owner_id = None
        self.pending_confirm = None
        self.pending_confirm_author_id = None
        self.compact_summary = None


class _FakeDb:
    """SessionLocal 内存桩：记录 ORM 落库（Task/Message）与事务动作。

    查询链按目标模型分派：AgentSession → 可写行桩（行锁/确认卡）；
    其余查询返回空。
    """

    def __init__(self) -> None:
        self.added: list[object] = []
        self.tasks: list[Task] = []
        self.committed = 0
        self.rolled_back = 0
        self._msg_seq = 0
        self._model = None

    def add(self, row: object) -> None:
        self.added.append(row)
        if isinstance(row, Task):
            self.tasks.append(row)

    def flush(self) -> None:
        for row in self.added:
            if getattr(row, "__tablename__", None) == "messages" and not getattr(row, "id", None):
                self._msg_seq += 1
                row.id = f"m-e2e-{self._msg_seq}"  # type: ignore[attr-defined]

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        pass

    def query(self, model, *_args):
        self._model = model
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        model = self._model
        if model is not None and getattr(model, "__name__", "") == "Session":
            return _SessionRow("s-e2e")
        return None

    def all(self):
        return []


class _E2eGateway:
    """模型网关桩：invoke 按脚本出文本（plan/react/router L1），stream 出 chat 正文。"""

    def __init__(self, invoke_texts: list[str] | None = None, chat_text: str = "你好，我是联调助手。") -> None:
        self._texts = list(invoke_texts or [])
        self._chat_text = chat_text
        self.invoke_calls = 0
        self.stream_calls = 0

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        self.invoke_calls += 1
        index = self.invoke_calls - 1
        if index < len(self._texts):
            return ModelResponse(text=self._texts[index], usage={}, latency_ms=0)
        return ModelResponse(text=self._chat_text, usage={}, latency_ms=0)

    def stream(self, request: object, config: dict | None = None):
        self.stream_calls += 1
        yield ModelStreamEvent(kind="content", text=self._chat_text)
        yield ModelStreamEvent(
            kind="completed",
            response=ModelResponse(text=self._chat_text, usage={}, latency_ms=0),
        )


def _model_config() -> ModelConfig:
    return ModelConfig(
        protocol="openai_chat",
        base_url="https://model.example.com",
        model="e2e-model",
        api_key="",
    )


_emitted: list[tuple[str, dict, str | None]] = []


async def _collect_emit(_db, _websocket, _state, _session_id, event, payload, **kwargs):
    _emitted.append((event, payload, kwargs.get("task_id")))
    return True


async def _drive(
    monkeypatch,
    gateway: _E2eGateway,
    text: str,
    *,
    hybrid: bool = True,
    workflow_confirm: dict | None = None,
) -> tuple[list[tuple[str, dict, str | None]], _FakeDb, dict]:
    """驱动一轮真实 _run_turn；返回 (emitted, db, turn_sink)。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", hybrid)
    db = _FakeDb()
    monkeypatch.setattr(ws, "SessionLocal", lambda: db)
    monkeypatch.setattr(ws, "_AGENT", LangGraphAgent(gateway))
    profile = ws._ProfileSnapshot(
        id="p-e2e",
        name="联调档",
        model="e2e-model",
        base_url="https://model.example.com",
        protocol="openai_chat",
    )
    monkeypatch.setattr(
        ws, "_selected_model_config", lambda _db: (_model_config(), profile)
    )
    monkeypatch.setattr(
        ws,
        "_history_messages",
        lambda _db, _session_id: [{"role": "user", "content": text}],
    )
    monkeypatch.setattr(ws, "_emit_persistent", _collect_emit)
    monkeypatch.setattr(ws, "_claim_terminal", lambda _sid, _turn_id: True)
    _emitted.clear()
    sink: dict = {}
    await ws._run_turn(
        "s-e2e",
        object(),
        ws._ConnectionState(),
        asyncio.Event(),
        user_id="u-e2e",
        turn_id=None,
        workflow_confirm=workflow_confirm,
        turn_sink=sink,
    )
    return list(_emitted), db, sink


def _completed(emitted) -> dict:
    payloads = [payload for event, payload, _ in emitted if event == "response.completed"]
    assert payloads, "回合未产出 response.completed"
    return payloads[-1]


def _assistant_texts(emitted) -> list[str]:
    return [
        str(payload.get("text") or "")
        for event, payload, _ in emitted
        if event == "assistant_message"
    ]


_PLAN_OK = (
    '{"intent":"排查并定位测试报告失败原因","skill_id":null,'
    '"slots":{"steps":["读取报告","定位失败用例","给出结论"]},'
    '"tools_needed":["read"],"delivery":"chat",'
    '"budget":{"model_calls":6,"tool_turns":4},"allows_replan":false,'
    '"notes":"联调用计划","protocol":"plan","version":"plan.v1"}'
)
_REACT_DONE = (
    '{"thought":"已定位原因","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n结论：样本量不足，建议补数。'
)
# H4：orchestrator 收尾后由 reflect 判决，无失败路径需多一次受控复核短调用
_REFLECT_PASS = (
    '{"verdict":"pass","reason":"可直接给出","protocol":"reflect","version":"reflect.v1"}'
)


# ─── H0：开关关闭纯对话全链路 ───


@pytest.mark.asyncio
async def test_h0_chat_full_ws_pipeline_without_engine(monkeypatch) -> None:
    """开关关闭：真实图 chat_stream_node → 真实翻译落库 → 事件流（无 engine）。"""
    gateway = _E2eGateway(chat_text="纯对话回答")
    emitted, db, _sink = await _drive(monkeypatch, gateway, "什么是 pass@1？", hybrid=False)
    texts = _assistant_texts(emitted)
    assert any("纯对话回答" in text for text in texts)
    completed = _completed(emitted)
    assert completed["finish_reason"] == "stop"
    assert "engine" not in completed  # 主开关关闭不出现引擎审计
    assert db.committed >= 1  # 助手消息与事件落库真实执行


# ─── H1：direct 分流与引擎审计 ───


@pytest.mark.asyncio
async def test_h1_direct_slash_engine_audit(monkeypatch) -> None:
    """斜杠（/help）→ direct 零模型防御收尾，completed 携带 engine=direct。"""
    gateway = _E2eGateway()
    emitted, _db, _sink = await _drive(monkeypatch, gateway, "/help", hybrid=True)
    completed = _completed(emitted)
    assert completed["engine"] == "direct"
    assert gateway.invoke_calls == 0 and gateway.stream_calls == 0  # 零模型调用
    texts = _assistant_texts(emitted)
    assert any("不支持该命令" in text for text in texts)


# ─── H2：workflow 发卡回合 ───


@pytest.mark.asyncio
async def test_h2_workflow_issues_confirm_card(monkeypatch) -> None:
    """评测请求 → W0–W5 发卡：confirm 事件（spec 与 defaults 一致）+ 叙述 + completed。"""
    gateway = _E2eGateway()  # 全程零模型调用（L0 高置信 + DAG 确定性）
    emitted, db, sink = await _drive(
        monkeypatch, gateway, "对数据集 D 用 profile-A 跑一次基准评测", hybrid=True
    )
    events = [event for event, _payload, _ in emitted]
    assert "confirm" in events
    confirm_payload = next(payload for event, payload, _ in emitted if event == "confirm")
    # V1.68：confirm 事件 payload 即 TaskSpec 平铺（defaults.py 单一事实源）
    spec = confirm_payload
    assert spec["kind"] == "benchmark"
    assert spec["profile_ids"] == []  # 平台默认值（defaults.py 同源）
    assert spec["with_stress"] is False
    assert spec["dataset_id"] is None
    assert spec["run"]["sample_size"] == 1000
    assert spec["run"]["concurrency"] == 4
    completed = _completed(emitted)
    assert completed["engine"] == "workflow"
    assert "router_confidence" in completed and "router_reason" in completed
    assert not db.tasks  # 未确认绝不入队
    assert sink.get("enqueued_task_id") is None
    assert gateway.invoke_calls == 0 and gateway.stream_calls == 0  # 确定性链路零模型


@pytest.mark.asyncio
async def test_h2_confirm_replay_enqueues_once_via_w6(monkeypatch) -> None:
    """确认回执重放：W5 合并 → W6 唯一入队 → W7 收尾（真实 worker_bridge 写桩库）。"""
    gateway = _E2eGateway()
    confirm = {
        "task_spec": {
            "profile_ids": ["p-e2e-1"],
            "dataset_id": "d-e2e-1",
        }
    }
    emitted, db, sink = await _drive(
        monkeypatch,
        gateway,
        "对数据集 D 用 profile-A 跑一次基准评测",
        hybrid=True,
        workflow_confirm=confirm,
    )
    assert sink.get("enqueued_task_id"), "回执重放后 W6 应产出任务 ID"
    assert len(db.tasks) == 1  # 恰入队一次（W6 唯一出口）
    task = db.tasks[0]
    assert task.kind == "benchmark"
    assert task.session_id == "s-e2e"
    assert task.created_by == "u-e2e"
    assert task.status == "queued"
    assert task.config["profile_ids"] == ["p-e2e-1"]
    completed = _completed(emitted)
    assert completed["engine"] == "workflow"
    texts = _assistant_texts(emitted)
    assert any("任务 ID" in text for text in texts)  # W7 收尾叙述
    assert db.committed >= 1


@pytest.mark.asyncio
async def test_h2_confirm_replay_missing_assets_not_enqueued(monkeypatch) -> None:
    """回执缺必填（profile_ids 空）→ VALIDATION 收尾，不入队、不留任务行。"""
    gateway = _E2eGateway()
    confirm = {"task_spec": {"profile_ids": []}}
    emitted, db, sink = await _drive(
        monkeypatch,
        gateway,
        "对数据集 D 跑一次基准评测",
        hybrid=True,
        workflow_confirm=confirm,
    )
    assert not db.tasks
    assert sink.get("enqueued_task_id") is None
    error = next((payload for event, payload, _ in emitted if event == "error"), None)
    assert error is not None
    assert "缺少必填" in str(error.get("message") or "")


# ─── H3：agent TAOR 回合 ───


@pytest.mark.asyncio
async def test_h3_agent_taor_plan_discover_done(monkeypatch) -> None:
    """探索请求 → plan(脚本) → discover(worker.diagnose) → orchestrator done → reflect 放行。

    H4：orchestrator 不再自行收尾，候选答复交 reflect 判决后发出（多一次复核短调用）。
    """
    gateway = _E2eGateway(invoke_texts=[_PLAN_OK, _REACT_DONE, _REFLECT_PASS])
    emitted, _db, _sink = await _drive(monkeypatch, gateway, "排查一下测试报告失败原因", hybrid=True)
    completed = _completed(emitted)
    assert completed["engine"] == "agent"
    assert completed["agent_id"] == "worker.diagnose"
    assert completed["finish_reason"] == "stop"
    texts = _assistant_texts(emitted)
    assert any("样本量不足" in text for text in texts)
    assert gateway.invoke_calls == 3  # plan 1 次 + orchestrator done 1 次 + reflect 1 次


@pytest.mark.asyncio
async def test_h3_agent_read_observation_failure_then_done(monkeypatch) -> None:
    """真实工具执行链：read（无沙箱上下文）失败 → H4 失败阶梯 repair → 收敛收尾。

    工具级失败经十层链异常隔离为 INTERNAL error 事件，但回合不崩溃（隔离语义：
    错误不打断图流）。H4 后失败不再直接放行：先 ``repair`` 注入修复观察回
    Executor 再试一次；本计划 ``allows_replan=false``，修复配额用尽即 ``reject``
    收尾——**不得**以 ``pass`` 静默放行失败。
    """
    react_read = (
        '{"thought":"读取报告","tool":"read","arguments":{"path":"result.md"},'
        '"done":false,"protocol":"react","version":"react.v1"}'
    )
    gateway = _E2eGateway(invoke_texts=[_PLAN_OK, react_read, _REACT_DONE, _REACT_DONE])
    emitted, _db, _sink = await _drive(monkeypatch, gateway, "排查一下测试报告失败原因", hybrid=True)
    events = [event for event, _payload, _ in emitted]
    assert "tool_call" in events and "tool_result" in events
    tool_result = next(payload for event, payload, _ in emitted if event == "tool_result")
    assert tool_result["name"] == "read"
    assert tool_result["ok"] is False  # ws 回合未注入沙箱 → 十层链拒绝并脱敏
    assert "redacted" in tool_result and "error" in tool_result
    completed = _completed(emitted)
    assert completed["engine"] == "agent"
    # 失败阶梯：plan + read Act + done + repair 后 done，共 4 次调用后收敛
    assert gateway.invoke_calls == 4
    # 修复一次仍失败且计划不允许重规划 → 以可读原因 reject 收尾，不误判为 pass
    assert completed["finish_reason"] == "error"


@pytest.mark.asyncio
async def test_h3_agent_out_of_view_tool_fail_closed(monkeypatch) -> None:
    """模型请求越权 bash（discover 永不选 sandbox）→ VALIDATION 就地收尾。"""
    react_bash = (
        '{"thought":"执行脚本","tool":"bash","arguments":{"command":"rm -rf /"},'
        '"done":false,"protocol":"react","version":"react.v1"}'
    )
    gateway = _E2eGateway(invoke_texts=[_PLAN_OK, react_bash])
    emitted, _db, _sink = await _drive(monkeypatch, gateway, "排查一下测试报告失败原因", hybrid=True)
    error = next((payload for event, payload, _ in emitted if event == "error"), None)
    assert error is not None
    assert "非法工具" in str(error.get("message") or "")
    assert not any(event == "tool_result" for event, _payload, _ in emitted)  # 无工具执行


# ─── 跨引擎多轮连续性 ───


@pytest.mark.asyncio
async def test_multi_turn_engine_switching_on_one_session(monkeypatch) -> None:
    """同一会话连续三轮：chat → workflow(发卡) → agent，各轮 completed 审计正确。"""
    engines: list[str] = []
    # 轮 1 chat：概念问答
    g1 = _E2eGateway(chat_text="pass@1 是模型单次正确率。")
    _emitted, _db, _sink = await _drive(monkeypatch, g1, "什么是 pass@1？", hybrid=True)
    assert _completed(_emitted)["engine"] == "chat"
    # 轮 2 workflow：评测发卡（确认卡事件 + engine=workflow）
    g2 = _E2eGateway()
    emitted2, db2, _sink2 = await _drive(monkeypatch, g2, "跑一次基准评测", hybrid=True)
    assert _completed(emitted2)["engine"] == "workflow"
    assert any(event == "confirm" for event, _payload, _ in emitted2)
    assert not db2.tasks
    # 轮 3 agent：探索（TAOR done）
    g3 = _E2eGateway(invoke_texts=[_PLAN_OK, _REACT_DONE])
    emitted3, _db3, _sink3 = await _drive(monkeypatch, g3, "排查一下测试报告失败原因", hybrid=True)
    assert _completed(emitted3)["engine"] == "agent"
    assert _completed(emitted3)["agent_id"] == "worker.diagnose"
    engines = ["chat", "workflow", "agent"]
    assert engines == ["chat", "workflow", "agent"]
    assert len(engines) == 3
