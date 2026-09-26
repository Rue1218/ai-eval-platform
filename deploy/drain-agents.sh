#!/usr/bin/env bash
# 由 deploy.sh 在同一 shell source；描述符 8 的排他锁持续到部署进程退出。
# 不删除锁文件、不强行取消回合；任一检查失败都阻止容器更新。

stop_idle_legacy_api() {
    # 旧 API 不认识文件锁：在其容器内持有 PG 表锁，封闭“检查空闲后又收到输入”的竞态。
    local api_container=$1 timeout_seconds=$2 started=$SECONDS active code pid input output barrier
    barrier=$(cat "${BASH_SOURCE[0]%/*}/legacy_agent_barrier.py") || return 1
    while true; do
        coproc LEGACY_BARRIER { docker exec -i "$api_container" python -u -c "$barrier"; }
        pid=$LEGACY_BARRIER_PID
        input=${LEGACY_BARRIER[1]}
        output=${LEGACY_BARRIER[0]}
        code=1
        if IFS= read -r -t 15 active <&"$output" && [[ "$active" =~ ^[0-9]+$ ]]; then
            if [ "$active" -eq 0 ]; then
                echo "==> 旧 API 已在数据库屏障内确认空闲，执行首次升级停机"
                # 即使 stop 超时也登记恢复责任，退出时只恢复本次主动停止的原容器。
                LEGACY_API_STOPPED=$api_container
                timeout 35 docker stop --time 20 "$api_container" >/dev/null && code=0
            else
                code=2
            fi
        fi
        # 关闭输入发送 EOF：放弃本次尝试时释放事务，停机成功时避免向已退出进程写管道。
        exec {input}>&-
        exec {output}<&-
        wait "$pid" 2>/dev/null || true
        if [ "$code" -eq 0 ]; then
            return 0
        fi
        if [ "$code" -ne 2 ]; then
            echo "错误：旧 API 首次升级检查或停机失败，未继续更新容器" >&2
            return 1
        fi
        if (( SECONDS - started >= timeout_seconds )); then
            echo "错误：旧 API 仍有 $active 个活动回合或专家运行，本次不停止服务" >&2
            return 1
        fi
        echo "==> 等待旧 API 的 $active 个活动回合或专家运行结束"
        sleep 2
    done
}

restore_legacy_api() {
    # 后续更新失败且旧容器尚未被替换时恢复服务；手动停止的服务没有此标记。
    local running
    [ -n "${LEGACY_API_STOPPED:-}" ] || return 0
    running=$(docker inspect --format '{{.State.Running}}' "$LEGACY_API_STOPPED" 2>/dev/null) || return 0
    if [ "$running" = "false" ]; then
        echo "==> 恢复本次首次升级停止的旧 API"
        docker start "$LEGACY_API_STOPPED" >/dev/null || echo "错误：旧 API 自动恢复失败，需要检查容器状态" >&2
    fi
}

verify_bootstrap_api() {
    # 首次升级必须等新 API 加载准入保护并恢复健康，才能写入成功部署基准。
    local attempt
    [ -n "${LEGACY_API_STOPPED:-}" ] || return 0
    for attempt in $(seq 1 30); do
        # 按文件检查独立准入模块，避免 app.agent.__init__ 冷启动整个 LangGraph/供应商依赖。
        if timeout 15 docker compose exec -T api python -c 'import json, os, runpy, urllib.request; assert callable(runpy.run_path("app/agent/deploy_guard.py")["turn_admission"]); result = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3)); assert result["status"] == "ok" and result["commit"] == os.environ["BUILD_VERSION"]' >/dev/null 2>&1; then
            echo "==> 首次升级后的 API 已加载部署保护并恢复健康"
            return 0
        fi
        sleep 2
    done
    echo "错误：首次升级后的 API 未通过健康与部署保护检查，不推进成功基准" >&2
    return 1
}

drain_agent_turns() {
    local api_container data_root timeout_seconds started active running guard_status=0
    timeout_seconds=${DEPLOY_AGENT_DRAIN_TIMEOUT:-600}
    if ! [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
        echo "错误：DEPLOY_AGENT_DRAIN_TIMEOUT 必须为正整数" >&2
        return 1
    fi
    api_container=$(docker compose ps -q api) || return 1
    # 首次部署或用户已停止 API 时，没有可接收新回合的服务。
    [ -n "$api_container" ] || return 0
    if [[ "$api_container" == *$'\n'* ]]; then
        echo "错误：首次升级与部署准入仅支持单 API 容器" >&2
        return 1
    fi
    running=$(docker inspect --format '{{.State.Running}}' "$api_container") || return 1
    if [ "$running" = "false" ]; then
        return 0
    fi
    [ "$running" = "true" ] || return 1
    # 仅模块明确缺失时进入首次升级；导入故障或 Docker 失败不能当成旧版本放行。
    timeout 15 docker exec "$api_container" python -c 'import pathlib, runpy, sys; path = pathlib.Path("app/agent/deploy_guard.py"); namespace = runpy.run_path(str(path)) if path.is_file() else sys.exit(3); assert callable(namespace["turn_admission"])' >/dev/null 2>&1 || guard_status=$?
    if [ "$guard_status" != 0 ] && [ "$guard_status" != 3 ]; then
        echo "错误：无法确认 API 部署准入能力，未更新容器" >&2
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
    if [ "$guard_status" = 3 ]; then
        stop_idle_legacy_api "$api_container" "$timeout_seconds"
        return $?
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
