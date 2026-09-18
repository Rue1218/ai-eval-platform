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
        self.response: dict | None = None
        self.text_parts: dict[tuple, str] = {}
        self.text_done_parts: dict[tuple, str] = {}
        self.text_item_ids: dict[tuple, str] = {}
        self.emitted_text = ""

    @staticmethod
    def _text_key(event: dict, kind: str) -> tuple:
        """正文事件的索引是校验和重建终态的唯一定位键。"""
        return event.get("output_index", 0), event.get("content_index", 0), kind

    def _record_text_done(self, event: dict, kind: str) -> None:
        """记录完成正文；它必须覆盖此前同一内容块的全部增量。"""
        key = self._text_key(event, kind)
        field = "text" if kind == "output_text" else "refusal"
        text = event.get(field, "")
        if not isinstance(text, str) or not text.startswith(self.text_parts.get(key, "")):
            raise ValueError("Responses 完成正文与增量不一致")
        self.text_done_parts[key] = text
        if isinstance(event.get("item_id"), str):
            self.text_item_ids[key] = event["item_id"]

    def _repair_empty_terminal_output(self, response: dict) -> dict:
        """仅修复已由正文完成事件证明、但网关遗漏 output 的单文本终态。

        该分支为 New API 等兼容网关保留。工具、多个正文块或非空终态都不能
        推断协议状态，仍由后续严格校验拒绝，避免伪造工具回放或思考状态。
        """
        if response.get("status") != "completed":
            return response
        output = response.get("output")
        if not isinstance(output, list):
            raise ValueError("Responses 完成快照输出结构不合法")
        if output or self.calls or len(self.text_done_parts) != 1:
            return response
        (output_index, content_index, kind), text = next(iter(self.text_done_parts.items()))
        if output_index != 0 or content_index != 0 or set(self.text_parts) - set(self.text_done_parts):
            return response
        field = "text" if kind == "output_text" else "refusal"
        content = {"type": kind, field: text}
        if kind == "output_text":
            content["annotations"] = []
        repaired = deepcopy(response)
        repaired["output"] = [{
            "id": self.text_item_ids.get((output_index, content_index, kind), "responses-fallback-0"),
            "type": "message", "role": "assistant", "status": "completed", "content": [content],
        }]
        return repaired

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
            key = self._text_key(event, "refusal" if kind == "response.refusal.delta" else "output_text")
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
            if item.get("type") == "function_call":
                return self._call(event["output_index"], item, complete=kind.endswith(".done"))
        if kind == "response.function_call_arguments.delta":
            index, delta = event["output_index"], event["delta"]
            if index not in self.calls or not isinstance(delta, str):
                raise ValueError("Responses 工具增量缺少起始项")
            self.calls[index]["arguments"] += delta
            return [("tool_delta", index, delta)]
        if kind in {"response.completed", "response.incomplete"}:
            response = event["response"]
            expected = "completed" if kind.endswith(".completed") else "incomplete"
            if response.get("status") != expected or response.get("error"):
                raise ValueError("Responses 终态不一致")
            response = self._repair_empty_terminal_output(response)
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
