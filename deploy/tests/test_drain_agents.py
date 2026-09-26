"""执行真实部署等待脚本，Docker 与时间用本地替身避免接触生产。"""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"


@unittest.skipUnless(Path(BASH).exists(), "需要 Bash")
class DrainAgentsTest(unittest.TestCase):
    """覆盖清空、超时、查询失败与旧 API 的失败关闭行为。"""

    def run_drain(self, scenario):
        """独立目录记录检查顺序，source 生产脚本后记录是否进入部署。"""
        with tempfile.TemporaryDirectory(prefix="drain-test-") as directory:
            root = Path(directory)
            script = r'''
set -euo pipefail
export PATH=/usr/bin:$PATH
docker() {
    case "$*" in
        'compose ps -q api')
            if [ "$SCENARIO" != absent ]; then echo unit-api; fi
            if [ "$SCENARIO" = multiple ]; then echo second-api; fi ;;
        *'.State.Running'*)
            [ "$SCENARIO" != inspect_fail ] || return 1
            if [ -f "$TEST_ROOT/stopped" ] || [ "$SCENARIO" = stopped ]; then echo false; else echo true; fi ;;
        inspect*) echo "$TEST_ROOT" ;;
        *settings.data_dir*) [ "$SCENARIO" != wrong_data_dir ] ;;
        'exec -i'*)
            touch "$TEST_ROOT/barrier"
            case "$SCENARIO" in
                old_query_fail) return 1 ;;
                old_malformed) echo invalid ;;
                old_active) echo 1 ;;
                old_wait)
                    if [ -f "$TEST_ROOT/polled" ]; then echo 0; else touch "$TEST_ROOT/polled"; echo 1; fi ;;
                *) echo 0 ;;
            esac
            read -r release || true
            rm "$TEST_ROOT/barrier" ;;
        exec*) case "$SCENARIO" in old*) return 3 ;; probe_fail) return 1 ;; esac ;;
        'stop --time 20 unit-api')
            [ -f "$TEST_ROOT/barrier" ] || return 8
            echo stopped >> "$TEST_ROOT/actions"
            touch "$TEST_ROOT/stopped"
            if [ "$SCENARIO" = old_killed ]; then kill "$LEGACY_BARRIER_PID"; fi
            [ "$SCENARIO" != old_stop_fail ] ;;
        'start unit-api') echo restored >> "$TEST_ROOT/actions" ;;
        'compose exec -T api'*) [ "$SCENARIO" != old_unhealthy ] ;;
        'compose exec -T postgres'*)
            [ "$SCENARIO" != query_fail ] || return 1
            [ "$SCENARIO" != malformed ] || { echo invalid; return; }
            if [ "$SCENARIO" = idle ] || { [ "$SCENARIO" = wait ] && [ -f "$TEST_ROOT/polled" ]; }; then
                echo 0
            else
                touch "$TEST_ROOT/polled"
                echo 1
            fi ;;
        *) return 9 ;;
    esac
}
flock() { [ "$SCENARIO" != lock_busy ] || return 1; echo locked >> "$TEST_ROOT/actions"; }
timeout() { [ "$SCENARIO" != query_hung ] || return 124; shift; "$@"; }
sleep() { SECONDS=$((SECONDS + 2)); }
source SCRIPT_PATH
trap restore_legacy_api EXIT
DEPLOY_AGENT_DRAIN_TIMEOUT=2
drain_agent_turns
if [[ "$SCENARIO" == old* ]]; then
    [ "${LEGACY_API_STOPPED:-}" = unit-api ] || exit 8
    [ "$SCENARIO" != old_deploy_fail ] || exit 1
    # 模拟新容器替换后已启动；退出清理不能再恢复旧容器。
    rm "$TEST_ROOT/stopped"
fi
verify_bootstrap_api
echo deployed >> "$TEST_ROOT/actions"
'''.replace("SCRIPT_PATH", shlex.quote((ROOT / "deploy/drain-agents.sh").as_posix()))
            result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, encoding="utf-8",
                                    env={**os.environ, "TEST_ROOT": root.as_posix(), "SCENARIO": scenario}, timeout=15)
            actions = (root / "actions").read_text() if (root / "actions").exists() else ""
            return result.returncode, actions, result.stdout + result.stderr

    def test_wait_and_idle_can_deploy(self):
        """现有回合清空后才允许容器更新；首次部署可直接创建。"""
        for scenario in ("idle", "wait", "absent", "stopped", "old_idle", "old_wait", "old_killed"):
            with self.subTest(scenario=scenario):
                code, actions, output = self.run_drain(scenario)
                self.assertEqual(code, 0, output)
                self.assertIn("deployed", actions)

    def test_uncertain_or_active_never_deploy(self):
        """查询/屏障失败或仍有活动回合时保留服务，不继续部署。"""
        for scenario in ("timeout", "query_fail", "query_hung", "malformed", "probe_fail", "inspect_fail", "wrong_data_dir", "lock_busy", "multiple", "old_active", "old_query_fail", "old_malformed", "old_stop_fail"):
            with self.subTest(scenario=scenario):
                code, actions, output = self.run_drain(scenario)
                self.assertNotEqual(code, 0, output)
                self.assertNotIn("deployed", actions)
                if scenario != "old_stop_fail":
                    self.assertNotIn("stopped", actions)

    def test_legacy_stop_keeps_database_barrier(self):
        """旧 API 只能在数据库屏障仍持有时停止，并登记自动重启责任。"""
        code, actions, output = self.run_drain("old_idle")
        self.assertEqual(code, 0, output)
        self.assertLess(actions.index("stopped"), actions.index("deployed"))
        self.assertNotIn("restored", actions)

    def test_failed_bootstrap_restores_original_container(self):
        """停机失败及停机后的部署失败都恢复本次停止的原容器。"""
        for scenario in ("old_stop_fail", "old_deploy_fail"):
            code, actions, output = self.run_drain(scenario)
            self.assertNotEqual(code, 0, output)
            self.assertIn("restored", actions)

    def test_unhealthy_new_api_does_not_mark_success(self):
        """新 API 未恢复健康或缺少部署保护时不能把首次升级标记为成功。"""
        code, actions, output = self.run_drain("old_unhealthy")
        self.assertNotEqual(code, 0, output)
        self.assertNotIn("deployed", actions)

    def test_drain_precedes_first_container_update(self):
        """所有部署路径共用的等待入口必须位于第一次容器变更之前。"""
        script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
        self.assertLess(script.index("\ndrain_agent_turns\n"), script.index("docker compose up"))
        self.assertLess(script.index("\ndrain_agent_turns\n"), script.index("docker compose stop"))
        self.assertLess(script.index("\nverify_bootstrap_api\n"), script.index('mv -f "$MARKER_NEXT"'))
