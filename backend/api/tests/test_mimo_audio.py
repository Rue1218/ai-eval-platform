"""MiMo 音频工具单测：只验证请求、解析、落盘与注册绑定，不连接上游。"""

from __future__ import annotations

import base64

import pytest

from app.agent.mcp_registry import bind_tool_arguments, execute_registered_tool
from app.agent.mimo_audio import (
    TTS_MODEL,
    TTS_VOICEDESIGN_MODEL,
    build_asr_payload,
    build_tts_payload,
    execute_speech_recognition,
    execute_speech_synthesis,
    recognize_speech,
    synthesize_speech,
)
from app.errors import AppError, ErrorCode
from app.models import StoredFile


class _Query:
    def __init__(self, row: StoredFile | None):
        self.row = row

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.row

    def all(self):
        return [self.row] if self.row else []


class _Db:
    def __init__(self, row: StoredFile | None = None):
        self.row = row
        self.added: list[StoredFile] = []

    def query(self, *_args, **_kwargs):
        return _Query(self.row)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, _item):
        pass


def test_build_asr_payload_uses_audio_data_url_and_language():
    payload = build_asr_payload(audio_bytes=b"wav", audio_mime="audio/wav", language="zh")

    content = payload["messages"][0]["content"][0]
    assert payload["model"] == "mimo-v2.5-asr"
    assert content["type"] == "input_audio"
    assert content["input_audio"]["data"] == "data:audio/wav;base64,d2F2"
    assert payload["extra_body"]["asr_options"]["language"] == "zh"


def test_build_tts_payload_places_style_before_assistant_text():
    payload = build_tts_payload(text="你好", style="温柔自然", voice="Mia")

    assert payload["model"] == TTS_MODEL
    assert payload["messages"] == [
        {"role": "user", "content": "温柔自然"},
        {"role": "assistant", "content": "你好"},
    ]
    assert payload["audio"] == {"format": "wav", "voice": "Mia"}


def test_build_voicedesign_payload_requires_style_and_omits_voice():
    payload = build_tts_payload(text="你好", style="年轻男声", model=TTS_VOICEDESIGN_MODEL)
    assert payload["model"] == TTS_VOICEDESIGN_MODEL
    assert payload["audio"] == {"format": "wav"}

    with pytest.raises(AppError) as exc:
        build_tts_payload(text="你好", model=TTS_VOICEDESIGN_MODEL)
    assert exc.value.code == ErrorCode.VALIDATION


def test_provider_parses_asr_and_tts_without_real_call(monkeypatch):
    captured: list[dict] = []
    encoded = base64.b64encode(b"synth").decode()

    def fake_post(_url, body, _headers, _timeout):
        captured.append(body)
        if body["model"] == "mimo-v2.5-asr":
            return {"choices": [{"message": {"content": "识别结果"}}]}
        return {"choices": [{"message": {"audio": {"data": encoded}}}]}

    monkeypatch.setattr("app.agent.mimo_audio._post_json", fake_post)
    monkeypatch.setattr("app.agent.mimo_audio.settings.mimo_audio_api_key", "test-key")
    assert recognize_speech(audio_bytes=b"wav", audio_mime="audio/wav") == "识别结果"
    assert synthesize_speech(text="你好") == b"synth"
    assert "test-key" not in str(captured)
    assert encoded not in str({"text": "识别结果"})


def test_provider_normalizes_malformed_response_and_missing_config(monkeypatch):
    monkeypatch.setattr("app.agent.mimo_audio.settings.mimo_audio_api_key", "test-key")
    monkeypatch.setattr("app.agent.mimo_audio._post_json", lambda *_args: {"choices": []})
    with pytest.raises(AppError) as exc:
        recognize_speech(audio_bytes=b"wav", audio_mime="audio/wav")
    assert exc.value.code == ErrorCode.UPSTREAM
    monkeypatch.setattr("app.agent.mimo_audio.settings.mimo_audio_api_key", "")
    monkeypatch.setattr("app.agent.mimo_audio.settings.mimo_tts_api_key", "")
    with pytest.raises(AppError) as exc:
        synthesize_speech(text="你好")
    assert exc.value.code == ErrorCode.VALIDATION


def test_execute_asr_reads_stored_file_and_returns_metadata_only(tmp_path, monkeypatch):
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF audio")
    row = StoredFile(
        id="ref-1",
        filename="ref.wav",
        content_type="audio/wav",
        size_bytes=10,
        sha256="a" * 64,
        storage_path=str(path),
        kind="wav",
        uploaded_by="u1",
    )
    monkeypatch.setattr("app.agent.mimo_audio.recognize_speech", lambda **_kwargs: "你好")
    result = execute_speech_recognition(_Db(row), {"file_id": row.id, "language": "zh"}, user_id="u1")
    assert result == {"text": "你好", "language": "zh", "file_id": row.id}
    assert "data" not in result


def test_execute_tts_persists_only_file_metadata(tmp_path, monkeypatch):
    db = _Db()
    monkeypatch.setattr("app.agent.mimo_audio.settings.data_dir", str(tmp_path))
    monkeypatch.setattr("app.agent.mimo_audio.synthesize_speech", lambda **_kwargs: b"wav-output")
    result = execute_speech_synthesis(db, {"text": "你好"}, user_id="u1")

    assert result["filename"] == "speech_synthesis.wav"
    assert result["content_type"] == "audio/wav"
    assert result["size"] == len(b"wav-output")
    assert "data" not in result
    assert (tmp_path / "files" / result["file_id"]).read_bytes() == b"wav-output"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"audio_bytes": b"", "audio_mime": "audio/wav"}, "不能为空"),
        ({"audio_bytes": b"audio", "audio_mime": "text/plain"}, "wav 或 mp3"),
    ],
)
def test_audio_input_validation(kwargs, message):
    with pytest.raises(AppError) as exc:
        build_asr_payload(**kwargs)
    assert exc.value.code == ErrorCode.VALIDATION
    assert message in exc.value.message


def test_registry_binds_audio_files_and_executes_tts(monkeypatch, tmp_path):
    path = tmp_path / "in.mp3"
    path.write_bytes(b"mp3")
    row = StoredFile(
        id="ref-2",
        filename="in.mp3",
        content_type="audio/mpeg",
        size_bytes=3,
        sha256="b" * 64,
        storage_path=str(path),
        kind="mp3",
        uploaded_by="u1",
    )
    db = _Db(row)
    bound_asr = bind_tool_arguments(
        db, "audio.speech_recognition", {"language": "en"}, text="", attachments=[row.id]
    )
    assert bound_asr == {"file_id": row.id, "language": "en"}
    bound_tts = bind_tool_arguments(
        db,
        "audio.speech_synthesis",
        {"style": "播音腔", "model": TTS_VOICEDESIGN_MODEL},
        text="欢迎",
        attachments=[],
    )
    assert bound_tts["text"] == "欢迎"
    assert bound_tts["style"] == "播音腔"
    monkeypatch.setattr("app.agent.mimo_audio.synthesize_speech", lambda **_kwargs: b"out")
    monkeypatch.setattr("app.agent.mimo_audio.settings.data_dir", str(tmp_path / "data"))
    result = execute_registered_tool(db, "audio.speech_synthesis", bound_tts, user_id="u1")
    assert result["file_id"]
    assert result["model"] == TTS_VOICEDESIGN_MODEL
