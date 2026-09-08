"""F5/G6 拒写升档审批测试（《工作区与沙箱设计方案》§6.4）。

覆盖：kernel read-only 拒写识别（EROFS 证据归因）、DENIED 错误码归一、
图级升档闭环——read-only 拒写（DENIED）→ denied 帧 + tool_approval 升档卡
（reason=escalation）→ approve resume → 同命令以 workspace-write 重放恰好
一次；reject → 不重放走失败阶梯；开关默认关 → 无卡（DENIED 仅失败观察）。
bash 可达经自定义注册表（含 bash 视野），不依赖 discover/runner。
"""

from __future__ import annotations

import asyncio

import pytest
from shared.sandbox_kernel import _looks_readonly_denied

from app.agent import LangGraphAgent
from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolResult
from app.harness.execution.native import NativeToolExecutor
from app.harness.execution.sandbox import _ERROR_MAP
from app.harness.memory import SerializableRequest
from app.harness.orchestration.agents import AgentDef, AgentRegistry
from app.llm import ModelResponse

_BASH_REGISTRY = AgentRegistry()
_BASH_REGISTRY.register(
    AgentDef(
        agent_id="worker.general",
        display_name="通用助手（测试含 bash）",
        capabilities=frozenset({"general"}),
        allowed_tools=("read", "bash"),
        max_permission="code",
        description="测试用",
    )
)

_PLAN_OK = (
    '{"intent":"整理会话工作区","skill_id":null,'
    '"slots":{"steps":["创建标记文件","核对","给出结论"]},'
    '"tools_needed":["bash"],"delivery":"chat",'
    '"budget":{"model_calls":8,"tool_turns":6},"allows_replan":false,'
    '"notes":"测试","protocol":"plan","version":"plan.v1"}'
)
_REACT_BASH_WRITE = (
    '{"thought":"写工作区","tool":"bash",'
    '"arguments":{"command":"touch /work/marker.txt && echo done"},'
    '"done":false,"protocol":"react","version":"react.v1"}'
)
_REACT_DONE = (
    '{"thought":"完成","tool":null,"arguments":{},"done":true,'
    '"protocol":"react","version":"react.v1"}\n\n已按计划完成。'
)
_REFLECT_PASS = (
    '{"verdict":"pass","reason":"可直接给出",'
    '"clarify_question":null,"repair_hint":null,'
    '"protocol":"reflect","version":"reflect.v1"}'
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


class _ScriptedGateway:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    def invoke(self, request: object, config: dict | None = None) -> ModelResponse:
        index = self.calls
        self.calls += 1
        if index >= len(self._texts):
            raise AssertionError(f"模型调用超出脚本：{self.calls}")
        system = str(getattr(request, "system", ""))[:14].replace("\n", " ")
        print(f"INVOKE#{index} sys={system!r}")  # noqa: T201
        return ModelResponse(text=self._texts[index], usage={}, latency_ms=0)


def _engine_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "credentials": {"api_key": ""}}}


def _saver():
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def _collect_until_interrupt(agent: LangGraphAgent, text: str, config: dict):
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


@pytest.fixture()
def _esc_on(monkeypatch):
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "agent_escalation_approval_enabled", True)
    yield


# ─── 1. kernel read-only 拒写识别 ───


def test_looks_readonly_denied_matches_erofs_evidence() -> None:
    assert _looks_readonly_denied("touch: cannot touch '/work/a.txt': Read-only file system")
    assert _looks_readonly_denied("bash: echo: cannot create /work/x: erofs")
    assert _looks_readonly_denied("  READ-ONLY FILE SYSTEM  ")


def test_looks_readonly_denied_negative_cases() -> None:
    assert not _looks_readonly_denied("touch: cannot touch '/work/a.txt': Permission denied")
    assert not _looks_readonly_denied("No space left on device")
    assert not _looks_readonly_denied("")
    assert not _looks_readonly_denied("command not found")


def test_denied_error_code_maps_in_client() -> None:
    assert _ERROR_MAP["DENIED"] is ErrorCode.DENIED


# ─── 2. 图级升档闭环（approve → workspace-write 重放恰好一次）───


def test_denied_triggers_escalation_card_and_approve_replays(_esc_on, monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_call(self, definition, arguments, context):
        # 真实 runner 语义：非 workspace-write 档写 /work 恒拒写（EROFS）；
        # 升档重放（workspace-write）才成功。
        calls.append({"mode": context.sandbox_mode, "command": arguments.get("command")})
        if context.sandbox_mode != "workspace-write":
            raise AppError(ErrorCode.DENIED, "沙箱卷只读拒绝写入（read-only 档位）")
        return ToolResult(
            name=definition.name,
            ok=True,
            data={
                "summary": "touch done",
                "model_text": "已创建 /work/marker.txt",
                "display": {"status": "success"},
            },
            call_id=context.call_id,
        )

    monkeypatch.setattr(NativeToolExecutor, "call", fake_call)
    gateway = _ScriptedGateway([_PLAN_OK, _REACT_BASH_WRITE, _REACT_DONE, _REFLECT_PASS])
    agent = LangGraphAgent(gateway, agent_registry=_BASH_REGISTRY, checkpointer=_saver())
    config = _engine_config("esc-approve")
    interrupt_value, events = _collect_until_interrupt(
        agent, "帮我运行脚本创建标记文件", config
    )

    assert interrupt_value is not None, "read-only 拒写应触发升档卡"
    assert interrupt_value.get("type") == "tool_approval"
    assert interrupt_value.get("reason") == "escalation"
    assert interrupt_value.get("name") == "bash"
    assert "marker.txt" in interrupt_value.get("command", "")
    assert interrupt_value.get("allowed_decisions") == ["approve", "reject"]
    approval_id = interrupt_value.get("id")
    assert approval_id

    resumed = _resume(agent, config, {"action": "approve", "id": approval_id})
    pending = _all_pending(resumed)
    # approve：中断前只读档 DENIED（1 次）+ resume 后 node 重放仍只读 DENIED
    #（1 次）→ interrupt 返回 approve → 以 workspace-write 重放恰好一次并成功
    escalated_calls = [item for item in calls if item["mode"] == "workspace-write"]
    denied_calls = [item for item in calls if item["mode"] != "workspace-write"]
    assert len(escalated_calls) == 1
    assert len(denied_calls) == 2
    result_frames = [e for e in pending if e["kind"] == "tool_result"]
    # 拒写事实帧（denied，MAJ-9② 首帧）+ 重放成功帧，按事件序收敛最后一条
    denied_frames = [e for e in result_frames if e["payload"].get("escalation") is True]
    assert len(denied_frames) == 1
    assert any(e["payload"].get("ok") is True for e in result_frames)
    assert result_frames[-1]["payload"].get("ok") is True  # 末帧收敛于成功
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "stop"


def test_denied_escalation_reject_no_replay(_esc_on, monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_call(self, definition, arguments, context):
        # 恒拒写：reject 后 node 重放仍只读档 → 再次 DENIED → 失败收尾（无写档执行）
        calls.append({"mode": context.sandbox_mode})
        raise AppError(ErrorCode.DENIED, "沙箱卷只读拒绝写入（read-only 档位）")

    monkeypatch.setattr(NativeToolExecutor, "call", fake_call)
    gateway = _ScriptedGateway([_PLAN_OK, _REACT_BASH_WRITE, _REACT_DONE, _REACT_DONE])
    agent = LangGraphAgent(gateway, agent_registry=_BASH_REGISTRY, checkpointer=_saver())
    config = _engine_config("esc-reject")
    interrupt_value, _events = _collect_until_interrupt(
        agent, "帮我运行脚本创建标记文件", config
    )
    assert interrupt_value is not None

    resumed = _resume(agent, config, {"action": "reject", "id": interrupt_value.get("id")})
    pending = _all_pending(resumed)
    # reject：不产生任何 workspace-write 调用（全部只读档 DENIED）——node 重放
    # 后拒绝观察 → H4 阶梯收尾（error）
    assert calls and all(item["mode"] != "workspace-write" for item in calls)
    tool_results = [e for e in pending if e["kind"] == "tool_result"]
    assert tool_results and all(e["payload"].get("ok") is False for e in tool_results)
    completed = next(e for e in pending if e["kind"] == "response.completed")
    assert completed["payload"]["finish_reason"] == "error"
    # plan + bash Act + repair 后 done + 再收尾 done（H4 阶梯；reject 不产 L3）
    assert gateway.calls == 4


def test_escalation_disabled_denied_is_plain_failure(monkeypatch) -> None:
    """开关默认关：DENIED 仅失败观察，无升档卡（F4 翻转前零行为变化）。"""
    monkeypatch.setattr(settings, "hybrid_engine_enabled", True)
    monkeypatch.setattr(settings, "agent_escalation_approval_enabled", False)

    async def fake_call(self, definition, arguments, context):
        raise AppError(ErrorCode.DENIED, "沙箱卷只读拒绝写入（read-only 档位）")

    monkeypatch.setattr(NativeToolExecutor, "call", fake_call)
    gateway = _ScriptedGateway([_PLAN_OK, _REACT_BASH_WRITE, _REACT_DONE, _REACT_DONE])
    agent = LangGraphAgent(gateway, agent_registry=_BASH_REGISTRY, checkpointer=_saver())
    config = _engine_config("esc-off")
    interrupt_value, events = _collect_until_interrupt(
        agent, "帮我运行脚本创建标记文件", config
    )
    assert interrupt_value is None  # 无卡
    pending = _all_pending(events)
    tool_results = [e for e in pending if e["kind"] == "tool_result"]
    assert tool_results and tool_results[0]["payload"].get("ok") is False
    assert any(e["kind"] == "response.completed" for e in pending)
