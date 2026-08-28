"""平台 M1 数据库模型（api / worker 共享的单一事实源）。

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
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import UserDefinedType

Base = declarative_base()


class PgVectorType(UserDefinedType):
    """不引入额外 ORM 依赖的 pgvector 列类型；仅记忆层模型使用。"""

    cache_ok = True

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kwargs: object) -> str:
        """生成 PostgreSQL pgvector 的确定维度列定义。"""
        return f"vector({self.dimensions})"

    def bind_processor(self, _dialect: object):
        """将 Python 浮点数组安全序列化为 PostgreSQL vector 文本。"""
        def process(value: list[float] | str | None) -> str | None:
            if value is None or isinstance(value, str):
                return value
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, _dialect: object, _coltype: object):
        """将 pgvector 文本恢复为浮点数组，异常值只作为空向量处理。"""
        def process(value: str | list[float] | None) -> list[float] | None:
            if value is None or isinstance(value, list):
                return value
            try:
                return [float(item) for item in value.strip("[]").split(",") if item]
            except (TypeError, ValueError):
                return None

        return process


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
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'team')", name="ck_sessions_visibility"
        ),
        Index("ix_sessions_visibility_deleted_at", "visibility", "deleted_at"),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    # 创建者（owner）始终不变；团队共享不改变资产归属。
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False, default="新会话")
    # private 仅 owner 可访问；team 对当前内部团队的正常成员开放协作。
    visibility = Column(
        String,
        nullable=False,
        default="private",
        server_default=text("'private'"),
    )
    # 软删除仅隐藏会话入口，消息、事件、任务和报告仍保留供审计回溯。
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # 当前未 ack 的确认卡（TaskSpec）；刷新回放优先读此列，禁止只靠进程内字典
    pending_confirm = Column(JSONB, nullable=True)
    # 确认卡属于提出该卡的成员，团队协作者不能替其确认、拒绝或覆盖。
    pending_confirm_author_id = Column(String, ForeignKey("users.id"), nullable=True)
    # /compact 摘要与窗口游标（messages.id）；从未压缩时皆为空
    compact_summary = Column(Text, nullable=True)
    compact_keep_from = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Message(Base):
    """可通过 REST 回放的会话文本和已上传附件引用。"""

    __tablename__ = "messages"
    __table_args__ = (
        # 同一浏览器重连重发同一个 client_message_id 时只保留一条用户消息。
        UniqueConstraint(
            "session_id", "client_message_id", name="uq_messages_session_client_message"
        ),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    attachments = Column(JSONB, nullable=False, default=list)
    # user 消息记录实际发言人；assistant/system 由平台生成，保留为空。
    author_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    # 浏览器生成的幂等键，仅 user 消息使用，供实时回显去重。
    client_message_id = Column(String(128), nullable=True)
    # assistant 交付句的回复生成耗时（毫秒）：从本轮 user_message 入 Harness 到交付的墙钟时长。
    # 仅 assistant 消息非空，user/system 保持 NULL；历史回放供前端气泡展示「耗时 x 秒」。
    latency_ms = Column(Integer, nullable=True)
    # turn 级观测指标快照（仅 assistant 消息）：模型轮数/token 用量/工具成败计数，
    # 由 react 收尾时随 assistant_message 事件写入，供前端气泡与性能归因展示。
    turn_stats = Column(JSONB, nullable=True)
    # 消息生成元数据快照（仅 assistant 消息记录实际生成该回答的模型与协议档快照，切换全局模型时不漂移）。
    model_name = Column(String(255), nullable=True)
    profile_id = Column(String(64), nullable=True)
    profile_name = Column(String(255), nullable=True)
    provider = Column(String(64), nullable=True)
    # 记忆层溯源：历史存量回填为 message:{id}，新消息由写入方一次性指定。
    source_id = Column(String, nullable=False, index=True)
    source_version = Column(Integer, nullable=False, default=1)
    origin_trace_id = Column(String, nullable=True, index=True)
    origin_span_id = Column(String, nullable=True)
    # forget/撤权后只禁止记忆召回，不删除 REST 审计消息。
    memory_revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class KnowledgeMemory(Base):
    """同库 pgvector 知识记忆；ACL/撤权先过滤，再由 MemoryPort 提供给 Context。"""

    __tablename__ = "memory_knowledge"
    __table_args__ = (
        Index("ix_memory_knowledge_tenant_source", "tenant_id", "source_id"),
        Index("ix_memory_knowledge_revoked", "memory_revoked"),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    tenant_id = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False, index=True)
    source_version = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    embedding = Column(PgVectorType(1536), nullable=True)
    # metadata 是 SQLAlchemy 保留属性名，模型属性使用 meta，数据库列仍为 metadata。
    meta = Column("metadata", JSONB, nullable=False, default=dict)
    acl = Column(String, nullable=False, default="tenant")
    acl_user_ids = Column(JSONB, nullable=False, default=list)
    origin_trace_id = Column(String, nullable=True, index=True)
    origin_span_id = Column(String, nullable=True)
    memory_revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


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
    context_window = Column(Integer, nullable=False, default=200000)
    # 单回合模型输出上限（max_tokens）：长文档总结/导出类任务可调大，
    # 避免回答在 8192 token 处被上游截断；未配置时回退 8192。
    max_output_tokens = Column(Integer, nullable=False, default=8192, server_default="8192")
    # 兼容优先：只有经人工验证的协议档才显式开启上游原生 tools。
    tool_call_mode = Column(
        String, nullable=False, default="native", server_default="native"
    )
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
    """数据集容器：正式评测只读取 active_version_id 指向的不可变版本。"""

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
    # 容器状态与当前可评测版本分离，新的 staging 导入不影响旧 active 版本。
    status = Column(String, nullable=False, default="draft", server_default="draft")
    active_version_id = Column(
        String,
        ForeignKey("dataset_versions.id", name="fk_datasets_active_version", use_alter=True),
        nullable=True,
        index=True,
    )
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetCatalogEntry(Base):
    """公开基准的稳定来源身份；可导入制品由其 release 另行冻结。"""

    __tablename__ = "dataset_catalog_entries"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    upstream_owner = Column(String, nullable=False)
    official_project_url = Column(Text, nullable=False)
    allowed_domains = Column(JSONB, nullable=False, default=list)
    purpose = Column(String, nullable=False, default="internal_evaluation_only")
    evidence_refs = Column(JSONB, nullable=False, default=list)
    status = Column(String, nullable=False, default="draft", index=True)
    submitted_by = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class DatasetCatalogRelease(Base):
    """目录来源的一次不可变 release manifest；审核后禁止原地修改。"""

    __tablename__ = "dataset_catalog_releases"
    __table_args__ = (
        UniqueConstraint("catalog_entry_id", "manifest_hash", name="uq_catalog_release_manifest"),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    catalog_entry_id = Column(String, ForeignKey("dataset_catalog_entries.id"), nullable=False, index=True)
    display_version = Column(String, nullable=False)
    source_revision = Column(String, nullable=False)
    manifest = Column(JSONB, nullable=False, default=dict)
    manifest_hash = Column(String(64), nullable=False, index=True)
    license = Column(JSONB, nullable=False, default=dict)
    allowed_splits = Column(JSONB, nullable=False, default=list)
    filter_schema = Column(JSONB, nullable=False, default=dict)
    parser_id = Column(String, nullable=False)
    parser_version = Column(String, nullable=False)
    task_family = Column(String, nullable=False)
    support_status = Column(String, nullable=False, default="review_required")
    risk_labels = Column(JSONB, nullable=False, default=list)
    status = Column(String, nullable=False, default="draft", index=True)
    submitted_by = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class DatasetCatalogReview(Base):
    """目录/release 的追加式审核记录；双人复核由服务层校验。"""

    __tablename__ = "dataset_catalog_reviews"

    id = Column(String, primary_key=True, default=uuid_str)
    catalog_entry_id = Column(String, ForeignKey("dataset_catalog_entries.id"), nullable=True, index=True)
    release_id = Column(String, ForeignKey("dataset_catalog_releases.id"), nullable=True, index=True)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    previous_status = Column(String, nullable=True)
    next_status = Column(String, nullable=False)
    manifest_hash = Column(String(64), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetImport(Base):
    """独立导入队列主记录；不复用评测 Task，也不产生评测报告。"""

    __tablename__ = "dataset_imports"
    __table_args__ = (
        UniqueConstraint("request_fingerprint", name="uq_dataset_import_fingerprint"),
        Index("ix_dataset_import_queue", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=uuid_str)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    catalog_release_id = Column(String, ForeignKey("dataset_catalog_releases.id"), nullable=False, index=True)
    request_fingerprint = Column(String(64), nullable=False)
    manifest = Column(JSONB, nullable=False, default=dict)
    manifest_hash = Column(String(64), nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    stage = Column(String, nullable=False, default="queued")
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    lease_token = Column(String(64), nullable=True, unique=True)
    lease_owner = Column(String, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    staging_revision = Column(Integer, nullable=False, default=0)
    summary = Column(JSONB, nullable=False, default=dict)
    error = Column(JSONB, nullable=False, default=dict)
    created_by = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    reviewed_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class DatasetImportAttempt(Base):
    """导入作业的单次领取与执行记录，用于租约回收和失败诊断。"""

    __tablename__ = "dataset_import_attempts"
    __table_args__ = (UniqueConstraint("import_id", "attempt_no", name="uq_dataset_import_attempt"),)

    id = Column(String, primary_key=True, default=uuid_str)
    import_id = Column(String, ForeignKey("dataset_imports.id"), nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False)
    worker_id = Column(String, nullable=True)
    lease_token = Column(String(64), nullable=False, unique=True)
    stage = Column(String, nullable=False, default="queued")
    error_code = Column(String, nullable=True)
    error_summary = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class DatasetSourceArtifact(Base):
    """Worker 实际取得的制品快照；哈希与 release manifest 一起进入正式版本。"""

    __tablename__ = "dataset_source_artifacts"

    id = Column(String, primary_key=True, default=uuid_str)
    import_id = Column(String, ForeignKey("dataset_imports.id"), nullable=False, index=True)
    artifact_name = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    size_bytes = Column(BigInteger, nullable=False)
    media_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetImportRow(Base):
    """导入产生的 staging 行；稳定 UUID 取代可变 row_no 作为发布选择键。"""

    __tablename__ = "dataset_import_rows"
    __table_args__ = (UniqueConstraint("import_id", "row_no", name="uq_dataset_import_row_no"),)

    id = Column(String, primary_key=True, default=uuid_str)
    import_id = Column(String, ForeignKey("dataset_imports.id"), nullable=False, index=True)
    row_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False, default="")
    reference = Column(Text, nullable=False, default="")
    context = Column(Text, nullable=True)
    extras = Column(JSONB, nullable=False, default=dict)
    row_status = Column(String, nullable=False, default="staging")
    provenance = Column(JSONB, nullable=False, default=dict)
    warnings = Column(JSONB, nullable=False, default=list)
    content_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class DatasetVersion(Base):
    """审核发布后的不可变数据集版本；active_version_id 仅指向该表。"""

    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_no", name="uq_dataset_version_no"),)

    id = Column(String, primary_key=True, default=uuid_str)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=False, index=True)
    import_id = Column(String, ForeignKey("dataset_imports.id"), nullable=True, index=True)
    version_no = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="active")
    manifest = Column(JSONB, nullable=False, default=dict)
    content_sha256 = Column(String(64), nullable=False, index=True)
    scorer_version = Column(String, nullable=False)
    published_by = Column(String, ForeignKey("users.id"), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetVersionRow(Base):
    """正式版本行快照；评测 Worker 仅可读取此表而非可编辑 staging。"""

    __tablename__ = "dataset_version_rows"
    __table_args__ = (UniqueConstraint("dataset_version_id", "row_no", name="uq_dataset_version_row_no"),)

    id = Column(String, primary_key=True, default=uuid_str)
    dataset_version_id = Column(String, ForeignKey("dataset_versions.id"), nullable=False, index=True)
    source_import_row_id = Column(String, ForeignKey("dataset_import_rows.id"), nullable=True)
    row_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    reference = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    extras = Column(JSONB, nullable=False, default=dict)
    provenance = Column(JSONB, nullable=False, default=dict)
    content_sha256 = Column(String(64), nullable=False)


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
    # 用例八字段格式扩展：子模块 / 功能点（PRD 用例模板）
    submodule = Column(String, nullable=False, default="")
    feature_point = Column(String, nullable=False, default="")
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
    # LLM 裁判打分（0-100 整数）：仅 use_judge 任务启用；未启用/未判样本为 None
    judge_score = Column(Integer, nullable=True)
    # 裁判评分理由（≤500 字），仅裁判打分成功样本非空
    judge_reason = Column(Text, nullable=True)
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


class KnowledgeBase(Base):
    """知识库资产：LightRAG 原生库或挂在协议档下的外部 RAG 服务。"""

    __tablename__ = "knowledge_bases"

    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, nullable=False)
    # lightrag（原生 query + 切块） | external_chat（外部 RAG 服务，挂在 profile）
    kind = Column(String, nullable=False, default="lightrag")
    # external_chat 时指向协议档 ID；lightrag 内置评测可不填
    profile_id = Column(String, nullable=True)
    # 核心库标记：整平台至多一个（由路由层维护互斥）
    is_core = Column(Boolean, nullable=False, default=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class KbDocument(Base):
    """知识库文档：保留文本正文用于服务端切块预览与本地检索兜底。"""

    __tablename__ = "kb_documents"
    __table_args__ = (Index("ix_kb_documents_kb_id", "kb_id"),)

    id = Column(String, primary_key=True, default=uuid_str)
    kb_id = Column(String, ForeignKey("knowledge_bases.id"), nullable=False)
    filename = Column(String, nullable=False)
    size = Column(Integer, nullable=False, default=0)
    mime = Column(String, nullable=False, default="")
    # 提取出的纯文本（切块与本地检索的数据源）；二进制文档解码失败时为空
    text = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="indexed")
    # 原始文件在磁盘上的路径（data/kb/{kb_id}/{doc_id}），二进制文档仍落盘
    storage_path = Column(String, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class GoldQa(Base):
    """黄金 QA 集元信息：同名覆盖上传时 version 递增。"""

    __tablename__ = "gold_qas"
    __table_args__ = (Index("ix_gold_qas_kb_id", "kb_id"),)

    id = Column(String, primary_key=True, default=uuid_str)
    kb_id = Column(String, ForeignKey("knowledge_bases.id"), nullable=False)
    name = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    row_count = Column(Integer, nullable=False, default=0)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class GoldQaItem(Base):
    """黄金 QA 行：question/reference 快照 + 期望命中文档 ID 列表。"""

    __tablename__ = "gold_qa_items"
    __table_args__ = (
        UniqueConstraint("gold_qa_id", "row_no", name="uq_gold_qa_items_qa_row_no"),
        Index("ix_gold_qa_items_gold_qa_id", "gold_qa_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    gold_qa_id = Column(String, ForeignKey("gold_qas.id"), nullable=False)
    row_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False, default="")
    reference = Column(Text, nullable=False, default="")
    # 期望命中文档 ID 数组；空数组样本不进 Hit Rate 评估分母
    expected_doc_ids = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class HarnessTurn(Base):
    """Harness 用户 Turn 审计：一个 Turn 一行，供链路回放。

    终态为 FINISHED / CANCELLED / FAILED_STOP；审计只落 PostgreSQL，不进 Redis。
    定时清理任务可后补，本表保留 created_at 供按保留天数过滤。
    """

    __tablename__ = "harness_turns"

    id = Column(String, primary_key=True, default=uuid_str)
    trace_id = Column(String, unique=True, nullable=False, index=True)
    turn_id = Column(String, nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="INIT")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class HarnessSpan(Base):
    """跨层 span：编排 / 执行 / 反馈写入；按 trace_id 索引并随 Turn 过期。"""

    __tablename__ = "harness_spans"
    __table_args__ = (Index("ix_harness_spans_trace_id", "trace_id"),)

    span_id = Column(String, primary_key=True)
    trace_id = Column(String, nullable=False)
    parent_span_id = Column(String, nullable=True)
    component = Column(String, nullable=False, default="")
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    latency_ms = Column(Integer, nullable=True)


class HarnessDiagnostic(Base):
    """受限诊断审计：原始 traceback 仅服务端可见，默认保留 30 天。"""

    __tablename__ = "harness_diagnostics"
    __table_args__ = (Index("ix_harness_diagnostics_trace_id", "trace_id"),)

    diagnostic_id = Column(String, primary_key=True)
    trace_id = Column(String, nullable=False)
    span_id = Column(String, nullable=False)
    traceback = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
