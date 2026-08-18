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
# CI 传入上次成功部署的提交，用于只构建真正发生变化的服务。
DEPLOY_BASE_COMMIT=${DEPLOY_BASE_COMMIT:-}
# CI 构建完成后传入 GHCR 镜像前缀与短期令牌；手动部署未传入时仍保留本机构建能力。
IMAGE_PREFIX=${IMAGE_PREFIX:-}
IMAGE_TAG=${IMAGE_TAG:-}
GHCR_ACTOR=${GHCR_ACTOR:-}
GHCR_TOKEN=${GHCR_TOKEN:-}
LOCK_FILE="$APP_DIR/.deploy.lock"
DEPLOY_MARKER="$APP_DIR/.deploy-success-sha"

cd "$APP_DIR"

# 同一服务器只允许一个部署进程运行，避免被取消的旧 SSH 会话与新会话同时构建镜像。
# 重载本脚本时继承已锁定的文件描述符，避免锁在 exec 瞬间被释放。
if [ "${DEPLOY_LOCK_ACQUIRED:-0}" != "1" ]; then
    exec 9>"$LOCK_FILE"
    echo "==> 等待部署互斥锁"
    # 取消的 SSH 任务若留下短暂构建进程，最多等待 2 分钟，避免流水线长时间假死。
    if ! flock -w 120 9; then
        echo "错误：等待部署互斥锁超过 2 分钟；请检查是否有残留 deploy.sh/docker build 进程"
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
# 优先使用工作流解析出的上次成功部署提交；手动部署则回退到本机成功标记。
if [ -z "$DEPLOY_BASE_COMMIT" ] && [ -s "$DEPLOY_MARKER" ]; then
    DEPLOY_BASE_COMMIT=$(cat "$DEPLOY_MARKER")
    export DEPLOY_BASE_COMMIT
fi
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

# 手动部署没有传入精确 SHA 时，以同步后的 HEAD 作为本次目标提交。
DEPLOY_COMMIT=${DEPLOY_COMMIT:-$(git rev-parse HEAD)}

# 注入构建版本信息
export BUILD_VERSION=$(git rev-parse --short HEAD)
export BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

echo "==> [2/4] 按代码差异构建容器镜像（BUILD_VERSION=$BUILD_VERSION，旧容器持续服务中）"
BUILD_SERVICES=()

# CI 已在 GitHub runner 构建镜像时，生产机仅拉取增量层，避免编译过程耗尽线上 CPU/内存。
if [ -n "$IMAGE_PREFIX" ] && [ -n "$IMAGE_TAG" ] && [ -n "$GHCR_ACTOR" ] && [ -n "$GHCR_TOKEN" ]; then
    IMAGE_PREFIX=${IMAGE_PREFIX,,}
    export WEB_IMAGE="${IMAGE_PREFIX}-web:${IMAGE_TAG}"
    export API_IMAGE="${IMAGE_PREFIX}-api:${IMAGE_TAG}"
    export WORKER_IMAGE="${IMAGE_PREFIX}-worker:${IMAGE_TAG}"
    export LIGHTRAG_IMAGE="${IMAGE_PREFIX}-lightrag:${IMAGE_TAG}"
    export STRESS_IMAGE="${IMAGE_PREFIX}-stress:${IMAGE_TAG}"

    echo "==> 登录 GHCR 并拉取预构建镜像"
    printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_ACTOR" --password-stdin >/dev/null
    docker compose pull web api worker lightrag stress
    docker logout ghcr.io >/dev/null 2>&1 || true
# 首次手动部署或基准提交不可用时，为保证正确性执行一次全量业务镜像构建。
elif [ -z "$DEPLOY_BASE_COMMIT" ] || ! git cat-file -e "${DEPLOY_BASE_COMMIT}^{commit}" 2>/dev/null; then
    echo "==> 未找到有效部署基准，本次全量构建"
    BUILD_SERVICES=(web api worker lightrag stress)
else
    echo "==> 对比上次成功部署：${DEPLOY_BASE_COMMIT:0:8}..${BUILD_VERSION}"
    CHANGED_FILES=$(git diff --name-only "$DEPLOY_BASE_COMMIT" "$DEPLOY_COMMIT")

    # compose 拓扑或根部署配置变化会影响所有服务，必须全量重建。
    if grep -Eq '^(docker-compose\.yml|\.env\.example)$' <<<"$CHANGED_FILES"; then
        BUILD_SERVICES=(web api worker lightrag stress)
    else
        grep -q '^frontend/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(web)
        grep -q '^backend/api/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(api)
        grep -q '^backend/worker/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(worker)
        grep -q '^backend/lightrag/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(lightrag)
        grep -q '^backend/stress/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(stress)
    fi
fi

if [ "${#BUILD_SERVICES[@]}" -eq 0 ]; then
    echo "==> 仅部署脚本/工作流发生变化，无需构建业务镜像"
else
    echo "==> 本次构建服务：${BUILD_SERVICES[*]}"
    # 低配服务器顺序构建，避免并发争抢内存触发 swap；未变化服务直接复用现有镜像。
    for service in "${BUILD_SERVICES[@]}"; do
        BUILDKIT_PROGRESS=plain docker compose build "$service"
    done
fi

echo "==> [3/4] 平滑滚动更新服务容器（无闪断）"
if ! docker compose up -d --no-build --remove-orphans; then
    echo "警告：平滑更新异常，尝试安全按序自愈拉起..."
    # 优先保证 postgres 不被误杀，仅重启业务应用
    docker compose stop web api worker lightrag stress 2>/dev/null || true
    docker compose up -d --no-build
fi

# 仅在容器滚动更新成功后记录部署提交，失败任务不会污染下一次差异计算基准。
printf '%s\n' "${DEPLOY_COMMIT:-$(git rev-parse HEAD)}" > "$DEPLOY_MARKER"

echo "==> [4/4] 清理未使用的历史悬空镜像"
docker image prune -f --filter "dangling=true" >/dev/null 2>&1 || true

echo "==> 部署成功完成！各服务运行状态："
docker compose ps
