"""系统斜杠命令解析（开发说明书 §9 / §16.4）。

发送仍走 ``user_message``；参数只作规划提示，前端不直接拼确认卡。
自定义斜杠 M1 未启用，本模块只处理系统 15 条。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import AppError, ErrorCode

# 斜杠语法冻结：/name 后可选参数
_SLASH_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]{0,31})(?:\s+(.+))?$")

# 系统 15 条：enabled=False 时面板灰置；若仍发来则 VALIDATION
SYSTEM_COMMANDS: dict[str, dict[str, str | bool]] = {
    "benchmark": {"group": "order", "enabled": True, "hint": "基准评测"},
    "rag": {"group": "order", "enabled": False, "hint": "RAG 评测", "reason": "将在知识库阶段启用"},
    "testcase": {"group": "order", "enabled": True, "hint": "生成用例"},
    "stress": {"group": "order", "enabled": True, "hint": "先评后压"},
    "cancel": {"group": "control", "enabled": True, "hint": "取消本会话非终态任务"},
    "rerun": {"group": "control", "enabled": True, "hint": "拷贝最近任务配置为新确认卡"},
    "stop": {"group": "control", "enabled": True, "hint": "停止本轮生成"},
    "new": {"group": "control", "enabled": True, "hint": "新建空会话"},
    "compact": {"group": "control", "enabled": True, "hint": "压缩本会话模型窗口"},
    "status": {"group": "readonly", "enabled": True, "hint": "当前占槽 / 活动任务"},
    "profiles": {"group": "readonly", "enabled": True, "hint": "列出协议档"},
    "datasets": {"group": "readonly", "enabled": True, "hint": "列出数据集"},
    "kb": {"group": "readonly", "enabled": False, "hint": "列出知识库", "reason": "将在知识库阶段启用"},
    "report": {"group": "readonly", "enabled": False, "hint": "读取已有报告", "reason": "报告解读将在 M4 接入"},
    "help": {"group": "system", "enabled": True, "hint": "列出当前已启用命令"},
}

SYSTEM_COMMAND_NAMES = frozenset(SYSTEM_COMMANDS)


@dataclass(frozen=True)
class SlashParse:
    """一次输入的斜杠解析结果；非斜杠时 command 为空。"""

    raw: str
    command: str | None
    args: str
    is_slash: bool


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
    lines = ["当前已启用的命令："]
    for name, meta in SYSTEM_COMMANDS.items():
        if meta.get("enabled"):
            lines.append(f"/{name}  {meta['hint']}")
    return "\n".join(lines)


def unknown_command_text() -> str:
    """未知 ``/`` 命令的交付句。"""
    return "未知命令。\n" + enabled_help_text()
