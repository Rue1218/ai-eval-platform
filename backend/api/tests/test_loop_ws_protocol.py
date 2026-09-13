"""v2 协议与事实投影：字段、双序号、完整目录与脱敏回归。"""

import json
from copy import deepcopy

import pytest

from app.agent.events import (
    correlation_from_data,
    event_schema_catalog,
    event_schema_catalog_etag,
    event_schema_descriptor,
    frame,
    persistent_frame,
    producer_for_event_type,
    project_fact,
    trace_frame,
    visible_frame,
)
from app.errors import AppError
from app.harness.security.loop_redaction import REDACTED, redact_event_for_transport
from app.routers.ws_v2 import parse_command


def command(kind="subscribe", data=None, **extra):
    """构造不含客户端 actor 的 v2 命令。"""
    return {
        "protocol_version": 2, "type": kind, "request_id": "r", "session_id": "s",
        "data": {} if data is None else data, **extra,
    }


def fact(kind="assistant/message", seq=0, **data):
    """事实从 seq=0 开始，工具/助手共用同一关联身份。"""
    return {
        "schema_version": 2, "type": kind, "seq": seq, "session_id": "s", "ts": 1.0,
        "data": {"turn": 1, "step": 1, "attempt_id": "a", **data},
    }


@pytest.mark.parametrize("value", [
    command(protocol_version=True), command(protocol_version=1),
    command(actor_id="victim"), command(data={"after_cursor": True}),
    command(data={"after_cursor": -1}), command(data={"last_event_id": 0}),
    command(data={"after_cursor": "0"}), command("unknown"),
    command("turn.submit", {"client_message_id": "m", "content": "x", "cwd": "/root"}),
    command("turn.cancel", {"turn_id": "t", "actor_id": "victim"}),
    command("trace.subscribe", {"after_seq": -2}),
])
def test_invalid_commands_fail_closed(value):
    """未知字段、类型转换、旧协议与客户端身份不允许透传。"""
    with pytest.raises(AppError):
        parse_command(json.dumps(value))


def test_submit_accepts_optional_controlled_profile_id():
    """协议档 ID 属于受控选择字段，规范帧保留给服务端重新授权解析。"""
    parsed = parse_command(json.dumps(command("turn.submit", {
        "client_message_id": "m", "content": "x", "profile_id": "profile-a",
    })))
    assert parsed.data["profile_id"] == "profile-a"


@pytest.mark.parametrize("raw", [
    '{"protocol_version":2,"protocol_version":2}',
    '{"protocol_version":2,"type":"subscribe","request_id":"r","session_id":"s",'
    '"data":{"after_cursor":NaN}}',
    "x" * 65537, "[" * 2000,
], ids=["duplicate-key", "nan", "oversized", "deep-json"])
def test_invalid_json_is_safe(raw):
    """重复键、非 JSON 数值、过大帧与深嵌套统一安全拒绝。"""
    with pytest.raises(AppError):
        parse_command(raw)


def test_fingerprint_canonical_defaults_and_trace_initial_seq():
    """显式默认值不改变摘要，事实初始订阅独立使用 -1。"""
    first = parse_command(json.dumps(command()))
    same = parse_command(json.dumps(command(data={"after_cursor": 0}, request_id="other")))
    assert first.fingerprint == same.fingerprint
    assert parse_command(json.dumps(command("trace.subscribe"))).data["after_seq"] == -1
    changed = parse_command(json.dumps(command(data={"after_cursor": 1})))
    assert first.fingerprint != changed.fingerprint


def test_approval_and_question_have_strict_identity():
    """交互完整身份与题目唯一性在进入主服务前验证。"""
    identity = {
        "interaction_id": "i", "turn_id": "t", "turn": 1, "attempt_id": "a",
        "call_id": "c", "nonce": "n",
    }
    approval = parse_command(json.dumps(command("approval.respond", {
        **identity, "decision": "always",
    })))
    assert approval.data["nonce"] == "n"
    question = parse_command(json.dumps(command("question.respond", {
        **identity, "answers": [{"question_id": "q", "answer": ["A"], "custom": "其他说明"}],
    })))
    assert question.data["answers"] == [{"question_id": "q", "answer": ["A"], "custom": "其他说明"}]
    with pytest.raises(AppError):
        parse_command(json.dumps(command("question.respond", {
            **identity, "answers": [
                {"question_id": "q", "answer": "1"}, {"question_id": "q", "answer": "2"},
            ],
        })))


def test_assistant_fact_has_two_stable_projections_and_no_raw():
    """一次提交产生消息与 attempt 终态；参数不进入公共工具声明。"""
    original = fact(
        content="answer", raw={"key": "hidden"}, protocol_state={"items": ["opaque"]},
        header={"system": "hidden"}, reasoning_content="private",
        usage={"prompt_tokens": 8, "completion_tokens": 3}, latency_ms=123,
        tool_calls=[{"id": "c", "name": "read", "args": {"secret": "hidden"}}],
    )
    before = deepcopy(original)
    projections = project_fact(original)
    assert [p["type"] for p in projections] == ["assistant.message", "assistant.end"]
    for item in projections:
        assert item["durability"] == "persistent"
        assert item["projection_kind"] == item["type"]
        assert item["correlation"]["source_seq"] == 0
        assert "cursor" not in item
    payload = projections[0]["data"]
    assert payload["tool_calls"] == [{"id": "c", "name": "read"}]
    assert payload["usage"] == {"prompt_tokens": 8, "completion_tokens": 3}
    assert payload["latency_ms"] == 123
    assert "hidden" not in json.dumps(projections)
    assert original == before
    wire = persistent_frame("s", 8, projections[0])
    assert wire["cursor"] == 8 and wire["correlation"]["source_seq"] == 0
    assert "projection_kind" not in wire


def test_assistant_attempt_latency_is_projected_without_estimating_old_records():
    """单次模型 Attempt 的耗时随消息和终态投影，旧事实缺字段仍保持兼容。"""
    projections = project_fact(fact(content="answer", latency_ms=1267))
    assert projections[0]["data"]["latency_ms"] == 1267
    assert projections[1]["data"]["latency_ms"] == 1267
    legacy = project_fact(fact(content="legacy"))
    assert all("latency_ms" not in item["data"] for item in legacy)


def test_failed_attempt_projects_safe_error_message_and_platform_code():
    """失败 Attempt 公开固定摘要和平台码，绝不投影上游错误正文。"""
    projected = project_fact(fact(
        "assistant/attempt",
        error="模型服务额度已用尽，请为当前协议档充值或切换可用模型后重试",
        error_code="BUDGET_EXCEEDED",
        raw={"message": "Authorization: super-secret"},
    ))[0]
    assert projected["type"] == "assistant.end"
    assert projected["data"]["error_code"] == "BUDGET_EXCEEDED"
    assert "额度已用尽" in projected["data"]["error_message"]
    assert "super-secret" not in json.dumps(projected)


@pytest.mark.parametrize("status", [
    "succeeded", "failed", "denied", "cancelled", "not_started", "outcome_unknown",
])
def test_tool_six_states_keep_identity_not_model_body(status):
    """六态不折叠；V1.78 登记工具的成功内容只经限长脱敏预览公开。"""
    event = fact("tool/result", call_id="c", call_seq=2, name="read", status=status,
                 content="PRIVATE BODY", output="PRIVATE BODY", synthetic=True)
    projected = project_fact(event)[0]
    assert projected["data"]["status"] == status
    assert projected["correlation"]["call_id"] == "c"
    assert "content" not in projected["data"] and "output" not in projected["data"]
    if status == "succeeded":
        assert projected["data"]["display"]["result_preview"] == "PRIVATE BODY"
    else:
        assert "PRIVATE BODY" not in json.dumps(projected)


def test_tool_dispatch_projects_name_mapping_and_contract_without_arguments():
    """公开调度字段可解释 wire→registry 映射，但绝不携带规范化参数或沙箱路径。"""
    event = fact(
        "tool/dispatch",
        call_id="c",
        call_seq=2,
        name="platform_task_status",
        execution_id="execution",
        registry_name="task.status",
        wire_name="platform_task_status",
        tool_contract_version="deepseek-harness.v1",
        normalized_args={"task_id": "private-task"},
        scope_path="C:/private/workspace",
    )
    projected = project_fact(event)[0]
    assert projected["data"] == {
        "name": "platform_task_status",
        "execution_id": "execution",
        "registry_name": "task.status",
        "wire_name": "platform_task_status",
        "tool_contract_version": "deepseek-harness.v1",
    }
    assert "private" not in json.dumps(projected)


def test_acl_placeholder_and_reasoning_filter():
    """受限卡占原游标；未授权 reasoning 增量直接丢弃。"""
    projected = project_fact(fact("approval/asked", id="i", toolName="bash", nonce="n"))[0]
    wire = persistent_frame("s", 1, projected)
    restricted = visible_frame(wire)
    assert restricted["cursor"] == 1
    assert restricted["data"] == {"restricted": True}
    assert visible_frame(wire, interactions=True)["data"]["interaction_id"] == "i"
    delta = frame("assistant.reasoning.delta", {"text": "reason"}, session_id="s")
    assert visible_frame(delta) is None
    assert visible_frame(delta, reasoning=True)["data"]["text"] == "reason"


def test_source_catalog_unknown_types_and_sensitive_paths():
    """源目录、未知 schema、生产者与关联函数均可直接供 SessionLog 调用。"""
    catalog = event_schema_catalog()
    assert {"request/header", "assistant/attempt", "tool/result"} <= catalog["events"].keys()
    assert event_schema_descriptor("future/new")["status"] == "unknown"
    assert producer_for_event_type("tool/result")
    assert correlation_from_data({"turn": 1, "step": True, "header_seq": 3}) == {
        "turn": 1, "header_seq": 3, "parent_event_seq": 3,
    }
    assert event_schema_catalog_etag().startswith("sha256:")
    catalog["events"].clear()
    assert event_schema_catalog()["events"]


def test_catalog_matches_runtime_history_selection_and_legacy_attempts():
    """真实 Loop 选择元数据符合目录，新字段保持对旧 attempt 事实的兼容。"""
    from jsonschema import Draft202012Validator

    from app.agent.loop import _history_selection

    history = [{"role": "user", "content": "first"},
               {"role": "assistant", "content": "reply"},
               {"role": "user", "content": "latest"}]
    selection = _history_selection(history, history[2:])
    catalog = event_schema_catalog()
    assert catalog["catalog_version"] == 6
    assert "task_plan/updated" in catalog["events"]
    validator = Draft202012Validator(catalog["events"]["assistant/attempt_start"]["schema"])
    legacy = {"turn": 1, "step": 1, "attempt_id": "a", "header_seq": 0,
              "history_upto_seq": 5}
    validator.validate(legacy)
    current = {**legacy, "history_selection": selection, "fingerprint_algorithm": "dsh-json-v1"}
    validator.validate(current)
    assert selection["indices"] == [2] and selection["message_count"] == 3
    assert list(validator.iter_errors({
        **current, "history_selection": {**selection, "indices": [-1]},
    }))
    event = fact("assistant/attempt_start", **current)
    semantic = project_fact(event)[0]
    assert semantic["data"] == {"header_seq": 0, "history_upto_seq": 5}
    trace = trace_frame(event, "s", source="history")
    assert trace["data"]["event"]["data"]["history_selection"] == selection
    assert trace["data"]["event"]["data"]["fingerprint_algorithm"] == "dsh-json-v1"

    switched_history = [{"role": "assistant", "content": "reply", "protocol_state": {"private": True}}]
    switched_selection = _history_selection(
        switched_history, [{"role": "assistant", "content": "reply"}],
    )
    validator.validate({**legacy, "history_selection": switched_selection})
    assert switched_selection["algorithm"] == "message_indices.v2"


def test_runtime_command_catalog_matches_store_receipt_without_semantic_reexecution():
    """登记 Store 现用 runtime/command 回执形状，不额外生成持久语义/命令接受帧。"""
    from jsonschema import Draft202012Validator

    receipt = {"fingerprint": "a" * 64, "data": {
        "accepted": True, "turn": 1, "turn_id": "s:1", "client_message_id": "m",
    }, "correlation": {"turn": 1, "turn_id": "s:1"}}
    catalog = event_schema_catalog()
    Draft202012Validator(catalog["events"]["runtime/command"]["schema"]).validate(receipt)
    assert event_schema_descriptor("runtime/command")["status"] == "known"
    assert producer_for_event_type("runtime/command") == "session.log"
    event = fact("runtime/command", **receipt)
    assert project_fact(event) == []
    trace = trace_frame(event, "s", source="history")
    assert trace["type"] == "trace.event" and "cursor" not in trace
    assert trace["data"]["event"]["data"] == receipt


def test_command_trace_omits_raw_request_and_nested_credential_extensions():
    """即使旧事实或扩展误带请求，trace 也只能公开接受结果白名单。"""
    event = fact("runtime/command", fingerprint="a" * 64, data={
        "accepted": True, "interaction_id": "i", "nonce": "nonce-private",
        "request": {"content": "raw-request-private", "credential": "credential-private"},
        "extension": {"payload": "unregistered-private"},
        "headers": {"Authorization": "auth-private"},
    }, correlation={"turn_id": "s:1", "extra": "extra-private"},
        request={"body": "body-private"}, credentials={"custom": "custom-private"},
        protocol_state={"opaque": "opaque-private"}, header={"system": "system-private"})
    original = deepcopy(event)
    trace = trace_frame(event, "s", source="runtime")
    public = trace["data"]["event"]["data"]
    assert public == {
        "fingerprint": "a" * 64, "data": {"accepted": True, "interaction_id": "i"},
        "correlation": {"turn_id": "s:1"},
    }
    assert "private" not in json.dumps(trace)
    assert event == original


def test_history_selection_trace_keeps_metadata_only():
    """上下文选择元数据中的未登记扩展不能成为历史正文的旁路。"""
    selection = {"algorithm": "message_indices.v1", "indices": [0], "message_count": 1,
                 "input_fingerprint": "a" * 64, "request": {"content": "PRIVATE"}}
    trace = trace_frame(fact("assistant/attempt_start", history_selection=selection),
                        "s", source="history")
    assert "PRIVATE" not in json.dumps(trace)
    assert trace["data"]["event"]["data"]["history_selection"]["indices"] == [0]


def test_recursive_redaction_and_unknown_fact_trace():
    """保留源通用脱敏，trace 既不占 cursor 也不外发系统或 opaque 内容。"""
    event = fact("future/new", data={"api_key": "secret"}, protocol_state="OPAQUE",
                 header="PRIVATE", raw="RAW")
    cleaned = redact_event_for_transport(event)
    assert cleaned["data"]["data"]["api_key"] == REDACTED
    assert event["data"]["data"]["api_key"] == "secret"
    trace = trace_frame(event, "s", source="history")
    assert trace["data"]["event"]["seq"] == 0
    assert trace["durability"] == "control" and "cursor" not in trace
    assert all(word not in json.dumps(trace) for word in ("OPAQUE", "PRIVATE", "RAW"))
    token = frame("assistant.text.delta", {"text": "Bearer abcdefghijklmnop"})
    assert token["data"]["text"] == REDACTED


def test_snapshot_preserves_ui_messages_but_rechecks_interaction_permission():
    """普通历史禁止模型 messages，但授权 UI 恢复消息不得被一并丢掉。"""
    original = frame("resync.required", {"cursor": 8, "snapshot": {
        "messages": [
            {"id": "m", "role": "user", "content": "hello"},
            {"role": "system", "content": "PRIVATE SYSTEM"},
            {"role": "tool", "content": "PRIVATE RESULT"},
        ],
        "pending_confirm": {"nonce": "private-nonce", "interaction_id": "i"},
    }}, session_id="s")
    assert len(original["data"]["snapshot"]["messages"]) == 1
    restricted = visible_frame(original, interactions=False)
    assert restricted["data"]["snapshot"]["pending_confirm"] == {"restricted": True}
    assert "private-nonce" not in json.dumps(restricted)
    assert original["data"]["snapshot"]["pending_confirm"]["nonce"] == "private-nonce"


def test_catalog_transport_preserves_source_schema_field_descriptions():
    """敏感字段名的 schema 描述并非秘密，完整事实目录不能被通用过滤破坏。"""
    catalog = event_schema_catalog()
    public = frame("schema.catalog", {"facts": catalog})
    assert public["data"]["facts"] == catalog
    assert "header" in public["data"]["facts"]["events"]["request/header"]["schema"]["properties"]


def test_trace_preserves_nonsecret_arguments_and_redacts_credentials():
    """诊断可解释工具参数，同时保持普通语义层的参数不可见边界。"""
    event = fact("tool/call", call_id="c", name="read", args={
        "file_path": "a.txt", "Authorization": "private", "api_key": "private",
    })
    trace = trace_frame(event, "s", source="runtime")
    assert trace["data"]["event"]["data"]["args"]["file_path"] == "a.txt"
    assert "private" not in json.dumps(trace)
    ordinary = project_fact(event)[0]
    assert ordinary["correlation"]["call_seq"] == 0
    assert "args" not in ordinary["data"]


def test_user_multimodal_history_is_not_sent_as_raw_semantic_content():
    """图文模型正文只生成用户文本投影，不能把内联图像混入公共会话流。"""
    original = fact("user/message", content=[
        {"type": "text", "text": "看附件"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,PRIVATE"}},
    ])
    payload = project_fact(original)[0]["data"]
    assert payload["content"] == "看附件"
    assert "PRIVATE" not in json.dumps(payload)


@pytest.mark.parametrize("kind,cursor", [
    ("turn.end", None), ("turn.end", 0), ("turn.end", True),
    ("assistant.text.delta", 1), ("pong", 1), ("unknown", None),
])
def test_durability_cannot_be_overridden(kind, cursor):
    """类型词汇固定持久性，不能将控制帧错误加入语义流。"""
    with pytest.raises(ValueError):
        frame(kind, {}, session_id="s", cursor=cursor)
