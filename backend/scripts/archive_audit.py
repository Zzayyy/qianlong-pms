"""命令行入口：审计表按月归档。

    py -3.12 scripts/archive_audit.py --dry-run          # 预演（不写库）
    py -3.12 scripts/archive_audit.py                    # 按默认保留 12 个月归档
    py -3.12 scripts/archive_audit.py --months 6         # 保留 6 个月
    py -3.12 scripts/archive_audit.py --month 2026-09    # 只归档指定月份
    py -3.12 scripts/archive_audit.py --list             # 列出已生成的归档表
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pms.audit.archive import (  # noqa: E402
    ARCHIVE_TABLES,
    DEFAULT_KEEP_MONTHS,
    archive_audit,
    parse_month,
)
from pms.core.database import dispose_engine, get_session_factory  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(description="PMS 审计表按月归档")
    parser.add_argument(
        "--months", type=int, default=DEFAULT_KEEP_MONTHS, help="保留最近 N 个月（含当月）"
    )
    parser.add_argument("--month", metavar="YYYY-MM", help="只归档指定月份，忽略 --months")
    parser.add_argument("--dry-run", action="store_true", help="预演：只统计不搬移")
    parser.add_argument("--list", action="store_true", help="列出已有归档表与行数")
    return parser


async def list_archives() -> int:
    """列出归档表及其行数。"""
    from sqlalchemy import text

    factory = get_session_factory()
    try:
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT table_name, table_rows FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name LIKE 't_sys_%_2%' "
                        "ORDER BY table_name"
                    )
                )
            ).all()
    finally:
        await dispose_engine()
    if not rows:
        print("暂无归档表")
        return 0
    print("归档表：")
    for name, table_rows in rows:
        print(f"  {name:<34} {table_rows} 行")
    return 0


async def run(months: int, month_text: str, dry_run: bool) -> int:
    """执行归档并返回退出码。"""
    only_month = parse_month(month_text) if month_text else None
    factory = get_session_factory()
    try:
        async with factory() as session:
            report = await archive_audit(
                session,
                keep_months=months,
                only_month=only_month,
                dry_run=dry_run,
            )
    finally:
        await dispose_engine()
    mode = "预演" if dry_run else "已归档"
    print(f"保留月数：{report['keepMonths']}　分界月份：{report['cutoff']}　模式：{mode}")
    if not report["tables"]:
        print("无需归档的数据")
        return 0
    for table, per_month in report["tables"].items():
        detail = "，".join(f"{month} {count} 行" for month, count in per_month.items())
        print(f"  {table}：{detail}")
    print(f"合计 {report['total']} 行；涉及主表：{', '.join(ARCHIVE_TABLES)}")
    return 0


def main() -> int:
    """命令行主流程。"""
    args = build_parser().parse_args()
    if args.list:
        return asyncio.run(list_archives())
    return asyncio.run(run(args.months, args.month, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
