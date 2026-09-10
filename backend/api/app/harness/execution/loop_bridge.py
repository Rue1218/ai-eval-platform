"""平台工具到新循环的薄桥，复用注册表、参数校验与单次原生分派。

主 Agent 接线：
* context_factory(identity) 返回平台 resolve_session_sandbox 后的可信上下文。
* authorize(definition, arguments, context) 每次检查 ACL、附件/任务归属、沙箱模式；
  成功返回 None，拒绝抛 AppError，不能把审批决定当作权限。
* SessionLog.append('tool/dispatch') 根据 execution_id/scope_path/access 原子取得
  工作区 guard；append('tool/result') 按 call_id 同事务结算。桥不提前 release。
* runner/interaction/business/mcp(definition, arguments, context, identity) 是异步
  单次执行接口。runner 必须取消并确认进程树终态；无法证实则返回 outcome_unknown。
  interaction 使用独立 TTL；business 负责确认、权限复验和同事务入队收据。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.errors import AppError, ErrorCode
from app.harness.contracts import ToolCall

from .aliases import bash_timeout_seconds, enforce_tool_argument_policy
from .context import ToolExecutionContext
from .dispatch import execute_raw
from .loop_tools import ToolExecutionResult, normalize_tool_output, tool_spec
from .registry import ToolDef, ToolRegistry, validate_tool_arguments

# 只开放文档首批已验证的读取并行语义，未知能力保持独占。
_PARALLEL = frozenset({"read", "read_image", "glob", "grep", "web_search", "web_fetch"})
_ALIASES = {
    "read": (("path", "file_path"), ("next_offset", "offset")),
    "write": (("path", "file_path"),),
    "edit": (("path", "file_path"), ("old", "old_string"), ("new", "new_string")),
    "web_search": (("limit", "max_results"),),
}
DispatchCallback = Callable[
    [ToolDef, dict[str, Any], ToolExecutionContext, dict[str, Any]], Awaitable[object]
]


async def _join(task: asyncio.Task) -> Any:
    """取消不会终止 Python 线程，必须持有任务直到真实工作结束。"""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()


class PlatformToolBridge:
    """请求级白名单与 wire 映射；不创建第二套 handler 或业务服务。"""

    def __init__(
        self, registry: ToolRegistry, *, allowed_tools: Sequence[str],
        context_factory: Callable[[dict[str, Any]], ToolExecutionContext],
        authorize: Callable[[ToolDef, dict[str, Any], ToolExecutionContext], None],
        runner: DispatchCallback | None = None, interaction: DispatchCallback | None = None,
        business: DispatchCallback | None = None, mcp: DispatchCallback | None = None,
        runner_instance_id: str | None = None,
        source_contract: str = "platform.v1",
    ) -> None:
        """调用方传入已取权限交集的白名单；运行期仍会复验，默认不装全部工具。"""
        if source_contract not in {"platform.v1", "deepseek-harness.v1"}:
            raise ValueError("未知工具字段契约版本")
        self.context_factory, self.authorize = context_factory, authorize
        self.runner, self.interaction, self.business, self.mcp = runner, interaction, business, mcp
        self.runner_instance_id = runner_instance_id
        self.source_contract = source_contract
        self.tools: list[PlatformLoopTool] = []
        self.wire_to_name: dict[str, str] = {}
        for name in dict.fromkeys(allowed_tools):
            definition = registry.get(name)
            wire = name if re.fullmatch(r"[A-Za-z0-9_]+", name) else "platform_" + re.sub(r"[^A-Za-z0-9_]", "_", name)
            if wire in self.wire_to_name:
                raise ValueError("工具 wire 名称冲突")
            self.wire_to_name[wire] = name
            self.tools.append(PlatformLoopTool(self, definition, wire))

    def specs(self) -> list:
        """从同一工具定义生成本次模型的 ToolSpec。"""
        return [tool_spec(tool) for tool in self.tools if tool.available]

    def available_tools(self) -> list[PlatformLoopTool]:
        """缺少 Runner/交互/业务适配器的能力不进入模型可见集合。"""
        return [tool for tool in self.tools if tool.available]


@dataclass(frozen=True)
class PlatformLoopTool:
    """单次调用绑定后仍仅需 name/metadata/schema/ainvoke 四项鸭子类型接口。"""

    bridge: PlatformToolBridge
    definition: ToolDef
    name: str
    identity: dict[str, Any] | None = None
    context: ToolExecutionContext | None = None

    @property
    def description(self) -> str:
        """说明复用注册表。"""
        return self.definition.description

    @property
    def schema(self) -> dict[str, Any]:
        """参数使用平台字段，源字段只用于显式兼容输入。"""
        return deepcopy(dict(self.definition.parameters_schema))

    @property
    def callback(self) -> DispatchCallback | None:
        """路由由注册表名称和 transport 决定，模型不得选择执行通道。"""
        if self.definition.name == "bash":
            return self.bridge.runner
        if self.definition.name == "ask_user_question":
            return self.bridge.interaction
        if self.definition.name == "task.create" or self.definition.requires_confirmation or self.definition.permission_policy.confirmation_required:
            return self.bridge.business
        if self.definition.transport == "mcp":
            return self.bridge.mcp
        return None

    @property
    def available(self) -> bool:
        """禁止把待接线的特殊工具退回普通 handler。"""
        if self.definition.name == "bash" and not self.bridge.runner_instance_id:
            return False
        special = (
            self.definition.name in {"bash", "ask_user_question", "task.create"}
            or self.definition.requires_confirmation
            or self.definition.permission_policy.confirmation_required
            or self.definition.transport == "mcp"
        )
        return (not special or self.callback is not None) and self.definition.execution_mode == "short"

    @property
    def metadata(self) -> dict[str, Any]:
        """平台风险映射到源调度元数据，交互不会与其他调用并发。

        ``dsh_requires_approval`` 为无参粗判（bash 按空命令=normal 计）；
        真正逐调用裁决在 ``approval_decision(args)``（scheduler 带 args 调用）。
        """
        policy = self.definition.permission_policy
        parallel = self.definition.name in _PARALLEL and policy.workspace != "write" and not self.definition.requires_prior_result and not self.definition.requires_confirmation
        access = "read" if parallel else "execute" if self.definition.name == "bash" else "write"
        # 问答和业务确认由各自回调等待，不叠加普通工具审批卡。
        interaction = self.definition.name in {"ask_user_question", "task.create"} or policy.confirmation_required or self.definition.requires_confirmation
        requires = (not parallel) and (not interaction) and self.approval_decision({}) != "auto"
        return {"dsh_execution_mode": "parallel" if parallel else "exclusive",
                "dsh_access": access, "dsh_requires_approval": requires}

    def approval_decision(self, args: Mapping[str, Any]) -> str:
        """按会话档位 + 工具 + 命令风险返回 ``auto``/``approval``/``deny``。"""
        from app.harness.security import permission_tier as tier_policy

        tier = self.context.permission_tier if self.context is not None else ""
        return tier_policy.decide(self.definition.name, dict(args or {}), tier)

    @property
    def approval_scope(self) -> str:
        """工作区/用户/档位/权限等级变化会使 always 授权失效。"""
        ctx = self.context
        if not ctx:
            return ""
        return json.dumps([ctx.user_id, ctx.sandbox_dir, ctx.sandbox_mode, ctx.permission_tier], ensure_ascii=False)

    def bind_call(self, identity: dict[str, Any]) -> PlatformLoopTool:
        """每个 call 独立上下文，避免并行共享 call_id。"""
        ctx = self.bridge.context_factory(dict(identity))
        if ctx.session_id != identity["session_id"] or not ctx.user_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "工具上下文身份不匹配")
        return replace(self, identity=dict(identity), context=replace(ctx, call_id=identity["call_id"]))

    def normalize_arguments(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """拒绝冲突别名；源行号仅在显式旧契约下转换一次。"""
        normalized = deepcopy(dict(args))
        for old, new in _ALIASES.get(self.definition.name, ()):
            if old in normalized:
                if new in normalized and normalized[old] != normalized[new]:
                    raise AppError(ErrorCode.VALIDATION, f"字段 {old}/{new} 冲突")
                normalized[new] = normalized.pop(old)
        if self.definition.name == "read" and self.bridge.source_contract == "deepseek-harness.v1" and "offset" in normalized:
            offset = normalized["offset"]
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 1:
                raise AppError(ErrorCode.VALIDATION, "源 offset 必须是从 1 开始的整数")
            normalized["offset"] = offset - 1
        enforce_tool_argument_policy(self.definition.name, normalized)
        error = validate_tool_arguments(self.schema, normalized)
        if error:
            raise AppError(ErrorCode.VALIDATION, error)
        return normalized

    def argument_error(self, args: dict[str, Any]) -> str | None:
        """共享同一套转换与 Schema 校验，不修改原始调用。"""
        try:
            self.normalize_arguments(args)
        except AppError as exc:
            return exc.message
        return None

    def check_permission(self, args: dict[str, Any]) -> None:
        """审批前后复验权限；关闭能力和上下文变更均拒绝派发。"""
        if not self.available or self.context is None or self.identity is None:
            raise AppError(ErrorCode.VALIDATION, "工具执行接口尚未接线")
        current = self.bridge.context_factory(dict(self.identity))
        if (current.session_id, current.user_id, current.sandbox_dir, current.sandbox_mode,
                current.permission_tier) != (
            self.context.session_id, self.context.user_id, self.context.sandbox_dir,
            self.context.sandbox_mode, self.context.permission_tier
        ):
            raise AppError(ErrorCode.UNAUTHORIZED, "工具授权上下文已变化")
        if self.definition.permission_policy.workspace != "none" and not self.context.sandbox_dir:
            raise AppError(ErrorCode.VALIDATION, "缺少可信工作区")
        # 三档权限：灾难级 bash 命令直接拒绝（不进审批；三档一致）。
        if self.definition.name == "bash" and self.approval_decision(args) == "deny":
            raise AppError(ErrorCode.DENIED, "命令命中灾难级操作，已拒绝执行")
        if self.bridge.authorize(self.definition, self.normalize_arguments(args), self.context) is not None:
            raise AppError(ErrorCode.UNAUTHORIZED, "权限接口必须显式校验并返回 None")

    def dispatch_data(self, args: dict[str, Any]) -> dict[str, Any]:
        """追加事实时交由 Store 原子建 guard；本层不能先建后单独提交。"""
        assert self.context is not None and self.identity is not None
        identity = self.identity
        execution_id = str(uuid5(NAMESPACE_URL, json.dumps(
            [identity["session_id"], identity["turn"], identity["attempt_id"], identity["call_id"]]
        )))
        data = {"execution_id": execution_id, "registry_name": self.definition.name,
                "session_id": identity["session_id"], "turn_id": f"{identity['session_id']}:{identity['turn']}",
                "wire_name": self.name, "tool_contract_version": self.bridge.source_contract,
                "normalized_args": self.normalize_arguments(args)}
        if self.definition.permission_policy.workspace != "none" or self.definition.name == "bash":
            scope = os.path.normcase(os.path.realpath(os.path.abspath(self.context.sandbox_dir)))
            data.update(scope_path=scope, canonical_scope=scope,
                        access="read" if self.definition.permission_policy.workspace == "read" else "write")
        if self.definition.name == "bash":
            from .loop_runner import RunnerRequest

            data.update(requested_timeout_ms=args.get("timeout"), effective_timeout_s=bash_timeout_seconds(args))
            request = RunnerRequest(
                execution_id=execution_id, session_id=identity["session_id"], turn_id=data["turn_id"],
                call_id=identity["call_id"], command=data["normalized_args"]["command"],
                workspace_root=data["scope_path"], mode=self.context.sandbox_mode,
                timeout_s=data["effective_timeout_s"],
            )
            data.update(runner_instance_id=self.bridge.runner_instance_id,
                        request_fingerprint=request.fingerprint, runner_request_payload=request.payload())
        return data

    async def ainvoke(self, args: dict[str, Any]) -> ToolExecutionResult:
        """只有 scheduler 提交 dispatch 后调用；同步工作在取消时 join 到终态。"""
        self.check_permission(args)
        assert self.context is not None and self.identity is not None
        normalized = self.normalize_arguments(args)
        if self.callback is not None:
            identity = {**self.identity, **self.dispatch_data(args)}
            if self.definition.name == "bash":
                from .loop_runner import RunnerRequest

                identity["runner_request"] = RunnerRequest(
                    execution_id=identity["execution_id"], session_id=identity["session_id"],
                    turn_id=identity["turn_id"], call_id=identity["call_id"],
                    command=normalized["command"], workspace_root=identity["scope_path"],
                    mode=self.context.sandbox_mode, timeout_s=identity["effective_timeout_s"],
                )
            try:
                output = await self.callback(self.definition, normalized, self.context, identity)
            except (ConnectionError, OSError, TimeoutError):
                if self.definition.name != "bash":
                    raise
                return ToolExecutionResult("无法证实远端执行结果", "outcome_unknown", "runner_outcome_unknown")
            except AppError as exc:
                if self.definition.name != "bash" or exc.code not in {ErrorCode.UPSTREAM, ErrorCode.TIMEOUT}:
                    raise
                return ToolExecutionResult("无法证实远端执行结果", "outcome_unknown", "runner_outcome_unknown")
            except Exception:
                if self.definition.name != "bash":
                    raise
                return ToolExecutionResult("无法证实远端执行结果", "outcome_unknown", "runner_outcome_unknown")
            # RunnerResult 的停止证据是释放 guard 的前提，不能把 running/未知映射为 failed。
            if self.definition.name == "bash" and not isinstance(output, ToolExecutionResult):
                if hasattr(output, "guard_releasable"):
                    metadata = {"execution_id": output.execution_id,
                                "runner_instance_id": output.runner_instance_id,
                                "termination_evidence": output.termination_evidence,
                                "process_tree_terminated": output.process_tree_terminated,
                                "execution_started": output.execution_started,
                                "request_fingerprint": output.request_fingerprint,
                                "cgroup_path": getattr(output, "cgroup_path", None)}
                    tombstone = (output.status == "not_started" and output.execution_started is False
                                 and output.termination_evidence == "not_started" and output.request_fingerprint is None)
                    if (output.execution_id != identity["execution_id"] or not output.guard_releasable
                        or output.runner_instance_id != identity["runner_instance_id"]
                        or not tombstone and output.request_fingerprint != identity["request_fingerprint"]):
                        return ToolExecutionResult("无法证实远端执行已停止", "outcome_unknown", "runner_outcome_unknown", metadata=metadata)
                    return ToolExecutionResult(
                        output.output or output.message, output.status, output.error_code, output.exit_code,
                        metadata=metadata,
                    )
                # 未声明停止证据的未知返回类型不具备释放 guard 的资格。
                return ToolExecutionResult("Runner 返回值缺少停止证据", "outcome_unknown", "runner_outcome_unknown")
            return normalize_tool_output(output)
        work = asyncio.create_task(asyncio.to_thread(
            execute_raw, ToolCall(self.definition.name, normalized, self.context.call_id),
            timeout_s=self.definition.timeout_s, permission=self.definition.permission,
            sandbox_dir=self.context.sandbox_dir, handler=self.definition.handler,
            context=self.context if self.definition.contextual else None,
            recovery_policy=self.definition.recovery_policy, output_schema=self.definition.output_schema,
        ))
        try:
            output = await asyncio.shield(work)
        except asyncio.CancelledError:
            output = await _join(work)
        return normalize_tool_output(output)
