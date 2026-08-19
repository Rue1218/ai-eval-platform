"""Worker 数据库会话工厂。

从 ``main.py`` 抽出供执行器与事件助手共用，避免循环导入；
连接参数与 api 容器一致，由环境变量 ``DATABASE_URL`` 注入。
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://aieval:aieval_pass@localhost:5432/aieval"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
