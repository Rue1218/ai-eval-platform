FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY requirements.txt .
# 下载缓存留在构建器中，依赖更新时复用，不增加运行镜像体积。
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY app.py .

EXPOSE 9621

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9621"]
