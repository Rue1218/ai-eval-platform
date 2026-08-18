#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 部署脚本：GitHub 代码更新 -> 服务器同步 -> 容器重建
# 由 GitHub Actions 或手动执行。
# 逻辑：强制同步到远程 main（服务器不是开发机，本地改动一律丢弃），
#       然后 docker compose 重建并清理旧镜像。
# ============================================================

APP_DIR=/opt/ai-eval-platform
GIT_REPO=${GIT_REPO:-git@github.com:Rue1218/ai-eval-platform.git}
BRANCH=${BRANCH:-main}

cd "$APP_DIR"

echo "==> 同步代码"
if [ ! -d .git ]; then
    echo "首次部署：clone 仓库"
    git clone "$GIT_REPO" .
fi

git fetch origin
git reset --hard "origin/$BRANCH"

# 注入构建版本信息（前端控制台打印用）
export BUILD_VERSION=$(git rev-parse --short HEAD)
export BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "==> 构建镜像（BUILD_VERSION=$BUILD_VERSION）"
docker compose build

echo "==> 启动与更新容器"
if ! docker compose up -d --remove-orphans; then
    echo "检测到容器元数据残留，强制清理本项目容器状态后重新拉起..."
    docker rm -f $(docker ps -a -q --filter "name=ai-eval-platform") 2>/dev/null || true
    docker container prune -f || true
    docker compose up -d
fi

echo "==> 清理旧镜像"
docker image prune -f

echo "==> 部署完成"
docker compose ps
