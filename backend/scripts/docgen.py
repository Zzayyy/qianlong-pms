#!/usr/bin/env python3.12
"""技术文档生成工具：增量文档、全量文档（含归档）、增量索引。

用法：
  python docgen.py incremental --title "<主题>" [--project-root DIR]
  python docgen.py full        [--project-root DIR] [--no-archive]
  python docgen.py index       [--project-root DIR]

生成物：
  doc/incremental/vA.B.C_YYYYMMDD_<主题>.md
  doc/full/全量技术文档.md            （当前版本的完整说明）
  doc/full/archive/vA.B.C_YYYYMMDD.md （前一版全量文档归档）
  doc/incremental/INDEX.md            （全部增量记录索引）
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

DEFAULT_VERSION = "1.1.1"
FULL_DOC_NAME = "全量技术文档.md"
INCREMENTAL_DIR_NAME = "incremental"
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "doc" / "templates"
INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t ]')
DOC_VERSION_RE = re.compile(r"当前版本：v?(\d+\.\d+\.\d+)")


class DocgenError(RuntimeError):
    """文档生成失败。"""


@dataclass(frozen=True, slots=True)
class IncrementEntry:
    """一条增量文档记录。"""

    version: str
    date: str
    title: str
    path: Path


def read_current_version(project_root: Path) -> str:
    version_file = project_root / "VERSION"
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text
    return DEFAULT_VERSION


def slugify(title: str) -> str:
    cleaned = INVALID_CHARS.sub("_", title).strip().strip(".")
    return cleaned or "变更记录"


def render(template_name: str, version: str, title: str = "") -> str:
    """渲染模板，替换占位符。"""
    template_path = TEMPLATE_DIR / template_name
    if not template_path.is_file():
        raise DocgenError(f"缺少模板文件：{template_path}")
    now = datetime.now()
    text = template_path.read_text(encoding="utf-8")
    return (
        text.replace("{{VERSION}}", version)
        .replace("{{TITLE}}", title)
        .replace("{{DATETIME}}", now.strftime("%Y-%m-%d %H:%M:%S"))
        .replace("{{DATE}}", now.strftime("%Y%m%d"))
        .replace("{{DATE_CN}}", now.strftime("%Y-%m-%d"))
    )


def create_incremental(project_root: Path, title: str) -> Path:
    version = read_current_version(project_root)
    date = datetime.now().strftime("%Y%m%d")
    target = project_root / "doc" / INCREMENTAL_DIR_NAME / f"v{version}_{date}_{slugify(title)}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise DocgenError(f"增量文档已存在：{target}")
    target.write_text(render("incremental.md", version, title), encoding="utf-8")
    return target


def create_full(project_root: Path, *, archive: bool = True) -> Path:
    version = read_current_version(project_root)
    doc_dir = project_root / "doc" / "full"
    doc_dir.mkdir(parents=True, exist_ok=True)
    current = doc_dir / FULL_DOC_NAME

    if archive and current.is_file():
        old_text = current.read_text(encoding="utf-8")
        match = DOC_VERSION_RE.search(old_text)
        old_version = match.group(1) if match else version
        old_date = datetime.fromtimestamp(current.stat().st_mtime).strftime("%Y%m%d")
        archive_dir = doc_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / f"v{old_version}_{old_date}.md"
        suffix = 2
        while target.exists():
            target = archive_dir / f"v{old_version}_{old_date}_{suffix}.md"
            suffix += 1
        current.replace(target)

    current.write_text(render("full.md", version), encoding="utf-8")
    return current


def collect_entries(project_root: Path) -> list[IncrementEntry]:
    inc_dir = project_root / "doc" / INCREMENTAL_DIR_NAME
    if not inc_dir.is_dir():
        return []
    entries: list[IncrementEntry] = []
    for path in inc_dir.glob("v*_*_*.md"):
        match = re.match(r"v([\d.]+)_(\d{8})_(.+)\.md$", path.name)
        if match is None:
            continue
        entries.append(
            IncrementEntry(
                version=match.group(1),
                date=match.group(2),
                title=match.group(3),
                path=path,
            )
        )
    entries.sort(key=lambda entry: (
        tuple(int(part) for part in entry.version.split(".")),
        entry.date,
        entry.title,
    ))
    return entries


def build_index(project_root: Path) -> Path:
    entries = collect_entries(project_root)
    version = read_current_version(project_root)
    lines = [
        "# 增量技术文档索引",
        "",
        f"- 当前版本：v{version}",
        f"- 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 记录总数：{len(entries)}",
        "",
        "| 版本 | 日期 | 主题 | 文档 |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        link = f"[{entry.path.name}](./{entry.path.name})"
        lines.append(f"| v{entry.version} | {entry.date} | {entry.title} | {link} |")
    target = project_root / "doc" / INCREMENTAL_DIR_NAME / "INDEX.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="技术文档生成工具")
    sub = parser.add_subparsers(dest="command", required=True)

    inc = sub.add_parser("incremental", help="生成增量文档骨架")
    inc.add_argument("--title", required=True, help="本次变更主题")
    inc.add_argument("--project-root", type=Path, default=Path.cwd())

    full = sub.add_parser("full", help="归档旧全量文档并生成新的全量文档骨架")
    full.add_argument("--no-archive", action="store_true", help="不归档旧版，直接覆盖")
    full.add_argument("--project-root", type=Path, default=Path.cwd())

    idx = sub.add_parser("index", help="重建增量文档索引")
    idx.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root: Path = args.project_root.resolve()

    try:
        match args.command:
            case "incremental":
                target = create_incremental(project_root, args.title)
            case "full":
                target = create_full(project_root, archive=not args.no_archive)
            case "index":
                target = build_index(project_root)
            case _:  # pragma: no cover - argparse 已约束子命令
                raise DocgenError(f"未知子命令 {args.command!r}")
    except DocgenError as exc:
        print(f"[文档错误] {exc}", file=sys.stderr)
        return 1

    print(f"已生成：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
