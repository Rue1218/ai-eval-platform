#!/usr/bin/env bash
# 由 deploy.sh 在同一 shell source；描述符 8 的排他锁持续到部署进程退出。
# 不删除锁文件、不强行取消回合；任一检查失败都阻止容器更新。

drain_agent_turns() {
    local api_container data_root timeout_seconds started active running
    timeout_seconds=${DEPLOY_AGENT_DRAIN_TIMEOUT:-600}
    if ! [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
        echo "错误：DEPLOY_AGENT_DRAIN_TIMEOUT 必须为正整数" >&2
        return 1
    fi
    api_container=$(docker compose ps -q api) || return 1
    # 首次部署或用户已停止 API 时，没有可接收新回合的服务。
    [ -n "$api_container" ] || return 0
    running=$(docker inspect --format '{{.State.Running}}' "$api_container") || return 1
    if [ "$running" = "false" ]; then
        return 0
    fi
    [ "$running" = "true" ] || return 1
    # 首次升级旧版本不能假装已有准入屏障；必须另约维护窗口停止旧 API 后再部署。
    if ! docker exec "$api_container" python -c 'import app.agent.deploy_guard' >/dev/null 2>&1; then
        echo "错误：当前 API 尚无部署准入保护。请在维护窗口确认无活动回合、停止旧 API 后首次升级；本次不重启服务。" >&2
        return 1
    fi
    # 锁路径必须与运行中 API 配置一致，不能仅根据默认挂载猜测。
    if ! docker exec "$api_container" python -c 'from app.config import settings; assert settings.data_dir == "/data"' >/dev/null 2>&1; then
        echo "错误：API 数据目录不符合 /data 部署契约，无法协调回合准入" >&2
        return 1
    fi
    data_root=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$api_container") || return 1
    if [ -z "$data_root" ] || [ ! -d "$data_root" ]; then
        echo "错误：无法确认 API 的共享数据目录，拒绝更新容器" >&2
        return 1
    fi
    exec 8>"$data_root/.agent-deploy.lock" || return 1
    if ! flock -w "$timeout_seconds" 8; then
        echo "错误：等待新回合提交事务退出超时，未更新容器" >&2
        return 1
    fi
    started=$SECONDS
    echo "==> 已暂停新回合准入，等待现有 Agent 回合结束（最多 ${timeout_seconds}s）"
    while true; do
        active=$(timeout 15 docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM agent_runtime_state WHERE active_turn IS NOT NULL"') || {
            echo "错误：无法读取活动回合，未更新容器" >&2
            return 1
        }
        active=${active//$'\r'/}
        if ! [[ "$active" =~ ^[0-9]+$ ]]; then
            echo "错误：活动回合计数无效，未更新容器" >&2
            return 1
        fi
        if [ "$active" -eq 0 ]; then
            echo "==> Agent 回合已清空，开始服务更新"
            return 0
        fi
        if (( SECONDS - started >= timeout_seconds )); then
            echo "错误：仍有 $active 个活动回合，已取消本次部署；不会中断会话" >&2
            return 1
        fi
        echo "==> 等待 $active 个活动回合结束"
        sleep 2
    done
}
