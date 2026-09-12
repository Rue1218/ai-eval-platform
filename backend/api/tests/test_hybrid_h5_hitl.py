"""H5 HITL/持久化测试（开发计划 H5 验收，批次 1）。

覆盖：图级 interrupt（危险 bash）→ 检查点暂停 → ahas_pending_interrupt →
resume 恢复（approve 继续执行 / reject 拒绝）且事件不重放；审批卡协议
（行锁落卡 meta/一次性 nonce/已有卡 CONCURRENCY 不覆盖）；审批回执行锁
校验链（owner/卡种/id/action）与 resume 至多一次。不依赖 PG（检查点用
进程内 InMemoryCheckpointer，语义与 PgCheckpointer 一致——真实 PG 演练见
开发计划 §4 Linux/Docker 环境）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent import LangGraphAgent
from app.errors import AppError, ErrorCode
from app.harness.memory import SerializableRequest
from app.harness.orchestration.agents import AgentDef, AgentRegistry
from app.llm import ModelResponse
from app.routers import ws

# 图级 interrupt 用自定义注册表：general Worker 视野含 bash（危险命令需
# interrupt 审批）。生产 discover 仍排除 sandbox（H5 安全评审另行放开）。
_BASH_REGISTRY = AgentRegistry()
_BASH_REGISTRY.register(
    AgentDef(
        agent_id="worker.general",
        display_name="通用助手（测试含 bash）",
        capabilities=frozenset({"general"}),
        allowed_tools=("read", "bash", "web_search", "ask_user_question"),
        max_permission="code",
        description="测试用",
    )
)


def _request(text: str) -> SerializableRequest:
    return SerializableRequest(
        config={
            "protocol": "openai_chat",
            "base_url": "https://model.example.com",
            "model": "test-model",
        },
        messages=({"role": "user", "content": text},),
    )


_PLAN_OK = (
    '{"intent":"排查测试环境异常","skill_id":null,'
    '"slots":{"steps":["检查环境","清理脏数据","给出结论"]},'
    '"tools_needed":["bash"],"delivery":"chat",'
    '"budget":{"model_calls":8,"tool_turns":6},"allows_replan":false,'
    '"notes":"测试","protocol":"plan","version":"plan.v1"}'
)
_REACT_BASH = (
    '{"thought":"整理工作区","tool":"bash","arguments":{"command":"touch /tmp/x.txt"},'
    '"done":false,"protocol":"react","version":"react.v1"}'
)
_REACT_DONE = (
    '{"thought":"完成","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n已按计划完成。'
)


class _ScriptedGateway:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        index = self.calls
        self.calls += 1
        if index >= len(self._texts):
            raise AssertionError(f"模型调用超出脚本：{self.calls}")
        return ModelResponse(text=self._texts[index], usage={}, latency_ms=0)


def _collect_until_interrupt(agent: LangGraphAgent, text: str, config: dict):
    """跑图直到 interrupt；返回 (interrupt_value, thread_id, 事件轨迹)。"""

    async def run():
        events: list[tuple[str, dict]] = []
        interrupt_value = None
        async for mode, chunk in agent.astream(_request(text), config=config):
            events.append((mode, chunk))
            if mode == "updates" and "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                first = interrupts[0]
                interrupt_value = getattr(first, "value", first)
        return interrupt_value, events

    return asyncio.run(run())


def _resume(agent: LangGraphAgent, config: dict, resume_value: dict):
    from langgraph.types import Command

    async def run():
        out: list[tuple[str, dict]] = []
        async for mode, chunk in agent.astream(
            _request("继续"), config=config, resume=Command(resume=resume_value)
        ):
            out.append((mode, chunk))
        return out

    return asyncio.run(run())


def _all_pending(events: list[tuple[str, dict]]) -> list[dict]:
    return [
        event
        for _mode, chunk in events
        if isinstance(chunk, dict)
        for value in chunk.values()
        if isinstance(value, dict)
        for event in value.get("pending_events", [])
    ]


def _engine_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "credentials": {"api_key": ""}}}


# ─── 1. 图级：bash 直通（F2/G4 静态裁决删除）───
#
# F2/G4 起 bash 不再因命令文本产生 tool_approval 卡（词表与静态裁决删除，
# 《工作区与沙箱设计方案》§6.3）；图级 tool_approval interrupt/resume 的
# 端到端语义改由 F5「拒写升档卡」接入时恢复覆盖（彼稿 §6.4、测试矩阵 F5
# 集成列）。本组锁定直通回归：bash 进入执行、无中断、回合正常收尾、事件
# 不重放；卡协议/落卡/ack 链路由本文件第 2–4 节继续保护。


def _saver():
    """进程内检查点（BaseCheckpointSaver 契约，CI 严格类型校验兼容）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def test_graph_bash_passthrough_no_interrupt(engine_on) -> None:
    """F2/G4：bash（原危险/变更命令）直通执行——无任何 tool_approval 中断。"""
    thread_id = "h5-thread-1"
    # H4 失败阶梯：bash 工具失败（本机无沙箱）→ 允许一次 repair → 两次收尾响应
    gateway = _ScriptedGateway([_PLAN_OK, _REACT_BASH, _REACT_DONE, _REACT_DONE])
    agent = LangGraphAgent(
        gateway, agent_registry=_BASH_REGISTRY, checkpointer=_saver()
    )
    config = _engine_config(thread_id)
    interrupt_value, events = _collect_until_interrupt(agent, "排查一下测试环境异常", config)

    assert interrupt_value is None, f"bash 直通后不应产生中断：{interrupt_value}"
    # 事件不重放：bash 工具调用恰好一条（无中断、无 resume 路径）
    all_events = _all_pending(events)
    assert len([e for e in all_events if e["kind"] == "tool_call"]) == 1
    tool_results = [e for e in all_events if e["kind"] == "tool_result"]
    # 本机测试环境无沙箱 runner → 工具失败观察（fail-closed），回合仍正常收尾
    assert tool_results and tool_results[0]["payload"]["ok"] is False
    completed = [e for e in all_events if e["kind"] == "response.completed"]
    assert completed
    assert asyncio.run(agent.ahas_pending_interrupt(thread_id)) is False


# 注：图级 tool_approval/升档卡 interrupt→resume 端到端用例在 F5 接入升档
# 审批时恢复（彼稿 §6.4 升档触发 = ToolNode 内 interrupt 路径，测试矩阵 F5
# 集成列）；本文件第 2–4 节继续保护卡落库/ack/一次性 resume 协议。


# ─── 2. 审批卡协议：落卡行锁 / meta / 一次性 nonce ───


class _Row:
    def __init__(self, session_id: str = "s-1") -> None:
        self.id = session_id
        self.user_id = "u-1"
        self.pending_confirm = None
        self.pending_confirm_author_id = None
        self.compact_summary = None


class _FakeDb:
    def __init__(self, row: _Row | None = None) -> None:
        self.row = row or _Row()
        self.committed = 0
        self.rolled_back = 0

    def query(self, _model):
        return self

    def filter(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.row

    def execute(self, statement, params=None):
        sql = str(getattr(statement, "text", statement))
        if sql.startswith("UPDATE sessions SET pending_confirm = NULL"):
            self.row.pending_confirm = None
            self.row.pending_confirm_author_id = None
        return self

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        pass


def test_persist_approval_writes_card_with_meta() -> None:
    db = _FakeDb()
    card = ws._persist_pending_approval(
        db,
        "s-1",
        {
            "type": "tool_approval",
            "id": "call-1",
            "call_id": "call-1",
            "name": "bash",
            "command": "rm -rf /tmp/x",
            "reason": "危险命令",
            "risk_level": "high",
        },
        thread_id="t-1",
        user_id="u-1",
    )
    assert db.row.pending_confirm is not None
    meta = db.row.pending_confirm["meta"]
    # #1（V1.72）：三类卡共用 meta，schema_version 升版为 2（消费端不读数字分支）
    assert meta["schema_version"] == 2
    assert meta["confirm_type"] == "tool_approval"
    assert meta["thread_id"] == "t-1"
    assert meta["owner_id"] == "u-1"
    assert meta["resume_nonce"]
    assert db.row.pending_confirm_author_id == "u-1"
    assert card["id"] == "call-1"
    assert "type" not in card  # 白名单过滤，不留图内字段


def test_persist_approval_rejects_existing_card() -> None:
    db = _FakeDb(_Row())
    db.row.pending_confirm = {"kind": "benchmark"}
    with pytest.raises(AppError) as exc:
        ws._persist_pending_approval(
            db, "s-1", {"id": "call-1", "name": "bash"}, thread_id="t-1", user_id="u-1"
        )
    assert exc.value.code == ErrorCode.CONCURRENCY
    assert db.row.pending_confirm["kind"] == "benchmark"  # 不覆盖


def test_confirm_card_now_carries_h5_meta() -> None:
    """确认卡（H2）升级后带 meta 恢复协议字段（不破坏 spec 平铺语义）。"""
    db = _FakeDb()
    ws._persist_pending_confirm(
        db,
        "s-1",
        {"kind": "benchmark", "profile_ids": [], "confirm_author": {"id": "u-1"}},
        thread_id="t-1",
        user_id="u-1",
    )
    card = db.row.pending_confirm
    assert card["kind"] == "benchmark"
    meta = card["meta"]
    assert meta["confirm_type"] == "task_confirm"
    assert meta["thread_id"] == "t-1"
    assert meta["owner_id"] == "u-1"
    assert db.row.pending_confirm_author_id == "u-1"


def test_confirm_card_duplicate_issue_rejected() -> None:
    """会话已有卡时重复发确认卡 → CONCURRENCY（不覆盖，团队协作不抢占）。"""
    db = _FakeDb(_Row())
    db.row.pending_confirm = {"kind": "testcase"}
    with pytest.raises(AppError) as exc:
        ws._persist_pending_confirm(
            db, "s-1", {"kind": "benchmark"}, thread_id="t-2", user_id="u-1"
        )
    assert exc.value.code == ErrorCode.CONCURRENCY
    assert db.row.pending_confirm["kind"] == "testcase"


# ─── 3. 审批回执行锁校验链 ───


def _approval_card(thread_id: str = "t-1") -> dict:
    return {
        "id": "call-1",
        "call_id": "call-1",
        "name": "bash",
        "command": "rm -rf /tmp/x",
        "meta": {
            # 刻意保留 V1.70 旧版 schema_version=1：验证升版后旧卡仍可被
            # ack 消费（零影响回归：消费端不读 schema 数字分支）
            "schema_version": 1,
            "confirm_type": "tool_approval",
            "thread_id": thread_id,
            "owner_id": "u-1",
            "resume_nonce": "nonce-1",
        },
    }


def test_approval_ack_clears_card_and_resumes_once(monkeypatch) -> None:
    started: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        ws,
        "_start_approval_resume",
        lambda _sid, _ws, _st, _uid, thread_id, action, approval_id: started.append(
            (thread_id, action, approval_id)
        )
        or object(),
    )
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    async def probe_ok(_thread_id: str) -> bool:
        return True  # F5/G6：恢复预检通过（直调层无真实检查点）

    monkeypatch.setattr(ws, "_approval_resume_probe", probe_ok)
    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    db = _FakeDb(_Row())
    db.row.pending_confirm = _approval_card()
    db.row.pending_confirm_author_id = "u-1"
    asyncio.run(
        ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
    )
    assert db.row.pending_confirm is None  # 清卡（一次性）
    assert started == [("t-1", "approve", "call-1")]  # 原 thread_id 恢复
    assert emitted and emitted[-1][0] == "tool_approval_ack"
    assert db.committed >= 1


def test_approval_ack_reject_no_resume(monkeypatch) -> None:
    started: list = []
    monkeypatch.setattr(
        ws, "_start_approval_resume", lambda *_a, **_k: started.append(1) or object()
    )

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        return True

    async def probe_ok(_thread_id: str) -> bool:
        return True  # F5/G6：恢复预检通过（reject 路径同受预检约束）

    monkeypatch.setattr(ws, "_approval_resume_probe", probe_ok)
    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    db = _FakeDb(_Row())
    db.row.pending_confirm = _approval_card()
    db.row.pending_confirm_author_id = "u-1"
    asyncio.run(
        ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "reject", "id": "call-1"})
    )
    assert db.row.pending_confirm is None
    assert started == [1]  # reject 也 resume（toolnode 收到 reject 不执行命令）


def test_approval_ack_repeated_after_clear_rejected(monkeypatch) -> None:
    """卡已消费（重复 ack）→ 拒绝（无待确认卡），resume 至多一次。"""
    monkeypatch.setattr(ws, "_start_approval_resume", lambda *_a, **_k: None)
    db = _FakeDb(_Row())  # 无卡
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
        )
    assert exc.value.code == ErrorCode.VALIDATION


def test_approval_ack_missing_resume_nonce_rejected() -> None:
    """审批卡缺少一次性恢复令牌时拒绝消费，避免恢复协议降级。"""
    db = _FakeDb(_Row())
    card = _approval_card()
    del card["meta"]["resume_nonce"]
    db.row.pending_confirm = card
    db.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(
                db,
                object(),
                ws._ConnectionState(),
                "s-1",
                "u-1",
                {"action": "approve", "id": "call-1"},
            )
        )
    assert exc.value.code == ErrorCode.VALIDATION
    assert db.row.pending_confirm is card


def test_approval_ack_wrong_owner_or_kind_rejected() -> None:
    db = _FakeDb(_Row())
    db.row.pending_confirm = _approval_card()
    db.row.pending_confirm_author_id = "u-2"  # 非 owner
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(db, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
        )
    assert exc.value.code == ErrorCode.UNAUTHORIZED
    db2 = _FakeDb(_Row())
    db2.row.pending_confirm = {"kind": "benchmark", "meta": {"confirm_type": "task_confirm", "thread_id": "t-1"}}
    db2.row.pending_confirm_author_id = "u-1"
    with pytest.raises(AppError) as exc:
        asyncio.run(
            ws._handle_approval_ack(db2, object(), ws._ConnectionState(), "s-1", "u-1", {"action": "approve", "id": "call-1"})
        )
    assert exc.value.code == ErrorCode.VALIDATION  # 任务确认卡不走审批 ack


# ─── 4. interrupt 帧 → 落卡广播（ws 层）───


def test_graph_interrupt_frame_persists_and_broadcasts(engine_on, monkeypatch) -> None:
    """__interrupt__ 帧（tool_approval）→ 行锁落卡 + tool_approval 事件广播。"""
    db = _FakeDb(_Row())
    emitted: list[tuple[str, dict]] = []

    async def fake_emit(_db, _ws, _st, _sid, event, payload, **kw):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    interrupt_payload = {
        "type": "tool_approval",
        "id": "call-9",
        "call_id": "call-9",
        "name": "bash",
        "command": "rm -rf /x",
        "reason": "危险命令",
        "risk_level": "high",
        "sandbox_scope": "…",
    }
    paused = asyncio.run(
        ws._handle_graph_interrupt(
            db, object(), ws._ConnectionState(), "s-1", (type("I", (), {"value": interrupt_payload})(),),
            thread_id="t-9",
            user_id="u-1",
        )
    )
    assert paused is True
    assert db.row.pending_confirm["meta"]["confirm_type"] == "tool_approval"
    assert db.row.pending_confirm["meta"]["thread_id"] == "t-9"
    assert emitted and emitted[-1][0] == "tool_approval"
    assert emitted[-1][1]["id"] == "call-9"
    assert "meta" not in emitted[-1][1]  # 广播不带内部 meta
