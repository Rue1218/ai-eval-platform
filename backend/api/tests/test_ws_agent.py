"""WS Agent 契约单测（M1 出口：短票拒绝与确认卡相关纯逻辑）。

无数据库环境下可测的部分：无效短票在查询数据库前即被 4401 拒绝；
确认卡 patch 深合并、LLM JSON 容错解析、资产名称匹配回退与 pong
心跳事件体均为纯函数。
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.routers.ws import (
    _USED_WS_TICKETS,
    _consume_ws_ticket,
    _deep_merge,
    _match_dataset,
    _match_profiles,
    _parse_llm_json,
    _pong_body,
    _visible_reply,
)


def test_ws_rejects_invalid_ticket_with_4401():
    """无效短票：连接在触达数据库前被关闭，关闭码为 4401。"""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/agent?ticket=not-a-jwt"):
            pass
    assert exc.value.code == 4401


def test_ws_ticket_is_single_use():
    """单次短票（PRD F-AGT-01）：同一 jti 仅首次连接可用，第二次拒绝。"""
    _USED_WS_TICKETS.clear()
    payload = {"type": "ws_ticket", "jti": "ticket-once-1"}

    assert _consume_ws_ticket(payload) is True  # 首次连接放行
    assert _consume_ws_ticket(payload) is False  # 同票再次连接拒绝
    assert _consume_ws_ticket({"type": "ws_ticket"}) is False  # 无 jti 视为非法票
    assert _USED_WS_TICKETS["ticket-once-1"] > 0


def test_ws_ticket_gc_cleans_expired_entries():
    """过期票据记录在下一次消费时被机会式清理，不无限增长。"""
    _USED_WS_TICKETS.clear()
    _USED_WS_TICKETS["stale-jti"] = 1.0  # 已过期的历史记录

    assert _consume_ws_ticket({"type": "ws_ticket", "jti": "fresh-jti"}) is True
    # 阈值未到不强制清理，但新票据正常记录
    assert "fresh-jti" in _USED_WS_TICKETS
    # 手动注入超阈值数量的过期条目后触发清理
    for i in range(1100):
        _USED_WS_TICKETS[f"old-{i}"] = 1.0
    assert _consume_ws_ticket({"type": "ws_ticket", "jti": "another-jti"}) is True
    assert "stale-jti" not in _USED_WS_TICKETS
    assert "old-0" not in _USED_WS_TICKETS
    assert "another-jti" in _USED_WS_TICKETS
    _USED_WS_TICKETS.clear()


def test_pong_body_matches_contract_shape():
    """pong 事件：公共头结构完整、payload 为空对象（API.md §4.3）。"""
    body = _pong_body("session-1", 42)

    assert body["event"] == "pong"
    assert body["session_id"] == "session-1"
    assert body["task_id"] is None
    assert body["event_id"] == 42
    assert body["payload"] == {}
    assert isinstance(body["ts"], str) and body["ts"]


def test_deep_merge_keeps_defaults_and_overrides_leaf():
    """确认卡 patch 深合并：未修改的嵌套默认值保留，叶子字段被覆盖。"""
    base = {"kind": "benchmark", "run": {"concurrency": 5, "timeout_s": 60}, "with_stress": False}
    merged = _deep_merge(dict(base), {"run": {"concurrency": 8}, "with_stress": True})

    assert merged["run"]["concurrency"] == 8
    assert merged["run"]["timeout_s"] == 60  # 未提及的默认值保留
    assert merged["with_stress"] is True
    assert merged["kind"] == "benchmark"


def test_visible_reply_progressive_extraction():
    """流式 reply 增量提取：未现键为空、部分值逐增、闭合后不再增长。"""
    # 未出现 reply 键：无可见文本（自然降级为终帧整体渲染）
    assert _visible_reply('{"intent": "chat"') == ""
    assert _visible_reply('') == ""
    # 部分值：随缓冲增长可见文本逐增
    assert _visible_reply('{"reply": "你好') == "你好"
    assert _visible_reply('{"reply": "你好，我是评测') == "你好，我是评测"
    # 值闭合后：后续 JSON 字段不再进入可见文本
    assert _visible_reply('{"reply": "完成", "intent": "benchmark"}') == "完成"


def test_visible_reply_handles_escapes():
    """转义处理：换行/引号/反斜杠正确还原，不完整转义尾部暂不展示。"""
    assert _visible_reply('{"reply": "第一行\\n第二行') == "第一行\n第二行"
    assert _visible_reply('{"reply": "他说\\"你好\\"') == '他说"你好"'
    assert _visible_reply('{"reply": "反斜杠\\\\') == "反斜杠\\"
    # 尾部单独的反斜杠：转义不完整，暂不展示
    assert _visible_reply('{"reply": "尾部\\') == "尾部"
    # \uXXXX 完整时还原，不完整时尾部暂不展示
    assert _visible_reply('{"reply": "中文\\u4e2d') == "中文中"
    assert _visible_reply('{"reply": "中文\\u4e') == "中文"


def test_parse_llm_json_tolerates_markdown_fence():
    """LLM 输出容错解析：允许 markdown 代码围栏与首尾解释文字。"""
    raw = '好的，以下是解析结果：\n```json\n{"intent": "benchmark", "reply": "收到"}\n```'
    data = _parse_llm_json(raw)

    assert data["intent"] == "benchmark"


def test_parse_llm_json_rejects_plain_text():
    """无 JSON 对象的输出必须显式失败，触发调用方回退规则版。"""
    with pytest.raises(ValueError):
        _parse_llm_json("抱歉，我不明白你的意思。")


def test_match_profiles_prefers_named_and_falls_back_to_first():
    """协议档匹配：命中名称取命中项，未提及或未命中回退首个。"""
    items = [
        {"id": "p-1", "name": "GPT-4o", "model": "gpt-4o"},
        {"id": "p-2", "name": "Claude", "model": "claude-3"},
    ]
    assert _match_profiles(items, ["Claude"]) == ["p-2"]
    assert _match_profiles(items, ["p-1"]) == ["p-1"]
    assert _match_profiles([], ["任何"]) == []


def test_match_dataset_prefers_named_and_falls_back_to_first():
    """数据集匹配：命中名称取命中项，未提及回退首个。"""
    items = [
        {"id": "d-1", "name": "smoke-20"},
        {"id": "d-2", "name": "golden-100"},
    ]
    assert _match_dataset(items, "golden") == "d-2"
    assert _match_dataset(items, "") == "d-1"
    assert _match_dataset(items, "未知") == "d-1"
    assert _match_dataset([], "任何") is None


def test_classify_intent_chat_vs_benchmark():
    """意图分类：闲聊与问候识别为 chat，绝不无脑兜底为 benchmark 下单。"""
    from app.routers.ws import _classify_intent

    assert _classify_intent("介绍一下你") == "chat"
    assert _classify_intent("你好") == "chat"
    assert _classify_intent("你是谁？你能帮我做什么？") == "chat"
    assert _classify_intent("随便聊聊") == "chat"

    assert _classify_intent("对比两个模型的基准表现") == "benchmark"
    assert _classify_intent("帮我跑一下 benchmark") == "benchmark"
    assert _classify_intent("根据 PRD 生成测试用例") == "testcase"
    assert _classify_intent("评测知识库召回效果") == "rag"
    assert _classify_intent("解读这份评测报告") == "report"
