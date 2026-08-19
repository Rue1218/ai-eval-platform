"""Worker 侧最小模型副本。

与 backend/api/app/models.py 保持一致。骨架版为容器隔离而复制；
后续可抽成共享 package（如 ./shared）供 api / worker 共同引用，避免漂移。
跨域外键一律不声明（worker 元数据中没有关联表，悬空外键会在 flush 时
抛 NoReferencedTableError）；真实外键由 api 侧 Alembic 迁移维护。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class Session(Base):
    """会话表最小映射：仅供 _push_ws 分配事件号时锁定会话行。"""

    __tablename__ = "sessions"

    id = Column(String, primary_key=True)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, nullable=True, index=True)
    parent_task_id = Column(String, nullable=True, index=True)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued", index=True)
    config = Column(JSONB, default=dict)
    # 进度摘要(JSONB NOT NULL):执行器逐批回写,缺失映射会导致赋值静默失效不落库
    progress = Column(JSONB, default=dict)
    result = Column(JSONB, default=dict)
    report_id = Column(String, nullable=True)
    # 不声明 ForeignKey("users.id")：worker 元数据中没有 users 表，
    # 悬空外键会在 flush 时抛 NoReferencedTableError，导致任务无法领取；
    # worker 不执行 DDL，真实外键由 api 侧 Alembic 迁移维护。
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class TaskEvent(Base):
    """与 API 一致的任务事件最小字段，Worker 写入时默认 info 级别。"""

    __tablename__ = "task_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    event = Column(String, nullable=False)
    level = Column(String, nullable=False, default="info")
    message = Column(Text, nullable=True)
    payload = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), default=utcnow)


class WsEvent(Base):
    """与 API 一致的会话事件字段，支持关联任务 ID。"""

    __tablename__ = "ws_events"
    __table_args__ = (Index("ix_ws_events_session_event", "session_id", "event_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    task_id = Column(String, nullable=True, index=True)
    event_id = Column(BigInteger, nullable=False)
    event = Column(String, nullable=False)
    payload = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=uuid_str)
    task_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)
    metrics = Column(JSONB, default=dict)
    # 基线冻结标记:数据库列为 NOT NULL 且无 DDL 默认(e5f92b7d31a8 迁移尾部已移除
    # server_default),ORM 侧缺失该列会使 Worker 写报告必然违反非空约束。
    is_baseline = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    """平台配置最小映射：Worker 仅读取 max_running_tasks 等并发闸门值。"""

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(JSONB, default=dict)


class ProtocolProfile(Base):
    """协议档最小映射：Worker 读取连接参数，密文仅在调用上游前解密。"""

    __tablename__ = "protocol_profiles"

    id = Column(String, primary_key=True)
    name = Column(String)
    protocol = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    model = Column(String, nullable=False)
    anthropic_version = Column(String, nullable=True)
    encrypted_key = Column(Text, nullable=True)


class Dataset(Base):
    """数据集最小映射：Worker 读取主指标口径与版本号写进报告快照。"""

    __tablename__ = "datasets"

    id = Column(String, primary_key=True)
    name = Column(String)
    version = Column(Integer)
    metric = Column(String)


class DatasetRow(Base):
    """数据行最小映射：待补全行（pending_complete）不进评分分母。"""

    __tablename__ = "dataset_rows"

    id = Column(String, primary_key=True)
    dataset_id = Column(String, index=True)
    row_no = Column(Integer)
    question = Column(Text)
    reference = Column(Text)
    context = Column(Text, nullable=True)
    pending_complete = Column(Boolean)


class EvalItem(Base):
    """样本级结果最小映射：断点续跑按 (task, profile, row_no) 查重跳过。"""

    __tablename__ = "eval_items"
    __table_args__ = (Index("ix_eval_items_task_profile", "task_id", "profile_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    profile_id = Column(String, nullable=False)
    row_no = Column(Integer, nullable=False)
    question = Column(Text)
    reference = Column(Text)
    context = Column(Text, nullable=True)
    output = Column(Text)
    score = Column(Float, nullable=True)
    exact = Column(Float, nullable=True)
    rouge_l = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    raw = Column(JSONB, nullable=True)
    usage = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class UsageLedger(Base):
    """用量台账最小映射：每「任务 × 协议档」一行，逐调用累加用于预算熔断。"""

    __tablename__ = "usage_ledger"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    profile_id = Column(String, nullable=False)
    prompt_tokens = Column(BigInteger, nullable=False, default=0)
    completion_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    est_cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StoredFile(Base):
    """文件元数据最小映射：testcase 任务读来源文档（PRD/OpenAPI/Excel）路径。"""

    __tablename__ = "files"

    id = Column(String, primary_key=True)
    filename = Column(String)
    content_type = Column(String, nullable=True)
    storage_path = Column(String)


class CaseSet(Base):
    """用例集最小映射：testcase 执行器写入，确认/废弃由 api 侧联动任务状态。"""

    __tablename__ = "case_sets"

    id = Column(String, primary_key=True, default=uuid_str)
    task_id = Column(String, index=True)
    name = Column(String)
    status = Column(String)
    generated_count = Column(Integer)
    confirmed_count = Column(Integer)
    checks = Column(JSONB, default=list)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class CaseItem(Base):
    """用例行最小映射：六策略字段 + 扩展列，批量落库。"""

    __tablename__ = "case_items"

    id = Column(String, primary_key=True, default=uuid_str)
    case_set_id = Column(String, index=True)
    strategy = Column(String)
    priority = Column(String)
    module = Column(String)
    name = Column(String)
    precondition = Column(Text)
    steps = Column(Text)
    expected = Column(Text)
    test_type = Column(String)
    extras = Column(JSONB, default=dict)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
