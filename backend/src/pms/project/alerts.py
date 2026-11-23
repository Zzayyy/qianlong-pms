"""项目风险预警：从进度、里程碑与工作日志里推导「待处理预警」。

口径（与风险台账分开）：
- 预警是**只读计算结果**，每次打开项目详情现算，不落库；
- 只有「转为风险」才写 `t_prj_risk`，并带上 `source=ALERT` + `source_key` 幂等键；
- 「忽略」写 `t_prj_alert_mute`，到期前不再提示同一个 key；
- 已有同 `source_key` 的风险（不论是否关闭）或处于忽略期的 key 不再下发，避免反复打扰；
- 日志类预警只覆盖「未勾风险标记但写了问题」的日志，勾了标记的仍由日志确认时直接落风险表。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.project.models import (
    PrjAlertMute,
    PrjMilestone,
    PrjProject,
    PrjRisk,
    PrjStage,
    PrjTask,
)

#: 预警来源标签（前端直接展示）
SOURCE_LABEL: Final[dict[str, str]] = {
    "PROJECT": "项目延期",
    "STAGE": "阶段延期",
    "MILESTONE": "里程碑逾期",
    "TASK": "任务延期",
    "WORKLOG": "日志问题",
}

#: 等级排序（高风险在前）
LEVEL_ORDER: Final[dict[str, int]] = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

#: 日志问题文本里的高危关键词：命中即按高风险提示
_HIGH_RISK_WORDS: Final[tuple[str, ...]] = (
    "延期",
    "阻塞",
    "卡住",
    "故障",
    "无法",
    "缺口",
    "投诉",
    "事故",
    "失败",
    "停机",
    "数据丢失",
    "人力不足",
    "资源不足",
)

#: 日志问题类预警的回看窗口（天）
_LOG_WINDOW_DAYS: Final[int] = 14
#: 日志问题类预警最多下发条数（避免刷屏）
_LOG_ALERT_LIMIT: Final[int] = 5
#: 任务延期类预警最多下发条数（超期最久的优先）
_TASK_ALERT_LIMIT: Final[int] = 5


@dataclass(frozen=True)
class Alert:
    """一条待处理预警（未落库，转正后才有风险 ID）。"""

    key: str
    source: str
    level: str
    risk_type: str
    title: str
    evidence: str
    owner_id: int = 0
    due_date: str | None = None


def _text(value: object) -> str:
    """日期/编码统一转字符串，空值返回空串。"""
    if value is None:
        return ""
    return str(value)


def _int_of(value: object) -> int:
    """宽松转整数（日志行里的 ID 可能是 int / str / None）。"""
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _overdue_days(due: object, today: date) -> int:
    """相对计划日期的逾期天数；已达成/无日期/未到期返回 0。"""
    text = _text(due)[:10]
    if not text:
        return 0
    try:
        due_date = date.fromisoformat(text)
    except ValueError:
        return 0
    return max((today - due_date).days, 0)


def _level_of(days: int) -> str:
    """延期等级：超过一周按高风险，其余中风险。"""
    return "HIGH" if days >= 7 else "MEDIUM"


def _summary(text: str, limit: int = 40) -> str:
    """单行摘要：去掉换行并截断，用于风险标题。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else f"{flat[:limit]}…"


def log_risk_level(problem: str) -> str:
    """日志问题文本 → 风险等级（关键词命中即高危）。"""
    text = str(problem or "")
    return "HIGH" if any(word in text for word in _HIGH_RISK_WORDS) else "MEDIUM"


def problem_summary(problem: str) -> str:
    """日志问题文本 → 单行摘要（用于风险标题，避免出现整段文本）。"""
    return _summary(problem, 40)


def build_alerts(
    *,
    project: PrjProject,
    stages: Sequence[PrjStage],
    milestones: Sequence[PrjMilestone],
    tasks: Sequence[PrjTask],
    log_problems: Sequence[dict[str, object]] = (),
    today: date | None = None,
) -> list[Alert]:
    """按项目现状推导预警清单（纯函数，便于单测）。

    - 项目超计划结束日未完工
    - 阶段超计划结束日未完成
    - 里程碑逾期未达成
    - 任务超计划结束日未完成
    - 日志写了问题但未勾「风险标记」
    """
    base = today or date.today()
    alerts: list[Alert] = []

    if str(project.status) in {"APPROVED", "IN_PROGRESS", "SUSPENDED"}:
        days = _overdue_days(project.plan_end, base)
        if days > 0:
            alerts.append(
                Alert(
                    key="PROJECT_DELAY",
                    source="PROJECT",
                    level="HIGH" if days >= 7 else "MEDIUM",
                    risk_type="RISK",
                    title=f"项目已超计划结束日 {days} 天",
                    evidence=(
                        f"计划结束 {_text(project.plan_end)}，"
                        f"当前进度 {round(float(project.progress or 0))}%"
                    ),
                    owner_id=int(project.pm_id or 0),
                    due_date=_text(project.plan_end) or None,
                )
            )

    for stage in stages:
        if str(stage.status) in {"DONE", "CANCELLED"}:
            continue
        days = _overdue_days(stage.plan_end, base)
        if days <= 0:
            continue
        alerts.append(
            Alert(
                key=f"STAGE_DELAY:{stage.id}",
                source="STAGE",
                level=_level_of(days),
                risk_type="RISK",
                title=f"阶段「{stage.stage_name}」超期 {days} 天",
                evidence=(
                    f"计划结束 {_text(stage.plan_end)}，"
                    f"当前进度 {round(float(stage.progress or 0))}%"
                ),
                owner_id=int(stage.owner_id or 0),
                due_date=_text(stage.plan_end) or None,
            )
        )

    for milestone in milestones:
        if str(milestone.status) in {"REACHED", "CANCELLED"}:
            continue
        days = _overdue_days(milestone.plan_date, base)
        if days <= 0:
            continue
        alerts.append(
            Alert(
                key=f"MILESTONE_DELAY:{milestone.id}",
                source="MILESTONE",
                level=_level_of(days),
                risk_type="RISK",
                title=f"里程碑「{milestone.milestone_name}」逾期 {days} 天",
                evidence=f"计划日期 {_text(milestone.plan_date)}，尚未标记达成",
                owner_id=int(milestone.owner_id or 0),
                due_date=_text(milestone.plan_date) or None,
            )
        )

    # 任务数量可能很多：只取超期最久的若干条，避免预警面板被同类项刷屏
    task_alerts: list[tuple[int, Alert]] = []
    for task in tasks:
        if str(task.status) in {"DONE", "CANCELLED"}:
            continue
        if float(task.progress or 0) >= 100:
            continue
        days = _overdue_days(task.plan_end, base)
        if days <= 0:
            continue
        task_alerts.append(
            (
                days,
                Alert(
                    key=f"TASK_DELAY:{task.id}",
                    source="TASK",
                    level=_level_of(days),
                    risk_type="RISK",
                    title=f"任务「{task.task_name}」超期 {days} 天",
                    evidence=(
                        f"计划结束 {_text(task.plan_end)}，"
                        f"当前进度 {round(float(task.progress or 0))}%"
                    ),
                    owner_id=int(task.owner_id or 0),
                    due_date=_text(task.plan_end) or None,
                ),
            )
        )
    task_alerts.sort(key=lambda item: item[0], reverse=True)
    alerts.extend(alert for _days, alert in task_alerts[:_TASK_ALERT_LIMIT])

    for row in list(log_problems)[:_LOG_ALERT_LIMIT]:
        problem = str(row.get("problem") or "")
        if not problem.strip():
            continue
        log_date = _text(row.get("logDate"))
        alerts.append(
            Alert(
                key=f"WORKLOG_PROBLEM:{_text(row.get('id'))}",
                source="WORKLOG",
                level=log_risk_level(problem),
                risk_type="ISSUE",
                title=f"日志反映问题：{_summary(problem)}",
                evidence=(
                    f"{log_date} 日志（{_text(row.get('worklogNo'))}）："
                    f"{_summary(problem, 80)}"
                ),
                owner_id=_int_of(row.get("userId")),
                due_date=None,
            )
        )

    alerts.sort(
        key=lambda item: (LEVEL_ORDER.get(item.level, 3), item.source, item.title)
    )
    return alerts


async def _converted_keys(session: AsyncSession, project_id: int) -> set[str]:
    """已经转正过的预警键（存在同 source_key 的风险即视为已处理）。"""
    rows = await session.execute(
        select(PrjRisk.source_key).where(
            PrjRisk.project_id == project_id,
            PrjRisk.deleted == 0,
            PrjRisk.source_key != "",
        )
    )
    return {str(key) for key in rows.scalars().all() if key}


async def _muted_keys(session: AsyncSession, project_id: int, today: date) -> set[str]:
    """处于忽略期内的预警键。"""
    rows = await session.execute(
        select(PrjAlertMute.alert_key, PrjAlertMute.muted_until).where(
            PrjAlertMute.project_id == project_id,
            PrjAlertMute.deleted == 0,
        )
    )
    keys: set[str] = set()
    for key, until in rows.all():
        if until is None or _text(until)[:10] >= today.isoformat():
            keys.add(str(key))
    return keys


async def list_alerts(
    session: AsyncSession, project_id: int, today: date | None = None
) -> list[Alert]:
    """计算项目待处理预警（已转正/已忽略的不再返回）。"""
    base = today or date.today()
    project = await session.get(PrjProject, project_id)
    if project is None or project.deleted:
        return []

    stages = list(
        (
            await session.execute(
                select(PrjStage).where(
                    PrjStage.project_id == project_id, PrjStage.deleted == 0
                )
            )
        )
        .scalars()
        .all()
    )
    milestones = list(
        (
            await session.execute(
                select(PrjMilestone).where(
                    PrjMilestone.project_id == project_id, PrjMilestone.deleted == 0
                )
            )
        )
        .scalars()
        .all()
    )
    tasks = list(
        (
            await session.execute(
                select(PrjTask).where(PrjTask.project_id == project_id, PrjTask.deleted == 0)
            )
        )
        .scalars()
        .all()
    )

    # 日志问题：只取近 N 天、已提交/已确认、写了问题但没勾风险标记的日志
    from pms.worklog.models import WlWorklog

    since = base - timedelta(days=_LOG_WINDOW_DAYS)
    rows = await session.execute(
        select(
            WlWorklog.id,
            WlWorklog.worklog_no,
            WlWorklog.log_date,
            WlWorklog.problem,
            WlWorklog.user_id,
        )
        .where(
            WlWorklog.project_id == project_id,
            WlWorklog.deleted == 0,
            WlWorklog.risk_flag == 0,
            WlWorklog.problem != "",
            WlWorklog.status.in_(("SUBMITTED", "CONFIRMED", "PENDING_APPROVE")),
            WlWorklog.log_date >= since,
        )
        .order_by(WlWorklog.log_date.desc(), WlWorklog.id.desc())
        .limit(_LOG_ALERT_LIMIT)
    )
    log_problems: list[dict[str, object]] = [
        {
            "id": row[0],
            "worklogNo": row[1],
            "logDate": row[2],
            "problem": row[3],
            "userId": row[4],
        }
        for row in rows.all()
    ]

    alerts = build_alerts(
        project=project,
        stages=stages,
        milestones=milestones,
        tasks=tasks,
        log_problems=log_problems,
        today=base,
    )
    skip = await _converted_keys(session, project_id)
    skip |= await _muted_keys(session, project_id, base)
    return [item for item in alerts if item.key not in skip]


async def find_alert(
    session: AsyncSession, project_id: int, key: str, today: date | None = None
) -> Alert | None:
    """按 key 取一条预警（转正时以服务端算出的内容为准，不信任前端文本）。"""
    for item in await list_alerts(session, project_id, today):
        if item.key == key:
            return item
    return None


async def muted_until_of(
    session: AsyncSession, project_id: int, key: str
) -> str | None:
    """已存在的忽略到期日（没有则返回 None）。"""
    row = (
        await session.execute(
            select(PrjAlertMute)
            .where(
                PrjAlertMute.project_id == project_id,
                PrjAlertMute.alert_key == key,
                PrjAlertMute.deleted == 0,
            )
            .order_by(PrjAlertMute.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _text(row.muted_until) or None


async def mute_alert(
    session: AsyncSession,
    project_id: int,
    key: str,
    days: int,
    operator_id: int = 0,
) -> str:
    """忽略某个预警一段天数（重复忽略则顺延），返回忽略到期日。"""
    span = max(1, min(int(days or 7), 90))
    until = (date.today() + timedelta(days=span)).isoformat()
    row = (
        await session.execute(
            select(PrjAlertMute)
            .where(
                PrjAlertMute.project_id == project_id,
                PrjAlertMute.alert_key == key,
                PrjAlertMute.deleted == 0,
            )
            .order_by(PrjAlertMute.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            PrjAlertMute(
                project_id=project_id,
                alert_key=key,
                muted_until=until,
                create_by=operator_id,
            )
        )
    else:
        row.muted_until = until
        row.update_by = operator_id
    await session.flush()
    return until
