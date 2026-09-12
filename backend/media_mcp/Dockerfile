FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY media_mcp/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY media_mcp/app ./app

EXPOSE 8002

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8002"]
