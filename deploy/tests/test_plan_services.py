"""在真实临时 Git 历史中验证增量部署，覆盖移动、共享依赖及失败轮次累积差异。"""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("plan_services", ROOT / "deploy/plan_services.py")
PLANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANNER)


class PlanServicesTest(unittest.TestCase):
    """每例独立仓库，不接触开发仓库历史或生产部署标记。"""

    def setUp(self) -> None:
        """复制真实 Dockerfile，使测试依赖与构建输入保持一致。"""
        self.temp = tempfile.TemporaryDirectory(prefix="deploy-plan-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for source in [ROOT / "frontend/Dockerfile", *(ROOT / "backend").glob("*/Dockerfile")]:
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.git("init", "-q")
        self.git("config", "user.email", "deploy-test@example.invalid")
        self.git("config", "user.name", "Deployment Test")
        self.base = self.commit()

    def git(self, *args: str) -> str:
        """在隔离仓库执行 Git，返回提交与差异所需文本。"""
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE).decode().strip()

    def commit(self) -> str:
        """提交夹具中的改动并返回精确版本。"""
        self.git("add", ".")
        self.git("commit", "-qm", "test fixture")
        return self.git("rev-parse", "HEAD")

    def change(self, path: str, content: str = "changed") -> None:
        """写入用例数据，而不是修改工作区文件。"""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def result(self) -> dict:
        """基于成功基准而非上一个提交生成实际计划。"""
        return PLANNER.plan(self.root, self.base, self.commit())

    def test_documentation_skips_build_and_deploy(self) -> None:
        """顶层规范、docs 和嵌套 README 不触发镜像或容器操作。"""
        for path in ("AGENTS.md", "docs/guide.md", "backend/media_mcp/README.md"):
            self.change(path)
        result = self.result()
        self.assertFalse(result["has_services"])
        self.assertFalse(result["needs_deploy"])

    def test_watch_document_filter_matches_real_git_pathspec(self) -> None:
        """巡检的 Git 排除规则跳过说明文档，但不能跳过工具提示词。"""
        # 从实际 Shell 脚本提取过滤参数，避免测试内维护第二份规则。
        script = (ROOT / "deploy/auto-deploy-watch.sh").read_text(encoding="utf-8")
        block = script.split('&& git diff --quiet "$LAST_DEPLOYED" "$REMOTE_SHA" -- .', 1)[1].split("; then", 1)[0]
        filters = [line.strip().rstrip("\\").strip().strip("'") for line in block.splitlines() if "exclude" in line]
        self.change("docs/guide.md")
        self.change("AGENTS.md")
        self.change("backend/media_mcp/README.md")
        self.commit()
        command = ["git", "diff", "--quiet", self.base, "HEAD", "--", ".", *filters]
        self.assertEqual(subprocess.run(command, cwd=self.root, check=False).returncode, 0)
        self.change("backend/media_mcp/app/SKILL.md")
        self.commit()
        self.assertEqual(subprocess.run(command, cwd=self.root, check=False).returncode, 1)

    def test_api_change_does_not_rebuild_runner(self) -> None:
        """API 修改只构建 API，runner 不再强制加入。"""
        self.change("backend/api/app/main.py")
        self.assertEqual(self.result()["build_services"], ["api"])

    def test_mcp_runtime_prompt_is_not_documentation(self) -> None:
        """工具代码与被 COPY 的 SKILL.md 均属于实际运行时输入。"""
        self.change("backend/media_mcp/app/SKILL.md")
        self.assertEqual(self.result()["build_services"], ["media-mcp"])

    def test_new_mcp_is_discovered(self) -> None:
        """新增工具按既有命名约定自动进入矩阵，无需修改工作流。"""
        self.change("backend/search_mcp/Dockerfile", "FROM python:3.12\nCOPY search_mcp/app /app\n")
        self.change("backend/search_mcp/app/main.py")
        result = self.result()
        self.assertEqual(result["build_services"], ["search-mcp"])
        self.assertEqual(result["matrix"]["include"][0]["context"], "backend")

    def test_shared_dependency_includes_mcp_consumer(self) -> None:
        """共享代码的新增 MCP 消费方也必须重建，不能只硬编码三个核心服务。"""
        path = self.root / "backend/media_mcp/Dockerfile"
        path.write_text(path.read_text() + "\nCOPY shared ./shared\n", encoding="utf-8")
        self.base = self.commit()
        self.change("backend/shared/models.py")
        self.assertEqual(set(self.result()["build_services"]), {"api", "worker", "runner", "media-mcp"})

    def test_deploy_script_reuses_images(self) -> None:
        """部署机制调整只应用配置，未变化 MCP 与 runner 复用不可变镜像。"""
        self.change("deploy/deploy.sh")
        result = self.result()
        self.assertEqual(result["build_services"], [])
        self.assertEqual(result["deploy_services"], result["all_services"])

    def test_compose_build_inputs_fall_back_to_full_build(self) -> None:
        """Compose 可改变任意构建参数，未解析的依赖保守全量处理。"""
        self.change("docker-compose.yml")
        result = self.result()
        self.assertEqual(result["build_services"], result["all_services"])

    def test_failed_commit_is_included_in_next_deploy(self) -> None:
        """跨过失败发布后追加文档，仍须部署尚未成功的业务改动。"""
        self.change("backend/api/app/main.py")
        self.commit()
        self.change("docs/new.md")
        self.assertEqual(self.result()["build_services"], ["api"])

    def test_move_rebuilds_source_and_destination(self) -> None:
        """路径迁移需要同时更新旧服务和新服务，不能仅处理 rename 目标。"""
        self.change("backend/api/app/moved.py")
        self.base = self.commit()
        self.change("backend/worker/app/moved.py")
        (self.root / "backend/api/app/moved.py").unlink()
        self.assertEqual(set(self.result()["build_services"]), {"api", "worker"})

    def test_invalid_baseline_builds_all(self) -> None:
        """首次部署或基准丢失时保留全量初始化能力。"""
        result = PLANNER.plan(self.root, "missing", self.base)
        self.assertEqual(result["build_services"], result["all_services"])
        self.assertGreater(len(result["build_services"]), 5)

    def test_backend_tests_do_not_rebuild_runtime(self) -> None:
        """未被 Dockerfile COPY 的 API 测试不需要制作运行镜像。"""
        self.change("backend/api/tests/test_new.py")
        self.assertFalse(self.result()["needs_deploy"])

    def test_json_copy_and_shared_dockerignore(self) -> None:
        """JSON COPY 及 Docker 上下文过滤规则变动均能命中依赖。"""
        self.change("backend/api/Dockerfile", 'FROM python:3.12\nCOPY ["api/app", "/app"]\n')
        self.base = self.commit()
        inputs = PLANNER.build_inputs(self.root, PLANNER.definitions(self.root)["api"])
        self.assertIn("backend/api/app", inputs)
        self.change("backend/.dockerignore")
        self.assertEqual(set(self.result()["build_services"]), {"api", "worker", "runner", "media-mcp"})


if __name__ == "__main__":
    unittest.main()
