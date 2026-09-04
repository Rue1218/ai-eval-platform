"""P1（Agent 审计小修）：orchestrator 条件边假守卫与越权引导消息。

覆盖：
1. ``_after_orchestrator`` 不再读 ``workflow_failed``（TAOR 子图不消费 Workflow
   专用字段；旧实现返回映射外的 "END" 是 LangGraph Invalid path 假守卫）；
2. 越权工具失败消息包含中性能力引导（人机回环，缓解 LLM intent 自由文本
   导致 discover 落 general 后模型盲目越权）。
"""


from app.agent import graph, taor_nodes
from app.harness.memory.state import GraphState


def _state(**extra) -> GraphState:
    base: dict = {"request": None, "messages": (), "pending_events": []}
    base.update(extra)
    return GraphState(**base)  # type: ignore[arg-type]


def test_after_orchestrator_ignores_workflow_failed() -> None:
    """TAOR 条件边不读 workflow_failed：误置该字段也按正常分支走（不崩不 END）。"""
    state = _state(workflow_failed=True)
    assert graph._after_orchestrator(state) == "reflect"
    state = _state(workflow_failed=True, pending_tool={"call_id": "c1", "name": "bash"})
    assert graph._after_orchestrator(state) == "tools"


def test_after_orchestrator_branching() -> None:
    assert graph._after_orchestrator(_state()) == "reflect"
    assert graph._after_orchestrator(_state(pending_tool={"call_id": "c1"})) == "tools"


def test_out_of_view_error_includes_capability_guidance() -> None:
    """越权失败消息带中性引导：明确说明用途可重新路由，不泄露执行器存在性。"""
    msg = taor_nodes._error_payload(
        "VALIDATION",
        "非法工具调用：bash（不在本轮视野内）。"
        "如需读取/整理文件或运行脚本等执行类能力，请在请求中明确说明用途"
        "（如『运行脚本…』），Agent 将按声明能力重新路由；不要尝试越权调用。",
    )
    text = msg[0]["payload"]["message"]
    assert "不在本轮视野内" in text
    assert "运行脚本" in text
    assert "不要尝试越权调用" in text
