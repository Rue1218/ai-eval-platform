"""澄清卡 interrupt() 节点（M4 阶段 3，O-11）。

澄清卡与确认卡**互斥**：澄清不建任务、不占回合预算、不写
``sessions.pending_confirm``。节点调用 LangGraph ``interrupt()`` 暂停图；
``__interrupt__`` 帧由 ws.py 翻译为 ``clarify`` 事件发出（事件桥接契约）。
用户回复后由 ws.py 转 ``Command(resume, update={'clarify_answer': answer})``
恢复图（M9 §3.5.1）。``id`` 为本次澄清唯一标识（uuid4），用于匹配前端
``clarify_reply.id``。
"""

from __future__ import annotations

from uuid import uuid4

from langgraph.types import interrupt

from app.harness.memory import GraphState

# interrupt() 载荷的 type 标识（ws.py 翻译层据此识别澄清卡）
CLARIFY_INTERRUPT_TYPE = "clarify"


def _clarify_question(state: GraphState) -> str:
    """从规划产物提取澄清问题；缺省用通用补槽提示。"""
    plan = state.get("plan")
    if isinstance(plan, dict):
        intent = str(plan.get("intent") or "").strip()
        notes = str(plan.get("notes") or "").strip()
        if intent:
            return f"规划「{intent}」还缺必要信息，请补充数据集、协议档或范围后再继续。"
        if notes:
            return f"需要补充信息后才能继续：{notes[:120]}"
    return "需要补充信息后才能继续，请回复以下问题："


def clarify_node(state: GraphState) -> dict:
    """澄清卡节点：产出澄清意图并 ``interrupt()`` 暂停图。

    - ``interrupt`` 载荷：``{'type': 'clarify', 'id', 'question', 'options'}``
      （ws.py 翻译为 ``NodeEvent(kind='clarify')`` 并 emit）；
    - 恢复后返回 ``{'clarify_answer': answer}`` 供后续节点消费；
    - 不建任务、不占回合预算、不写 ``pending_confirm``（与 confirm 互斥）。
    """
    clarify_id = uuid4().hex
    question = _clarify_question(state)
    answer = interrupt(
        {
            "type": CLARIFY_INTERRUPT_TYPE,
            "id": clarify_id,
            "question": question,
            "options": None,
        }
    )
    return {
        "clarify_answer": str(answer) if answer is not None else "",
        "clarify_id": clarify_id,
        "force_replan": True,
    }
