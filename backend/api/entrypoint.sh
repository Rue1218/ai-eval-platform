#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 容器启动脚本：数据库迁移 -> 启动 uvicorn
# 兼容旧版数据库：早期骨架版用 create_all 建表，无 alembic_version 表；
# 此时表结构已与最新迁移一致，用 stamp head 建立基线，避免 DuplicateTable。
# ============================================================

echo "==> 检查数据库状态"
NEED_STAMP=$(python - <<'PY'
import os
from sqlalchemy import create_engine, inspect

engine = create_engine(os.environ["DATABASE_URL"])
insp = inspect(engine)
tables = set(insp.get_table_names())
# 旧版 create_all 数据库：有业务表但无迁移版本表
print("1" if ("users" in tables and "alembic_version" not in tables) else "0")
PY
)

if [ "$NEED_STAMP" = "1" ]; then
    echo "==> 检测到旧版数据库（无迁移标记），stamp head 建立基线"
    alembic stamp head
else
    echo "==> 执行数据库迁移"
    alembic upgrade head
fi

echo "==> 启动应用"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
