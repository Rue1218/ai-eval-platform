# 构建阶段 (采用 Node.js 22 LTS 基础镜像)
FROM node:22-alpine AS build
WORKDIR /app

# 按锁文件安装；下载缓存留在 BuildKit 中，依赖变化时复用已有包，不打进镜像层。
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --registry=https://registry.npmmirror.com --prefer-offline --no-audit --no-fund

# 内存参数只影响 Vite 阶段，调堆上限不再使依赖安装层失效。
# CI 默认 4096；服务器本地构建沿用 1536（768 曾实测 OOM）。
ARG NODE_BUILD_MEMORY=4096
ENV NODE_OPTIONS="--max-old-space-size=${NODE_BUILD_MEMORY}"

# 构建版本信息：在依赖安装后注入，避免版本变化破坏依赖缓存。
ARG BUILD_VERSION=unknown
ARG BUILD_TIME=
ENV BUILD_VERSION=${BUILD_VERSION} \
    BUILD_TIME=${BUILD_TIME}

COPY . .
# 将低频变化的 vendor 分包单独存放；运行镜像分层复制，业务更新无需重拉这些大文件。
RUN npm run build && mkdir -p /app/vendor-assets && \
    for asset in /app/dist/assets/vendor-*; do \
        if [ -f "$asset" ]; then mv "$asset" /app/vendor-assets/; fi; \
    done

# 运行阶段
# resolve + zone 的动态 upstream 需要 Nginx OSS 1.27.3 或更新版本。
FROM nginx:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/vendor-assets/ /usr/share/nginx/html/assets/
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
