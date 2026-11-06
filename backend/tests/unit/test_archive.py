"""审计归档纯函数测试：月份边界、保留期、待归档月份、表名。"""

from __future__ import annotations

from datetime import date

from pms.audit.archive import (
    add_months,
    archive_table_name,
    cutoff_month,
    month_floor,
    parse_month,
    pending_months,
)


def test_month_floor_and_add() -> None:
    """月份取整与按月加减（含月末溢出）。"""
    assert month_floor(date(2026, 10, 30)) == date(2026, 10, 1)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_cutoff_month() -> None:
    """保留 N 个月（含当月）后的分界月份。"""
    today = date(2026, 10, 30)
    assert cutoff_month(today, 12) == date(2025, 11, 1)
    assert cutoff_month(today, 1) == date(2026, 10, 1)
    assert cutoff_month(today, 3) == date(2026, 8, 1)
    assert cutoff_month(today, 0) == date(2026, 10, 1)  # 至少保留当月


def test_pending_months() -> None:
    """待归档月份为 `[最早月, cutoff)`，无数据返回空。"""
    assert pending_months(None, date(2026, 10, 1)) == []
    months = pending_months(date(2026, 7, 15), date(2026, 10, 1))
    assert months == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
    assert pending_months(date(2026, 10, 5), date(2026, 10, 1)) == []


def test_archive_table_name_and_parse() -> None:
    """归档表名后缀为 YYYYMM；`YYYY-MM` 可解析为月份首日。"""
    assert archive_table_name("t_sys_operate_log", date(2026, 9, 1)) == "t_sys_operate_log_202609"
    assert archive_table_name("t_sys_login_log", date(2025, 12, 1)) == "t_sys_login_log_202512"
    assert parse_month("2026-09") == date(2026, 9, 1)
