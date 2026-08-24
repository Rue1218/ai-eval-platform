FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# 构建上下文为 backend/：api 与 worker 共享 backend/shared 模型包
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Harness 沙箱（bash 工具）：bwrap 进程级隔离（无网络/工作区唯一可写/资源受限）
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap \
    && rm -rf /var/lib/apt/lists/*

COPY shared ./shared
COPY api/app ./app
COPY api/alembic.ini .
COPY api/migrations ./migrations
COPY api/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
