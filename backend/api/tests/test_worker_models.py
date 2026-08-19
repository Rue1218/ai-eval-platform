"""Worker 模型副本对齐回归测试。

背景(2026-08-19 线上事故):worker 容器的 Report 副本缺 ``is_baseline``
列,而该列数据库 DDL 为 NOT NULL 且无 server_default,导致 Worker 写报告
必然 IntegrityError、任务统一 INTERNAL 失败。本测试按文件路径加载 worker
副本,守护「worker 写路径涉及的 NOT NULL 列必须有 ORM 映射」这条底线。
"""

import importlib.util
from pathlib import Path

# worker 侧模型路径:backend/worker/app/models.py(评分器同款按路径加载方式)
_MODELS_PATH = Path(__file__).resolve().parents[2] / "worker" / "app" / "models.py"
_spec = importlib.util.spec_from_file_location("worker_models", _MODELS_PATH)
worker_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_models)


def test_report_has_not_null_is_baseline_mapping():
    # reports.is_baseline 为 NOT NULL 且无 DDL 默认:ORM 副本缺该列时
    # Worker 的 INSERT 会违反非空约束,必须在映射层补 Python 侧 default
    columns = worker_models.Report.__table__.columns
    assert "is_baseline" in columns
    col = columns["is_baseline"]
    assert col.nullable is False
    assert col.default is not None and col.default.arg is False


def test_task_has_progress_mapping():
    # tasks.progress 为 JSONB NOT NULL:执行器逐批回写进度摘要,
    # 缺映射会使赋值静默失效,刷新后任务进度文案丢失
    assert "progress" in worker_models.Task.__table__.columns


def test_eval_write_path_columns_present():
    # worker 写路径三张表的关键列齐全(与 api Alembic 迁移对齐)
    eval_cols = set(worker_models.EvalItem.__table__.columns.keys())
    assert {"task_id", "profile_id", "row_no", "score", "error", "raw", "usage"} <= eval_cols
    ledger_cols = set(worker_models.UsageLedger.__table__.columns.keys())
    assert {"task_id", "profile_id", "total_tokens", "est_cost_usd"} <= ledger_cols
