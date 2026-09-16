import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal
from .errors import register_error_handlers
from .harness.execution.registry import build_default_registry
from .harness.orchestration.agents import (
    get_default_agent_registry,
    validate_agent_registry_integrity,
)
from .harness.skills.registry import SKILL_CATALOG
from .harness.skills.storage import ensure_skill_files
from .models import ProtocolProfile, User
from .routers import (
    admin,
    agent_prefs,
    agents,
    auth,
    cases,
    collaborations,
    dataset_catalog,
    datasets,
    dispatch,
    files,
    kb,
    mcp,
    profiles,
    reports,
    sessions,
    tasks,
    user_workspaces,
    users,
    ws,
    ws_v2,
)
from .security import hash_password
from .seed import bootstrap_preview_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-eval")

APP_VERSION = "0.1.0"


def _bootstrap_admin() -> None:
    """创建首个同权成员，并将早期骨架角色归一为 member。"""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.bootstrap_admin_username).first()
        if not existing:
            db.add(
                User(
                    username=settings.bootstrap_admin_username,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    display_name=settings.bootstrap_admin_username,
                    role="member",
                    # V1.83 起机制废除：引导成员同样不再强制首次改密。
                    must_change_password=False,
                )
            )
            db.commit()
            logger.info("已创建引导成员 %s", settings.bootstrap_admin_username)
        elif existing.role != "member":
            existing.role = "member"
            db.commit()
    finally:
        db.close()


def _bootstrap_preview() -> None:
    """全新部署时播种预览数据；播种失败仅记录日志，不阻塞服务启动。"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == settings.bootstrap_admin_username).first()
        if admin:
            bootstrap_preview_data(db, admin)
    except Exception:
        db.rollback()
        logger.exception("预览种子数据播种失败（不影响服务运行）")
    finally:
        db.close()


def _validate_agent_registry() -> None:
    """H0：Agent Registry 启动期一致性校验（strict 下缺项即阻止启动）。

    校验 ``allowed_tools ⊆ ToolRegistry``、``skill_ids ⊆ SKILL_CATALOG`` 与
    ``model_profile_id``（非空时）的协议档存在性。数据库暂不可用（首启迁移
    前）时仅跳过协议档维度，静态引用校验始终执行。
    """
    db_profile_ids: frozenset[str] | None = frozenset()
    try:
        db = SessionLocal()
        try:
            db_profile_ids = frozenset(
                str(row[0]) for row in db.query(ProtocolProfile.id).all()
            )
        finally:
            db.close()
    except Exception:
        db_profile_ids = None
        logger.warning("Agent Registry 协议档校验跳过：数据库暂不可用")
    validate_agent_registry_integrity(
        get_default_agent_registry(),
        tool_names=frozenset(build_default_registry().names()),
        skill_ids=frozenset(SKILL_CATALOG),
        db_profile_ids=db_profile_ids,
        strict=settings.agent_registry_strict,
    )


def _validate_hitl_checkpointer() -> None:
    """H5 批次 2：HITL 持久化启动门禁。

    混合引擎开启（``hybrid_engine_enabled=true``）时，Agent 分支的危险 bash 会
    触发图内 ``interrupt()`` 审批；审批回执需以原 ``thread_id`` 经
    ``Command(resume=...)`` 恢复检查点。``memory`` 检查点为进程内单例，api 重启
    或多副本轮询即丢失待恢复线程，用户点「批准」时找不到中断点（审计矛盾
    C-7 / ADR-7）。

    - ``agent_hitl_strict_pg=true``（生产部署）：混合引擎 + memory 检查点 →
      抛 ``AppError(VALIDATION)`` 阻止启动（fail-fast）；
    - ``agent_hitl_strict_pg=false``（默认，单副本/测试）：仅 ``logger.warning``
      告警，便于用 ``memory`` 验证 interrupt 语义；正式发布 HITL 前必须切
      ``AGENT_CHECKPOINTER=postgres`` 并完成重启恢复演练（开发计划 §3 H5）。
    """
    if not settings.hybrid_engine_enabled:
        return
    mode = str(settings.agent_checkpointer or "memory").strip().lower()
    if mode == "postgres":
        return
    msg = (
        "混合引擎已开启但检查点为 memory：HITL 审批 resume 无法跨进程重启恢复，"
        "正式发布前必须设 AGENT_CHECKPOINTER=postgres 并完成重启恢复演练"
    )
    if settings.agent_hitl_strict_pg:
        from .errors import AppError, ErrorCode

        raise AppError(ErrorCode.VALIDATION, msg)
    logger.warning(msg)


def _resolve_instance_id() -> str:
    """H5 批次 2：派生 API 实例标识（粘性路由用，暴露于 /api/health）。

    优先使用 ``AGENT_INSTANCE_ID`` 显式配置；为空时以 ``hostname:pid`` 派生，
    同一进程内稳定、跨重启变化——多副本部署时网关按 ``session_id`` 粘性路由
    到同一实例，保证会话级 abort dict 与 interrupt ``thread_id`` 可寻址。
    """
    explicit = (settings.agent_instance_id or "").strip()
    if explicit:
        return explicit
    import os
    import socket

    return f"{socket.gethostname()}:{os.getpid()}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 表结构由 Alembic 管理（启动前执行 alembic upgrade head），此处只做引导数据
    # 首次启动只补齐缺失的运行时技能文件，已有管理员修改绝不覆盖。
    ensure_skill_files()
    _bootstrap_admin()
    _bootstrap_preview()
    # H0：Agent Registry 静态引用校验在引导数据之后执行；strict 模式抛
    # AppError(VALIDATION) 阻止进程启动（fail-fast），见 AGENTS.md H0 硬门槛。
    _validate_agent_registry()
    # H5 批次 2：HITL 持久化门禁——混合引擎开启时检查点必须可跨进程恢复。
    _validate_hitl_checkpointer()
    from .routers.ws import approval_expiry_loop
    from .runtime import checkpoint_ttl_loop

    cleanup_task = asyncio.create_task(checkpoint_ttl_loop())
    # #3（V1.73）：审批卡 TTL 扫描（过期 tool_approval 卡清卡 + expired 终态）
    approval_expiry = asyncio.create_task(approval_expiry_loop())
    from .agent.loop_service import LoopService

    app.state.loop_service = LoopService()
    from .harness.execution.workspace_guard import configure as configure_workspace_guard

    configure_workspace_guard(SessionLocal)
    try:
        yield
    finally:
        try:
            await app.state.loop_service.close()
        finally:
            configure_workspace_guard(None)
            for task in (cleanup_task, approval_expiry):
                task.cancel()
            for task in (cleanup_task, approval_expiry):
                with suppress(asyncio.CancelledError):
                    await task


app = FastAPI(title="AI 测试与评估平台", version=APP_VERSION, lifespan=lifespan)

register_error_handlers(app)

# 开发环境跨域由环境变量白名单控制，生产通常由 nginx 同源反代。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(files.router)
app.include_router(sessions.router)
app.include_router(agent_prefs.router)
app.include_router(tasks.router)
app.include_router(profiles.router)
app.include_router(datasets.router)
app.include_router(datasets.folders_router)
app.include_router(dataset_catalog.router)
app.include_router(cases.router)
app.include_router(collaborations.router)
app.include_router(cases.folders_router)
app.include_router(admin.router)
app.include_router(user_workspaces.router)
app.include_router(dispatch.router)
app.include_router(kb.router)
app.include_router(mcp.router)
# H1：Agent Worker 只读目录（API.md §3.6.3，登录可见的脱敏投影）
app.include_router(agents.router)
app.include_router(reports.router)
app.include_router(ws.router)

app.include_router(ws_v2.router)


@app.get("/api/health")
def health():
    # H5 批次 2：暴露实例标识，供网关按 session_id 粘性路由健康检查识别副本。
    return {"status": "ok", "version": app.version, "instance_id": _resolve_instance_id()}
