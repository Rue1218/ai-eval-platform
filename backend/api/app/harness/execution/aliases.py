"""原生工具入参别名归一：旧字段名写入 canonical 后删除，再交给 Schema 校验。"""

from __future__ import annotations

from collections.abc import Mapping

from app.errors import AppError, ErrorCode

# 工具名 → (旧键, 新键)。新键已有非空值时只删旧键，避免覆盖模型显式传入。
_ALIASES: dict[str, tuple[tuple[str, str], ...]] = {
    "read": (("path", "file_path"), ("next_offset", "offset")),
    "write": (("path", "file_path"),),
    "edit": (("path", "file_path"), ("old", "old_string"), ("new", "new_string")),
    "web_search": (("limit", "max_results"),),
    "task": (("goal", "prompt"),),
    "TaskCreate": (("title", "subject"), ("goal", "subject"), ("prompt", "description")),
    "TaskGet": (("id", "taskId"), ("task_id", "taskId")),
    "TaskUpdate": (("id", "taskId"), ("task_id", "taskId")),
}

_ALLOWED_ENGINES = frozenset({"", "auto", "native"})
_BASH_WALL_TIMEOUT_S = 15.0


def _has_value(value: object) -> bool:
    """判断参数是否已由模型显式给出（空串视为未给，留给别名回填）。"""
    return value is not None and value != ""


def normalize_tool_arguments(
    name: str,
    arguments: Mapping[str, object] | None,
    schema: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """把旧字段名改写为 canonical 名，并补齐 task 的 description/prompt。

    仅当当前 Schema 声明了新键时才改写/删除旧键，避免测试或扩展工具仍用
    ``path`` 时被误删。
    """
    raw = dict(arguments or {})
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    declared = properties if isinstance(properties, Mapping) else None
    for old_key, new_key in _ALIASES.get(name, ()):
        schema_has_new = declared is None or new_key in declared
        schema_has_old = declared is not None and old_key in declared
        if schema_has_new and not _has_value(raw.get(new_key)) and old_key in raw:
            raw[new_key] = raw[old_key]
        if schema_has_new and old_key in raw and not schema_has_old:
            raw.pop(old_key, None)
    if name == "task" and (declared is None or "prompt" in declared):
        prompt = str(raw.get("prompt") or "").strip()
        description = str(raw.get("description") or "").strip()
        if prompt and not description:
            raw["description"] = prompt[:24] + ("…" if len(prompt) > 24 else "")
        elif description and not prompt:
            raw["prompt"] = description
        if prompt:
            raw["prompt"] = prompt
        if description or raw.get("description"):
            raw["description"] = str(raw.get("description") or "").strip()
    if name == "TaskCreate" and (declared is None or "subject" in declared):
        subject = str(raw.get("subject") or "").strip()
        if not subject:
            raw["subject"] = str(raw.get("description") or raw.get("prompt") or "")[:120]
    return raw


def enforce_tool_argument_policy(name: str, arguments: Mapping[str, object]) -> None:
    """拒绝关沙箱、后台执行以及未实现的搜索/抓取引擎。"""
    if name in {"bash", "task"} and arguments.get("run_in_background") is True:
        raise AppError(ErrorCode.VALIDATION, "平台不支持后台执行工具")
    if name == "bash" and arguments.get("dangerouslyDisableSandbox") is True:
        raise AppError(ErrorCode.VALIDATION, "禁止关闭 bash 沙箱")
    if name in {"web_search", "web_fetch"}:
        engine = str(arguments.get("engine") or "").strip().lower()
        if engine and engine not in _ALLOWED_ENGINES:
            raise AppError(ErrorCode.VALIDATION, "当前仅支持 auto/native 检索引擎")


def bash_timeout_seconds(arguments: Mapping[str, object]) -> float:
    """把可选 timeout（毫秒）换成秒，并封顶现有沙箱墙钟 15s。"""
    raw = arguments.get("timeout")
    if raw is None or raw == "":
        return _BASH_WALL_TIMEOUT_S
    try:
        timeout_ms = float(raw)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION, "timeout 必须是毫秒整数") from exc
    if timeout_ms <= 0:
        raise AppError(ErrorCode.VALIDATION, "timeout 必须大于 0")
    return min(_BASH_WALL_TIMEOUT_S, timeout_ms / 1000.0)
