"""Worker LLM 裁判模块与编排单元测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.judge import (
    build_judge_call_kwargs,
    build_judge_messages,
    judge_single_sample,
    parse_judge_output,
)
from app.protocol import ProtocolCallError

# ─── parse_judge_output ───

def test_parse_json_with_reason():
    assert parse_judge_output('{"score": 85, "reason": "要点齐全"}') == (85, "要点齐全")


def test_parse_json_with_noise_prefix_suffix():
    text = '好的，评分如下：\n{"score": 72, "reason": "部分正确"}\n以上。'
    assert parse_judge_output(text) == (72, "部分正确")


def test_parse_pure_number():
    assert parse_judge_output("88") == (88, None)


def test_parse_number_with_text():
    assert parse_judge_output("得分 90 分") == (90, None)


def test_parse_json_float_score():
    assert parse_judge_output('{"score": 75.0, "reason": "ok"}') == (75, "ok")


def test_parse_json_string_score():
    assert parse_judge_output('{"score": "80", "reason": "ok"}') == (80, "ok")


def test_parse_out_of_range():
    assert parse_judge_output("150") == (None, None)
    assert parse_judge_output("-3") == (None, None)
    assert parse_judge_output('{"score": 120, "reason": "超界"}') == (None, None)


def test_parse_garbage():
    assert parse_judge_output("完全不相关") == (None, None)
    assert parse_judge_output("") == (None, None)
    assert parse_judge_output("   ") == (None, None)


def test_parse_long_reason_truncated():
    reason = "长" * 600
    text = f'{{"score": 60, "reason": "{reason}"}}'
    score, parsed_reason = parse_judge_output(text)
    assert score == 60
    assert parsed_reason is not None and len(parsed_reason) <= 500


# ─── build_judge_messages ───

def test_build_judge_messages_with_context():
    messages = build_judge_messages(
        {"question": "1+1=?", "reference": "2", "context": "背景", "output": "2"}
    )
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert "背景信息:" in content
    assert "1+1=?" in content
    assert "标准参考答案:2" in content
    assert "2" in content


def test_build_judge_messages_without_context():
    messages = build_judge_messages(
        {"question": "Q", "reference": "R", "context": "", "output": "O"}
    )
    content = messages[0]["content"]
    assert "背景信息:" not in content
    assert "Q" in content and "R" in content and "O" in content


# ─── judge_single_sample ───

def _item_data(output="答案"):
    return {"question": "Q", "reference": "R", "context": "", "output": output}


def test_judge_single_sample_success(monkeypatch):
    mock_result = MagicMock()
    mock_result.text = '{"score": 82, "reason": "良好"}'
    mock_result.latency_ms = 150.0
    mock_result.usage = {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
    mock_result.raw = {"id": "judge-1"}

    monkeypatch.setattr("app.judge.call_protocol", lambda **kw: mock_result)

    res = judge_single_sample(
        {"protocol": "openai_chat", "base_url": "https://x", "model": "j", "api_key": "k"},
        _item_data(),
        lambda raw: raw,
    )
    assert res["ok"] is True
    assert res["judge_score"] == 82
    assert res["judge_reason"] == "良好"
    assert res["latency_ms"] == 150.0
    assert res["usage"]["total_tokens"] == 28


def test_judge_single_sample_protocol_error(monkeypatch):
    def boom(**kw):
        raise ProtocolCallError("UPSTREAM", "上游返回 500")

    monkeypatch.setattr("app.judge.call_protocol", boom)
    res = judge_single_sample(
        {"protocol": "openai_chat", "base_url": "https://x", "model": "j", "api_key": "k"},
        _item_data(),
        lambda raw: raw,
    )
    assert res["ok"] is False
    assert "UPSTREAM" in res["error"]


def test_judge_single_sample_parse_failure(monkeypatch):
    mock_result = MagicMock()
    mock_result.text = "抱歉，无法评分。"
    mock_result.latency_ms = 10.0
    mock_result.usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    mock_result.raw = None
    monkeypatch.setattr("app.judge.call_protocol", lambda **kw: mock_result)
    res = judge_single_sample(
        {"protocol": "openai_chat", "base_url": "https://x", "model": "j", "api_key": "k"},
        _item_data(),
        lambda raw: raw,
    )
    assert res["ok"] is False
    assert "JUDGE_PARSE" in res["error"]


# ─── build_judge_call_kwargs ───

def test_build_judge_call_kwargs():
    kwargs = build_judge_call_kwargs(
        protocol="anthropic_messages",
        base_url="https://x",
        model="claude",
        api_key="k",
        anthropic_version="2023-06-01",
        timeout_s=15.0,
    )
    assert kwargs["system"]
    assert kwargs["temperature"] == 0
    assert kwargs["max_tokens"] == 100
    assert kwargs["timeout_s"] == 15.0


# ─── _persist_usage / _run_judge（MagicMock DB） ───

def _fake_sample(row_no, output="答案", error=None):
    return SimpleNamespace(
        row_no=row_no,
        question="Q",
        reference="R",
        context="",
        output=output,
        error=error,
        judge_score=None,
        judge_reason=None,
    )


def test_persist_usage_upsert():
    from app import benchmark

    db = MagicMock()
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing
    benchmark._persist_usage(
        db,
        "task-1",
        {"p-1": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "est_cost_usd": 0.03}},
    )
    assert existing.prompt_tokens == 10
    assert existing.total_tokens == 15
    # 新 profile 时走 add 分支
    db.query.return_value.filter.return_value.first.return_value = None
    benchmark._persist_usage(
        db,
        "task-1",
        {"p-2": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "est_cost_usd": 0.004}},
    )
    added = [c.args[0] for c in db.add.call_args_list]
    assert any(getattr(row, "profile_id", None) == "p-2" for row in added)


def test_run_judge_scores_and_counts(monkeypatch):
    from app import benchmark

    samples = [_fake_sample(1), _fake_sample(2), _fake_sample(3, error="UPSTREAM")]
    # 模拟 SQL 过滤语义：error 非空 / 空输出的样本不进裁判查询集
    ok_samples = [s for s in samples if not s.error and s.output]

    db = MagicMock()
    filtered = MagicMock()
    filtered.order_by.return_value.all.return_value = ok_samples
    db.query.return_value.filter.return_value = filtered

    def fake_connection(profile):
        return "https://x", "judge-model", "sk-key"

    monkeypatch.setattr(benchmark, "profile_connection", fake_connection)
    monkeypatch.setattr(benchmark, "_is_cancelled", lambda d, t: False)
    monkeypatch.setattr(benchmark, "_progress", lambda *a, **k: None)

    def fake_judge(judge_kwargs, item_data, truncate_raw_fn):
        return {
            "ok": True,
            "judge_score": 80,
            "judge_reason": "ok",
            "latency_ms": 10,
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

    monkeypatch.setattr(benchmark, "judge_single_sample", fake_judge)

    usage_totals = {}
    result = benchmark._run_judge(
        db,
        SimpleNamespace(id="task-1"),
        SimpleNamespace(id="j-1", protocol="openai_chat", anthropic_version=None),
        {"timeout_s": 15.0},
        batch_size=2,
        max_usd=10.0,
        price=0.002,
        usage_totals=usage_totals,
    )
    assert result["judged"] == 2  # 两个成功样本
    assert result["failed"] == 0  # 失败样本(error 非空)不在查询集内
    assert samples[0].judge_score == 80
    assert samples[2].judge_score is None
    assert usage_totals["j-1"]["total_tokens"] == 16  # 2 × 8
