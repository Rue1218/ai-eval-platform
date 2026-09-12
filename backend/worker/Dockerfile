FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# 构建上下文为 backend/：api 与 worker 共享 backend/shared 模型包
COPY worker/requirements.txt .
# 下载缓存留在构建器中，依赖更新时复用，不增加运行镜像体积。
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY shared ./shared
COPY worker/app ./app

CMD ["python", "-m", "app.main"]
