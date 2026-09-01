"""工作链路循环：计划内清单/提问工具成功后应从剩余步骤移除。"""

from app.agent.loop import confirm_plan_ready_for_reflect, remaining_plan_tools
from app.harness.contracts import Observation


def test_remaining_plan_tools_drops_board_tools_after_success() -> None:
    state = {
        "plan": {
            "delivery": "confirm",
            "tools_needed": ["TaskCreate", "ask_user_question", "read"],
        },
        "observations": [
            Observation(tool="TaskCreate", text="已创建", ok=True),
            Observation(tool="ask_user_question", text="已回复", ok=True),
        ],
    }
    assert remaining_plan_tools(state) == ("read",)
    assert confirm_plan_ready_for_reflect(state) is False


def test_confirm_plan_ready_when_only_meta_tools_remain() -> None:
    state = {
        "plan": {"delivery": "confirm", "tools_needed": ["task", "TaskCreate"]},
        "observations": [
            Observation(tool="task", text="清单", ok=True),
            Observation(tool="TaskCreate", text="已创建", ok=True),
        ],
    }
    assert remaining_plan_tools(state) == ()
    assert confirm_plan_ready_for_reflect(state) is True
