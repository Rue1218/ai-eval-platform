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
