"""前端契约：模型能力、真实请求估算、安全预览与快照 ACL。"""

from copy import deepcopy

from app.agent.events import frame, persistent_frame, project_fact, visible_frame
from app.agent.loop_presentation import (
    profile_capabilities,
    question_answers,
    request_summary,
    tool_display,
)
from app.harness.execution.loop_tools import tool_spec
from app.harness.execution.registry import build_default_registry
from app.llm.contracts import ModelConfig
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


def test_task_display_accepts_agent_wire_registry_and_mcp_names():
    """三种已登记任务名称都投影同一安全字段集合，避免卡片因名称差异失去参数。"""
    names = (
        "platform_task_status",
        "task.status",
        "platform.tasks.task.status",
    )
    for name in names:
        display = tool_display({"name": name, "args": {"task_id": "task-1", "secret": "hidden"}})
        assert display["registry_name"] == "task.status"
        assert '"task_id": "task-1"' in display["arguments_preview"]
        assert "hidden" not in str(display)


def test_request_meter_matches_actual_wire_estimator():
    """统计读取同一个请求对象，明确估算及输出预留。"""
    from app.agent.loop_wiring import _prompt_tokens

    config = ModelConfig(protocol="openai_chat", base_url="https://api.deepseek.com", model="deepseek-chat", api_key="test")
    request = resolve_request(config, messages=[{"role": "user", "content": "你好"}])
    summary = request_summary(request, context_window=64000, input_fingerprint="fingerprint", history_upto_seq=7)
    assert summary["context_meter"]["input_tokens"] == _prompt_tokens(request)
    assert summary["context_meter"]["reserved_output_tokens"] == request.max_tokens
    assert sum(summary["context_meter"]["breakdown"].values()) == _prompt_tokens(request)
    assert summary["context_meter"]["breakdown"]["system_prompt"] > 0
    assert summary["context_meter"]["breakdown"]["conversation_messages"] > 0
    assert "api_key" not in str(summary)


def test_request_meter_splits_native_and_mcp_tool_schemas():
    """工具来源按本轮注册表快照区分，不能把 MCP schema 混入原生工具。"""
    config = ModelConfig(protocol="openai_chat", base_url="https://api.deepseek.com", model="deepseek-chat", api_key="test")
    request = resolve_request(
        config,
        messages=[{"role": "user", "content": "请执行"}],
        tools=[
            ToolSpec("read", "读取文件", {"type": "object", "properties": {}}),
            ToolSpec("platform_task_create", "创建任务", {"type": "object", "properties": {}}),
        ],
    )
    meter = request_summary(
        request,
        context_window=64000,
        input_fingerprint="fingerprint",
        history_upto_seq=7,
        tool_transports={"read": "native", "platform_task_create": "mcp"},
    )["context_meter"]
    assert meter["breakdown"]["tools"] > 0
    assert meter["breakdown"]["mcp"] > 0
    assert meter["breakdown"]["skill"] == 0
    assert meter["breakdown"]["memory_files"] == 0


def test_request_summary_uses_native_tool_schema_shape():
    """轨迹快照必须直接复用真实注册表定义，不能给前端拼装示例 Schema。"""
    config = ModelConfig(protocol="openai_chat", base_url="https://api.deepseek.com", model="deepseek-chat", api_key="test")
    definition = build_default_registry().get("read")
    request = resolve_request(
        config,
        messages=[{"role": "user", "content": "读取文件"}],
        tools=[tool_spec(definition)],
    )

    tool = request_summary(request)["tools"][0]

    assert tool == {
        "name": definition.name,
        "description": definition.description,
        "parameters": dict(definition.parameters_schema),
    }


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
