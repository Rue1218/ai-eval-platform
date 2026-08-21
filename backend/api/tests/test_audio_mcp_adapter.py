"""可注入音频 MCP Adapter 单测：不连接真实 MCP Server。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agent.audio_mcp_adapter import (
    AudioMcpRequest,
    AudioMcpResponse,
    normalize_request,
    normalize_response,
    synthesize_via_mcp,
)
from app.errors import AppError, ErrorCode


@dataclass
class _Transport:
    result: object

    def __post_init__(self):
        self.calls: list[tuple[AudioMcpRequest, float]] = []

    def invoke(self, request: AudioMcpRequest, *, timeout_s: float) -> object:
        self.calls.append((request, timeout_s))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_normalize_request_converts_bytes_like_and_trims_values():
    request = normalize_request(
        ref_bytes=bytearray(b"reference"),
        ref_mime=" Audio/WAV ",
        text="  欢迎使用  ",
        style=" 温柔  ",
    )

    assert request == AudioMcpRequest(
        ref_bytes=b"reference",
        ref_mime="audio/wav",
        text="欢迎使用",
        style="温柔",
    )


def test_synthesize_passes_typed_request_and_timeout():
    transport = _Transport(b"generated-audio")

    result = synthesize_via_mcp(
        ref_bytes=memoryview(b"reference"),
        ref_mime="audio/mpeg",
        text="欢迎使用",
        transport=transport,
        timeout_s=12,
    )

    assert result == b"generated-audio"
    assert transport.calls == [
        (
            AudioMcpRequest(
                ref_bytes=b"reference",
                ref_mime="audio/mpeg",
                text="欢迎使用",
                style="",
            ),
            12.0,
        )
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"ref_bytes": b"", "ref_mime": "audio/wav", "text": "朗读"}, "参考音频"),
        ({"ref_bytes": b"ref", "ref_mime": "audio/wav", "text": "  "}, "请输入"),
        ({"ref_bytes": b"ref", "ref_mime": "", "text": "朗读"}, "MIME"),
        ({"ref_bytes": b"ref", "ref_mime": "text/plain", "text": "朗读"}, "音频 MIME"),
        ({"ref_bytes": b"ref", "ref_mime": "audio/wav", "text": "朗读", "style": 1}, "风格"),
    ],
)
def test_synthesize_validates_request_before_transport(kwargs, message):
    transport = _Transport(b"should-not-be-used")

    with pytest.raises(AppError) as exc:
        synthesize_via_mcp(**kwargs, transport=transport)

    assert exc.value.code == ErrorCode.VALIDATION
    assert message in exc.value.message
    assert transport.calls == []


def test_synthesize_rejects_invalid_timeout():
    transport = _Transport(b"should-not-be-used")

    with pytest.raises(AppError) as exc:
        synthesize_via_mcp(
            ref_bytes=b"ref",
            ref_mime="audio/wav",
            text="朗读",
            transport=transport,
            timeout_s=0,
        )

    assert exc.value.code == ErrorCode.VALIDATION
    assert transport.calls == []


@pytest.mark.parametrize("value", [b"", bytearray(), memoryview(b"")])
def test_normalize_response_rejects_empty_audio(value):
    with pytest.raises(AppError) as exc:
        normalize_response(value)

    assert exc.value.code == ErrorCode.UPSTREAM


def test_normalize_response_accepts_typed_result_and_normalizes_bytes_like():
    result = normalize_response(AudioMcpResponse(bytearray(b"audio"), " Audio/WAV "))

    assert result == AudioMcpResponse(data=b"audio", mime_type="audio/wav")


def test_normalize_response_rejects_unknown_mapping_shape():
    with pytest.raises(AppError) as exc:
        normalize_response({"audio": "base64-value"})

    assert exc.value.code == ErrorCode.UPSTREAM


def test_normalize_response_rejects_non_string_mime_type():
    with pytest.raises(AppError) as exc:
        normalize_response(AudioMcpResponse(b"audio", mime_type=123))

    assert exc.value.code == ErrorCode.UPSTREAM


def test_synthesize_maps_timeout_without_leaking_details():
    secret = "private-audio-payload"
    transport = _Transport(TimeoutError(secret))

    with pytest.raises(AppError) as exc:
        synthesize_via_mcp(
            ref_bytes=b"ref",
            ref_mime="audio/wav",
            text="朗读",
            transport=transport,
        )

    assert exc.value.code == ErrorCode.TIMEOUT
    assert secret not in exc.value.message


def test_synthesize_maps_connection_error_without_leaking_details():
    secret = "https://private.example.test"
    transport = _Transport(OSError(secret))

    with pytest.raises(AppError) as exc:
        synthesize_via_mcp(
            ref_bytes=b"ref",
            ref_mime="audio/wav",
            text="朗读",
            transport=transport,
        )

    assert exc.value.code == ErrorCode.UPSTREAM
    assert secret not in exc.value.message


def test_synthesize_preserves_app_error():
    original = AppError(ErrorCode.VALIDATION, "provider rejected input")
    transport = _Transport(original)

    with pytest.raises(AppError) as exc:
        synthesize_via_mcp(
            ref_bytes=b"ref",
            ref_mime="audio/wav",
            text="朗读",
            transport=transport,
        )

    assert exc.value is original


def test_synthesize_maps_unexpected_error_without_leaking_details():
    secret = "secret-response-body"
    transport = _Transport(RuntimeError(secret))

    with pytest.raises(AppError) as exc:
        synthesize_via_mcp(
            ref_bytes=b"ref",
            ref_mime="audio/wav",
            text="朗读",
            transport=transport,
        )

    assert exc.value.code == ErrorCode.INTERNAL
    assert secret not in exc.value.message
