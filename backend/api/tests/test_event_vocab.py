"""dsh 改进 #4：事件词汇表版本化（D5 测试清单）。

覆盖：注册表完整性断言（防词汇表再漂移）、``_translate_event`` 未知 kind /
版本不符两路径、``_frame`` 公共头 ``vocab_version``、转发护栏
``event_vocab_strict`` 的 false 告警跳过与 true fail-closed 两策略、
``_split_event_version`` 历史无版本行兼容。
"""

from __future__ import annotations

import asyncio

import pytest
from shared.event_vocab import (
    EVENT_VERSION,
    NODE_EVENT_KINDS,
    PERSISTENT_KINDS,
    is_node_event,
    is_persistent,
)

from app.harness.contracts import NodeEventKind, make_event
from app.routers import ws


def test_registry_covers_node_contract_and_emitter_only_kinds() -> None:
    """注册表 = 图可产子集 ∪ 直产子集；直产 kind（回执/任务控制/标题）不缺位。"""
    assert set(NodeEventKind.__args__) == set(NODE_EVENT_KINDS)
    # 图可产事件必须全部持久化（瞬态帧不进词汇表）
    for kind in NODE_EVENT_KINDS:
        assert is_persistent(kind) and is_node_event(kind)
    # ws.py / worker 直产且落库的事件不得缺位（对齐 API.md §4.3 + §4.4 回执）；
    # 回执/任务控制/标题类直产事件不在图可产白名单内
    for kind in (
        "confirm_ack",
        "tool_approval_ack",
        "clarify_ack",  # V1.72（#1）新增回执事件（新 kind 已升版 event.v2）
        "task_cancelled",
        "session_title",
    ):
        assert kind in PERSISTENT_KINDS
        assert not is_node_event(kind)
    # progress/report/error 图可产且 Worker 亦直产（词汇表单一事实源覆盖两方）
    for kind in ("progress", "report", "error", "thought"):
        assert kind in PERSISTENT_KINDS


def test_make_event_injects_current_version() -> None:
    """图内事件构造自动注入当前词汇版本。"""
    event = make_event("tool_result", {"call_id": "c-1", "name": "read", "ok": True})
    assert event["event_version"] == EVENT_VERSION
    assert is_persistent("tool_result")


def test_frame_carries_vocab_version_header() -> None:
    """#4 D2：公共头恒发 vocab_version；业务 payload 不受影响。"""
    frame = ws._frame(
        "s-1",
        "progress",
        3,
        {"percent": 10},
        task_id="t-1",
    )
    assert frame["vocab_version"] == EVENT_VERSION
    assert frame["payload"] == {"percent": 10}


def test_split_event_version_strips_reserved_key_and_tolerates_legacy() -> None:
    """#4 D3/D4：写库保留字段被剥离；历史无版本行返回 None 兼容。"""
    payload, version = ws._split_event_version({"percent": 10, "event_version": EVENT_VERSION})
    assert payload == {"percent": 10}
    assert version == EVENT_VERSION
    # 历史无版本行（V1.71 前 / 旧 Worker）：原样返回 + None
    legacy, legacy_version = ws._split_event_version({"percent": 10})
    assert legacy == {"percent": 10}
    assert legacy_version is None
    # 非字符串版本视为缺失（宽容）
    _payload, bad = ws._split_event_version({"event_version": 123})
    assert bad is None


def test_event_vocab_mismatch_policy() -> None:
    """转发护栏：未知 kind / 版本不符拒转发；无版本行按当前版本放行。"""
    assert ws._event_vocab_mismatch("progress", EVENT_VERSION) is None
    assert ws._event_vocab_mismatch("progress", None) is None  # 历史兼容
    assert ws._event_vocab_mismatch("not_a_real_event", EVENT_VERSION) == "unknown"
    assert ws._event_vocab_mismatch("progress", "event.v9") == "version"
    assert ws._event_vocab_mismatch("not_a_real_event", "event.v9") == "unknown"


@pytest.mark.asyncio
async def test_translate_event_rejects_unknown_kind_fail_closed(monkeypatch) -> None:
    """图内未知 kind 绝不落库广播（fail-closed）：告警并跳过。"""
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(ws, "_emit_persistent", _make_fake_emit(emitted))

    await ws._translate_event(
        object(),
        object(),
        ws._ConnectionState(),
        "s-1",
        None,
        {"kind": "not_a_real_event", "payload": {"x": 1}, "event_version": EVENT_VERSION},
    )
    assert emitted == []


@pytest.mark.asyncio
async def test_translate_event_tolerates_version_drift_and_translates(monkeypatch) -> None:
    """版本漂移仅告警：按当前词汇表翻译落库广播（同部署漂移哨兵）。"""
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(ws, "_emit_persistent", _make_fake_emit(emitted))

    event = make_event("tool_result", {"call_id": "c-1", "name": "read", "ok": True})
    event["event_version"] = "event.v9"  # 模拟旧检查点/漂移载荷
    await ws._translate_event(
        object(),
        object(),
        ws._ConnectionState(),
        "s-1",
        None,
        event,
    )
    assert [kind for kind, _payload in emitted] == ["tool_result"]


@pytest.mark.asyncio
async def test_forward_loop_skips_unknown_event_in_gray_mode(monkeypatch) -> None:
    """event_vocab_strict=false：未知 kind / 版本不符 → 告警跳过，正常事件照常转发。"""
    monkeypatch.setattr(ws, "settings", _FakeSettings(event_vocab_strict=False))
    sent: list[dict] = []
    batches = [
        [
            _Row(5, "progress", {"percent": 10, "event_version": EVENT_VERSION}, "t-1"),
            _Row(6, "error", {"code": "INTERNAL", "message": "x", "event_version": EVENT_VERSION}, "t-1"),
            _Row(7, "progress", {"percent": 20, "event_version": "event.v9"}, "t-1"),
        ],
        [],
    ]

    class _WS:
        async def send_json(self, frame: dict) -> None:
            sent.append(frame)

    monkeypatch.setattr(ws, "SessionLocal", lambda: _BatchesDb(batches))
    monkeypatch.setattr(ws, "_FORWARD_POLL_S", 0.01)
    state = ws._ConnectionState()
    state.cursor = 4
    stop = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(ws._forward_loop(_WS(), state, "s-1", stop), _stop_soon())
    # 版本漂移行（event.v9）被跳过（灰度告警），当前版本行照常转发
    assert [frame["event_id"] for frame in sent] == [5, 6]
    assert state.cursor == 7
    # 转发帧不含保留字段（剥离后才广播）
    assert all("event_version" not in frame["payload"] for frame in sent)
    assert all(frame["vocab_version"] == EVENT_VERSION for frame in sent)


@pytest.mark.asyncio
async def test_forward_loop_fail_closed_emits_error_in_strict_mode(monkeypatch) -> None:
    """event_vocab_strict=true：fail-closed 拒收并落 error（按 kind 去重）。"""
    monkeypatch.setattr(ws, "settings", _FakeSettings(event_vocab_strict=True))
    sent: list[dict] = []
    rejected_errors: list[dict] = []
    batches = [
        [
            _Row(5, "progress", {"percent": 10, "event_version": "event.v9"}, "t-1"),
            _Row(6, "progress", {"percent": 12, "event_version": "event.v9"}, "t-1"),
        ],
        [],
    ]

    class _WS:
        async def send_json(self, frame: dict) -> None:
            sent.append(frame)

    async def fake_emit_error(_db, _ws, _state, _session_id, error) -> None:
        rejected_errors.append({"code": error.code.value, "message": error.message})

    monkeypatch.setattr(ws, "_emit_error", fake_emit_error)
    monkeypatch.setattr(ws, "SessionLocal", lambda: _BatchesDb(batches))
    monkeypatch.setattr(ws, "_FORWARD_POLL_S", 0.01)
    state = ws._ConnectionState()
    state.cursor = 4
    stop = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(ws._forward_loop(_WS(), state, "s-1", stop), _stop_soon())
    assert sent == []
    assert state.cursor == 6
    assert len(rejected_errors) == 1  # 同 kind 去重，不刷屏
    assert rejected_errors[0]["code"] == "INTERNAL"


def _make_fake_emit(emitted: list[tuple[str, dict]]) -> object:
    async def fake_emit(_db, _websocket, _state, _session_id, event, payload, **_kw) -> bool:
        emitted.append((event, dict(payload)))
        return True

    return fake_emit


class _FakeSettings:
    """forward_loop 校验开关的最小替身。"""

    def __init__(self, event_vocab_strict: bool) -> None:
        self.event_vocab_strict = event_vocab_strict


class _Row:
    """与 test_ws_protocol._Row 同构的转发行替身。"""

    def __init__(self, event_id: int, event: str, payload: dict, task_id: str | None):
        self.event_id = event_id
        self.event = event
        self.payload = payload
        self.task_id = task_id
        self.ts = None


class _BatchesDb:
    """按轮次返回行批的转发查询替身（批次耗尽后返回空，与 test_ws_protocol 同构）。"""

    def __init__(self, batches: list[list[_Row]]) -> None:
        self._batches = batches

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self._batches.pop(0) if self._batches else []

    def close(self) -> None:
        pass
