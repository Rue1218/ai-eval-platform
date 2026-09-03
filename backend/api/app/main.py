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
    build_default_agent_registry,
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
    users,
    workspaces,
    ws,
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
                    must_change_password=True,
                )
            )
            db.commit()
            logger.info("已创建引导成员 %s（请登录后立即改密）", settings.bootstrap_admin_username)
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
        build_default_agent_registry(),
        tool_names=frozenset(build_default_registry().names()),
        skill_ids=frozenset(SKILL_CATALOG),
        db_profile_ids=db_profile_ids,
        strict=settings.agent_registry_strict,
    )


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
    from .runtime import checkpoint_ttl_loop

    cleanup_task = asyncio.create_task(checkpoint_ttl_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


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
app.include_router(cases.folders_router)
app.include_router(admin.router)
app.include_router(workspaces.router)
app.include_router(dispatch.router)
app.include_router(kb.router)
app.include_router(mcp.router)
# H1：Agent Worker 只读目录（API.md §3.6.3，登录可见的脱敏投影）
app.include_router(agents.router)
app.include_router(reports.router)
app.include_router(ws.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}
