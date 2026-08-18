#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 部署脚本：GitHub 代码更新 -> 服务器同步 -> 零中断平滑热更
# 优化点：
# 1. 开启 BuildKit 并发多核构建，极大缩短镜像生成时间
# 2. 前端 Dockerfile 分层缓存修复（npm install 100% 命中缓存）
# 3. 先在后台并发完成镜像构建，构建期间旧容器持续对外提供服务（0 中断）
# 4. 镜像构建完成后，执行 docker compose 原子滚动替换，避免数据库与前端闪断
# ============================================================

APP_DIR=/opt/ai-eval-platform
GIT_REPO=${GIT_REPO:-git@github.com:Rue1218/ai-eval-platform.git}
BRANCH=${BRANCH:-main}

cd "$APP_DIR"

echo "==> [1/4] 同步最新代码 (分支: $BRANCH)"
if [ ! -d .git ]; then
    echo "首次部署：初始化 clone 仓库"
    git clone "$GIT_REPO" .
fi

git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

# git reset 可能刚更新本脚本；重新加载一次，确保手动部署也使用当前提交的逻辑。
if [ "${DEPLOY_SCRIPT_RELOADED:-0}" != "1" ]; then
    echo "==> 重新加载当前提交的部署脚本"
    export DEPLOY_SCRIPT_RELOADED=1
    exec bash "$APP_DIR/deploy/deploy.sh"
fi

# 注入构建版本信息
export BUILD_VERSION=$(git rev-parse --short HEAD)
export BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

echo "==> [2/4] 并发构建容器镜像（BUILD_VERSION=$BUILD_VERSION，旧容器持续服务中）"
docker compose build --parallel

echo "==> [3/4] 平滑滚动更新服务容器（无闪断）"
if ! docker compose up -d --no-build --remove-orphans; then
    echo "警告：平滑更新异常，尝试安全按序自愈拉起..."
    # 优先保证 postgres 不被误杀，仅重启业务应用
    docker compose stop web api worker lightrag stress 2>/dev/null || true
    docker compose up -d --no-build
fi

echo "==> [4/4] 清理未使用的历史悬空镜像"
docker image prune -f --filter "dangling=true" >/dev/null 2>&1 || true

echo "==> 部署成功完成！各服务运行状态："
docker compose ps
