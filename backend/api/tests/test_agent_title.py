"""会话标题 AI 生成测试：结构化输出解析、兜底链路与 WS 触发编排。"""

import asyncio

import pytest

from app.adapters import AdapterResult
from app.agent import title as title_mod
from app.errors import AppError, ErrorCode
from app.models import Session as AgentSession
from app.routers import ws


def test_fallback_title_collapses_and_truncates():
    """兜底标题：压缩空白并按 18 字截断。"""
    assert title_mod.fallback_title("  帮我\n对 MMLU 数据集 跑基准评测  ") == "帮我 对 MMLU 数据集 跑基准评"
    assert title_mod.fallback_title("") == ""
    assert title_mod.fallback_title("   ") == ""


def test_extract_title_plain_and_fenced():
    """解析管线：裸 JSON 与代码围栏包裹均可提取。"""
    assert title_mod.extract_title_payload('{"title": "MMLU 基准评测"}') == "MMLU 基准评测"
    fenced = "```json\n{\"title\": \"RAG 知识库评估\"}\n```"
    assert title_mod.extract_title_payload(fenced) == "RAG 知识库评估"


def test_extract_title_tolerates_prose_and_quotes():
    """容忍前后解释文字与成对包裹引号；非成对符号原样保留。"""
    # 前后解释文字不干扰 JSON 截取；「」非成对引号表成员，原样保留
    noisy = '好的，结果如下：{"title": "PRD 分析总结"} 请查收'
    assert title_mod.extract_title_payload(noisy) == "PRD 分析总结"
    # 中文成对引号剥离
    assert title_mod.extract_title_payload('{"title": "\u201c压测报告生成\u201d"}') == "压测报告生成"


def test_extract_title_clamps_overlong():
    """超长标题按 40 字硬截断。"""
    raw = '{"title": "' + "长" * 60 + '"}'
    assert title_mod.extract_title_payload(raw) == "长" * 40


@pytest.mark.parametrize(
    "raw",
    [
        "没有 JSON 的普通回答",
        '{"name": "字段名不对"}',
        '{"title": "   "}',
        "[]",
        "",
    ],
)
def test_extract_title_contract_violations_raise(raw):
    """契约不符一律抛 ValueError，由调用方回退消息截断。"""
    with pytest.raises(ValueError):
        title_mod.extract_title_payload(raw)


@pytest.mark.asyncio
async def test_generate_title_uses_model_payload(monkeypatch):
    """模型返回合法结构化输出时直接采用。"""

    def fake_call(db, system, user, **_kwargs):
        assert "会话命名助手" in system
        return AdapterResult(text='{"title": "数据集基准评测"}', usage={}, raw={}, latency_ms=5)

    monkeypatch.setattr(title_mod, "call_agent_model", fake_call)
    assert await title_mod.generate_title_text("帮我评测数据集") == "数据集基准评测"


@pytest.mark.asyncio
async def test_generate_title_falls_back_on_bad_json(monkeypatch):
    """模型输出契约不符时回退为消息截断。"""

    def fake_call(db, system, user, **_kwargs):
        return AdapterResult(text="抱歉我不明白", usage={}, raw={}, latency_ms=5)

    monkeypatch.setattr(title_mod, "call_agent_model", fake_call)
    assert await title_mod.generate_title_text("帮我评测数据集好不好") == "帮我评测数据集好不好"


@pytest.mark.asyncio
async def test_generate_title_falls_back_on_upstream_error(monkeypatch):
    """协议档未配置 / 上游异常时降级为消息截断，不向外抛错。"""

    def fake_call(db, system, user, **_kwargs):
        raise AppError(ErrorCode.VALIDATION, "尚未配置 Agent 协议档")

    monkeypatch.setattr(title_mod, "call_agent_model", fake_call)
    assert await title_mod.generate_title_text("压测一下网关接口") == "压测一下网关接口"


@pytest.mark.asyncio
async def test_generate_title_empty_text_skips_model(monkeypatch):
    """空消息不调模型，直接返回空标题。"""

    def fake_call(db, system, user, **_kwargs):
        raise AssertionError("空消息不应调用模型")

    monkeypatch.setattr(title_mod, "call_agent_model", fake_call)
    assert await title_mod.generate_title_text("   ") == ""


class _TitleDb:
    """最小数据库桩：只支持标题行锁查询与提交。"""

    def __init__(self, row) -> None:
        self._row = row
        self.committed = False

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._row

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_schedule_title_generates_and_emits(monkeypatch):
    """默认标题会话收到首条消息后生成标题、落库并广播 session_title。"""
    session = AgentSession(id="s-1", user_id="u-1", title="新会话", visibility="private")
    row = AgentSession(id="s-1", user_id="u-1", title="新会话", visibility="private")
    emitted: list[tuple[str, dict]] = []

    async def fake_generate(text: str) -> str:
        assert text == "帮我评测 MMLU 数据集"
        return "MMLU 基准评测"

    async def fake_emit(_db, _websocket, _state, session_id, event, payload):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "SessionLocal", lambda: _TitleDb(row))
    monkeypatch.setattr(ws, "generate_title_text", fake_generate)
    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_TITLE_GENERATING", set())

    ws._maybe_schedule_title(session, object(), ws._ConnectionState(), "帮我评测 MMLU 数据集")
    for _ in range(10):
        await asyncio.sleep(0)
    assert row.title == "MMLU 基准评测"
    assert emitted and emitted[0][0] == "session_title"
    assert emitted[0][1] == {"title": "MMLU 基准评测", "source": "ai"}
    assert "s-1" not in ws._TITLE_GENERATING


@pytest.mark.asyncio
async def test_schedule_title_skips_custom_title(monkeypatch):
    """非默认标题（用户已改名或已生成）不再触发。"""
    session = AgentSession(id="s-2", user_id="u-1", title="自定义标题", visibility="private")

    def fail_session_local():
        raise AssertionError("非默认标题不应建数据库连接")

    monkeypatch.setattr(ws, "SessionLocal", fail_session_local)
    monkeypatch.setattr(ws, "_TITLE_GENERATING", set())
    ws._maybe_schedule_title(session, object(), ws._ConnectionState(), "新消息")
    await asyncio.sleep(0)
    assert session.title == "自定义标题"


@pytest.mark.asyncio
async def test_schedule_title_keeps_renamed_row(monkeypatch):
    """生成期间标题已被他人改掉时放弃写入，不覆盖用户命名。"""
    session = AgentSession(id="s-3", user_id="u-1", title="新会话", visibility="private")
    row = AgentSession(id="s-3", user_id="u-1", title="用户已改名", visibility="private")
    emitted: list[tuple[str, dict]] = []

    async def fake_generate(text: str) -> str:
        return "AI 生成的标题"

    async def fake_emit(_db, _websocket, _state, _session_id, event, payload):
        emitted.append((event, payload))
        return True

    monkeypatch.setattr(ws, "SessionLocal", lambda: _TitleDb(row))
    monkeypatch.setattr(ws, "generate_title_text", fake_generate)
    monkeypatch.setattr(ws, "_emit_persistent", fake_emit)
    monkeypatch.setattr(ws, "_TITLE_GENERATING", set())

    ws._maybe_schedule_title(session, object(), ws._ConnectionState(), "首条消息")
    for _ in range(10):
        await asyncio.sleep(0)
    assert row.title == "用户已改名"
    assert not emitted
