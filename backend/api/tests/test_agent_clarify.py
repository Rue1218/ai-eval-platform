"""M4 澄清卡节点单测（阶段 3，O-11）；不触碰 WS/DB/真实模型。"""

import asyncio

from langgraph.graph import END, START, StateGraph

from app.agent.clarify import CLARIFY_INTERRUPT_TYPE, clarify_node
from app.harness.memory import GraphState, InMemoryCheckpointer, SerializableRequest


def _request() -> SerializableRequest:
    """构造最小可序列化请求。"""
    return SerializableRequest(
        config={"protocol": "openai_chat", "model": "test-model"},
        messages=({"role": "user", "content": "需要补充信息"},),
    )


def _build_graph():
    """含澄清节点的最小图（interrupt 语义验证）。"""
    graph = StateGraph(GraphState)
    graph.add_node("clarify", clarify_node)
    graph.add_edge(START, "clarify")
    graph.add_edge("clarify", END)
    return graph.compile(checkpointer=InMemoryCheckpointer())


def _collect(compiled, config: dict):
    """消费图 astream 输出（单 mode="updates" 的 dict 帧；含 __interrupt__ 键）。"""

    async def run():
        out: list[dict] = []
        async for frame in compiled.astream(
            {"request": _request()},
            config=config,
            stream_mode="updates",
        ):
            out.append(frame)
        return out

    return asyncio.run(run())


def test_clarify_interrupts_graph_with_payload() -> None:
    """澄清节点 interrupt() 暂停图，产出含 id/question/options 的载荷。"""
    thread = {"configurable": {"thread_id": "c1"}}
    frames = _collect(_build_graph(), thread)
    interrupt_frames = [
        frame["__interrupt__"] for frame in frames if "__interrupt__" in frame
    ]
    assert len(interrupt_frames) == 1
    interrupt = interrupt_frames[0][0]  # Interrupt 对象（(Interrupt,) 元组包裹）
    payload = interrupt.value  # value 即载荷 dict
    assert payload["type"] == CLARIFY_INTERRUPT_TYPE
    assert payload["id"]
    assert payload["question"]
    assert payload["options"] is None


def test_clarify_resume_with_answer() -> None:
    """用户回复后 Command(resume) 恢复图，节点返回 clarify_answer。"""
    from langgraph.types import Command

    compiled = _build_graph()
    thread = {"configurable": {"thread_id": "c2"}}
    _collect(compiled, thread)

    async def resume():
        out: list[dict] = []
        async for frame in compiled.astream(
            Command(resume="数据集用 mmlu"),
            config=thread,
            stream_mode="updates",
        ):
            out.append(frame)
        return out

    frames = asyncio.run(resume())
    assert frames, "恢复后应产出节点更新"
    clarify_update = [
        value
        for frame in frames
        for value in frame.values()
        if isinstance(value, dict) and "clarify_answer" in value
    ]
    assert clarify_update and clarify_update[0]["clarify_answer"] == "数据集用 mmlu"
