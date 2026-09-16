"""P1 前台专家协调器：持久创建、并行运行、查询、等待与取消。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.errors import AppError, ErrorCode
from app.harness.execution.loop_tools import ToolExecutionResult
from app.harness.security import permission_tier as tier_policy
from app.models import (
    AgentCollaboration,
    AgentCommandReceipt,
    AgentInstance,
    AgentRun,
    ProtocolProfile,
    Session,
    Setting,
    utcnow,
)
from app.workspace_service import resolve_session_sandbox

from .experts import get_expert, list_experts
from .runtime import AgentRuntime
from .subagent_log import SubagentLog

TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def _fingerprint(command: str, arguments: dict[str, Any]) -> str:
    """对模型可控参数做规范摘要，防同一 call_id 携带不同请求重放。"""
    payload = json.dumps(
        {"command": command, "arguments": arguments},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CollaborationCoordinator:
    """绑定一个主回合的子运行；子任务生命周期由 ``TurnChildren`` 统一收拢。"""

    def __init__(
        self,
        service,
        entry,
        actor_id: str,
        root_data: dict[str, Any],
        children,
        budget,
    ) -> None:
        """只保存服务端注入身份与安全快照，不接受模型指定会话或调用者。"""
        self.service = service
        self.entry = entry
        self.actor_id = actor_id
        self.root_data = root_data
        self.children = children
        self.budget = budget
        self.collaboration_id: str | None = None
        self.root_turn: int | None = None
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self._closed = False

    async def close(self) -> None:
        """主回合 drain 后冻结新派发并保存最后汇总调用；按当前回合资源归属调用。"""
        self._closed = True
        self.budget.close()
        self._persist_budget()

    async def dispatch(self, definition, arguments, _context, identity) -> ToolExecutionResult:
        """按注册表名称分派六个短工具，返回可直接进入模型历史的 JSON。"""
        handlers = {
            "agent.list": self._list,
            "agent.spawn": self._spawn,
            "agent.status": self._status,
            "agent.wait": self._wait,
            "agent.result": self._result,
            "agent.cancel": self._cancel,
        }
        handler = handlers.get(definition.name)
        if handler is None:
            raise AppError(ErrorCode.VALIDATION, "未知专家调度命令")
        payload = await handler(arguments, identity)
        self._persist_budget()
        return ToolExecutionResult(json.dumps(payload, ensure_ascii=False), "succeeded")

    async def _list(self, arguments: dict[str, Any], _identity: dict[str, Any]) -> dict[str, Any]:
        """返回角色能力摘要；提示词正文和协议凭据不出服务端。"""
        capability = str(arguments.get("capability", "")).strip().lower()
        experts = list_experts()
        if capability:
            experts = [
                item for item in experts
                if capability in (item["name"] + " " + item["description"] + " " + item["badge"]).lower()
            ]
        return {"experts": experts, "count": len(experts), "max_instances": 8}

    def _ensure_collaboration(self, identity: dict[str, Any]) -> AgentCollaboration:
        """按会话+根回合幂等取得协作；目标仅保存主输入的安全展示文本。"""
        turn = identity.get("turn")
        if type(turn) is not int or turn < 1:
            raise AppError(ErrorCode.VALIDATION, "专家调度缺少主回合身份")
        if self.collaboration_id is not None:
            with self.service.session_factory() as db:
                row = db.get(AgentCollaboration, self.collaboration_id)
                if row is None:
                    raise AppError(ErrorCode.NOT_FOUND, "专家协作不存在")
                return row
        with self.service.session_factory() as db:
            row = db.execute(
                select(AgentCollaboration).where(
                    AgentCollaboration.session_id == self.entry.log.session_id,
                    AgentCollaboration.root_turn == turn,
                )
            ).scalar_one_or_none()
            if row is None:
                row = AgentCollaboration(
                    session_id=self.entry.log.session_id,
                    owner_id=self.actor_id,
                    root_turn=turn,
                    goal=str(self.root_data.get("content", ""))[:60000],
                    budget={
                        "mode": "hard_calls",
                        "max_calls": settings.agent_collaboration_max_calls,
                        "max_concurrent": settings.agent_subagent_max_concurrent,
                        "max_calls_per_run": settings.agent_subagent_max_calls_per_run,
                        **self.budget.snapshot(),
                    },
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            self.collaboration_id = row.id
            self.root_turn = turn
            return row

    def _receipt(self, db, collaboration_id: str, identity: dict[str, Any], command: str,
                 arguments: dict[str, Any]) -> dict[str, Any] | None:
        """读取变更工具回执；不同参数复用调用身份时明确冲突。"""
        caller = str(identity.get("run_id") or f"root:{self.entry.log.session_id}:{identity['turn']}")
        call_id = str(identity.get("call_id", ""))
        fingerprint = _fingerprint(command, arguments)
        previous = db.execute(
            select(AgentCommandReceipt).where(
                AgentCommandReceipt.caller_run_id == caller,
                AgentCommandReceipt.call_id == call_id,
            )
        ).scalar_one_or_none()
        if previous is None:
            return None
        if previous.fingerprint != fingerprint or previous.command != command:
            raise AppError(ErrorCode.CONCURRENCY, "同一专家调度调用对应不同参数")
        if previous.collaboration_id != collaboration_id:
            raise AppError(ErrorCode.CONCURRENCY, "专家调度回执不属于当前协作")
        return dict(previous.result)

    def _write_receipt(self, db, collaboration_id: str, identity: dict[str, Any],
                       command: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """与状态变更同事务写入幂等回执。"""
        caller = str(identity.get("run_id") or f"root:{self.entry.log.session_id}:{identity['turn']}")
        db.add(AgentCommandReceipt(
            collaboration_id=collaboration_id,
            caller_run_id=caller,
            call_id=str(identity["call_id"]),
            command=command,
            fingerprint=_fingerprint(command, arguments),
            result=result,
        ))

    async def _spawn(self, arguments: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        """原子创建实例与首次运行，再交给主回合子任务域并行执行。"""
        collaboration = self._ensure_collaboration(identity)
        expert = get_expert(arguments["expert_id"])
        profile_id = arguments.get("profile_id") or self.root_data.get("profile_id")
        with self.service.session_factory() as db:
            # 与整组停止锁定同一行，避免取消锁存与新实例创建交错。
            collaboration = db.execute(select(AgentCollaboration).where(
                AgentCollaboration.id == collaboration.id,
            ).with_for_update()).scalar_one()
            previous = self._receipt(db, collaboration.id, identity, "agent.spawn", arguments)
            if previous is not None:
                return previous
            if self._closed or collaboration.cancel_requested:
                raise AppError(ErrorCode.CONCURRENCY, "专家协作已停止，不能启动新专家")
            count = db.query(AgentInstance).filter(
                AgentInstance.collaboration_id == collaboration.id
            ).count()
            if count >= 8:
                raise AppError(ErrorCode.BUDGET_EXCEEDED, "协作专家实例额度已用尽")
            if not profile_id:
                default_profile = db.get(Setting, "agent_profile_id")
                profile_id = (
                    default_profile.value.strip()
                    if default_profile is not None and isinstance(default_profile.value, str)
                    else ""
                )
            profile = db.get(ProtocolProfile, profile_id) if profile_id else None
            if profile is None or "agent" not in (profile.usages or []):
                raise AppError(ErrorCode.VALIDATION, "专家运行协议档不可用")
            session = db.get(Session, self.entry.log.session_id)
            if session is None:
                raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
            from .loop_wiring import SUBAGENT_TOOLS, _expert_tools

            default_tier = db.get(Setting, "permission_tier_default")
            permission_tier = tier_policy.normalize(
                session.permission_tier
                or (default_tier.value if default_tier is not None and isinstance(default_tier.value, str) else None)
            )
            child_tools = [
                name for name in _expert_tools(expert)
                if name in SUBAGENT_TOOLS and tier_policy.decide(name, {}, permission_tier) == "auto"
            ]
            instance = AgentInstance(
                collaboration_id=collaboration.id,
                expert_id=expert.expert_id,
                expert_snapshot={
                    "id": expert.expert_id,
                    "name": expert.name,
                    "description": expert.description,
                    "badge": expert.badge,
                },
                profile_snapshot={
                    "id": profile.id,
                    "protocol": profile.protocol,
                    "model": profile.model,
                    "version": profile.updated_at.isoformat() if profile.updated_at else "",
                },
                permission_snapshot={
                    "tier": permission_tier,
                    "tools": child_tools,
                    "workspace": "isolated_child",
                },
                depth=1,
            )
            db.add(instance)
            db.flush()
            run = AgentRun(
                collaboration_id=collaboration.id,
                instance_id=instance.id,
                goal=arguments["goal"],
                output_contract=arguments["output_contract"],
            )
            db.add(run)
            db.flush()
            result = {
                "collaboration_id": collaboration.id,
                "instance_id": instance.id,
                "run_id": run.id,
                "status": "queued",
            }
            self._write_receipt(db, collaboration.id, identity, "agent.spawn", arguments, result)
            # 同一主回合可分批调度，创建新运行时原子刷新当前成果汇总状态。
            collaboration.status = "running"
            collaboration.finished_at = None
            db.commit()
        try:
            task = self.children.start(
                lambda: self._run_child(
                    run.id,
                    expert.expert_id,
                    str(profile_id),
                    arguments["goal"],
                    arguments["output_contract"],
                )
            )
        except RuntimeError as exc:
            self._mark_failed(run.id, "child_limit")
            raise AppError(ErrorCode.BUDGET_EXCEEDED, "协作专家实例额度已用尽") from exc
        self.tasks[run.id] = task
        task.add_done_callback(lambda completed: self._settle_child(run.id, completed))
        return result

    def _settle_child(self, run_id: str, task: asyncio.Task[Any]) -> None:
        """协程首次执行前就被取消时也须落终态；正常完成由幂等写入保留成果。"""
        cancelled = task.cancelled()
        reason = "cancelled" if cancelled else ErrorCode.INTERNAL.value
        self._finish_run(
            run_id, "cancelled" if cancelled else "failed",
            {"content": "", "finish_reason": reason, "complete": False}, error_code=reason,
        )
        self._refresh_collaboration()

    async def _run_child(
        self,
        run_id: str,
        expert_id: str,
        profile_id: str,
        goal: str,
        output_contract: str,
    ) -> None:
        """使用独立事实日志和沙箱目录运行真实 AgentLoop，并持久化可信终态。"""
        from .loop import build_agent
        from .loop_wiring import build_dependencies

        runtime: AgentRuntime | None = None
        resources: list[Any] = []
        final_status = "failed"
        final_result: dict[str, Any] = {
            "content": "", "finish_reason": "error", "complete": False,
        }
        final_error: str | None = ErrorCode.INTERNAL.value
        propagate_cancel = False
        try:
            log = SubagentLog(self.entry.log.session_id, run_id, self.service.session_factory,
                              actor_id=self.actor_id)
            runtime = AgentRuntime(log, await build_agent(self.service._settings()),
                                   approval_broker=self.service._broker, actor_id=self.actor_id)
            workspace = self._child_workspace(run_id)
            with self.service.session_factory() as db:
                run = db.get(AgentRun, run_id)
                if run is None:
                    return
                run.status = "running"
                run.started_at = utcnow()
                db.commit()
            child_entry = SimpleNamespace(log=log)
            child_prompt = f"{goal}\n\n【交付要求】\n{output_contract}"
            dependencies, resources = await build_dependencies(
                self.service,
                child_entry,
                self.actor_id,
                {
                    "content": child_prompt,
                    "_model_content": child_prompt,
                    "agent_id": expert_id,
                    "profile_id": profile_id,
                    "_subagent": True,
                    "_subagent_workspace": workspace,
                    "_model_budget": self.budget,
                    "_budget_run_id": run_id,
                },
            )
            await runtime.submit(child_prompt, dependencies=dependencies, actor_id=self.actor_id)
            await runtime.wait()
            events = log.read()
            reason = next(
                (event["data"].get("reason") for event in reversed(events)
                 if event.get("type") == "turn/end"),
                "error",
            )
            text = next(
                (event["data"].get("content") or event["data"].get("message", {}).get("content", "")
                 for event in reversed(events) if event.get("type") == "assistant/message"),
                "",
            )
            status = "succeeded" if reason == "completed" else "cancelled" if reason == "cancelled" else "failed"
            final_status = status
            final_result = {
                "content": text,
                "finish_reason": reason,
                "complete": status == "succeeded",
            }
            final_error = None if status == "succeeded" else str(reason)
        except asyncio.CancelledError:
            final_status = "cancelled"
            final_result = {
                "content": "", "finish_reason": "cancelled", "complete": False,
            }
            final_error = "cancelled"
            propagate_cancel = True
        except AppError as exc:
            final_error = exc.code.value
        except Exception:
            final_error = ErrorCode.INTERNAL.value
        finally:
            async def cleanup() -> None:
                """运行时关闭失败也继续释放依赖；清理独立于父任务的重复取消。"""
                try:
                    if runtime is not None:
                        await runtime.close()
                finally:
                    await self.service._close_resources(resources)

            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    propagate_cancel = True
                except Exception:
                    break
            try:
                cleanup_task.result()
            except Exception:
                final_status = "failed"
                final_error = ErrorCode.INTERNAL.value
                final_result = {"content": "", "finish_reason": "error", "complete": False}
            if propagate_cancel:
                final_status = "cancelled"
                final_error = "cancelled"
                final_result = {**final_result, "finish_reason": "cancelled", "complete": False}
            # 只有资源已经关闭、运行协程即将退出时才发布终态；否则 agent.wait
            # 可能先返回，主回合收尾再次 cancel 正在清理的子任务。
            self._finish_run(run_id, final_status, final_result, error_code=final_error)
            self._refresh_collaboration()
        if propagate_cancel:
            raise asyncio.CancelledError

    def _child_workspace(self, run_id: str) -> str:
        """每个实例只获得会话根下的独立子目录，避免并行写入互相覆盖。"""
        with self.service.session_factory() as db:
            session = db.get(Session, self.entry.log.session_id)
            if session is None:
                raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
            root = resolve_session_sandbox(session.id, session.workspace_id, session.scope_path)
        root_path = Path(root).resolve()
        base = root_path / ".subagents"
        base.mkdir(parents=True, exist_ok=True)
        if base.is_symlink() or not base.resolve().is_relative_to(root_path):
            raise AppError(ErrorCode.UNAUTHORIZED, "专家工作区边界无效")
        path = base / run_id
        path.mkdir(parents=False, exist_ok=True)
        if path.is_symlink() or path.resolve().parent != base.resolve():
            raise AppError(ErrorCode.UNAUTHORIZED, "专家工作区边界无效")
        return str(path.resolve())

    async def _status(self, arguments: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        """查询只允许当前根回合创建的运行。"""
        collaboration = self._ensure_collaboration(identity)
        return {"runs": self._run_rows(collaboration.id, arguments["run_ids"])}

    async def _wait(self, arguments: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        """短轮询等待 any/all 终态；sleep 释放事件循环且不占模型并发槽。"""
        collaboration = self._ensure_collaboration(identity)
        run_ids = arguments["run_ids"]
        mode = arguments.get("mode", "all")
        deadline = asyncio.get_running_loop().time() + int(arguments.get("timeout_seconds", 10))
        while True:
            rows = self._run_rows(collaboration.id, run_ids)
            terminal = [row["status"] in TERMINAL for row in rows]
            if (mode == "all" and all(terminal)) or (mode == "any" and any(terminal)):
                return {"completed": True, "mode": mode, "runs": rows}
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return {"completed": False, "mode": mode, "runs": rows}
            await asyncio.sleep(min(0.2, remaining))

    async def _result(self, arguments: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        """结果在终态后可用；失败与取消仍返回明确覆盖状态。"""
        collaboration = self._ensure_collaboration(identity)
        rows = self._run_rows(collaboration.id, [arguments["run_id"]], include_result=True)
        row = rows[0]
        return {**row, "available": row["status"] in TERMINAL}

    async def _cancel(self, arguments: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        """先持久化取消请求和回执，再触发进程内任务停止。"""
        collaboration = self._ensure_collaboration(identity)
        with self.service.session_factory() as db:
            previous = self._receipt(db, collaboration.id, identity, "agent.cancel", arguments)
            if previous is not None:
                return previous
            run = db.execute(select(AgentRun).where(
                AgentRun.id == arguments["run_id"],
                AgentRun.collaboration_id == collaboration.id,
            ).with_for_update()).scalar_one_or_none()
            if run is None:
                raise AppError(ErrorCode.NOT_FOUND, "专家运行不存在")
            accepted = run.status not in TERMINAL
            if accepted:
                run.cancel_requested = True
            result = {"run_id": run.id, "accepted": accepted, "status": run.status}
            self._write_receipt(db, collaboration.id, identity, "agent.cancel", arguments, result)
            db.commit()
        task = self.tasks.get(arguments["run_id"])
        if accepted and task is not None and not task.done() and not task.cancelling():
            task.cancel()
        return result

    def _run_rows(self, collaboration_id: str, run_ids: list[str], *,
                  include_result: bool = False) -> list[dict[str, Any]]:
        """保持输入顺序，任一越权或不存在的 ID 都整体拒绝。"""
        with self.service.session_factory() as db:
            rows = db.execute(select(AgentRun, AgentInstance).join(
                AgentInstance, AgentInstance.id == AgentRun.instance_id
            ).where(
                AgentRun.collaboration_id == collaboration_id,
                AgentRun.id.in_(run_ids),
            )).all()
            by_id = {run.id: (run, instance) for run, instance in rows}
            if any(run_id not in by_id for run_id in run_ids):
                raise AppError(ErrorCode.NOT_FOUND, "专家运行不存在")
            result = []
            for run_id in run_ids:
                run, instance = by_id[run_id]
                item = {
                    "run_id": run.id,
                    "instance_id": run.instance_id,
                    "expert": instance.expert_snapshot,
                    "model": instance.profile_snapshot.get("model"),
                    "goal": run.goal,
                    "output_contract": run.output_contract,
                    "status": run.status,
                    "result_available": run.status in TERMINAL,
                    "error_code": run.error_code,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                }
                if include_result:
                    item["result"] = run.result
                result.append(item)
            return result

    def _finish_run(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any],
        *,
        error_code: str | None = None,
    ) -> None:
        """终态只写一次；迟到完成不能覆盖已取消实例。"""
        with self.service.session_factory() as db:
            run = db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update()).scalar_one()
            if run.status in TERMINAL:
                return
            run.status = "cancelled" if run.cancel_requested else status
            run.result = (
                {**result, "finish_reason": "cancelled", "complete": False}
                if run.status == "cancelled" else result
            )
            run.error_code = "cancelled" if run.status == "cancelled" else error_code
            run.finished_at = utcnow()
            db.commit()

    def _mark_failed(self, run_id: str, error_code: str) -> None:
        """内部异常仅保存稳定错误码，不落上游原文或 traceback。"""
        with self.service.session_factory() as db:
            run = db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update()).scalar_one_or_none()
            if run is None or run.status in TERMINAL:
                return
            run.status = "cancelled" if run.cancel_requested else "failed"
            run.error_code = error_code
            run.finished_at = utcnow()
            db.commit()

    def _refresh_collaboration(self) -> None:
        """全部运行终止后汇总协作状态；存在活动运行时保持 running。"""
        if self.collaboration_id is None:
            return
        with self.service.session_factory() as db:
            collaboration = db.execute(select(AgentCollaboration).where(
                AgentCollaboration.id == self.collaboration_id
            ).with_for_update()).scalar_one_or_none()
            if collaboration is None:
                return
            statuses = list(db.execute(select(AgentRun.status).where(
                AgentRun.collaboration_id == collaboration.id
            )).scalars())
            if statuses and all(status in TERMINAL for status in statuses):
                if collaboration.cancel_requested or any(status == "cancelled" for status in statuses):
                    collaboration.status = "cancelled"
                elif any(status == "failed" for status in statuses):
                    collaboration.status = "failed"
                else:
                    collaboration.status = "succeeded"
                collaboration.finished_at = utcnow()
            elif statuses:
                collaboration.status = "running"
                collaboration.finished_at = None
            collaboration.budget = {**(collaboration.budget or {}), **self.budget.snapshot()}
            db.commit()

    def _persist_budget(self) -> None:
        """把精确调用计数投影到持久协作快照。"""
        if self.collaboration_id is None:
            return
        with self.service.session_factory() as db:
            collaboration = db.get(AgentCollaboration, self.collaboration_id)
            if collaboration is not None:
                collaboration.budget = {**(collaboration.budget or {}), **self.budget.snapshot()}
                db.commit()

    async def cancel_run_by_user(self, run_id: str, reason: str) -> dict[str, Any]:
        """前端停止指定专家；授权由路由按协作会话先行校验。"""
        if self.collaboration_id is None:
            raise AppError(ErrorCode.NOT_FOUND, "专家协作不存在")
        with self.service.session_factory() as db:
            run = db.execute(select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.collaboration_id == self.collaboration_id,
            ).with_for_update()).scalar_one_or_none()
            if run is None:
                raise AppError(ErrorCode.NOT_FOUND, "专家运行不存在")
            accepted = run.status not in TERMINAL
            if accepted:
                run.cancel_requested = True
            db.commit()
        task = self.tasks.get(run_id)
        if accepted and task is not None and not task.done() and not task.cancelling():
            task.cancel()
        return {"run_id": run_id, "accepted": accepted, "reason": reason[:500]}

    async def cancel_all_by_user(self, reason: str) -> dict[str, Any]:
        """持久化整组停止，再并行取消所有本地子任务。"""
        if self.collaboration_id is None:
            raise AppError(ErrorCode.NOT_FOUND, "专家协作不存在")
        with self.service.session_factory() as db:
            collaboration = db.execute(select(AgentCollaboration).where(
                AgentCollaboration.id == self.collaboration_id
            ).with_for_update()).scalar_one_or_none()
            if collaboration is None:
                raise AppError(ErrorCode.NOT_FOUND, "专家协作不存在")
            collaboration.cancel_requested = True
            runs = list(db.execute(select(AgentRun).where(
                AgentRun.collaboration_id == collaboration.id,
                AgentRun.status.in_(("queued", "running")),
            )).scalars())
            for run in runs:
                run.cancel_requested = True
            db.commit()
        for run in runs:
            task = self.tasks.get(run.id)
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()
        return {"collaboration_id": self.collaboration_id, "accepted": bool(runs),
                "run_ids": [run.id for run in runs], "reason": reason[:500]}
