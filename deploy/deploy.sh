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
# CI 会传入精确提交；手动部署未传入时仍保持部署 main 分支的原有行为。
DEPLOY_COMMIT=${DEPLOY_COMMIT:-}
LOCK_FILE="$APP_DIR/.deploy.lock"

cd "$APP_DIR"

# 同一服务器只允许一个部署进程运行，避免被取消的旧 SSH 会话与新会话同时构建镜像。
# 重载本脚本时继承已锁定的文件描述符，避免锁在 exec 瞬间被释放。
if [ "${DEPLOY_LOCK_ACQUIRED:-0}" != "1" ]; then
    exec 9>"$LOCK_FILE"
    echo "==> 等待部署互斥锁"
    if ! flock -w 25m 9; then
        echo "错误：等待部署互斥锁超过 25 分钟"
        exit 1
    fi
    export DEPLOY_LOCK_ACQUIRED=1
fi

echo "==> [1/4] 同步最新代码 (分支: $BRANCH)"
if [ ! -d .git ]; then
    echo "首次部署：初始化 clone 仓库"
    git clone "$GIT_REPO" .
fi

git fetch origin "$BRANCH"
# CI 必须部署触发提交，避免旧工作流在 fetch 后误部署更晚推送的 main。
if [ -n "$DEPLOY_COMMIT" ]; then
    git cat-file -e "${DEPLOY_COMMIT}^{commit}"
    git reset --hard "$DEPLOY_COMMIT"
else
    git reset --hard "origin/$BRANCH"
fi

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

echo "==> [2/4] 分阶段构建容器镜像（BUILD_VERSION=$BUILD_VERSION，旧容器持续服务中）"
# Vite 与 Python/Go 镜像并发构建会在低配服务器上争抢 CPU、内存并触发 swap；前端单独构建。
BUILDKIT_PROGRESS=plain docker compose build web
# 前端完成后再并发构建后端镜像，保留后端依赖缓存的构建效率。
BUILDKIT_PROGRESS=plain docker compose build --parallel api worker lightrag stress

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
