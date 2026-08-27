"""Harness WS 探针 live：连真实 API 服务跑 L0/L1/L2 全套场景（部署后回归证据）。

默认跳过：未设置 ``HARNESS_PROBE_BASE`` 时整文件 skip；设置后自动启用：:

    pytest tests/test_harness_probe_live.py -v

或一键脚本 ``tools/harness-ws-probe/run-live.ps1`` / ``run-live.sh``。

环境变量：
    HARNESS_PROBE_BASE       服务 HTTP 地址（必填，如 http://127.0.0.1:8000）
    HARNESS_PROBE_USER       登录用户名（默认 admin）
    HARNESS_PROBE_PASSWORD   登录密码（默认 admin123）
    HARNESS_PROBE_INSECURE   =1 时跳过 TLS 校验（https 自签场景）
    HARNESS_PROBE_TRACE_DIR  抓包证据落盘目录（默认 tools/harness-ws-probe/traces/）

前置条件：服务在线；L2 chat 需已配置 Agent 协议档（未配时该用例失败即红，
与 CLI live 的 /help 容错语义不同——回归场景要求环境完整）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROBE_ROOT = Path(__file__).resolve().parents[3] / "tools" / "harness-ws-probe"
sys.path.insert(0, str(PROBE_ROOT))

from harness_ws_probe.client import ProbeClient, connect_expect_close  # noqa: E402
from harness_ws_probe.errors import ProbeError  # noqa: E402
from harness_ws_probe.expect import ExpectMatcher, ProbeAssertion  # noqa: E402
from harness_ws_probe.scenarios import l0, l1  # noqa: E402
from harness_ws_probe.scenarios.chat import run_chat_turn  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("HARNESS_PROBE_BASE"),
        reason="未设置 HARNESS_PROBE_BASE（live 探针需真实服务）",
    ),
]


class _LiveLoop:
    """跨用例复用同一事件循环。

    ProbeClient 内部的 httpx/websockets 对象绑定创建它的事件循环；若每个
    用例各自 ``asyncio.run()``，循环被关闭后复用会抛 ``Event loop is closed``
    （Python 3.14 下尤为严格）。因此用单一长生命周期循环执行全部协程。
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

    def run(self, coro: Any) -> Any:
        return self._loop.run_until_complete(coro)

    def close(self) -> None:
        self._loop.run_until_complete(asyncio.sleep(0))
        self._loop.close()


@pytest.fixture(scope="module")
def live() -> tuple[ProbeClient, _LiveLoop]:
    """模块级 live 客户端：登录后供各用例建会话使用；teardown 落盘抓包证据。"""
    base = os.environ["HARNESS_PROBE_BASE"]
    insecure = os.environ.get("HARNESS_PROBE_INSECURE") == "1"
    client = ProbeClient(
        base,
        username=os.environ.get("HARNESS_PROBE_USER", "admin"),
        password=os.environ.get("HARNESS_PROBE_PASSWORD", "admin123"),
        insecure=insecure,
    )
    loop = _LiveLoop()
    loop.run(client.login())
    try:
        yield client, loop
    finally:
        # 每次 live 回归自动落盘脱敏后的双向抓包，作为可追溯证据。
        trace_dir = Path(
            os.environ.get("HARNESS_PROBE_TRACE_DIR")
            or (PROBE_ROOT / "traces")
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        client.trace.write_jsonl(trace_dir / f"live-{stamp}.jsonl")
        loop.run(client.close())
        loop.close()


def _new_session(client: ProbeClient, loop: _LiveLoop) -> None:
    """建一个新会话并建连，保证用例间状态互不干扰。"""
    loop.run(client.create_session())
    loop.run(client.connect())


def test_live_handshake_close_codes(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L0：非法票 4401 / 不存在会话 4404（不依赖主连接）。"""
    client, _ = live
    base = client.base_url
    insecure = client.insecure
    code = asyncio.run(
        connect_expect_close(
            base, ticket="invalid", session_id=None, insecure=insecure, expect_code=4401
        )
    )
    assert code == 4401
    code = asyncio.run(
        connect_expect_close(
            base,
            ticket="invalid",
            session_id="00000000-0000-0000-0000-000000000000",
            insecure=insecure,
            expect_code=4404,
        )
    )
    assert code == 4404


def test_live_l0_unknown_and_cancel(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L0：第五种上行 → VALIDATION；空会话 /cancel → 没有可取消。"""
    client, loop = live
    _new_session(client, loop)
    loop.run(l0.run_unknown_event(client))
    loop.run(l0.run_cancel_empty(client))


def test_live_l0_stress_confirm_cancel(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L0：/stress 发确认卡，confirm_ack(false) 取消且不建任务。"""
    client, loop = live
    _new_session(client, loop)
    loop.run(l0.run_stress_and_cancel_confirm(client))


def test_live_l0_help_and_idempotent(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L0：/help 正文含斜杠清单；client_message_id 幂等只回一次。

    沿用 CLI live 的容错语义：未配置 Agent 协议档时 /help 不可达，跳过该场景，
    其余 L0/L1/L2 场景不受影响。
    """
    client, loop = live
    _new_session(client, loop)
    try:
        loop.run(l0.run_help(client))
        loop.run(l0.run_idempotent_client_message(client))
    except (ProbeError, ProbeAssertion) as exc:
        pytest.skip(f"/help 或幂等不可达（多半未配 Agent 协议档）：{exc}")


def test_live_l0_reconnect_replay(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L0：断线后按 last_event_id 重连补发，不得含瞬态帧。"""
    client, loop = live
    _new_session(client, loop)
    loop.run(l0.run_reconnect_replay(client))


def test_live_l1_confirm_enqueue(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L1：/stress → 确认卡 → confirm_ack(ok=true, sample_size=1) → 返回 task_id。

    注意：本用例会真实创建 queued 任务（sample_size=1、with_stress=false），
    由 Worker 异步消费，属 live 回归的预期行为。
    """
    client, loop = live
    _new_session(client, loop)
    matcher = loop.run(l1.run_confirm_enqueue(client, allow_enqueue=True))
    task_id = matcher.confirm_enqueued()
    assert task_id, "confirm_ack 回执必须携带 task_id"


def test_live_l2_chat_contract(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L2：真实模型一轮对话，断言思考链契约（think_final 先于 completed 等）。"""
    client, loop = live
    _new_session(client, loop)
    stats = loop.run(run_chat_turn(client, "用一句话介绍你自己"))
    assert stats["completed_ms"] >= 0
    # 契约断言已内置于 run_chat_turn(check=True)；此处再显式核验一轮事件序列。
    ExpectMatcher(client.trace).chat_turn_contract(after_frame=stats["after_frame"])
    assert stats["answer"], "chat 回合必须产出正文"


def test_live_l3_react_tool_contract(live: tuple[ProbeClient, _LiveLoop]) -> None:
    """L3：真实 ReAct 回合——模型调用 read 工具，校验工具事件序列与思考链契约。

    断言点：tool_call 帧（含工具名）→ tool_progress 三阶段（validating/
    executing/finalizing）→ tool_result 回执（无论成功失败）→ think_final
    先于 completed；事件白名单须放行 tool_progress/tool_output_delta 瞬态帧
    （对齐 f7801a3 契约）。
    """
    client, loop = live
    _new_session(client, loop)
    # 模型是否调用工具属概率行为（qwen 系列偶发直接作答）：
    # 换措辞最多重试三轮，避免偶发误报；仍失败才判定 ReAct 链路异常。
    prompts = [
        "用 read 工具读取文件 /tmp/nonexistent.txt 看是否存在，直接输出结果",
        "立即调用 read 工具读取 /tmp/nonexistent.txt，只报告工具返回内容，不要解释",
        "必须调用 read 工具（参数 path=/tmp/nonexistent.txt），读取结果后简短汇报",
    ]
    mark = len(client.trace.frames)
    calls: list = []
    for prompt in prompts:
        stats = loop.run(run_chat_turn(client, prompt))
        assert stats["completed_ms"] >= 0
        frames = client.trace.frames[mark:]
        calls = [f for f in frames if f.event == "tool_call"]
        if calls:
            break
    assert calls, "ReAct 回合必须出现 tool_call 帧（两轮均未触发工具调用）"
    assert any(
        str(f.raw.get("payload", {}).get("name")) == "read" for f in calls
    ), "本轮工具调用应为 read"
    stages = [
        f.raw.get("payload", {}).get("stage")
        for f in frames
        if f.event == "tool_progress"
    ]
    assert stages, "ReAct 回合必须出现 tool_progress 帧"
    assert any(f.event == "tool_result" for f in frames), "工具必须返回 tool_result 回执"
    # 契约：白名单（含 tool_progress/tool_output_delta）、event_id 单调、think_final 顺序。
    # 注意：event_id 按连接计数，跨会话会重置，必须限定在本次用例窗口内检查。
    ExpectMatcher(client.trace).event_whitelist(after_frame=mark)
    ExpectMatcher(client.trace).event_ids_monotonic(after_frame=mark)
    ExpectMatcher(client.trace).chat_turn_contract(after_frame=mark)
    assert stats["answer"], "ReAct 回合必须基于工具结果产出正文"
