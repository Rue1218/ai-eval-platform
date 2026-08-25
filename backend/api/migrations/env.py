import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 确保 api/ 在 sys.path，可导入 app 包（alembic 从 api/ 目录运行）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app import models  # noqa: E402,F401  导入以注册全部模型到 Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 连接串统一来自应用配置（环境变量 DATABASE_URL），保证与 api 进程一致
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def _include_object(object_: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    """按环境变量收窄 autogenerate 表范围，避免临时库缺少可选扩展时产生噪声。

    常规迁移不设置 ``ALEMBIC_AUTOGEN_TABLES``，行为与此前完全一致。仅在隔离
    数据库缺少 pgvector 等可选扩展时，才允许例如 ``protocol_profiles`` 的单表
    比对；该开关只影响生成命令，不影响 ``upgrade`` 或生产运行时。
    """
    selected = {
        item.strip()
        for item in os.getenv("ALEMBIC_AUTOGEN_TABLES", "").split(",")
        if item.strip()
    }
    if not selected:
        return True
    if type_ == "table":
        return name in selected
    table = getattr(object_, "table", None)
    return table is None or getattr(table, "name", None) in selected


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 而不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
