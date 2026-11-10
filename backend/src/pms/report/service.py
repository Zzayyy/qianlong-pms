"""统计看板服务：指标计算、日聚合、公司/部门/项目/个人四类看板（设计稿 08）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.project import service as project_service
from pms.project.models import PrjProject, PrjRisk
from pms.project.progress import HealthThresholds, evaluate_health
from pms.report.metrics import (
    ProjectMetric,
    cost_index,
    delay_days,
    personal_load,
    schedule_index,
    summarize,
    top_delayed,
)
from pms.report.models import StProjectDaily, StWorklogDaily
from pms.system.config_service import ConfigService
from pms.worklog import service as worklog_service
from pms.worklog.models import WlItem, WlWorklog
from pms.worklog.rules import workdays_between

_CONFIRMED: Final[str] = "CONFIRMED"

#: 只有进行中的项目才判定健康度；已交付/关闭的项目不再因为延期与日志率被标红
_HEALTH_ACTIVE: Final[frozenset[str]] = frozenset(
    {"APPROVING", "APPROVED", "IN_PROGRESS", "SUSPENDED"}
)
_HEALTH_TERMINAL: Final[frozenset[str]] = frozenset(
    {"COMPLETED", "ACCEPTED", "CLOSED", "TERMINATED"}
)


async def _health_thresholds(config: ConfigService) -> HealthThresholds:
    """读取健康度阈值参数（08 §2.4，全部后台可调）。"""
    return HealthThresholds(
        spi_red=await config.get_float("health.spi.red"),
        spi_yellow=await config.get_float("health.spi.yellow"),
        cpi_yellow=await config.get_float("health.cpi.yellow"),
        delay_red_days=await config.get_int("health.delay.redDays"),
        delay_yellow_days=await config.get_int("health.delay.yellowDays"),
        risk_high_open=await config.get_bool("health.risk.high.open"),
        log_fill_rate_red=await config.get_float("health.logFillRate.red"),
        log_fill_rate_yellow=await config.get_float("health.logFillRate.yellow"),
        open_issue_yellow=await config.get_int("health.openIssue.yellow"),
    )


async def project_metric(session: AsyncSession, project: PrjProject) -> ProjectMetric:
    """计算单个项目指标（进度、SPI/CPI、健康度、风险、变更、填写率）。"""
    tasks = await project_service.list_tasks(session, project.id)
    planned = float(sum(float(task.plan_hours) for task in tasks))
    actual = float(sum(float(task.actual_hours) for task in tasks))
    progress = float(project.progress)
    start_date = project.plan_start
    if start_date is not None and not isinstance(start_date, date):
        start_date = date.fromisoformat(str(start_date))
    spi = schedule_index(planned, progress, project.plan_start, project.plan_end)
    cpi = cost_index(planned, actual, progress)
    delayed = delay_days(project.plan_end)

    # 注意：结果必须立即取值，后续 await 会关闭上一个 Result
    risk_open = int(
        (
            await session.execute(
                select(func.count(PrjRisk.id)).where(
                    PrjRisk.project_id == project.id,
                    PrjRisk.risk_type == "RISK",
                    PrjRisk.status == "OPEN",
                    PrjRisk.deleted == 0,
                )
            )
        ).scalar_one()
    )
    issue_open = int(
        (
            await session.execute(
                select(func.count(PrjRisk.id)).where(
                    PrjRisk.project_id == project.id,
                    PrjRisk.risk_type == "ISSUE",
                    PrjRisk.status == "OPEN",
                    PrjRisk.deleted == 0,
                )
            )
        ).scalar_one()
    )
    from pms.change.models import ChgRequest

    change_count = int(
        (
            await session.execute(
                select(func.count(ChgRequest.id)).where(
                    ChgRequest.project_id == project.id, ChgRequest.deleted == 0
                )
            )
        ).scalar_one()
    )
    fill_rate = await _project_fill_rate(session, project.id, start_date)

    config = ConfigService(session)
    # 未到计划开始日：还没有考核基准，暂按健康处理（否则新立项项目因无日志直接被判红）
    if start_date is not None and date.today() < start_date:
        health = "GREEN"
    else:
        health = evaluate_health(
            spi_value=spi,
            cpi_value=cpi,
            delay_days=delayed,
            high_risk_open=risk_open > 0,
            log_fill_rate=fill_rate,
            open_issue_count=issue_open,
            thresholds=await _health_thresholds(config),
        )
    return ProjectMetric(
        project_id=project.id,
        project_name=project.project_name,
        dept_id=project.dept_id,
        status=project.status,
        health=str(health),
        progress=progress,
        spi=spi,
        cpi=cpi,
        delay_days=delayed,
        planned_hours=planned,
        actual_hours=actual,
        risk_open=risk_open,
        issue_open=issue_open,
        change_count=change_count,
        log_fill_rate=fill_rate,
    )


async def _project_fill_rate(
    session: AsyncSession, project_id: int, started_on: date | None = None
) -> float:
    """项目日志填写率（成员 × 工作日）。

    观测窗口取「近 30 天」与「项目计划开始日」的较晚者：
    否则新立项的项目会因为立项前的空档被算成低填写率而直接判红。
    """
    members = await project_service.list_members(session, project_id)
    if not members:
        return 100.0
    date_to = date.today()
    date_from = date_to - timedelta(days=30)
    if started_on is not None and started_on > date_from:
        date_from = started_on
    if date_from > date_to:
        return 100.0
    date_to_text = date_to.isoformat()
    date_from_text = date_from.isoformat()
    submitted = 0
    for member in members:
        stats = await worklog_service.stats(
            session,
            user_id=member.user_id,
            date_from=date_from_text,
            date_to=date_to_text,
        )
        submitted += int(stats["submittedDays"])
    required = workdays_between(date_from, date_to) * len(members)
    if required <= 0:
        return 100.0
    return round(submitted / required * 100, 2)


async def refresh_project_health(session: AsyncSession, project_id: int) -> str:
    """重算并回写项目健康度（详情打开、日聚合共用）。

    说明：健康度原先只在看板里实时计算，`t_prj_project.health` 一直是默认 GREEN，
    项目列表因此永远显示「健康」。这里显式回写，让列表与看板口径一致。
    """
    project = await project_service.get_project(session, project_id)
    if str(project.status) in _HEALTH_TERMINAL:
        if str(project.health) != "GREEN":
            project.health = "GREEN"
            await session.flush()
        return "GREEN"
    metric = await project_metric(session, project)
    if str(project.health) != metric.health:
        project.health = metric.health
        await session.flush()
    return metric.health


async def project_dashboard(session: AsyncSession, project_id: int) -> dict[str, object]:
    """项目看板：指标 + 阶段进度 + 里程碑 + 风险 Top。"""
    project = await project_service.get_project(session, project_id)
    metric = await project_metric(session, project)
    stages = await project_service.list_stages(session, project_id)
    milestones = await project_service.list_milestones(session, project_id)
    return {
        "metric": _metric_out(metric),
        "stages": [
            {
                "id": stage.id,
                "stageName": stage.stage_name,
                "progress": float(stage.progress),
                "weight": float(stage.weight),
                "planStart": stage.plan_start,
                "planEnd": stage.plan_end,
            }
            for stage in stages
        ],
        "milestones": [
            {
                "id": item.id,
                "name": item.milestone_name,
                "planDate": item.plan_date,
                "actualDate": item.actual_date,
                "status": item.status,
                "delayDays": item.delay_days,
            }
            for item in milestones
        ],
    }


async def dept_dashboard(session: AsyncSession, dept_ids: list[int]) -> dict[str, object]:
    """部门看板：本部门项目汇总 + 延期 Top5。"""
    metrics = await _metrics_of(session, dept_ids)
    return {
        "summary": summarize(metrics),
        "topDelayed": [_metric_out(item) for item in top_delayed(metrics, 5)],
        "projects": [_metric_out(item) for item in metrics],
    }


async def company_dashboard(session: AsyncSession) -> dict[str, object]:
    """公司看板：全量项目汇总 + 部门维度分布。"""
    metrics = await _metrics_of(session, None)
    by_dept: dict[int, int] = {}
    for item in metrics:
        by_dept[item.dept_id] = by_dept.get(item.dept_id, 0) + 1
    return {
        "summary": summarize(metrics),
        "byDept": by_dept,
        "topDelayed": [_metric_out(item) for item in top_delayed(metrics, 10)],
    }


async def personal_summary(
    session: AsyncSession, user_id: int, date_from: str, date_to: str
) -> dict[str, object]:
    """个人看板：工时、项目分布、填写率与及时率。"""
    stats = await worklog_service.stats(
        session, user_id=user_id, date_from=date_from, date_to=date_to
    )
    stmt = (
        select(WlItem.project_id, func.sum(WlItem.hours))
        .join(WlWorklog, WlWorklog.id == WlItem.worklog_id)
        .where(
            WlWorklog.user_id == user_id,
            WlWorklog.status == _CONFIRMED,
            WlWorklog.log_date >= date_from,
            WlWorklog.log_date <= date_to,
            WlItem.deleted == 0,
            WlWorklog.deleted == 0,
        )
        .group_by(WlItem.project_id)
    )
    result = await session.execute(stmt)
    rows = result.all()
    names: dict[int, str] = {}
    for project_id, _hours in rows:
        project = await session.get(PrjProject, project_id)
        names[project_id] = project.project_name if project else "非项目"
    return {
        "stats": stats,
        "byProject": personal_load(
            [(int(pid), names.get(int(pid), "非项目"), float(hours)) for pid, hours in rows]
        ),
    }


async def aggregate_daily(session: AsyncSession, stat_date: str | None = None) -> dict[str, int]:
    """日聚合：写 `t_st_project_daily` 与 `t_st_worklog_daily`（按天幂等覆盖）。"""
    day = stat_date or date.today().isoformat()
    await session.execute(
        delete(StProjectDaily).where(StProjectDaily.stat_date == day)
    )
    projects = await project_service.list_projects(session, 0, 1000)
    count_projects = 0
    for project in projects:
        metric = await project_metric(session, project)
        # 顺带回写项目健康度，列表页才有非默认值（终态项目保持健康）
        if str(project.status) in _HEALTH_ACTIVE and str(project.health) != metric.health:
            project.health = metric.health
        session.add(
            StProjectDaily(
                project_id=metric.project_id,
                dept_id=metric.dept_id,
                stat_date=day,
                progress=metric.progress,
                spi=metric.spi,
                cpi=metric.cpi,
                health=metric.health,
                planned_hours=metric.planned_hours,
                actual_hours=metric.actual_hours,
                delay_days=metric.delay_days,
            )
        )
        count_projects += 1

    await session.execute(
        delete(StWorklogDaily).where(StWorklogDaily.stat_date == day)
    )
    stmt = (
        select(
            WlWorklog.user_id,
            WlWorklog.dept_id,
            WlItem.project_id,
            func.sum(WlItem.hours),
            WlWorklog.is_late,
            WlWorklog.status,
        )
        .join(WlItem, WlItem.worklog_id == WlWorklog.id)
        .where(
            WlWorklog.log_date == day,
            WlWorklog.status == _CONFIRMED,
            WlWorklog.deleted == 0,
            WlItem.deleted == 0,
        )
        .group_by(
            WlWorklog.user_id,
            WlWorklog.dept_id,
            WlItem.project_id,
            WlWorklog.is_late,
            WlWorklog.status,
        )
    )
    rows = (await session.execute(stmt)).all()
    for user_id, dept_id, project_id, hours, is_late, status in rows:
        session.add(
            StWorklogDaily(
                user_id=int(user_id),
                dept_id=int(dept_id),
                project_id=int(project_id),
                stat_date=day,
                hours=float(hours),
                is_late=int(is_late),
                log_status=str(status),
            )
        )
    await session.flush()
    return {"projects": count_projects, "worklogs": len(rows)}


async def _metrics_of(
    session: AsyncSession, dept_ids: list[int] | None
) -> list[ProjectMetric]:
    """按部门（或全部）计算项目指标集合。"""
    stmt = select(PrjProject).where(
        PrjProject.deleted == 0, PrjProject.status != "DRAFT"
    )
    if dept_ids:
        stmt = stmt.where(PrjProject.dept_id.in_(dept_ids))
    result = await session.execute(stmt.order_by(PrjProject.id.desc()).limit(500))
    return [await project_metric(session, project) for project in result.scalars().all()]


def _metric_out(metric: ProjectMetric) -> dict[str, object]:
    """指标出参。"""
    return {
        "projectId": metric.project_id,
        "projectName": metric.project_name,
        "deptId": metric.dept_id,
        "status": metric.status,
        "health": metric.health,
        "progress": round(metric.progress, 2),
        "spi": round(metric.spi, 4),
        "cpi": round(metric.cpi, 4),
        "delayDays": metric.delay_days,
        "plannedHours": round(metric.planned_hours, 2),
        "actualHours": round(metric.actual_hours, 2),
        "riskOpen": metric.risk_open,
        "issueOpen": metric.issue_open,
        "changeCount": metric.change_count,
        "logFillRate": metric.log_fill_rate,
    }
