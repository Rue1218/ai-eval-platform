FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# 构建上下文为 backend/：api 与 worker 共享 backend/shared 模型包
COPY api/requirements.txt .
# 下载缓存留在构建器中，依赖更新时复用，不增加运行镜像体积。
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# 沙箱 bwrap 已迁出：P4-2 起由独立 runner 容器执行，api 不再安装 bubblewrap、
# 不再需要 privileged/seccomp:unconfined/SYS_ADMIN（见 docker-compose.yml）。

# 构建版本：CI / deploy.sh 经 build-arg 注入，/api/health 据此暴露运行版本便于核查部署。
# 放在依赖安装层之后，避免版本变化破坏 pip 缓存。
ARG BUILD_VERSION=unknown
ARG BUILD_TIME=
ENV BUILD_VERSION=${BUILD_VERSION} \
    BUILD_TIME=${BUILD_TIME}

COPY shared ./shared
COPY api/app ./app
COPY api/alembic.ini .
COPY api/migrations ./migrations
COPY api/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
