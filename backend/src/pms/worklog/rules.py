"""工作日志状态与规则（设计稿 07 §3 / §4）。

纯函数实现，便于单元测试；校验返回错误清单，由服务层转成业务异常。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class WorklogStatus(StrEnum):
    """日志状态。"""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_APPROVE = "PENDING_APPROVE"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class RemindType(StrEnum):
    """催办类型。"""

    AUTO = "AUTO"
    MANUAL = "MANUAL"


@dataclass(slots=True, frozen=True)
class HoursLimits:
    """工时限额（参数 `worklog.hours.*`）。"""

    max_per_day: float = 24.0
    warn_per_day: float = 8.0
    step: float = 0.5


NO_PREFIX: str = "WL"


def next_worklog_no(log_date: date, serial: int) -> str:
    """生成日志编号 `WL-2026-000001`（R-LOG-01）。"""
    return f"{NO_PREFIX}-{log_date.year}-{serial:06d}"


def late_days(log_date: date, today: date | None = None) -> int:
    """计算补填天数：`0` 表示当日提交。"""
    base = today or date.today()
    return max((base - log_date).days, 0)


def is_late(days: int) -> bool:
    """是否补填（T+1 及以后）。"""
    return days > 0


def submit_status(days: int, late_max_days: int) -> WorklogStatus:
    """按补填天数决定提交后状态：超期需 PM 审批（R-LOG-09）。"""
    if days > late_max_days:
        return WorklogStatus.PENDING_APPROVE
    return WorklogStatus.SUBMITTED


def check_log_date(
    log_date: date, max_backfill_days: int, today: date | None = None
) -> list[str]:
    """校验可填报日期（补填窗口由 `worklog.backfill.maxDays` 控制）。

    返回错误描述清单：未来日期、超出补填窗口均不允许保存。
    """
    base = today or date.today()
    errors: list[str] = []
    if log_date > base:
        errors.append("不能填写未来日期的日志")
    days = (base - log_date).days
    if max_backfill_days >= 0 and days > max_backfill_days:
        errors.append(
            f"仅允许补填最近 {max_backfill_days} 天内的日志（所选日期为 {days} 天前）"
        )
    return errors


def daily_total_warning(total_hours: float, warn_hours: float) -> str:
    """当日累计工时超过预警阈值时的提示文案（**仅提示，不禁止提交**）。"""
    if warn_hours > 0 and total_hours > warn_hours:
        return (
            f"当日累计工时 {total_hours:g}h，已超过预警阈值 {warn_hours:g}h，"
            "请确认填报是否合理（不影响提交）"
        )
    return ""


def validate_hours(
    total_hours: float,
    item_hours: float,
    limits: HoursLimits | None = None,
) -> list[str]:
    """单条日志工时校验，返回错误描述清单（空列表表示通过）。

    说明：超过 `warn_per_day` 仅做提示（见 `daily_total_warning`），不再阻断提交；
    超过 `max_per_day` 仍按 R-LOG-05 拒绝。
    """
    rule = limits or HoursLimits()
    errors: list[str] = []
    if total_hours <= 0:
        errors.append("工时为 0 的日志不允许提交（R-LOG-04）")
    if abs(total_hours - item_hours) > 1e-6:
        errors.append(f"明细工时合计 {item_hours} 与总工时 {total_hours} 不一致（R-LOG-03）")
    if total_hours > rule.max_per_day:
        errors.append(f"单日工时超过上限 {rule.max_per_day}h（R-LOG-05）")
    return errors


def round_hours(value: float, step: float = 0.5) -> float:
    """按步长取整工时（默认 0.5h，四舍五入而非银行家舍入）。"""
    if step <= 0:
        return value
    return math.floor(value / step + 0.5) * step


def fill_rate(submitted_days: int, required_days: int) -> float:
    """填写率 = 已提交天数 / 应填天数（R-LOG-12）。"""
    if required_days <= 0:
        return 100.0
    return round(submitted_days / required_days * 100, 2)


def on_time_rate(on_time_days: int, submitted_days: int) -> float:
    """及时率 = 当日提交天数 / 已提交天数（R-LOG-12）。"""
    if submitted_days <= 0:
        return 100.0
    return round(on_time_days / submitted_days * 100, 2)


def is_weekend(day: date) -> bool:
    """是否周末（一期以「周末」近似工作日历）。"""
    return day.weekday() >= 5


def workdays_between(start: date, end: date) -> int:
    """统计区间内工作日天数（含首尾）。"""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if not is_weekend(current):
            days += 1
        current += timedelta(days=1)
    return days
