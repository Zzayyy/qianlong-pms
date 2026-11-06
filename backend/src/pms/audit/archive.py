"""审计表按月归档（设计稿 03 §7 / 11 §4：留痕可查、可归档、主表可控）。

策略：
- 按月把过期的审计数据搬入**月份归档表**（`t_sys_operate_log_202509`），搬完删除主表数据
- 归档表用 `CREATE TABLE IF NOT EXISTS ... LIKE` 动态创建（同结构），不在迁移链中
- 每月一个事务：先 `INSERT ... SELECT`，再 `DELETE`，保证不丢不重
- 支持 `dry_run` 预演（只统计不搬移）、支持指定单月归档
- 保留月数由参数 `audit.keepMonths` 控制（默认 12 个月，含当月）

    py -3.12 scripts/archive_audit.py --dry-run        # 预演
    py -3.12 scripts/archive_audit.py --months 6       # 保留 6 个月
    py -3.12 scripts/archive_audit.py --month 2026-09  # 只归档 2026-09
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.logging import get_logger

logger = get_logger(__name__)

# 参与归档的审计表（主表 → 月份归档表）
ARCHIVE_TABLES: Final[tuple[str, ...]] = ("t_sys_operate_log", "t_sys_login_log")

DEFAULT_KEEP_MONTHS: Final[int] = 12


def month_floor(day: date) -> date:
    """取所在月份首日。"""
    return day.replace(day=1)


def add_months(day: date, months: int) -> date:
    """按月加减（日溢出取月末）。"""
    total = (day.year * 12 + day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = _days_in_month(year, month)
    return date(year, month, min(day.day, last_day))


def _days_in_month(year: int, month: int) -> int:
    """当月天数。"""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def cutoff_month(today: date, keep_months: int) -> date:
    """保留最近 `keep_months` 个月（含当月）时的归档分界月份。"""
    keep = max(1, keep_months)
    return add_months(month_floor(today), -(keep - 1))


def pending_months(earliest: date | None, cutoff: date) -> list[date]:
    """列出 `[最早记录月, cutoff)` 区间内需要归档的月份首日。"""
    if earliest is None:
        return []
    months: list[date] = []
    current = month_floor(earliest)
    while current < cutoff:
        months.append(current)
        current = add_months(current, 1)
    return months


def archive_table_name(base_table: str, month: date) -> str:
    """归档表名：`t_sys_operate_log` + 202509 → `t_sys_operate_log_202509`。"""
    return f"{base_table}_{month.strftime('%Y%m')}"


def parse_month(text_value: str) -> date:
    """解析 `YYYY-MM` 为月份首日。"""
    year_text, _, month_text = text_value.partition("-")
    return date(int(year_text), int(month_text), 1)


async def _earliest_month(session: AsyncSession, table: str) -> date | None:
    """查主表最早的 `create_time`（无数据返回 None）。"""
    row = (
        await session.execute(text(f"SELECT MIN(create_time) FROM {table}"))  # noqa: S608
    ).scalar()
    return row.date() if hasattr(row, "date") else None


async def _count_range(session: AsyncSession, table: str, start: date, end: date) -> int:
    """统计某月区间内的行数。"""
    row = (
        await session.execute(
            text(  # noqa: S608
                f"SELECT COUNT(1) FROM {table} WHERE create_time >= :start AND create_time < :end"
            ),
            {"start": start, "end": end},
        )
    ).scalar()
    return int(row or 0)


async def _move_month(session: AsyncSession, table: str, month: date) -> int:
    """单月搬移：建归档表 → INSERT SELECT → DELETE（同一事务）。"""
    end = add_months(month, 1)
    archive_table = archive_table_name(table, month)
    # DDL 会隐式提交，必须先于事务执行
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {archive_table} LIKE {table}"))  # noqa: S608
    await session.commit()

    count = await _count_range(session, table, month, end)
    if count == 0:
        return 0
    await session.execute(
        text(  # noqa: S608
            f"INSERT INTO {archive_table} SELECT * FROM {table} "
            "WHERE create_time >= :start AND create_time < :end"
        ),
        {"start": month, "end": end},
    )
    deleted = (
        await session.execute(
            text(  # noqa: S608
                f"DELETE FROM {table} WHERE create_time >= :start AND create_time < :end"
            ),
            {"start": month, "end": end},
        )
    ).rowcount
    await session.commit()
    logger.info("归档 %s %s：搬移 %s 行（主表删除 %s 行）", table, month, count, deleted)
    return count


async def archive_audit(
    session: AsyncSession,
    *,
    keep_months: int = DEFAULT_KEEP_MONTHS,
    only_month: date | None = None,
    dry_run: bool = False,
    tables: tuple[str, ...] = ARCHIVE_TABLES,
    today: date | None = None,
) -> dict[str, Any]:
    """按月归档审计表，返回 `{"dryRun", "cutoff", "tables": {表: {月: 行数}}, "total"}`。"""
    base_day = today or date.today()
    cutoff = month_floor(only_month) if only_month else cutoff_month(base_day, keep_months)
    report: dict[str, Any] = {
        "dryRun": dry_run,
        "cutoff": cutoff.isoformat(),
        "keepMonths": keep_months,
        "tables": {},
        "total": 0,
    }
    for table in tables:
        months = [month_floor(only_month)] if only_month else pending_months(
            await _earliest_month(session, table), cutoff
        )
        per_month: dict[str, int] = {}
        for month in months:
            end = add_months(month, 1)
            count = await _count_range(session, table, month, end)
            if count == 0:
                continue
            if dry_run:
                per_month[month.strftime("%Y-%m")] = count
            else:
                moved = await _move_month(session, table, month)
                per_month[month.strftime("%Y-%m")] = moved
            report["total"] += count
        if per_month:
            report["tables"][table] = per_month
    return report
