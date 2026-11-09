"""工作日志服务：填报、提交、确认、补填审批、评论、催办（设计稿 07）。

填报口径（v1.1.15 起）：
- **一人一天可有多条日志**，每条日志对应一个项目（可选任务），便于按项目记账；
- 当日累计工时超过 `worklog.hours.warnPerDay`（默认 8h）时**仅提示不禁止**；
- 只能补填最近 `worklog.backfill.maxDays`（默认 5 天）内的日志，阈值后台可调。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Final

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import (
    BizRuleError,
    ConflictError,
    DataForbiddenError,
    NotFoundError,
)
from pms.core.context import AuthContext
from pms.org.scope import project_visible, worklog_visible
from pms.project import service as project_service
from pms.project.models import PrjMember, PrjProject, PrjRisk, PrjTask
from pms.system.config_service import ConfigService
from pms.worklog.models import WlComment, WlItem, WlReminder, WlWorklog
from pms.worklog.rules import (
    HoursLimits,
    WorklogStatus,
    check_log_date,
    daily_total_warning,
    fill_rate,
    late_days,
    next_worklog_no,
    on_time_rate,
    round_hours,
    submit_status,
    validate_hours,
    workdays_between,
)

_STATUS_CONFIRMABLE: Final[frozenset[str]] = frozenset({WorklogStatus.SUBMITTED})
_STATUS_EDITABLE: Final[frozenset[str]] = frozenset(
    {WorklogStatus.DRAFT, WorklogStatus.REJECTED}
)


async def _limits(config: ConfigService) -> HoursLimits:
    """读取工时限额参数。"""
    return HoursLimits(
        max_per_day=await config.get_float("worklog.hours.maxPerDay"),
        warn_per_day=await config.get_float("worklog.hours.warnPerDay"),
        step=await config.get_float("worklog.hours.step"),
    )


async def _next_serial(session: AsyncSession) -> int:
    """日志流水号（按当前总数 +1）。"""
    result = await session.execute(
        select(func.count(WlWorklog.id)).where(WlWorklog.deleted == 0)
    )
    return int(result.scalar_one()) + 1


async def save_draft(
    session: AsyncSession,
    context: AuthContext,
    *,
    log_date: str,
    worklog_id: int = 0,
    log_type: str = "PROJECT",
    project_id: int = 0,
    task_id: int = 0,
    total_hours: float = 0,
    content: str = "",
    problem: str = "",
    plan: str = "",
    risk_flag: bool = False,
    progress_after: float = 0,
    items: list[dict[str, object]] | None = None,
) -> WlWorklog:
    """保存一条日志草稿（新增或按 `worklog_id` 更新）。

    模型约定（v1.1.17 起）：
    - `log_type=PROJECT`：一条日志对应一个项目 / 一个任务，团队可见；
    - `log_type=PERSONAL`：不绑定项目，默认仅本人可见，提交即生效；
    - `t_wl_item` 仅用于项目日志的唯一任务明细；
    - 日期必须落在补填窗口内（默认最近 5 天，参数 `worklog.backfill.maxDays`）。
    """
    config = ConfigService(session)
    step = await config.get_float("worklog.hours.step")
    backfill_max = await config.get_int("worklog.backfill.maxDays")
    day = _as_date(log_date)
    errors = check_log_date(day, backfill_max)
    if errors:
        raise BizRuleError("；".join(errors))

    worklog: WlWorklog | None = None
    log_type = (log_type or "PROJECT").upper()
    if log_type not in {"PROJECT", "PERSONAL"}:
        raise BizRuleError("日志类型无效")

    if worklog_id:
        worklog = await _get(session, worklog_id)
        if worklog.user_id != context.user_id:
            raise DataForbiddenError("只能修改自己的日志")
        if worklog.status not in _STATUS_EDITABLE:
            raise ConflictError(f"该日志状态为 {worklog.status}，不允许修改")

    if log_type == "PERSONAL":
        # 个人日志不绑定项目/任务，不参与项目工时与风险
        project_id = 0
        task_id = 0
        progress_after = 0
        risk_flag = False
        items = None

    # 兼容明细入参：一条日志只允许一个任务明细，避免主表与明细口径不一致
    if items:
        if len(items) > 1:
            raise BizRuleError("一条日志只支持一个项目/任务明细，请按项目分别记录")
        payload = items[0]
        project_id = int(payload.get("projectId", project_id) or project_id)
        task_id = int(payload.get("taskId", task_id) or task_id)
        total_hours = float(payload.get("hours", total_hours) or total_hours)
        content = str(payload.get("content", content) or content)
        progress_after = float(payload.get("progressAfter", progress_after) or progress_after)

    if log_type == "PROJECT":
        await _ensure_project_target(session, context, project_id, task_id)

    hours = float(total_hours)
    items = []
    if project_id or task_id:
        items = [
            {
                "projectId": project_id,
                "taskId": task_id,
                "hours": hours,
                "content": content,
                "progressAfter": progress_after,
            }
        ]

    if worklog is None:
        worklog = WlWorklog(
            worklog_no=next_worklog_no(day, await _next_serial(session)),
            user_id=context.user_id,
            dept_id=context.dept_id,
            log_date=day,
            status=WorklogStatus.DRAFT,
            create_by=context.user_id,
        )
        session.add(worklog)
        await session.flush()
    else:
        worklog.log_date = day
        worklog.status = WorklogStatus.DRAFT

    worklog.log_type = log_type
    worklog.project_id = project_id
    worklog.task_id = task_id
    worklog.total_hours = round_hours(hours, step)
    worklog.content = content
    worklog.problem = problem
    worklog.plan = plan
    worklog.risk_flag = 1 if risk_flag else 0
    worklog.update_by = context.user_id

    await _replace_items(session, worklog.id, items, step)
    await session.flush()
    return worklog


async def submit(session: AsyncSession, worklog_id: int, user_id: int = 0) -> WlWorklog:
    """提交日志：校验工时与补填窗口 → 判定补填 → 进入待确认或补填待审批。

    当日累计工时超过上限仍拒绝；超过预警阈值只提示（由调用方展示 `day_summary`）。
    """
    worklog = await _get(session, worklog_id)
    if user_id and worklog.user_id != user_id:
        raise DataForbiddenError("只能提交自己的日志")
    config = ConfigService(session)
    limits = await _limits(config)
    backfill_max = await config.get_int("worklog.backfill.maxDays")
    errors = check_log_date(_as_date(worklog.log_date), backfill_max)
    items = await list_items(session, worklog.id)
    item_hours = (
        sum(float(item.hours) for item in items)
        if items
        else float(worklog.total_hours)
    )
    errors.extend(validate_hours(float(worklog.total_hours), item_hours, limits))
    if errors:
        raise BizRuleError("；".join(errors))

    others = await _day_hours(
        session, worklog.user_id, _as_date(worklog.log_date), exclude_id=worklog.id
    )
    day_total = round_hours(others + float(worklog.total_hours), limits.step)
    if day_total > limits.max_per_day:
        raise BizRuleError(
            f"当日累计工时 {day_total:g}h 超过上限 {limits.max_per_day:g}h（R-LOG-05）"
        )

    day = late_days(_as_date(worklog.log_date))
    late_max = await config.get_int("worklog.late.maxDays")
    deadline_hour = max(
        0, min(24, await config.get_int("worklog.daily.deadlineHour"))
    )
    confirm_required = await config.get_bool("worklog.confirm.required")
    now = datetime.now()
    same_day = now.date() == _as_date(worklog.log_date)
    after_deadline = (
        same_day
        and deadline_hour < 24
        and now.time() > time(hour=deadline_hour)
    )
    worklog.is_late = 1 if day > 0 or after_deadline else 0
    worklog.late_days = day
    worklog.submit_time = date.today()
    worklog.submit_at = now
    worklog.update_by = user_id

    if worklog.log_type == "PERSONAL":
        # 个人日志不进入团队确认队列，提交即生效
        worklog.status = WorklogStatus.CONFIRMED
        worklog.confirm_by = user_id or worklog.user_id
        worklog.confirm_time = date.today()
    elif not confirm_required:
        # 参数关闭确认：提交即确认，并立即回填任务工时/进度
        worklog.status = WorklogStatus.CONFIRMED
        worklog.confirm_by = user_id or worklog.user_id
        worklog.confirm_time = date.today()
        await _apply_confirm_effects(session, worklog, user_id or worklog.user_id)
    else:
        worklog.status = submit_status(day, late_max)
    await session.flush()
    return worklog


async def delete_worklog(
    session: AsyncSession, worklog_id: int, user_id: int
) -> None:
    """删除自己的草稿/被驳回日志（软删除，明细一并失效）。"""
    worklog = await _get(session, worklog_id)
    if worklog.user_id != user_id:
        raise DataForbiddenError("只能删除自己的日志")
    if worklog.status not in _STATUS_EDITABLE:
        raise ConflictError(f"该日志状态为 {worklog.status}，不允许删除")
    worklog.deleted = 1
    worklog.update_by = user_id
    for item in await list_items(session, worklog.id):
        item.deleted = 1
    await session.flush()


async def day_summary(
    session: AsyncSession, *, user_id: int, log_date: str
) -> dict[str, object]:
    """统计某人某天的累计工时与预警状态（超过阈值仅提示）。"""
    config = ConfigService(session)
    limits = await _limits(config)
    day = _as_date(log_date)
    total = await _day_hours(session, user_id, day)
    count_result = await session.execute(
        select(func.count(WlWorklog.id)).where(
            WlWorklog.deleted == 0,
            WlWorklog.user_id == user_id,
            WlWorklog.log_date == day,
            WlWorklog.status != WorklogStatus.REJECTED,
        )
    )
    total = round_hours(total, limits.step)
    return {
        "date": day.isoformat(),
        "logCount": int(count_result.scalar_one()),
        "totalHours": total,
        "warnHours": limits.warn_per_day,
        "maxHours": limits.max_per_day,
        "overWarn": limits.warn_per_day > 0 and total > limits.warn_per_day,
        "warning": daily_total_warning(total, limits.warn_per_day),
    }


async def fill_options(session: AsyncSession, *, user_id: int) -> dict[str, object]:
    """填报选项：补填窗口、工时阈值与我参与的项目（前端下拉数据源）。"""
    config = ConfigService(session)
    limits = await _limits(config)
    projects = await list_my_projects(session, user_id)
    return {
        "backfillMaxDays": await config.get_int("worklog.backfill.maxDays"),
        "warnHours": limits.warn_per_day,
        "maxHours": limits.max_per_day,
        "step": limits.step,
        "today": date.today().isoformat(),
        "projects": [
            {
                "id": project.id,
                "projectCode": project.project_code,
                "projectName": project.project_name,
                "status": project.status,
            }
            for project in projects
        ],
    }


async def list_my_projects(
    session: AsyncSession, user_id: int
) -> list[PrjProject]:
    """我参与（或负责）的项目，用于填报下拉。"""
    member_projects = select(PrjMember.project_id).where(
        PrjMember.user_id == user_id,
        PrjMember.deleted == 0,
    )
    stmt = (
        select(PrjProject)
        .where(
            PrjProject.deleted == 0,
            or_(PrjProject.pm_id == user_id, PrjProject.id.in_(member_projects)),
        )
        .order_by(PrjProject.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def project_names(
    session: AsyncSession, project_ids: set[int]
) -> dict[int, str]:
    """批量取项目名称（列表展示用）。"""
    ids = {int(project_id) for project_id in project_ids if project_id}
    if not ids:
        return {}
    result = await session.execute(
        select(PrjProject.id, PrjProject.project_name).where(PrjProject.id.in_(ids))
    )
    return {int(project_id): str(name) for project_id, name in result.all()}


async def _apply_confirm_effects(
    session: AsyncSession, worklog: WlWorklog, operator_id: int
) -> None:
    """确认生效：回填任务工时/进度、生成风险项、重算项目进度。"""
    for item in await list_items(session, worklog.id):
        if item.task_id:
            task = await session.get(PrjTask, item.task_id)
            if task is not None:
                task.actual_hours = float(task.actual_hours) + float(item.hours)
                if float(item.progress_after) > float(task.progress):
                    task.progress = float(item.progress_after)
        project_id = item.project_id or worklog.project_id
        if project_id and worklog.risk_flag:
            session.add(
                PrjRisk(
                    project_id=project_id,
                    risk_type="RISK",
                    title=f"日志风险：{worklog.worklog_no}",
                    description=worklog.problem or worklog.content,
                    level="MEDIUM",
                    owner_id=worklog.user_id,
                    create_by=operator_id,
                )
            )
    await session.flush()
    for item in await list_items(session, worklog.id):
        if item.project_id:
            await project_service.recalc_progress(session, item.project_id)


async def confirm(session: AsyncSession, worklog_id: int, operator_id: int) -> WlWorklog:
    """PM 确认：回填任务工时与进度、生成风险项、重算项目进度（07 §6）。"""
    worklog = await _get(session, worklog_id)
    if worklog.status not in _STATUS_CONFIRMABLE:
        raise ConflictError(f"状态 {worklog.status} 不可确认")
    worklog.status = WorklogStatus.CONFIRMED
    worklog.confirm_by = operator_id
    worklog.confirm_time = date.today()
    worklog.update_by = operator_id
    await _apply_confirm_effects(session, worklog, operator_id)
    return worklog


async def reject(
    session: AsyncSession, worklog_id: int, operator_id: int, reason: str = ""
) -> WlWorklog:
    """PM 驳回：回到可修改状态。"""
    worklog = await _get(session, worklog_id)
    if worklog.status == WorklogStatus.CONFIRMED:
        await _rollback_effort(session, worklog)
    worklog.status = WorklogStatus.REJECTED
    worklog.reject_reason = reason
    worklog.update_by = operator_id
    await session.flush()
    return worklog


async def unconfirm(session: AsyncSession, worklog_id: int, operator_id: int) -> WlWorklog:
    """撤销确认：反向扣减工时后回到待确认（R-LOG-08）。"""
    worklog = await _get(session, worklog_id)
    if worklog.status != WorklogStatus.CONFIRMED:
        raise ConflictError("仅已确认日志可撤销确认")
    await _rollback_effort(session, worklog)
    worklog.status = WorklogStatus.SUBMITTED
    worklog.confirm_by = 0
    worklog.confirm_time = None
    worklog.update_by = operator_id
    await session.flush()
    return worklog


async def approve_late(session: AsyncSession, worklog_id: int, operator_id: int) -> WlWorklog:
    """逾期补填审批通过：PENDING_APPROVE → SUBMITTED。"""
    worklog = await _get(session, worklog_id)
    if worklog.status != WorklogStatus.PENDING_APPROVE:
        raise ConflictError("仅补填待审批日志可审批")
    worklog.status = WorklogStatus.SUBMITTED
    worklog.update_by = operator_id
    await session.flush()
    return worklog


async def add_comment(
    session: AsyncSession,
    worklog_id: int,
    context: AuthContext,
    content: str,
    *,
    parent_id: int = 0,
) -> WlComment:
    """日志评论（`parent_id` 指向被回复的评论，支持多级回复）。"""
    if parent_id:
        parent = await session.get(WlComment, parent_id)
        if parent is None or parent.deleted or parent.worklog_id != worklog_id:
            raise NotFoundError("回复的评论不存在")
    comment = WlComment(
        worklog_id=worklog_id,
        user_id=context.user_id,
        parent_id=parent_id,
        content=content,
        create_by=context.user_id,
    )
    session.add(comment)
    await session.flush()
    return comment


async def list_comments(session: AsyncSession, worklog_id: int) -> list[WlComment]:
    """评论列表。"""
    result = await session.execute(
        select(WlComment)
        .where(WlComment.worklog_id == worklog_id, WlComment.deleted == 0)
        .order_by(WlComment.id)
    )
    return list(result.scalars().all())


async def delete_comment(
    session: AsyncSession,
    worklog_id: int,
    comment_id: int,
    user_id: int,
    *,
    can_manage: bool = False,
) -> None:
    """删除评论：本人或管理员可删，并级联删除其整棵回复树。"""
    comment = await session.get(WlComment, comment_id)
    if comment is None or comment.deleted or comment.worklog_id != worklog_id:
        raise NotFoundError("评论不存在")
    if comment.user_id != user_id and not can_manage:
        raise DataForbiddenError("只能删除自己的评论")
    comment.deleted = 1
    comment.update_by = user_id
    visited = {comment.id}
    frontier = [comment.id]
    while frontier:
        replies = await session.execute(
            select(WlComment).where(
                WlComment.parent_id.in_(frontier), WlComment.deleted == 0
            )
        )
        next_frontier: list[int] = []
        for reply in replies.scalars().all():
            if reply.id in visited:
                continue
            visited.add(reply.id)
            reply.deleted = 1
            reply.update_by = user_id
            next_frontier.append(reply.id)
        frontier = next_frontier
    await session.flush()


async def create_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    log_date: str,
    remind_type: str = "AUTO",
    remind_by: int = 0,
    content: str = "",
) -> WlReminder:
    """生成催办记录（自动或手动，07 §7）。"""
    reminder = WlReminder(
        user_id=user_id,
        log_date=log_date,
        remind_type=remind_type,
        remind_by=remind_by,
        content=content,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def list_reminders(
    session: AsyncSession,
    user_id: int | None = None,
    status: str = "",
    *,
    offset: int = 0,
    limit: int = 0,
) -> list[WlReminder]:
    """催办列表（`limit <= 0` 表示不限制数量）。"""
    stmt = select(WlReminder).where(WlReminder.deleted == 0)
    if user_id:
        stmt = stmt.where(WlReminder.user_id == user_id)
    if status:
        stmt = stmt.where(WlReminder.status == status)
    stmt = stmt.order_by(WlReminder.id.desc())
    if limit > 0:
        stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def reminder_targets(
    session: AsyncSession,
    *,
    log_date: str,
    dept_ids: list[int] | None = None,
) -> list[dict[str, object]]:
    """待催办人员：在岗、未提交该日日志、且该日尚未催办。"""
    from pms.org.models import SysDept, SysUser

    day = _as_date(log_date)
    submitted = select(WlWorklog.user_id).where(
        WlWorklog.deleted == 0,
        WlWorklog.log_date == day,
        WlWorklog.status.in_(
            [
                WorklogStatus.SUBMITTED,
                WorklogStatus.PENDING_APPROVE,
                WorklogStatus.CONFIRMED,
            ]
        ),
    )
    reminded = select(WlReminder.user_id).where(
        WlReminder.deleted == 0,
        WlReminder.log_date == day,
    )
    stmt = (
        select(SysUser)
        .where(
            SysUser.deleted == 0,
            SysUser.status == "ENABLED",
            SysUser.id.not_in(submitted),
            SysUser.id.not_in(reminded),
        )
        .order_by(SysUser.dept_id, SysUser.id)
        .limit(500)
    )
    if dept_ids is not None:
        stmt = stmt.where(SysUser.dept_id.in_(dept_ids))
    users = list((await session.execute(stmt)).scalars().all())
    if not users:
        return []
    dept_result = await session.execute(
        select(SysDept.id, SysDept.dept_name).where(
            SysDept.id.in_({user.dept_id for user in users})
        )
    )
    dept_names = {int(dept_id): str(name) for dept_id, name in dept_result.all()}
    return [
        {
            "id": user.id,
            "username": user.username,
            "realName": user.real_name,
            "deptId": user.dept_id,
            "deptName": dept_names.get(user.dept_id, ""),
        }
        for user in users
    ]


async def count_reminders(
    session: AsyncSession, user_id: int | None = None, status: str = ""
) -> int:
    """催办记录数量。"""
    stmt = select(func.count(WlReminder.id)).where(WlReminder.deleted == 0)
    if user_id:
        stmt = stmt.where(WlReminder.user_id == user_id)
    if status:
        stmt = stmt.where(WlReminder.status == status)
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def mark_reminder_read(
    session: AsyncSession, reminder_id: int, user_id: int
) -> WlReminder:
    """标记本人催办已读。"""
    reminder = await session.get(WlReminder, reminder_id)
    if reminder is None or reminder.deleted:
        raise NotFoundError("催办记录不存在")
    if reminder.user_id != user_id:
        raise DataForbiddenError("只能处理自己的催办提醒")
    if reminder.status != "READ":
        reminder.status = "READ"
        reminder.update_by = user_id
        await session.flush()
    return reminder


async def mark_all_reminders_read(session: AsyncSession, user_id: int) -> int:
    """把本人全部待处理催办标记为已读。"""
    result = await session.execute(
        update(WlReminder)
        .where(
            WlReminder.user_id == user_id,
            WlReminder.status == "OPEN",
            WlReminder.deleted == 0,
        )
        .values(status="READ", update_by=user_id)
    )
    await session.flush()
    return int(result.rowcount or 0)


def _worklog_filters(
    *,
    user_ids: list[int] | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str = "",
    keyword: str = "",
    log_type: str = "",
    exclude_user_id: int = 0,
) -> list[ColumnElement[bool]]:
    """构造日志查询条件（列表与计数共用）。"""
    conditions: list[ColumnElement[bool]] = [WlWorklog.deleted == 0]
    if user_ids:
        conditions.append(WlWorklog.user_id.in_(user_ids))
    if log_type:
        conditions.append(WlWorklog.log_type == log_type)
    if exclude_user_id:
        conditions.append(WlWorklog.user_id != exclude_user_id)
    if project_id:
        subq = select(WlItem.worklog_id).where(
            WlItem.project_id == project_id, WlItem.deleted == 0
        )
        conditions.append(
            or_(WlWorklog.project_id == project_id, WlWorklog.id.in_(subq))
        )
    if date_from:
        conditions.append(WlWorklog.log_date >= date_from)
    if date_to:
        conditions.append(WlWorklog.log_date <= date_to)
    if status:
        values = [item.strip() for item in status.split(",") if item.strip()]
        if len(values) == 1:
            conditions.append(WlWorklog.status == values[0])
        elif values:
            conditions.append(WlWorklog.status.in_(values))
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        conditions.append(
            or_(
                WlWorklog.content.like(like),
                WlWorklog.problem.like(like),
                WlWorklog.plan.like(like),
                WlWorklog.worklog_no.like(like),
            )
        )
    return conditions


async def list_worklogs(
    session: AsyncSession,
    *,
    user_ids: list[int] | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str = "",
    keyword: str = "",
    log_type: str = "",
    exclude_user_id: int = 0,
    offset: int = 0,
    limit: int = 0,
) -> list[WlWorklog]:
    """日志列表（候选集，可见性在 API 层用 `can_view` 逐条过滤）。

    `limit <= 0` 表示不限制数量，供可见性过滤后自行分页使用。
    """
    conditions = _worklog_filters(
        user_ids=user_ids,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        keyword=keyword,
        log_type=log_type,
        exclude_user_id=exclude_user_id,
    )
    stmt = (
        select(WlWorklog)
        .where(*conditions)
        .order_by(WlWorklog.log_date.desc(), WlWorklog.id.desc())
    )
    if limit > 0:
        stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_worklogs(
    session: AsyncSession,
    *,
    user_ids: list[int] | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str = "",
    keyword: str = "",
    log_type: str = "",
    exclude_user_id: int = 0,
) -> int:
    """按与列表一致的条件统计条数（本人日志分页用）。"""
    conditions = _worklog_filters(
        user_ids=user_ids,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        keyword=keyword,
        log_type=log_type,
        exclude_user_id=exclude_user_id,
    )
    result = await session.execute(
        select(func.count(WlWorklog.id)).where(*conditions)
    )
    return int(result.scalar_one() or 0)


async def can_view(
    session: AsyncSession, context: AuthContext, worklog: WlWorklog
) -> bool:
    """日志可见性：个人日志仅本人；项目日志按本人/下级/部门/项目组规则。"""
    if worklog.log_type == "PERSONAL":
        return worklog.user_id == context.user_id
    config = ConfigService(session)
    items = await list_items(session, worklog.id)
    project_ids = {item.project_id for item in items if item.project_id}
    if worklog.project_id:
        project_ids.add(worklog.project_id)

    is_subordinate = worklog.user_id != context.user_id and await _is_subordinate(
        session, context, worklog.user_id
    )
    is_dept_scope = context.can_see_dept(worklog.dept_id)
    same_project = False
    for project_id in project_ids:
        if await project_service.is_member(session, project_id, context.user_id):
            same_project = True
            break

    if not worklog_visible(
        is_self=worklog.user_id == context.user_id,
        is_subordinate=is_subordinate,
        is_dept_scope=is_dept_scope,
        is_dept_privileged=context.is_dept_head or context.is_privileged,
        dept_log_visible=await config.get_bool("worklog.dept.visible"),
        same_project=same_project,
        project_log_visible=await config.get_bool("worklog.project.visible"),
    ):
        return False

    # 与项目可见性联动：项目不可见则其日志不可见
    dept_visible = await config.get_bool("project.dept.visible")
    public_visible = await config.get_bool("project.public.visible")
    for project_id in project_ids:
        project = await session.get(PrjProject, project_id)
        if project is None:
            continue
        if not project_visible(
            secret_level=project.secret_level,
            is_member=await project_service.is_member(session, project_id, context.user_id),
            is_pm=project.pm_id == context.user_id,
            is_dept_visible=dept_visible,
            is_owner_dept_visible=context.can_see_dept(project.dept_id),
            is_all_scope=context.is_all_scope,
            public_visible=public_visible,
        ):
            return False
    return True


async def stats(
    session: AsyncSession,
    *,
    user_id: int,
    date_from: str,
    date_to: str,
) -> dict[str, float]:
    """个人填写率与及时率（按**自然日去重**统计，R-LOG-12）。"""
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    required = workdays_between(start, end)
    stmt = select(WlWorklog).where(
        WlWorklog.deleted == 0,
        WlWorklog.user_id == user_id,
        WlWorklog.log_date >= date_from,
        WlWorklog.log_date <= date_to,
        WlWorklog.status.in_(
            [WorklogStatus.SUBMITTED, WorklogStatus.CONFIRMED, WorklogStatus.PENDING_APPROVE]
        ),
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    submitted_days = len({row.log_date for row in rows})
    on_time_days = len({row.log_date for row in rows if row.is_late == 0})
    return {
        "requiredDays": float(required),
        "submittedDays": float(submitted_days),
        "fillRate": fill_rate(submitted_days, required),
        "onTimeRate": on_time_rate(on_time_days, submitted_days),
        "totalHours": float(sum(float(row.total_hours) for row in rows)),
    }


def period_bounds(
    period: str,
    anchor: date | None = None,
    *,
    date_from: str = "",
    date_to: str = "",
) -> tuple[date, date]:
    """按 `day/week/month/custom` 计算统计区间（含首尾）。"""
    base = anchor or date.today()
    key = (period or "day").lower()
    if key == "week":
        start = base - timedelta(days=base.weekday())
        return start, start + timedelta(days=6)
    if key == "month":
        start = base.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        return start, next_month - timedelta(days=1)
    if key == "custom":
        start = date.fromisoformat(date_from) if date_from else base
        end = date.fromisoformat(date_to) if date_to else base
        return (start, end) if start <= end else (end, start)
    return base, base


async def period_summary(
    session: AsyncSession,
    *,
    user_id: int,
    date_from: date,
    date_to: date,
    period: str = "day",
) -> dict[str, object]:
    """按日/周/月汇总个人日志：工时、条数、填报率、项目与每日分布。"""
    config = ConfigService(session)
    limits = await _limits(config)
    result = await session.execute(
        select(WlWorklog)
        .where(
            WlWorklog.deleted == 0,
            WlWorklog.user_id == user_id,
            WlWorklog.log_date >= date_from,
            WlWorklog.log_date <= date_to,
            WlWorklog.status != WorklogStatus.REJECTED,
        )
        .order_by(WlWorklog.log_date, WlWorklog.id)
    )
    rows = list(result.scalars().all())

    by_project: dict[int, dict[str, object]] = {}
    by_status: dict[str, int] = {}
    late_count = 0
    for row in rows:
        project_id = int(row.project_id or 0)
        bucket = by_project.setdefault(
            project_id,
            {"projectId": project_id, "hours": 0.0, "logCount": 0},
        )
        bucket["hours"] = float(bucket["hours"]) + float(row.total_hours)
        bucket["logCount"] = int(bucket["logCount"]) + 1
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.is_late:
            late_count += 1

    names = await project_names(session, set(by_project))
    projects = [
        {
            "projectId": item["projectId"],
            "projectName": names.get(int(item["projectId"]), "") or "个人 / 其他",
            "hours": round_hours(float(item["hours"]), limits.step),
            "logCount": item["logCount"],
        }
        for item in by_project.values()
    ]
    projects.sort(key=lambda item: float(item["hours"]), reverse=True)

    day_map: dict[date, dict[str, object]] = {}
    current = date_from
    while current <= date_to:
        day_map[current] = {"date": current.isoformat(), "hours": 0.0, "count": 0}
        current += timedelta(days=1)
    for row in rows:
        slot = day_map.get(row.log_date) if row.log_date else None
        if slot is not None:
            slot["hours"] = float(slot["hours"]) + float(row.total_hours)
            slot["count"] = int(slot["count"]) + 1

    total_hours = round_hours(
        sum(float(row.total_hours) for row in rows), limits.step
    )
    filled_days = len({row.log_date for row in rows if row.log_date})
    late_days_set = {
        row.log_date for row in rows if row.log_date and row.is_late
    }
    on_time_days = max(0, filled_days - len(late_days_set))
    today = date.today()
    calc_end = min(date_to, today)
    required_days = workdays_between(date_from, calc_end) if calc_end >= date_from else 0

    return {
        "period": period,
        "dateFrom": date_from.isoformat(),
        "dateTo": date_to.isoformat(),
        "totalHours": total_hours,
        "logCount": len(rows),
        "filledDays": filled_days,
        "requiredDays": required_days,
        "fillRate": fill_rate(filled_days, required_days),
        "onTimeRate": on_time_rate(on_time_days, filled_days),
        "avgHoursPerWorkday": (
            round(total_hours / required_days, 2) if required_days > 0 else 0.0
        ),
        "lateCount": late_count,
        "warnHours": limits.warn_per_day,
        "maxHours": limits.max_per_day,
        "overWarn": (
            period == "day"
            and limits.warn_per_day > 0
            and total_hours > limits.warn_per_day
        ),
        "byStatus": by_status,
        "byProject": projects,
        "days": [
            {
                "date": slot["date"],
                "hours": round_hours(float(slot["hours"]), limits.step),
                "count": slot["count"],
            }
            for slot in day_map.values()
        ],
    }


async def user_names(
    session: AsyncSession, user_ids: set[int]
) -> dict[int, tuple[str, str]]:
    """批量取用户名与姓名（列表/评论展示用）。"""
    from pms.org.models import SysUser

    ids = {int(user_id) for user_id in user_ids if user_id}
    if not ids:
        return {}
    result = await session.execute(
        select(SysUser.id, SysUser.username, SysUser.real_name).where(
            SysUser.id.in_(ids)
        )
    )
    return {
        int(user_id): (str(username), str(real_name or ""))
        for user_id, username, real_name in result.all()
    }


async def task_names(session: AsyncSession, task_ids: set[int]) -> dict[int, str]:
    """批量取任务名称（详情展示用）。"""
    ids = {int(task_id) for task_id in task_ids if task_id}
    if not ids:
        return {}
    result = await session.execute(
        select(PrjTask.id, PrjTask.task_name).where(PrjTask.id.in_(ids))
    )
    return {int(task_id): str(name) for task_id, name in result.all()}


async def get_worklog(session: AsyncSession, worklog_id: int) -> WlWorklog:
    """取日志（对外）。"""
    return await _get(session, worklog_id)


async def list_items(session: AsyncSession, worklog_id: int) -> list[WlItem]:
    """日志明细。"""
    result = await session.execute(
        select(WlItem)
        .where(WlItem.worklog_id == worklog_id, WlItem.deleted == 0)
        .order_by(WlItem.id)
    )
    return list(result.scalars().all())


async def _day_hours(
    session: AsyncSession,
    user_id: int,
    log_date: date,
    *,
    exclude_id: int = 0,
) -> float:
    """某人某天已填工时合计（不含被驳回的日志）。"""
    stmt = select(func.coalesce(func.sum(WlWorklog.total_hours), 0)).where(
        WlWorklog.deleted == 0,
        WlWorklog.user_id == user_id,
        WlWorklog.log_date == log_date,
        WlWorklog.status != WorklogStatus.REJECTED,
    )
    if exclude_id:
        stmt = stmt.where(WlWorklog.id != exclude_id)
    result = await session.execute(stmt)
    return float(result.scalar_one() or 0)


async def _ensure_project_target(
    session: AsyncSession, context: AuthContext, project_id: int, task_id: int
) -> None:
    """校验填报对象：项目存在且本人参与（R-LOG-07），任务归属一致。"""
    if project_id:
        project = await session.get(PrjProject, project_id)
        if project is None or project.deleted:
            raise NotFoundError("项目不存在")
        is_member = await project_service.is_member(session, project_id, context.user_id)
        if project.pm_id != context.user_id and not is_member:
            raise BizRuleError("不是该项目成员，不能对该项目填报（R-LOG-07）")
    if task_id:
        task = await session.get(PrjTask, task_id)
        if task is None or task.deleted:
            raise NotFoundError("任务不存在")
        if project_id and task.project_id != project_id:
            raise BizRuleError("所选任务不属于该项目")


async def _replace_items(
    session: AsyncSession, worklog_id: int, items: list[dict[str, object]], step: float
) -> None:
    """覆盖式保存明细（总分一致由提交时校验）。"""
    for row in await list_items(session, worklog_id):
        row.deleted = 1
    for payload in items:
        session.add(
            WlItem(
                worklog_id=worklog_id,
                project_id=int(payload.get("projectId", 0) or 0),
                task_id=int(payload.get("taskId", 0) or 0),
                hours=round_hours(float(payload.get("hours", 0) or 0), step),
                content=str(payload.get("content", "")),
                progress_after=float(payload.get("progressAfter", 0) or 0),
            )
        )
    await session.flush()


async def _rollback_effort(session: AsyncSession, worklog: WlWorklog) -> None:
    """撤销/驳回时反向扣减任务实际工时。"""
    for item in await list_items(session, worklog.id):
        if item.task_id:
            task = await session.get(PrjTask, item.task_id)
            if task is not None:
                task.actual_hours = max(float(task.actual_hours) - float(item.hours), 0)
    await session.flush()


async def _is_subordinate(session: AsyncSession, context: AuthContext, author_id: int) -> bool:
    """作者是否为当前用户的直属下级（层级由 `org.manager.depth` 控制）。"""
    from pms.org.models import SysUser

    depth = await ConfigService(session).get_int("org.manager.depth")
    current = await session.get(SysUser, author_id)
    hops = 0
    while current is not None and hops < max(depth, 0):
        if current.manager_id == context.user_id:
            return True
        if not current.manager_id:
            break
        current = await session.get(SysUser, current.manager_id)
        hops += 1
    return False


def _as_date(value: object) -> date:
    """把日志日期列值转为 `date`。"""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


async def _get(session: AsyncSession, worklog_id: int) -> WlWorklog:
    """按 ID 取日志。"""
    worklog = await session.get(WlWorklog, worklog_id)
    if worklog is None or worklog.deleted:
        raise NotFoundError("日志不存在")
    return worklog
