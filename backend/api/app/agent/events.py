"""Agent Loop v2 的事实投影与信封；本模块不访问数据库、不执行工具。"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.harness.contracts import loop_events as fact_schemas

# 保留源事实目录公开接口，供 SessionLog 写入信封与诊断订阅复用。
from app.harness.contracts.loop_events import (
    correlation_from_data as correlation_from_data,
)
from app.harness.contracts.loop_events import (
    event_schema_descriptor as event_schema_descriptor,
)
from app.harness.contracts.loop_events import (
    producer_for_event_type as producer_for_event_type,
)
from app.harness.security.loop_redaction import redact_event_for_transport, redact_for_transport

# 每类数据只公开登记字段，未知事实留在事实库而非猜测展示含义。
_FIELDS = {
    "user.message": "content client_message_id author_id attachment_refs",
    "turn.start": "",
    "turn.end": "reason",
    "step.start": "",
    "step.end": "reason usage",
    "assistant.start": "header_seq history_upto_seq request_summary",
    "assistant.message": "content tool_calls usage latency_ms finish_reason interrupted reasoning_preview",
    "assistant.end": "outcome committed_seq interrupted error_code error_message latency_ms",
    "assistant.retry": "retry_index previous_attempt_id error_code delay_s",
    "tool.call": "name display",
    "tool.dispatch": "name execution_id registry_name wire_name tool_contract_version",
    "tool.result": "name status synthetic display error_code exit_code",
    "task_plan.updated": "plan",
    "approval.requested": "interaction_id nonce name expires_at display",
    "approval.resolved": "interaction_id decision source_outcome",
    "question.requested": "interaction_id nonce questions expires_at",
    "question.resolved": "interaction_id outcome answers",
    "task_confirmation.requested": "interaction_id nonce spec_hash display expires_at",
    "task_confirmation.resolved": "interaction_id spec_hash decision",
    "execution.quarantined": "execution_id reason display",
    "execution.reconciled": "execution_id outcome display",
    "task.queued": "status display",
    "task.progress": "status progress display",
    "task.report": "report_id display",
    "task.end": "status report_id display",
    "session.updated": "title engine_version",
    "context.trimmed": "reason dropped kept in_scope_total keep_from_id limit",
    "runtime.error": "code message",
}
PERSISTENT_TYPES = frozenset(_FIELDS)
TRANSIENT_TYPES = frozenset({
    "assistant.text.delta", "assistant.reasoning.delta", "trace.chunk",
})
CONTROL_TYPES = frozenset({
    "hello", "capabilities", "schema.catalog", "command.accepted", "command.rejected",
    "subscribed", "replay.completed", "resync.required", "pong", "trace.event",
})
CORRELATION_FIELDS = frozenset({
    "turn_id", "turn", "step", "attempt_id", "call_id", "call_seq", "task_id", "source_seq",
})
_RESTRICTED_TYPES = frozenset({
    "approval.requested", "approval.resolved", "question.requested", "question.resolved",
    "task_confirmation.requested", "task_confirmation.resolved",
})
_PRIVATE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "cookie", "password", "secret", "token",
    "access_token", "refresh_token", "headers", "header", "raw", "protocol_state",
    "provider_options", "system", "system_segments", "messages", "arguments_raw",
    "args", "arguments", "traceback", "reasoning_content", "reasoning",
})
_SOURCE_TYPES = {name.replace(".", "/"): name for name in PERSISTENT_TYPES}
_SOURCE_TYPES.update({
    "assistant/attempt_start": "assistant.start",
    "assistant/attempt": "assistant.end",
    "approval/asked": "approval.requested",
    "approval/decided": "approval.resolved",
    "question/asked": "question.requested",
    "question/answered": "question.resolved",
    "context/trim": "context.trimmed",
})
_OUTCOMES = {
    "allowed": "allow", "denied": "deny", "allowed-always": "always",
    "timed_out": "expired", "cancelled": "cancelled",
}


def _trace_public(value: Any) -> Any:
    """诊断保留参数形状但屏蔽内部提示词、opaque 状态及异常原文。"""
    forbidden = {
        "protocol_state", "raw", "header", "headers", "system", "system_segments",
        "messages", "provider_options", "traceback", "error", "exception", "nonce",
        "reasoning_content", "reasoning",
    }
    if isinstance(value, dict):
        return {
            key: _trace_public(item) for key, item in value.items()
            if isinstance(key, str) and key.lower() not in forbidden
        }
    if isinstance(value, list):
        return [_trace_public(item) for item in value]
    return deepcopy(value)


def scrub(value: Any) -> Any:
    """深拷贝并剔除禁止出站的结构字段；不是对任意文本秘密的识别器。"""
    if isinstance(value, dict):
        return {
            key: scrub(item) for key, item in value.items()
            if isinstance(key, str) and key.lower().replace("-", "_") not in _PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return deepcopy(value)


def _pick(data: dict, fields: str) -> dict:
    """按显式字段集合取值，不修改事实正文。"""
    return scrub({key: data[key] for key in fields.split() if key in data})


def _transport_data(event_type: str, data: dict) -> dict:
    """目录是静态 schema；恢复快照只特许平台 UI 消息，不放开模型历史。"""
    if event_type == "schema.catalog":
        return deepcopy(data)
    if event_type == "trace.event":
        return redact_for_transport(_trace_public(data))
    result = scrub(data)
    if event_type == "resync.required" and isinstance(data.get("snapshot"), dict):
        source = data["snapshot"]
        if isinstance(source.get("messages"), list):
            result["snapshot"]["messages"] = [
                _pick(message, "id role content client_message_id author_id attachment_refs")
                for message in source["messages"]
                if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
                and isinstance(message.get("content"), str)
            ]
    return redact_for_transport(result)


def frame(
    event_type: str,
    data: dict,
    *,
    session_id: str | None = None,
    cursor: int | None = None,
    correlation: dict | None = None,
    request_id: str | None = None,
    ts: str | float | None = None,
) -> dict:
    """按词汇固定 durability，禁止把瞬态编号伪装成持久游标。"""
    if event_type in PERSISTENT_TYPES:
        durability = "persistent"
        if not session_id or type(cursor) is not int or cursor < 1:
            raise ValueError("持久帧必须指定会话与正整数游标")
    elif event_type in TRANSIENT_TYPES | CONTROL_TYPES:
        durability = "transient" if event_type in TRANSIENT_TYPES else "control"
        if cursor is not None:
            raise ValueError("非持久帧不得带游标")
    else:
        raise ValueError("未登记的事件类型")
    if request_id is not None and event_type not in {"command.accepted", "command.rejected"}:
        raise ValueError("只有命令回执可携带 request_id")
    if isinstance(ts, int | float):
        ts = datetime.fromtimestamp(ts, UTC).isoformat()
    result = {
        "protocol_version": 2, "type": event_type, "durability": durability,
        "ts": ts or datetime.now(UTC).isoformat(),
        "correlation": {
            key: deepcopy(value) for key, value in (correlation or {}).items()
            if key in CORRELATION_FIELDS
        },
        "data": _transport_data(event_type, data),
    }
    if session_id is not None:
        result["session_id"] = session_id
    if cursor is not None:
        result["cursor"] = cursor
    if request_id is not None:
        result["request_id"] = request_id
    return result


def project_fact(event: dict) -> list[dict]:
    """生成无 cursor 的持久信封；Store 同事务取号并按 projection_kind 去重。"""
    event_type = _SOURCE_TYPES.get(event.get("type"))
    if event_type is None:
        return []
    seq = event.get("seq")
    if type(seq) is not int or seq < 0 or not event.get("session_id"):
        raise ValueError("事实缺少会话或合法 seq")
    source = event.get("data", {})
    if not isinstance(source, dict):
        raise ValueError("事实 data 必须为对象")
    correlation = {
        key: source[key] for key in CORRELATION_FIELDS if key in source
    }
    correlation.update({
        key: value for key, value in event.get("correlation", {}).items()
        if key in CORRELATION_FIELDS
    })
    correlation["source_seq"] = seq
    if event_type == "tool.call":
        correlation["call_seq"] = seq
    data = _pick(source, _FIELDS[event_type])
    if event_type in {"tool.call", "tool.result"}:
        from .loop_presentation import tool_display

        data["display"] = tool_display(source, result=event_type == "tool.result")
    if event_type == "assistant.message" and isinstance(source.get("reasoning_content"), str):
        data["reasoning_preview"] = source["reasoning_content"]
    if event_type == "user.message":
        # 图文内容属于模型正文；语义流只展示文本与平台附件引用，禁止内联图像。
        content = source.get("display_content", source.get("content", ""))
        if isinstance(content, list):
            content = "\n".join(
                item["text"] for item in content if isinstance(item, dict)
                and item.get("type") == "text" and isinstance(item.get("text"), str)
            )
        data["content"] = content if isinstance(content, str) else ""
    if event_type in _RESTRICTED_TYPES:
        # 源审批身份显式映射；nonce 只能由主服务持久创建，不能在投影中伪造。
        if "interaction_id" not in data:
            identity = source.get("approval_id", source.get("id"))
            if identity is not None:
                data["interaction_id"] = identity
        if event_type == "approval.requested" and "name" not in data:
            data["name"] = source.get("toolName", "")
    if event_type == "assistant.message":
        message = source.get("message") or {}
        data["content"] = source.get("content", message.get("content", ""))
        calls = source.get("tool_calls", message.get("tool_calls", []))
        data["tool_calls"] = [
            _pick(call, "id call_id name") for call in calls if isinstance(call, dict)
        ]
    if event_type == "assistant.end":
        data.setdefault("outcome", source.get("outcome", "failed"))
        data.setdefault("committed_seq", seq)
        # attempt 事实只保存安全摘要 error；投影改名避免客户端误把它当上游原文。
        if isinstance(source.get("error"), str):
            data["error_message"] = source["error"]
    if event_type == "tool.result":
        data.setdefault("synthetic", False)
    if event_type == "approval.resolved":
        outcome = source.get("outcome")
        if outcome in _OUTCOMES:
            data.update(decision=_OUTCOMES[outcome], source_outcome=outcome)
        elif outcome in {"allow", "deny", "always", "expired", "cancelled"}:
            # 平台审批已经归一 outcome，不能只识别源 allowed/denied 写法。
            data["decision"] = outcome
    if event_type == "runtime.error":
        data = {"code": "INTERNAL", "message": "回合运行失败"}
    projections = [(event_type, data)]
    if event_type == "assistant.message":
        end_data = {
            "outcome": "committed", "committed_seq": seq,
            "interrupted": bool(source.get("interrupted", False)),
        }
        # 旧事实没有该字段时保持缺省，不把 null 伪装成一次已计量的耗时。
        if "latency_ms" in source:
            end_data["latency_ms"] = source["latency_ms"]
        projections.append(("assistant.end", end_data))
    result = []
    for kind, payload in projections:
        envelope = frame(
            kind, payload, session_id=event["session_id"], cursor=1,
            correlation=correlation, ts=event.get("ts"),
        )
        del envelope["cursor"]
        envelope["projection_kind"] = kind
        result.append(envelope)
    return result


def persistent_frame(
    session_id: str, cursor: int, projection: dict, *, ts: str | float | None = None,
) -> dict:
    """由 Store 分配游标后形成公开信封，内部 projection_kind 不上网。"""
    return frame(
        projection["type"], projection["data"], session_id=session_id, cursor=cursor,
        correlation=projection.get("correlation"), ts=ts or projection.get("ts"),
    )


def visible_frame(envelope: dict, *, interactions: bool = False, reasoning: bool = False) -> dict | None:
    """逐接收者裁剪；受限持久事件仍占原 cursor，禁止直接跳过。"""
    event_type = envelope.get("type")
    result = frame(
        event_type, envelope["data"], session_id=envelope.get("session_id"),
        cursor=envelope.get("cursor"), correlation=envelope.get("correlation"),
        request_id=envelope.get("request_id"), ts=envelope.get("ts"),
    )
    if event_type in _RESTRICTED_TYPES and not interactions:
        result["data"] = {"restricted": True}
    if event_type == "resync.required" and not interactions:
        state = result["data"].get("snapshot", {})
        if state.get("pending_confirm"):
            state["pending_confirm"] = {"restricted": True}
    if event_type == "assistant.reasoning.delta" and not reasoning:
        return None
    if not reasoning:
        result["data"].pop("reasoning_preview", None)
    if event_type == "resync.required":
        state = result["data"].get("snapshot", {})
        # 快照也逐条应用最新授权，禁止持久思考或历史交互绕过发送时复验。
        if "timeline" in state:
            state["timeline"] = [visible_frame(item, interactions=interactions, reasoning=reasoning)
                                 for item in envelope["data"].get("snapshot", {}).get("timeline", [])]
        for item in state.get("assistants", []):
            if not reasoning:
                item.pop("reasoning_preview", None)
    if event_type in PERSISTENT_TYPES and result["data"] != {"restricted": True}:
        result["data"] = _pick(result["data"], _FIELDS[event_type])
    return result


def trace_frame(event: dict, session_id: str, *, source: str) -> dict:
    """诊断保留源事实形状并独立脱敏，原始提示词和 opaque 状态永不透传。"""
    if source not in {"history", "runtime"} or event.get("session_id") != session_id:
        raise ValueError("诊断来源或会话不匹配")
    if type(event.get("seq")) is not int or event["seq"] < 0:
        raise ValueError("诊断事实 seq 无效")
    safe = redact_event_for_transport(event)
    public = _trace_public(safe.get("data", {}))
    if event["type"] == "runtime/command":
        # Store 的 data 是接受收据而非客户端请求，诊断也只公开已登记结果字段。
        receipt = safe.get("data", {})
        public = _pick(receipt, "fingerprint")
        public["data"] = _pick(
            receipt.get("data", {}),
            "accepted turn turn_id client_message_id interaction_id source_seq",
        )
        public["correlation"] = {
            key: value for key, value in receipt.get("correlation", {}).items()
            if key in CORRELATION_FIELDS and isinstance(value, int | str)
            and not isinstance(value, bool)
        }
    if event["type"] == "assistant/attempt_start" and "history_selection" in public:
        public["history_selection"] = _pick(
            public["history_selection"],
            "algorithm indices message_count input_fingerprint transformations",
        )
    return frame("trace.event", {
        "source": source,
        "event": {**{key: safe[key] for key in (
            "seq", "type", "ts", "schema_version", "event_version", "producer", "schema",
            "correlation", "event_id", "session_id", "durability",
        ) if key in safe}, "data": public},
    }, session_id=session_id)


def schema_catalog() -> dict:
    """传输目录独立版本化，不假装它是原始事实 schema 的完整描述。"""
    return {
        "version": "agent-loop-stream.v2.2",
        "types": {
            **{name: {"durability": "persistent", "fields": fields.split()}
               for name, fields in _FIELDS.items()},
            **{name: {"durability": "transient"} for name in sorted(TRANSIENT_TYPES)},
            **{name: {"durability": "control"} for name in sorted(CONTROL_TYPES)},
        },
    }


def event_schema_catalog() -> dict:
    """完整源事实目录返回独立副本，防止调用者修改全局定义。"""
    return deepcopy(fact_schemas.schema_catalog())


def event_schema_catalog_etag() -> str:
    """事实目录缓存标识，与传输目录版本分离。"""
    return fact_schemas.schema_catalog_etag()
