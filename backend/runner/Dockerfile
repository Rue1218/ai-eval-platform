FROM python:3.12-slim

# 服务器本地构建可传 APT_MIRROR（如 mirrors.ustc.edu.cn）替换 Debian 官方源：
# deb.debian.org 从国内低配机实测 17.6kB/s，apt 层冷缓存时单次安装可达 9min+。
# CI（GitHub runner）不传该参数，保持官方源不动。
ARG APT_MIRROR=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 沙箱内核改为「容器内直跑」：需要 util-linux 的 unshare 建 netns/pidns
# （runner 是唯一持有 SYS_ADMIN/NET_ADMIN + seccomp:unconfined 的容器）。
# trixie 的源集中在 /etc/apt/sources.list.d/debian.sources（main 与 security
# 均为 deb.debian.org host），替换 host 即可同时覆盖；兼容旧版 sources.list。
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" \
            /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

# 构建上下文为 backend/：共享沙箱内核 backend/shared/sandbox_kernel.py
COPY shared ./shared
COPY runner ./runner

EXPOSE 8001

CMD ["python", "-m", "runner.main"]
