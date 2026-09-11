"""会话标题自适应提取与修改接口单测。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agent.title import fallback_title
from app.routers.sessions import _auto_fill_session_titles
from app.schemas import SessionTitleUpdate


def test_fallback_title_strips_references_and_markdown():
    """验证 fallback_title 对引用、Markdown 标题/列表及引号的清洗能力。"""
    raw1 = "[引用对话记忆]\n这是历史记忆\n[/引用对话记忆] 帮我分析最新的评测指标"
    assert fallback_title(raw1) == "帮我分析最新的评测指标"

    raw2 = "### 评测大模型在数学数据集上的表现"
    assert fallback_title(raw2) == "评测大模型在数学数据集上的表现"

    raw3 = "- 检查系统的健康状态"
    assert fallback_title(raw3) == "检查系统的健康状态"

    raw4 = '“压测报告生成”'
    assert fallback_title(raw4) == "压测报告生成"


def test_auto_fill_session_titles_from_agent_events():
    """验证 _auto_fill_session_titles 从 agent_events 提取首条用户消息并回写标题。"""
    db = MagicMock()
    session = SimpleNamespace(id="s-1", title="新会话")

    agent_event_row = (
        "s-1",
        {
            "data": {"content": "请对该模型进行基准测试"},
            "extensions": {"display_content": "请对该模型进行基准测试"},
        },
    )
    query_mock = MagicMock()
    query_mock.filter.return_value.order_by.return_value.all.return_value = [agent_event_row]
    db.query.return_value = query_mock

    _auto_fill_session_titles(db, [session])

    assert session.title == "请对该模型进行基准测试"
    db.commit.assert_called_once()


def test_auto_fill_session_titles_skips_custom_title():
    """验证已拥有自定义标题的会话不被重写。"""
    db = MagicMock()
    session = SimpleNamespace(id="s-2", title="我的定制评测")

    _auto_fill_session_titles(db, [session])

    assert session.title == "我的定制评测"
    db.query.assert_not_called()
    db.commit.assert_not_called()


def test_session_title_schema_validation():
    """验证 SessionTitleUpdate 字段校验约束。"""
    update = SessionTitleUpdate(title="新标题")
    assert update.title == "新标题"

    with pytest.raises(Exception):
        SessionTitleUpdate(title="")

    with pytest.raises(Exception):
        SessionTitleUpdate(title="a" * 201)
