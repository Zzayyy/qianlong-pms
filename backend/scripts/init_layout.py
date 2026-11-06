#!/usr/bin/env python3.12
"""初始化项目目录骨架：五类资产目录、VERSION、文档模板与初始全量文档。

用法：
  python init_layout.py [--project-root DIR] [--init-version 1.1.1] [--force]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # 避免在技能目录生成 __pycache__

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from docgen import build_index, create_full  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

DIRECTORIES = (
    "doc",
    "doc/incremental",
    "doc/full",
    "doc/full/archive",
    "doc/templates",
    "backend",
    "backend/src",
    "backend/tests",
    "backend/tests/unit",
    "backend/tests/integration",
    "backend/migrations",
    "backend/scripts",
    "backend/data",
    "backend/data/uploads",
    "frontend",
    "frontend/src",
    "backups",
)
DEFAULT_VERSION = "1.1.1"
KEEP_FILE = ".gitkeep"
TEMPLATE_DIR = SCRIPT_DIR.parents[1] / "doc" / "templates"


class LayoutError(RuntimeError):
    """目录初始化失败。"""


def ensure_directories(project_root: Path) -> list[Path]:
    created: list[Path] = []
    for relative in DIRECTORIES:
        directory = project_root / relative
        if not directory.is_dir():
            directory.mkdir(parents=True)
            created.append(directory)
        keep = directory / KEEP_FILE
        if not keep.exists():
            keep.touch()
    return created


def ensure_version(project_root: Path, init_version: str, force: bool) -> str:
    version_file = project_root / "VERSION"
    if version_file.is_file() and not force:
        return version_file.read_text(encoding="utf-8").strip()
    version_file.write_text(f"{init_version}\n", encoding="utf-8")
    return init_version


def copy_templates(project_root: Path) -> list[Path]:
    target_dir = project_root / "doc" / "templates"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for template in sorted(TEMPLATE_DIR.glob("*.md")):
        target = target_dir / template.name
        if not target.exists():
            shutil.copy2(template, target)
            copied.append(target)
    return copied


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="初始化项目目录骨架")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--init-version", default=DEFAULT_VERSION, help="初始版本号 A.B.C")
    parser.add_argument("--force", action="store_true", help="已存在 VERSION 时也覆盖为初始版本")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root: Path = args.project_root.resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    try:
        created = ensure_directories(project_root)
        version = ensure_version(project_root, args.init_version, args.force)
        copy_templates(project_root)
        full_doc = create_full(project_root, archive=False)
        index = build_index(project_root)
    except (LayoutError, RuntimeError) as exc:
        print(f"[初始化错误] {exc}", file=sys.stderr)
        return 1

    print(f"项目根目录：{project_root}")
    print(f"初始版本：v{version}")
    if created:
        print("新建目录：")
        for directory in created:
            print(f"  + {directory.relative_to(project_root).as_posix()}")
    print(f"全量文档：{full_doc.relative_to(project_root).as_posix()}")
    print(f"增量索引：{index.relative_to(project_root).as_posix()}")
    print("变更流程：backup.py -> 修改 -> version.py bump -> docgen.py incremental/full/index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
