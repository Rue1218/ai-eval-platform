#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 备用自动部署巡检脚本（GitHub Actions 用量受限时的服务器侧回退链路）
#
# 背景：
#   主链路为 GitHub Actions CD：Actions 构建 GHCR 镜像后 SSH 触发 deploy/deploy.sh
#   在服务器拉取镜像滚动更新。当 Actions 触发用量上限（分钟/计费额度耗尽）时，
#   主链路停摆、生产更新停滞。本脚本由宝塔面板「计划任务」周期调用：
#   巡检 origin/main 是否有未部署的新提交，发现后在服务器本地构建镜像并平滑部署
#   （deploy/deploy.sh 未传 IMAGE_* 环境变量时自带的本机构建回退路径），
#   完整复用其部署互斥锁、差异构建、PostgreSQL 升级备份与镜像清理能力。
#
# 用法：
#   宝塔计划任务（每 5 分钟）：bash /opt/ai-eval-platform/deploy/auto-deploy-watch.sh
#   手动立即部署一次（忽略模式与"已是最新"判断）：bash .../auto-deploy-watch.sh --force
#
# 模式开关（$APP_DIR/.deploy-mode，未跟踪文件，git reset 不会覆盖）：
#   actions  默认。主链路正常时使用：仅巡检记录待部署提交，不执行部署，
#            避免与 Actions 主链路双写部署基准。
#   local    备用。发现 main 新提交即本地构建部署，不依赖 GitHub Actions。
#   切换启用：echo local > /opt/ai-eval-platform/.deploy-mode
#   回切主链路：echo actions > /opt/ai-eval-platform/.deploy-mode
#
# 可选配置（$APP_DIR/.auto-deploy.env，建议 chmod 600，不入库）：
#   DEPLOY_NOTIFY_WEBHOOK=  企业微信群机器人 Webhook（部署成败均推送；钉钉 text 兼容）
#   API_HEALTH_URL=         健康检查地址（默认 http://127.0.0.1:8000/api/health）
#   WEB_HEALTH_URL=         Web 健康地址（默认 http://127.0.0.1/；宝塔 Nginx 占 80 时改真实端口）
# ============================================================

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH

APP_DIR=${APP_DIR:-/opt/ai-eval-platform}
BRANCH=${BRANCH:-main}
API_HEALTH_URL=${API_HEALTH_URL:-http://127.0.0.1:8000/api/health}
WEB_HEALTH_URL=${WEB_HEALTH_URL:-http://127.0.0.1/}

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
    esac
done

# 宝塔计划任务默认以 root 运行；但 /opt/ai-eval-platform 与 .git 属主是 deploy 用户
# （见 deploy/server-setup.sh），GitHub 部署密钥也在 /home/deploy/.ssh：
# root 直接执行 git fetch/reset 会把仓库对象写成 root 属主、破坏 deploy 身份的主链路部署。
# 因此 root 启动时先修正日志目录属主，再以 deploy 身份降权重入本脚本（幂等防循环）。
WATCH_SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
if [ "$(id -u)" -eq 0 ] && [ "${DEPLOY_WATCH_REEXEC:-0}" != "1" ] && id deploy >/dev/null 2>&1; then
    mkdir -p "$APP_DIR/logs"
    chown -R deploy:deploy "$APP_DIR/logs" 2>/dev/null || true
    exec sudo -u deploy -H env \
        DEPLOY_WATCH_REEXEC=1 APP_DIR="$APP_DIR" BRANCH="$BRANCH" \
        API_HEALTH_URL="$API_HEALTH_URL" WEB_HEALTH_URL="$WEB_HEALTH_URL" \
        bash "$WATCH_SELF" "$@"
fi

LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/auto-deploy.log"
MODE_FILE="$APP_DIR/.deploy-mode"
ENV_FILE="$APP_DIR/.auto-deploy.env"
WATCH_LOCK="$APP_DIR/.auto-deploy.lock"
SUCCESS_MARKER="$APP_DIR/.deploy-success-sha"

mkdir -p "$LOG_DIR"

_log() {
    # 统一 UTC 时间戳写巡检日志；deploy.sh 的构建输出也追加到同一文件
    printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG_FILE"
}

# 日志超 10MB 时仅保留末尾 2000 行，避免计划任务长期运行写爆磁盘
if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    tail -n 2000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

MODE=$(tr -d '[:space:]' < "$MODE_FILE" 2>/dev/null || true)
MODE=${MODE:-actions}
case "$MODE" in
    actions|local) ;;
    *)
        _log "错误：未知部署模式 '$MODE'（$MODE_FILE 仅支持 actions/local），本次跳过"
        exit 1
        ;;
esac

_notify() {
    # 可选通知：企业微信群机器人 text 格式；用 python3 构造 JSON 防注入。
    # 通知失败静默，不影响部署主流程；Webhook 地址只从 env 读取，不写入日志。
    local message=${1:-}
    [ -n "${DEPLOY_NOTIFY_WEBHOOK:-}" ] || return 0
    python3 - "$message" <<'PY' 2>/dev/null | curl -fsS -m 10 \
        -H 'Content-Type: application/json' -d @- "${DEPLOY_NOTIFY_WEBHOOK}" >/dev/null 2>&1 || true
import json, sys
print(json.dumps({"msgtype": "text", "text": {"content": sys.argv[1]}}))
PY
}

# 同一服务器只允许一个巡检进程（部署互斥由 deploy/deploy.sh 的锁兜底）。
# 非阻塞获取：上一轮部署尚未结束时直接跳过本轮，避免任务排队堆积。
exec 8>"$WATCH_LOCK"
if ! flock -n 8; then
    _log "跳过：上一轮备用巡检/部署仍在进行"
    exit 0
fi

cd "$APP_DIR"

# 拉取远端 main 最新提交（服务器已配置 GitHub SSH 部署密钥，与主链路同一通道；
# Actions 用量上限不影响 git 拉取，这是本备用链路成立的前提）
FETCH_OK=0
for attempt in 1 2 3; do
    if git fetch origin "$BRANCH"; then
        FETCH_OK=1
        break
    fi
    _log "警告：git fetch 第 $attempt 次失败，稍后重试"
    sleep $((attempt * 2))
done
if [ "$FETCH_OK" != "1" ]; then
    _log "错误：git fetch 连续 3 次失败，本轮巡检终止（请检查服务器到 GitHub 的 SSH 连通性）"
    _notify "【ai-eval 备用部署】git fetch 连续失败，请检查服务器到 GitHub 的 SSH 连通性"
    exit 1
fi

LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE_SHA=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
if [ -z "$REMOTE_SHA" ]; then
    _log "错误：无法解析 origin/$BRANCH，请确认远端分支存在"
    exit 1
fi

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ] && [ "$FORCE" != "1" ]; then
    _log "巡检正常：mode=$MODE 本地已是最新 ${LOCAL_SHA:0:8}"
    exit 0
fi

if [ "$MODE" != "local" ] && [ "$FORCE" != "1" ]; then
    # actions 模式只提示待部署，不部署（避免与主链路双写部署基准）。
    # 若该日志连续出现而 Actions 又长期没有成功记录，即主链路已停摆，应切换 local。
    _log "待部署：发现 origin/$BRANCH 新提交 ${REMOTE_SHA:0:8}（当前 mode=actions，备用链路未启用，等待 GitHub Actions 部署）"
    exit 0
fi

PREV_SHA=$(cat "$SUCCESS_MARKER" 2>/dev/null || echo "")
_log "开始备用部署：mode=local ${PREV_SHA:0:8} -> ${REMOTE_SHA:0:8}${FORCE:+（手动强制）}"

# 服务器本地构建部署：不传 IMAGE_* 环境变量即走 deploy.sh 既有本机构建回退路径；
# DEPLOY_COMMIT 传入精确提交，deploy.sh 检测目标提交已在本地对象库会跳过重复 fetch，
# 并自动重载当前提交版本的脚本，保证备用链路同样部署最新部署逻辑。
if ! DEPLOY_COMMIT="$REMOTE_SHA" bash "$APP_DIR/deploy/deploy.sh" >>"$LOG_FILE" 2>&1; then
    _log "错误：备用部署失败（deploy.sh 退出非 0），线上保持上一次成功版本 ${PREV_SHA:0:8}"
    _notify "【ai-eval 备用部署】部署失败：${REMOTE_SHA:0:8}，线上保持上一版本 ${PREV_SHA:0:8}，请查看 $LOG_FILE"
    exit 1
fi

# 部署后健康检查：API /api/health 免登录，Web 首页需回 200；容器重建需要缓冲，重试 150 秒
HEALTH_OK=0
for _attempt in $(seq 1 30); do
    if curl -fsS -m 5 "$API_HEALTH_URL" >/dev/null 2>&1 \
        && curl -fsS -m 5 -o /dev/null "$WEB_HEALTH_URL"; then
        HEALTH_OK=1
        break
    fi
    sleep 5
done
if [ "$HEALTH_OK" != "1" ]; then
    _log "错误：部署后 150 秒内健康检查未通过（API=$API_HEALTH_URL Web=$WEB_HEALTH_URL），请排查 docker compose logs"
    _notify "【ai-eval 备用部署】${REMOTE_SHA:0:8} 部署后健康检查失败！回滚命令：cd $APP_DIR && git reset --hard $PREV_SHA && bash deploy/deploy.sh"
    exit 1
fi

_log "部署成功：mode=local 已上线 ${REMOTE_SHA:0:8}（健康检查通过）"
_notify "【ai-eval 备用部署】已上线 ${REMOTE_SHA:0:8}（服务器本地构建，健康检查通过）"
