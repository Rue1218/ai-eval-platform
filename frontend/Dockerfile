# 构建阶段
FROM node:20-alpine AS build
WORKDIR /app

# 构建版本信息：由 docker compose / deploy.sh 通过 build args 注入
ARG BUILD_VERSION=unknown
ARG BUILD_TIME=
ENV BUILD_VERSION=${BUILD_VERSION} \
    BUILD_TIME=${BUILD_TIME}

COPY package.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN npm run build

# 运行阶段
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
