"""最小会话控制斜杠解析。

业务斜杠、资产查询斜杠及其 MCP 注入已移除，避免抢占模型路由。
当前仅保留不参与业务决策的 ``/stop`` 与 ``/compact``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import AppError, ErrorCode

# 斜杠语法冻结：/name 后可选参数
_SLASH_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]{0,31})(?:\s+(.+))?$")

# 控制命令不绑定业务工具，也不向规划阶段注入工具清单。
SYSTEM_COMMANDS: dict[str, dict[str, str | bool]] = {
    "stop": {"group": "control", "enabled": True, "hint": "停止本轮生成"},
    "compact": {"group": "control", "enabled": True, "hint": "压缩本会话模型窗口"},
}

SYSTEM_COMMAND_NAMES = frozenset(SYSTEM_COMMANDS)


@dataclass(frozen=True)
class SlashParse:
    """一次输入的斜杠解析结果；非斜杠时 command 为空。"""

    raw: str
    command: str | None
    args: str
    is_slash: bool


def is_unknown_slash(parsed: SlashParse) -> bool:
    """语法合法但未注册（如 ``/foo``），或 ``/`` 后无法解析出命令名。"""
    if not parsed.is_slash:
        return False
    if not parsed.command:
        return True
    return parsed.command not in SYSTEM_COMMAND_NAMES


def parse_slash(text: str) -> SlashParse:
    """解析整段 trim 后的用户输入。不是 ``/`` 开头则整句当自然语言。"""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return SlashParse(raw=raw, command=None, args="", is_slash=False)
    matched = _SLASH_RE.match(raw)
    if not matched:
        return SlashParse(raw=raw, command=None, args="", is_slash=True)
    name = matched.group(1).lower()
    args = (matched.group(2) or "").strip()
    return SlashParse(raw=raw, command=name, args=args, is_slash=True)


def assert_command_enabled(command: str) -> None:
    """灰置命令若仍发来：抛 VALIDATION，Harness 结束。"""
    meta = SYSTEM_COMMANDS.get(command)
    if meta is None:
        return
    if meta.get("enabled"):
        return
    reason = str(meta.get("reason") or "该能力未启用")
    raise AppError(ErrorCode.VALIDATION, f"「/{command}」{reason}")


def enabled_help_text() -> str:
    """``/help`` 只列出当前已启用命令。"""
    lines = ["当前仅保留会话控制命令："]
    for name, meta in SYSTEM_COMMANDS.items():
        if meta.get("enabled"):
            lines.append(f"/{name}  {meta['hint']}")
    return "\n".join(lines)


def unknown_command_text() -> str:
    """未知 ``/`` 命令的交付句。"""
    return "未知命令。\n" + enabled_help_text()
