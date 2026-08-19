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
    _is_smalltalk,
    _match_dataset,
    _match_profiles,
    _parse_llm_json,
    _pong_body,
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


def test_is_smalltalk_matches_greetings_only():
    """闲聊快速通道：仅整词打招呼/感谢/极短确认命中，评测指令绝不误伤。"""
    # 命中：各种打招呼、感谢、确认（含大小写、标点、空白）
    assert _is_smalltalk("你好")
    assert _is_smalltalk(" 你好！ ")
    assert _is_smalltalk("hello")
    assert _is_smalltalk("HI")
    assert _is_smalltalk("在吗")
    assert _is_smalltalk("谢谢！")
    assert _is_smalltalk("好的")
    assert _is_smalltalk("嗯嗯")
    assert _is_smalltalk("ok~")
    assert _is_smalltalk("收到。")
    # 不命中：真实评测指令与含关键词的句子必须走 LLM
    assert not _is_smalltalk("帮我评测一下 gpt-4o")
    assert not _is_smalltalk("你好，我要发起一次基准评测")
    assert not _is_smalltalk("压测")
    assert not _is_smalltalk("用 smoke 数据集跑一次评测")


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
