"""Responses 协议公共编解码，供 API 与 Worker 使用同一线协议。"""

import json
from copy import deepcopy


def response_input(messages: list[dict]) -> list[dict]:
    """把平台消息转换为独立消息项、函数调用项和函数结果项。"""
    result = []
    for message in messages:
        role = message["role"]
        content = message.get("content") or ""
        if role == "tool":
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            result.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": content})
            continue
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "text":
                    parts.append({"type": "output_text" if role == "assistant" else "input_text", "text": part["text"]})
                elif part.get("type") == "image_url" and role == "user":
                    image = part["image_url"]
                    parts.append({"type": "input_image", "image_url": image["url"], "detail": image.get("detail", "auto")})
                else:
                    raise ValueError("不支持的 Responses 内容块")
            content = parts
        if content or not message.get("tool_calls"):
            result.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            function = call.get("function") or call
            arguments = call.get("arguments_raw", function.get("arguments", call.get("args", {})))
            result.append({
                "type": "function_call", "call_id": call["id"], "name": function["name"],
                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
            })
    return result


def response_body(*, model: str, messages: list[dict], system: str | None,
                  max_tokens: int, temperature: float | None) -> dict:
    """构造无服务端会话依赖的请求；历史由平台持有。"""
    body = {"model": model, "input": response_input(messages), "max_output_tokens": max_tokens, "store": False}
    if system:
        body["instructions"] = system
    # 推理模型不接受常规 temperature，省略后使用模型默认配置。
    if temperature is not None and not model.lower().rsplit("/", 1)[-1].startswith(("o1", "o3", "o4", "gpt-5")):
        body["temperature"] = temperature
    return body


def response_text(data: dict) -> str:
    """仅接受正常完成响应，拒绝把失败或截断内容当成成功评测。"""
    if data.get("status") != "completed" or data.get("error"):
        raise ValueError("Responses 响应未成功完成")
    return "".join(
        part.get("text", "") if part.get("type") == "output_text" else part.get("refusal", "")
        for item in data["output"] if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") in {"output_text", "refusal"}
    )


def response_usage(data: dict) -> dict:
    """归一 Responses token 计数，保留缓存和推理计费明细。"""
    raw = data.get("usage") or {}
    prompt, completion = int(raw.get("input_tokens") or 0), int(raw.get("output_tokens") or 0)
    return {
        "prompt_tokens": prompt, "completion_tokens": completion,
        "total_tokens": int(raw.get("total_tokens") or prompt + completion),
        **(raw.get("input_tokens_details") or {}), **(raw.get("output_tokens_details") or {}),
    }


class ResponsesStream:
    """累计工具参数并校验终态；EOF 本身不代表响应成功。"""

    def __init__(self):
        self.calls: dict[int, dict] = {}
        self.call_done_arguments: dict[int, str] = {}
        self.response: dict | None = None
        self.text_parts: dict[tuple, str] = {}
        self.text_done_parts: dict[tuple, str] = {}
        # 跟踪所有已观察到的项与内容块，空终态不能悄悄丢弃其他输出。
        self.item_ids: dict[int, str] = {}
        self.item_types: dict[int, str] = {}
        self.completed_items: dict[int, dict] = {}
        self.content_types: dict[tuple, str] = {}
        self.completed_content: dict[tuple, dict] = {}
        self.emitted_text = ""

    @staticmethod
    def _index(value: object) -> int:
        """索引必须是非负整数，避免布尔值或负索引混淆输出身份。"""
        if type(value) is not int or value < 0:
            raise ValueError("Responses 输出索引不合法")
        return value

    @classmethod
    def _text_key(cls, event: dict, kind: str) -> tuple:
        """正文事件的索引是校验和重建终态的唯一定位键。"""
        return cls._index(event.get("output_index", 0)), cls._index(event.get("content_index", 0)), kind

    def _observe_item(self, index: int, kind: str, item_id: str | None) -> None:
        """同一下标的类型和非空身份必须稳定，跨下标不能复用身份。"""
        if not isinstance(kind, str) or not kind or self.item_types.get(index, kind) != kind:
            raise ValueError("Responses 输出项类型发生变化")
        self.item_types[index] = kind
        if item_id is not None:
            if not isinstance(item_id, str) or not item_id:
                raise ValueError("Responses 输出项身份不合法")
            if self.item_ids.get(index, item_id) != item_id or any(
                previous == item_id and previous_index != index
                for previous_index, previous in self.item_ids.items()
            ):
                raise ValueError("Responses 输出项身份发生变化或重复")
            self.item_ids[index] = item_id

    def _observe_content(self, event: dict, kind: str) -> tuple:
        """将内容事件关联到同一消息，并拒绝内容块改变类型。"""
        if not isinstance(kind, str) or not kind:
            raise ValueError("Responses 内容块类型不合法")
        key = self._text_key(event, kind)
        self._observe_item(key[0], "message", event.get("item_id"))
        pair = key[:2]
        if self.content_types.get(pair, kind) != kind:
            raise ValueError("Responses 内容块类型发生变化")
        self.content_types[pair] = kind
        return key

    def _record_text_done(self, event: dict, kind: str) -> None:
        """记录完成正文；它必须覆盖此前同一内容块的全部增量。"""
        key = self._observe_content(event, kind)
        field = "text" if kind == "output_text" else "refusal"
        text = event.get(field)
        if not isinstance(text, str) or not text.startswith(self.text_parts.get(key, "")):
            raise ValueError("Responses 完成正文与增量不一致")
        if key in self.text_done_parts and self.text_done_parts[key] != text:
            raise ValueError("Responses 重复完成正文不一致")
        self.text_done_parts[key] = text

    def _repair_empty_terminal_output(self, response: dict) -> dict:
        """从已核验完成事件恢复网关遗漏的终态，绝不依据工具增量推断完成。

        工具或推理必须具有全量、连续的 output_item.done 快照；纯文本仍沿用
        单内容块兼容。非空终态不修改，所有分支仍须通过后续一致性校验。
        """
        if response.get("status") != "completed":
            return response
        output = response.get("output")
        if not isinstance(output, list):
            raise ValueError("Responses 完成快照输出结构不合法")
        if not output and (self.calls or "reasoning" in self.item_types.values()):
            repaired = deepcopy(response)
            repaired["output"] = self._completed_output_items()
            return repaired
        if output or self.calls or len(self.text_done_parts) != 1:
            return response
        (output_index, content_index, kind), text = next(iter(self.text_done_parts.items()))
        if output_index != 0 or content_index != 0 or set(self.text_parts) - set(self.text_done_parts):
            return response
        if self.item_types != {0: "message"} or self.content_types != {(0, 0): kind}:
            raise ValueError("Responses 空终态包含额外输出项或内容块")
        field = "text" if kind == "output_text" else "refusal"
        content = deepcopy(self.completed_content.get((0, 0), {"type": kind, field: text}))
        if content.get("type") != kind or content.get(field) != text:
            raise ValueError("Responses 完成内容块与正文不一致")
        if kind == "output_text":
            content.setdefault("annotations", [])
        item = deepcopy(self.completed_items.get(0, {
            "type": "message", "role": "assistant", "status": "completed", "content": [content],
        }))
        if (item.get("role") != "assistant" or item.get("status") != "completed"
                or len(item.get("content", [])) != 1):
            raise ValueError("Responses 完成消息不满足单文本兼容条件")
        # 缺少供应商身份时不伪造固定 ID；下一轮使用普通助手消息回放。
        if 0 in self.item_ids:
            item["id"] = self.item_ids[0]
        repaired = deepcopy(response)
        repaired["output"] = [item]
        return repaired

    def _completed_output_items(self) -> list[dict]:
        """仅回放逐项完成的原始快照，工具身份、参数和推理状态不补造。"""
        indexes = set(self.item_types)
        if (not indexes or indexes != set(self.completed_items)
                or sorted(indexes) != list(range(len(indexes)))):
            raise ValueError("Responses 空终态缺少完整工具或推理输出项")
        output = [deepcopy(self.completed_items[index]) for index in range(len(indexes))]
        call_ids = set()
        for item in output:
            kind = item.get("type")
            if kind not in {"message", "function_call", "reasoning"}:
                raise ValueError("Responses 空终态包含不支持的输出项")
            if item.get("status", "completed") != "completed":
                raise ValueError("Responses 输出项未成功完成")
            if not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("Responses 完成输出项身份缺失")
            if kind == "function_call":
                if any(not isinstance(item.get(key), str) or not item[key] for key in ("call_id", "name", "arguments")):
                    raise ValueError("Responses 完成工具身份或参数缺失")
                if item["call_id"] in call_ids:
                    raise ValueError("Responses 完成工具调用身份重复")
                call_ids.add(item["call_id"])
                # 错误参数不能因补齐空终态变成可执行工具，解析后仍回放原串。
                if not isinstance(json.loads(item["arguments"]), dict):
                    raise ValueError("Responses 完成工具参数不是对象")
            elif kind == "message":
                if item.get("role") != "assistant" or not isinstance(item.get("content"), list) or not item["content"]:
                    raise ValueError("Responses 完成消息结构不完整")
            elif not isinstance(item.get("encrypted_content"), str) or not item["encrypted_content"]:
                # store=false 下不把展示摘要伪装成可回放的私有推理状态。
                raise ValueError("Responses 完成推理项缺少回放状态")
        return output

    def _validate_output(self, output: list[dict]) -> None:
        """终态必须覆盖所有已观察项，并与消息和内容块的完成快照一致。"""
        if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
            raise ValueError("Responses 完成快照输出结构不合法")
        for index, kind in self.item_types.items():
            if index >= len(output) or output[index].get("type") != kind:
                raise ValueError("Responses 完成快照缺少正文或工具输出项")
            item = output[index]
            if index in self.item_ids and item.get("id") != self.item_ids[index]:
                raise ValueError("Responses 完成快照输出项身份不一致")
            if any(item.get(key) != value for key, value in self.completed_items.get(index, {}).items()):
                raise ValueError("Responses 完成快照与完成输出项不一致")
        for (index, content_index), kind in self.content_types.items():
            content = output[index].get("content", [])
            if (not isinstance(content, list) or content_index >= len(content)
                    or not isinstance(content[content_index], dict)
                    or content[content_index].get("type") != kind):
                raise ValueError("Responses 完成快照缺少正文内容块")
            if any(content[content_index].get(key) != value
                   for key, value in self.completed_content.get((index, content_index), {}).items()):
                raise ValueError("Responses 完成快照与完成内容块不一致")

    def _complete_text(self, output: list[dict]) -> list[tuple]:
        """按输出项和内容项核对正文，仅补齐可安全追加的后缀，拒绝回退或错序。"""
        final_parts = {}
        for output_index, item in enumerate(output):
            if item.get("type") != "message":
                continue
            for content_index, part in enumerate(item.get("content", [])):
                kind = part.get("type")
                if kind not in {"output_text", "refusal"}:
                    continue
                text = part.get("text" if kind == "output_text" else "refusal", "")
                if not isinstance(text, str):
                    raise ValueError("Responses 完成正文不是文本")
                final_parts[(output_index, content_index, kind)] = text
        for key, done_text in self.text_done_parts.items():
            if final_parts.get(key) != done_text:
                raise ValueError("Responses 完成正文与完成事件不一致")
        for key, streamed in self.text_parts.items():
            if key not in final_parts or not final_parts[key].startswith(streamed):
                raise ValueError("Responses 完成正文与增量不一致")
        final_text = "".join(final_parts.values())
        if not final_text.startswith(self.emitted_text):
            raise ValueError("Responses 正文顺序不一致")
        tail = final_text[len(self.emitted_text):]
        return [("text", tail)] if tail else []

    def _call(self, index: int, item: dict, *, complete: bool) -> list[tuple]:
        """使用 call_id 配对结果，item.id 仅属于供应商输出项身份。"""
        events = []
        previous = self.calls.get(index)
        if not previous:
            if not item.get("call_id") or not item.get("name"):
                raise ValueError("Responses 工具身份缺失")
            previous = {"call_id": item["call_id"], "name": item["name"], "arguments": ""}
            self.calls[index] = previous
            events.append(("tool_start", index, item["call_id"], item["name"]))
        if (item.get("call_id"), item.get("name")) != (previous["call_id"], previous["name"]):
            raise ValueError("Responses 工具身份发生变化")
        if complete:
            arguments = item.get("arguments", "")
            if index in self.call_done_arguments and arguments != self.call_done_arguments[index]:
                raise ValueError("Responses 完成工具参数与完成事件不一致")
            if not isinstance(arguments, str) or not arguments.startswith(previous["arguments"]):
                raise ValueError("Responses 工具参数发生回退")
            tail = arguments[len(previous["arguments"]):]
            if tail:
                events.append(("tool_delta", index, tail))
            previous["arguments"] = arguments
        return events

    def feed(self, event: dict) -> list[tuple]:
        """投影语义事件，完成快照补齐省略的工具增量且不重复参数。"""
        kind = event.get("type", "")
        if self.response is not None:
            raise ValueError("Responses 终态后出现事件")
        if kind in {"error", "response.failed"}:
            raise ValueError("Responses 上游响应失败")
        if kind in {"response.output_text.delta", "response.refusal.delta"}:
            delta = event.get("delta", "")
            if not isinstance(delta, str):
                raise ValueError("Responses 正文增量不是文本")
            # 兼容省略索引的单正文网关；标准多项响应仍使用各自索引，不能混淆拒绝与正文。
            key = self._observe_content(event, "refusal" if kind == "response.refusal.delta" else "output_text")
            if key in self.text_done_parts:
                raise ValueError("Responses 正文完成后出现增量")
            self.text_parts[key] = self.text_parts.get(key, "") + delta
            self.emitted_text += delta
            return [("text", delta)]
        if kind in {"response.output_text.done", "response.refusal.done"}:
            self._record_text_done(event, "refusal" if kind == "response.refusal.done" else "output_text")
            return []
        if kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            return [("reasoning", event.get("delta", ""))]
        if kind in {"response.output_item.added", "response.output_item.done"}:
            item = event.get("item") or {}
            index = self._index(event["output_index"])
            self._observe_item(index, item.get("type"), item.get("id"))
            if kind.endswith(".done"):
                if index in self.completed_items and self.completed_items[index] != item:
                    raise ValueError("Responses 重复完成输出项不一致")
                self.completed_items[index] = deepcopy(item)
            if item.get("type") == "function_call":
                return self._call(event["output_index"], item, complete=kind.endswith(".done"))
        if kind in {"response.content_part.added", "response.content_part.done"}:
            part = event.get("part") or {}
            pair = self._observe_content(event, part.get("type"))[:2]
            if kind.endswith(".done"):
                if pair in self.completed_content and self.completed_content[pair] != part:
                    raise ValueError("Responses 重复完成内容块不一致")
                self.completed_content[pair] = deepcopy(part)
        if kind == "response.function_call_arguments.delta":
            index, delta = event["output_index"], event["delta"]
            if index not in self.calls or not isinstance(delta, str):
                raise ValueError("Responses 工具增量缺少起始项")
            if index in self.call_done_arguments or index in self.completed_items:
                raise ValueError("Responses 工具完成后出现参数增量")
            self.calls[index]["arguments"] += delta
            return [("tool_delta", index, delta)]
        if kind == "response.function_call_arguments.done":
            index = self._index(event["output_index"])
            self._observe_item(index, "function_call", event.get("item_id"))
            arguments = event.get("arguments")
            if (index not in self.calls or not isinstance(arguments, str)
                    or not arguments.startswith(self.calls[index]["arguments"])):
                raise ValueError("Responses 工具完成参数与增量不一致")
            if index in self.call_done_arguments and self.call_done_arguments[index] != arguments:
                raise ValueError("Responses 重复工具完成参数不一致")
            if index in self.completed_items and self.completed_items[index].get("arguments") != arguments:
                raise ValueError("Responses 工具完成参数与输出项不一致")
            self.call_done_arguments[index] = arguments
        if kind in {"response.completed", "response.incomplete"}:
            response = event["response"]
            expected = "completed" if kind.endswith(".completed") else "incomplete"
            if response.get("status") != expected or response.get("error"):
                raise ValueError("Responses 终态不一致")
            response = self._repair_empty_terminal_output(response)
            self._validate_output(response["output"])
            events = self._complete_text(response["output"])
            final_calls = set()
            for index, item in enumerate(response["output"]):
                if item.get("type") == "function_call":
                    final_calls.add(index)
                    events.extend(self._call(index, item, complete=True))
            if set(self.calls) != final_calls:
                raise ValueError("Responses 完成快照缺少工具项")
            self.response = deepcopy(response)
            return events
        return []
