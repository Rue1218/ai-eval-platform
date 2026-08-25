FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 沙箱内核需要 bwrap（userns/mount/pivot_root）；runner 是唯一持有
# privileged + seccomp:unconfined 的容器（api 不再需要）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap \
    && rm -rf /var/lib/apt/lists/*

# 构建上下文为 backend/：共享 bwrap 内核 backend/shared/sandbox_kernel.py
COPY shared ./shared
COPY runner ./runner

EXPOSE 8001

CMD ["python", "-m", "runner.main"]
