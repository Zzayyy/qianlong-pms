#!/usr/bin/env python3.12
"""项目版本号 A.B.C 管理工具。

规则：
  * 每段取值 1..999，最小值为 1，不存在 0；
  * 常规修改递增 C；C 溢出后 C 复位为 1 并递增 B；B 溢出后复位并递增 A；
  * 递增 A 属主版本变更，必须显式传入 --allow-major 与 --reason，否则拒绝执行。

用法：
  python version.py show [--project-root DIR]
  python version.py bump [--level patch|minor|major] [--allow-major] [--reason TEXT] [--dry-run]
  python version.py set 2.1.1 [--allow-major] [--reason TEXT]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

MIN_SEGMENT = 1
MAX_SEGMENT = 999
DEFAULT_VERSION = "1.1.1"
VERSION_FILE_NAME = "VERSION"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


class VersionError(RuntimeError):
    """版本号解析或递增失败。"""


@dataclass(frozen=True, slots=True, order=True)
class Version:
    """三端版本号，各端取值 1..999。"""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for name, value in (("A", self.major), ("B", self.minor), ("C", self.patch)):
            if not MIN_SEGMENT <= value <= MAX_SEGMENT:
                raise VersionError(f"版本段 {name}={value} 超出范围 {MIN_SEGMENT}..{MAX_SEGMENT}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> Version:
        parts = text.strip().split(".")
        if len(parts) != 3:
            raise VersionError(f"版本号格式必须为 A.B.C，实际为 {text!r}")
        try:
            segments = tuple(int(part) for part in parts)
        except ValueError as exc:  # pragma: no cover - 入参来自命令行
            raise VersionError(f"版本号 {text!r} 含非数字段") from exc
        return cls(segments[0], segments[1], segments[2])

    def _carry(self, major: int, minor: int, patch: int) -> Version:
        if patch > MAX_SEGMENT:
            patch, minor = MIN_SEGMENT, minor + 1
        if minor > MAX_SEGMENT:
            minor, major = MIN_SEGMENT, major + 1
        if major > MAX_SEGMENT:
            raise VersionError(
                f"主版本号 A 已达上限 {MAX_SEGMENT}，无法继续递增；请归档历史版本后另起新项目"
            )
        return Version(major, minor, patch)

    def bump(self, level: str = "patch") -> Version:
        """按级别递增，进位处理在 _carry 中完成。"""
        match level:
            case "patch":
                return self._carry(self.major, self.minor, self.patch + 1)
            case "minor":
                return self._carry(self.major, self.minor + 1, MIN_SEGMENT)
            case "major":
                return self._carry(self.major + 1, MIN_SEGMENT, MIN_SEGMENT)
            case _:  # pragma: no cover - argparse 已约束取值
                raise VersionError(f"未知递增级别 {level!r}")


def find_version_file(project_root: Path) -> Path:
    return project_root / VERSION_FILE_NAME


def read_version(project_root: Path) -> Version:
    path = find_version_file(project_root)
    if not path.is_file():
        raise VersionError(
            f"未找到 {path}；请先执行 scripts/init_layout.py 初始化项目，或手动写入初始版本 {DEFAULT_VERSION}"
        )
    return Version.parse(path.read_text(encoding="utf-8"))


def write_version(project_root: Path, version: Version) -> None:
    path = find_version_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{version}\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="项目版本号 A.B.C 管理工具")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="项目根目录")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="打印当前版本号")

    bump = sub.add_parser("bump", help="递增版本号")
    bump.add_argument("--level", choices=("patch", "minor", "major"), default="patch")
    bump.add_argument("--allow-major", action="store_true", help="授权提升主版本号 A")
    bump.add_argument("--reason", default="", help="主版本变更理由（提升 A 时必填）")
    bump.add_argument("--dry-run", action="store_true", help="只打印结果，不写入 VERSION")

    set_cmd = sub.add_parser("set", help="直接设置版本号")
    set_cmd.add_argument("value", help="形如 1.2.3")
    set_cmd.add_argument("--allow-major", action="store_true", help="授权提升主版本号 A")
    set_cmd.add_argument("--reason", default="", help="主版本变更理由（提升 A 时必填）")
    return parser


def guard_major(current: Version, target: Version, *, allow_major: bool, reason: str) -> None:
    """提升 A 必须经过用户明确授权。"""
    if target.major <= current.major:
        return
    if not allow_major:
        raise VersionError(
            f"本次变更会把主版本号 A 从 {current} 提升到 {target}。"
            "主版本变更必须先获得用户明确告知与授权，"
            '确认后追加 --allow-major --reason "<理由>" 重新执行；未获授权时禁止执行。'
        )
    if not reason.strip():
        raise VersionError("提升主版本号 A 时必须通过 --reason 说明理由")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.project_root.resolve()

    try:
        match args.command:
            case "show":
                print(read_version(root))
                return 0

            case "bump":
                current = read_version(root)
                target = current.bump(args.level)
                guard_major(current, target, allow_major=args.allow_major, reason=args.reason)
                if args.dry_run:
                    print(f"{current} -> {target}（未写入）")
                    return 0
                write_version(root, target)
                print(f"{current} -> {target}")
                return 0

            case "set":
                current = read_version(root)
                target = Version.parse(args.value)
                guard_major(current, target, allow_major=args.allow_major, reason=args.reason)
                write_version(root, target)
                print(f"{current} -> {target}")
                return 0

            case _:  # pragma: no cover - argparse 已约束子命令
                raise VersionError(f"未知子命令 {args.command!r}")
    except VersionError as exc:
        print(f"[版本错误] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
