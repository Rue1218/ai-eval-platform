FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# 构建上下文为 backend/：api 与 worker 共享 backend/shared 模型包
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY worker/app ./app

CMD ["python", "-m", "app.main"]
