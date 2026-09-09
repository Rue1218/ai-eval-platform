"""引擎回合（chat/agent/read）与 V1.8 尽力触发场景（澄清卡等）。"""

from __future__ import annotations

from typing import Any

from ..client import ProbeClient
from ..errors import ProbeError
from ..expect import ExpectMatcher, ProbeAssertion
from ..recorder import TraceFrame
from .acceptance import AcceptanceReport, MAX_WAIT_TURN, drain, _payload

READ_PROMPTS = [
    "用 read 工具读取 /tmp/nonexistent.txt 看是否存在，直接输出结果",
    "立即调用 read 工具读取 /tmp/nonexistent.txt，只报告工具返回内容，不要解释",
    "必须调用 read 工具（参数 path=/tmp/nonexistent.txt），读取结果后简短汇报",
]

CLARIFY_PROMPTS = [
    "帮我创建一个 benchmark 评测任务，但请先问我两个问题澄清：数据集用哪个、要不要压测",
    "请先调用提问工具问我需要澄清的问题（数据集与样本量），再开始评测任务",
]


def _cards(client: ProbeClient, mark: int, event: str) -> list[TraceFrame]:
    return [
        f for f in client.trace.frames[mark:]
        if f.dir == "down" and f.event == event
    ]


async def run_chat_engine(client: ProbeClient, report: AcceptanceReport) -> None:
    """L2 chat：流式正文 → completed(stop)，engine=chat 审计字段。"""
    mark = len(client.trace.frames)
    try:
        await client.send_user_message("用一句话介绍你自己")
        done = await client.wait_event("response.completed", timeout_s=MAX_WAIT_TURN)
        await drain(client, 0.4)
        matcher = ExpectMatcher(client.trace)
        matcher.chat_turn_contract(after_frame=mark)
        payload = done.get("payload") or {}
        if payload.get("engine") != "chat":
            raise ProbeAssertion(f"chat 轮 engine 期望 chat，实际 {payload.get('engine')}")
        report.record("L2 chat 引擎审计字段", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L2 chat 引擎审计字段", "FAIL", str(exc))


async def run_agent_read(client: ProbeClient, report: AcceptanceReport) -> None:
    """L3 agent：read 可被选中执行，tool_call/result 成对 + 契约断言。"""
    mark = len(client.trace.frames)
    try:
        calls: list[TraceFrame] = []
        for text in READ_PROMPTS:
            await client.send_user_message(text)
            await client.wait_event("response.completed", timeout_s=MAX_WAIT_TURN)
            await drain(client, 0.4)
            calls = _cards(client, mark, "tool_call")
            if calls:
                break
        if not calls:
            report.record("L3 agent read 工具回合", "NA", "三轮未触发工具调用")
            return
        matcher = ExpectMatcher(client.trace)
        matcher.event_whitelist(after_frame=mark)
        matcher.event_ids_monotonic(after_frame=mark)
        matcher.tool_call_ids_paired()
        matcher.chat_turn_contract(after_frame=mark)
        names = {str(_payload(f).get("name") or "") for f in calls}
        if "read" not in names:
            raise ProbeAssertion(f"期望 read，实际 {names}")
        results = [f for f in client.trace.frames[mark:] if f.dir == "down" and f.event == "tool_result"]
        redacted = all(_payload(f).get("redacted") is not False for f in results)
        report.record("L3 agent read 工具回合", "PASS", f"tools={sorted(names)} redacted={redacted}")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("L3 agent read 工具回合", "FAIL", str(exc))


async def run_context_trim(client: ProbeClient, report: AcceptanceReport) -> None:
    """V1.74 #2：context_trim 为合法持久 kind；出现即校验元信息白名单。"""
    frames = [f for f in client.trace.downlink() if f.event == "context_trim"]
    if not frames:
        report.record("V1.74 context_trim 窗口裁剪", "NA", "短会话未触发裁剪")
        return
    payload = _payload(frames[-1])
    allowed = {"reason", "dropped", "kept", "in_scope_total", "keep_from_id", "limit"}
    extra = set(payload) - allowed
    if extra:
        report.record("V1.74 context_trim payload 白名单", "FAIL", f"多余字段 {sorted(extra)}")
        return
    report.record("V1.74 context_trim 留痕元信息", "PASS")


async def run_fabrication(client: ProbeClient, report: AcceptanceReport) -> None:
    """V1.75 P3：fabrication 为合法持久 kind；出现即校验结构。"""
    frames = [f for f in client.trace.downlink() if f.event == "fabrication"]
    if not frames:
        report.record("V1.75 fabrication 编造对账", "NA", "本回合无编造声明")
        return
    payload = _payload(frames[-1])
    missing = [k for k in ("claim", "repairs") if k not in payload]
    if missing:
        report.record("V1.75 fabrication payload 结构", "FAIL", f"缺 {missing}")
        return
    report.record("V1.75 fabrication 编造对账留痕", "PASS")


async def run_clarify_try(client: ProbeClient, report: AcceptanceReport) -> None:
    """V1.72 #1：尽力触发 ask_user_question 澄清卡；成功则作答收尾。"""
    mark = len(client.trace.frames)
    try:
        cards: list[TraceFrame] = []
        for text in CLARIFY_PROMPTS:
            await client.send_user_message(text)
            try:
                await client.wait_event("response.completed", timeout_s=MAX_WAIT_TURN)
            except ProbeError:
                pass
            await drain(client, 0.4)
            cards = _cards(client, mark, "clarify")
            if cards:
                break
        if not cards:
            report.record("V1.72 clarify 澄清卡触发", "NA", "模型未走 ask_user_question")
            return
        card = cards[-1]
        payload = _payload(card)
        questions = payload.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ProbeAssertion("clarify 卡 questions[] 缺失")
        for q in questions:
            for key in ("id", "question", "type"):
                if key not in q:
                    raise ProbeAssertion(f"clarify 题目缺 {key}")
        ExpectMatcher(client.trace).card_payload_clean("clarify")
        answers = []
        for q in questions:
            if q.get("type") == "text":
                answers.append({"id": q["id"], "custom": "是"})
            else:
                options = q.get("options") or []
                label = options[0]["label"] if options else "是"
                answers.append({"id": q["id"], "selected": [label]})
        await client.send_clarify_reply(str(payload.get("id")), answers)
        await client.wait_event("clarify_ack", timeout_s=30)
        try:
            await client.wait_event("response.completed", timeout_s=MAX_WAIT_TURN)
        except ProbeError:
            pass
        report.record("V1.72 clarify 作答 → clarify_ack", "PASS")
    except (ProbeAssertion, ProbeError) as exc:
        report.record("V1.72 clarify 作答 → clarify_ack", "FAIL", str(exc))
