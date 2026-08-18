# 构建阶段
FROM node:20-alpine AS build
WORKDIR /app

ENV NODE_OPTIONS="--max-old-space-size=1024"

# 先复制依赖清单并安装，充分利用 Docker 层缓存（只要 package.json 不变就不重复安装）
COPY package.json package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com && \
    npm install --prefer-offline --no-audit

# 构建版本信息：由 docker compose / deploy.sh 通过 build args 注入（移至 npm install 之后避免破坏依赖缓存）
ARG BUILD_VERSION=unknown
ARG BUILD_TIME=
ENV BUILD_VERSION=${BUILD_VERSION} \
    BUILD_TIME=${BUILD_TIME}

COPY . .
RUN npm run build

# 运行阶段
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
