-- pgvector 扩展启用脚本
-- 仅在数据卷首次初始化时由 docker-entrypoint-initdb.d 自动执行；
-- 已有 pgdata 卷的环境需一次性手动执行：
--   docker compose exec postgres psql -U aieval -d aieval -c "CREATE EXTENSION IF NOT EXISTS vector;"
CREATE EXTENSION IF NOT EXISTS vector;
