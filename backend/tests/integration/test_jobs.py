"""定时任务测试：催办生成、幂等、日聚合、调度器装配。"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Final

import pytest
from sqlalchemy import delete, select

from pms.core.database import get_session_factory
from pms.jobs import (
    build_scheduler,
    job_aggregate_daily,
    job_archive_audit,
    job_change_sla,
    job_remind_worklogs,
)
from pms.org.models import SysDept, SysUser
from pms.report.models import StProjectDaily, StWorklogDaily
from pms.worklog.models import WlReminder, WlWorklog
from pms.worklog.rules import WorklogStatus

pytestmark = pytest.mark.integration

_SUFFIX: Final[str] = str(int(time.time()) % 100000)


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


async def test_remind_job_tolerates_multiple_logs_per_day() -> None:
    """一人一天多条日志时催办任务不崩（判存在必须容忍多行）。"""
    day = _last_weekday()
    factory = get_session_factory()
    user_id = 0
    dept_id = 0
    try:
        async with factory() as session:
            dept = SysDept(
                parent_id=0,
                dept_name=f"催办部门{_SUFFIX}",
                dept_code=f"JB{_SUFFIX}",
                path="/",
                level=1,
            )
            session.add(dept)
            await session.flush()
            dept_id = dept.id

            user = SysUser(
                username=f"jb_{_SUFFIX}", real_name="催办人", dept_id=dept.id, password_hash="x"
            )
            session.add(user)
            await session.flush()
            user_id = user.id

            # 同一天两条已提交日志：旧实现用 scalar_one_or_none 会抛 MultipleResultsFound
            for index in range(2):
                session.add(
                    WlWorklog(
                        worklog_no=f"WL-JB{_SUFFIX}-{index}",
                        user_id=user.id,
                        dept_id=dept.id,
                        log_type="PROJECT",
                        log_date=day,
                        total_hours=4,
                        content="同日多条日志",
                        status=WorklogStatus.SUBMITTED,
                    )
                )
            await session.commit()

        await job_remind_worklogs(day)

        async with factory() as session:
            mine = await session.execute(
                select(WlReminder.id).where(
                    WlReminder.user_id == user_id,
                    WlReminder.log_date == day,
                    WlReminder.remind_type == "AUTO",
                )
            )
            assert mine.scalars().first() is None, "已提交日志的用户不应再被催办"
    finally:
        async with factory() as session:
            await session.execute(
                delete(WlReminder).where(
                    WlReminder.log_date == day, WlReminder.remind_type == "AUTO"
                )
            )
            if user_id:
                await session.execute(delete(WlWorklog).where(WlWorklog.user_id == user_id))
                await session.execute(delete(SysUser).where(SysUser.id == user_id))
            if dept_id:
                await session.execute(delete(SysDept).where(SysDept.id == dept_id))
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
