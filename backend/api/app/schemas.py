"""REST 和 WebSocket 共用的 Pydantic 契约模型。"""

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, model_validator


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
    """创建协议档时的可写字段，API Key 仅在本模型出现。"""

    name: str = Field(min_length=1, max_length=128)
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"]
    base_url: HttpUrl
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    anthropic_version: str | None = Field(default=None, max_length=64)
    usages: list[Literal["target", "agent", "judge"]] = Field(default_factory=list)


class ProfileUpdate(ApiModel):
    """更新协议档；空 API Key 表示不修改既有密文。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"] | None = None
    base_url: HttpUrl | None = None
    model: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    anthropic_version: str | None = Field(default=None, max_length=64)
    usages: list[Literal["target", "agent", "judge"]] | None = None


class ProfileOut(OrmOut):
    """协议档公开字段，任何响应均不含加密 Key。"""

    id: str
    name: str
    protocol: str
    base_url: str
    model: str
    usages: list[str]
    anthropic_version: str | None = None
    has_api_key: bool = False
    created_at: Any
    updated_at: Any


class SessionCreate(ApiModel):
    """创建空 Agent 会话的输入。"""

    title: str = Field(default="新会话", min_length=1, max_length=200)


class SessionOut(OrmOut):
    """会话列表项及可选活动任务摘要。"""

    id: str
    title: str
    created_at: Any
    updated_at: Any
    active_task: dict[str, Any] | None = None


class MessageOut(OrmOut):
    """REST 回放使用的消息字段。"""

    id: str
    role: str
    content: str
    attachments: list[str]
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
    """创建数据集输入。"""

    name: str = Field(min_length=1, max_length=100)


class DatasetOut(OrmOut):
    """数据集响应模型。"""

    id: str
    name: str
    version: int = 1
    row_count: int = 0
    created_by: str | None = None
    created_at: Any


class RunConfig(ApiModel):
    """Benchmark 与 RAG 的可复现实行配置。"""

    sample_size: int | None = Field(default=None, ge=1, le=20_000)
    concurrency: int | None = Field(default=None, ge=1, le=100)
    timeout_s: int | None = Field(default=None, ge=1, le=600)
    retry: int | None = Field(default=None, ge=0, le=5)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    k: int | None = Field(default=None, ge=1, le=20)
    use_judge: bool = False


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
    """任务列表与创建接口的统一响应。"""

    id: str
    session_id: str | None
    parent_task_id: str | None
    kind: str
    status: str
    config: dict[str, Any]
    progress: dict[str, Any]
    result: dict[str, Any]
    report_id: str | None
    creator: str = Field(validation_alias=AliasChoices("created_by", "creator"))
    created_at: Any
    updated_at: Any


class TaskDetailOut(TaskOut):
    """任务详情额外返回的追加式事件时间线。"""

    events: list[TaskEventOut] = Field(default_factory=list)


class PageOut(OrmOut):
    """统一分页外层，具体路由传入 items 内容。"""

    items: list[Any]
    total: int
