"""MiMo 音频短工具：语音识别与语音合成的受控上游适配。"""

from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from ..config import settings
from ..errors import AppError, ErrorCode
from ..models import StoredFile
from .log import agent_trace
from .voiceclone import (
    REF_AUDIO_MAX_BYTES,
    _mime_for_filename,
    is_audio_file,
    persist_audio_bytes,
)

ASR_MODEL = "mimo-v2.5-asr"
TTS_MODEL = "mimo-v2.5-tts"
TTS_VOICEDESIGN_MODEL = "mimo-v2.5-tts-voicedesign"
TTS_MODELS = frozenset({TTS_MODEL, TTS_VOICEDESIGN_MODEL})
AUDIO_OUTPUT_FORMAT = "wav"
ASR_LANGUAGES = frozenset({"auto", "zh", "en"})


def _completions_url(base_url: str) -> str:
    """把 MiMo base URL 归一为 OpenAI chat/completions 地址。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AppError(ErrorCode.VALIDATION, "MiMo 音频未配置服务地址")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _audio_mime(filename: str, content_type: str | None) -> str:
    """仅接受语音克隆共用的 wav/mp3 MIME 类型。"""
    mime = (content_type or "").strip().lower()
    if mime == "audio/mp3":
        mime = "audio/mpeg"
    if mime in {"audio/wav", "audio/mpeg"}:
        return mime
    return _mime_for_filename(filename)


def _validate_audio_input(audio_bytes: bytes, audio_mime: str) -> tuple[bytes, str]:
    """校验音频非空、大小和 MIME，避免异常内容进入 Base64 请求。"""
    if not isinstance(audio_bytes, bytes | bytearray | memoryview):
        raise AppError(ErrorCode.VALIDATION, "音频不能为空")
    audio_bytes = bytes(audio_bytes)
    if not audio_bytes:
        raise AppError(ErrorCode.VALIDATION, "音频不能为空")
    if len(audio_bytes) > REF_AUDIO_MAX_BYTES:
        raise AppError(ErrorCode.VALIDATION, "音频过大，请使用不超过 7MB 的 wav/mp3")
    mime = (audio_mime or "").strip().lower()
    if mime == "audio/mp3":
        mime = "audio/mpeg"
    if mime not in {"audio/wav", "audio/mpeg"}:
        raise AppError(ErrorCode.VALIDATION, "音频须为 wav 或 mp3")
    return audio_bytes, mime


def build_asr_payload(
    *,
    audio_bytes: bytes,
    audio_mime: str,
    language: str = "auto",
    model: str = ASR_MODEL,
) -> dict[str, Any]:
    """构造 MiMo ASR 的 chat/completions 请求，不返回构造出的 Base64。"""
    audio, mime = _validate_audio_input(audio_bytes, audio_mime)
    language = (language or "auto").strip().lower()
    if language not in ASR_LANGUAGES:
        raise AppError(ErrorCode.VALIDATION, "语音识别语言仅支持 auto、zh 或 en")
    model = (model or ASR_MODEL).strip()
    if model != ASR_MODEL:
        raise AppError(ErrorCode.VALIDATION, "语音识别模型配置无效")
    encoded = base64.b64encode(audio).decode("ascii")
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": f"data:{mime};base64,{encoded}"},
                    }
                ],
            }
        ],
        "extra_body": {"asr_options": {"language": language}},
        "stream": False,
    }


def build_tts_payload(
    *,
    text: str,
    style: str = "",
    model: str = TTS_MODEL,
    voice: str | None = None,
) -> dict[str, Any]:
    """构造 MiMo TTS 请求，播报文本放 assistant、风格指令放 user。"""
    text = (text or "").strip()
    if not text:
        raise AppError(ErrorCode.VALIDATION, "请输入要合成的文本")
    style = (style or "").strip()
    model = (model or TTS_MODEL).strip()
    allowed_models = {
        str(getattr(settings, "mimo_tts_preset_model", TTS_MODEL) or TTS_MODEL).strip(),
        str(
            getattr(settings, "mimo_tts_voicedesign_model", TTS_VOICEDESIGN_MODEL)
            or TTS_VOICEDESIGN_MODEL
        ).strip(),
    }
    if model not in allowed_models or model not in TTS_MODELS:
        raise AppError(ErrorCode.VALIDATION, "语音合成模型配置无效")
    if model == TTS_VOICEDESIGN_MODEL and not style:
        raise AppError(ErrorCode.VALIDATION, "音色设计模型需要提供风格描述")
    audio: dict[str, Any] = {"format": AUDIO_OUTPUT_FORMAT}
    if model == TTS_MODEL:
        audio["voice"] = (
            voice or getattr(settings, "mimo_tts_voice", "mimo_default") or "mimo_default"
        ).strip()
    return {
        "model": model,
        "messages": [
            {"role": "user", "content": style},
            {"role": "assistant", "content": text},
        ],
        "audio": audio,
        "stream": False,
    }


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    """同步提交 JSON；测试通过替换本函数，绝不连接真实上游。"""
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict):
        raise ValueError("response is not an object")
    return payload


def _decode_audio_data(raw: object) -> bytes:
    """解析上游音频 Base64 或 data URL，并将解析失败归一化。"""
    if not isinstance(raw, str) or not raw.strip():
        raise AppError(ErrorCode.UPSTREAM, "上游未返回音频")
    encoded = raw.strip()
    if encoded.startswith("data:"):
        if "," not in encoded:
            raise AppError(ErrorCode.UPSTREAM, "上游音频数据无法解析")
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游音频数据无法解析") from exc
    if not data:
        raise AppError(ErrorCode.UPSTREAM, "上游返回空音频")
    return data


def _extract_message(payload: object) -> dict[str, Any]:
    """提取 choices[0].message，拒绝不完整的上游响应。"""
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AppError(ErrorCode.UPSTREAM, "上游响应结构异常")
    return message


def _extract_asr_text(payload: object) -> str:
    """提取 ASR 返回的 assistant 文本，不保留上游原文之外的敏感字段。"""
    message = _extract_message(payload)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
        text = "".join(parts).strip()
        if text:
            return text
    raise AppError(ErrorCode.UPSTREAM, "上游未返回识别文本")


def _extract_tts_audio(payload: object) -> bytes:
    """严格按 choices[0].message.audio.data 提取 TTS 音频。"""
    message = _extract_message(payload)
    audio = message.get("audio")
    if not isinstance(audio, dict):
        raise AppError(ErrorCode.UPSTREAM, "上游未返回音频")
    return _decode_audio_data(audio.get("data"))


def _settings_value(primary: str, fallback: str, default: str = "") -> str:
    """读取新音频配置并兼容已有音色克隆配置。"""
    value = str(getattr(settings, primary, "") or "").strip()
    return value or str(getattr(settings, fallback, default) or "").strip()


def _request_payload(payload: dict[str, Any], *, model: str, operation: str) -> dict[str, Any]:
    """调用 MiMo 并归一化网络、超时及响应错误。"""
    api_key = _settings_value("mimo_audio_api_key", "mimo_tts_api_key")
    if not api_key:
        raise AppError(ErrorCode.VALIDATION, "MiMo 音频未配置，请联系管理员")
    base_url = _settings_value("mimo_audio_base_url", "mimo_tts_base_url")
    url = _completions_url(base_url)
    timeout_s = float(getattr(settings, "mimo_audio_timeout_s", 90.0) or 90.0)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }
    agent_trace(f"MiMo {operation} 开始 model={model} timeout={int(timeout_s)}s")
    try:
        response = _post_json(url, payload, headers, timeout_s)
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.code}") from exc
    except (TimeoutError, URLError) as exc:
        reason = str(getattr(exc, "reason", exc)).lower()
        if isinstance(exc, TimeoutError) or "timed out" in reason or "timeout" in reason:
            raise AppError(ErrorCode.TIMEOUT, f"MiMo {operation}超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc
    except AppError:
        raise
    except ValueError as exc:
        raise AppError(ErrorCode.UPSTREAM, "上游响应无法解析") from exc
    except Exception as exc:
        agent_trace(f"MiMo {operation}内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "音频操作失败") from exc
    agent_trace(f"MiMo {operation}完成 model={model}")
    return response


def recognize_speech(*, audio_bytes: bytes, audio_mime: str, language: str = "auto") -> str:
    """调用 MiMo ASR，返回识别文本。"""
    model = str(getattr(settings, "mimo_asr_model", ASR_MODEL) or ASR_MODEL).strip()
    payload = build_asr_payload(audio_bytes=audio_bytes, audio_mime=audio_mime, language=language, model=model)
    return _extract_asr_text(_request_payload(payload, model=model, operation="语音识别"))


def synthesize_speech(
    *, text: str, style: str = "", model: str | None = None, voice: str | None = None
) -> bytes:
    """调用 MiMo TTS，返回 wav 二进制，不向工具结果暴露 Base64。"""
    selected_model = (
        model
        or getattr(settings, "mimo_tts_preset_model", TTS_MODEL)
        or TTS_MODEL
    ).strip()
    payload = build_tts_payload(text=text, style=style, model=selected_model, voice=voice)
    return _extract_tts_audio(_request_payload(payload, model=selected_model, operation="语音合成"))


def _stored_audio(db: Session, file_id: str, *, user_id: str) -> tuple[StoredFile, bytes, str]:
    """读取并校验当前用户的 StoredFile 音频，沿用 wav/mp3 约束。"""
    stored = (
        db.query(StoredFile)
        .filter(StoredFile.id == file_id, StoredFile.uploaded_by == user_id)
        .first()
    )
    if not stored:
        raise AppError(ErrorCode.NOT_FOUND, "音频文件不存在")
    if not is_audio_file(stored):
        raise AppError(ErrorCode.VALIDATION, "音频文件须为 wav 或 mp3")
    path = Path(stored.storage_path)
    if not path.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "音频文件不存在")
    try:
        audio, mime = _validate_audio_input(path.read_bytes(), _audio_mime(stored.filename, stored.content_type))
    except OSError as exc:
        raise AppError(ErrorCode.NOT_FOUND, "音频文件不存在") from exc
    return stored, audio, mime


def arguments_for_speech_recognition(db: Session, *, text: str, attachments: list[str]) -> dict[str, str]:
    """从本轮附件绑定 ASR 文件，禁止模型伪造文件 ID。"""
    ids = [item for item in attachments if isinstance(item, str) and item]
    rows = db.query(StoredFile).filter(StoredFile.id.in_(ids)).all() if ids else []
    by_id = {row.id: row for row in rows}
    audio_ids = [item for item in ids if is_audio_file(by_id.get(item))]
    return {"file_id": audio_ids[-1] if audio_ids else "", "language": "auto"}


def arguments_for_speech_synthesis(*, text: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """绑定 TTS 文本、模式、风格和受控模型参数。"""
    args = dict(arguments or {})
    mode = str(args.get("mode") or "preset").strip().lower()
    if mode not in {"preset", "voicedesign"}:
        raise AppError(ErrorCode.VALIDATION, "语音合成模式仅支持 preset 或 voicedesign")
    default_model = (
        getattr(settings, "mimo_tts_voicedesign_model", TTS_VOICEDESIGN_MODEL)
        if mode == "voicedesign"
        else getattr(settings, "mimo_tts_preset_model", TTS_MODEL)
    )
    model = str(args.get("model") or default_model or "").strip()
    return {
        "text": str(args.get("text") or text or "").strip(),
        "mode": mode,
        "style": str(args.get("style") or "").strip(),
        "model": model,
        "voice": str(args.get("voice") or "").strip(),
    }


def execute_speech_recognition(db: Session, arguments: dict[str, Any] | None, *, user_id: str) -> dict[str, Any]:
    """读取 StoredFile 执行 ASR，仅返回文本和安全元数据。"""
    args = arguments if isinstance(arguments, dict) else {}
    file_id = str(args.get("file_id") or "").strip()
    if not file_id:
        raise AppError(ErrorCode.VALIDATION, "请上传 wav 或 mp3 音频")
    stored, audio, mime = _stored_audio(db, file_id, user_id=user_id)
    language = str(args.get("language") or "auto").strip().lower()
    text = recognize_speech(audio_bytes=audio, audio_mime=mime, language=language)
    return {
        "text": text,
        "language": language,
        "file_id": file_id,
    }


def execute_speech_synthesis(db: Session, arguments: dict[str, Any] | None, *, user_id: str) -> dict[str, Any]:
    """执行 TTS 并持久化音频，只返回 StoredFile 元数据。"""
    args = arguments if isinstance(arguments, dict) else {}
    text = str(args.get("text") or "").strip()
    style = str(args.get("style") or "").strip()
    mode = str(args.get("mode") or "preset").strip().lower()
    if mode not in {"preset", "voicedesign"}:
        raise AppError(ErrorCode.VALIDATION, "语音合成模式仅支持 preset 或 voicedesign")
    default_model = (
        getattr(settings, "mimo_tts_voicedesign_model", TTS_VOICEDESIGN_MODEL)
        if mode == "voicedesign"
        else getattr(settings, "mimo_tts_preset_model", TTS_MODEL)
    )
    model = str(args.get("model") or default_model or "").strip()
    voice = str(args.get("voice") or "").strip() or None
    audio = synthesize_speech(text=text, style=style, model=model, voice=voice)
    out = persist_audio_bytes(
        db,
        filename="speech_synthesis.wav",
        content=audio,
        content_type="audio/wav",
        user_id=user_id,
    )
    return {
        "file_id": out.id,
        "filename": out.filename,
        "content_type": out.content_type,
        "size": out.size_bytes,
        "model": model,
        "mode": mode,
        "content_url": f"/api/files/{out.id}/content",
    }


# 兼容执行器的统一命名，同时保留清晰的领域函数名供单测调用。
speech_recognition = execute_speech_recognition
speech_synthesis = execute_speech_synthesis
recognize_audio = recognize_speech
synthesize_audio = synthesize_speech
