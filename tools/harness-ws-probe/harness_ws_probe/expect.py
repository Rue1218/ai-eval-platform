"""协议断言：公共头、事件白名单、斜杠与确认卡形状。"""

from __future__ import annotations

from typing import Any

from .protocol import DOWNLINK_EVENTS, FORBIDDEN_DOWNLINK, PUBLIC_HEADER_KEYS, is_transient
from .recorder import TraceFrame, TraceRecorder


class ProbeAssertion(AssertionError):
    """契约不满足：带中文说明，便于 CLI / pytest 直接展示。"""


def _payload(frame: TraceFrame) -> dict[str, Any]:
    raw = frame.raw
    inner = raw.get("payload")
    return inner if isinstance(inner, dict) else {}


def _down_named(trace: TraceRecorder, name: str) -> list[TraceFrame]:
    return [item for item in trace.downlink() if item.event == name]


class ExpectMatcher:
    """对一条 Trace 做可组合断言（API.md §4.2–§4.4）。"""

    def __init__(self, trace: TraceRecorder) -> None:
        self.trace = trace

    def public_headers(self) -> None:
        for item in self.trace.downlink():
            raw = item.raw
            missing = [key for key in PUBLIC_HEADER_KEYS if key not in raw]
            if missing:
                raise ProbeAssertion(f"下行缺少公共头 {missing} event={item.event}")
            if raw.get("event") != item.event:
                raise ProbeAssertion("公共头 event 与录制事件名不一致")

    def event_whitelist(self, *, after_frame: int = 0) -> None:
        for item in self.trace.downlink():
            if item.frame_index < after_frame:
                continue
            if item.event in FORBIDDEN_DOWNLINK:
                raise ProbeAssertion(f"禁止的旧事件名：{item.event}")
            if item.event and item.event not in DOWNLINK_EVENTS:
                raise ProbeAssertion(f"未知下行事件：{item.event}")

    def event_ids_monotonic(self, *, after_frame: int = 0) -> None:
        last = 0
        for item in self.trace.downlink():
            if item.frame_index < after_frame:
                continue
            if not item.persistent:
                continue
            if item.event_id is None:
                raise ProbeAssertion(f"持久事件缺少 event_id：{item.event}")
            if item.event_id <= last:
                raise ProbeAssertion(
                    f"event_id 必须严格递增：{item.event_id} <= {last}"
                )
            last = item.event_id

    def no_forbidden_uplink(self, allowed_raw: bool = False) -> None:
        """默认上行只能是五类；allowed_raw 时允许场景探测用的非法事件帧。"""
        from .protocol import UPLINK_EVENTS

        for item in self.trace.uplink():
            if item.event in UPLINK_EVENTS:
                continue
            if allowed_raw:
                continue
            raise ProbeAssertion(f"非法上行事件：{item.event}")

    def error(self, code: str, contains: str) -> TraceFrame:
        for item in _down_named(self.trace, "error"):
            payload = _payload(item)
            if payload.get("code") == code and contains in str(payload.get("message") or ""):
                return item
        raise ProbeAssertion(f"未找到 error {code} 含「{contains}」")

    def help_completed(self) -> None:
        texts: list[str] = []
        for item in _down_named(self.trace, "assistant_message"):
            texts.append(str(_payload(item).get("text") or ""))
        blob = "\n".join(texts)
        if "/cancel" not in blob or "/stress" not in blob:
            raise ProbeAssertion("/help 正文必须提到 /cancel 与 /stress")
        if not _down_named(self.trace, "response.completed"):
            raise ProbeAssertion("/help 回合缺少 response.completed")

    def cancel_empty(self) -> None:
        self.error("VALIDATION", "没有可取消")

    def stress_confirm(self) -> TraceFrame:
        cards = _down_named(self.trace, "confirm")
        if not cards:
            raise ProbeAssertion("/stress 未发出 confirm")
        card = cards[-1]
        payload = _payload(card)
        kind = payload.get("kind")
        if kind == "stress":
            raise ProbeAssertion("对话路径不得发出 kind=stress 确认卡")
        if kind not in {"benchmark", "rag"}:
            raise ProbeAssertion(f"/stress 确认卡 kind 非法：{kind}")
        if payload.get("with_stress") is not True:
            raise ProbeAssertion("/stress 确认卡必须 with_stress=true")
        ids = payload.get("profile_ids") or []
        if not isinstance(ids, list):
            raise ProbeAssertion("profile_ids 必须是列表")
        return card

    def confirm_cancelled(self) -> None:
        acks = _down_named(self.trace, "confirm_ack")
        if not acks:
            raise ProbeAssertion("取消确认后没有 confirm_ack")
        payload = _payload(acks[-1])
        if payload.get("ok") is not False:
            raise ProbeAssertion("取消确认的 confirm_ack.ok 必须为 false")
        if payload.get("task_id"):
            raise ProbeAssertion("取消确认不得带 task_id")
        after = acks[-1].t_ms
        for item in self.trace.downlink():
            if item.t_ms < after:
                continue
            if item.event in {"progress", "report"}:
                raise ProbeAssertion("取消确认后不得出现 progress/report")

    def confirm_enqueued(self) -> str:
        acks = _down_named(self.trace, "confirm_ack")
        if not acks:
            raise ProbeAssertion("入队后没有 confirm_ack")
        payload = _payload(acks[-1])
        if payload.get("ok") is not True:
            raise ProbeAssertion("入队 confirm_ack.ok 必须为 true")
        task_id = payload.get("task_id")
        if not task_id:
            raise ProbeAssertion("入队必须返回 task_id")
        return str(task_id)

    def chat_turn_contract(self, *, after_frame: int = 0) -> None:
        """闲聊/真模型回合：completed 收尾；有思考链时 think_final 必须在它之前。

        对齐 API.md §4.3：``response.completed`` 是整轮结束；思考增量不得一字一帧。
        """
        frames = [item for item in self.trace.frames[after_frame:] if item.dir == "down"]
        persistent = [item for item in frames if item.persistent]
        if not persistent:
            raise ProbeAssertion("本轮没有持久下行")
        if persistent[-1].event != "response.completed":
            names = [item.event for item in persistent]
            raise ProbeAssertion(
                f"本轮最后持久事件必须是 response.completed，实际顺序 {names}"
            )
        thinks = [
            item
            for item in frames
            if item.event == "thought" and _payload(item).get("stream") == "think"
        ]
        finals = [
            item
            for item in frames
            if item.event == "thought" and _payload(item).get("stream") == "think_final"
        ]
        if thinks and not finals:
            raise ProbeAssertion("有 thought.stream=think 必须落 think_final")
        if finals:
            final_at = next(
                (
                    index
                    for index, item in enumerate(persistent)
                    if item.event == "thought"
                    and _payload(item).get("stream") == "think_final"
                ),
                None,
            )
            done_at = next(
                (
                    index
                    for index, item in enumerate(persistent)
                    if item.event == "response.completed"
                ),
                None,
            )
            if final_at is None or done_at is None or final_at > done_at:
                raise ProbeAssertion(
                    "think_final 必须在 response.completed 之前（API.md §4.3）"
                )
        if len(thinks) >= 24:
            tiny = sum(
                1
                for item in thinks
                if len(str(_payload(item).get("text") or "")) <= 2
            )
            if tiny * 2 >= len(thinks):
                raise ProbeAssertion(
                    f"思考增量疑似一字一帧：{tiny}/{len(thinks)} 帧不超过 2 字"
                )
        hidden_needles = (
            "here's a thinking process",
            "analyze user input",
            "identify key points",
        )
        for item in [*thinks, *finals]:
            blob = str(_payload(item).get("text") or "").lower()
            if any(needle in blob for needle in hidden_needles):
                raise ProbeAssertion(
                    "thought 不得暴露隐藏思维链（Here's a thinking process / Analyze User Input）"
                )

    def completed_once(self, *, after_frame: int = 0) -> None:
        done = [
            item
            for item in self.trace.frames[after_frame:]
            if item.dir == "down" and item.event == "response.completed"
        ]
        if len(done) != 1:
            raise ProbeAssertion(f"期望恰好一轮 response.completed，实际 {len(done)}")

    def replay_no_transient(self) -> None:
        for item in self.trace.downlink():
            if item.event == "assistant_delta":
                raise ProbeAssertion("重连补发不得包含 assistant_delta")
            if is_transient(item.raw) and item.event != "pong":
                raise ProbeAssertion(f"重连补发不得包含瞬态 {item.event}")

    def tool_call_ids_paired(self) -> None:
        calls = {
            _payload(item).get("call_id")
            for item in _down_named(self.trace, "tool_call")
        }
        results = {
            _payload(item).get("call_id")
            for item in _down_named(self.trace, "tool_result")
        }
        calls.discard(None)
        results.discard(None)
        missing = calls - results
        if missing:
            raise ProbeAssertion(f"tool_result 缺少 call_id：{missing}")

    def vocab_version_consistent(self, expected: str | None = None) -> None:
        """V1.71 词汇表版本化：公共头 vocab_version 存在且恒等于当前版本。

        对齐 API.md §4.2（服务端恒发可选字段）与 shared/event_vocab.py 演进纪律。
        服务端对每帧（含 pong 瞬态帧）统一注入，故对全部下行帧校验；
        空会话仅有 pong 时同样可校验。
        """
        from .protocol import EXPECTED_VOCAB_VERSION

        expected = expected or EXPECTED_VOCAB_VERSION
        seen = 0
        for item in self.trace.downlink():
            seen += 1
            version = item.raw.get("vocab_version")
            if version != expected:
                raise ProbeAssertion(
                    f"下行帧 vocab_version 期望 {expected}，实际 {version!r} event={item.event}"
                )
        if seen == 0:
            raise ProbeAssertion("没有下行帧可校验 vocab_version")

    def no_pending_confirm(self, event: str, code: str = "VALIDATION") -> None:
        """卡片回执在无卡时的 fail-closed：error(VALIDATION)，绝不 resume。

        V1.72/1.73：clarify_reply / tool_approval_ack / confirm_ack 在
        pending_confirm 为空时一律拒绝（清卡后重复 ack 走同一路径）。
        """
        codes = {
            "clarify_reply": ("无待澄清卡", "无待处理的澄清卡", "无待确认"),
            "tool_approval_ack": ("无待审批卡", "无待确认"),
            "confirm_ack": ("无待确认卡", "无待确认"),
        }
        needles = codes.get(event, ("无待",))
        for item in _down_named(self.trace, "error"):
            payload = _payload(item)
            if payload.get("code") != code:
                continue
            message = str(payload.get("message") or "")
            if any(needle in message for needle in needles):
                return item
        raise ProbeAssertion(f"{event} 无卡时应 error({code} 无待确认卡)")

    def card_payload_clean(self, event: str) -> TraceFrame:
        """卡事件 payload 不得携带 meta/thread_id/resume_nonce/nonce（B 路线剥离）。"""
        card = _down_named(self.trace, event)[-1]
        payload = _payload(card)
        for needle in ("meta", "thread_id", "resume_nonce", "nonce", "created_at"):
            if needle in payload:
                raise ProbeAssertion(
                    f"{event} payload 泄漏内部字段 {needle}（B 路线只投影白名单）"
                )
        return card

    def completed_with(self, *, finish_reason: str, engine: str | None = None) -> TraceFrame:
        """断言最近的 response.completed 收尾语义（含可选 engine 审计字段）。"""
        done = _down_named(self.trace, "response.completed")
        if not done:
            raise ProbeAssertion("缺少 response.completed")
        frame = done[-1]
        payload = _payload(frame)
        if payload.get("finish_reason") != finish_reason:
            raise ProbeAssertion(
                f"finish_reason 期望 {finish_reason}，实际 {payload.get('finish_reason')}"
            )
        if engine is not None and payload.get("engine") != engine:
            raise ProbeAssertion(f"engine 期望 {engine}，实际 {payload.get('engine')}")
        return frame
