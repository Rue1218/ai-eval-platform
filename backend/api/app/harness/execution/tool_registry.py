"""工具注册表：元数据、参数绑定与分派的唯一正文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.errors import AppError, ErrorCode

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class McpToolDefinition:
    """单个短工具的公开元数据与执行预算。"""

    name: str
    title: str
    description: str
    permission: str
    timeout_s: int
    parallel_safe: bool = False
    idempotency: bool = False


# 任何展示、白名单或执行分派都必须从此表派生，禁止手写第二份工具名。
REGISTERED_TOOLS: tuple[McpToolDefinition, ...] = (
    McpToolDefinition(
        name="audio.voiceclone",
        title="音色克隆配音",
        description="用本轮 wav/mp3 参考音频克隆音色并合成配音",
        permission="write",
        timeout_s=90,
        parallel_safe=False,
        idempotency=False,
    ),
    McpToolDefinition(
        name="image.generate",
        title="Qwen Image 生图",
        description="Qwen Image 3.0 文本或参考图生图",
        permission="write",
        timeout_s=90,
        parallel_safe=False,
        idempotency=False,
    ),
    McpToolDefinition(
        name="audio.speech_recognition",
        title="语音识别",
        description="将本地上传的 wav/mp3 音频转录为文本",
        permission="write",
        timeout_s=90,
        parallel_safe=False,
        idempotency=False,
    ),
    McpToolDefinition(
        name="audio.speech_synthesis",
        title="语音合成",
        description="用 MiMo TTS 将文本合成为 wav 音频",
        permission="write",
        timeout_s=90,
        parallel_safe=False,
        idempotency=False,
    ),
)
TOOL_BY_NAME = {tool.name: tool for tool in REGISTERED_TOOLS}


def get_tool_definition(name: str) -> McpToolDefinition | None:
    """按名称读取已注册工具；未注册能力一律返回空。"""
    return TOOL_BY_NAME.get((name or "").strip())


def bind_tool_arguments(
    db: Session,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    text: str,
    attachments: list[str],
) -> dict[str, Any]:
    """绑定模型入参与本轮附件，禁止模型伪造参考文件 ID。"""
    args = dict(arguments or {})
    if name == "audio.voiceclone":
        from app.agent.voiceclone import arguments_for_voiceclone

        bound = arguments_for_voiceclone(
            db, text=str(args.get("text") or text), attachments=attachments
        )
        if args.get("text"):
            bound["text"] = str(args["text"])
        return bound
    if name == "image.generate":
        from app.agent.imagegen import arguments_for_imagegen

        bound = arguments_for_imagegen(
            db, text=str(args.get("prompt") or text), attachments=attachments
        )
        if args.get("prompt"):
            bound["prompt"] = str(args["prompt"])
        if "prompt_extend" in args:
            bound["prompt_extend"] = bool(args["prompt_extend"])
        return bound
    if name == "audio.speech_recognition":
        from app.agent.mimo_audio import arguments_for_speech_recognition

        bound = arguments_for_speech_recognition(db, text=text, attachments=attachments)
        if args.get("language"):
            bound["language"] = str(args["language"]).strip().lower()
        return bound
    if name == "audio.speech_synthesis":
        from app.agent.mimo_audio import arguments_for_speech_synthesis

        return arguments_for_speech_synthesis(text=text, arguments=args)
    raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")


def execute_registered_tool(
    db: Session,
    name: str,
    arguments: dict[str, Any],
    *,
    user_id: str,
) -> dict[str, Any]:
    """执行已注册工具；领域函数正文留在 agent/，此处只分派。"""
    if name == "audio.voiceclone":
        from app.agent.voiceclone import execute_voiceclone

        return execute_voiceclone(db, arguments, user_id=user_id)
    if name == "image.generate":
        from app.agent.imagegen import execute_imagegen

        return execute_imagegen(db, arguments, user_id=user_id)
    if name == "audio.speech_recognition":
        from app.agent.mimo_audio import execute_speech_recognition

        return execute_speech_recognition(db, arguments, user_id=user_id)
    if name == "audio.speech_synthesis":
        from app.agent.mimo_audio import execute_speech_synthesis

        return execute_speech_synthesis(db, arguments, user_id=user_id)
    raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")
