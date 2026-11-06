"""统计指标内核测试（设计稿 08 §2）。"""

from __future__ import annotations

from datetime import date

from pms.report.metrics import (
    ProjectMetric,
    cost_index,
    delay_days,
    earned_value,
    personal_load,
    schedule_index,
    summarize,
    top_delayed,
)


def _metric(**kwargs: object) -> ProjectMetric:
    """构造指标，默认「健康」。"""
    defaults: dict[str, object] = {
        "project_id": 1,
        "project_name": "P1",
        "dept_id": 10,
        "status": "IN_PROGRESS",
        "health": "GREEN",
        "progress": 50.0,
        "spi": 1.0,
        "cpi": 1.0,
        "delay_days": 0,
        "planned_hours": 100.0,
        "actual_hours": 100.0,
    }
    defaults.update(kwargs)
    return ProjectMetric(**defaults)  # type: ignore[arg-type]


def test_earned_value() -> None:
    """EV = 计划工时 × 进度%。"""
    assert earned_value(100, 50) == 50


def test_schedule_and_cost_index() -> None:
    """SPI = EV/PV，CPI = EV/AC；0 值保护为 1.0。"""
    assert schedule_index(100, 80) == 0.8
    assert cost_index(100, 125, 100) == 0.8
    assert schedule_index(0, 0) == 1.0
    assert cost_index(100, 0, 50) == 1.0


def test_delay_days() -> None:
    """延期天数：过期为正，未到期为 0。"""
    today = date(2026, 10, 29)
    assert delay_days(date(2026, 10, 20), today) == 9
    assert delay_days("2026-11-10", today) == 0
    assert delay_days(None, today) == 0


def test_summarize_counts_and_health() -> None:
    """汇总：数量、健康分布、均值、工时。"""
    metrics = [
        _metric(project_id=1, health="GREEN", progress=80, delay_days=0),
        _metric(project_id=2, health="RED", progress=20, delay_days=20),
        _metric(project_id=3, health="YELLOW", status="COMPLETED", progress=100),
    ]
    data = summarize(metrics)
    assert data["projectCount"] == 3
    assert data["delayedCount"] == 1
    assert data["byHealth"] == {"GREEN": 1, "RED": 1, "YELLOW": 1}
    assert data["inProgressCount"] == 2
    assert data["plannedHours"] == 300.0
    assert 0 < float(data["avgProgress"]) <= 100


def test_summarize_empty() -> None:
    """空集合不除零。"""
    data = summarize([])
    assert data["projectCount"] == 0
    assert data["avgSpi"] == 0.0


def test_top_delayed_order() -> None:
    """延期 TopN 按延期天数降序。"""
    metrics = [
        _metric(project_id=1, delay_days=1),
        _metric(project_id=2, delay_days=30),
        _metric(project_id=3, delay_days=9),
    ]
    assert [item.project_id for item in top_delayed(metrics, 2)] == [2, 3]


def test_personal_load_ratio() -> None:
    """个人工时按项目分布与占比。"""
    rows = personal_load([(1, "A", 6), (2, "B", 2)])
    assert rows[0]["ratio"] == 75.0
    assert rows[1]["ratio"] == 25.0
    assert personal_load([]) == []
