"""指标内核（设计稿 08 §2）。

纯函数：不访问数据库，便于单元测试与口径复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True, frozen=True)
class ProjectMetric:
    """单个项目的看板指标。"""

    project_id: int
    project_name: str
    dept_id: int
    status: str
    health: str
    progress: float
    spi: float
    cpi: float
    delay_days: int
    planned_hours: float
    actual_hours: float
    risk_open: int = 0
    issue_open: int = 0
    change_count: int = 0
    log_fill_rate: float = 100.0


def earned_value(planned_hours: float, progress: float) -> float:
    """挣值 EV = 计划工时 × 进度%。"""
    return planned_hours * progress / 100


def schedule_index(planned_hours: float, progress: float) -> float:
    """进度绩效 SPI = EV / PV（PV 取计划工时）。"""
    if planned_hours <= 0:
        return 1.0
    return earned_value(planned_hours, progress) / planned_hours


def cost_index(planned_hours: float, actual_hours: float, progress: float) -> float:
    """成本绩效 CPI = EV / AC（无实际工时按 1.0）。"""
    if actual_hours <= 0:
        return 1.0
    return earned_value(planned_hours, progress) / actual_hours


def delay_days(plan_end: date | str | None, today: date | None = None) -> int:
    """相对计划结束日的延期天数（未到期为 0）。"""
    if plan_end is None:
        return 0
    base = today or date.today()
    end = plan_end if isinstance(plan_end, date) else date.fromisoformat(str(plan_end))
    return max((base - end).days, 0)


def _average(values: list[float]) -> float:
    """均值，空集合返回 0。"""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def summarize(metrics: list[ProjectMetric]) -> dict[str, object]:
    """项目集合汇总：数量、状态/健康分布、均值与风险项。"""
    by_status: dict[str, int] = {}
    by_health: dict[str, int] = {}
    for item in metrics:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_health[item.health] = by_health.get(item.health, 0) + 1
    return {
        "projectCount": len(metrics),
        "inProgressCount": by_status.get("IN_PROGRESS", 0),
        "delayedCount": sum(1 for item in metrics if item.delay_days > 0),
        "byStatus": by_status,
        "byHealth": by_health,
        "avgProgress": round(_average([item.progress for item in metrics]) * 100, 2) / 100,
        "avgSpi": _average([item.spi for item in metrics]),
        "avgCpi": _average([item.cpi for item in metrics]),
        "plannedHours": round(sum(item.planned_hours for item in metrics), 2),
        "actualHours": round(sum(item.actual_hours for item in metrics), 2),
        "riskOpen": sum(item.risk_open for item in metrics),
        "issueOpen": sum(item.issue_open for item in metrics),
        "changeCount": sum(item.change_count for item in metrics),
        "avgLogFillRate": round(
            _average([item.log_fill_rate for item in metrics]) * 100, 2
        )
        / 100,
    }


def top_delayed(metrics: list[ProjectMetric], limit: int = 5) -> list[ProjectMetric]:
    """延期天数最多的项目（看板 TopN）。"""
    return sorted(metrics, key=lambda item: item.delay_days, reverse=True)[:limit]


def personal_load(items: list[tuple[int, str, float]]) -> list[dict[str, object]]:
    """个人工时按项目分布：`(project_id, project_name, hours)`。"""
    total = sum(hours for _, _, hours in items)
    return [
        {
            "projectId": project_id,
            "projectName": name,
            "hours": round(hours, 2),
            "ratio": round(hours / total * 100, 2) if total else 0.0,
        }
        for project_id, name, hours in items
    ]
