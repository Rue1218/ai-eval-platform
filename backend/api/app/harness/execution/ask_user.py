"""ask_user_question：把模型提问投影为现有 clarify 中断。"""

from __future__ import annotations

from collections.abc import Mapping

from app.errors import AppError, ErrorCode


def validate_questions(arguments: Mapping[str, object]) -> list[dict[str, object]]:
    """校验 questions 数组，返回可序列化的问题列表。"""
    raw = arguments.get("questions")
    if not isinstance(raw, list) or not raw:
        raise AppError(ErrorCode.VALIDATION, "questions 不能为空")
    if len(raw) > 8:
        raise AppError(ErrorCode.VALIDATION, "一次最多提出 8 个问题")
    questions: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个问题格式无效")
        qid = str(item.get("id") or "").strip()
        question = str(item.get("question") or "").strip()
        if not qid or not question:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个问题缺少 id 或 question")
        if qid in seen:
            raise AppError(ErrorCode.VALIDATION, "问题 id 不能重复")
        seen.add(qid)
        options_raw = item.get("options") or []
        options: list[dict[str, str]] = []
        if options_raw:
            if not isinstance(options_raw, list):
                raise AppError(ErrorCode.VALIDATION, f"第 {index} 个问题的 options 必须是数组")
            for opt in options_raw:
                if isinstance(opt, Mapping):
                    label = str(opt.get("label") or "").strip()
                    hint = str(opt.get("description") or "").strip()
                else:
                    label = str(opt or "").strip()
                    hint = ""
                if label:
                    options.append({"label": label, "description": hint})
        qtype = str(item.get("type") or "radio").strip() or "radio"
        if qtype not in {"radio", "checkbox", "text"}:
            raise AppError(ErrorCode.VALIDATION, "type 仅支持 radio/checkbox/text")
        questions.append(
            {
                "id": qid,
                "question": question,
                "header": str(item.get("header") or "").strip(),
                "options": options,
                "multi_select": item.get("multi_select") is True,
                "required": item.get("required") is not False,
                "type": qtype,
            }
        )
    return questions


def first_option_labels(question: Mapping[str, object]) -> list[str] | None:
    """旧澄清卡只吃字符串选项；没有选项时返回 None。"""
    options = question.get("options")
    if not isinstance(options, list) or not options:
        return None
    labels = [
        str(item.get("label") or "")
        for item in options
        if isinstance(item, Mapping) and str(item.get("label") or "").strip()
    ]
    return labels or None


def answers_from_reply(
    questions: list[Mapping[str, object]],
    raw_answer: object,
) -> list[dict[str, object]]:
    """把 clarify_reply 的纯文本投影为 answers[]。

    按行对齐题目：空行表示该题未答，不得 ``strip`` 掉前导空行。
    ``multi_select`` / ``checkbox`` 把逗号分隔的标签拆回 ``selected``。
    """
    text = str(raw_answer or "").replace("\r\n", "\n").rstrip("\n")
    lines = [line.strip() for line in text.split("\n")] if text or questions else []
    answers: list[dict[str, object]] = []
    for index, question in enumerate(questions):
        qid = str(question.get("id") or "")
        if index < len(lines):
            value = lines[index]
        elif len(questions) == 1:
            value = text.strip()
        else:
            value = ""
        multi = question.get("multi_select") is True or str(question.get("type") or "") == "checkbox"
        if multi and value:
            selected = [part.strip() for part in value.split(",") if part.strip()]
        else:
            selected = [value] if value else []
        answers.append(
            {
                "id": qid,
                "selected": selected,
                "custom": value,
            }
        )
    return answers


def _question_map(questions: list[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    """题目 id → 题目映射；id 缺失/重复按无效载荷处理（上层已校验）。"""
    return {str(question.get("id") or ""): question for question in questions}


def validate_answers(
    questions: list[Mapping[str, object]],
    raw_answers: object,
) -> list[dict[str, object]]:
    """强校验多题 answers[]（#1 B 路线：ClarifyCard 问卷一次作答）。

    规则：answers 必须为非空数组且至多与 questions 等长；每题 ``id`` 必须
    存在且不重复；``selected`` 必须为字符串数组，radio/checkbox 取值必须为
    该题 ``options[].label`` 的子集（无 options 时允许空选/以 ``custom``
    作答）；text 题忽略 ``selected`` 取 ``custom``；``required`` 题必须有
    值，否则抛 ``AppError(VALIDATION)``。返回归一 answers[]：
    ``[{id, selected:[label…], custom}]``（与 ``answers_from_reply`` 同形，
    toolnode 与 ws.py 双保险共用本实现）。
    """
    if not isinstance(raw_answers, list) or not raw_answers:
        raise AppError(ErrorCode.VALIDATION, "answers 不能为空")
    if len(raw_answers) > len(questions):
        raise AppError(ErrorCode.VALIDATION, "答复数量超过问题数量")
    by_id = _question_map(questions)
    seen: set[str] = set()
    answers: list[dict[str, object]] = []
    for index, item in enumerate(raw_answers, start=1):
        if not isinstance(item, Mapping):
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个答复格式无效")
        qid = str(item.get("id") or "").strip()
        question = by_id.get(qid)
        if not qid or question is None:
            raise AppError(ErrorCode.VALIDATION, f"第 {index} 个答复引用了未知问题 id")
        if qid in seen:
            raise AppError(ErrorCode.VALIDATION, "问题答复不能重复")
        seen.add(qid)
        selected_raw = item.get("selected")
        selected: list[str] = []
        if selected_raw is not None:
            if not isinstance(selected_raw, list) or not all(
                isinstance(part, str) for part in selected_raw
            ):
                raise AppError(ErrorCode.VALIDATION, f"问题 {qid} 的 selected 必须是字符串数组")
            selected = [part.strip() for part in selected_raw if part.strip()]
        custom = item.get("custom")
        if custom is not None and not isinstance(custom, str):
            raise AppError(ErrorCode.VALIDATION, f"问题 {qid} 的 custom 必须是字符串")
        custom = str(custom or "").strip()
        qtype = str(question.get("type") or "radio")
        raw_options = question.get("options")
        option_labels: set[str] = set()
        if isinstance(raw_options, list):
            option_labels = {
                str(opt.get("label") or "").strip()
                for opt in raw_options
                if isinstance(opt, Mapping)
            }
        if qtype in {"radio", "checkbox"} and option_labels:
            unknown = [part for part in selected if part not in option_labels]
            if unknown:
                raise AppError(
                    ErrorCode.VALIDATION,
                    f"问题 {qid} 的选项不在给定范围内：{', '.join(unknown)}",
                )
        if qtype == "radio" and len(selected) > 1:
            raise AppError(ErrorCode.VALIDATION, f"问题 {qid} 为单选，只能选择一个选项")
        if qtype == "text":
            # text 题以 custom 为准，清空 selected 防止误导
            selected = []
        if question.get("required") is not False and not selected and not custom:
            raise AppError(ErrorCode.VALIDATION, f"问题 {qid} 为必答")
        answers.append({"id": qid, "selected": selected, "custom": custom})
    # 允许只答部分题目，但必答题缺答必须拦截；非必答题补空条目保持全量对齐
    for question in questions:
        qid = str(question.get("id") or "")
        if qid in seen:
            continue
        if question.get("required") is not False:
            raise AppError(ErrorCode.VALIDATION, f"问题 {qid} 为必答")
        answers.append({"id": qid, "selected": [], "custom": ""})
    return answers


def resolve_clarify_answers(
    questions: list[Mapping[str, object]],
    reply: object,
) -> list[dict[str, object]]:
    """把 clarify interrupt 的恢复值解析为归一 answers[]（#1）。

    - Mapping 且含 ``answers`` 数组（ClarifyCard 多题结构，服务端
      ``clarify_reply`` 已强校验，此处纵深防御再校验一次）→ 直接采用；
    - 其余（历史纯文本兼容投影）→ 按 ``answers_from_reply`` 行对齐投影。
    """
    if isinstance(reply, Mapping) and isinstance(reply.get("answers"), list):
        return validate_answers(questions, reply["answers"])
    return answers_from_reply(questions, reply)
