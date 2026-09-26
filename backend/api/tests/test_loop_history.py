"""历史回读的来源隔离、公开投影、共享分页预算及真实工具桥回归。"""

import json
from types import SimpleNamespace

import pytest

from app.agent import loop_wiring
from app.agent.compaction import ContextCompactor
from app.agent.experts import EXPERTS
from app.agent.history import HISTORY_TOKEN_LIMIT, register_history_tool
from app.errors import AppError, ErrorCode
from app.harness.context.meter import estimate_payload_tokens
from app.harness.execution.context import ToolExecutionContext
from app.harness.execution.loop_bridge import PlatformToolBridge
from app.harness.execution.registry import ToolRegistry
from app.harness.execution.scheduler import ToolScheduler
from app.harness.security.permission_tier import decide
from app.llm.loop_contracts import Done, TextDelta
from tests import test_loop_wiring as wiring_fixtures
from tests.test_loop_compaction import conversation, store_messages
from tests.test_loop_runtime import MemoryLog, ScriptedAdapter

wired = wiring_fixtures.wired


def _active_log(contents=("历史要求",), *, session_id="same-session"):
    """原始消息之后提交一个尚未结算的真实助手工具调用。"""
    log = MemoryLog(session_id)
    for content in contents:
        log.append("user/message", {"content": content})
    _append_active(log)
    return log


def _append_active(log):
    """工具执行时助手调用已落库，而当前 tool/result 尚未产生。"""
    log.append("assistant/message", {"message": {
        "role": "assistant", "content": "", "tool_calls": [
            {"id": "history-call", "name": "platform_history_read", "args": {"source_ids": ["m:0"]}},
        ],
    }})


def _reader(log):
    """只创建当前日志的注册表和可信执行上下文，不连接数据库。"""
    registry = ToolRegistry()
    register_history_tool(registry, log)
    context = ToolExecutionContext(session_id=log.session_id, user_id="actor", call_id="history-call")
    return registry, context


def _read(log, arguments):
    """纯 handler 验证与生产桥使用同一注册表定义。"""
    registry, context = _reader(log)
    return registry.get("history.read").handler(arguments, None, context)


def test_history_projection_excludes_private_state_and_inline_images():
    """用户图像、工具参数图像及供应商状态均不能通过回读进入公开结果。"""
    log = MemoryLog()
    log.append("user/message", {"content": [
        {"type": "text", "text": "请检查这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,IMAGEPRIVATE"}},
        {"type": "thinking", "thinking": "BLOCK_PRIVATE", "signature": "BLOCK_SIGNATURE_PRIVATE"},
    ]})
    log.append("assistant/message", {"message": {
        "role": "assistant", "content": "开始读取", "reasoning_content": "PRIVATE_REASONING",
        "protocol_state": {"items": [{"signature": "PRIVATE_SIGNATURE"}]},
        "tool_calls": [{"id": "old-read", "name": "read", "args": {
            "path": "a.png", "preview": "data:image/png;base64,ARGPRIVATE",
            "protocol_state": {"signature": "NESTED_PRIVATE"}, "api_key": "secret-key-value",
        }, "arguments_raw": "RAW_PRIVATE"}],
    }})
    log.append("tool/result", {"call_id": "old-read", "name": "read", "status": "failed",
                               "content": "读取失败 data:image/png;base64,TOOLPRIVATE"})
    _append_active(log)
    original = log.read()

    result = _read(log, {"source_ids": ["m:0", "m:1", "m:2"]})

    serialized = json.dumps(result, ensure_ascii=False)
    assert "PRIVATE" not in serialized and "secret-key-value" not in serialized
    assert "base64" not in serialized and "protocol_state" not in serialized
    assert "reasoning_content" not in serialized and "arguments_raw" not in serialized
    projected = [json.loads(item["text"]) for item in result["items"]]
    assert "图片内容已省略" in serialized
    assert projected[1]["tool_calls"][0]["args"]["path"] == "a.png"
    assert projected[2]["is_error"] is True and projected[2]["id"] == "old-read"
    assert all(item["next_offset"] is None for item in result["items"])
    assert log.read() == original


@pytest.mark.parametrize("credential", [
    "password=fictional-value", "api_key: fictional-value",
    "-----BEGIN RSA PRIVATE KEY-----\nfictional-body\n-----END RSA PRIVATE KEY-----",
])
@pytest.mark.parametrize("location", ["user", "tool", "arguments"])
def test_history_redacts_credential_assignments_before_pagination(credential, location):
    """回读派生结果不能重新发布记忆层已拒绝的凭据；先脱敏再计算公开分页位置。"""
    log = MemoryLog()
    log.append("user/message", {"content": credential if location == "user" else "安全的用户说明"})
    log.append("assistant/message", {"message": {
        "role": "assistant", "content": "读取历史文件", "tool_calls": [
            {"id": "old", "name": "read", "args": {
                "path": "config.txt", "note": credential if location == "arguments" else "安全说明",
            }},
        ],
    }})
    log.append("tool/result", {"call_id": "old", "name": "read", "status": "succeeded",
                               "content": credential if location == "tool" else "安全结果"})
    _append_active(log)
    original = log.read()
    source_id = {"user": "m:0", "arguments": "m:1", "tool": "m:2"}[location]
    pieces, offset = [], 0
    for _ in range(30):
        item = _read(log, {"source_ids": [source_id], "offset": offset, "max_chars": 13})["items"][0]
        pieces.append(item["text"])
        if item["next_offset"] is None:
            break
        offset = item["next_offset"]
    else:
        pytest.fail("脱敏后的有限消息应能分页读完")
    public = "".join(pieces)
    assert "fictional" not in public and "PRIVATE KEY" not in public
    assert "[已脱敏]" in public
    assert log.read() == original


def test_history_keeps_safe_security_explanations():
    """普通预算与密码保护说明不因包含安全相关词语而丢失。"""
    content = "token 预算为2048，password 字段不要写入日志。"
    item = _read(_active_log((content,)), {"source_ids": ["m:0"]})["items"][0]
    assert json.loads(item["text"])["content"] == content


@pytest.mark.parametrize("session_id,user_id", [("other-session", "actor"), ("same-session", "")])
def test_history_rejects_mismatched_or_missing_runtime_identity(session_id, user_id):
    """handler 只接受所属日志和已鉴权成员上下文，不能跨会话复用绑定函数。"""
    registry, _ = _reader(_active_log())
    context = ToolExecutionContext(session_id=session_id, user_id=user_id, call_id="history-call")
    with pytest.raises(AppError) as caught:
        registry.get("history.read").handler({"source_ids": ["m:0"]}, None, context)
    assert caught.value.code == ErrorCode.UNAUTHORIZED


def test_history_pages_reassemble_the_public_message_without_silent_truncation():
    """每页明确续读位置，拼回的是公开 JSON 全文而不是截断后伪称完整的消息。"""
    content = "已核验的详细事实。" * 700
    log = _active_log((content,))
    offset, pieces, total = 0, [], None
    for _ in range(20):
        result = _read(log, {"source_ids": ["m:0"], "offset": offset, "max_chars": 8000})
        assert estimate_payload_tokens(json.dumps(result, ensure_ascii=False)) <= HISTORY_TOKEN_LIMIT
        item = result["items"][0]
        total = item["total_chars"]
        assert item["offset"] == offset and item["text"]
        pieces.append(item["text"])
        if item["next_offset"] is None:
            break
        assert item["next_offset"] == offset + len(item["text"])
        offset = item["next_offset"]
    else:
        pytest.fail("有界分页未能读完来源")
    restored = "".join(pieces)
    assert len(pieces) > 1 and len(restored) == total
    assert json.loads(restored) == {"role": "user", "content": content}
    last = _read(log, {"source_ids": ["m:0"], "offset": total + 100})["items"][0]
    assert last == {"source_id": "m:0", "text": "", "offset": total, "next_offset": None, "total_chars": total}


def test_three_sources_share_one_output_token_budget():
    """三条大来源共享总预算，每条都获得可继续读取的非空片段。"""
    log = _active_log(tuple("大段已核验事实。" * 1500 for _ in range(3)))
    result = _read(log, {"source_ids": ["m:0", "m:1", "m:2"], "max_chars": 8000})
    assert estimate_payload_tokens(json.dumps(result, ensure_ascii=False)) <= HISTORY_TOKEN_LIMIT
    assert len(result["items"]) == 3
    for item in result["items"]:
        assert 0 < len(item["text"]) < 8000
        assert item["next_offset"] == len(item["text"]) < item["total_chars"]


@pytest.mark.parametrize("arguments", [
    {}, {"source_ids": []}, {"source_ids": ["m:0"] * 2},
    {"source_ids": ["m:0", "m:1", "m:2", "m:3"]},
    {"source_ids": ["m:-1"]}, {"source_ids": ["m:00"]}, {"source_ids": ["m:0\n"]},
    {"source_ids": ["other:m:0"]}, {"source_ids": [True]},
    {"source_ids": ["m:0"], "session_id": "other"},
    {"source_ids": ["m:0"], "run_id": "parent"},
    {"source_ids": ["m:0"], "offset": -1}, {"source_ids": ["m:0"], "offset": True},
    {"source_ids": ["m:0"], "max_chars": 0}, {"source_ids": ["m:0"], "max_chars": 8001},
])
def test_history_rejects_invalid_or_cross_scope_parameters(arguments):
    """模型不能指定身份、伪造索引格式或绕过分页边界。"""
    with pytest.raises(AppError) as caught:
        _read(_active_log(), arguments)
    assert caught.value.code == ErrorCode.VALIDATION


@pytest.mark.parametrize("source_id", ["m:1", "m:2", "m:999999"])
def test_history_rejects_current_call_and_future_sources(source_id):
    """当前助手调用及之后的来源不可回读，避免把未结算内容当成历史。"""
    with pytest.raises(AppError) as caught:
        _read(_active_log(), {"source_ids": [source_id]})
    assert caught.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize("resolved", [False, True])
def test_history_requires_an_unresolved_active_history_call(resolved):
    """无活动调用和已经结算的旧调用都不能成为读取授权边界。"""
    log = _active_log()
    if resolved:
        log.append("tool/result", {"call_id": "history-call", "name": "platform_history_read",
                                   "status": "succeeded", "content": "旧读取结果"})
    registry, context = _reader(log)
    if not resolved:
        context = ToolExecutionContext(session_id=log.session_id, user_id="actor", call_id="missing")
    with pytest.raises(AppError) as caught:
        registry.get("history.read").handler({"source_ids": ["m:0"]}, None, context)
    assert caught.value.code == ErrorCode.VALIDATION


def test_history_main_and_child_with_same_session_id_read_only_their_bound_log():
    """m:N 仅属于绑定日志，主子运行即使共享会话 ID 也不会串读。"""
    main, child = _active_log(("MAIN_ONLY",)), _active_log(("CHILD_ONLY",))
    child.run_id = "child-run"
    main_text = _read(main, {"source_ids": ["m:0"]})["items"][0]["text"]
    child_text = _read(child, {"source_ids": ["m:0"]})["items"][0]["text"]
    assert "MAIN_ONLY" in main_text and "CHILD_ONLY" not in main_text
    assert "CHILD_ONLY" in child_text and "MAIN_ONLY" not in child_text


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_history_uses_real_bridge_authorization_and_persistent_scheduler_result(allowed):
    """读取仍受执行前 ACL 复验，成功正文由现有调度器持久化并回填给模型。"""
    log = _active_log(("历史事实",))
    registry, _ = _reader(log)
    checks = []

    def context_factory(identity):
        """调用身份由调度器注入，不使用模型参数决定日志归属。"""
        return ToolExecutionContext(session_id=identity["session_id"], user_id="actor", permission_tier="tier1")

    def authorize(definition, arguments, context):
        """模拟会话权限在实际执行前被撤回。"""
        checks.append((definition.name, context.user_id))
        if not allowed:
            raise AppError(ErrorCode.UNAUTHORIZED, "会话不可见")

    bridge = PlatformToolBridge(registry, allowed_tools=["history.read"],
                                context_factory=context_factory, authorize=authorize)
    assert bridge.specs()[0].name == "platform_history_read"
    settings = SimpleNamespace(dsh_require_approval=True, dsh_max_parallel_tool_calls=2,
                               dsh_approval_timeout_seconds=.1)
    scheduler = ToolScheduler(settings, bridge.available_tools())
    messages = await scheduler.execute(
        session_id=log.session_id, log=log, turn=1, step=1, attempt_id="attempt",
        calls=[{"id": "history-call", "name": "platform_history_read", "args": {"source_ids": ["m:0"]}}],
        emit=lambda event: None, allow_dispatch=True,
    )
    assert checks and all(check == ("history.read", "actor") for check in checks)
    saved = next(event["data"] for event in log.read() if event["type"] == "tool/result")
    assert saved["content"] == messages[0]["content"]
    if allowed:
        assert saved["status"] == "succeeded"
        assert json.loads(saved["content"])["items"][0]["source_id"] == "m:0"
        assert estimate_payload_tokens(saved["content"]) <= HISTORY_TOKEN_LIMIT
    else:
        assert saved["status"] == "denied" and "历史事实" not in saved["content"]


@pytest.mark.parametrize("tier", ["tier1", "tier2", "tier3"])
def test_history_read_is_read_only_without_extra_approval(tier):
    """回读历史属于只读动作，但不替代桥接层的会话访问权限。"""
    assert decide("history.read", {}, tier) == "auto"


@pytest.mark.asyncio
@pytest.mark.parametrize("is_subagent", [False, True])
@pytest.mark.parametrize("expert", EXPERTS, ids=lambda expert: expert.expert_id)
async def test_history_real_wiring_exposes_tool_only_to_main_run(wired, monkeypatch, is_subagent, expert):
    """真实装配同时约束请求视野和调度入口，子运行不继承父日志工具。"""
    wired.session.permission_tier = "tier1"
    # 此身份替身没有提示词配置表；仍使用各专家的真实内置正文和工具声明。
    monkeypatch.setattr(loop_wiring, "get_effective_expert_prompt", lambda db, selected: selected.system_prompt)
    data = {"content": "继续检查历史", "agent_id": expert.expert_id}
    if is_subagent:
        data.update({"_subagent": True, "_subagent_workspace": str(wired.root)})
    deps, resources = await loop_wiring.build_dependencies(wired.service, wired.entry, "actor", data)
    try:
        visible = {tool.name for tool in deps.request.tools}
        assert ("platform_history_read" in visible) is not is_subagent
        assert ("platform_history_read" in deps.scheduler._by_name) is not is_subagent
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("expert", EXPERTS, ids=lambda expert: expert.expert_id)
async def test_each_main_expert_can_read_source_after_actual_compaction(wired, monkeypatch, expert):
    """每个可选主专家都能沿真实装配→摘要→工具桥→调度器回读被覆盖的原始来源。"""
    monkeypatch.setattr(loop_wiring, "get_effective_expert_prompt", lambda db, selected: selected.system_prompt)
    messages, log = conversation(), wired.entry.log
    store_messages(log, messages[:2])
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": messages[-1]["content"], "agent_id": expert.expert_id},
    )
    try:
        store_messages(log, messages)
        compact = next(resource for resource in resources if isinstance(resource, ContextCompactor))
        # 按各专家实际系统段和工具schema选阈值，避免较长专家提示恰好不触发摘要。
        budget = int(loop_wiring._prompt_tokens(deps.request) * 1.05)
        compact.context_window = budget + deps.request.max_tokens + compact.reserve
        provider = ScriptedAdapter([TextDelta("已读取历史观察，待核对具体原文 [m:1]。"), Done("stop")])
        compact.adapter = provider
        prepared = await deps.request_factory(messages, "off")

        assert len(provider.requests) == compact.calls == 1
        saved = next(event["data"] for event in log.read() if event["type"] == "context/compacted")
        assert saved["covered_messages"] == 2 and saved["source_ids"] == ["m:1"]
        assert messages[1] not in prepared.messages
        assert loop_wiring._prompt_tokens(prepared) <= budget
        assert "platform_history_read" in {tool.name for tool in prepared.tools}

        call = {"id": "compacted-source-read", "name": "platform_history_read",
                "args": {"source_ids": saved["source_ids"], "max_chars": 8000}}
        log.append("assistant/message", {"message": {"role": "assistant", "content": "", "tool_calls": [call]}})
        results = await deps.scheduler.execute(
            session_id=log.session_id, log=log, turn=2, step=1, attempt_id="after-compaction",
            calls=[call], emit=lambda event: None, allow_dispatch=True,
        )
        result = next(event["data"] for event in log.read() if event["type"] == "tool/result")
        assert result["status"] == "succeeded" and result["content"] == results[0]["content"]
        item = json.loads(result["content"])["items"][0]
        assert item["source_id"] == "m:1" and item["next_offset"] is None
        assert json.loads(item["text"]) == messages[1]
        assert estimate_payload_tokens(result["content"]) <= HISTORY_TOKEN_LIMIT
    finally:
        await wired.service._close_resources(resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_history_real_wiring_executes_bound_log_and_rechecks_actor(wired, revoked):
    """装配后的回读走真实上下文与 ACL；撤销成员资格立即阻断历史正文。"""
    log = wired.entry.log
    log.append("user/message", {"content": "装配日志独有的历史事实"})
    deps, resources = await loop_wiring.build_dependencies(
        wired.service, wired.entry, "actor", {"content": "继续检查历史"},
    )
    try:
        _append_active(log)
        wired.user.disabled = revoked
        messages = await deps.scheduler.execute(
            session_id=log.session_id, log=log, turn=1, step=1, attempt_id="wired-attempt",
            calls=[{"id": "history-call", "name": "platform_history_read", "args": {"source_ids": ["m:0"]}}],
            emit=lambda event: None, allow_dispatch=True,
        )
        saved = next(event["data"] for event in log.read() if event["type"] == "tool/result")
        assert saved["content"] == messages[0]["content"]
        if revoked:
            assert saved["status"] == "denied" and "装配日志独有的历史事实" not in saved["content"]
        else:
            assert saved["status"] == "succeeded"
            item = json.loads(saved["content"])["items"][0]
            assert json.loads(item["text"]) == {"role": "user", "content": "装配日志独有的历史事实"}
            assert estimate_payload_tokens(saved["content"]) <= HISTORY_TOKEN_LIMIT
    finally:
        await wired.service._close_resources(resources)
