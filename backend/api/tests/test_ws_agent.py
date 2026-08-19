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
    _deep_merge,
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
