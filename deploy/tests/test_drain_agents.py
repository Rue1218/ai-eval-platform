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
        'compose ps -q api') if [ "$SCENARIO" != absent ]; then echo unit-api; fi ;;
        *'.State.Running'*) [ "$SCENARIO" != inspect_fail ] || return 1; echo true ;;
        inspect*) echo "$TEST_ROOT" ;;
        *settings.data_dir*) [ "$SCENARIO" != wrong_data_dir ] ;;
        exec*) [ "$SCENARIO" != old ] ;;
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
DEPLOY_AGENT_DRAIN_TIMEOUT=2
drain_agent_turns
echo deployed >> "$TEST_ROOT/actions"
'''.replace("SCRIPT_PATH", shlex.quote((ROOT / "deploy/drain-agents.sh").as_posix()))
            result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, encoding="utf-8",
                                    env={**os.environ, "TEST_ROOT": root.as_posix(), "SCENARIO": scenario}, timeout=15)
            actions = (root / "actions").read_text() if (root / "actions").exists() else ""
            return result.returncode, actions, result.stdout + result.stderr

    def test_wait_and_idle_can_deploy(self):
        """现有回合清空后才允许容器更新；首次部署可直接创建。"""
        for scenario in ("idle", "wait", "absent"):
            with self.subTest(scenario=scenario):
                code, actions, output = self.run_drain(scenario)
                self.assertEqual(code, 0, output)
                self.assertIn("deployed", actions)

    def test_uncertain_or_active_never_deploy(self):
        """不能查询、超时或旧 API 未支持准入屏障时一律保留旧容器。"""
        for scenario in ("timeout", "query_fail", "query_hung", "malformed", "old", "inspect_fail", "wrong_data_dir", "lock_busy"):
            with self.subTest(scenario=scenario):
                code, actions, output = self.run_drain(scenario)
                self.assertNotEqual(code, 0, output)
                self.assertNotIn("deployed", actions)

    def test_drain_precedes_first_container_update(self):
        """所有部署路径共用的等待入口必须位于第一次容器变更之前。"""
        script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
        self.assertLess(script.index("\ndrain_agent_turns\n"), script.index("docker compose up"))
        self.assertLess(script.index("\ndrain_agent_turns\n"), script.index("docker compose stop"))
