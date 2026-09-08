"""Agent 会话及历史回放 REST 接口。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..agent.attachments import normalize_history_attachments
from ..agent.log import agent_trace
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError, ErrorCode
from ..harness.context import compute_meter, is_window_eligible, recent_window
from ..harness.context.meter import DEFAULT_MAX_TOKENS, DEFAULT_MCP_TOOLS_MAX
from ..harness.memory import purge_session_checkpoints
from ..models import AuditLog, Message, ProtocolProfile, Setting, Task, User, Workspace, WsEvent
from ..models import Session as AgentSession
from ..schemas import SessionCreate, SessionOut, SessionSharingUpdate
from ..session_access import require_session_owner, require_visible_session
from ..session_connections import SESSION_CONNECTION_HUB
from ..workspace_service import ensure_workspace_scope

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
ACTIVE_STATUSES = {"queued", "running", "awaiting_case_confirm"}


def _agent_context_window(db: Session) -> int:
    """读当前 Agent 协议档的上下文窗口；未配置回退 200k。"""
    setting = db.query(Setting).filter(Setting.key == "agent_profile_id").first()
    profile_id = setting.value if setting else None
    if not isinstance(profile_id, str) or not profile_id:
        return DEFAULT_MAX_TOKENS
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if profile is None:
        return DEFAULT_MAX_TOKENS
    return int(getattr(profile, "context_window", 0) or DEFAULT_MAX_TOKENS)


def _skills_hint_text() -> str:
    """常驻 Skill Hint 正文（名称 + 一句话），供仪表估算技能段。"""
    from ..harness.skills import list_hints

    return "\n".join(f"{hint.name}：{hint.summary}" for hint in list_hints())


def _mcp_tools_count() -> int:
    """当前注册表工具数（原生 + 内部短 MCP）。"""
    from ..harness.execution.registry import build_default_registry

    return len(build_default_registry().names())


def build_session_context_meter(
    db: Session,
    session: AgentSession,
    messages: list[Message],
) -> dict:
    """按窗口算法计算 ``context_meter``（CX-7，前端只读）。"""
    eligible = [
        {
            "role": row.role,
            "content": row.content or "",
            "source_id": row.source_id or row.id,
        }
        for row in messages
        if is_window_eligible(row.role)
    ]
    windowed = recent_window(
        eligible,
        limit=20,
        keep_from=session.compact_keep_from,
    )
    compact_summary = session.compact_summary or ""
    return dict(
        compute_meter(
            windowed,
            max_tokens=_agent_context_window(db),
            compact_summary=compact_summary,
            skills_text=_skills_hint_text(),
            mcp_tools_count=_mcp_tools_count(),
            mcp_tools_max=DEFAULT_MCP_TOOLS_MAX,
            memory_files_count=1 if compact_summary.strip() else 0,
        )
    )


def _session_out(
    db: Session,
    row: AgentSession,
    user: User,
    workspace_names: dict[str, str] | None = None,
) -> dict:
    """补齐会话 owner、绑定工作区名、当前成员管理权和活动任务摘要。

    ``workspace_names`` 为列表预取结果（避免 N+1）；None 时按行单查（单对象
    场景如 create/sharing）。
    """
    task = (
        db.query(Task)
        .filter(Task.session_id == row.id, Task.status.in_(ACTIVE_STATUSES))
        .order_by(Task.created_at.desc())
        .first()
    )
    workspace_name = None
    if row.workspace_id:
        if workspace_names is not None:
            workspace_name = workspace_names.get(row.workspace_id)
        else:
            ws_row = (
                db.query(Workspace).filter(Workspace.id == row.workspace_id).first()
            )
            workspace_name = ws_row.name if ws_row else None
    value = SessionOut.model_validate(row).model_dump(mode="json")
    value["workspace_name"] = workspace_name
    value["can_manage"] = row.user_id == user.id
    value["can_delete"] = row.user_id == user.id
    value["active_task"] = (
        {"id": task.id, "kind": task.kind, "status": task.status} if task else None
    )
    return value


@router.get("")
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前成员创建的私有会话及全团队共享的未删除会话。"""
    rows = (
        db.query(AgentSession)
        .filter(
            AgentSession.deleted_at.is_(None),
            or_(AgentSession.user_id == user.id, AgentSession.visibility == "team"),
        )
        .order_by(AgentSession.updated_at.desc())
        .all()
    )
    # N+1 收窄（P3 轻修）：绑定工作区名称一次预取（活跃任务查询仍按行进行）
    bound_ids = {row.workspace_id for row in rows if row.workspace_id}
    ws_names: dict[str, str] = {}
    if bound_ids:
        ws_names = {
            ws.id: ws.name
            for ws in db.query(Workspace).filter(Workspace.id.in_(bound_ids)).all()
        }
    items = [_session_out(db, row, user, workspace_names=ws_names) for row in rows]
    return {"items": items, "total": len(items)}


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建尚未关联长任务的空 Agent 会话，默认仅创建者可见。

    F3/G5：可选携带 ``workspace_id``/``scope_path`` 绑定用户工作区——创建时
    固化、运行期不可变（设计 §5，无换绑端点，需换绑 = 删除重建）；绑定仅限
    private 会话（BLK-4：防 team 成员借绑定会话横向获得工作区写授权）；属主
    校验 fail-closed。未绑定 = legacy 临时工作区（与 F3 前行为一致）。
    """
    from ..config import settings

    if body.engine_version == "agent_loop_v2" and not settings.agent_loop_enabled:
        raise AppError(ErrorCode.VALIDATION, "Agent Loop v2 尚未开启")
    workspace_id = (body.workspace_id or "").strip() or None
    scope_path: str | None = None
    if workspace_id:
        if body.visibility != "private":
            raise AppError(ErrorCode.VALIDATION, "绑定工作区的会话必须为私有可见性")
        # 行锁与 purge 同锁序（workspace → sessions），防 purge×create 竞态
        # 触发 FK RESTRICT IntegrityError → 500（BLK-4/P1 修复）。
        workspace = (
            db.query(Workspace)
            .filter(Workspace.id == workspace_id)
            .with_for_update()
            .first()
        )
        if (
            workspace is None
            or workspace.owner_id != user.id
            or workspace.deleted_at is not None
        ):
            raise AppError(ErrorCode.VALIDATION, "工作区不存在或无权绑定")
        scope_path = (body.scope_path or "").strip("/") or None
    session = AgentSession(
        user_id=user.id,
        title=body.title.strip(),
        engine_version=body.engine_version,
        visibility=body.visibility,
        workspace_id=workspace_id,
        scope_path=scope_path,
    )
    db.add(session)
    db.flush()  # 行先落库（取 id 供审计；目录就绪在行后，失败回滚不产生孤儿行）
    if workspace_id:
        # 目录就绪：scope 防穿越校验 + 目标按需 mkdir；失败回滚行并清理目录
        # 残留（best-effort；scope 子目录 mkdir 失败残留为空目录链，小概率
        # 可被 owner 在「我的工作区」清理，不产生不可见孤儿——BLK-4）。
        try:
            ensure_workspace_scope(workspace.id, scope_path)
        except AppError:
            db.rollback()
            raise
        db.add(
            AuditLog(
                user_id=user.id,
                action="session_workspace_bind",
                target_type="session",
                target_id=session.id,
                detail={"workspace_id": workspace_id, "scope_path": scope_path},
            )
        )
    db.commit()
    db.refresh(session)
    return _session_out(db, session, user)


@router.put("/{session_id}/sharing", response_model=SessionOut)
async def update_session_sharing(
    session_id: str,
    body: SessionSharingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """由会话创建者在私有和全团队共享之间切换可见范围。"""
    session = require_session_owner(db, session_id, user.id, lock=True)
    # F3/G5（BLK-4）：绑定工作区的会话不可转团队共享（写授权不随 team 开放）
    if body.visibility == "team" and session.workspace_id:
        raise AppError(
            ErrorCode.VALIDATION, "绑定工作区的会话不可转为团队共享"
        )
    # 收回共享前：pending_confirm 作者是协作者时拒绝收回——避免协作者卡成孤儿
    # （会话被卡阻塞无法删除/续用，且协作者已不可确认——P4 修复）。
    if (
        body.visibility == "private"
        and session.visibility == "team"
        and session.pending_confirm_author_id is not None
        and str(session.pending_confirm_author_id) != str(user.id)
    ):
        raise AppError(
            ErrorCode.VALIDATION, "存在协作者待处理的确认卡，请先确认或取消后再收回共享"
        )
    session.visibility = body.visibility
    db.add(
        AuditLog(
            user_id=user.id,
            action="session_sharing_update",
            target_type="session",
            target_id=session.id,
            detail={"visibility": body.visibility},
        )
    )
    db.commit()
    db.refresh(session)
    # 从 team 收回到 private 时主动中断协作者连接，避免继续收到瞬态流。
    if session.visibility == "private":
        await SESSION_CONNECTION_HUB.close_non_owner(session.id, session.user_id)
    return _session_out(db, session, user)


@router.get("/{session_id}/messages")
def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """回放用户/助手文本与确认卡等 WebSocket 历史事件。"""
    session = require_visible_session(db, session_id, user.id)
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at, Message.id)
        .all()
    )
    events = (
        db.query(WsEvent)
        .filter(WsEvent.session_id == session_id)
        .order_by(WsEvent.event_id)
        .all()
    )
    author_ids = {row.author_id for row in messages if row.author_id}
    if session.pending_confirm_author_id:
        author_ids.add(session.pending_confirm_author_id)
    authors = (
        db.query(User).filter(User.id.in_(author_ids)).all() if author_ids else []
    )
    author_map = {
        row.id: {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
        }
        for row in authors
    }
    return {
        "messages": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "attachments": normalize_history_attachments(db, row.attachments),
                "author_id": row.author_id,
                "author": author_map.get(row.author_id),
                "client_message_id": row.client_message_id,
                # assistant 交付句回复耗时（毫秒），仅 assistant 非空；前端气泡展示「耗时 x 秒」。
                "latency_ms": row.latency_ms,
                "model_name": row.model_name,
                "profile_id": row.profile_id,
                "profile_name": row.profile_name,
                "provider": row.provider,
                "created_at": row.created_at,
            }
            for row in messages
        ],
        "events": [
            {
                "event_id": row.event_id,
                "event": row.event,
                "task_id": row.task_id,
                "payload": row.payload,
                "ts": row.ts,
            }
            for row in events
        ],
        "pending_confirm": session.pending_confirm,
        "pending_confirm_author_id": session.pending_confirm_author_id,
        "pending_confirm_author": author_map.get(session.pending_confirm_author_id),
        "compact_summary": session.compact_summary,
        "context_meter": build_session_context_meter(db, session, messages),
    }


@router.delete("/{session_id}", status_code=204, response_class=Response)
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """软删除空闲会话，不物理删除审计消息、事件、任务或报告。"""
    session = require_session_owner(db, session_id, user.id, lock=True)
    if session.pending_confirm:
        raise AppError(ErrorCode.VALIDATION, "存在待确认任务，请先确认或取消后再删除会话")
    active_task = (
        db.query(Task)
        .filter(Task.session_id == session.id, Task.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if active_task:
        raise AppError(ErrorCode.VALIDATION, "存在执行中的任务，请先取消或等待任务结束")

    # MAJ-4：软删前中止该会话在途 Agent 回合（尽力而为——取消分支负责唯一
    # completed 收尾；软删后断连 close_all 在 commit 后执行）。局部 import
    # 防 routers/ws → sessions 循环依赖。
    from . import ws as _ws_module

    _ws_module.stop_session_turns(session.id)

    session.deleted_at = datetime.now(UTC)
    db.add(
        AuditLog(
            user_id=user.id,
            action="session_delete",
            target_type="session",
            target_id=session.id,
            detail={"mode": "soft_delete"},
        )
    )
    db.commit()
    # 软删除后联动清该会话检查点（失败不影响 204，TTL 后台任务会兜底）。
    try:
        removed = purge_session_checkpoints(session.id)
        if removed:
            agent_trace(f"session checkpoint cleanup removed={removed}")
    except Exception as exc:
        agent_trace(f"session checkpoint cleanup failed type={type(exc).__name__}")
    # 删除完成后统一断开 owner 与协作者。
    await SESSION_CONNECTION_HUB.close_all(session.id)
    return Response(status_code=204)
