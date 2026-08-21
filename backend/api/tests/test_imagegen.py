"""Qwen Image 内置短工具单测：不调用真实上游。"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.imagegen import (
    arguments_for_imagegen,
    generate_image_bytes,
    inject_imagegen_plan,
    looks_like_image_generation,
)
from app.agent.mcp_tools import collect_ids, execute_short_tool
from app.agent.plan import PlanArtifact, l0_plan
from app.agent.react import run_react
from app.errors import AppError, ErrorCode
from app.harness.contracts.cancellation import CancellationToken
from app.harness.contracts.trace import TraceContext
from app.models import StoredFile


def _turn_ctx() -> dict:
    """阶段 2：测试夹具必须显式构造同一 Turn 的 trace/cancel。"""
    trace = TraceContext.for_turn()
    return {"trace": trace, "cancel": CancellationToken(turn_id=trace.turn_id)}


class _ImageQuery:
    def __init__(self, rows: list[StoredFile]):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _ImageDb:
    def __init__(self, rows: list[StoredFile] | None = None):
        self.rows = rows or []
        self.added: list[StoredFile] = []

    def query(self, *_args, **_kwargs):
        return _ImageQuery(self.rows)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, item):
        return item


def _image_row(tmp_path, *, file_id: str = "f-ref") -> StoredFile:
    path = tmp_path / file_id
    path.write_bytes(b"\x89PNG\r\n\x1a\nreference")
    return StoredFile(
        id=file_id,
        filename="ref.png",
        content_type="image/png",
        size_bytes=path.stat().st_size,
        sha256="a" * 64,
        storage_path=str(path),
        kind="png",
        uploaded_by="u1",
    )


def test_arguments_for_imagegen_uses_last_image_attachment(tmp_path):
    row = _image_row(tmp_path)
    db = _ImageDb([row])

    args = arguments_for_imagegen(db, text="改成水彩风格", attachments=[row.id])

    assert args == {"prompt": "改成水彩风格", "file_id": row.id, "prompt_extend": True}


def test_inject_imagegen_plan_for_explicit_image_request():
    plan = l0_plan("请生成一张赛博朋克城市图片")

    out = inject_imagegen_plan(_ImageDb(), plan, text="请生成一张赛博朋克城市图片", attachments=[])

    assert out.intent == "chat"
    assert out.delivery == "text"
    assert out.tools_needed == ["image.generate"]


def test_inject_imagegen_does_not_replace_testcase_intent():
    """生成测试用例不能被图片关键词误判。"""
    plan = l0_plan("请生成登录模块测试用例")

    out = inject_imagegen_plan(_ImageDb(), plan, text="请生成登录模块测试用例", attachments=[])

    assert out.intent == "testcase"
    assert "image.generate" not in out.tools_needed


def test_portrait_photography_is_image_not_benchmark():
    """用户要竖幅人像摄影时，即使文案含明暗对比，也只规划 image.generate。"""
    text = "帮我生成一张一张竖幅户外人像摄影，整体从上到下呈现温暖的午后街景氛围。顶部左侧明暗对比柔和。"
    assert looks_like_image_generation(text) is True
    plan = l0_plan(text, prefs={"last_profile_ids": ["p1"], "last_dataset_id": "d1"})
    assert plan.intent == "chat"
    assert plan.skill_id is None
    assert plan.tools_needed == ["image.generate"]
    assert plan.delivery == "text"
    out = inject_imagegen_plan(
        _ImageDb(),
        PlanArtifact(
            intent="benchmark",
            skill_id="skill-benchmark",
            slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids", "dataset_id"]},
            tools_needed=["model.list", "dataset.list"],
            delivery="clarify",
            budget={"max_tool_rounds": 4},
            notes="规划：已按规则识别为 benchmark。",
            source="l0",
            pref_thoughts=["沿用你上次的协议档，可在卡上改"],
        ),
        text=text,
        attachments=[],
    )
    assert out.intent == "chat"
    assert out.skill_id is None
    assert out.tools_needed == ["image.generate"]
    assert out.pref_thoughts == []
    assert "已按规则识别为 benchmark" not in (out.notes or "")


def test_generate_image_bytes_sends_text_and_reference(monkeypatch):
    captured: dict = {}

    def _fake_post(url, body, headers, timeout_s):
        captured.update(url=url, body=body, headers=headers, timeout_s=timeout_s)
        return {"output": {"choices": [{"message": {"content": [{"image": "https://cdn.test/result.png"}]}}]}}

    monkeypatch.setattr("app.agent.imagegen.settings.qwen_image_api_url", "https://qwen.test/generate")
    monkeypatch.setattr("app.agent.imagegen.settings.qwen_image_api_key", "test-key")
    monkeypatch.setattr("app.agent.imagegen.settings.qwen_image_model", "qwen-image-3.0")
    monkeypatch.setattr("app.agent.imagegen._post_json", _fake_post)
    monkeypatch.setattr(
        "app.agent.imagegen._download_image",
        lambda _url, _timeout: (b"\x89PNG\r\n\x1a\nresult", "image/png"),
    )

    data, mime = generate_image_bytes(
        prompt="改成油画风格",
        ref_bytes=b"\x89PNG\r\n\x1a\nreference",
        ref_mime="image/png",
    )

    assert data.startswith(b"\x89PNG")
    assert mime == "image/png"
    assert captured["body"]["model"] == "qwen-image-3.0"
    assert captured["body"]["input"]["messages"][0]["content"][0]["image"].startswith("data:image/png;base64,")
    assert captured["body"]["input"]["messages"][0]["content"][1] == {"text": "改成油画风格"}
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_execute_imagegen_persists_file_without_binary_payload(tmp_path, monkeypatch):
    row = _image_row(tmp_path)
    monkeypatch.setattr("app.agent.imagegen.settings.data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(
        "app.agent.imagegen.generate_image_bytes",
        lambda **_kwargs: (b"\x89PNG\r\n\x1a\nresult", "image/png"),
    )

    ok, data, error, _latency = execute_short_tool(
        _ImageDb([row]),
        "image.generate",
        {"prompt": "改成油画风格", "file_id": row.id},
        user_id="u1",
    )

    assert ok is True
    assert error is None
    assert data["filename"] == "imagegen.png"
    assert data["content_url"].endswith("/content")
    assert "data" not in data
    assert collect_ids(data) == [data["file_id"]]
    assert (tmp_path / "data" / "files" / data["file_id"]).read_bytes().startswith(b"\x89PNG")


def test_run_react_passes_imagegen_arguments(tmp_path, monkeypatch):
    row = _image_row(tmp_path)
    captured: dict = {}

    def _fake_isolated(name, arguments, user_id):
        captured.update(name=name, arguments=arguments, user_id=user_id)
        return True, {"file_id": "out-1", "content_url": "/api/files/out-1/content"}, None, 12

    monkeypatch.setattr("app.agent.react._execute_short_tool_isolated", _fake_isolated)
    plan = PlanArtifact(
        intent="chat",
        skill_id=None,
        slots={"filled": {}, "missing": []},
        tools_needed=["image.generate"],
        delivery="text",
        budget={"max_tool_rounds": 1},
        notes="规划：生图",
        source="l0",
    )
    events: list[tuple[str, dict]] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append((event, payload))
        return len(events)

    asyncio.run(
        run_react(
            _ImageDb([row]),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            text="根据参考图生成油画风格",
            attachments=[row.id],
            **_turn_ctx(),
        )
    )

    assert captured["name"] == "image.generate"
    assert captured["arguments"]["prompt"] == "根据参考图生成油画风格"
    assert captured["arguments"]["file_id"] == row.id
    assert events[0][0] == "thought"
    assert events[0][1].get("stage") == "react"
    assert events[1][0] == "tool_call"


def test_react_redirects_eval_inventory_when_user_asks_for_photo(monkeypatch):
    """规划误塞 model.list 时，生图口令仍只执行 image.generate。"""
    captured: list[str] = []

    def _fake_isolated(name, arguments, user_id):
        captured.append(name)
        return True, {"file_id": "out-1"}, None, 8

    monkeypatch.setattr("app.agent.react._execute_short_tool_isolated", _fake_isolated)
    plan = PlanArtifact(
        intent="benchmark",
        skill_id="skill-benchmark",
        slots={"filled": {"kind": "benchmark"}, "missing": ["profile_ids", "dataset_id"]},
        tools_needed=["model.list", "dataset.list"],
        delivery="clarify",
        budget={"max_tool_rounds": 4},
        notes="规划：已按规则识别为 benchmark。",
        source="l0",
    )
    events: list[str] = []

    async def _emit(event: str, payload: dict, **_kwargs) -> int:
        events.append(payload.get("name") or event)
        return len(events)

    asyncio.run(
        run_react(
            _ImageDb(),
            plan,
            user_id="u1",
            emit=_emit,
            check_abort=lambda: None,
            slash_fill_first=False,
            text="帮我生成一张竖幅户外人像摄影",
            attachments=[],
            **_turn_ctx(),
        )
    )

    assert captured == ["image.generate"]
    assert "model.list" not in events
    assert "dataset.list" not in events


def test_generate_image_requires_configuration(monkeypatch):
    monkeypatch.setattr("app.agent.imagegen.settings.qwen_image_api_url", "")
    monkeypatch.setattr("app.agent.imagegen.settings.qwen_image_api_key", "")
    monkeypatch.setattr("app.agent.imagegen.settings.qwen_image_model", "")

    with pytest.raises(AppError) as exc:
        generate_image_bytes(prompt="test")

    assert exc.value.code == ErrorCode.VALIDATION
