"""验证前端镜像拆分静态资源后路径与内容保持完整。"""

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
if BASH is None and Path("C:/Program Files/Git/bin/bash.exe").is_file():
    BASH = "C:/Program Files/Git/bin/bash.exe"


def file_hashes(root: Path) -> dict[str, str]:
    """按相对路径与内容哈希比较资源，检测丢失、覆盖或路径变化。"""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@unittest.skipUnless(BASH, "静态资源拆分检查需要 Bash")
class BuildAssetsTest(unittest.TestCase):
    """执行 Dockerfile 中实际的资源拆分命令，再模拟两层 COPY 合并。"""

    def check_assets(self, files: dict[str, str]) -> None:
        """用给定构建产物验证最终站点与原产物逐文件一致。"""
        with tempfile.TemporaryDirectory(prefix="deploy-assets-") as directory:
            app = Path(directory)
            dist = app / "dist"
            for name, content in files.items():
                path = dist / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            expected = file_hashes(dist)
            dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
            # 跳过 npm 编译，保留 Dockerfile 的真实拆分逻辑，并映射到隔离目录。
            tail = dockerfile.split("RUN npm run build", 1)[1].split("\n\n", 1)[0]
            command = ("true" + tail).replace("/app", shlex.quote(app.as_posix()))
            if os.name == "nt":
                # Git Bash 非登录 Shell 不保证含 coreutils 路径，显式提供 mkdir/mv。
                command = "export PATH=/usr/bin:$PATH\n" + command
            subprocess.run([BASH, "-c", command], check=True, capture_output=True)

            vendor = app / "vendor-assets"
            self.assertTrue(vendor.is_dir())
            self.assertEqual(
                set(file_hashes(vendor)),
                {Path(name).name for name in files if name.startswith("assets/vendor-")},
            )
            site = app / "site"
            shutil.copytree(vendor, site / "assets")
            shutil.copytree(dist, site, dirs_exist_ok=True)
            self.assertEqual(expected, file_hashes(site))

    def test_vendor_and_application_assets_remain_complete(self) -> None:
        """JS、CSS、字体与入口 HTML 在分层合并后路径、内容完全一致。"""
        self.check_assets({
            "index.html": '<script src="/assets/index-ab.js"></script>',
            "assets/index-ab.js": 'import "./vendor-naive-cd.js"',
            "assets/vendor-naive-cd.js": "export const value = 1",
            "assets/vendor-katex-ef.css": "body { color: black }",
            "assets/font-gh.woff2": "font bytes",
            "favicon.svg": "<svg/>",
        })

    def test_build_without_vendor_chunks_still_succeeds(self) -> None:
        """没有 vendor 分包时空层仍可复制，普通资源不丢失。"""
        self.check_assets({"index.html": "entry", "assets/index-ab.js": "app"})


if __name__ == "__main__":
    unittest.main()
