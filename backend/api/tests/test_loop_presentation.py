"""前端契约：模型能力、真实请求估算、安全预览与快照 ACL。"""

from copy import deepcopy

from app.agent.events import frame, persistent_frame, project_fact, visible_frame
from app.agent.loop_presentation import (
    profile_capabilities,
    question_answers,
    request_summary,
    tool_display,
)
from app.llm.contracts import ModelConfig, SystemSegment
from app.llm.loop_contracts import ToolSpec
from app.llm.resolver import AuthorizedProfileSnapshot, resolve_request


def test_efforts_use_provider_resolver():
    """DeepSeek 不发布 xhigh；未知普通模型不捏造思考能力。"""
    profile = AuthorizedProfileSnapshot(ModelConfig(protocol="openai_chat", base_url="https://api.deepseek.com", model="deepseek-chat", api_key="test"))
    allowed, default = profile_capabilities(profile)
    assert allowed == ["off", "low", "medium", "high", "max"]
    assert default in allowed


def test_preview_allowlist_empty_edit_and_truncation():
    """空替换保留；秘密字段不公开，长内容有明确截断。"""
    display = tool_display({"name": "edit", "args": {"path": "a.txt", "new": "", "api_key": "secret"}})
    assert '"new": ""' in display["arguments_preview"]
    assert "secret" not in str(display)
    output = tool_display({"name": "read", "status": "succeeded", "content": "x" * 12001}, result=True)
    assert output["truncated"] and len(output["result_preview"]) == 12000
    assert tool_display({"name": "unknown", "args": {"secret": "hidden"}})["unavailable_reason"]


def test_request_meter_matches_actual_wire_estimator():
    """统计读取同一个请求对象，来源归因不会丢失或重复输入 token。"""
    from app.agent.loop_wiring import _prompt_tokens

    config = ModelConfig(protocol="openai_chat", base_url="https://api.deepseek.com", model="deepseek-chat", api_key="test")
    request = resolve_request(
        config,
        messages=[{"role": "user", "content": "你好"}],
        system_segments=(SystemSegment("系统提示词"),),
        tools=(
            ToolSpec("read", "读取", {"type": "object", "properties": {}}),
            ToolSpec("task.create", "创建评测", {"type": "object", "properties": {}}),
        ),
    )
    summary = request_summary(request, context_window=64000, input_fingerprint="fingerprint", history_upto_seq=7)
    meter = summary["context_meter"]
    assert meter["input_tokens"] == _prompt_tokens(request)
    assert meter["reserved_output_tokens"] == request.max_tokens
    assert meter["system_tokens"] > 0
    assert meter["mcp_tokens"] > 0
    assert meter["tools_tokens"] > 0
    assert meter["skills_tokens"] == 0
    assert sum(meter[name] for name in (
        "system_tokens", "skills_tokens", "mcp_tokens", "tools_tokens", "conversation_tokens",
    )) == meter["input_tokens"]
    assert "api_key" not in str(summary)


def test_reasoning_is_persistent_but_acl_trimmed_on_replay_and_snapshot():
    """普通回放、恢复快照和二次发送复验都必须裁掉未授权思考。"""
    fact = {"type": "assistant/message", "session_id": "s", "seq": 0, "data": {"turn": 1, "attempt_id": "a", "content": "答案", "reasoning_content": "授权思考"}}
    projection = project_fact(fact)[0]
    event = persistent_frame("s", 1, projection)
    before = deepcopy(event)
    assert visible_frame(event, reasoning=True)["data"]["reasoning_preview"] == "授权思考"
    assert "授权思考" not in str(visible_frame(event))
    snapshot = frame("resync.required", {"cursor": 1, "snapshot": {"timeline": [event], "assistants": [{"reasoning_preview": "授权思考"}]}}, session_id="s")
    assert "授权思考" not in str(visible_frame(snapshot))
    assert event == before


def test_question_array_roundtrip_preserves_comma_labels():
    """多选携带真实标签，不按逗号拆分，返回现有 validator 的唯一格式。"""
    questions = [{"id": "q", "question": "选择", "type": "checkbox", "required": True,
                  "options": [{"label": "A,B"}, {"label": "C"}]}]
    result = question_answers(questions, [{"question_id": "q", "answer": ["A,B", "C"]}])
    assert result == {"answers": [{"id": "q", "selected": ["A,B", "C"], "custom": ""}]}


def test_json_result_credentials_are_redacted_before_stringification():
    """工具 JSON 字符串必须先解析，避免键名脱敏被序列化边界绕过。"""
    result = tool_display({"name": "read", "status": "succeeded", "content": '{"api_key":"private-value","rows":2}'}, result=True)
    assert "private-value" not in str(result)
    assert result["format"] == "json"
