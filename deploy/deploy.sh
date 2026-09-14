#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 部署脚本：同步精确提交 -> 增量准备镜像 -> 替换变化服务。
# CI 构建后生产机只拉取；本地回退使用 BuildKit 缓存并逐服务串行构建。
# 构建期间旧容器继续服务；单副本替换仍有短暂切换窗口。
# ============================================================

# 部署目录可被环境变量覆盖（本机部署于 /root/ai-eval-platform，GitHub Actions 使用 /opt 默认值）
APP_DIR=${APP_DIR:-/opt/ai-eval-platform}
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
# 限制生产机同时拉取的服务数，降低并发下载/解压造成的内存与磁盘争抢。
# 仅作用于 pull，不改变 Compose 启动依赖顺序或 CI 的独立构建任务。
DEPLOY_PULL_PARALLEL=${DEPLOY_PULL_PARALLEL:-2}
if ! [[ "$DEPLOY_PULL_PARALLEL" =~ ^[1-9][0-9]*$ ]]; then
    echo "错误：DEPLOY_PULL_PARALLEL 必须为正整数" >&2
    exit 1
fi
# 基础设施镜像不在此处定义默认值：以 docker-compose.yml 的插值结果为唯一事实源（见 [2] 阶段）。
# 避免脚本默认值与 Compose 默认镜像漂移（曾因旧 postgres:16.15-alpine 硬编码覆盖 pgvector 镜像）。
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

# 已持有部署互斥锁：此时不应再有其它 git 写操作。被取消的 SSH 会话
# 可能在 git reset 中途留下 HEAD.lock / index.lock，必须先清掉再同步。
if [ -d "$APP_DIR/.git" ]; then
    stale_locks=$(find "$APP_DIR/.git" -name '*.lock' -type f 2>/dev/null || true)
    if [ -n "$stale_locks" ]; then
        echo "警告：清理过期 git 锁"
        echo "$stale_locks"
        find "$APP_DIR/.git" -name '*.lock' -type f -delete
    fi
fi

git_fetch_with_retry() {
    # GitHub SSH 偶发拒绝复用通道（channel 0: administratively prohibited），短间隔连拉会失败。
    local attempt=1
    local max_attempts=3
    while true; do
        if git fetch "$@"; then
            return 0
        fi
        if [ "$attempt" -ge "$max_attempts" ]; then
            echo "错误：git fetch 失败（已重试 $max_attempts 次）" >&2
            return 1
        fi
        echo "警告：git fetch 失败，${attempt}/${max_attempts} 次，即将重试"
        sleep $((attempt * 2))
        attempt=$((attempt + 1))
    done
}

echo "==> [1/4] 同步最新代码 (分支: $BRANCH)"
if [ ! -d .git ]; then
    echo "首次部署：初始化 clone 仓库"
    git clone "$GIT_REPO" .
fi

# 优先使用工作流解析出的上次成功部署提交；手动部署则回退到本机成功标记。
if [ -z "$DEPLOY_BASE_COMMIT" ] && [ -s "$DEPLOY_MARKER" ]; then
    DEPLOY_BASE_COMMIT=$(cat "$DEPLOY_MARKER")
    export DEPLOY_BASE_COMMIT
fi

# 工作流入口已经 fetch 过目标提交；脚本重载后 HEAD 已到位。再 fetch 会被 GitHub SSH 拒通道。
if [ -n "$DEPLOY_COMMIT" ] && git cat-file -e "${DEPLOY_COMMIT}^{commit}" 2>/dev/null \
    && [ "$(git rev-parse HEAD 2>/dev/null || true)" = "$(git rev-parse "$DEPLOY_COMMIT")" ]; then
    echo "==> 工作区已在目标提交 ${DEPLOY_COMMIT:0:8}，跳过 fetch"
elif [ -n "$DEPLOY_COMMIT" ] && git cat-file -e "${DEPLOY_COMMIT}^{commit}" 2>/dev/null; then
    echo "==> 目标提交已在本地对象库，跳过 fetch：${DEPLOY_COMMIT:0:8}"
    git reset --hard "$DEPLOY_COMMIT"
else
    git_fetch_with_retry origin "$BRANCH"
    # CI 必须部署触发提交，避免旧工作流在 fetch 后误部署更晚推送的 main。
    if [ -n "$DEPLOY_COMMIT" ]; then
        git cat-file -e "${DEPLOY_COMMIT}^{commit}"
        git reset --hard "$DEPLOY_COMMIT"
    else
        git reset --hard "origin/$BRANCH"
    fi
fi

# 手动部署没有传入精确 SHA 时，以同步后的 HEAD 作为本次目标提交。
DEPLOY_COMMIT=${DEPLOY_COMMIT:-$(git rev-parse HEAD)}
export DEPLOY_COMMIT

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

# 先判断部署差异：纯文档/测试提交同步 Git 后即可结束，不访问 Docker 或清理镜像。
# CI 与服务器共用计划，避免拉取 CI 未构建的目标标签。
DEPLOY_PLAN=$(python3 deploy/plan_services.py --base "$DEPLOY_BASE_COMMIT" --target "$DEPLOY_COMMIT")
BUILD_LIST=$(python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["build_services"]))' <<<"$DEPLOY_PLAN")
UPDATE_LIST=$(python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["deploy_services"]))' <<<"$DEPLOY_PLAN")
read -r -a BUILD_SERVICES <<<"$BUILD_LIST"
read -r -a UPDATE_SERVICES <<<"$UPDATE_LIST"
if [ "${#UPDATE_SERVICES[@]}" -eq 0 ]; then
    echo "==> 无运行时变化，跳过构建与容器更新"
    printf '%s\n' "$DEPLOY_COMMIT" > "$DEPLOY_MARKER"
    exit 0
fi
echo "==> 本次构建：${BUILD_SERVICES[*]:-无}；配置应用：${UPDATE_SERVICES[*]:-无}"

# H5 混合引擎生产前置检查：开启混合引擎时禁止以 memory 检查点部署，
# 否则 API 虽能启动，HITL 中断状态却无法跨进程重启恢复。
echo "==> 校验 H5 生产检查点与沙箱网络配置"
docker compose config --format json | python3 -c '
import json
import sys

config = json.load(sys.stdin)
services = config.get("services", {})
api_env = services.get("api", {}).get("environment", {})
hybrid_enabled = str(api_env.get("HYBRID_ENGINE_ENABLED", "false")).lower() == "true"
checkpointer = str(api_env.get("AGENT_CHECKPOINTER", "memory")).lower()
strict_pg = str(api_env.get("AGENT_HITL_STRICT_PG", "false")).lower() == "true"
if hybrid_enabled and (checkpointer != "postgres" or not strict_pg):
    print("错误：HYBRID_ENGINE_ENABLED=true 时必须同时设置 AGENT_CHECKPOINTER=postgres 与 AGENT_HITL_STRICT_PG=true", file=sys.stderr)
    sys.exit(1)
runner_networks = set(services.get("runner", {}).get("networks", {}))
if runner_networks != {"sandbox_net", "runner_egress"}:
    print("错误：runner 必须加入 sandbox_net(控制面) + runner_egress(出网)", file=sys.stderr)
    sys.exit(1)
if config.get("networks", {}).get("runner_egress", {}).get("internal"):
    print("错误：runner_egress 不得为 internal（档3 需公网）", file=sys.stderr)
    sys.exit(1)
# 沙箱形态断言（容器内直跑，见 docs/…-沙箱执行方案重设计.md）：无 privileged、
# read_only rootfs + tmpfs、no-new-privileges、显式 seccomp:unconfined、
# SYS_ADMIN（unshare 建命名空间）+ NET_ADMIN（档3 专用 netns/veth 出网）。
runner_cfg = services.get("runner", {})
runner_caps = set(runner_cfg.get("cap_add", []) or [])
runner_secopts = set(runner_cfg.get("security_opt", []) or [])
runner_tmpfs = set(runner_cfg.get("tmpfs", []) or [])
if runner_cfg.get("privileged"):
    print("错误：runner 不得 privileged，请改 compose 后重试", file=sys.stderr)
    sys.exit(1)
if not runner_cfg.get("read_only"):
    print("错误：runner 必须 read_only: true（rootfs 只读，系统目录兜底）", file=sys.stderr)
    sys.exit(1)
if "SYS_ADMIN" not in runner_caps:
    print("错误：runner 必须 cap_add SYS_ADMIN（unshare 建 netns/pidns 所需）", file=sys.stderr)
    sys.exit(1)
if "NET_ADMIN" not in runner_caps:
    print("错误：runner 必须 cap_add NET_ADMIN（档3 专用 netns/veth 出网所需）", file=sys.stderr)
    sys.exit(1)
if "seccomp:unconfined" not in runner_secopts:
    print("错误：runner 必须显式 seccomp:unconfined（默认 profile 拦 unshare，PoC 结论）", file=sys.stderr)
    sys.exit(1)
if not any(opt.startswith("no-new-privileges") for opt in runner_secopts):
    print("错误：runner 必须设 no-new-privileges", file=sys.stderr)
    sys.exit(1)
if not any(p.startswith("/tmp") for p in runner_tmpfs) or not any(p.startswith("/run") for p in runner_tmpfs):
    print("错误：runner 必须挂 /tmp 与 /run tmpfs（read_only 运行面）", file=sys.stderr)
    sys.exit(1)
runner_mounts = {v.get("target") for v in (runner_cfg.get("volumes", []) or []) if isinstance(v, dict)}
if "/data/workspaces" not in runner_mounts:
    print("错误：runner 必须挂载工作区 /data/workspaces（rw）", file=sys.stderr)
    sys.exit(1)
if not any(t for t in runner_mounts if t and not str(t).startswith("/data")):
    print("错误：runner 必须挂载外部白名单基目录（EXTERNAL_BASE_DIR）", file=sys.stderr)
    sys.exit(1)
print(f"H5 配置通过：hybrid={hybrid_enabled} checkpointer={checkpointer} strict_pg={strict_pg}；runner 沙箱断言通过")
'

# 外部白名单基目录就绪（compose 以它做 rw 挂载；不存在时 docker 会建空目录）
EXTERNAL_BASE_DIR="${EXTERNAL_BASE_DIR:-/srv/agent-external}"
mkdir -p "$EXTERNAL_BASE_DIR"

echo "==> [2/4] 按代码差异构建容器镜像（BUILD_VERSION=$BUILD_VERSION，旧容器持续服务中）"

# 受控 MCP 以 backend/<名称>_mcp/Dockerfile 作为约定入口，Compose 服务名为
# <名称>-mcp。新增 MCP 只需遵守该目录与命名约定，即可自动进入构建、拉取、
# 滚动更新和历史镜像保留流程，避免再出现媒体 MCP 漏部署。
MCP_BUILD_SERVICES=()
for dockerfile in backend/*_mcp/Dockerfile; do
    [ -f "$dockerfile" ] || continue
    mcp_package=$(basename "$(dirname "$dockerfile")")
    mcp_service="${mcp_package%_mcp}"
    mcp_service="${mcp_service//_/-}-mcp"
    MCP_BUILD_SERVICES+=("$mcp_service")
done

service_image_variable() {
    # Compose 镜像变量统一遵循 <SERVICE_UPPERCASE>_IMAGE，例如 media-mcp -> MEDIA_MCP_IMAGE。
    local normalized="${1^^}"
    normalized="${normalized//-/_}"
    printf '%s_IMAGE\n' "$normalized"
}

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
        image_variable="$(service_image_variable "$service")"
        export "$image_variable=${IMAGE_PREFIX}-${service}:${IMAGE_TAG}"
    done

    if [ "${#BUILD_SERVICES[@]}" -eq 0 ]; then
        echo "==> 仅部署脚本/工作流发生变化，无需拉取业务镜像"
    else
        echo "==> 登录 GHCR，仅拉取变化服务：${BUILD_SERVICES[*]}"
        printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_ACTOR" --password-stdin >/dev/null
        docker compose --parallel "$DEPLOY_PULL_PARALLEL" pull "${BUILD_SERVICES[@]}"
        docker logout ghcr.io >/dev/null 2>&1 || true
    fi
elif [ "${#BUILD_SERVICES[@]}" -eq 0 ]; then
    echo "==> 仅部署脚本/工作流发生变化，无需构建业务镜像"
else
    echo "==> 本次构建服务：${BUILD_SERVICES[*]}"
    # 本地构建的 apt 层走 USTC Debian 镜像源（deb.debian.org 实测 17.6kB/s，
    # runner 冷缓存安装 bubblewrap 耗时 9min+）；CI 在 GitHub runner 构建不受影响。
    export APT_MIRROR=${APT_MIRROR:-mirrors.ustc.edu.cn}
    # 低配服务器顺序构建，避免并发争抢内存触发 swap；未变化服务直接复用现有镜像。
    for service in "${BUILD_SERVICES[@]}"; do
        if [ "$service" = "web" ]; then
            # 服务器本地构建收紧 Vite 堆，避免与运行中容器争抢内存后持续 swap（CI 构建不受影响）。
            # 768 已不够：2026-08-29 前端增长后 vite build 在 768MB 堆上限 OOM，
            # 手动部署需 1536 才能通过（9 分钟）；内存充足的机器可经 NODE_BUILD_MEMORY 调高（本机 16G 用 2048）。
            NODE_BUILD_MEMORY="${NODE_BUILD_MEMORY:-1536}" BUILDKIT_PROGRESS=plain docker compose build "$service"
        else
            BUILDKIT_PROGRESS=plain docker compose build "$service"
        fi
    done
fi

# 上一轮部署可能在镜像已拉取后、容器滚动前被中断；此时 .deploy-images.env
# 虽记录了目标不可变镜像，但线上仍会继续运行旧容器。把镜像不一致的服务
# 重新纳入本轮更新，避免工作流误报成功而静态前端仍停留在旧版本。
RECONCILED_SERVICES=()
TRACKED_IMAGE_SERVICES=(web api worker runner lightrag stress "${MCP_BUILD_SERVICES[@]}")
for service in "${TRACKED_IMAGE_SERVICES[@]}"; do
    image_variable="$(service_image_variable "$service")"
    expected_image="${!image_variable:-}"
    [ -n "$expected_image" ] || continue

    service_containers=$(docker compose ps -aq "$service" 2>/dev/null || true)
    [ -n "$service_containers" ] || continue
    running_images=$(docker inspect --format '{{.Config.Image}}' $service_containers 2>/dev/null | sort -u)
    if grep -Fqx "$expected_image" <<<"$running_images"; then
        continue
    fi

    echo "==> 检测到 $service 仍使用旧镜像，补入本轮更新：${running_images:-未知} -> $expected_image"
    case " ${BUILD_SERVICES[*]} " in
        *" $service "*) ;;
        *)
            BUILD_SERVICES+=("$service")
            RECONCILED_SERVICES+=("$service")
            ;;
    esac
done

# 差异矩阵在前面已完成，补入的服务尚未经过首次拉取；CI 凭据可用时必须显式
# 拉取其已记录的不可变镜像，避免 --no-build 更新时误用本地旧缓存。
if [ "${#RECONCILED_SERVICES[@]}" -gt 0 ] \
    && [ -n "$IMAGE_PREFIX" ] && [ -n "$GHCR_ACTOR" ] && [ -n "$GHCR_TOKEN" ]; then
    echo "==> 拉取镜像不一致的服务：${RECONCILED_SERVICES[*]}"
    printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_ACTOR" --password-stdin >/dev/null
    docker compose --parallel "$DEPLOY_PULL_PARALLEL" pull "${RECONCILED_SERVICES[@]}"
    docker logout ghcr.io >/dev/null 2>&1 || true
fi

# 基础设施目标镜像以 docker-compose.yml 插值结果为准（唯一事实源），脚本不再重复定义默认值；
# 若环境显式设置 POSTGRES_IMAGE/REDIS_IMAGE，compose 插值会自然生效。单次调用减少部署耗时。
INFRA_IMAGES=$(docker compose config --format json | python3 -c \
    'import json, sys
services = json.load(sys.stdin)["services"]
try:
    print(services["postgres"]["image"])
    print(services["redis"]["image"])
except KeyError:
    sys.exit(1)') || {
    echo "错误：无法解析 postgres/redis 服务镜像，请确认 docker-compose.yml 含对应服务" >&2
    exit 1
}
TARGET_POSTGRES_IMAGE=$(sed -n '1p' <<<"$INFRA_IMAGES")
TARGET_REDIS_IMAGE=$(sed -n '2p' <<<"$INFRA_IMAGES")

# PostgreSQL 镜像变更属于有状态升级：先完整备份，再拉取目标镜像。
POSTGRES_CONTAINER=$(docker compose ps -q postgres 2>/dev/null || true)
CURRENT_POSTGRES_IMAGE=""
POSTGRES_IMAGE_CHANGED=0
if [ -n "$POSTGRES_CONTAINER" ]; then
    CURRENT_POSTGRES_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$POSTGRES_CONTAINER")
fi

if [ "$CURRENT_POSTGRES_IMAGE" != "$TARGET_POSTGRES_IMAGE" ]; then
    POSTGRES_IMAGE_CHANGED=1
    echo "==> PostgreSQL 镜像更新：${CURRENT_POSTGRES_IMAGE:-首次部署} -> ${TARGET_POSTGRES_IMAGE}"
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
    echo "==> 拉取 PostgreSQL 目标镜像"
    timeout 300 docker pull "$TARGET_POSTGRES_IMAGE"
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

# 已有 pgdata 卷不会重新执行 /docker-entrypoint-initdb.d 脚本；每次部署幂等补齐 vector 扩展。
echo "==> 确保 pgvector 扩展已启用"
if ! docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "CREATE EXTENSION IF NOT EXISTS vector"'; then
    echo "错误：pgvector 扩展启用失败，请检查 PostgreSQL 日志" >&2
    exit 1
fi

# Redis 与 PostgreSQL 一样独立检测与更新（AOF/rdb 持久化在 redisdata 卷，无需备份）。
REDIS_CONTAINER=$(docker compose ps -q redis 2>/dev/null || true)
CURRENT_REDIS_IMAGE=""
REDIS_IMAGE_CHANGED=0
if [ -n "$REDIS_CONTAINER" ]; then
    CURRENT_REDIS_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$REDIS_CONTAINER")
fi

if [ "$CURRENT_REDIS_IMAGE" != "$TARGET_REDIS_IMAGE" ]; then
    REDIS_IMAGE_CHANGED=1
    echo "==> Redis 镜像更新：${CURRENT_REDIS_IMAGE:-首次部署} -> ${TARGET_REDIS_IMAGE}"
    timeout 300 docker pull "$TARGET_REDIS_IMAGE"
fi

if [ "$REDIS_IMAGE_CHANGED" = "1" ]; then
    echo "==> 单独更新 Redis 容器"
    if ! docker compose up -d --no-build redis; then
        echo "错误：Redis 容器更新失败，业务容器保持原状" >&2
        exit 1
    fi
    echo "==> 验证 Redis 健康状态"
    REDIS_READY=0
    for attempt in $(seq 1 30); do
        if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
            REDIS_READY=1
            break
        fi
        sleep 2
    done
    if [ "$REDIS_READY" != "1" ]; then
        echo "错误：Redis 在 60 秒内未恢复健康，请检查容器日志" >&2
        exit 1
    fi
fi

# 只滚动更新发生变化且原本处于运行状态的服务；用户主动 stop/pause 的服务保持原状态。
DEPLOY_SERVICES=()
# 配置应用与镜像构建分离：脚本更新复用旧镜像，恢复检测到的旧容器仍需纳入更新。
for service in "${RECONCILED_SERVICES[@]}"; do
    case " ${UPDATE_SERVICES[*]} " in
        *" $service "*) ;;
        *) UPDATE_SERVICES+=("$service") ;;
    esac
done
for service in "${UPDATE_SERVICES[@]}"; do
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
else
    UP_ARGS=(--no-build --remove-orphans)
    if [ -z "$IMAGE_PREFIX" ] && [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
        # 本地构建路径（手动部署回退）：镜像名固定不变（ai-eval-platform-api 等），
        # compose 判定容器 config 未变时不 recreate，新代码将不生效（历史事故：
        # api 容器长期跑 2 天前旧镜像）。强制重建以加载本次构建产物。
        UP_ARGS+=(--force-recreate)
        echo "==> 本地构建路径：强制重建 ${DEPLOY_SERVICES[*]} 以加载新镜像"
    fi
    if ! docker compose up -d "${UP_ARGS[@]}" "${DEPLOY_SERVICES[@]}"; then
        echo "警告：业务服务平滑更新异常，尝试安全按序自愈拉起：${DEPLOY_SERVICES[*]}"
        # PostgreSQL 已独立验证健康，自愈阶段只处理本次计划更新的业务应用。
        docker compose stop "${DEPLOY_SERVICES[@]}" 2>/dev/null || true
        docker compose up -d --no-build "${DEPLOY_SERVICES[@]}"
    fi
fi

# 受控 MCP 在 API 调用前必须完成服务端健康检查。为后续 MCP 固化 healthcheck
# 契约：缺少健康检查也会阻断部署，而不是把连接失败留到 Agent 回合才暴露。
for service in "${DEPLOY_SERVICES[@]}"; do
    case " ${MCP_BUILD_SERVICES[*]} " in
        *" $service "*) ;;
        *) continue ;;
    esac
    echo "==> 验证 $service MCP 服务健康状态"
    MCP_READY=0
    for attempt in $(seq 1 30); do
        service_container=$(docker compose ps -q "$service" 2>/dev/null || true)
        if [ -n "$service_container" ]; then
            service_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$service_container" 2>/dev/null || true)
            if [ "$service_health" = "healthy" ]; then
                MCP_READY=1
                break
            fi
            if [ "$service_health" = "unhealthy" ] || [ "$service_health" = "missing" ]; then
                break
            fi
        fi
        sleep 2
    done
    if [ "$MCP_READY" != "1" ]; then
        echo "错误：$service MCP 服务未在 60 秒内通过健康检查" >&2
        exit 1
    fi
done

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

# 先原子持久化镜像引用，再更新成功基准，避免中断留下新基准与旧镜像映射。
# 使用 %q 防止再次 source 时发生 shell 注入；临时文件位于同目录以保证原子替换。
IMAGE_ENV_NEXT=$(mktemp "$APP_DIR/.deploy-images.env.XXXXXX")
{
    for service in "${TRACKED_IMAGE_SERVICES[@]}"; do
        variable="$(service_image_variable "$service")"
        if [ -n "${!variable:-}" ]; then
            printf '%s=%q\n' "$variable" "${!variable}"
        fi
    done
} > "$IMAGE_ENV_NEXT"
mv -f "$IMAGE_ENV_NEXT" "$DEPLOY_IMAGE_ENV"
# 仅在容器更新与镜像映射持久化成功后推进基准。
MARKER_NEXT=$(mktemp "$APP_DIR/.deploy-success-sha.XXXXXX")
printf '%s\n' "$DEPLOY_COMMIT" > "$MARKER_NEXT"
mv -f "$MARKER_NEXT" "$DEPLOY_MARKER"

echo "==> [4/4] 清理未使用的历史镜像"
docker image prune -f --filter "dangling=true" >/dev/null 2>&1 || true
# 高频部署下旧 ghcr tag 快速堆积（曾达 68 个镜像把 dockerd RSS 推到 483MB）；
# 低配机 docker system df 会卡死，改用定向列表：保留所有容器（含手动停止）引用的
# 镜像与 .deploy-images.env 记录的当前镜像引用，其余 ghcr 业务镜像删除。
# 回滚代价为重新 pull（ghcr 保留全部历史 tag），与 2026-08-19 手动清理策略一致。
KEEP_IMAGES=$(docker ps -a --format '{{.Image}}')
for service in "${TRACKED_IMAGE_SERVICES[@]}"; do
    variable="$(service_image_variable "$service")"
    KEEP_IMAGES+=$'\n'"${!variable:-}"
done
docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep '^ghcr.io/rue1218/ai-eval-platform-' \
    | while read -r old_image; do
        grep -qx "$old_image" <<<"$KEEP_IMAGES" || docker rmi "$old_image" >/dev/null 2>&1 || true
    done || true
# 本地构建路径不存在 ghcr 镜像时 grep 无匹配返回 1，必须 `|| true` 避免 pipefail 误报部署失败。
# 构建缓存只清 7 天前的：服务器本地构建（手动部署回退路径）仍可复用近期层，
# 又避免历史缓存无限堆积（2026-08-21 实测曾积到 4.6GB）。
docker builder prune -f --filter "until=168h" >/dev/null 2>&1 || true

echo "==> 部署成功完成！各服务运行状态："
docker compose ps
