"""Agent 专家目录：用户在 Agent 页显式选择的专家角色。

与 ``harness/orchestration/agents.py`` 的 Worker 注册表职责不同：

- ``AgentRegistry``：图内按能力自动打分发现的**内部分工**，不对用户暴露；
- 本模块：用户在 Agent 页**显式选择**的专家，是前端选择器的唯一数据源，
  定义专家提示词（追加在核心系统提示词之后）与工具视野。

红线：
- 专家角色与其提示词内置基线随代码版本分发；管理端的专家覆盖层
  （``agent_expert_prompt_overrides``）仅替换有效文本，协议档补充提示词
  （``agent_prompt_overlays``）仍然独立生效，三者不互相覆盖。
- 专家**不能**扩大平台工具白名单：``allowed_tools`` 与 AgentLoop 的
  ``ALLOWED_TOOLS`` 取交集后才生效（见 ``loop_wiring._build_dependencies``）。
- 专家不改变权限、错误契约与任务状态机；提示词只做角色与流程约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.errors import AppError, ErrorCode

# 默认专家：保持平台既有行为（无额外提示词、全工具视野）。
DEFAULT_EXPERT_ID = "general"
_PROMPT_DIR = Path(__file__).resolve().parent / "expert_prompts"


@dataclass(frozen=True, slots=True)
class ExpertDef:
    """一个可被用户选择的专家；``system_prompt`` 为空表示不追加提示词。"""

    expert_id: str
    name: str
    description: str
    badge: str
    prompt_file: str | None = None
    allowed_tools: tuple[str, ...] = ()
    default: bool = False
    deliverable_kind: str | None = None

    @property
    def system_prompt(self) -> str:
        """读取专家提示词；文件缺失或为空时返回空串（由 validate_experts 兜底）。"""
        if not self.prompt_file:
            return ""
        path = _PROMPT_DIR / self.prompt_file
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()


EXPERTS: tuple[ExpertDef, ...] = (
    ExpertDef(
        expert_id=DEFAULT_EXPERT_ID,
        name="通用助手",
        description="平台默认助手：对话、工作区文件、评测任务入队与查询。",
        badge="通用",
        default=True,
    ),
    ExpertDef(
        expert_id="testcase-agent",
        name="测试用例设计专家",
        description="从需求文档生成测试用例：需求解析 → 功能点/测试点拆分 → 六类用例 → CSV 交付。",
        badge="用例设计",
        prompt_file="testcase_agent.md",
        allowed_tools=("read", "write", "edit", "bash", "ask_user_question"),
    ),
    ExpertDef(
        expert_id="benchmark-designer", name="基准设计专家", badge="基准设计",
        description="起草文本模型评测蓝图：测量目标、场景、能力、指标和预算。",
        prompt_file="benchmark_designer.md",
        allowed_tools=("read", "glob", "grep"),
        deliverable_kind="benchmark_blueprint",
    ),
    ExpertDef(
        expert_id="benchmark-data-curator", name="基准数据专家", badge="数据候选",
        description="依据已校验蓝图起草数据候选、来源和独立验证计划，不发布数据。",
        prompt_file="benchmark_data_curator.md",
        allowed_tools=("read", "glob", "grep", "web_search", "web_fetch"),
        deliverable_kind="data_manifest_candidate",
    ),
    ExpertDef(
        expert_id="benchmark-scoring-designer", name="基准评分设计专家", badge="评分草案",
        description="依据已校验蓝图起草评分维度、锚点、缺失处理、校准和复核策略。",
        prompt_file="benchmark_scoring_designer.md",
        allowed_tools=("read", "glob", "grep"),
        deliverable_kind="scoring_policy_draft",
    ),
)
_BY_ID = {expert.expert_id: expert for expert in EXPERTS}


def validate_experts() -> None:
    """启动期校验：ID 唯一、默认专家唯一、声明了提示词的专家必须有正文。

    fail-fast 而非静默降级——专家提示词缺失会让用户选中一个"没有能力的专家"。
    """
    if len(_BY_ID) != len(EXPERTS):
        raise RuntimeError("专家 ID 重复")
    defaults = [expert for expert in EXPERTS if expert.default]
    if len(defaults) != 1:
        raise RuntimeError("必须且只能有一个默认专家")
    for expert in EXPERTS:
        if not expert.expert_id or not expert.name.strip():
            raise RuntimeError(f"专家定义不完整：{expert.expert_id!r}")
        if expert.prompt_file and not expert.system_prompt:
            raise RuntimeError(f"专家提示词缺失或为空：{expert.expert_id}")


def resolve_expert(agent_id: object) -> ExpertDef:
    """解析用户选择的专家；缺省或非法值回落默认专家（不报错，保证旧客户端兼容）。

    显式传入未知 ID 视为前端与后端版本不一致，回落默认专家并在选择器里体现，
    避免因为一个可选字段让整个回合提交失败。
    """
    if isinstance(agent_id, str):
        expert = _BY_ID.get(agent_id.strip())
        if expert is not None:
            return expert
    return _BY_ID[DEFAULT_EXPERT_ID]


def get_expert(expert_id: object) -> ExpertDef:
    """按 ID 严格读取专家定义，供受控管理接口拒绝未知目标。

    与 ``resolve_expert`` 的兼容回落语义不同，管理端不能把拼错的 ID 悄悄
    落到默认专家，否则会造成错误配置或错误审计记录。
    """
    normalized = expert_id.strip() if isinstance(expert_id, str) else ""
    expert = _BY_ID.get(normalized)
    if expert is None:
        raise AppError(ErrorCode.NOT_FOUND, "专家不存在")
    return expert


def list_experts() -> list[dict]:
    """投影给前端选择器：不暴露提示词正文与工具视野细节。"""
    return [
        {
            "id": expert.expert_id,
            "name": expert.name,
            "description": expert.description,
            "badge": expert.badge,
            "default": expert.default,
            **({"deliverable_kind": expert.deliverable_kind} if expert.deliverable_kind else {}),
        }
        for expert in EXPERTS
    ]


def default_expert_id() -> str:
    """当前默认专家 ID（会话 UI 的初始选择）。"""
    return _BY_ID[DEFAULT_EXPERT_ID].expert_id
