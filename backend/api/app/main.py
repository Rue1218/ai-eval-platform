import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal
from .errors import register_error_handlers
from .models import User
from .routers import (
    admin,
    agent_prefs,
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
    slash_commands,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 表结构由 Alembic 管理（启动前执行 alembic upgrade head），此处只做引导数据
    _bootstrap_admin()
    _bootstrap_preview()
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
app.include_router(slash_commands.router)
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
app.include_router(reports.router)
app.include_router(ws.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}
