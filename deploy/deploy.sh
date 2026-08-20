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
# PostgreSQL 使用精确补丁版本；仅目标镜像发生变化时执行备份与重建。
POSTGRES_IMAGE=${POSTGRES_IMAGE:-postgres:16.15-alpine}
export POSTGRES_IMAGE
LOCK_FILE="$APP_DIR/.deploy.lock"
DEPLOY_MARKER="$APP_DIR/.deploy-success-sha"
DEPLOY_IMAGE_ENV="$APP_DIR/.deploy-images.env"

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

# 先计算本次真正受影响的服务；CI 拉取与手动本地构建共用同一结果。
if [ -z "$DEPLOY_BASE_COMMIT" ] || ! git cat-file -e "${DEPLOY_BASE_COMMIT}^{commit}" 2>/dev/null; then
    echo "==> 未找到有效部署基准，本次全量构建"
    BUILD_SERVICES=(web api worker lightrag stress)
else
    echo "==> 对比上次成功部署：${DEPLOY_BASE_COMMIT:0:8}..${BUILD_VERSION}"
    CHANGED_FILES=$(git diff --name-only "$DEPLOY_BASE_COMMIT" "$DEPLOY_COMMIT")

    # Compose/部署配置由 up 阶段直接应用，不要求重建镜像；只有服务构建上下文变化才构建。
    grep -q '^frontend/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(web)
    grep -q '^backend/api/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(api)
    grep -q '^backend/worker/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(worker)
    grep -q '^backend/lightrag/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(lightrag)
    grep -q '^backend/stress/' <<<"$CHANGED_FILES" && BUILD_SERVICES+=(stress)
    # 共享模型包 backend/shared/ 被 api 与 worker 打进镜像，变更须同时重建（缺谁补谁）。
    if grep -q '^backend/shared/' <<<"$CHANGED_FILES"; then
        case " ${BUILD_SERVICES[*]} " in
            *' api '*) ;;
            *) BUILD_SERVICES+=(api) ;;
        esac
        case " ${BUILD_SERVICES[*]} " in
            *' worker '*) ;;
            *) BUILD_SERVICES+=(worker) ;;
        esac
    fi
fi

# 恢复上一轮各服务使用的不可变镜像引用，未变化服务不会回退到旧镜像。
if [ -s "$DEPLOY_IMAGE_ENV" ]; then
    set -a
    # 文件仅由本脚本写入受控的镜像引用，不包含凭据。
    # shellcheck disable=SC1090
    source "$DEPLOY_IMAGE_ENV"
    set +a
fi

# CI 已在 GitHub runner 构建镜像时，生产机只拉取变化服务的增量层。
if [ -n "$IMAGE_PREFIX" ] && [ -n "$IMAGE_TAG" ] && [ -n "$GHCR_ACTOR" ] && [ -n "$GHCR_TOKEN" ]; then
    IMAGE_PREFIX=${IMAGE_PREFIX,,}
    for service in "${BUILD_SERVICES[@]}"; do
        case "$service" in
            web) export WEB_IMAGE="${IMAGE_PREFIX}-web:${IMAGE_TAG}" ;;
            api) export API_IMAGE="${IMAGE_PREFIX}-api:${IMAGE_TAG}" ;;
            worker) export WORKER_IMAGE="${IMAGE_PREFIX}-worker:${IMAGE_TAG}" ;;
            lightrag) export LIGHTRAG_IMAGE="${IMAGE_PREFIX}-lightrag:${IMAGE_TAG}" ;;
            stress) export STRESS_IMAGE="${IMAGE_PREFIX}-stress:${IMAGE_TAG}" ;;
        esac
    done

    if [ "${#BUILD_SERVICES[@]}" -eq 0 ]; then
        echo "==> 仅部署脚本/工作流发生变化，无需拉取业务镜像"
    else
        echo "==> 登录 GHCR，仅拉取变化服务：${BUILD_SERVICES[*]}"
        printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_ACTOR" --password-stdin >/dev/null
        docker compose pull "${BUILD_SERVICES[@]}"
        docker logout ghcr.io >/dev/null 2>&1 || true
    fi
elif [ "${#BUILD_SERVICES[@]}" -eq 0 ]; then
    echo "==> 仅部署脚本/工作流发生变化，无需构建业务镜像"
else
    echo "==> 本次构建服务：${BUILD_SERVICES[*]}"
    # 低配服务器顺序构建，避免并发争抢内存触发 swap；未变化服务直接复用现有镜像。
    for service in "${BUILD_SERVICES[@]}"; do
        BUILDKIT_PROGRESS=plain docker compose build "$service"
    done
fi

# PostgreSQL 镜像变更属于有状态升级：先完整备份，再拉取目标镜像。
POSTGRES_CONTAINER=$(docker compose ps -q postgres 2>/dev/null || true)
CURRENT_POSTGRES_IMAGE=""
POSTGRES_IMAGE_CHANGED=0
if [ -n "$POSTGRES_CONTAINER" ]; then
    CURRENT_POSTGRES_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$POSTGRES_CONTAINER")
fi

if [ "$CURRENT_POSTGRES_IMAGE" != "$POSTGRES_IMAGE" ]; then
    POSTGRES_IMAGE_CHANGED=1
    echo "==> PostgreSQL 镜像更新：${CURRENT_POSTGRES_IMAGE:-首次部署} -> ${POSTGRES_IMAGE}"
    if [ -n "$POSTGRES_CONTAINER" ]; then
        BACKUP_DIR="$APP_DIR/data/backups"
        BACKUP_FILE="$BACKUP_DIR/postgres-pre-upgrade-$(date -u +'%Y%m%dT%H%M%SZ').sql.gz"
        mkdir -p "$BACKUP_DIR"
        echo "==> 升级前执行 pg_dumpall：$BACKUP_FILE"
        if ! docker compose exec -T postgres sh -c 'pg_dumpall -U "$POSTGRES_USER"' | gzip -c > "$BACKUP_FILE"; then
            rm -f "$BACKUP_FILE"
            echo "错误：PostgreSQL 升级前备份失败，已中止镜像切换" >&2
            exit 1
        fi
        chmod 600 "$BACKUP_FILE"
        if [ ! -s "$BACKUP_FILE" ]; then
            echo "错误：PostgreSQL 备份文件为空，已中止镜像切换" >&2
            exit 1
        fi
    fi
    echo "==> 拉取 PostgreSQL 精确版本镜像"
    timeout 300 docker pull "$POSTGRES_IMAGE"
fi

# 有状态容器必须先单独更新并恢复健康，再允许业务容器滚动更新。
if [ "$POSTGRES_IMAGE_CHANGED" = "1" ]; then
    echo "==> 单独更新 PostgreSQL 容器"
    if ! docker compose up -d --no-build postgres; then
        echo "错误：PostgreSQL 容器更新失败，业务容器保持原状；请使用升级前备份排查" >&2
        exit 1
    fi
    echo "==> 验证 PostgreSQL 升级后健康状态"
    POSTGRES_READY=0
    for attempt in $(seq 1 30); do
        if docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
            POSTGRES_READY=1
            break
        fi
        sleep 2
    done
    if [ "$POSTGRES_READY" != "1" ]; then
        echo "错误：PostgreSQL 在 60 秒内未恢复健康，请使用升级前备份排查或回滚" >&2
        exit 1
    fi
fi

# 只滚动更新发生变化且原本处于运行状态的服务；用户主动 stop/pause 的服务保持原状态。
DEPLOY_SERVICES=()
for service in "${BUILD_SERVICES[@]}"; do
    SERVICE_CONTAINER=$(docker compose ps -aq "$service" 2>/dev/null || true)
    if [ -z "$SERVICE_CONTAINER" ]; then
        # 首次部署没有旧容器，需要创建服务。
        DEPLOY_SERVICES+=("$service")
        continue
    fi
    SERVICE_RUNNING=$(docker inspect --format '{{.State.Running}}' "$SERVICE_CONTAINER")
    SERVICE_PAUSED=$(docker inspect --format '{{.State.Paused}}' "$SERVICE_CONTAINER")
    if [ "$SERVICE_RUNNING" = "true" ] && [ "$SERVICE_PAUSED" != "true" ]; then
        DEPLOY_SERVICES+=("$service")
    else
        echo "==> 保留 $service 的停止/暂停状态；镜像已更新，手动恢复时生效"
    fi
done

if [ "${#DEPLOY_SERVICES[@]}" -eq 0 ]; then
    echo "==> [3/4] 无需滚动更新业务服务"
elif ! docker compose up -d --no-build --remove-orphans "${DEPLOY_SERVICES[@]}"; then
    echo "警告：业务服务平滑更新异常，尝试安全按序自愈拉起：${DEPLOY_SERVICES[*]}"
    # PostgreSQL 已独立验证健康，自愈阶段只处理本次计划更新的业务应用。
    docker compose stop "${DEPLOY_SERVICES[@]}" 2>/dev/null || true
    docker compose up -d --no-build "${DEPLOY_SERVICES[@]}"
fi

# Web 镜像的入口 HTML 与其首屏静态资源必须成对存在，否则 Nginx 会把缺失分包回退成 HTML。
if [[ " ${DEPLOY_SERVICES[*]} " == *" web "* ]]; then
    echo "==> 验证 Web 入口引用的静态资源"
    docker compose exec -T web sh -eu -c '
        web_root=/usr/share/nginx/html
        entry_html="$web_root/index.html"
        [ -f "$entry_html" ] || { echo "错误：Web 容器缺少 index.html" >&2; exit 1; }

        asset_paths=$(sed -n \
            -e "s|.*src=\"\(/assets/[^\"]*\)\".*|\1|p" \
            -e "s|.*href=\"\(/assets/[^\"]*\)\".*|\1|p" \
            "$entry_html")
        [ -n "$asset_paths" ] || { echo "错误：Web 入口未引用 Vite 静态资源" >&2; exit 1; }

        for asset_path in $asset_paths; do
            [ -f "$web_root$asset_path" ] || { echo "错误：Web 容器缺少静态资源 $asset_path" >&2; exit 1; }
        done
    '
fi

# 仅在容器滚动更新成功后记录部署提交，失败任务不会污染下一次差异计算基准。
printf '%s\n' "${DEPLOY_COMMIT:-$(git rev-parse HEAD)}" > "$DEPLOY_MARKER"
# 持久化镜像引用；使用 %q 防止再次 source 时发生 shell 注入。
{
    for variable in WEB_IMAGE API_IMAGE WORKER_IMAGE LIGHTRAG_IMAGE STRESS_IMAGE; do
        if [ -n "${!variable:-}" ]; then
            printf '%s=%q\n' "$variable" "${!variable}"
        fi
    done
} > "$DEPLOY_IMAGE_ENV"

echo "==> [4/4] 清理未使用的历史悬空镜像"
docker image prune -f --filter "dangling=true" >/dev/null 2>&1 || true

echo "==> 部署成功完成！各服务运行状态："
docker compose ps
