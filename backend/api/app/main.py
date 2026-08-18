import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal
from .errors import register_error_handlers
from .models import User
from .routers import admin, auth, datasets, profiles, tasks, ws
from .security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-eval")

APP_VERSION = "0.1.0"


def _bootstrap_admin() -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.bootstrap_admin_username).first()
        if not existing:
            db.add(
                User(
                    username=settings.bootstrap_admin_username,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role="admin",
                )
            )
            db.commit()
            logger.info("已创建引导管理员 %s（请登录后立即改密）", settings.bootstrap_admin_username)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 表结构由 Alembic 管理（启动前执行 alembic upgrade head），此处只做引导数据
    _bootstrap_admin()
    yield


app = FastAPI(title="AI 测试与评估平台", version=APP_VERSION, lifespan=lifespan)

register_error_handlers(app)

# 开发环境跨域（生产走 nginx 同源，无需 CORS）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(profiles.router)
app.include_router(datasets.router)
app.include_router(admin.router)
app.include_router(ws.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}
