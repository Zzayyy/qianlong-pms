"""工作日志规则测试（设计稿 07 §3 / §4 / §9）。"""

from __future__ import annotations

from datetime import date

from pms.worklog.rules import (
    HoursLimits,
    WorklogStatus,
    check_log_date,
    daily_total_warning,
    fill_rate,
    is_weekend,
    late_days,
    next_worklog_no,
    on_time_rate,
    round_hours,
    submit_status,
    validate_hours,
    workdays_between,
)


def test_worklog_no_format() -> None:
    """日志编号 `WL-2026-000001`（R-LOG-01）。"""
    assert next_worklog_no(date(2026, 10, 29), 1) == "WL-2026-000001"


def test_hours_must_match_items() -> None:
    """明细合计必须等于总工时（R-LOG-03）。"""
    errors = validate_hours(8, 6)
    assert any("不一致" in item for item in errors)


def test_zero_hours_rejected() -> None:
    """工时为 0 不允许提交（R-LOG-04）。"""
    assert any("工时为 0" in item for item in validate_hours(0, 0))


def test_over_max_hours_rejected() -> None:
    """单日超过 24h 拒绝（R-LOG-05）。"""
    assert any("上限" in item for item in validate_hours(25, 25))


def test_over_warn_hours_only_warning() -> None:
    """超过预警阈值只提示不禁止（用户需求：超 8h 告警但不拦截）。"""
    assert validate_hours(10, 10) == []
    assert daily_total_warning(10, 8) != ""
    assert daily_total_warning(8, 8) == ""


def test_backfill_window() -> None:
    """补填窗口：仅允许最近 N 天（默认 5 天），且不允许未来日期。"""
    today = date(2026, 11, 3)
    assert check_log_date(today, 5, today) == []
    assert check_log_date(date(2026, 10, 29), 5, today) == []
    assert any("5 天" in item for item in check_log_date(date(2026, 10, 28), 5, today))
    assert any("未来" in item for item in check_log_date(date(2026, 11, 4), 5, today))


def test_hours_limit_configurable() -> None:
    """阈值可通过参数放宽。"""
    relaxed = HoursLimits(max_per_day=30, warn_per_day=20, step=0.5)
    assert validate_hours(25, 25, relaxed) == []


def test_round_hours_by_step() -> None:
    """工时按步长取整。"""
    assert round_hours(3.2, 0.5) == 3.0
    assert round_hours(3.25, 0.5) == 3.5


def test_late_days_and_status() -> None:
    """补填天数与提交后状态（R-LOG-09）。"""
    today = date(2026, 10, 29)
    assert late_days(today, today) == 0
    assert late_days(date(2026, 10, 27), today) == 2
    assert submit_status(0, 3) is WorklogStatus.SUBMITTED
    assert submit_status(2, 3) is WorklogStatus.SUBMITTED
    assert submit_status(5, 3) is WorklogStatus.PENDING_APPROVE


def test_rates() -> None:
    """填写率与及时率（R-LOG-12）。"""
    assert fill_rate(8, 10) == 80.0
    assert fill_rate(0, 0) == 100.0
    assert on_time_rate(7, 8) == 87.5
    assert on_time_rate(0, 0) == 100.0


def test_workdays_between() -> None:
    """工作日统计（周末不计）。"""
    assert is_weekend(date(2026, 10, 31)) is True
    assert is_weekend(date(2026, 10, 30)) is False
    assert workdays_between(date(2026, 10, 26), date(2026, 10, 30)) == 5
    assert workdays_between(date(2026, 10, 31), date(2026, 10, 26)) == 0
