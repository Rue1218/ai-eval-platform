"""前端展示投影：只读真实请求和登记工具，不开放内部执行配置。"""

import json
from collections.abc import Mapping
from dataclasses import replace

from app.harness.execution.task_contract import canonical_task_tool_name
from app.harness.security.loop_redaction import redact_for_transport
from app.llm.loop_contracts import LlmRequestError
from app.llm.resolver import resolve_request

# 字段名来自平台工具 codec；不把任意参数透传到普通会话。
TOOL_FIELDS = {
    "read": "path file_path offset next_offset limit",
    "write": "path file_path content",
    "edit": "path file_path old new old_string new_string",
    "bash": "command timeout timeout_ms",
    "web_search": "query limit max_results",
    "web_fetch": "url",
    "ask_user_question": "",
    "task": "description prompt steps",
    "task.create": "kind",
    "task.status": "task_id",
    "task.cancel": "task_id",
    # 媒体提示词与参考图可能包含用户隐私；卡片只展示非敏感生成参数。
    "image.generate": "size count prompt_extend",
    "video.create": "resolution duration watermark",
    "video.status": "upstream_task_id",
}
PREVIEW_LIMIT = 12000
_TASK_STEP_LIMIT = 12
_TASK_TEXT_LIMIT = 300


# 模型侧安全名 → 注册表短名：媒体 MCP 工具由 loop_bridge 统一生成
# ``platform_`` 前缀名（含点号的工具不能直接暴露给部分提供方），展示投影
# 必须按此还原，否则媒体结果会因未登记展示字段而拿不到结果预览。
_MODEL_WIRE_ALIASES = {
    "platform_image_generate": "image.generate",
    "platform_video_create": "video.create",
    "platform_video_status": "video.status",
}


def _canonical_display_name(wire: str) -> str:
    """把模型可见名归一为注册表短名；未知名称保持原样。"""
    name = canonical_task_tool_name(wire)
    return _MODEL_WIRE_ALIASES.get(name, name)


def _task_display(source: Mapping[str, object], *, result: bool) -> dict[str, object] | None:
    """提取成功 task 的有限结果预览；抽屉状态不从这里读取。"""
    raw: object
    if result:
        display = source.get("display")
        raw = display.get("task") if isinstance(display, Mapping) else None
    else:
        raw = source.get("args")
    if not isinstance(raw, Mapping):
        return None

    goal = str(raw.get("goal") or raw.get("description") or raw.get("prompt") or "").strip()
    raw_steps = raw.get("steps")
    if not goal or not isinstance(raw_steps, list):
        return None

    steps: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for item in raw_steps[:_TASK_STEP_LIMIT]:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()[:_TASK_TEXT_LIMIT]
        status = str(item.get("status") or "pending")
        if not title or status not in {"pending", "in_progress", "completed"}:
            continue
        normalized_title = title.casefold()
        if normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        steps.append({"title": title, "status": status})
    if not steps:
        return None
    return {"goal": goal[:_TASK_TEXT_LIMIT], "steps": steps}


def tool_display(source: dict, *, result: bool = False) -> dict:
    """仅对登记工具投影安全预览；错误输出只公开归一错误码。"""
    wire = source.get("name", "")
    name = _canonical_display_name(wire)
    display = {"version": 1, "title": name, "registry_name": name, "wire_name": wire,
               "format": "text", "truncated": False}
    if name not in TOOL_FIELDS:
        return {**display, "unavailable_reason": "该工具尚未登记展示字段"}
    task = _task_display(source, result=True) if name == "task" and result and source.get("status") == "succeeded" else None
    if result:
        if source.get("status") != "succeeded":
            return {**display, "result_preview": source.get("error_code") or "工具未成功完成"}
        value = source.get("content", "")
        if isinstance(value, str):
            try:
                value = json.loads(value)
                display["format"] = "json"
            except (ValueError, RecursionError):
                pass
        preview = redact_for_transport(value)
        text = preview if isinstance(preview, str) else json.dumps(preview, ensure_ascii=False)
        display.update(result_preview=text[:PREVIEW_LIMIT], truncated=len(text) > PREVIEW_LIMIT)
    else:
        args = source.get("args", {})
        if not isinstance(args, dict):
            return {**display, "unavailable_reason": "参数无效"}
        safe = redact_for_transport({key: args[key] for key in TOOL_FIELDS[name].split() if key in args})
        text = json.dumps(safe, ensure_ascii=False, indent=2)
        display.update(arguments_preview=text[:PREVIEW_LIMIT], truncated=len(text) > PREVIEW_LIMIT)
        display["target"] = str(safe.get("path", safe.get("file_path", safe.get("url", safe.get("query", safe.get("upstream_task_id", ""))))))[:300]
    if task is not None:
        display["task"] = task
    return display


def question_answers(questions: list[dict], answers: list[dict]) -> dict:
    """v2 选择标签与“其他”文本转同一校验模型，保留逗号标签。"""
    from app.errors import AppError, ErrorCode
    from app.harness.execution.ask_user import validate_answers

    by_id = {question["id"]: question for question in questions}
    normalized = []
    for item in answers:
        question = by_id.get(item["question_id"], {})
        value = item["answer"]
        question_type = str(question.get("type") or "radio")
        custom = str(item.get("custom") or "").strip()
        if isinstance(value, list):
            if question_type != "checkbox":
                raise AppError(ErrorCode.VALIDATION, "仅多选问题接受标签数组")
            selected = value
        else:
            selected = [part.strip() for part in value.split(",") if part.strip()] if question.get("multi_select") or question_type == "checkbox" else ([value] if value else [])
        # 简答题及无选项题保持旧客户端仅传 answer 时的兼容投影。
        if question_type == "text" or not question.get("options"):
            custom = custom or (value if isinstance(value, str) else "")
            selected = []
        normalized.append({"id": item["question_id"], "custom": custom,
                           "selected": selected if question.get("options") else []})
    return {"answers": validate_answers(questions, normalized)}


def profile_capabilities(profile) -> tuple[list[str], str | None]:
    """调用同一个 resolver 验证每个候选档位，禁止维护第二份模型能力名单。"""
    allowed = []
    for effort in ("off", "low", "medium", "high", "max"):
        config = replace(profile.config, reasoning_enabled=effort != "off",
                         reasoning_effort=effort if effort != "off" else "medium")
        try:
            resolve_request(replace(profile, config=config), messages=[])
        except LlmRequestError:
            continue
        allowed.append(effort)
    selected = profile.config.reasoning_effort if profile.config.reasoning_enabled else "off"
    return allowed, selected if selected in allowed else next(iter(allowed), None)


def request_summary(
    request,
    *,
    context_window=None,
    history_upto_seq=None,
    input_fingerprint=None,
    tool_transports: dict[str, str] | None = None,
) -> dict:
    """记录实际 attempt 的配置和同源输入估算；测试/旧事实缺协议时保留未知。"""
    meter = None
    if request.protocol and context_window:
        from .loop_wiring import _prompt_breakdown, _prompt_tokens

        input_tokens = _prompt_tokens(request)
        meter = {"basis": "serialized_request.v2", "estimated": True,
                 "profile_version": request.profile_version, "input_fingerprint": input_fingerprint,
                 "history_upto_seq": history_upto_seq, "capacity": context_window,
                 "input_tokens": input_tokens, "reserved_output_tokens": request.max_tokens,
                 "breakdown": _prompt_breakdown(request, tool_transports, input_tokens)}
    return {"model": request.model, "provider": request.provider, "protocol": request.protocol,
            "profile_id": request.profile_id, "profile_version": request.profile_version,
            "reasoning_effort": request.reasoning_effort, "max_tokens": request.max_tokens,
            "input_fingerprint": input_fingerprint, "context_meter": meter,
            # 轨迹快照沿用 DeepSeek Harness 的原生工具定义外形，方便前端直接呈现 Schema。
            "tools": [
                {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
                for tool in request.tools
            ]}
