"""协议档工具探测经过三种真实 SDK，网络使用本地替身且不执行任何业务工具。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import profile_probe, profile_tool_probe
from app.llm.contracts import ModelConfig
from app.llm.loop_contracts import Done, TextDelta
from app.profile_tool_probe import probe_tool_roundtrip
from app.routers.profiles import _probe_message, _probe_model_config
from app.schemas import ProfileProbeCreate
from tests.test_loop_llm_sdk import install_transport, sse
from tests.test_responses_protocol import completed, wire


def probe_wire(protocol, *, call=False, answer="result-token", arguments=None):
    """生成标准工具流或最终文本，避免绕过 SDK 和生产适配器。"""
    args = arguments if arguments is not None else {"token": "request-token"}
    if protocol == "openai_responses":
        if call:
            items = [{"type": "reasoning", "id": "rs_probe", "summary": [], "encrypted_content": "opaque"},
                     {"type": "function_call", "id": "fc_probe", "call_id": "call_probe", "name": "profile_probe_echo",
                      "arguments": json.dumps(args), "status": "completed"}]
            return wire([{"type": "response.completed", "response": completed(items)}])
        data = completed()
        data["output"][0]["content"][0]["text"] = answer
        return wire([{"type": "response.output_text.delta", "delta": answer},
                     {"type": "response.completed", "response": data}])
    if protocol == "openai_chat":
        base = {"id": "chat_probe", "object": "chat.completion.chunk", "created": 1, "model": "unit"}
        delta = ({"tool_calls": [{"index": 0, "id": "call_probe", "type": "function",
                  "function": {"name": "profile_probe_echo", "arguments": json.dumps(args)}}]}
                 if call else {"content": answer})
        return b"".join([
            sse({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}),
            sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if call else "stop"}]}),
            b"data: [DONE]\n\n",
        ])
    block = ({"type": "tool_use", "id": "call_probe", "name": "profile_probe_echo", "input": {}}
             if call else {"type": "text", "text": ""})
    delta = {"type": "input_json_delta", "partial_json": json.dumps(args)} if call else {"type": "text_delta", "text": answer}
    events = [
        {"type": "message_start", "message": {"id": "msg_probe", "type": "message", "role": "assistant",
         "model": "unit", "content": [], "stop_reason": None, "usage": {"input_tokens": 1, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use" if call else "end_turn"}, "usage": {"output_tokens": 1}},
        {"type": "message_stop"},
    ]
    return b"".join(sse(event, named=True) for event in events)


@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
@pytest.mark.parametrize("failure", [None, "no_call", "wrong_arguments", "wrong_result", "eof"])
def test_tool_probe_real_sdk(monkeypatch, protocol, failure):
    """只有工具调用与回填两步成功才通过；自称支持、错误参数或断流均不通过。"""
    sent = []
    monkeypatch.setattr(profile_tool_probe.secrets, "token_hex", lambda size: "request-token" if size == 8 else "result-token")

    def handler(request):
        """捕获已序列化请求；第二次响应必须对应真实回填结果。"""
        payload = json.loads(request.content)
        sent.append(payload)
        if failure == "eof":
            content = b""
        elif len(sent) == 1:
            content = probe_wire(protocol, call=failure != "no_call",
                                 arguments={"token": "wrong"} if failure == "wrong_arguments" else None)
        else:
            content = probe_wire(protocol, answer="wrong" if failure == "wrong_result" else "result-token")
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    install_transport(monkeypatch, "anthropic" if protocol == "anthropic_messages" else "openai", handler)
    config = ModelConfig(protocol, "https://unit.invalid/v1", "unit", api_key="private-key",
                         reasoning_enabled=False, reasoning_template_id="no-reasoning-v1")
    result = asyncio.run(probe_tool_roundtrip(config))
    assert result["status"] == ("failed" if failure else "passed")
    assert "private-key" not in str(result) and "result-token" not in str(result)
    if failure is None:
        assert len(sent) == 2
        if protocol == "openai_responses":
            assert sent[1]["input"][1]["encrypted_content"] == "opaque"
            assert sent[1]["input"][-1] == {"type": "function_call_output", "call_id": "call_probe", "output": "result-token"}
        elif protocol == "openai_chat":
            assert sent[1]["messages"][-1]["tool_call_id"] == "call_probe"
            assert sent[1]["messages"][-1]["content"] == "result-token"
        else:
            output = sent[1]["messages"][-1]["content"][0]
            assert output["type"] == "tool_result" and output["tool_use_id"] == "call_probe"
            assert "result-token" in str(output["content"])


@pytest.mark.asyncio
async def test_tool_probe_timeout_and_close(monkeypatch):
    """持续等待的模型有整段时限，超时后连接池仍释放。"""
    closed = []

    class SlowAdapter:
        """模拟永不完成的上游。"""

        async def stream(self, request):
            """发一个正文片段后等待，不能因收到首字续期超时。"""
            yield TextDelta("wait")
            await asyncio.sleep(1)
            yield Done("stop")

        async def close(self):
            """记录清理。"""
            closed.append(True)

    monkeypatch.setattr(profile_tool_probe, "build_adapter", lambda config: (SlowAdapter(), config.model))
    config = ModelConfig("openai_chat", "https://unit.invalid", "unit", api_key="unit", reasoning_enabled=False, timeout_s=0.01)
    assert (await probe_tool_roundtrip(config))["error_code"] == "TIMEOUT"
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("check_tools,reasoning_ok", [(True, True), (False, True), (True, False)])
async def test_tool_probe_is_separate_and_uses_verified_effort(monkeypatch, check_tools, reasoning_ok):
    """工具失败不抹掉思考能力；未选择或无通过档位时不额外请求模型。"""
    selected = []

    async def reasoning(config, **kwargs):
        """仅允许 high 档通过，验证不会使用模板默认 medium。"""
        return (reasoning_ok and config.reasoning_effort == "high", "reasoning_delta", None)

    async def tool(config):
        """工具探测保持独立失败状态。"""
        selected.append(config.reasoning_effort)
        return {"status": "failed", "effort": config.reasoning_effort, "error_code": "UPSTREAM"}

    monkeypatch.setattr(profile_probe, "_probe_one", reasoning)
    monkeypatch.setattr(profile_probe, "probe_tool_roundtrip", tool)
    config = ModelConfig("openai_responses", "https://unit.invalid", "gpt-5.4", api_key="unit",
                         reasoning_template_id="responses-reasoning-effort-v1")
    result = await profile_probe._probe_all(config, check_tools=check_tools)
    assert result["supported_efforts"] == (["high"] if reasoning_ok else [])
    assert selected == (["high"] if check_tools and reasoning_ok else [])
    assert result["tool_probe"]["status"] == ("failed" if selected else "skipped")


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [0, 0.5])
async def test_tool_stage_respects_remaining_total_budget(monkeypatch, budget):
    """工具探测只能使用剩余总时限，预算耗尽时不发起额外请求。"""
    timeouts = []

    async def reasoning(config, **kwargs):
        """普通文本验证立即完成。"""
        return True, "request_completed", None

    async def tool(config):
        """捕获工具阶段得到的实际超时预算。"""
        timeouts.append(config.timeout_s)
        return {"status": "passed", "effort": "off"}

    monkeypatch.setattr(profile_probe, "PROBE_TOTAL_DEADLINE_SECONDS", budget)
    monkeypatch.setattr(profile_probe, "_probe_one", reasoning)
    monkeypatch.setattr(profile_probe, "probe_tool_roundtrip", tool)
    config = ModelConfig("openai_chat", "https://unit.invalid", "unit", api_key="unit",
                         reasoning_enabled=False, reasoning_template_id="no-reasoning-v1")
    result = await profile_probe._probe_all(config, check_tools=True)
    if budget:
        assert len(timeouts) == 1 and 0 < timeouts[0] <= budget
    else:
        assert not timeouts and result["tool_probe"]["error_code"] == "TIMEOUT"


@pytest.mark.parametrize("usages,expected", [(["agent"], True), (["target", "judge"], False)])
def test_profile_probe_route_selects_agent_usage(monkeypatch, usages, expected):
    """沿用已有保存接口；只有 Agent 用途触发附加工具探测。"""
    from app.routers import profiles

    selected = []

    def probe(config, *, check_tools):
        """捕获路由向探测服务传入的用途。"""
        selected.append(check_tools)
        return {"status": "passed"}

    monkeypatch.setattr(profiles, "probe_reasoning_template", probe)
    body = ProfileProbeCreate(name="unit", protocol="openai_responses", base_url="https://unit.invalid/v1",
                              model="unit", usages=usages, reasoning_template_id="no-reasoning-v1")
    _probe_model_config(body, api_key="unit")
    assert selected == [expected]


def test_probe_message_does_not_claim_tool_success_from_text():
    """文本完成与工具失败必须分别提示，且不泄露原始错误。"""
    probe = {"status": "passed", "supported_efforts": ["off"],
             "tool_probe": {"status": "failed", "error_code": "secret-upstream-error"}}
    message = _probe_message(probe)
    assert "工具往返未通过" in message and "secret" not in message
    assert "未验证" in _probe_message({**probe, "tool_probe": {"status": "skipped"}})


@pytest.mark.parametrize("change", ["none", "template_version", "api_key"])
def test_saved_tool_status_invalidates_with_credentials_or_template(monkeypatch, tmp_path, change):
    """已保存结果能回显，但凭据或模板变更后不可继续宣称通过。"""
    from app.config import settings
    from app.models import ProtocolProfile
    from app.profile_env import write_profile_env
    from app.routers import profiles
    from app.schemas import ProfileUpdate
    from tests.test_profile_check import _ProfileDb

    monkeypatch.setattr(settings, "profile_env_file", str(tmp_path / "profiles.env"))
    write_profile_env("tool-probe-unit", base_url="https://unit.invalid/v1", model="unit", api_key="unit")
    profile = ProtocolProfile(id="tool-probe-unit", name="unit", protocol="openai_responses", usages=["agent"],
        base_url="https://unit.invalid/v1", model="unit", anthropic_version=None, reasoning_config_version=1,
        reasoning_template_id="no-reasoning-v1", tool_call_mode="native", reasoning_probe={
            "status": "passed", "template_id": "no-reasoning-v1",
            "template_version": 1 if change == "template_version" else 2,
            "supported_efforts": ["off"], "tool_probe": {"status": "passed", "effort": "off"},
        })
    if change == "api_key":
        db = _ProfileDb(profile)
        db.add = lambda item: None
        db.commit = lambda: None
        db.refresh = lambda item: None
        monkeypatch.setattr(profiles, "client_ip", lambda request: None)
        result = profiles._update_profile(profile.id, ProfileUpdate(api_key="new-channel-key"),
                                         SimpleNamespace(), db, SimpleNamespace(id="unit-user"))
        assert profile.reasoning_probe is None
    else:
        result = profiles._profile_out(profile)
    assert result.tool_probe_status == ("passed" if change == "none" else "unverified")
