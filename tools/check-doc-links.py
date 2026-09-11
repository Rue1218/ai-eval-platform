#!/usr/bin/env python3
"""检查 docs 中引用的仓库内路径是否存在，防止新增失效引用。

用法：
    python tools/check-doc-links.py            # 报告模式（默认，退出码 0）
    python tools/check-doc-links.py --strict   # 严格模式：存在失效引用时退出码 1

设计：只检查形如 `backend/....py|ts|vue|sql` 的仓库内路径引用；
文首带"历史归档/文档维护提示"标注的文档单独归类，便于评估清理进度。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATH_PATTERN = re.compile(r"`(backend/[\w./-]+\.(?:py|ts|vue|sql))`")
ARCHIVE_MARKERS = ("历史归档", "文档维护提示")


def main() -> int:
    strict = "--strict" in sys.argv
    missing: dict[str, list[str]] = {}
    annotated = 0
    for doc in sorted((REPO / "docs").glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        if any(marker in text for marker in ARCHIVE_MARKERS):
            annotated += 1
        bad = sorted({m.group(1) for m in PATH_PATTERN.finditer(text)
                      if not (REPO / m.group(1)).exists()})
        if bad:
            missing[doc.name] = bad

    total = sum(len(v) for v in missing.values())
    for name, paths in missing.items():
        head = ", ".join(paths[:4]) + (" …" if len(paths) > 4 else "")
        print(f"{name}: {len(paths)} 处 -> {head}")
    print(f"\n失效引用 {total} 处，涉及 {len(missing)} 个文档；"
          f"已加历史标注的文档 {annotated} 份。")
    if not total:
        print("全部引用有效 ✓")
    return 1 if (strict and total) else 0


if __name__ == "__main__":
    sys.exit(main())
