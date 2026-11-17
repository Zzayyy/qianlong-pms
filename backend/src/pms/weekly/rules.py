"""周报规则：周区间、周标签、编号与状态（纯函数，便于单测）。"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum


class WeeklyScope(StrEnum):
    """周报范围。"""

    PROJECT = "PROJECT"
    PERSONAL = "PERSONAL"


class WeeklyStatus(StrEnum):
    """周报状态：AI 生成后待确认 → 确认归档。"""

    GENERATED = "GENERATED"
    CONFIRMED = "CONFIRMED"


class WeeklySource(StrEnum):
    """生成来源。"""

    AUTO = "AUTO"
    MANUAL = "MANUAL"


#: 周报编号前缀：项目周报 / 个人周总结
NO_PREFIX: dict[str, str] = {
    WeeklyScope.PROJECT.value: "PW",
    WeeklyScope.PERSONAL.value: "SW",
}


def week_bounds(anchor: date | None = None) -> tuple[date, date]:
    """返回所在自然周的周一与周日（含首尾）。"""
    base = anchor or date.today()
    start = base - timedelta(days=base.weekday())
    return start, start + timedelta(days=6)


def week_label(start: date) -> str:
    """ISO 周标签，如 `2026-W46`。"""
    iso = start.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def next_report_no(week_start: date, scope: str, serial: int) -> str:
    """生成周报编号，如 `PW-2026-W46-0001`。"""
    prefix = NO_PREFIX.get(scope, "WK")
    return f"{prefix}-{week_label(week_start)}-{serial:04d}"
