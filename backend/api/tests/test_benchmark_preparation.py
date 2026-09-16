"""评测准备闭环：真实协调器和数据库，供应商调用替身不代替上线试点。"""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import collaboration, loop, loop_wiring, preparation
from app.agent.collaboration import CollaborationCoordinator
from app.agent.collaboration_scope import TurnChildren
from app.agent.model_budget import ModelCallBudget
from app.errors import AppError, ErrorCode
from app.models import AgentInstance, AgentRun, AgentRunEvent, Session, Setting
from app.routers.collaborations import _run_payload, _safe_event
from tests import test_subagent_collaboration as collaboration_fixtures

collaboration_db = collaboration_fixtures.collaboration_db


def blueprint():
    """合法小型蓝图，不宣称结果分数或来源已审核。"""
    return {
        "scope": {"evaluation_mode": "model", "scenario_ids": ["reasoning"]},
        "body": {
            "measurement_goal": "测试文本推理能力", "capabilities": ["多步推理"],
            "metrics": [{"id": "accuracy", "description": "正确率", "direction": "higher"}],
            "budget": {"max_samples": 2, "max_target_calls": 2, "max_judge_calls": 0, "cost_limit_usd": None},
            "exclusions": ["工具系统"], "assumptions": ["开发试点"],
        },
    }


def data_manifest():
    """来源与验证计划仅是候选声明。"""
    return {
        "scope": blueprint()["scope"],
        "body": {
            "sources": [{"source_id": "source1", "uri": "https://example.invalid/source",
                         "license": "待审核", "provenance": "团队需求", "intended_use": "candidate"}],
            "candidates": [{"case_id": "case1", "source_id": "source1", "group_id": "group1",
                            "scenario_id": "reasoning", "input": "比较两个结论",
                            "evidence_locator": "需求第 1 节", "verification_plan": "由独立人员复核"}],
            "coverage_gaps": ["尚未覆盖长上下文"],
        },
    }


def scoring_policy():
    """评分草案具备锚点、校准和缺失处理，不实际打分。"""
    return {
        "scope": blueprint()["scope"],
        "body": {
            "scorer": "llm_rubric",
            "dimensions": [{"id": "accuracy", "weight": 1.0, "anchors": [
                {"score": 0, "description": "错误"}, {"score": 0.5, "description": "部分正确"},
                {"score": 1, "description": "全部正确"},
            ]}],
            "normalization": "加权汇总", "evidence_requirements": ["引用答案段落"],
            "missing_policy": "review", "review_triggers": ["分歧"], "calibration_plan": "独立黄金集校准",
        },
    }


@pytest.fixture
def prepared(collaboration_db, monkeypatch):
    """保留真实 spawn、事件、终态和引用读取，模型只负责提供可控的最终正文。"""
    responses = {
        "benchmark_blueprint": blueprint(), "data_manifest_candidate": data_manifest(),
        "scoring_policy_draft": scoring_policy(),
    }
    messages = []
    release = asyncio.Event()
    release.set()

    class Runtime:
        """供应商替身通过真实子日志写最终回复。"""

        def __init__(self, log, _graph, **_kwargs):
            """记录受控 run 日志。"""
            self.log = log

        async def submit(self, content, **_kwargs):
            """可挂起以覆盖取消和访问撤销时序。"""
            messages.append(content)
            await release.wait()
            with collaboration_db() as db:
                contract = preparation.load_contract(db, self.log.run_id)
            payload = responses[contract["kind"]]
            text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            self.log.append("assistant/message", {"content": text})
            self.log.append("turn/end", {"reason": "completed"})

        async def wait(self):
            """同步写入日志，无额外供应商等待。"""

        async def close(self):
            """无外部连接。"""

    children = TurnChildren(max_children=8)
    service = SimpleNamespace(session_factory=collaboration_db, _settings=lambda: None,
                              _broker=None, _close_resources=AsyncMock())
    coordinator = CollaborationCoordinator(
        service, SimpleNamespace(log=SimpleNamespace(session_id="s1")), "u1",
        {"content": "准备开发基准", "profile_id": "p1"}, children,
        ModelCallBudget(max_calls=80, max_concurrent=3, max_calls_per_run=20),
    )
    wiring = AsyncMock(return_value=({}, []))
    monkeypatch.setattr(collaboration, "AgentRuntime", Runtime)
    monkeypatch.setattr(loop, "build_agent", AsyncMock(return_value=None))
    monkeypatch.setattr(loop_wiring, "build_dependencies", wiring)
    monkeypatch.setattr(coordinator, "_child_workspace", lambda run_id: f"isolated/{run_id}")
    return SimpleNamespace(coordinator=coordinator, responses=responses, messages=messages,
                           db=collaboration_db, wiring=wiring, children=children, release=release)


async def spawn(prepared, expert_id="benchmark-designer", refs=None, *, call_id=None):
    """每次调用使用独立身份；可传同一 call_id 验证幂等。"""
    return await prepared.coordinator._spawn(
        {"expert_id": expert_id, "goal": "按材料准备草稿", "output_contract": "遵守服务端 schema",
         "input_refs": refs or []},
        {"turn": 1, "call_id": call_id or f"call-{len(prepared.coordinator.tasks)}"},
    )


async def result(prepared, created):
    """经过真实异步完成和数据库投影读取结果。"""
    await prepared.coordinator.tasks[created["run_id"]]
    return await prepared.coordinator._result({"run_id": created["run_id"]}, {"turn": 1})


@pytest.mark.asyncio
async def test_blueprint_to_parallel_data_and_scoring(prepared):
    """完整三角色链路，独立上下文接收固定版本材料，页面刷新仍读取相同成果。"""
    first = await spawn(prepared)
    first_result = await result(prepared, first)
    ref = first_result["result"]["reference"]
    assert first_result["status"] == "succeeded"
    assert ref["id"] != first["run_id"]
    second, third = await asyncio.gather(
        spawn(prepared, "benchmark-data-curator", [ref], call_id="data"),
        spawn(prepared, "benchmark-scoring-designer", [ref], call_id="scoring"),
    )
    outputs = await asyncio.gather(result(prepared, second), result(prepared, third))
    assert all(item["status"] == "succeeded" for item in outputs)
    for item in outputs:
        envelope = item["result"]["deliverable"]
        assert envelope["based_on_refs"] == [ref]
        assert envelope["producer"]["run_id"] == item["run_id"]
        assert envelope["validation"]["status"] == "validated"
        with prepared.db() as db:
            run = db.get(AgentRun, item["run_id"])
            projected = _run_payload(run, db.get(AgentInstance, run.instance_id))
        assert projected["result"] == item["result"]
    assert all("测试文本推理能力" in message for message in prepared.messages[1:])
    assert len({call.args[3]["_subagent_workspace"] for call in prepared.wiring.call_args_list}) == 3
    assert len(prepared.coordinator.tasks) == 3
    with prepared.db() as db:
        assert db.get(AgentRun, first["run_id"]).result == first_result["result"]


@pytest.mark.asyncio
async def test_frozen_prompt_and_no_private_contract_leak(prepared):
    """派发后修改专家设置不会改变本运行角色文本；内部事件不向页面暴露快照。"""
    created = await spawn(prepared)
    with prepared.db() as db:
        contract = preparation.load_contract(db, created["run_id"])
        db.add(Setting(key="agent_expert_prompt_overrides", value={"benchmark-designer": "后来的角色"}))
        db.commit()
    completed = await result(prepared, created)
    actual = prepared.wiring.call_args.args[3]["_preparation_contract"]
    assert actual["expert_prompt"] == contract["expert_prompt"]
    assert "后来的角色" not in actual["expert_prompt"]
    with prepared.db() as db:
        event = db.query(AgentRunEvent).filter_by(run_id=created["run_id"], type="preparation/contract").one()
        assert _safe_event(event.envelope)["data"] == {}
    assert completed["expert"]["prompt_version"].startswith("sha256:")
    assert "expert_prompt" not in completed["expert"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ref", ["hash", "version", "kind", "missing", "duplicate", "extra"])
async def test_bad_refs_rejected_before_child_created(prepared, bad_ref):
    """引用错误不得进入模型调用，尤其不能接受路径、latest 或自报 approved。"""
    first = await result(prepared, await spawn(prepared))
    ref = deepcopy(first["result"]["reference"])
    if bad_ref == "hash":
        ref["hash"] = "sha256:" + "0" * 64
    elif bad_ref == "version":
        ref["version"] = "latest"
    elif bad_ref == "kind":
        ref["kind"] = "file"
    elif bad_ref == "missing":
        ref["id"] = "missing"
    elif bad_ref == "extra":
        ref["approved"] = True
    refs = [ref, ref] if bad_ref == "duplicate" else [ref]
    with pytest.raises(AppError) as exc:
        await spawn(prepared, "benchmark-data-curator", refs)
    assert exc.value.code == (ErrorCode.NOT_FOUND if bad_ref == "missing" else ErrorCode.VALIDATION)
    assert len(prepared.coordinator.tasks) == 1
    with prepared.db() as db:
        assert db.query(AgentRun).count() == 1


@pytest.mark.asyncio
async def test_missing_blueprint_and_untyped_expert_rejected(prepared):
    """数据/评分必须有蓝图，普通专家不能把材料读取变成绕过用途检查的渠道。"""
    with pytest.raises(AppError, match="蓝图"):
        await spawn(prepared, "benchmark-data-curator")
    first = await result(prepared, await spawn(prepared))
    with pytest.raises(AppError, match="不接受"):
        await spawn(prepared, "general", [first["result"]["reference"]])


@pytest.mark.asyncio
async def test_cross_session_and_revoked_visibility(prepared):
    """即使知道完整 hash，也不能跨会话读取；旧幂等回执不绕过当前会话授权。"""
    created = await spawn(prepared, call_id="first")
    first = await result(prepared, created)
    ref = first["result"]["reference"]
    with prepared.db() as db:
        db.add(Session(id="s2", user_id="u1", title="另一个会话", engine_version="agent_loop_v2"))
        db.commit()
        with pytest.raises(AppError) as exc:
            preparation.resolve_inputs(db, "s2", "u1", "data_manifest_candidate", [ref])
        assert exc.value.code == ErrorCode.NOT_FOUND
        session = db.get(Session, "s1")
        session.user_id = "other-owner"
        db.commit()
    with pytest.raises(AppError) as exc:
        await spawn(prepared, call_id="first")
    assert exc.value.code == ErrorCode.NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_output", ["forged", "missing", "nan", "duplicate", "fenced", "huge", "scope", "budget"])
async def test_invalid_model_output_never_publishes_reference(prepared, bad_output):
    """模型正常结束不等于交付通过；伪造验证/审批及格式问题明确失败。"""
    payload = blueprint()
    if bad_output == "forged":
        payload["validation"] = {"status": "validated", "approved": True}
    elif bad_output == "missing":
        del payload["body"]["measurement_goal"]
    elif bad_output == "nan":
        payload["body"]["budget"]["cost_limit_usd"] = float("nan")
    elif bad_output == "duplicate":
        payload = '{"scope":{},"scope":{},"body":{}}'
    elif bad_output == "fenced":
        payload = "```json\n" + json.dumps(payload) + "\n```"
    elif bad_output == "huge":
        payload = "文" * 65536
    elif bad_output == "scope":
        payload["scope"]["evaluation_mode"] = "agent_system"
    elif bad_output == "budget":
        payload["body"]["budget"]["max_target_calls"] = 1
    prepared.responses["benchmark_blueprint"] = payload
    completed = await result(prepared, await spawn(prepared))
    assert completed["status"] == "failed"
    assert completed["error_code"] == "VALIDATION"
    assert completed["result"]["complete"] is False
    assert "reference" not in completed["result"]
    assert completed["result"]["validation"]["status"] == "rejected"
    assert all(set(issue) == {"path", "code"} for issue in completed["result"]["validation"]["issues"])


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["source", "evidence", "scenario", "weight", "anchor", "hidden_answer"])
async def test_semantic_gaps_and_hidden_answers_rejected(prepared, defect):
    """严格正文校验拒绝缺证据、外部来源、越界场景以及不完整评分规则。"""
    first = await result(prepared, await spawn(prepared))
    role = "benchmark-data-curator"
    data = prepared.responses["data_manifest_candidate"]
    scoring = prepared.responses["scoring_policy_draft"]
    if defect == "source":
        data["body"]["candidates"][0]["source_id"] = "absent"
    elif defect == "evidence":
        del data["body"]["candidates"][0]["evidence_locator"]
    elif defect == "scenario":
        data["scope"]["scenario_ids"] = ["math"]
        data["body"]["candidates"][0]["scenario_id"] = "math"
    elif defect == "hidden_answer":
        data["body"]["candidates"][0]["expected_answer"] = "隐藏答案"
    else:
        role = "benchmark-scoring-designer"
        if defect == "weight":
            scoring["body"]["dimensions"][0]["weight"] = 0.5
        else:
            scoring["body"]["dimensions"][0]["anchors"][1]["score"] = 1
    completed = await result(prepared, await spawn(prepared, role, [first["result"]["reference"]]))
    assert completed["status"] == "failed"
    assert "reference" not in completed["result"]


@pytest.mark.asyncio
async def test_cancel_and_late_finish_cannot_publish(prepared):
    """取消终态不可被后来有效 JSON 覆盖。"""
    prepared.release.clear()
    created = await spawn(prepared)
    await asyncio.sleep(0)
    await prepared.coordinator.cancel_run_by_user(created["run_id"], "停止")
    await asyncio.gather(*prepared.coordinator.tasks.values(), return_exceptions=True)
    prepared.coordinator._finish_run(created["run_id"], "succeeded", {
        "content": json.dumps(blueprint()), "finish_reason": "completed", "complete": True,
    })
    with prepared.db() as db:
        run = db.get(AgentRun, created["run_id"])
        assert run.status == "cancelled" and "reference" not in run.result


@pytest.mark.asyncio
async def test_same_call_replays_same_deliverable_and_new_run_is_immutable(prepared):
    """旧运行与交付保持不变；返工创建独立身份，不谎称已有修订链。"""
    first = await spawn(prepared, call_id="first")
    old = await result(prepared, first)
    assert await spawn(prepared, call_id="first") == first
    prepared.responses["benchmark_blueprint"]["body"]["measurement_goal"] = "修正后的目标"
    revised = await result(prepared, await spawn(prepared, refs=[old["result"]["reference"]]))
    assert revised["result"]["reference"]["id"] != old["result"]["reference"]["id"]
    assert revised["result"]["deliverable"]["revision"] == 1
    with prepared.db() as db:
        assert db.get(AgentRun, first["run_id"]).result == old["result"]


@pytest.mark.asyncio
async def test_recheck_inputs_before_publishing(prepared):
    """专家启动后上游内容被改动，旧摘要必须在终态验收再次拒绝。"""
    first = await spawn(prepared)
    initial = await result(prepared, first)
    prepared.release.clear()
    second = await spawn(prepared, "benchmark-data-curator", [initial["result"]["reference"]])
    await asyncio.sleep(0)
    with prepared.db() as db:
        run = db.get(AgentRun, first["run_id"])
        value = deepcopy(run.result)
        value["body"]["measurement_goal"] = "被改动的正文"
        run.result = value
        db.commit()
    prepared.release.set()
    completed = await result(prepared, second)
    assert completed["status"] == "failed"
    assert completed["result"]["validation"]["issues"] == [{"path": "input_refs", "code": "VALIDATION"}]
    assert "reference" not in completed["result"]


@pytest.mark.asyncio
async def test_combined_material_limit_is_not_silent_truncation(prepared):
    """单份合法草稿仍受输入合计字节上限约束，超限不能截断证据后继续。"""
    payload = blueprint()
    payload["body"]["measurement_goal"] = "文" * 7000
    payload["body"]["assumptions"] = ["文" * 1900] * 3
    prepared.responses["benchmark_blueprint"] = payload
    one = await result(prepared, await spawn(prepared))
    two = await result(prepared, await spawn(prepared))
    with pytest.raises(AppError, match="64 KiB"):
        await spawn(prepared, "benchmark-data-curator", [one["result"]["reference"], two["result"]["reference"]])
    assert len(prepared.coordinator.tasks) == 2


@pytest.mark.asyncio
async def test_directory_exposes_actual_submission_schema(prepared):
    """主 Agent 可发现三个准备角色及真实 schema，不能把报告角色误认为已实现。"""
    catalog = await prepared.coordinator._list({}, {})
    drafts = [item for item in catalog["experts"] if item.get("deliverable_kind")]
    assert {item["deliverable_kind"] for item in drafts} == set(preparation.SUBMISSIONS)
    for item in drafts:
        assert item["submission_schema"] == preparation.submission_schema(item["deliverable_kind"])
        assert item["submission_schema"]["additionalProperties"] is False
