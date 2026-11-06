#!/usr/bin/env python3.12
"""修改前备份工具：把本次待修改文件按原路径镜像复制到 backups/ 并记录清单。

用法：
  python backup.py <文件或目录> [<文件或目录> ...] [--project-root DIR] [--note "说明"]

备份位置：backups/<YYYYMMDD-HHMMSS>_vA.B.C/
清单文件：该目录下的 manifest.json（含原始路径、SHA-256、大小、时间）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

DEFAULT_VERSION = "1.1.1"
CHUNK_SIZE = 1 << 20


class BackupError(RuntimeError):
    """备份失败。"""


@dataclass(frozen=True, slots=True)
class BackupItem:
    """单条备份记录。"""

    source: str
    target: str
    sha256: str
    size: int


def read_current_version(project_root: Path) -> str:
    """读取当前版本号；缺少 VERSION 文件时回落为默认版本。"""
    version_file = project_root / "VERSION"
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text
    return DEFAULT_VERSION


def iter_files(path: Path) -> Iterator[Path]:
    """展开入参：文件直接产出，目录递归产出其下所有文件。"""
    if path.is_file():
        yield path
        return
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                yield child
        return
    raise BackupError(f"路径不存在：{path}")


def mirror_target(backup_root: Path, source: Path, project_root: Path) -> Path:
    """计算镜像目标路径；项目外的文件统一归入 _external/。"""
    resolved = source.resolve()
    try:
        return backup_root / resolved.relative_to(project_root)
    except ValueError:
        drive = resolved.drive.rstrip(":\\/") or "root"
        return backup_root / "_external" / drive / Path(*resolved.parts[1:]).as_posix()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_files(sources: list[Path], project_root: Path, note: str) -> tuple[Path, list[BackupItem]]:
    """执行备份，返回备份目录与记录列表。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = project_root / "backups" / f"{stamp}_v{read_current_version(project_root)}"
    backup_root.mkdir(parents=True, exist_ok=False)

    items: list[BackupItem] = []
    for raw in sources:
        for source in iter_files(raw):
            target = mirror_target(backup_root, source, project_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            items.append(
                BackupItem(
                    source=source.resolve().as_posix(),
                    target=target.relative_to(backup_root).as_posix(),
                    sha256=sha256_of(source),
                    size=source.stat().st_size,
                )
            )

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": project_root.as_posix(),
        "backup_root": backup_root.relative_to(project_root).as_posix(),
        "version": read_current_version(project_root),
        "note": note,
        "items": [asdict(item) for item in items],
    }
    (backup_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return backup_root, items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="修改前备份工具")
    parser.add_argument("sources", nargs="+", type=Path, help="本次将要修改/删除的文件或目录")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument("--note", default="", help="本次修改说明，写入 manifest.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        print(f"[备份错误] 项目根目录不存在：{project_root}", file=sys.stderr)
        return 1

    sources = [
        source if source.is_absolute() else project_root / source for source in args.sources
    ]
    try:
        backup_root, items = backup_files(sources, project_root, args.note)
    except BackupError as exc:
        print(f"[备份错误] {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:  # pragma: no cover - 时间戳冲突
        print(f"[备份错误] 备份目录已存在：{exc.filename}", file=sys.stderr)
        return 1

    print(f"备份目录：{backup_root}")
    for item in items:
        print(f"  - {item.source} -> {item.target} ({item.size} B, sha256={item.sha256[:16]}…)")
    print(f"共 {len(items)} 个文件，清单：{backup_root / 'manifest.json'}")
    print("下一步：修改文件 → python scripts/version.py bump")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
