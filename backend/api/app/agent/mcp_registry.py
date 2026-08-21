"""最小 MCP 工具注册表：工具清单、参数绑定与执行策略的唯一来源。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..errors import AppError, ErrorCode

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class McpToolDefinition:
    """单个 MCP 工具的公开元数据与执行预算。"""

    name: str
    title: str
    description: str
    permission: str
    timeout_s: int


# 任何 MCP 展示、白名单或执行分派都必须从此表派生，禁止复制工具名列表。
REGISTERED_TOOLS: tuple[McpToolDefinition, ...] = (
    McpToolDefinition(
        name="audio.voiceclone",
        title="音色克隆配音",
        description="用本轮 wav/mp3 参考音频克隆音色并合成配音",
        permission="write",
        timeout_s=90,
    ),
    McpToolDefinition(
        name="image.generate",
        title="Qwen Image 生图",
        description="Qwen Image 3.0 文本或参考图生图",
        permission="write",
        timeout_s=90,
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
        from .voiceclone import arguments_for_voiceclone

        bound = arguments_for_voiceclone(
            db, text=str(args.get("text") or text), attachments=attachments
        )
        if args.get("text"):
            bound["text"] = str(args["text"])
        return bound
    if name == "image.generate":
        from .imagegen import arguments_for_imagegen

        bound = arguments_for_imagegen(
            db, text=str(args.get("prompt") or text), attachments=attachments
        )
        if args.get("prompt"):
            bound["prompt"] = str(args["prompt"])
        if "prompt_extend" in args:
            bound["prompt_extend"] = bool(args["prompt_extend"])
        return bound
    raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")


def execute_registered_tool(
    db: Session,
    name: str,
    arguments: dict[str, Any],
    *,
    user_id: str,
) -> dict[str, Any]:
    """执行已注册工具；新增工具必须同时在本注册表登记并走该分派。"""
    if name == "audio.voiceclone":
        from .voiceclone import execute_voiceclone

        return execute_voiceclone(db, arguments, user_id=user_id)
    if name == "image.generate":
        from .imagegen import execute_imagegen

        return execute_imagegen(db, arguments, user_id=user_id)
    raise AppError(ErrorCode.VALIDATION, f"未知短工具「{name}」")
