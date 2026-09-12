"""L0 现行契约场景：斜杠/词汇表/非法上行/幂等/断线重放/卡拒绝。"""

from __future__ import annotations

from ..client import ProbeClient
from ..errors import ProbeError
from ..expect import ExpectMatcher, ProbeAssertion
from .acceptance import AcceptanceReport, _now, drain, new_session, _payload

SLASHES = ("/help", "/cancel", "/stress", "/compact")


async def run_slash_matrix(client: ProbeClient, report: AcceptanceReport) -> None:
    """现行斜杠语义：/help /cancel /stress /compact → direct 拒绝，error 收尾。"""
    for slash in SLASHES:
        mark = len(client.trace.frames)
        await client.send_user_message(slash)
        await client.wait_event("response.completed", timeout_s=60)
        await drain(client, 0.3)
        matcher = ExpectMatcher(client.trace)
        try:
            matcher.completed_with(finish_reason="error", engine="direct")
            matcher.event_whitelist(after_frame=mark)
            matcher.event_ids_monotonic(after_frame=mark)
            texts = [
                str(_payload(f).get("text") or "")
                for f in client.trace.frames[mark:]
                if f.dir == "down" and f.event == "assistant_message"
            ]
            blob = " ".join(texts)
            # 现行文案：仅支持 /stop（早期版本为只支持 /stop，双词兼容）
            if "/stop" not in blob or ("暂不支持" not in blob and "不支持该命令" not in blob):
                raise ProbeAssertion(f"{slash} 拒绝正文缺失：{blob[:100]!r}")
            report.record(f"L0 {slash} direct 拒绝", "PASS")
        except (ProbeAssertion, ProbeError) as exc:
            report.record(f"L0 {slash} direct 拒绝", "FAIL", str(exc))


async def run_stop_idle(client: ProbeClient, report: AcceptanceReport) -> None:
    """/stop 空转：completed(cancelled)，无用户回显/无卡。"""
    mark = len(client.trace.frames)
    await client.send_user_message("/stop")
    await client.wait_event("response.completed", timeout_s=30)
    await drain(client, 0.3)
    matcher = ExpectMatcher(client.trace)
    try:
        matcher.completed_with(finish_reason="cancelled")
        seen = [
            f.event
            for f in client.trace.frames[mark:]
            if f.dir == "down" and f.event in {"user_message", "tool_call", "confirm", "clarify"}
        ]
        if seen:
            raise ProbeAssertion(f"/stop 空转不应出现 {seen}")
        report.record("L0 /stop 空转 cancelled", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L0 /stop 空转 cancelled", "FAIL", str(exc))


async def run_unknown_uplink(client: ProbeClient, report: AcceptanceReport) -> None:
    """非法上行事件 → error(VALIDATION)。"""
    await client.send_raw({"event": "not_an_event", "payload": {}})
    await client.wait_event("error", timeout_s=20)
    matcher = ExpectMatcher(client.trace)
    try:
        matcher.public_headers()
        matcher.error("VALIDATION", "不支持的 WebSocket 事件")
        report.record("L0 非法上行 VALIDATION", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L0 非法上行 VALIDATION", "FAIL", str(exc))


async def run_idempotent(client: ProbeClient, report: AcceptanceReport) -> None:
    """client_message_id 幂等：同键重复只回显一次，不启动第二轮。"""
    key = f"acceptance-idem-{_now()}"
    mark = len(client.trace.frames)
    await client.send_user_message("/help", client_message_id=key)
    await client.wait_event("response.completed", timeout_s=60)
    await client.send_user_message("/help", client_message_id=key)
    await drain(client, 0.5)
    matcher = ExpectMatcher(client.trace)
    try:
        matcher.completed_once(after_frame=mark)
        report.record("L0 client_message_id 幂等", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L0 client_message_id 幂等", "FAIL", str(exc))


async def run_reconnect_replay(client: ProbeClient, report: AcceptanceReport) -> None:
    """断线按 last_event_id 重连补发：无瞬态帧、词汇表版本一致。"""
    await client.send_user_message("/help")
    await client.wait_event("response.completed", timeout_s=60)
    await drain(client, 0.3)
    cursor = client.last_event_id
    await client.disconnect()
    await client.connect(session_id=client.session_id, last_event_id=cursor)
    await drain(client, 0.8)
    matcher = ExpectMatcher(client.trace)
    try:
        matcher.replay_no_transient()
        matcher.vocab_version_consistent()
        report.record("L0 断线重连补发", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L0 断线重连补发", "FAIL", str(exc))


async def run_vocab_headers(client: ProbeClient, report: AcceptanceReport) -> None:
    """V1.71 #4：公共头完整 + vocab_version=event.v5 恒发。

    event_id 单调性只限本连接窗口（跨会话/重连按连接重置，live 契约如此）；
    词汇表版本服务端对每帧统一注入，可全 trace 校验。
    """
    mark = len(client.trace.frames)
    await drain(client, 0.2)
    matcher = ExpectMatcher(client.trace)
    try:
        matcher.public_headers()
        matcher.event_whitelist(after_frame=mark)
        matcher.event_ids_monotonic(after_frame=mark)
        matcher.vocab_version_consistent()
        report.record("V1.71 词汇表 event.v5 + 白名单", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("V1.71 词汇表 event.v5 + 白名单", "FAIL", str(exc))


async def run_cards_reject_no_card(client: ProbeClient, report: AcceptanceReport) -> None:
    """三类卡回执无卡时 fail-closed：error(VALIDATION 无待确认卡)。"""
    probes = [
        ("clarify_reply", {"id": "no-card", "answers": [{"id": "q1", "answer": "x"}]}),
        ("tool_approval_ack", {"id": "no-card", "action": "approve"}),
        ("confirm_ack", {"ok": True, "patch": {"run": {"sample_size": 1}, "with_stress": False}}),
    ]
    for event, payload in probes:
        await client.send_raw({"event": event, "payload": payload})
        await client.wait_event("error", timeout_s=20)
        matcher = ExpectMatcher(client.trace)
        try:
            matcher.no_pending_confirm(event)
            report.record(f"V1.72/73 无卡拒绝 {event}", "PASS")
        except (ProbeAssertion, ProbeError) as exc:
            report.record(f"V1.72/73 无卡拒绝 {event}", "FAIL", str(exc))


__all__ = [
    "SLASHES",
    "run_slash_matrix",
    "run_stop_idle",
    "run_unknown_uplink",
    "run_idempotent",
    "run_reconnect_replay",
    "run_vocab_headers",
    "run_cards_reject_no_card",
    "new_session",
]
