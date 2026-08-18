#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 容器启动脚本：数据库迁移 -> 启动 uvicorn
# 兼容旧版数据库：早期骨架版用 create_all 建表，无 alembic_version 表；
# 它只等价于 0001，必须先标记 0001 再继续升级，不能直接跳到 head。
# ============================================================

# 数据库不可用或迁移锁冲突时必须有上限，交由 Docker restart 策略恢复，不能永久卡住部署。
DATABASE_CHECK_RETRIES=${DATABASE_CHECK_RETRIES:-12}
DATABASE_CHECK_INTERVAL_SECONDS=${DATABASE_CHECK_INTERVAL_SECONDS:-5}
DATABASE_CONNECT_TIMEOUT_SECONDS=${DATABASE_CONNECT_TIMEOUT_SECONDS:-5}
MIGRATION_TIMEOUT_SECONDS=${MIGRATION_TIMEOUT_SECONDS:-180}
MIGRATION_LOCK_TIMEOUT_MS=${MIGRATION_LOCK_TIMEOUT_MS:-15000}
MIGRATION_STATEMENT_TIMEOUT_MS=${MIGRATION_STATEMENT_TIMEOUT_MS:-120000}

echo "==> 检查数据库状态（最多重试 ${DATABASE_CHECK_RETRIES} 次）"
NEED_STAMP=""
for ((attempt = 1; attempt <= DATABASE_CHECK_RETRIES; attempt++)); do
    if NEED_STAMP=$(DATABASE_CONNECT_TIMEOUT_SECONDS="$DATABASE_CONNECT_TIMEOUT_SECONDS" python - <<'PY'
import os
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

connect_timeout = int(os.environ["DATABASE_CONNECT_TIMEOUT_SECONDS"])
try:
    # connect_timeout 限制网络建连；statement_timeout 防止元数据查询永久等待。
    engine = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={
            "connect_timeout": connect_timeout,
            "options": "-c statement_timeout=10000",
        },
    )
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        tables = set(inspect(connection).get_table_names())
except (SQLAlchemyError, ValueError):
    # 不输出异常详情，避免连接串中的敏感信息进入容器日志。
    print("数据库连接检查失败", file=sys.stderr)
    sys.exit(1)

# 旧版 create_all 数据库：有业务表但无迁移版本表。
print("1" if ("users" in tables and "alembic_version" not in tables) else "0")
PY
    ); then
        break
    fi

    if [ "$attempt" -eq "$DATABASE_CHECK_RETRIES" ]; then
        echo "错误：数据库在限定时间内不可用，容器将退出并由 restart 策略重试" >&2
        exit 1
    fi

    echo "==> 数据库暂不可用，${DATABASE_CHECK_INTERVAL_SECONDS} 秒后重试（${attempt}/${DATABASE_CHECK_RETRIES}）" >&2
    sleep "$DATABASE_CHECK_INTERVAL_SECONDS"
done


run_alembic() {
    # 在数据库锁与进程执行时长均受限的条件下执行一条 Alembic 命令。
    local phase="$1"
    shift
    local migration_pgoptions="${PGOPTIONS:-} -c lock_timeout=${MIGRATION_LOCK_TIMEOUT_MS} -c statement_timeout=${MIGRATION_STATEMENT_TIMEOUT_MS}"

    echo "==> ${phase}（最长 ${MIGRATION_TIMEOUT_SECONDS} 秒）"
    if ! PGOPTIONS="$migration_pgoptions" python - "$MIGRATION_TIMEOUT_SECONDS" "$@" <<'PY'
import subprocess
import sys

timeout_seconds = int(sys.argv[1])
command = ["alembic", *sys.argv[2:]]
try:
    subprocess.run(command, check=True, timeout=timeout_seconds)
except subprocess.TimeoutExpired:
    print(f"错误：Alembic 在 {timeout_seconds} 秒内未完成", file=sys.stderr)
    sys.exit(124)
except subprocess.CalledProcessError as exc:
    print(f"错误：Alembic 执行失败，退出码 {exc.returncode}", file=sys.stderr)
    sys.exit(exc.returncode or 1)
PY
    then
        echo "错误：${phase}失败，容器将退出并由 restart 策略重试" >&2
        exit 1
    fi
}

if [ "$NEED_STAMP" = "1" ]; then
    run_alembic "检测到旧版数据库（无迁移标记），stamp 0001 基线" stamp 0001
fi

run_alembic "执行数据库迁移" upgrade head

echo "==> 启动应用"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
