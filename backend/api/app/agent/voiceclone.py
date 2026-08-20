"""音色克隆短工具：参考音频 + 文本 → MIMO TTS，落盘后只回 file_id。

上游走 OpenAI 兼容 ``POST {base}/chat/completions``，模型默认
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
_CLONE_HINTS = (
    "配音",
    "克隆",
    "音色",
    "voiceclone",
    "voice clone",
    "朗读",
    "用这",
    "参考音频",
)
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


def arguments_for_voiceclone(
    db: Session,
    *,
    text: str,
    attachments: list[str],
    preferred_file_id: str | None = None,
) -> dict[str, str]:
    """由本轮原文与附件组装工具入参，禁止模型编造 file_id。"""
    return {
        "text": (text or "").strip(),
        "file_id": pick_audio_file_id(db, attachments, preferred_file_id),
    }


def _looks_like_eval(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _EVAL_KEEP_HINTS)


def _looks_like_clone(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _CLONE_HINTS)


def inject_voiceclone_plan(
    db: Session,
    plan: Any,
    *,
    text: str,
    attachments: list[str],
) -> Any:
    """自然语言回合：有参考音则注入短工具；无音频但口令像配音则澄清。

    斜杠评测路径不要调用本函数。L0 把配音句误判成 benchmark 时，
    若没有评测关键词则改走 chat + ``audio.voiceclone``。
    """
    if "image.generate" in plan.tools_needed:
        return plan
    audio_ids = list_audio_file_ids(db, attachments)
    if plan.intent in _SKIP_INTENTS:
        return plan

    if not audio_ids:
        if _looks_like_clone(text) and plan.intent in {"chat", "inspect", *_EVAL_INTENTS}:
            plan.intent = "chat"
            plan.skill_id = None
            plan.tools_needed = []
            plan.delivery = "clarify"
            plan.notes = "规划：音色克隆需要上传 wav 或 mp3 参考音频"
        return plan

    # 有参考音：配音口令优先于评测关键词（朗读稿里可能出现「评测平台」）
    if plan.intent in _EVAL_INTENTS and _looks_like_eval(text) and not _looks_like_clone(text):
        return plan

    if not (text or "").strip():
        plan.intent = "chat"
        plan.skill_id = None
        plan.tools_needed = []
        plan.delivery = "clarify"
        plan.notes = "规划：已收到参考音频，请输入要合成的文本"
        return plan

    # 配音优先：无论 L0 误判为评测还是本就要聊天，只保留音频克隆工具，
    # 避免 React 阶段顺带跑 model.list / dataset.list 浪费轮次。
    plan.intent = "chat"
    plan.skill_id = None
    plan.tools_needed = ["audio.voiceclone"]
    plan.delivery = "text"
    plan.slots = {"filled": {}, "missing": []}
    if "配音" not in (plan.notes or "") and "参考音频" not in (plan.notes or ""):
        plan.notes = "规划：使用参考音频合成配音"
    return plan


def _completions_url(base_url: str) -> str:
    """把配置的 base 归一成 chat/completions 地址。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AppError(ErrorCode.VALIDATION, "音色克隆未配置")
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


def synthesize_wav(*, ref_bytes: bytes, ref_mime: str, text: str, style: str = "") -> bytes:
    """调用 MIMO TTS 语音克隆，返回 wav 字节。"""
    api_key = (settings.mimo_tts_api_key or "").strip()
    if not api_key:
        raise AppError(ErrorCode.VALIDATION, "音色克隆未配置，请联系管理员")
    model = (settings.mimo_tts_model or "mimo-v2.5-tts-voiceclone").strip()
    url = _completions_url(settings.mimo_tts_base_url)
    timeout_s = float(settings.mimo_tts_timeout_s or 90.0)
    voice = f"data:{ref_mime};base64,{base64.b64encode(ref_bytes).decode('ascii')}"
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
    agent_trace(f"音色克隆开始 model={model} timeout={int(timeout_s)}s")
    try:
        data = _post_json(url, body, headers, timeout_s)
    except HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM, f"上游返回 {exc.code}") from exc
    except TimeoutError as exc:
        raise AppError(ErrorCode.TIMEOUT, "音色合成超时") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason:
            raise AppError(ErrorCode.TIMEOUT, "音色合成超时") from exc
        raise AppError(ErrorCode.UPSTREAM, "上游连接失败") from exc
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"音色克隆内部异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.INTERNAL, "操作失败") from exc

    try:
        choices = data.get("choices") if isinstance(data, dict) else None
        message = (choices[0] or {}).get("message") if choices else None
        audio = (message or {}).get("audio") if isinstance(message, dict) else None
        b64 = (audio or {}).get("data") if isinstance(audio, dict) else None
        if not isinstance(b64, str) or not b64:
            raise AppError(ErrorCode.UPSTREAM, "音色合成失败")
        wav = _decode_audio_b64(b64)
    except AppError:
        raise
    except Exception as exc:
        agent_trace(f"音色克隆响应异常 type={type(exc).__name__}")
        raise AppError(ErrorCode.UPSTREAM, "音色合成失败") from exc
    agent_trace(f"音色克隆完成 bytes={len(wav)}")
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
    """读参考音、调上游、落盘，返回可播放的文件元数据（不含二进制）。"""
    args = arguments if isinstance(arguments, dict) else {}
    text = str(args.get("text") or "").strip()
    if not text:
        raise AppError(ErrorCode.VALIDATION, "请输入要合成的文本")
    file_id = str(args.get("file_id") or "").strip()
    if not file_id:
        raise AppError(ErrorCode.VALIDATION, "请上传 wav 或 mp3 参考音频")
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
    style = str(args.get("style") or "").strip()
    wav = synthesize_wav(ref_bytes=ref_bytes, ref_mime=mime, text=text, style=style)
    out = persist_audio_bytes(
        db,
        filename="voiceclone.wav",
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
VOICECLONE_CLARIFY_RE = re.compile(r"(参考音频|音色克隆|配音)")
