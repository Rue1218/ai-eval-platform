"""语音合成短工具：文本 → MIMO TTS；有参考音则克隆，否则用内置音色。

上游走 OpenAI 兼容 ``POST {base}/chat/completions``。无附件时模型默认
``mimo-v2.5-tts``（``audio.voice=mimo_default``）；有 wav/mp3 时用
``mimo-v2.5-tts-voiceclone``。禁止把 API Key、参考音频或合成音频的
base64 写入 ``agent_trace`` / 工具观察。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from ..config import settings
from ..errors import AppError, ErrorCode
from ..models import StoredFile, uuid_str
from .log import agent_trace

# 参考音频扩展名（与 files 白名单、MIMO 文档一致）
AUDIO_SUFFIXES = {".wav", ".mp3"}
AUDIO_KINDS = frozenset({"wav", "mp3", "mpeg"})
# 编码后上限 10MB：原始约 7.5MB；略收紧避免网关拒收
REF_AUDIO_MAX_BYTES = 7 * 1024 * 1024
OUTPUT_FORMAT = "wav"

_EVAL_KEEP_HINTS = (
    "benchmark",
    "评测",
    "评估",
    "对比",
    "跑分",
    "打分",
    "测试模型",
    "模型质量",
    "评一下",
    "帮我评",
    "prd",
    "用例",
    "测试用例",
    "生成用例",
    "rag",
    "知识库",
    "检索",
    "召回",
    "lightrag",
    "黄金",
    "压测",
    "加压",
    "先评后压",
)
# 无附件时仍要求参考音（克隆口令）
_CLONE_ONLY_HINTS = (
    "克隆",
    "音色",
    "voiceclone",
    "voice clone",
    "参考音频",
    "用这",
)
# 纯文本即可合成
_TTS_HINTS = (
    "配音",
    "朗读",
    "输出音频",
    "生成音频",
    "生成语音",
    "合成语音",
    "文字转语音",
    "语音合成",
    "输出语音",
    "转成语音",
    "转成音频",
    "读出来",
    "念出来",
    "播报",
    "tts",
)
_COMMAND_PREFIXES = (
    "帮我输出音频",
    "请输出音频",
    "帮我生成音频",
    "请生成音频",
    "帮我生成语音",
    "生成一段音频",
    "生成音频",
    "输出音频",
    "帮我朗读一下",
    "帮我朗读",
    "请朗读",
    "朗读一下",
    "帮我读出来",
    "文字转语音",
    "语音合成",
    "合成语音",
    "输出语音",
    "转成语音",
    "转成音频",
    "朗读",
)
_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'))
_PLACEHOLDER_SPEAK = frozenset({"这段话", "这段文字", "一下", "吧"})
_SKIP_INTENTS = frozenset({"cancel", "rerun", "compact", "report"})
_EVAL_INTENTS = frozenset({"benchmark", "rag", "testcase"})


def is_audio_filename(filename: str | None) -> bool:
    """文件名是否为 wav/mp3。"""
    return Path(filename or "").suffix.lower() in AUDIO_SUFFIXES


def is_audio_file(row: StoredFile | None) -> bool:
    """元数据是否指向可作参考音的 wav/mp3。"""
    if row is None:
        return False
    kind = (row.kind or "").lower().lstrip(".")
    if kind in AUDIO_KINDS:
        return True
    return is_audio_filename(row.filename)


def _mime_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    return "audio/wav"


def list_audio_file_ids(db: Session, attachments: list[str]) -> list[str]:
    """按本轮附件顺序筛出 wav/mp3 的 file_id。"""
    ids = [fid for fid in attachments if isinstance(fid, str) and fid]
    if not ids:
        return []
    rows = db.query(StoredFile).filter(StoredFile.id.in_(ids)).all()
    by_id = {row.id: row for row in rows}
    return [fid for fid in ids if is_audio_file(by_id.get(fid))]


def pick_audio_file_id(db: Session, attachments: list[str], preferred: str | None = None) -> str:
    """优先用入参 file_id（须在本轮附件且为音频），否则取本轮最后一段参考音。"""
    audio_ids = list_audio_file_ids(db, attachments)
    if preferred and preferred in audio_ids:
        return preferred
    return audio_ids[-1] if audio_ids else ""


def extract_tts_text(text: str) -> str:
    """从用户原话抽出朗读稿：引号 / 冒号之后 / 去掉「帮我输出音频」一类前缀。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    for left, right in _QUOTE_PAIRS:
        start = raw.find(left)
        if start < 0:
            continue
        end = raw.find(right, start + len(left))
        if end > start + len(left):
            inner = raw[start + len(left) : end].strip()
            if inner:
                return inner
    for sep in ("：", ":"):
        if sep in raw:
            after = raw.split(sep, 1)[1].strip()
            if after:
                return after
    leftover = raw
    lowered = leftover.lower()
    for prefix in _COMMAND_PREFIXES:
        if lowered.startswith(prefix.lower()):
            leftover = leftover[len(prefix) :].lstrip("，,。 !！")
            break
    leftover = leftover.strip()
    if leftover in _PLACEHOLDER_SPEAK:
        return ""
    return leftover


def arguments_for_voiceclone(
    db: Session,
    *,
    text: str,
    attachments: list[str],
    preferred_file_id: str | None = None,
) -> dict[str, str]:
    """由本轮原文与附件组装工具入参，禁止模型编造 file_id。"""
    speak = extract_tts_text(text) or (text or "").strip()
    args: dict[str, str] = {"text": speak}
    file_id = pick_audio_file_id(db, attachments, preferred_file_id)
    if file_id:
        args["file_id"] = file_id
    return args


def _looks_like_eval(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _EVAL_KEEP_HINTS)


def _looks_like_clone(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _CLONE_ONLY_HINTS)


def _looks_like_tts(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _TTS_HINTS)


def _mark_audio_plan(plan: Any, *, notes: str) -> Any:
    """改走 chat 交付，只保留语音合成短工具。"""
    plan.intent = "chat"
    plan.skill_id = None
    plan.tools_needed = ["audio.voiceclone"]
    plan.delivery = "text"
    plan.slots = {"filled": {}, "missing": []}
    plan.notes = notes
    return plan


def inject_voiceclone_plan(
    db: Session,
    plan: Any,
    *,
    text: str,
    attachments: list[str],
) -> Any:
    """自然语言回合：纯文本可走内置音色；有参考音则克隆。

    斜杠评测路径不要调用本函数。无附件却说「克隆音色」时仍澄清要上传参考音。
    """
    audio_ids = list_audio_file_ids(db, attachments)
    if plan.intent in _SKIP_INTENTS:
        return plan

    speak = extract_tts_text(text)
    if not audio_ids:
        if _looks_like_clone(text) and plan.intent in {"chat", "inspect", *_EVAL_INTENTS}:
            plan.intent = "chat"
            plan.skill_id = None
            plan.tools_needed = []
            plan.delivery = "clarify"
            plan.notes = "规划：音色克隆需要上传 wav 或 mp3 参考音频"
            return plan
        if _looks_like_tts(text) and plan.intent in {"chat", "inspect", *_EVAL_INTENTS}:
            if not speak:
                plan.intent = "chat"
                plan.skill_id = None
                plan.tools_needed = []
                plan.delivery = "clarify"
                plan.notes = "规划：请输入要朗读的文本"
                return plan
            return _mark_audio_plan(plan, notes="规划：用内置音色将文本合成为语音")
        return plan

    # 有参考音：评测关键词且不像配音/朗读时不抢评测单
    if (
        plan.intent in _EVAL_INTENTS
        and _looks_like_eval(text)
        and not _looks_like_clone(text)
        and not _looks_like_tts(text)
    ):
        return plan

    if not (text or "").strip():
        plan.intent = "chat"
        plan.skill_id = None
        plan.tools_needed = []
        plan.delivery = "clarify"
        plan.notes = "规划：已收到参考音频，请输入要合成的文本"
        return plan

    return _mark_audio_plan(plan, notes="规划：使用参考音频合成配音")


def _completions_url(base_url: str) -> str:
    """把配置的 base 归一成 chat/completions 地址。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AppError(ErrorCode.VALIDATION, "语音合成未配置")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _post_json(url: str, body: dict, headers: dict, timeout_s: float) -> dict:
    """同步 POST JSON。单测可替换本函数，避免打真实上游。"""
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode())


def _decode_audio_b64(raw: str) -> bytes:
    """解析上游 audio.data：纯 base64 或 data: 前缀。"""
    payload = (raw or "").strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise AppError(ErrorCode.UPSTREAM, "音色合成失败") from exc
    if not data:
        raise AppError(ErrorCode.UPSTREAM, "音色合成失败")
    return data


def synthesize_wav(
    *,
    text: str,
    ref_bytes: bytes | None = None,
    ref_mime: str = "audio/wav",
    style: str = "",
) -> bytes:
    """调用 MIMO TTS：有参考音则克隆，否则用内置音色。返回 wav 字节。"""
    api_key = (settings.mimo_tts_api_key or "").strip()
    if not api_key:
        raise AppError(ErrorCode.VALIDATION, "语音合成未配置，请联系管理员")
    if ref_bytes:
        model = (settings.mimo_tts_model or "mimo-v2.5-tts-voiceclone").strip()
        voice = f"data:{ref_mime};base64,{base64.b64encode(ref_bytes).decode('ascii')}"
        mode = "clone"
    else:
        model = (settings.mimo_tts_speech_model or "mimo-v2.5-tts").strip()
        voice = (settings.mimo_tts_voice or "mimo_default").strip() or "mimo_default"
        mode = "tts"
    url = _completions_url(settings.mimo_tts_base_url)
    timeout_s = float(settings.mimo_tts_timeout_s or 90.0)
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": style or ""},
            {"role": "assistant", "content": text},
        ],
        "audio": {"format": OUTPUT_FORMAT, "voice": voice},
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }
    agent_trace(f"语音合成开始 mode={mode} model={model} timeout={int(timeout_s)}s")
    try:
        data = _post_json(url, body, headers, timeout_s)
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "语音合成超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise AppError(ErrorCode.TIMEOUT, "语音合成超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"语音合成内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "操作失败") from exc

    try:
        choices = data.get("choices") if isinstance(data, dict) else None
        message = (choices[0] or {}).get("message") if choices else None
        audio = (message or {}).get("audio") if isinstance(message, dict) else None
        b64 = (audio or {}).get("data") if isinstance(audio, dict) else None
        if not isinstance(b64, str) or not b64:
            raise AppError(ErrorCode.UPSTREAM, "语音合成失败")
        wav = _decode_audio_b64(b64)
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"语音合成响应异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.UPSTREAM, "语音合成失败") from exc
    agent_trace(f"语音合成完成 mode={mode} bytes={len(wav)}")
    return wav


def persist_audio_bytes(
    db: Session,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    user_id: str,
) -> StoredFile:
    """把合成音频写入本地卷并登记 files 表。"""
    safe_name = Path(filename).name or "voiceclone.wav"
    file_id = uuid_str()
    storage_dir = Path(settings.data_dir) / "files"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / file_id
    storage_path.write_bytes(content)
    stored = StoredFile(
        id=file_id,
        filename=safe_name,
        content_type=content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(storage_path),
        kind=Path(safe_name).suffix.lower().lstrip("."),
        uploaded_by=user_id,
    )
    db.add(stored)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        raise
    db.refresh(stored)
    return stored


def execute_voiceclone(db: Session, arguments: dict | None, *, user_id: str) -> dict[str, Any]:
    """调上游、落盘，返回可播放的文件元数据（不含二进制）。无 file_id 走内置音色。"""
    args = arguments if isinstance(arguments, dict) else {}
    text = str(args.get("text") or "").strip()
    if not text:
        raise AppError(ErrorCode.VALIDATION, "请输入要合成的文本")
    file_id = str(args.get("file_id") or "").strip()
    style = str(args.get("style") or "").strip()
    ref_bytes: bytes | None = None
    mime = "audio/wav"
    filename = "tts.wav"
    if file_id:
        stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
        if not stored or not is_audio_file(stored):
            raise AppError(ErrorCode.VALIDATION, "参考音频须为 wav 或 mp3")
        path = Path(stored.storage_path)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "参考音频不存在")
        ref_bytes = path.read_bytes()
        if not ref_bytes:
            raise AppError(ErrorCode.VALIDATION, "参考音频不能为空")
        if len(ref_bytes) > REF_AUDIO_MAX_BYTES:
            raise AppError(ErrorCode.VALIDATION, "参考音频过大，请使用不超过 7MB 的 wav/mp3")
        mime = stored.content_type if stored.content_type in {"audio/wav", "audio/mpeg", "audio/mp3"} else _mime_for_filename(stored.filename)
        if mime == "audio/mp3":
            mime = "audio/mpeg"
        filename = "voiceclone.wav"
    wav = synthesize_wav(text=text, ref_bytes=ref_bytes, ref_mime=mime, style=style)
    out = persist_audio_bytes(
        db,
        filename=filename,
        content=wav,
        content_type="audio/wav",
        user_id=user_id,
    )
    return {
        "file_id": out.id,
        "filename": out.filename,
        "content_type": out.content_type,
        "size": out.size_bytes,
        "content_url": f"/api/files/{out.id}/content",
    }


# 供澄清句识别，避免套上「请补充评测目标」后缀
VOICECLONE_CLARIFY_RE = re.compile(r"(参考音频|音色克隆|配音|朗读|语音|音频)")
