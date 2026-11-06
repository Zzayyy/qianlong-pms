"""进度与指标计算（设计稿 05 §6、08 §2）。

纯函数，权重来自阶段与任务，归一化处理，便于单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Sequence


@dataclass(slots=True, frozen=True)
class TaskProgress:
    """任务进度输入。"""

    weight: float
    progress: float


@dataclass(slots=True, frozen=True)
class StageProgress:
    """阶段进度输入。"""

    weight: float
    progress: float


_PERCENT: Final[float] = 100.0


def normalize(values: Sequence[float]) -> list[float]:
    """归一化权重：全 0 或空时按等权处理。"""
    total = sum(value for value in values if value > 0)
    if total <= 0:
        return [1.0] * len(values) if values else []
    return [value / total for value in values]


def stage_progress(tasks: Sequence[TaskProgress]) -> float:
    """按任务权重计算阶段进度（0~100）。"""
    if not tasks:
        return 0.0
    weights = normalize([task.weight for task in tasks])
    return sum(weight * task.progress for weight, task in zip(weights, tasks, strict=True))


def project_progress(stages: Sequence[StageProgress]) -> float:
    """按阶段权重计算项目进度（0~100）。"""
    if not stages:
        return 0.0
    weights = normalize([stage.weight for stage in stages])
    return sum(weight * stage.progress for weight, stage in zip(weights, stages, strict=True))


def spi(earned_value: float, planned_value: float) -> float:
    """进度绩效指数 SPI = EV / PV；PV 为 0 时返回 1.0（暂无偏差）。"""
    return 1.0 if planned_value <= 0 else earned_value / planned_value


def cpi(earned_value: float, actual_cost: float) -> float:
    """成本绩效指数 CPI = EV / AC；AC 为 0 时返回 1.0。"""
    return 1.0 if actual_cost <= 0 else earned_value / actual_cost


@dataclass(slots=True, frozen=True)
class HealthThresholds:
    """健康度阈值（来自系统参数，禁止硬编码）。"""

    spi_red: float = 0.8
    spi_yellow: float = 0.9
    cpi_yellow: float = 0.9
    delay_red_days: int = 15
    delay_yellow_days: int = 1
    risk_high_open: bool = True
    log_fill_rate_red: float = 60.0
    log_fill_rate_yellow: float = 80.0
    open_issue_yellow: int = 5


def evaluate_health(
    *,
    spi_value: float,
    cpi_value: float,
    delay_days: int,
    high_risk_open: bool,
    log_fill_rate: float,
    open_issue_count: int,
    thresholds: HealthThresholds,
) -> str:
    """项目健康度判定（设计稿 08 §2.4）：先判红，再判黄，其余为绿。"""
    if (
        spi_value < thresholds.spi_red
        or cpi_value < thresholds.cpi_yellow
        or delay_days > thresholds.delay_red_days
        or (thresholds.risk_high_open and high_risk_open)
        or log_fill_rate < thresholds.log_fill_rate_red
    ):
        return "RED"
    if (
        spi_value < thresholds.spi_yellow
        or delay_days > thresholds.delay_yellow_days
        or log_fill_rate < thresholds.log_fill_rate_yellow
        or open_issue_count > thresholds.open_issue_yellow
    ):
        return "YELLOW"
    return "GREEN"
