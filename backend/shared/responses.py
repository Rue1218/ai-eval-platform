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
            return [("text", event.get("delta", ""))]
        if kind == "response.reasoning_summary_text.delta":
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
            events = []
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
