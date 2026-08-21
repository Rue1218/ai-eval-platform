"""共享模型包完整性回归测试。

api 与 worker 共用 backend/shared/models.py 单一事实源；本测试守住两类历史事故：
1. 悬空外键：worker 曾持独立模型副本，元数据缺 users 表导致 flush 时
   抛 NoReferencedTableError、任务无法领取（2026-08-19）。
2. 双副本漂移：api 改字段、worker 副本未同步导致读写静默丢列。
"""

from shared.models import Base as SharedBase

from app.models import Base as ApiBase

EXPECTED_TABLES = {
    "users",
    "sessions",
    "messages",
    "ws_events",
    "protocol_profiles",
    "files",
    "datasets",
    "tasks",
    "task_events",
    "reports",
    "settings",
    "audit_logs",
    "dispatch_workers",
    "dispatch_events",
    "dataset_folders",
    "dataset_rows",
    "case_folders",
    "case_sets",
    "case_items",
    "eval_items",
    "usage_ledger",
    "harness_turns",
    "harness_spans",
    "harness_diagnostics",
}


def test_api_models_share_single_source():
    """api 的 re-export 必须指向共享包的同一个 Base（同一份元数据）。"""
    assert ApiBase is SharedBase


def test_all_expected_tables_present():
    assert EXPECTED_TABLES <= set(SharedBase.metadata.tables)


def test_all_foreign_keys_resolve():
    """共享元数据内不允许悬空外键：FK 目标表必须都在同一 metadata 中。"""
    tables = SharedBase.metadata.tables
    for table in tables.values():
        for fk in table.foreign_keys:
            target_table = fk.column.table.name
            assert target_table in tables, (
                f"{table.name}.{fk.parent.name} 悬空外键 -> {fk.target_fullname}"
            )
