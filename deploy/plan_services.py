"""CI 与服务器共用的增量部署计划：按 Dockerfile 输入选择镜像，保留失败提交差异。"""

import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess


def documentation(path: str) -> bool:
    """只排除说明文档；工具目录内的 SKILL.md 等运行时提示词仍参与构建。"""
    return path.startswith("docs/") or (
        "/" not in path and path.endswith(".md")
    ) or PurePosixPath(path).name == "README.md"


def definitions(root: Path) -> dict[str, dict[str, str]]:
    """发现固定业务服务及遵守目录命名约定的动态 MCP 工具服务。"""
    result = {
        "web": {"context": "frontend", "dockerfile": "frontend/Dockerfile"},
        **{
            name: {"context": "backend", "dockerfile": f"backend/{name}/Dockerfile"}
            for name in ("api", "worker", "runner")
        },
        **{
            name: {"context": f"backend/{name}", "dockerfile": f"backend/{name}/Dockerfile"}
            for name in ("lightrag", "stress")
        },
    }
    for dockerfile in sorted((root / "backend").glob("*_mcp/Dockerfile")):
        name = dockerfile.parent.name.removesuffix("_mcp").replace("_", "-") + "-mcp"
        result[name] = {"context": "backend", "dockerfile": dockerfile.relative_to(root).as_posix()}
    return {name: {"service": name, **value} for name, value in result.items()}


def build_inputs(root: Path, definition: dict[str, str]) -> list[str]:
    """读取本地 COPY/ADD 输入；不支持的动态语法保守回退到整个构建上下文。"""
    context = definition["context"]
    inputs = [definition["dockerfile"], context + "/.dockerignore", definition["dockerfile"] + ".dockerignore"]
    content = (root / definition["dockerfile"]).read_text(encoding="utf-8").replace("\\\n", " ")
    for line in content.splitlines():
        command, _, arguments = line.strip().partition(" ")
        if command.upper() not in {"COPY", "ADD"}:
            # RUN bind 挂载可以引入额外源码，保守使用整个上下文，避免漏部署。
            if command.upper() == "RUN" and "--mount=" in arguments and (
                "type=bind" in arguments or "type=" not in arguments
            ):
                inputs.append(context)
            continue
        if arguments.startswith("--from="):
            continue
        try:
            while arguments.startswith("--"):
                _, arguments = arguments.split(None, 1)
            parts = json.loads(arguments) if arguments.startswith("[") else shlex.split(arguments)
            if len(parts) < 2:
                raise ValueError("缺少 COPY 输入")
            for source in parts[:-1]:
                if "$" in source or "<<" in source or ".." in PurePosixPath(source).parts:
                    inputs.append(context)
                elif "://" not in source:
                    inputs.append(str(PurePosixPath(context) / source.lstrip("/")).rstrip("/"))
        except (ValueError, TypeError):
            inputs.append(context)
    return inputs


def matches(path: str, source: str) -> bool:
    """兼容目录、单文件和 COPY 通配符，删除文件也能命中旧输入路径。"""
    return path == source or path.startswith(source + "/") or fnmatch.fnmatchcase(path, source)


def plan(root: Path, base: str, target: str) -> dict:
    """基于上次成功部署到目标提交的完整差异生成构建及更新计划。"""
    services = definitions(root)
    valid = bool(base) and subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0
    if not valid:
        selected = list(services)
        changed = []
        deploy = selected
    else:
        # 禁用 rename 检测，以删除+新增覆盖移动文件的两侧；NUL 分隔兼容空格和换行。
        changed = subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", "-z", base, target], cwd=root,
        ).decode("utf-8").strip("\0").split("\0")
        changed = [path for path in changed if path and not documentation(path)]
        # 每个 Dockerfile 只读取一次，避免大批文件变更时重复解析构建依赖。
        inputs = {name: build_inputs(root, definition) for name, definition in services.items()}
        selected = [
            name for name in services
            if any(matches(path, source) for path in changed for source in inputs[name])
        ]
        # Compose 可能改 build args/context，未解析的构建输入必须全量保守处理。
        if "docker-compose.yml" in changed:
            selected = list(services)
        # 运维脚本变化只重新应用配置，不为未变化的 MCP/runner 制造新镜像。
        deploy = list(services) if any(
            path.startswith("deploy/") and not path.startswith("deploy/tests/") for path in changed
        ) else list(selected)
    return {
        "matrix": {"include": [services[name] for name in selected]},
        "build_services": selected,
        "deploy_services": deploy,
        "all_services": list(services),
        "has_services": bool(selected),
        "needs_deploy": bool(deploy),
    }


def main() -> None:
    """为 Actions 输出矩阵，为 Bash 输出逐行服务名；失败时返回非零退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""))
    parser.add_argument("--target", default=os.environ.get("TARGET_SHA", "HEAD"))
    parser.add_argument("--format", choices=("json", "github", "build", "deploy", "all"), default="json")
    args = parser.parse_args()
    result = plan(Path.cwd(), args.base, args.target)
    if args.format == "github":
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for name in ("matrix", "has_services", "needs_deploy"):
                output.write(f"{name}={json.dumps(result[name], separators=(',', ':'))}\n")
        print(json.dumps(result, ensure_ascii=False))
    elif args.format in {"build", "deploy", "all"}:
        key = {"build": "build_services", "deploy": "deploy_services", "all": "all_services"}[args.format]
        print("\n".join(result[key]))
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
