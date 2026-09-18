"""按 Attempt 无损拼装正文、工具参数和供应商原始状态；完整性检查前不执行工具。"""

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from app.llm.loop_contracts import (
    Done,
    Message,
    ProviderItemDelta,
    ProviderItemEnd,
    ProviderItemStart,
    ReasoningDelta,
    StreamChunk,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
)


@dataclass
class _BufferedToolCall:
    """保留同一 index 的调用身份及原始 JSON 碎片。"""

    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)

    def as_message_call(self) -> dict[str, Any]:
        # 只有需要形成完整 assistant/message 时才拼接并解析参数；push() 阶段不做
        # JSON 解析，因此流中间的 ``{"path":`` 不可能被误当作可执行参数。
        """解析完整原串，保留无法执行的参数及其错误。"""
        raw = "".join(self.arguments)
        call: dict[str, Any] = {"id": self.id, "name": self.name, "arguments_raw": raw}
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            # 保留原文和错误，而不是悄悄改成空对象。Scheduler 会把它结算为错误结果。
            call["parse_error"] = f"invalid JSON arguments: {exc.msg}"
            return call

        if not isinstance(parsed, dict):
            call["parse_error"] = "tool arguments must decode to a JSON object"
            return call
        call["args"] = parsed
        return call


class AssistantAttempt:
    """累积单次请求的片段，工具与供应商状态各自保序且不重复生成语义调用。"""

    def __init__(self) -> None:
        """初始化当前对象的独立状态。"""
        self._text: list[str] = []
        self._reasoning: list[str] = []
        self._calls: dict[int, _BufferedToolCall] = {}
        self._items: dict[str, dict[str, Any]] = {}
        self._protocol_errors: list[str] = []
        self._identity_errors: list[str] = []
        self._chunk_index = 0
        self.done: Done | None = None
        self.text_parts: list[dict] | None = None

    def push(self, chunk: StreamChunk) -> int:
        """累积片段并返回本 Attempt 的瞬态下标，不占持久序号。"""
        if self.done is not None:
            raise ValueError("provider emitted a chunk after Done")
        index = self._chunk_index
        self._chunk_index += 1
        if isinstance(chunk, TextDelta):
            # 用户可见正文；graph.py 会选择是否马上推送给浏览器。
            self._text.append(chunk.text)
            if chunk.text_parts is not None:
                self.text_parts = deepcopy(chunk.text_parts)
            elif chunk.output_index is not None:
                # 终态前取消也须持久化已显示的阶段；其他协议没有索引，仍保持普通正文。
                if self.text_parts is None:
                    self.text_parts = []
                part = next((part for part in self.text_parts
                             if part["output_index"] == chunk.output_index), None)
                if part is None:
                    part = {"output_index": chunk.output_index, "phase": None, "text": ""}
                    self.text_parts.append(part)
                part["text"] += chunk.text
                if chunk.phase is not None:
                    part["phase"] = chunk.phase
        elif isinstance(chunk, ReasoningDelta):
            # Provider 的 reasoning 与正文分开保存，避免被拼进最终 answer text。
            self._reasoning.append(chunk.text)
        elif isinstance(chunk, ToolCallStart):
            # 先记录工具身份。后续参数 chunk 可能不再携带 id 或 name。
            call = self._calls.setdefault(chunk.index, _BufferedToolCall())
            if call.id and chunk.id and call.id != chunk.id:
                self._identity_errors.append(f"tool call {chunk.index} changed id")
            if call.name and chunk.name and call.name != chunk.name:
                self._identity_errors.append(f"tool call {chunk.index} changed name")
            call.id = chunk.id or call.id
            call.name = chunk.name or call.name
        elif isinstance(chunk, ToolCallDelta):
            # 只追加原始 JSON 字符串碎片；此处不解析、更不会调用工具。
            self._calls.setdefault(chunk.index, _BufferedToolCall()).arguments.append(
                chunk.arguments_fragment
            )
        elif isinstance(chunk, ProviderItemStart):
            if chunk.item_id in self._items or any(
                item["index"] == chunk.index for item in self._items.values()
            ):
                self._protocol_errors.append("duplicate provider item identity")
            else:
                self._items[chunk.item_id] = {
                    "index": chunk.index, "kind": chunk.kind, "fields": {}, "item": None
                }
        elif isinstance(chunk, ProviderItemDelta):
            item = self._items.get(chunk.item_id)
            if item is None or item["item"] is not None:
                self._protocol_errors.append("provider delta outside an open item")
            else:
                fields = item["fields"]
                fields[chunk.field] = fields.get(chunk.field, "") + chunk.fragment
        elif isinstance(chunk, ProviderItemEnd):
            item = self._items.get(chunk.item_id)
            if item is None or item["item"] is not None:
                self._protocol_errors.append("provider end outside an open item")
            elif not isinstance(chunk.item, dict):
                self._protocol_errors.append("provider item is not an object")
            else:
                # End 是适配器给出的完整 wire 快照，字段可能是结构化数组而非字符串。
                # 增量用于诊断；原样保存快照，禁止把签名/加密块转成展示文本。
                item["item"] = deepcopy(chunk.item)
        elif isinstance(chunk, Done):
            # Done 是 Adapter 认定的流结束信号。缺失 Done 时 graph.py 会将 Attempt
            # 结算为 missing_finish，而不会把缓冲内容当成正常回复。
            self.done = chunk
        else:  # pragma: no cover - 未知片段必须失败关闭，不能静默丢失数据。
            raise TypeError(f"unsupported stream chunk: {type(chunk)!r}")
        return index

    @property
    def text(self) -> str:
        """取得已累积的用户可见正文。"""
        return "".join(self._text)

    @property
    def reasoning_content(self) -> str:
        """取得与正文分开保存的思考内容。"""
        return "".join(self._reasoning)

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        # 按 Provider 给出的调用 index 排序，保证工具结果能按模型声明的顺序配对。
        """按供应商下标返回完整调用，保留原始参数。"""
        return [self._calls[index].as_message_call() for index in sorted(self._calls)]

    def message(self) -> Message:
        """组装规范助手消息；调用者须先检查 Done、身份和协议状态完整性。"""
        message: Message = {"role": "assistant", "content": self.text}
        if self.reasoning_content:
            message["reasoning_content"] = self.reasoning_content
        if self._calls:
            message["tool_calls"] = self.tool_calls
        if self.done is not None and self.done.protocol_state is not None:
            message["protocol_state"] = self.protocol_state
        return message

    def incomplete_call_errors(self) -> list[str]:
        """检查完整调用及参数错误；参数错误由调度器结算而不丢调用。"""
        errors: list[str] = list(self._identity_errors)
        for index, call in enumerate(self.tool_calls):
            if not call.get("id"):
                errors.append(f"tool call {index} has no id")
            if not call.get("name"):
                errors.append(f"tool call {index} has no name")
            if "parse_error" in call:
                errors.append(f"tool call {index}: {call['parse_error']}")
        return errors

    def identity_errors(self) -> list[str]:
        """检查使结果无法配对的身份错误。"""
        errors: list[str] = list(self._identity_errors)
        for index, call in enumerate(self.tool_calls):
            if not call.get("id"):
                errors.append(f"tool call {index} has no id")
            if not call.get("name"):
                errors.append(f"tool call {index} has no name")
        return errors

    @property
    def protocol_state(self) -> dict[str, Any] | None:
        """返回可持久化的状态副本，避免修改事实历史或适配器持有的对象。"""
        if self.done is None or self.done.protocol_state is None:
            return None
        state = self.done.protocol_state
        return deepcopy(state) if isinstance(state, dict) else asdict(state)

    def protocol_errors(self, *, allow_incomplete: bool = False) -> list[str]:
        """正常完成要求状态完整；截断仅允许无回传状态的未闭合诊断块。"""
        errors = list(self._protocol_errors)
        ordered = sorted(self._items.values(), key=lambda item: item["index"])
        if not allow_incomplete and any(item["item"] is None for item in ordered):
            errors.append("provider stream contains an incomplete item")
        state = self.protocol_state
        if ordered and state is None and not allow_incomplete:
            errors.append("provider items have no replay protocol state")
        if state is not None:
            if not isinstance(state.get("items"), list):
                errors.append("protocol state items must be a list")
            elif any(not isinstance(item, dict) for item in state["items"]):
                errors.append("protocol state contains a non-object item")
            elif ordered and state["items"] != [item["item"] for item in ordered]:
                errors.append("protocol state differs from completed provider items")
        return errors
