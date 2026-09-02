"""REST 和 WebSocket 共用的 Pydantic 契约模型。"""

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    """所有输入模型默认拒绝契约外字段，避免浏览器临时字段落库。"""

    model_config = ConfigDict(extra="forbid")


class OrmOut(ApiModel):
    """支持由 SQLAlchemy 模型安全构造的只读响应基类。"""

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(ApiModel):
    """登录请求的用户名和密码。"""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(ApiModel):
    """当前成员的密码变更请求。"""

    old_password: str | None = Field(default=None, max_length=512)
    new_password: str = Field(min_length=8, max_length=512)


class UserCreate(ApiModel):
    """创建成员账号的输入字段，所有成员自动使用 member 角色。"""

    username: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=320)
    password: str = Field(min_length=8, max_length=512)
    must_change_password: bool = True


class UserUpdate(ApiModel):
    """可修改的成员资料，不暴露角色变更能力。"""

    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=320)


class UserStatusUpdate(ApiModel):
    """成员启用或停用请求。"""

    disabled: bool


class ResetPasswordRequest(ApiModel):
    """成员重置密码请求。"""

    password: str = Field(min_length=8, max_length=512)


class UserOut(OrmOut):
    """不包含密码哈希和认证版本的成员响应。"""

    id: str
    username: str
    display_name: str | None = None
    email: str | None = None
    role: Literal["member"] = "member"
    disabled: bool
    must_change_password: bool
    last_login_at: Any | None = None
    last_login_ip: str | None = None
    created_at: Any


class ProfileCreate(ApiModel):
    """创建协议档时的可写字段；三类模型的 API Key 仅在本模型出现。"""

    name: str = Field(min_length=1, max_length=128)
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"]
    base_url: str = Field(min_length=1, max_length=1024)
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    embedding_base_url: str | None = Field(default=None, max_length=1024)
    embedding_model: str | None = Field(default=None, max_length=256)
    embedding_api_key: str | None = Field(default=None, max_length=4096)
    reranker_base_url: str | None = Field(default=None, max_length=1024)
    reranker_model: str | None = Field(default=None, max_length=256)
    reranker_api_key: str | None = Field(default=None, max_length=4096)
    anthropic_version: str | None = Field(default=None, max_length=64)
    usages: list[Literal["target", "agent", "judge"]] = Field(default_factory=list)
    context_window: int = Field(default=200000, ge=1000, le=10000000, description="上下文窗口大小 (Tokens)")
    max_output_tokens: int = Field(
        default=8192, ge=256, le=131072, description="Agent 单回合模型输出上限 (max_tokens)"
    )
    tool_call_mode: Literal["native", "legacy"] = Field(
        default="native", description="Agent 工具调用模式：原生 ToolCall（默认）或受控 JSON 回退"
    )

    @model_validator(mode="before")
    @classmethod
    def clean_empty_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for k in (
                "embedding_base_url",
                "embedding_model",
                "embedding_api_key",
                "reranker_base_url",
                "reranker_model",
                "reranker_api_key",
                "api_key",
                "anthropic_version",
            ):
                if k in data and isinstance(data[k], str) and not data[k].strip():
                    data[k] = None
        return data


class ProfileUpdate(ApiModel):
    """更新协议档；空的三类 API Key 均表示不修改既有密文。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    embedding_base_url: str | None = Field(default=None, max_length=1024)
    embedding_model: str | None = Field(default=None, max_length=256)
    embedding_api_key: str | None = Field(default=None, max_length=4096)
    reranker_base_url: str | None = Field(default=None, max_length=1024)
    reranker_model: str | None = Field(default=None, max_length=256)
    reranker_api_key: str | None = Field(default=None, max_length=4096)
    anthropic_version: str | None = Field(default=None, max_length=64)
    usages: list[Literal["target", "agent", "judge"]] | None = None
    context_window: int | None = Field(default=None, ge=1000, le=10000000, description="上下文窗口大小 (Tokens)")
    max_output_tokens: int | None = Field(
        default=None, ge=256, le=131072, description="Agent 单回合模型输出上限 (max_tokens)"
    )
    tool_call_mode: Literal["native", "legacy"] | None = None

    @model_validator(mode="before")
    @classmethod
    def clean_empty_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for k in (
                "embedding_base_url",
                "embedding_model",
                "embedding_api_key",
                "reranker_base_url",
                "reranker_model",
                "reranker_api_key",
                "api_key",
                "anthropic_version",
            ):
                if k in data and isinstance(data[k], str) and not data[k].strip():
                    data[k] = None
        return data


class ProfileOut(OrmOut):
    """协议档公开字段，任何响应均不含 API Key。"""

    id: str
    name: str
    protocol: str
    base_url: str
    model: str
    usages: list[str]
    anthropic_version: str | None = None
    has_api_key: bool = False
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    has_embedding_api_key: bool = False
    reranker_base_url: str | None = None
    reranker_model: str | None = None
    has_reranker_api_key: bool = False
    context_window: int = 200000
    max_output_tokens: int = 8192
    tool_call_mode: Literal["native", "legacy"] = "native"
    created_at: Any
    updated_at: Any


class FetchModelsIn(ApiModel):
    """远程获取模型列表请求入参。"""

    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"] = "openai_chat"
    base_url: str | None = Field(default=None, max_length=1024)
    api_key: str | None = Field(default=None, max_length=4096)
    profile_id: str | None = None
    anthropic_version: str | None = None



class SessionCreate(ApiModel):
    """创建空 Agent 会话的输入。"""

    title: str = Field(default="新会话", min_length=1, max_length=200)
    visibility: Literal["private", "team"] = "private"


class SessionSharingUpdate(ApiModel):
    """会话创建者设置团队共享范围的输入。"""

    visibility: Literal["private", "team"]


class SessionOut(OrmOut):
    """会话列表项及当前成员的共享管理权限。"""

    id: str
    title: str
    owner_id: str = Field(validation_alias=AliasChoices("user_id", "owner_id"))
    visibility: Literal["private", "team"] = "private"
    created_at: Any
    updated_at: Any
    can_manage: bool = False
    can_delete: bool = False
    active_task: dict[str, Any] | None = None


class MessageOut(OrmOut):
    """REST 回放使用的消息字段。"""

    id: str
    role: str
    content: str
    attachments: list[str | dict[str, Any]]
    author_id: str | None = None
    client_message_id: str | None = None
    latency_ms: int | None = None
    model_name: str | None = None
    profile_id: str | None = None
    profile_name: str | None = None
    provider: str | None = None
    created_at: Any


class FileOut(OrmOut):
    """文件元数据响应，不包含内部存储路径。"""

    id: str
    filename: str
    content_type: str | None = None
    size: int = Field(validation_alias=AliasChoices("size_bytes", "size"))
    sha256: str
    created_at: Any


class DatasetCreate(ApiModel):
    """创建数据集输入；metric 缺省为 contain。"""

    name: str = Field(min_length=1, max_length=100)
    metric: str = Field(default="contain", min_length=1, max_length=32)


class DatasetOut(OrmOut):
    """数据集响应模型（API §3.7；契约 owner_id 即本模型的 created_by）。"""

    id: str
    name: str
    version: int = 1
    folder_id: str | None = None
    row_count: int = 0
    pending_complete_count: int = 0
    metric: str = "contain"
    # 目录导入发布后的容器状态；手工维护的历史数据集仍保持 draft。
    status: str = "draft"
    # 评测创建时必须冻结该不可变版本，而不是直接读取可编辑行。
    active_version_id: str | None = None
    column_schema: list[dict[str, Any]] = Field(default_factory=list)
    created_by: str | None = None
    created_at: Any


class CatalogEntryIn(ApiModel):
    """目录来源草稿：仅记录经审计的官方身份与允许分发域名。"""

    name: str = Field(min_length=1, max_length=160)
    upstream_owner: str = Field(min_length=1, max_length=160)
    official_project_url: str = Field(min_length=8, max_length=2_000)
    allowed_domains: list[str] = Field(min_length=1, max_length=20)
    purpose: str = Field(default="internal_evaluation_only", max_length=128)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class CatalogReleaseIn(ApiModel):
    """固定 release manifest；提交审核后只允许通过新 release 修订。"""

    display_version: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(min_length=1, max_length=256)
    manifest: dict[str, Any]
    license: dict[str, Any]
    allowed_splits: list[str] = Field(min_length=1, max_length=8)
    filter_schema: dict[str, Any]
    parser_id: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=64)
    task_family: Literal["multiple_choice", "generation", "instruction_following"]
    support_status: Literal["supported", "review_required", "planned"] = "review_required"
    risk_labels: list[str] = Field(default_factory=list, max_length=20)


class ReviewNoteIn(ApiModel):
    """来源、release 或导入审核操作的最小审计意见。"""

    note: str | None = Field(default=None, max_length=2_000)


class ResolveBlockIn(ReviewNoteIn):
    """封禁复核只能恢复批准状态或确认持续封禁。"""

    decision: Literal["approved", "blocked"]


class DatasetImportCreate(ApiModel):
    """创建独立导入作业；外部地址与解析规则只来自已批准 release。"""

    catalog_entry_id: str = Field(min_length=1, max_length=64)
    release_id: str = Field(min_length=1, max_length=64)
    splits: list[str] = Field(min_length=1, max_length=8)
    filter_schema_version: int = Field(ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    target_name: str | None = Field(default=None, min_length=1, max_length=160)
    target_dataset_id: str | None = Field(default=None, min_length=1, max_length=64)
    folder_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_target(self) -> "DatasetImportCreate":
        """目标容器必须是已有数据集或一个待创建名称。"""
        if not self.target_name and not self.target_dataset_id:
            raise ValueError("target_name 与 target_dataset_id 至少填写一项")
        return self


class StagingRowsSave(ApiModel):
    """staging 编辑使用读取时的 revision，避免多人按行号误发布。"""

    expected_staging_revision: int = Field(ge=0)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=20_000)


class PublishImportIn(ReviewNoteIn):
    """发布时必须同时锁定导入批次、revision 与稳定 staging 行 ID。"""

    import_id: str = Field(min_length=1, max_length=64)
    expected_staging_revision: int = Field(ge=0)
    accepted_row_ids: list[str] = Field(min_length=1, max_length=20_000)


class RunConfig(ApiModel):
    """Benchmark 与 RAG 的可复现实行配置。

    字段缺省 ``None`` 表示 REST 请求可省略该键。确认卡预填默认值不在本模型，
    单一事实源见 ``app.agent.defaults.DEFAULT_RUN``（PRD §5.2.2）。
    """

    sample_size: int | None = Field(default=None, ge=1, le=1000)
    concurrency: int | None = Field(default=None, ge=1, le=100)
    timeout_s: int | None = Field(default=None, ge=1, le=600)
    retry: int | None = Field(default=None, ge=0, le=5)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    k: int | None = Field(default=None, ge=1, le=20)
    use_judge: bool = False
    # LLM 裁判协议档（usages 需含 "judge"）：use_judge=True 时必填
    judge_profile_id: str | None = Field(default=None, max_length=64)


class StressConfig(ApiModel):
    """仅质量任务派生压测时可用的参数段。"""

    env: Literal["dev", "test", "staging", "prod"]
    qps: int = Field(ge=1, le=500)
    duration_s: int = Field(ge=1, le=1800)
    sla_p99_ms: int | None = Field(default=None, ge=1)


class CaseSource(ApiModel):
    """用例生成的文件或文本二选一输入。"""

    file_id: str | None = None
    text: str | None = Field(default=None, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_single_source(self) -> "CaseSource":
        """确保用例生成输入在文件和文本之间二选一。"""
        has_file = bool(self.file_id)
        has_text = bool(self.text and self.text.strip())
        if has_file == has_text:
            raise ValueError("case_source 必须且只能提供 file_id 或 text")
        return self


class TaskCreate(ApiModel):
    """确认卡与 REST 共用的 TaskSpec，兼容前端暂存的 config 包装。"""

    kind: Literal["benchmark", "rag", "testcase", "stress"]
    session_id: str | None = None
    parent_task_id: str | None = None
    profile_ids: list[str] = Field(default_factory=list)
    dataset_id: str | None = None
    kb_id: str | None = None
    gold_qa_id: str | None = None
    rag_mode: list[Literal["naive", "local", "global", "hybrid"]] = Field(default_factory=list)
    run: RunConfig | None = None
    with_stress: bool = False
    stress: StressConfig | None = None
    case_source: CaseSource | None = None

    @model_validator(mode="before")
    @classmethod
    def unpack_frontend_config(cls, value: Any) -> Any:
        """兼容已完成前端发送的 {kind, config, session_id} 包装结构。"""
        if not isinstance(value, dict):
            return value
        nested = value.get("config")
        if not isinstance(nested, dict):
            return value
        merged = dict(nested)
        for key, item in value.items():
            if key != "config" and item is not None:
                merged[key] = item
        return merged

    @model_validator(mode="after")
    def validate_by_kind(self) -> "TaskCreate":
        """按 PRD 确认卡规则校验不同 kind 的必填段。"""
        if self.kind == "benchmark":
            if not 1 <= len(self.profile_ids) <= 5:
                raise ValueError("benchmark 需要 1–5 个 profile_ids")
            if not self.dataset_id:
                raise ValueError("benchmark 需要 dataset_id")
            if not self.run:
                raise ValueError("benchmark 需要 run")
            if self.run.use_judge and not self.run.judge_profile_id:
                raise ValueError("启用 LLM 裁判时需要 judge_profile_id")
        elif self.kind == "rag":
            if not self.kb_id or not self.gold_qa_id:
                raise ValueError("rag 需要 kb_id 和 gold_qa_id")
            if not self.run:
                raise ValueError("rag 需要 run")
        elif self.kind == "testcase":
            if not self.case_source:
                raise ValueError("testcase 需要 case_source")
        elif not self.parent_task_id:
            raise ValueError("手动创建 stress 任务需要 parent_task_id")

        if self.with_stress:
            if self.kind not in {"benchmark", "rag"}:
                raise ValueError("with_stress 仅支持 benchmark 或 rag")
            if not self.stress:
                raise ValueError("with_stress=true 时需要 stress")
        return self

    def snapshot(self) -> dict[str, Any]:
        """生成可复现的任务配置快照，不重复保存会话关联字段。"""
        return self.model_dump(exclude={"session_id"}, exclude_none=True, mode="json")


class TaskEventOut(OrmOut):
    """任务详情时间线中的单条事件。"""

    id: int
    task_id: str
    event: str
    level: str
    message: str | None = None
    payload: dict[str, Any]
    ts: Any


class TaskOut(OrmOut):
    """任务列表与创建接口的统一响应（API §3.10：item 含 dataset_id/kb_id/creator_id 顶层引用）。"""

    id: str
    session_id: str | None
    parent_task_id: str | None
    kind: str
    status: str
    config: dict[str, Any]
    progress: dict[str, Any]
    result: dict[str, Any]
    report_id: str | None
    # 顶层引用字段：Task ORM 无同名列，由路由层 _task_out 从 config 快照提升填充
    dataset_id: str | None = None
    kb_id: str | None = None
    # 契约字段名 creator_id 与既有前端字段 creator 并存输出，保证新旧消费端兼容
    creator: str = Field(validation_alias=AliasChoices("created_by", "creator"))
    creator_id: str | None = Field(default=None, validation_alias=AliasChoices("created_by", "creator_id"))
    created_at: Any
    updated_at: Any


class TaskDetailOut(TaskOut):
    """任务详情额外返回的追加式事件时间线。"""

    events: list[TaskEventOut] = Field(default_factory=list)


class PageOut(OrmOut):
    """统一分页外层，具体路由传入 items 内容。"""

    items: list[Any]
    total: int


# ─── 调度内核与 Worker 节点管理（API V1.3 §3.13） ───


class DispatchWorkerCreate(ApiModel):
    """注册新 Worker 执行节点的输入。"""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    caps: list[str] = Field(default_factory=list)
    weight: int = Field(default=100, ge=1, le=1000)


class DispatchWorkerUpdate(ApiModel):
    """修改节点状态、权重或能力标签；状态取值对齐调度契约。"""

    state: Literal["idle", "busy", "offline", "draining"] | None = None
    weight: int | None = Field(default=None, ge=1, le=1000)
    caps: list[str] | None = None


class DispatchWorkerOut(OrmOut):
    """调度面可读的 Worker 心跳与能力快照。"""

    id: str
    name: str
    caps: list[str]
    state: str
    weight: int
    load_percent: float | None = None
    current_task: str | None = None
    last_heartbeat_at: Any | None = None


class DispatchConfigUpdate(ApiModel):
    """更新分发策略与全局并发容量。"""

    strategy: Literal["负载均衡", "优先级抢占", "亲和性"] | None = None
    max_running_tasks: int | None = Field(default=None, ge=1, le=64)


class DispatchOverviewOut(ApiModel):
    """调度中心大盘指标与内核雷达状态。"""

    online_workers: int
    total_workers: int
    queue_depth: int
    avg_dispatch_cost_ms: float
    assigned_today: int
    strategy: str
    max_running_tasks: int
    heartbeat_interval_ms: int


class DispatchEventOut(OrmOut):
    """调度分配日志流中的单条事件。"""

    id: int
    task_id: str | None = None
    worker_id: str | None = None
    event: str
    message: str
    ts: Any


class DispatchEventPage(ApiModel):
    """增量事件流响应，next_after_id 供下一轮轮询携带。"""

    items: list[DispatchEventOut]
    next_after_id: int


# ─── MCP 工具中心（API V1.3 §3.6.1，V1.0 只读） ───


class McpToolOut(ApiModel):
    """MCP 工具注册清单项，区分已挂载内置工具与独立注册项。"""

    name: str
    desc: str
    permission: Literal["read", "write"]
    enabled: bool
    source: Literal["builtin", "standalone"] = "builtin"


# ─── 数据集工作台扩展（API V1.3 §3.7） ───


class ColumnSchemaItem(ApiModel):
    """数据集自定义扩展列定义，行内扩展值按 key 落入 DatasetRow.extras。"""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=32)
    required: bool = False
    sort_order: int = 0


class DatasetUpdate(ApiModel):
    """数据集可修改字段；column_schema 为整体替换而非合并。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    metric: str | None = Field(default=None, min_length=1, max_length=32)
    folder_id: str | None = None
    column_schema: list[ColumnSchemaItem] | None = None

    @model_validator(mode="after")
    def validate_unique_column_keys(self) -> "DatasetUpdate":
        """扩展列 key 必须全局唯一，否则行内扩展值无法对应列定义。"""
        if self.column_schema is not None:
            keys = [col.key for col in self.column_schema]
            if len(keys) != len(set(keys)):
                raise ValueError("column_schema 中存在重复 key")
        return self


class FolderIn(ApiModel):
    """目录创建/更新共用输入；POST 时 name 由路由校验必填，PUT 仅修改提供的字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: str | None = None
    sort_order: int | None = None


class FolderOut(OrmOut):
    """数据集目录树节点响应。"""

    id: str
    name: str
    parent_id: str | None = None
    sort_order: int = 0
    created_at: Any


class DatasetRowIn(ApiModel):
    """单行保存输入：q/r/c 短名映射 question/reference/context，其余键进入 extras。"""

    # 扩展列 key 由 Dataset.column_schema 动态定义，此处必须放行契约外字段
    model_config = ConfigDict(extra="allow")

    row_no: int = Field(ge=1)
    q: str | None = Field(default=None, max_length=100_000)
    r: str | None = Field(default=None, max_length=100_000)
    c: str | None = Field(default=None, max_length=100_000)
    source_case_id: str | None = Field(default=None, max_length=64)


class RowsPayload(ApiModel):
    """批量保存请求；row_no 缺失由字段校验拦截为 VALIDATION，此处拦截重复。"""

    rows: list[DatasetRowIn] = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def validate_unique_row_no(self) -> "RowsPayload":
        """单次批量保存内 row_no 不允许重复，避免 upsert 目标行歧义。"""
        row_nos = [row.row_no for row in self.rows]
        if len(row_nos) != len(set(row_nos)):
            raise ValueError("rows 中存在重复 row_no")
        return self


class AiGenerateIn(ApiModel):
    """AI 候选生成请求；模型调用层重建设计期间仅保留接口契约。"""

    dataset_id: str = Field(min_length=1, max_length=64)
    mode: Literal["scene", "seed", "doc", "fill_missing"]
    instruction: str | None = Field(default=None, max_length=20_000)
    source_text: str | None = Field(default=None, max_length=1_000_000)
    seed: str | None = Field(default=None, max_length=100_000)
    rows: list[dict[str, Any]] | None = None
    max_count: int = Field(default=10, ge=1, le=50)
    model: str | None = Field(default=None, max_length=256)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def validate_by_mode(self) -> "AiGenerateIn":
        """fill_missing 必须携带待补全行；其余模式至少要有一段生成依据。"""
        if self.mode == "fill_missing":
            if not self.rows:
                raise ValueError("fill_missing 模式必须提供待补全 rows")
        elif not any(
            [
                self.instruction and self.instruction.strip(),
                self.source_text and self.source_text.strip(),
                self.seed and self.seed.strip(),
            ]
        ):
            raise ValueError("请至少提供 instruction、source_text 或 seed 之一")
        return self


# ─── 用例工作台（API V1.3 §3.8） ───


class CaseSetCreate(ApiModel):
    """创建空用例集输入；column_schema 规则同数据集自定义列。"""

    name: str = Field(min_length=1, max_length=100)
    folder_id: str | None = None
    column_schema: list[ColumnSchemaItem] | None = None

    @model_validator(mode="after")
    def validate_unique_column_keys(self) -> "CaseSetCreate":
        """扩展列 key 必须全局唯一，否则用例行内扩展值无法对应列定义。"""
        if self.column_schema is not None:
            keys = [col.key for col in self.column_schema]
            if len(keys) != len(set(keys)):
                raise ValueError("column_schema 中存在重复 key")
        return self


class CaseSetUpdate(ApiModel):
    """用例集可修改字段；column_schema 为整体替换，confirmed 集由路由层拒绝。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    folder_id: str | None = None
    column_schema: list[ColumnSchemaItem] | None = None

    @model_validator(mode="after")
    def validate_unique_column_keys(self) -> "CaseSetUpdate":
        """扩展列 key 必须全局唯一，否则用例行内扩展值无法对应列定义。"""
        if self.column_schema is not None:
            keys = [col.key for col in self.column_schema]
            if len(keys) != len(set(keys)):
                raise ValueError("column_schema 中存在重复 key")
        return self


class CaseSetOut(OrmOut):
    """用例集列表项响应（API §3.8）；expires_at 由任务域写入，此处原样返回。"""

    id: str
    task_id: str | None = None
    name: str
    status: str = "generated"
    generated_count: int = 0
    confirmed_count: int = 0
    folder_id: str | None = None
    column_schema: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    expires_at: Any | None = None
    created_at: Any
    updated_at: Any | None = None


class CaseSetDetailOut(CaseSetOut):
    """用例集详情额外返回的用例行数组（固定字段 + 扩展列平铺）。"""

    cases: list[dict[str, Any]] = Field(default_factory=list)


class CaseIn(ApiModel):
    """单条用例保存输入：固定字段之外的扩展列 key 进入 CaseItem.extras。"""

    # 扩展列 key 由 CaseSet.column_schema 动态定义，此处必须放行契约外字段
    model_config = ConfigDict(extra="allow")

    id: str | None = Field(default=None, max_length=64)
    strategy: str = Field(min_length=1, max_length=32)
    priority: str = Field(min_length=1, max_length=16)
    module: str = Field(default="", max_length=100)
    submodule: str | None = Field(default=None, max_length=100)
    feature_point: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    precondition: str | None = Field(default=None, max_length=100_000)
    steps: str | None = Field(default=None, max_length=100_000)
    expected: str | None = Field(default=None, max_length=100_000)
    test_type: str | None = Field(default=None, max_length=64)


class CasesPayload(ApiModel):
    """批量保存用例请求；单次请求内用例 id 不允许重复，避免 upsert 目标歧义。"""

    cases: list[CaseIn] = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def validate_unique_case_id(self) -> "CasesPayload":
        """单次批量保存内显式 id 不允许重复；缺省 id 由服务端生成，不参与查重。"""
        ids = [case.id for case in self.cases if case.id]
        if len(ids) != len(set(ids)):
            raise ValueError("cases 中存在重复 id")
        return self


class CaseConfirmIn(ApiModel):
    """确认/废弃用例集请求；ok=false 时置 cancelled 并联动关联任务。"""

    ok: bool
    # edits / mapping_target / target_id 为契约预留字段：映射入库走 /map 接口，
    # 本接口仅消费 ok 做状态流转，其余字段接收后仅记入审计明细
    edits: dict[str, Any] | None = None
    mapping_target: Literal["dataset", "gold_qa"] | None = None
    target_id: str | None = Field(default=None, max_length=64)


class CaseCancelIn(ApiModel):
    """废弃用例集请求，可附废弃原因。"""

    reason: str | None = Field(default=None, max_length=2000)


class CaseMapIn(ApiModel):
    """批量映射用例到目标基准数据集或知识库黄金问答的请求。"""

    target: Literal["dataset", "gold_qa"]
    target_id: str = Field(min_length=1, max_length=64)
    case_ids: list[str] = Field(min_length=1, max_length=20_000)


class CaseAiGenerateIn(ApiModel):
    """AI 候选用例生成请求；仅返回未落库候选，不创建用例集。"""

    source_doc_id: str | None = Field(default=None, max_length=64)
    source_text: str | None = Field(default=None, max_length=1_000_000)
    # 6 大策略配比（百分比），键取值 positive/negative/boundary/equivalence/state/scenario
    strategy_weights: dict[str, int] | None = None
    complexity: str | None = Field(default=None, max_length=32)
    max_count: int = Field(default=45, ge=1, le=100)

    @model_validator(mode="after")
    def validate_source(self) -> "CaseAiGenerateIn":
        """source_doc_id 与 source_text 至少填一项，作为用例生成依据。"""
        has_doc = bool(self.source_doc_id)
        has_text = bool(self.source_text and self.source_text.strip())
        if not (has_doc or has_text):
            raise ValueError("source_doc_id 与 source_text 至少填一项")
        return self


class CaseAiFillIn(ApiModel):
    """行级 AI 补全请求；case_ids 必填且必须全部属于该用例集。"""

    case_ids: list[str] = Field(min_length=1, max_length=20_000)
    instruction: str | None = Field(default=None, max_length=20_000)
    # 缺省时补全所有缺失字段；提供时仅补全指定字段（含扩展列 key）
    fields: list[str] | None = Field(default=None, max_length=64)


class KbCreate(ApiModel):
    """知识库创建输入：kind 区分 LightRAG 原生库与外部 RAG 服务。"""

    name: str = Field(min_length=1, max_length=100)
    kind: Literal["lightrag", "external_chat"] = "lightrag"
    profile_id: str | None = Field(default=None, max_length=64)


class KbUpdate(ApiModel):
    """知识库更新输入：仅修改提供的字段，拒绝契约外字段落库。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: Literal["lightrag", "external_chat"] | None = None
    profile_id: str | None = Field(default=None, max_length=64)
    is_core: bool | None = None


class KbOut(ApiModel):
    """知识库响应：doc_count / owner / capabilities 为派生字段，手动构造。"""

    id: str
    name: str
    kind: str
    doc_count: int | None = None
    is_core: bool = False
    owner: str = ""
    profile_id: str | None = None
    capabilities: dict = Field(default_factory=lambda: {"projection": False, "rerank_compare": False})
    created_at: Any | None = None


class KbDocOut(ApiModel):
    """知识库文档响应：size 为格式化展示串（如 "12.4 KB"）。"""

    doc_id: str
    filename: str
    status: str
    size: str = ""
    created_at: Any | None = None


class KbChunkOut(ApiModel):
    """切块预览响应。"""

    chunk_id: str
    doc_id: str
    text: str
    tokens: int


class KbQueryIn(ApiModel):
    """检索 Playground 请求。"""

    query: str = Field(min_length=1, max_length=20_000)
    mode: Literal["naive", "local", "global", "hybrid"] = "hybrid"
    k: int = Field(default=5, ge=1, le=20)


class KbQueryItemOut(ApiModel):
    """检索结果单条：hit 标记该切块文档是否命中黄金 QA 期望文档。"""

    chunk_id: str
    doc_name: str = ""
    similarity: float | None = None
    text: str = ""
    hit: bool = False


class KbQueryOut(ApiModel):
    """检索 Playground 响应：指标按「question 匹配的黄金 QA 行」计算。"""

    query: str
    mode: str
    items: list[KbQueryItemOut] = Field(default_factory=list)
    reranked_ids: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=lambda: {"hit_rate": 0.0, "mrr": 0.0, "recall": 0.0, "contain": 0.0})


class GoldQaOut(ApiModel):
    """黄金 QA 集响应。"""

    id: str
    kb_id: str
    name: str
    version: int
    row_count: int
    owner: str = ""
    created_at: Any | None = None
