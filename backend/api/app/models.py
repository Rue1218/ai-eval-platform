"""平台 M1 数据库模型。

实体主键保持 UUID 字符串，以兼容首个骨架迁移；需要由前端扩展的
半结构化字段使用 PostgreSQL JSONB，其余可查询事实均使用独立列。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


def utcnow() -> datetime:
    """返回数据库默认使用的 UTC 当前时间。"""
    return datetime.now(UTC)


def uuid_str() -> str:
    """生成与 API 契约一致的 UUID 字符串主键。"""
    return str(uuid.uuid4())


class User(Base):
    """单一成员账号及浏览器认证失效版本。"""

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uuid_str)
    username = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="member")
    must_change_password = Column(Boolean, nullable=False, default=True)
    disabled = Column(Boolean, nullable=False, default=False)
    auth_version = Column(Integer, nullable=False, default=1)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    last_login_ip = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Session(Base):
    """Agent 对话会话，不承载浏览器登录 Cookie。"""

    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=uuid_str)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False, default="新会话")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Message(Base):
    """可通过 REST 回放的会话文本和已上传附件引用。"""

    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    attachments = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WsEvent(Base):
    """按会话单调事件号持久化的 WebSocket 事件。"""

    __tablename__ = "ws_events"
    __table_args__ = (
        UniqueConstraint("session_id", "event_id", name="uq_ws_events_session_event"),
        Index("ix_ws_events_session_event", "session_id", "event_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    task_id = Column(String, nullable=True, index=True)
    event_id = Column(BigInteger, nullable=False)
    event = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class ProtocolProfile(Base):
    """三协议档及仅写入的加密上游凭据。"""

    __tablename__ = "protocol_profiles"
    __table_args__ = (
        CheckConstraint(
            "protocol IN ('openai_chat', 'openai_responses', 'anthropic_messages')",
            name="ck_protocol_profiles_protocol",
        ),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    protocol = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    model = Column(String, nullable=False)
    usages = Column(JSONB, nullable=False, default=list)
    anthropic_version = Column(String, nullable=True)
    encrypted_key = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class StoredFile(Base):
    """本地文件卷的元数据，二进制内容不进入 PostgreSQL。"""

    __tablename__ = "files"

    id = Column(String, primary_key=True, default=uuid_str)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    storage_path = Column(String, nullable=False, unique=True)
    kind = Column(String, nullable=True)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Dataset(Base):
    """数据集：M2 起挂载目录树、评测口径与自定义扩展列定义。"""

    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    row_count = Column(Integer, nullable=False, default=0)
    # 待补全行数：question/reference 任一缺失的行计入，且不进评分分母
    pending_complete_count = Column(Integer, nullable=False, default=0)
    # 默认评判口径，契约取值如 contain / exact / judge，由评测执行侧解释
    metric = Column(String, nullable=False, default="contain")
    folder_id = Column(String, ForeignKey("dataset_folders.id"), nullable=True)
    # 自定义扩展列定义数组：[{key, name, type, required?, sort_order}]
    column_schema = Column(JSONB, nullable=False, default=list)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Task(Base):
    """长任务队列、确认卡快照和 Worker 控制字段。"""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('benchmark', 'rag', 'testcase', 'stress')", name="ck_tasks_kind"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_case_confirm', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_tasks_status",
        ),
        Index("ix_tasks_queue", "status", "created_at"),
        Index(
            "uq_tasks_active_session",
            "session_id",
            unique=True,
            postgresql_where=text(
                "session_id IS NOT NULL AND status IN "
                "('queued', 'running', 'awaiting_case_confirm')"
            ),
        ),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True, index=True)
    parent_task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued", index=True)
    config = Column(JSONB, nullable=False, default=dict)
    progress = Column(JSONB, nullable=False, default=dict)
    result = Column(JSONB, nullable=False, default=dict)
    report_id = Column(String, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    claimed_by_worker_id = Column(String, nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempt = Column(Integer, nullable=False, default=0)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class TaskEvent(Base):
    """任务状态、告警和进度摘要组成的追加式时间线。"""

    __tablename__ = "task_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True)
    event = Column(String, nullable=False)
    level = Column(String, nullable=False, default="info")
    message = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Report(Base):
    """M1 mock 报告及后续各类评测报告的统一入口。"""

    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=uuid_str)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True, unique=True)
    kind = Column(String, nullable=False)
    metrics = Column(JSONB, nullable=False, default=dict)
    # 免登分享：token 只写不在列表回显，到期即失效
    share_token = Column(String, nullable=True, index=True)
    share_expire_at = Column(DateTime(timezone=True), nullable=True)
    # 基线冻结标记：同数据集版本 + 主指标对比的基准报告
    is_baseline = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Setting(Base):
    """全员同权可维护的非敏感平台配置。"""

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(JSONB, nullable=False, default=dict)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """安全与配置变更审计；明文凭据禁止写入 detail。"""

    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    detail = Column(JSONB, nullable=False, default=dict)
    ip = Column(String, nullable=True)
    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DispatchWorker(Base):
    """调度面可读的 Worker 心跳和能力快照。"""

    __tablename__ = "dispatch_workers"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    caps = Column(JSONB, nullable=False, default=list)
    state = Column(String, nullable=False, default="offline", index=True)
    weight = Column(Integer, nullable=False, default=100)
    load_percent = Column(Float, nullable=True)
    current_task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class DispatchEvent(Base):
    """由 Worker 或调度器追加的分配事件，供前端增量读取。"""

    __tablename__ = "dispatch_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    worker_id = Column(String, ForeignKey("dispatch_workers.id"), nullable=True, index=True)
    event = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    detail = Column(JSONB, nullable=False, default=dict)
    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetFolder(Base):
    """数据集目录树节点；删除非空目录由路由层校验拦截。"""

    __tablename__ = "dataset_folders"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("dataset_folders.id"), nullable=True, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetRow(Base):
    """数据集行：固定三元组字段 + 扩展列值 extras，按 (dataset_id, row_no) 唯一。"""

    __tablename__ = "dataset_rows"
    __table_args__ = (
        UniqueConstraint("dataset_id", "row_no", name="uq_dataset_rows_dataset_row_no"),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    row_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False, default="")
    reference = Column(Text, nullable=False, default="")
    context = Column(Text, nullable=True)
    # 扩展列 key -> 值，键名由 Dataset.column_schema 定义
    extras = Column(JSONB, nullable=False, default=dict)
    # question/reference 任一缺失即视为待补全，评分时不计入分母
    pending_complete = Column(Boolean, nullable=False, default=False)
    # 由用例映射等来源写入时可回溯的用例 ID
    source_case_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class CaseFolder(Base):
    """用例目录树节点；删除非空目录由路由层校验拦截。"""

    __tablename__ = "case_folders"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("case_folders.id"), nullable=True, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CaseSet(Base):
    """用例集：AI 生成或手工维护的用例集合，确认后形成版本快照。

    expires_at 由任务域在关联任务进入 awaiting_case_confirm 时写入（+72h），
    用例域不主动维护该字段，仅在详情响应中原样返回。
    """

    __tablename__ = "case_sets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generated', 'confirmed', 'cancelled')", name="ck_case_sets_status"
        ),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    # 由 testcase 任务派生的用例集回写任务 ID，确认/废弃时联动任务状态
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    name = Column(String, nullable=False, default="未命名用例集")
    status = Column(String, nullable=False, default="generated", index=True)
    generated_count = Column(Integer, nullable=False, default=0)
    confirmed_count = Column(Integer, nullable=False, default=0)
    folder_id = Column(String, ForeignKey("case_folders.id"), nullable=True)
    # 自定义扩展列定义数组：[{key, name, type, required?, sort_order}]
    column_schema = Column(JSONB, nullable=False, default=list)
    # 确认页红字检查项数组：[{level, code, message}]，由生成/保存侧计算
    checks = Column(JSONB, nullable=False, default=list)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class CaseItem(Base):
    """用例行：固定策略字段 + extras 扩展列值，按用例 id 在用例集内 upsert。"""

    __tablename__ = "case_items"

    id = Column(String, primary_key=True, default=uuid_str)
    case_set_id = Column(String, ForeignKey("case_sets.id"), nullable=False, index=True)
    strategy = Column(String, nullable=False)
    priority = Column(String, nullable=False)
    module = Column(String, nullable=False, default="")
    name = Column(String, nullable=False)
    precondition = Column(Text, nullable=False, default="")
    steps = Column(Text, nullable=False, default="")
    expected = Column(Text, nullable=False, default="")
    test_type = Column(String, nullable=False, default="")
    # 已映射到数据集/黄金 QA 的用例不再重复映射
    mapped = Column(Boolean, nullable=False, default=False)
    # name/expected 任一缺失即视为待补全，映射入库时进入目标集待补全行
    pending_complete = Column(Boolean, nullable=False, default=False)
    # 扩展列 key -> 值，键名由 CaseSet.column_schema 定义
    extras = Column(JSONB, nullable=False, default=dict)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class EvalItem(Base):
    """样本级评测结果：benchmark 任务按「profile × 行」落一行。

    ``score`` 为主指标得分；调用失败样本为 ``None`` 且 ``error`` 非空，
    不计入评分分母。question/reference/context 为任务执行时点的快照，
    数据集行后续被编辑不影响历史报告回放。
    """

    __tablename__ = "eval_items"
    __table_args__ = (
        UniqueConstraint("task_id", "profile_id", "row_no", name="uq_eval_items_task_profile_row"),
        Index("ix_eval_items_task_profile", "task_id", "profile_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True)
    # 协议档 ID 以字符串保存：档位删除后历史样本结果仍可回放
    profile_id = Column(String, nullable=False)
    row_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False, default="")
    reference = Column(Text, nullable=False, default="")
    context = Column(Text, nullable=True)
    output = Column(Text, nullable=False, default="")
    score = Column(Float, nullable=True)
    exact = Column(Float, nullable=True)
    rouge_l = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    # 错误码与摘要（如 "UPSTREAM: 上游返回 401"），绝不包含 API Key
    error = Column(Text, nullable=True)
    # 上游原始响应（超 32KB 截断），供样本页 Raw 报文回放
    raw = Column(JSONB, nullable=True)
    # 归一后的 token 用量 {prompt_tokens, completion_tokens, total_tokens}
    usage = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class UsageLedger(Base):
    """token 用量与估算费用台账：每「任务 × 协议档」一行，执行器逐调用累加。

    费用估算口径：``total_tokens / 1000 × settings.stress.price_per_1k_tokens``；
    任务级预算熔断由 Worker 按 ``settings.default_max_usd``（默认 5）执行。
    """

    __tablename__ = "usage_ledger"
    __table_args__ = (
        UniqueConstraint("task_id", "profile_id", name="uq_usage_ledger_task_profile"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True)
    profile_id = Column(String, nullable=False)
    prompt_tokens = Column(BigInteger, nullable=False, default=0)
    completion_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    est_cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
