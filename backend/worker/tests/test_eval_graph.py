"""Worker 评测流水线 LangGraph 图编排单元测试。"""

from unittest.mock import MagicMock

from app.eval_graph import BenchmarkEvalPipeline, BenchmarkGraphState, eval_single_row


def test_eval_single_row_success(monkeypatch):
    """测试 eval_single_row 在模型返回成功时的打分和字段提取。"""
    mock_result = MagicMock()
    mock_result.text = "42"
    mock_result.latency_ms = 120.0
    mock_result.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    mock_result.raw = {"id": "chatcmpl-test"}

    monkeypatch.setattr("app.eval_graph.call_protocol", lambda **kw: mock_result)

    res = eval_single_row(
        call_kwargs={"protocol": "openai_chat", "base_url": "https://api.openai.com/v1", "model": "gpt-4o", "api_key": "sk-mock"},
        row_data={"row_no": 1, "question": "答案是什么？", "reference": "42", "context": ""},
        retry=0,
        metric="exact_match",
        truncate_raw_fn=lambda raw: raw,
    )
    assert res["ok"] is True
    assert res["output"] == "42"
    assert res["score"] == 1.0
    assert res["exact"] == 1.0
    assert res["latency_ms"] == 120.0
    assert res["usage"]["total_tokens"] == 15


def test_benchmark_graph_compile():
    """测试 LangGraph 评测图正确编译并能处理已完成状态。"""
    pipeline = BenchmarkEvalPipeline(
        db_factory=MagicMock(),
        push_progress_fn=MagicMock(),
        truncate_raw_fn=lambda x: x,
        is_cancelled_fn=MagicMock(return_value=False),
    )
    assert pipeline.graph is not None

    initial_state: BenchmarkGraphState = {
        "task_id": "task-test",
        "dataset_id": "ds-test",
        "metric": "exact_match",
        "rows_data": [],
        "profiles_data": [],
        "run_params": {},
        "max_usd": 5.0,
        "price_per_1k": 0.002,
        "batch_size": 4,
        "total_samples": 10,
        "done_samples": 10,
        "usage_totals": {},
        "is_cancelled": False,
        "is_budget_exceeded": False,
        "completed": False,
    }
    final_state = pipeline.run(initial_state)
    assert final_state.get("completed") is True
