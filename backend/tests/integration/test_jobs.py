"""定时任务测试：催办生成、幂等、日聚合、调度器装配。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from pms.core.database import get_session_factory
from pms.jobs import (
    build_scheduler,
    job_aggregate_daily,
    job_aggregate_daily,
    job_archive_audit,
    job_change_sla,
    job_remind_worklogs,
)
from pms.report.models import StProjectDaily, StWorklogDaily
from pms.worklog.models import WlReminder

pytestmark = pytest.mark.integration


def _last_weekday() -> str:
    """取上一个工作日（周一至周五）。"""
    current = date.today() - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current.isoformat()


def test_scheduler_jobs() -> None:
    """调度器装配四个任务（含审计按月归档）。"""
    scheduler = build_scheduler()
    jobs = {job.id: job.name for job in scheduler.get_jobs()}
    assert set(jobs) == {
        "worklog_remind",
        "report_aggregate",
        "change_sla",
        "audit_archive",
    }
    assert "归档" in jobs["audit_archive"]


async def test_remind_job_is_idempotent() -> None:
    """催办按「人 + 日期」幂等，重复执行不重复生成。"""
    day = _last_weekday()
    factory = get_session_factory()
    created: list[int] = []
    try:
        first = await job_remind_worklogs(day)
        second = await job_remind_worklogs(day)
        async with factory() as session:
            rows = await session.execute(
                select(WlReminder.id).where(
                    WlReminder.log_date == day, WlReminder.remind_type == "AUTO"
                )
            )
            created = list(rows.scalars().all())
        assert first > 0, "工作日应为未提交日志的用户生成催办"
        assert second == 0, "重复执行不应重复催办"
        assert len(created) == first
    finally:
        async with factory() as session:
            await session.execute(
                delete(WlReminder).where(
                    WlReminder.log_date == day, WlReminder.remind_type == "AUTO"
                )
            )
            await session.commit()


async def test_aggregate_job_writes_snapshots() -> None:
    """日聚合写入项目快照并支持覆盖。"""
    day = date.today().isoformat()
    factory = get_session_factory()
    result = await job_aggregate_daily(day)
    assert result["projects"] >= 0
    async with factory() as session:
        rows = await session.execute(
            select(StProjectDaily.id).where(StProjectDaily.stat_date == day)
        )
        ids = list(rows.scalars().all())
        logs = await session.execute(
            select(StWorklogDaily.id).where(StWorklogDaily.stat_date == day)
        )
        log_ids = list(logs.scalars().all())
    assert len(ids) == result["projects"]
    assert len(log_ids) == result["worklogs"]
    async with factory() as session:
        await session.execute(delete(StProjectDaily).where(StProjectDaily.stat_date == day))
        await session.execute(delete(StWorklogDaily).where(StWorklogDaily.stat_date == day))
        await session.commit()


async def test_change_sla_job_runs() -> None:
    """变更审批超时检查可安全执行（无待办时返回 0）。"""
    assert await job_change_sla() >= 0


async def test_archive_job_respects_keep_months() -> None:
    """保留期很长时不搬移任何数据，任务返回归档报告。"""
    report = await job_archive_audit(keep_months=120)
    assert report["total"] == 0
    assert report["tables"] == {}
