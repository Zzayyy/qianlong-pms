"""定时任务（设计稿 07 §7 / 08 §3）：日志催办、看板日聚合、变更审批超时提醒。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any, Final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.audit.archive import DEFAULT_KEEP_MONTHS, archive_audit
from pms.audit.lock import DEFAULT_TTL_SECONDS, acquire, release
from pms.common.logging import get_logger
from pms.core.database import get_session_factory
from pms.notice import service as notice_service
from pms.org.models import SysUser
from pms.report import service as report_service
from pms.system.config_service import ConfigService
from pms.worklog import service as worklog_service
from pms.worklog.models import WlReminder, WlWorklog
from pms.worklog.rules import WorklogStatus, is_weekend

logger = get_logger(__name__)

AUDIT_KEEP_MONTHS_KEY: Final[str] = "audit.keepMonths"

_SUBMITTED_STATUSES: Final[list[str]] = [
    WorklogStatus.SUBMITTED,
    WorklogStatus.PENDING_APPROVE,
    WorklogStatus.CONFIRMED,
]

_scheduler: AsyncIOScheduler | None = None


async def run_exclusive(
    lock_name: str,
    func: Callable[[], Awaitable[Any]],
    *,
    enable_key: str = "job.enabled",
    ttl_key: str = "job.lock.ttlSeconds",
) -> Any:
    """多实例去重执行：抢到 `t_sys_job_lock` 的进程才真正执行任务。"""
    factory = get_session_factory()
    async with factory() as session:
        config = ConfigService(session)
        if not await config.get_bool(enable_key):
            logger.info("任务 %s 已关闭（%s=false），跳过", lock_name, enable_key)
            return None
        ttl = await config.get_int(ttl_key) or DEFAULT_TTL_SECONDS
        got = await acquire(session, lock_name, ttl)
    if not got:
        logger.info("任务 %s 由其他实例执行，本实例跳过", lock_name)
        return None
    try:
        return await func()
    finally:
        async with factory() as session:
            await release(session, lock_name)


async def job_remind_worklogs(day: str | None = None, *, notify: bool = False) -> int:
    """日志催办：为「上一工作日未提交日志」的在岗用户生成催办记录（T+1 触发）。

    `notify=True` 时同时写入站内通知；调度器执行时开启，测试/脚本默认只记录催办。
    """
    target = date.fromisoformat(day) if day else date.today() - timedelta(days=1)
    if is_weekend(target):
        logger.info("催办跳过：%s 为非工作日", target)
        return 0
    day_text = target.isoformat()
    factory = get_session_factory()
    count = 0
    async with factory() as session:
        config = ConfigService(session)
        if not await config.get_bool("worklog.remind.enabled"):
            logger.info("日志未填提醒已关闭（worklog.remind.enabled=false）")
            return 0
        users = (await session.execute(
            select(SysUser).where(SysUser.deleted == 0, SysUser.status == "ENABLED")
        )).scalars().all()
        for user in users:
            exists = (
                await session.execute(
                    select(WlWorklog.id).where(
                        WlWorklog.deleted == 0,
                        WlWorklog.user_id == user.id,
                        WlWorklog.log_date == day_text,
                        WlWorklog.status.in_(_SUBMITTED_STATUSES),
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            duplicated = (
                await session.execute(
                    select(WlReminder.id).where(
                        WlReminder.deleted == 0,
                        WlReminder.user_id == user.id,
                        WlReminder.log_date == day_text,
                        WlReminder.remind_type == "AUTO",
                    )
                )
            ).scalar_one_or_none()
            if duplicated is not None:
                continue
            content = f"请补填 {day_text} 的工作日志"
            reminder = await worklog_service.create_reminder(
                session,
                user_id=user.id,
                log_date=day_text,
                remind_type="AUTO",
                content=content,
            )
            if notify:
                await notice_service.create_notice(
                    session,
                    receiver_id=user.id,
                    title="工作日志催办",
                    content=content,
                    notice_type="REMINDER",
                    biz_type="WORKLOG_REMINDER",
                    biz_id=reminder.id,
                )
            count += 1
        await session.commit()
    logger.info("日志催办完成：新增 %s 条（%s）", count, day_text)
    return count


async def job_aggregate_daily(day: str | None = None) -> dict[str, int]:
    """看板日聚合：写项目与人员工时快照（按天幂等覆盖）。"""
    factory = get_session_factory()
    async with factory() as session:
        result = await report_service.aggregate_daily(session, day)
        await session.commit()
    logger.info("日聚合完成：%s", result)
    return result


async def job_change_sla(_session: AsyncSession | None = None) -> int:
    """变更审批超时提醒：统计超过 SLA 仍未审批的节点数量（当前仅记录日志）。"""
    from datetime import datetime

    from pms.change.models import ChgApproval, ChgRequest

    factory = get_session_factory()
    count = 0
    async with factory() as session:
        rows = (
            await session.execute(
                select(ChgApproval, ChgRequest.request_code)
                .join(ChgRequest, ChgRequest.id == ChgApproval.request_id)
                .where(
                    ChgApproval.deleted == 0,
                    ChgApproval.status == "PENDING",
                    ChgRequest.deleted == 0,
                )
            )
        ).all()
        now = datetime.now()
        for approval, request_code in rows:
            created = approval.create_time
            if isinstance(created, datetime) and (now - created).days > approval.sla_days:
                count += 1
                logger.warning(
                    "变更 %s 第 %s 节点（%s）已超 SLA %s 天",
                    request_code,
                    approval.seq,
                    approval.node_role,
                    approval.sla_days,
                )
    logger.info("变更审批超时检查完成：超时节点 %s 个", count)
    return count


async def job_archive_audit(keep_months: int | None = None) -> dict[str, Any]:
    """审计表按月归档：把超出保留期的日志搬入月份归档表。"""
    factory = get_session_factory()
    async with factory() as session:
        config = ConfigService(session)
        months = keep_months or await config.get_int(AUDIT_KEEP_MONTHS_KEY) or DEFAULT_KEEP_MONTHS
        report = await archive_audit(session, keep_months=months)
    logger.info(
        "审计归档完成：搬移 %s 行，涉及 %s 张表",
        report["total"],
        len(report["tables"]),
    )
    return report


async def _remind_exclusive() -> Any:
    """日志催办（带分布式锁，同时推送站内通知）。"""
    return await run_exclusive(
        "worklog_remind", lambda: job_remind_worklogs(notify=True)
    )


async def _aggregate_exclusive() -> Any:
    """看板日聚合（带分布式锁）。"""
    return await run_exclusive("report_aggregate", job_aggregate_daily)


async def _sla_exclusive() -> Any:
    """变更审批超时提醒（带分布式锁）。"""
    return await run_exclusive("change_sla", job_change_sla)


async def _archive_exclusive() -> Any:
    """审计表按月归档（带分布式锁）。"""
    return await run_exclusive("audit_archive", job_archive_audit)


def build_scheduler() -> AsyncIOScheduler:
    """按固定时间创建调度器（不启动）。

    所有任务都经 `run_exclusive` 包装：多实例部署时同一时刻只有一个实例执行。
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        _remind_exclusive,
        CronTrigger(hour=9, minute=0),
        id="worklog_remind",
        name="日志催办（T+1 09:00）",
        replace_existing=True,
    )
    scheduler.add_job(
        _aggregate_exclusive,
        CronTrigger(hour=1, minute=0),
        id="report_aggregate",
        name="看板日聚合（每日 01:00）",
        replace_existing=True,
    )
    scheduler.add_job(
        _sla_exclusive,
        CronTrigger(hour=2, minute=0),
        id="change_sla",
        name="变更审批超时提醒（每日 02:00）",
        replace_existing=True,
    )
    scheduler.add_job(
        _archive_exclusive,
        CronTrigger(day=1, hour=3, minute=0),
        id="audit_archive",
        name="审计表按月归档（每月 1 日 03:00）",
        replace_existing=True,
    )
    return scheduler


def start_scheduler() -> AsyncIOScheduler | None:
    """启动调度器（重复调用安全）。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = build_scheduler()
    if not _scheduler.running:
        _scheduler.start()
        logger.info("定时任务已启动：%s", [job.name for job in _scheduler.get_jobs()])
    return _scheduler


def shutdown_scheduler() -> None:
    """停止调度器。"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")
    _scheduler = None
