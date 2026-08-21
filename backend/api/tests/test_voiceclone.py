"""音色克隆短工具与规划注入单测（不连真实 MIMO）。"""

from __future__ import annotations

import asyncio
import base64

import pytest

from app.agent.mcp_tools import collect_ids, execute_short_tool
from app.agent.plan import PlanArtifact, TurnBudget, l0_plan, run_plan
from app.agent.react import run_react
from app.agent.slash import parse_slash
from app.agent.voiceclone import (
    _completions_url,
    _decode_audio_b64,
    arguments_for_voiceclone,
    inject_voiceclone_plan,
)
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.trace import TraceContext
from app.models import StoredFile
from app.routers.files import _validate_filename


def _turn_ctx() -> dict:
    """阶段 2：测试夹具必须显式构造同一 Turn 的 trace/cancel。"""
    trace = TraceContext.for_turn()
    return {"trace": trace, "cancel": CancellationToken(turn_id=trace.turn_id)}


class _AudioQuery:
    def __init__(self, row: StoredFile | None):
        self.row = row

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.row

    def all(self):
        return [self.row] if self.row else []


class _AudioDb:
    def __init__(self, row: StoredFile | None = None):
        self.row = row
        self.added: list = []

    def query(self, *_args, **_kwargs):
        return _AudioQuery(self.row)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, item):
        return item


def _wav_row(tmp_path, *, file_id: str = "f-ref") -> StoredFile:
    path = tmp_path / file_id
    path.write_bytes(b"RIFF....WAVEfmt ")
    return StoredFile(
        id=file_id,
        filename="ref.wav",
        content_type="audio/wav",
        size_bytes=path.stat().st_size,
        sha256="a" * 64,
        storage_path=str(path),
        kind="wav",
        uploaded_by="u1",
    )


def test_validate_filename_allows_wav_mp3():
    assert _validate_filename("a.wav") == "a.wav"
    assert _validate_filename("b.MP3") == "b.MP3"
    with pytest.raises(AppError) as exc:
        _validate_filename("c.exe")
    assert exc.value.code == ErrorCode.VALIDATION


def test_completions_url_normalizes_v1_base():
    assert _completions_url("https://example.com/v1") == "https://example.com/v1/chat/completions"
    assert (
        _completions_url("https://example.com/v1/chat/completions")
        == "https://example.com/v1/chat/completions"
    )


def test_decode_audio_strips_data_uri():
    raw = base64.b64encode(b"wav-bytes").decode("ascii")
    assert _decode_audio_b64(f"data:audio/wav;base64,{raw}") == b"wav-bytes"
    assert _decode_audio_b64(raw) == b"wav-bytes"


def test_inject_voiceclone_when_audio_and_text(tmp_path):
    row = _wav_row(tmp_path)
    plan = l0_plan("用这个声音说欢迎使用评测平台")
    out = inject_voiceclone_plan(_AudioDb(row), plan, text="用这个声音说欢迎使用评测平台", attachments=[row.id])
    assert out.intent == "chat"
    assert out.delivery == "text"
    assert out.tools_needed == ["audio.voiceclone"]


def test_inject_voiceclone_clarify_without_text(tmp_path):
    row = _wav_row(tmp_path)
    plan = l0_plan("")
    out = inject_voiceclone_plan(_AudioDb(row), plan, text="", attachments=[row.id])
    assert out.delivery == "clarify"
    assert out.tools_needed == []
    assert "参考音频" in out.notes


def test_inject_voiceclone_clarify_without_audio():
    plan = l0_plan("帮我克隆音色朗读这段话")
    out = inject_voiceclone_plan(_AudioDb(None), plan, text="帮我克隆音色朗读这段话", attachments=[])
    assert out.delivery == "clarify"
    assert "wav" in out.notes


def test_inject_skips_real_benchmark(tmp_path):
    row = _wav_row(tmp_path)
    plan = l0_plan("帮我评一下这两个模型")
    out = inject_voiceclone_plan(_AudioDb(row), plan, text="帮我评一下这两个模型", attachments=[row.id])
    assert out.intent == "benchmark"
    assert "audio.voiceclone" not in out.tools_needed


def test_run_plan_greeting_with_audio_injects_tool(tmp_path, monkeypatch):
    row = _wav_row(tmp_path)

    def _boom(*_a, **_k):
        raise AssertionError("自然语言不得打独立规划模型")

    monkeypatch.setattr("app.agent.plan._call_plan_model", _boom)
    plan = run_plan(
        _AudioDb(row),
        text="你好",
        parsed=parse_slash("你好"),
        history=[],
        prefs={},
        attachments=[row.id],
        budget=TurnBudget(),
    )
    assert plan.intent == "chat"
    assert plan.tools_needed == ["audio.voiceclone"]
    assert plan.loop == "react"


def test_execute_voiceclone_persists_file_without_audio_payload(tmp_path, monkeypatch):
    row = _wav_row(tmp_path)
    monkeypatch.setattr("app.agent.voiceclone.settings.data_dir", str(tmp_path / "data"))
    monkeypatch.setattr("app.agent.voiceclone.synthesize_wav", lambda **_kwargs: b"SYNTH-WAV")

    ok, data, error, _latency = execute_short_tool(
        _AudioDb(row),
        "audio.voiceclone",
        {"text": "欢迎使用", "file_id": row.id},
        user_id="u1",
    )
    assert ok is True
    assert error is None
    assert data["filename"] == "voiceclone.wav"
    assert data["content_url"].endswith("/content")
    assert "data" not in data
    assert collect_ids(data) == [data["file_id"]]
    saved = (tmp_path / "data" / "files" / data["file_id"]).read_bytes()
    assert saved == b"SYNTH-WAV"


def test_execute_voiceclone_requires_config(monkeypatch):
    monkeypatch.setattr("app.agent.voiceclone.settings.mimo_tts_api_key", "")
    with pytest.raises(AppError) as exc:
        from app.agent.voiceclone import synthesize_wav

        synthesize_wav(ref_bytes=b"abc", ref_mime="audio/wav", text="hi")
    assert exc.value.code == ErrorCode.VALIDATION


def test_run_react_passes_voiceclone_arguments(tmp_path, monkeypatch):
    row = _wav_row(tmp_path)
    captured: dict = {}

    def _fake_isolated(name, arguments, user_id):
        captured["name"] = name
        captured["arguments"] = arguments
        captured["user_id"] = user_id
        return True, {"file_id": "out-1", "content_url": "/api/files/out-1/content"}, None, 12

    monkeypatch.setattr("app.agent.react._execute_short_tool_isolated", _fake_isolated)
    plan = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=["audio.voiceclone"],
        delivery="text",
        budget={"max_tool_rounds": 1},
        notes="规划：配音",
        source="l0",
    )
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return len(events)

    asyncio.run(
        run_react(
            _AudioDb(row),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            text="欢迎使用",
            attachments=[row.id],
            **_turn_ctx(),
        )
    )
    assert captured["arguments"]["text"] == "欢迎使用"
    assert captured["arguments"]["file_id"] == row.id
    assert events[0][0] == "thought"
    assert events[0][1].get("stage") == "react"
    assert events[1][0] == "tool_call"
    assert events[1][1]["arguments"]["file_id"] == row.id
    assert arguments_for_voiceclone(_AudioDb(row), text="欢迎使用", attachments=[row.id])["file_id"] == row.id
