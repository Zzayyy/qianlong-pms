"""进度与健康度计算测试（设计稿 05 §6、08 §2）。"""

from __future__ import annotations

from pms.project.progress import (
    HealthThresholds,
    StageProgress,
    TaskProgress,
    cpi,
    evaluate_health,
    normalize,
    project_progress,
    spi,
    stage_progress,
)


def test_normalize_weights() -> None:
    """权重归一化；全 0 时等权。"""
    assert sum(normalize([1, 1, 2])) == 1.0
    assert normalize([0, 0]) == [1.0, 1.0]


def test_stage_progress_weighted() -> None:
    """阶段进度按任务权重加权。"""
    value = stage_progress(
        [TaskProgress(weight=3, progress=100), TaskProgress(weight=1, progress=0)]
    )
    assert value == 75.0


def test_project_progress_weighted() -> None:
    """项目进度按阶段权重加权。"""
    value = project_progress(
        [StageProgress(weight=1, progress=50), StageProgress(weight=1, progress=100)]
    )
    assert value == 75.0


def test_empty_progress() -> None:
    """无阶段/任务时进度为 0。"""
    assert project_progress([]) == 0.0
    assert stage_progress([]) == 0.0


def test_spi_cpi() -> None:
    """SPI / CPI 计算与 0 值保护。"""
    assert spi(80, 100) == 0.8
    assert cpi(90, 100) == 0.9
    assert spi(0, 0) == 1.0
    assert cpi(0, 0) == 1.0


def test_health_red_by_spi() -> None:
    """SPI 低于红线判红。"""
    assert (
        evaluate_health(
            spi_value=0.75,
            cpi_value=1.0,
            delay_days=0,
            high_risk_open=False,
            log_fill_rate=100,
            open_issue_count=0,
            thresholds=HealthThresholds(),
        )
        == "RED"
    )


def test_health_yellow_by_log_fill_rate() -> None:
    """日志填写率低于黄线判黄。"""
    assert (
        evaluate_health(
            spi_value=1.0,
            cpi_value=1.0,
            delay_days=0,
            high_risk_open=False,
            log_fill_rate=70,
            open_issue_count=0,
            thresholds=HealthThresholds(),
        )
        == "YELLOW"
    )


def test_health_green() -> None:
    """全部达标判绿。"""
    assert (
        evaluate_health(
            spi_value=1.0,
            cpi_value=1.0,
            delay_days=0,
            high_risk_open=False,
            log_fill_rate=95,
            open_issue_count=1,
            thresholds=HealthThresholds(),
        )
        == "GREEN"
    )


def test_health_thresholds_configurable() -> None:
    """阈值可调：放宽后同一指标由红变绿。"""
    relaxed = HealthThresholds(spi_red=0.5, spi_yellow=0.7, delay_red_days=60)
    assert (
        evaluate_health(
            spi_value=0.75,
            cpi_value=1.0,
            delay_days=0,
            high_risk_open=False,
            log_fill_rate=100,
            open_issue_count=0,
            thresholds=relaxed,
        )
        == "GREEN"
    )
