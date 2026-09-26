"""执行部署内的真实 Python 探测，确保不会重复初始化完整 Agent 图。"""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ProbeAgentGuardTest(unittest.TestCase):
    """用会抛异常的 Agent 包初始化器验证探测隔离及健康判断。"""

    def probe(self, kind, *, missing=False, health=None, broken=False):
        """执行生产 Shell 中的原样探测，仅替换 HTTP 响应和无关依赖。"""
        lines = (ROOT / "deploy/drain-agents.sh").read_text(encoding="utf-8").splitlines()
        marker = "guard_status=$?" if kind == "capability" else "result = json.load"
        command = shlex.split(next(line for line in lines if marker in line))
        code = command[command.index("-c") + 1]
        with tempfile.TemporaryDirectory(prefix="guard-probe-") as directory:
            root = Path(directory)
            agent = root / "app/agent"
            agent.mkdir(parents=True)
            (root / "app/__init__.py").write_text("", encoding="utf-8")
            (root / "app/errors.py").write_text("AppError = Exception\nErrorCode = object\n", encoding="utf-8")
            (agent / "__init__.py").write_text('raise RuntimeError("must not initialize Agent graph")\n', encoding="utf-8")
            if not missing:
                shutil.copyfile(ROOT / "backend/api/app/agent/deploy_guard.py", agent / "deploy_guard.py")
            if broken:
                (agent / "deploy_guard.py").write_text('raise RuntimeError("broken guard")\n', encoding="utf-8")
            response = json.dumps(health or {"status": "ok", "commit": "test-sha"})
            wrapper = "import io, sys, urllib.request; urllib.request.urlopen = lambda *a, **k: io.StringIO(sys.argv[2]); exec(sys.argv[1])"
            return subprocess.run(
                [sys.executable, "-c", wrapper, code, response], cwd=root,
                env={**os.environ, "BUILD_VERSION": "test-sha", "PYTHONPATH": str(root)},
                capture_output=True, text=True, timeout=10,
            )

    def test_capability_does_not_initialize_agent_graph(self):
        """有效准入模块可独立检查，不受重型 Agent 包初始化影响。"""
        result = self.probe("capability")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bootstrap_health_does_not_initialize_agent_graph(self):
        """启动后的健康校验不能在另一进程再次加载完整 Agent 图。"""
        result = self.probe("health")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_guard_is_distinct_from_broken_guard(self):
        """只有模块缺失返回旧版本码，损坏模块必须拒绝部署。"""
        self.assertEqual(self.probe("capability", missing=True).returncode, 3)
        self.assertNotIn(self.probe("capability", broken=True).returncode, (0, 3))
        self.assertNotEqual(self.probe("health", missing=True).returncode, 0)

    def test_unhealthy_or_wrong_version_still_fails(self):
        """轻量化不能放宽健康状态与实际镜像版本的校验。"""
        for health in ({"status": "failed", "commit": "test-sha"}, {"status": "ok", "commit": "old-sha"}):
            with self.subTest(health=health):
                self.assertNotEqual(self.probe("health", health=health).returncode, 0)
