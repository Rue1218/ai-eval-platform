"""Harness 编排层：Agent Registry（Worker 能力注册表，H0 基础设施）。

``AgentDef`` 描述同一张 LangGraph 图内的 Worker 配置（能力标签 + 允许工具
视野 + Skill 绑定 + 权限上限 + 预算），**不是**独立进程或独立图（ADR-3 /
C-5：不新增第二条 Agent 循环与第二个模型入口）。

- ``AgentDef.allowed_tools`` 只允许使用 ``ToolRegistry`` 注册全名；
- ``model_profile_id`` 只持协议档 ID（ADR-3：档不可用 fail-closed，禁止静默
  回落）；``None`` 表示沿用会话当前协议档；
- 加载方式为**静态注册 + 启动期校验**（对齐 ADR-8「禁止未知 Server 动态
  加载」）：不通过时严格模式抛 ``AppError(VALIDATION)`` 阻止进程启动，
  宽松模式仅告警。``discover`` 打分选择在 H3 接线（本层只提供注册与校验）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from app.errors import AppError, ErrorCode

logger = logging.getLogger("harness.agents")

# Worker 权限上限（收敛 ToolPermissionPolicy 的 workspace 档位）
AgentPermission = Literal["read", "write", "code"]


@dataclass(frozen=True, slots=True)
class AgentDef:
    """Worker 能力定义（AgentRegistry 唯一源）。

    ``allowed_tools`` 是本 Worker 的工具视野上限，由后续 ``discover`` 节点
    收窄注入 ``RootState.allowed_tools``；未在 ToolRegistry 注册的名字在
    启动期即 fail-fast。
    """

    agent_id: str  # 如 "worker.general"
    display_name: str  # 如 "通用助手"
    capabilities: frozenset[str]  # 能力标签，如 {"general"}
    allowed_tools: tuple[str, ...]  # 工具视野白名单（必须为 ToolRegistry 注册全名）
    skill_ids: tuple[str, ...] = ()  # 可绑定技能；空 = 不注入工作流正文
    max_permission: AgentPermission = "read"  # 权限上限
    budget: Mapping[str, int] = field(default_factory=dict)  # model_calls / tool_turns 上限
    # 协议档 ID 覆盖（ADR-3）：只持档 ID，不持 LLM 实例或协议客户端。
    # None = 沿用会话当前协议档；指定档不存在或未配 Key 时 fail-closed，
    # 禁止静默回落（会让评测结果模型归属不可信）。
    model_profile_id: str | None = None
    description: str = ""  # 供 Router / Orchestrator 做能力匹配的自然语言说明


class AgentRegistry:
    """Worker 注册表；静态注册 + 查询，模式对齐 ``ToolRegistry``。"""

    def __init__(self) -> None:
        self._defs: dict[str, AgentDef] = {}

    def register(self, def_: AgentDef) -> None:
        """登记 Worker；重名登记抛 VALIDATION（防止覆盖导致分派漂移）。"""
        if def_.agent_id in self._defs:
            raise AppError(ErrorCode.VALIDATION, f"Worker 重复登记：{def_.agent_id}")
        self._defs[def_.agent_id] = def_

    def get(self, agent_id: str) -> AgentDef:
        """按 ID 取 Worker；未注册抛 VALIDATION（对外只读面亦不暴露内部细节）。"""
        definition = self._defs.get(agent_id)
        if definition is None:
            raise AppError(ErrorCode.VALIDATION, f"未注册 Worker：{agent_id}")
        return definition

    def find(self, agent_id: str) -> AgentDef | None:
        """按 ID 取 Worker；未注册返回 None（内部容错查询）。"""
        return self._defs.get(agent_id)

    def names(self) -> tuple[str, ...]:
        """全部 Worker ID（按注册序）。"""
        return tuple(self._defs)

    def iter_defs(self) -> list[AgentDef]:
        """全部 Worker 定义列表。"""
        return list(self._defs.values())

    def is_registered(self, agent_id: str) -> bool:
        """判断 Worker 是否已注册（discover 兜底与启动校验用）。"""
        return agent_id in self._defs

    def discover(
        self,
        *,
        capabilities: frozenset[str] = frozenset(),
        skill_id: str | None = None,
    ) -> AgentDef:
        """确定性选择 Worker（H3 discover 节点消费；不调模型，同输入稳定同输出）。

        匹配规则（注册序稳定，无随机）：
        1. ``worker.sandbox`` 静态排除——code 能力须等 H5 持久化 HITL 与安全
           评审后放开，任何 discover 结果都不得包含它（fail-closed）；
        2. 候选 = 能力全含（请求 capabilities ⊆ 声明的 capabilities）的 Worker；
        3. 得分 = 命中能力数 + 绑定该 ``skill_id`` 的加成；得分最高者胜出，
           并列取注册序在先；零命中回落 ``worker.general``（验收：同一输入
           稳定选择同一 Agent）。
        """
        excluded = {"worker.sandbox"}  # H5 前任何 discover 不得选中
        best: AgentDef | None = None
        best_score = -1
        for def_ in self.iter_defs():
            if def_.agent_id in excluded:
                continue
            if not capabilities.issubset(def_.capabilities):
                continue
            score = len(capabilities & def_.capabilities)
            if skill_id is not None and skill_id in def_.skill_ids:
                score += 1
            if score > best_score:
                best, best_score = def_, score
        if best is not None:
            return best
        fallback = self._defs.get("worker.general")
        if fallback is None:
            raise AppError(ErrorCode.VALIDATION, "缺少通用 Worker（worker.general 未注册）")
        return fallback


def build_default_agent_registry() -> AgentRegistry:
    """静态声明首批 Worker（与 ``build_default_registry`` 工具注册表并列）。

    命名口径（对齐混合驱动引擎架构 V1.4）：``allowed_tools`` 一律使用
    ``ToolRegistry`` 注册全名——``task`` 为原生会话任务入口，
    ``TaskCreate|TaskGet|TaskUpdate|TaskList`` 为会话看板四件套（写
    ``session_tasks`` 不写 PG ``tasks`` 表），``platform.tasks.task.*`` 为
    MCP 长任务桥且**不进入任何 Worker 视野**（仅 Workflow ``enqueue`` 节点
    经工具十层链调用，避免探索路径绕过门禁直接入队）。
    """
    registry = AgentRegistry()
    registry.register(
        AgentDef(
            agent_id="worker.general",
            display_name="通用助手",
            capabilities=frozenset({"general"}),
            allowed_tools=("read", "web_search", "web_fetch", "task"),
            max_permission="read",
            description="通用对话与只读探索：读文件、联网检索、会话任务看板",
        )
    )
    registry.register(
        AgentDef(
            agent_id="worker.diagnose",
            display_name="诊断排查",
            capabilities=frozenset({"read_workspace", "analyze_report", "trace_task"}),
            allowed_tools=("read", "TaskGet", "TaskList", "web_search"),
            max_permission="read",
            description="报告解读与任务排查：只读工作区、任务详情与网络检索",
        )
    )
    registry.register(
        AgentDef(
            agent_id="worker.dataset",
            display_name="数据集助手",
            capabilities=frozenset({"inspect_dataset", "prepare_slots"}),
            allowed_tools=("read", "write", "edit", "task"),
            max_permission="write",
            description="数据集检视与槽位整理：工作区内读写编辑与会话任务",
        )
    )
    registry.register(
        AgentDef(
            agent_id="worker.sandbox",
            display_name="沙箱执行",
            capabilities=frozenset({"run_script", "verify_output"}),
            allowed_tools=("read", "bash"),
            max_permission="code",
            description="bash 沙箱执行（code 权限；H5 HITL 持久化前不得被 discover 选中）",
        )
    )
    return registry


@lru_cache(maxsize=1)
def get_default_agent_registry() -> AgentRegistry:
    """返回进程级静态 Worker 注册表唯一实例。

    H0 要求启动期校验、Agent 子图与只读目录共享同一份静态声明。注册表本身
    只在初始化时写入，后续仅查询，缓存该实例既避免三处重复构造，也让启动期
    校验的对象就是运行时实际使用的对象。
    """
    return build_default_agent_registry()


def validate_agent_registry_integrity(
    registry: AgentRegistry,
    *,
    tool_names: frozenset[str],
    skill_ids: frozenset[str],
    db_profile_ids: frozenset[str] | None = None,
    strict: bool = True,
) -> list[str]:
    """启动期一致性校验（H0 硬门槛：Registry 缺项 fail-fast）。

    逐条校验：``allowed_tools ⊆ ToolRegistry``、``skill_ids ⊆ SKILL_CATALOG``、
    ``model_profile_id``（非空时）存在于协议档。返回全部问题描述；
    ``strict=True`` 时任一问题抛 ``AppError(VALIDATION)`` 阻止进程启动；
    ``strict=False`` 仅告警（供测试与降级场景）。
    """
    problems: list[str] = []
    for def_ in registry.iter_defs():
        unknown_tools = [name for name in def_.allowed_tools if name not in tool_names]
        if unknown_tools:
            problems.append(
                f"Worker {def_.agent_id} 引用未注册工具：{', '.join(unknown_tools)}"
            )
        unknown_skills = [sid for sid in def_.skill_ids if sid not in skill_ids]
        if unknown_skills:
            problems.append(
                f"Worker {def_.agent_id} 引用未知技能：{', '.join(unknown_skills)}"
            )
        if def_.model_profile_id is not None and db_profile_ids is not None:
            if def_.model_profile_id not in db_profile_ids:
                problems.append(
                    f"Worker {def_.agent_id} 指向不存在协议档：{def_.model_profile_id}"
                )
    if problems and strict:
        raise AppError(ErrorCode.VALIDATION, "Agent Registry 启动校验失败：" + "；".join(problems))
    return problems
