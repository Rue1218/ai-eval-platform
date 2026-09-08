"""从 deepseek-harness-py 移植的完整事实目录；与 WS 传输目录独立版本化。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

EVENT_ENVELOPE_VERSION = 2
EVENT_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_CATALOG_VERSION = 3
SCHEMA_REF_PREFIX = "dsh://events/"


def _object_schema(
    properties: dict[str, dict[str, Any]],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """创建向前兼容的 JSON Schema 对象定义。"""

    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        # 生产者可先于目录扩展可选字段；持久信封仍为事实来源。
        "additionalProperties": True,
    }


_INTEGER = {"type": "integer"}
_STRING = {"type": "string"}
_OBJECT = {"type": "object", "additionalProperties": True}
_ARRAY = {"type": "array"}


def _field(type_schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {**type_schema, "description": description}


def _event(
    description: str,
    properties: dict[str, dict[str, Any]],
    *,
    required: tuple[str, ...] = (),
    sensitive_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """描述事件，并为传输层预留脱敏策略。

    路径使用以持久事件信封为根的 JSON Pointer。这是元数据而不是校验器：
    新版生产者仍可添加字段，传输层也会继续按通用敏感字段名进行保护。
    """

    return {
        "version": 1,
        "description": description,
        "schema": _object_schema(properties, required=required),
        "sensitive_paths": list(sensitive_paths),
    }


EVENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "session/start": _event(
        "Initial immutable session configuration.",
        {
            "cwd": _field(_STRING, "Workspace directory at session creation."),
            "model": _field(_STRING, "Configured model identifier."),
        },
    ),
    "turn/start": _event(
        "A user turn was accepted for execution.",
        {"turn": _field(_INTEGER, "One-based turn number within the session.")},
        required=("turn",),
    ),
    "user/message": _event(
        "User input accepted into durable model history.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "content": _field(_STRING, "User-visible input text."),
            "source": _field(_STRING, "Origin of the input, normally user."),
            "reasoning_effort": _field(_STRING, "Optional turn-level reasoning setting."),
        },
        required=("turn", "content"),
    ),
    "step/start": _event(
        "A model/tool loop step started.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "One-based step number within the turn."),
        },
        required=("turn", "step"),
    ),
    "step/end": _event(
        "A model/tool loop step reached a terminal boundary.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Completed step."),
            "reason": _field(_STRING, "Why the step ended."),
        },
        required=("turn", "step"),
    ),
    "request/header": _event(
        "The normalized model-visible request configuration.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "reason": _field(_STRING, "Why this header was emitted or changed."),
            "fingerprint": _field(_STRING, "Stable fingerprint of the normalized header."),
            "header": _field(_OBJECT, "Model-visible request header, including tools."),
        },
        required=("turn", "step", "header"),
        sensitive_paths=(
            "/data/header/authorization",
            "/data/header/api_key",
            "/data/header/api-key",
            "/data/header/token",
            "/data/header/cookie",
        ),
    ),
    "assistant/attempt_start": _event(
        "A provider streaming attempt started.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Stable identifier for this provider attempt."),
            "header_seq": _field(_INTEGER, "Sequence of the request/header used by this attempt."),
            "history_upto_seq": _field(_INTEGER, "Latest durable history record sent to the model."),
            "history_selection": _field(_object_schema({
                "algorithm": {"type": "string", "const": "message_indices.v1"},
                "indices": {"type": "array", "items": {"type": "integer", "minimum": 0},
                            "uniqueItems": True},
                "message_count": {"type": "integer", "minimum": 0},
                "input_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            }, required=("algorithm", "indices", "message_count", "input_fingerprint")),
                "对 history_upto_seq 所界定派生消息列表的有序索引与实际输入摘要，不含正文。"),
            "fingerprint_algorithm": _field(
                {"type": "string", "const": "dsh-json-v1"}, "请求头指纹算法版本。",
            ),
        },
        required=("turn", "step", "attempt_id"),
    ),
    "runtime/command": _event(
        "Store 同事务保存的命令接受回执，原始请求和凭据不属于此结构。",
        {
            "fingerprint": _field(_STRING, "规范命令输入摘要，用于同请求 ID 冲突检查。"),
            "data": _field(_object_schema({
                "accepted": {"type": "boolean"},
                "turn": _INTEGER, "turn_id": _STRING, "client_message_id": _STRING,
                "interaction_id": _STRING, "source_seq": _INTEGER,
            }), "接受结果的业务身份，不包含原始命令 data。"),
            "correlation": _field(_OBJECT, "接受结果对应的执行关联身份。"),
        },
        required=("fingerprint", "data", "correlation"),
        sensitive_paths=("/data/request", "/data/credentials", "/data/data/request"),
    ),
    "assistant/message": _event(
        "Completed or interrupted assistant message committed to history.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Provider attempt that produced the message."),
            "message": _field(_OBJECT, "Normalized message used for later model history."),
            "content": _field(_STRING, "Assistant text content."),
            "reasoning_content": _field(_STRING, "Provider-visible reasoning channel when available."),
            "tool_calls": _field(_ARRAY, "Normalized tool calls requested by the assistant."),
            "usage": _field(_OBJECT, "Provider usage metadata when available."),
            "finish_reason": _field(_STRING, "Provider completion reason."),
            "interrupted": _field({"type": "boolean"}, "Whether cancellation interrupted output."),
        },
        required=("turn", "step", "attempt_id"),
    ),
    "assistant/attempt": _event(
        "A provider attempt failed before a message could be committed.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Failed provider attempt."),
            "error": _field(_STRING, "Human-readable failure detail."),
            "error_code": _field(_STRING, "Stable failure category."),
        },
        required=("turn", "step", "attempt_id", "error"),
    ),
    "assistant/retry": _event(
        "The runtime scheduled another provider attempt.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Previous failed attempt."),
            "retry_index": _field(_INTEGER, "Retry ordinal for the step."),
            "error": _field(_STRING, "Failure that triggered the retry."),
            "error_code": _field(_STRING, "Stable failure category."),
        },
        required=("turn", "step", "retry_index"),
    ),
    "tool/call": _event(
        "A normalized tool call requested by the model.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Provider attempt that requested the call."),
            "call_id": _field(_STRING, "Stable provider or runtime call identifier."),
            "call_seq": _field(_INTEGER, "Durable sequence of this tool/call event."),
            "name": _field(_STRING, "Requested tool name."),
            "args": _field(_OBJECT, "Parsed tool arguments."),
            "arguments_raw": _field(_STRING, "Original provider argument string, if retained."),
            "parse_error": _field(_STRING, "Argument parsing failure, if any."),
        },
        required=("turn", "step", "attempt_id", "call_id", "name"),
        sensitive_paths=(
            "/data/args/authorization",
            "/data/args/api_key",
            "/data/args/token",
            "/data/args/password",
            "/data/args/secret",
        ),
    ),
    "approval/asked": _event(
        "The runtime requested user approval before dispatching a tool.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Provider attempt that requested the call."),
            "call_id": _field(_STRING, "Tool call awaiting a decision."),
            "name": _field(_STRING, "Tool name."),
            "args": _field(_OBJECT, "Arguments submitted for approval."),
        },
        required=("turn", "step", "attempt_id", "call_id", "name"),
        sensitive_paths=(
            "/data/args/authorization",
            "/data/args/api_key",
            "/data/args/token",
            "/data/args/password",
            "/data/args/secret",
        ),
    ),
    "approval/decided": _event(
        "An approval decision was recorded for a tool call.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Provider attempt that requested the call."),
            "call_id": _field(_STRING, "Tool call that received a decision."),
            "outcome": _field(_STRING, "Approval outcome."),
            "implicit": _field({"type": "boolean"}, "Whether a persisted always-allow rule decided it."),
        },
        required=("turn", "step", "attempt_id", "call_id", "outcome"),
    ),
    "tool/dispatch": _event(
        "The tool crossed the execution boundary and may have side effects.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Provider attempt that requested the call."),
            "call_id": _field(_STRING, "Dispatched tool call."),
            "call_seq": _field(_INTEGER, "Sequence of the corresponding tool/call event."),
            "name": _field(_STRING, "Dispatched tool name."),
        },
        required=("turn", "step", "attempt_id", "call_id", "name"),
    ),
    "tool/result": _event(
        "A terminal result for a model-requested tool call.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "step": _field(_INTEGER, "Owning step."),
            "attempt_id": _field(_STRING, "Provider attempt that requested the call."),
            "call_id": _field(_STRING, "Settled tool call."),
            "call_seq": _field(_INTEGER, "Sequence of the corresponding tool/call event."),
            "name": _field(_STRING, "Tool name."),
            "content": _field(_STRING, "Normalized tool output committed to history."),
            "status": _field(_STRING, "Terminal execution status."),
            "error_code": _field(_STRING, "Stable error category, if any."),
            "exit_code": _field(_INTEGER, "Native process exit code, if any."),
            "synthetic": _field({"type": "boolean"}, "Whether recovery synthesized this result."),
        },
        required=("turn", "step", "attempt_id", "call_id", "name", "content", "status"),
    ),
    "runtime/error": _event(
        "The graph runtime failed outside a normal provider attempt.",
        {
            "turn": _field(_INTEGER, "Owning turn."),
            "error": _field(_STRING, "Human-readable runtime failure."),
            "error_code": _field(_STRING, "Stable runtime failure category."),
        },
        required=("turn", "error"),
    ),
    "turn/end": _event(
        "A user turn reached a terminal state.",
        {
            "turn": _field(_INTEGER, "Completed turn."),
            "reason": _field(_STRING, "Terminal reason."),
        },
        required=("turn", "reason"),
    ),
}


# 平台增量只扩展目录，不改变源事件字段与 schema 引用。
for _kind, _description in {
    "runtime/cancel_requested": "已接受指定回合的取消请求，最终仍需 turn/end。",
    "question/asked": "持久工具问题，绑定交互身份与有效期。",
    "question/answered": "已接受的问题回答，仍需回填工具结果。",
    "task_confirmation/requested": "等待业务规格确认。",
    "task_confirmation/resolved": "业务规格确认的持久决定。",
    "execution/quarantined": "远端执行结果未知，保留工作区隔离。",
    "execution/reconciled": "受信证据解除远端执行隔离。",
    "context/trimmed": "上下文窗口裁剪元信息。",
    "session/updated": "会话公开展示元信息变更。",
    "task/queued": "Worker 任务已入队。",
    "task/progress": "Worker 任务进展。",
    "task/report": "Worker 报告引用。",
    "task/end": "Worker 任务终态，独立于 Agent 回合。",
}.items():
    EVENT_SCHEMAS[_kind] = _event(_description, {})


def event_schema_ref(event_type: str) -> str:
    """返回事件类型对应的稳定 schema 引用。"""

    return f"{SCHEMA_REF_PREFIX}{event_type}"


def producer_for_event_type(event_type: str) -> str:
    """返回负责生成该事实的子系统标识。"""

    if event_type == "session/start":
        return "session.manager"
    if event_type in {"turn/start", "turn/end", "user/message", "runtime/error"}:
        return "agent.runtime"
    if event_type.startswith(("tool/", "approval/")):
        return "agent.tool_scheduler"
    if event_type.startswith(("step/", "request/", "assistant/")):
        return "agent.graph"
    return "session.log"


def event_schema_descriptor(event_type: str, event_version: int = 1) -> dict[str, Any]:
    """返回嵌入新事实信封的轻量 schema 元信息。"""

    known = event_type in EVENT_SCHEMAS
    return {
        "ref": event_schema_ref(event_type),
        "version": event_version,
        "dialect": EVENT_SCHEMA_DIALECT,
        "status": "known" if known else "unknown",
    }


def sensitive_paths_for_event_type(event_type: str) -> tuple[str, ...]:
    """返回此事件声明为不得离开服务端的 JSON Pointer 字段。"""

    definition = EVENT_SCHEMAS.get(event_type)
    if definition is None:
        return ()
    return tuple(definition.get("sensitive_paths", ()))


def correlation_from_data(data: dict[str, Any]) -> dict[str, Any]:
    """只提取已登记的跨事件关联身份。"""

    correlation: dict[str, Any] = {}
    for key in (
        "turn", "step", "attempt_id", "call_id", "call_seq", "header_seq", "turn_id", "task_id",
    ):
        value = data.get(key)
        if isinstance(value, int | str) and not isinstance(value, bool):
            correlation[key] = value
    parent_seq = data.get("parent_event_seq", data.get("header_seq"))
    if isinstance(parent_seq, int) and not isinstance(parent_seq, bool):
        correlation["parent_event_seq"] = parent_seq
    return correlation


def envelope_schema() -> dict[str, Any]:
    """返回持久事实信封的 JSON Schema。"""

    return _object_schema(
        {
            "schema_version": _field(_INTEGER, "Envelope compatibility version."),
            "event_version": _field(_INTEGER, "Version of this event type's data payload."),
            "event_id": _field(_STRING, "Stable event identifier."),
            "session_id": _field(_STRING, "Owning session identifier."),
            "seq": _field(_INTEGER, "Monotonic sequence within the session."),
            "ts": _field({"type": "number"}, "Wall-clock commit timestamp in seconds."),
            "type": _field(_STRING, "Durable event type."),
            "producer": _field(_STRING, "Subsystem that committed the event."),
            "durability": _field(_STRING, "committed, transient, or synthetic."),
            "correlation": _field(_OBJECT, "Cross-event turn, step, attempt, and call links."),
            "schema": _field(_OBJECT, "Reference to this event payload's schema."),
            "data": _field(_OBJECT, "Event-specific payload."),
            "extensions": _field(_OBJECT, "Forward-compatible extension fields."),
        },
        required=("schema_version", "session_id", "seq", "ts", "type", "data"),
    )


def schema_catalog() -> dict[str, Any]:
    """返回可缓存、可 JSON 序列化的完整事实目录。"""

    return {
        "catalog_version": SCHEMA_CATALOG_VERSION,
        "dialect": EVENT_SCHEMA_DIALECT,
        "envelope": {
            "ref": "dsh://events/envelope",
            "version": EVENT_ENVELOPE_VERSION,
            "schema": envelope_schema(),
        },
        "events": {
            event_type: {
                "ref": event_schema_ref(event_type),
                "version": definition["version"],
                "dialect": EVENT_SCHEMA_DIALECT,
                "description": definition["description"],
                "schema": definition["schema"],
                "sensitive_paths": definition["sensitive_paths"],
            }
            for event_type, definition in EVENT_SCHEMAS.items()
        },
    }


def schema_catalog_etag() -> str:
    """返回供客户端缓存目录的稳定内容摘要。"""

    encoded = json.dumps(
        schema_catalog(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
