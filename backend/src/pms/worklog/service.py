"""工作日志服务：填报、提交、确认、补填审批、评论、催办（设计稿 07）。

填报口径（v1.1.15 起）：
- **一人一天可有多条日志**，每条日志对应一个项目（可选任务），便于按项目记账；
- 当日累计工时超过 `worklog.hours.warnPerDay`（默认 8h）时**仅提示不禁止**；
- 只能补填最近 `worklog.backfill.maxDays`（默认 5 天）内的日志，阈值后台可调。
"""

from __future__ import annotations

from dataclasses import dataclass
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
from pms.issue.models import IssIssue
from pms.issue.state import IssueStatus, IssueType
from pms.org.scope import project_visible, worklog_visible
from pms.project import service as project_service
from pms.project.alerts import log_risk_level, problem_summary
from pms.project.models import PrjMember, PrjProject, PrjTask
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
    validate_required_text,
    workdays_between,
)

_STATUS_CONFIRMABLE: Final[frozenset[str]] = frozenset({WorklogStatus.SUBMITTED})

#: 组内角色中文别名（历史数据兼容）：比较前统一映射回编码
_MEMBER_ROLE_ALIASES: Final[dict[str, str]] = {
    "成员": "MEMBER",
    "开发": "DEV",
    "测试": "TEST",
    "运维": "OPS",
    "实施": "IMPL",
    "设计": "DESIGN",
    "销售": "SALES",
    "项目经理": "PM",
    "总监": "DIRECTOR",
}

#: 项目内可见全部团队日志的组内角色（负责人 / 总监）
_TEAM_MANAGER_ROLES: Final[frozenset[str]] = frozenset({"PM", "DIRECTOR"})
_STATUS_EDITABLE: Final[frozenset[str]] = frozenset(
    {WorklogStatus.DRAFT, WorklogStatus.REJECTED}
)


@dataclass(frozen=True)
class LogTypeMeta:
    """日志类型元数据，收敛各处的类型分支判断。"""

    label: str
    requires_project: bool = False
    personal_only: bool = False


#: 项目日志绑定项目/任务；个人日志仅本人可见；
#: 学习/外出/会议属于不绑定项目的日常事务日志，团队可见、提交即生效。
LOG_TYPE_META: Final[dict[str, LogTypeMeta]] = {
    "PROJECT": LogTypeMeta("项目", requires_project=True),
    "PERSONAL": LogTypeMeta("个人", personal_only=True),
    "STUDY": LogTypeMeta("学习"),
    "OUTING": LogTypeMeta("外出"),
    "MEETING_COMPANY": LogTypeMeta("公司会议"),
    "MEETING_DEPT": LogTypeMeta("部门会议"),
    "MEETING_PROJECT": LogTypeMeta("项目会议"),
}


def log_type_meta(log_type: str | None) -> LogTypeMeta:
    """取日志类型元数据，未知类型按项目日志兜底。"""
    return LOG_TYPE_META.get((log_type or "PROJECT").upper(), LOG_TYPE_META["PROJECT"])


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
    issue_id: int = 0,
    total_hours: float = 0,
    content: str = "",
    problem: str = "",
    plan: str = "",
    risk_flag: bool = False,
    progress_after: float = 0,
    items: list[dict[str, object]] | None = None,
) -> WlWorklog:
    """保存一条日志草稿（新增或按 `worklog_id` 更新）。

    模型约定：
    - `log_type=PROJECT`：一条日志可覆盖多个项目（每个项目一条 `t_wl_item` 明细、
      各自带工时），主表 `project_id/task_id/issue_id` 取第一条项目做兼容展示；
    - 明细可挂任务或问题单（Bug / 生产问题），二者选填且互斥；
    - `log_type=PERSONAL`：不绑定项目，默认仅本人可见，提交即生效；
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
    meta = LOG_TYPE_META.get(log_type)
    if meta is None:
        raise BizRuleError("日志类型无效")

    if worklog_id:
        worklog = await _get(session, worklog_id)
        if worklog.user_id != context.user_id:
            raise DataForbiddenError("只能修改自己的日志")
        if worklog.status not in _STATUS_EDITABLE:
            raise ConflictError(f"该日志状态为 {worklog.status}，不允许修改")

    if not meta.requires_project:
        # 个人/学习/外出/会议日志不绑定项目、任务，不参与项目工时与风险
        project_id = 0
        task_id = 0
        issue_id = 0
        progress_after = 0
        risk_flag = False
        items = None

    # 项目日志支持一条日志记多个项目：每个明细带自己的工时，主表取第一条项目做兼容
    normalized: list[dict[str, object]] = []
    if meta.requires_project:
        payloads = items or [
            {
                "projectId": project_id,
                "taskId": task_id,
                "issueId": issue_id,
                "hours": total_hours,
                "progressAfter": progress_after,
            }
        ]
        seen: set[tuple[int, int, int]] = set()
        for payload in payloads:
            pid = int(payload.get("projectId", 0) or 0)
            tid = int(payload.get("taskId", 0) or 0)
            iid = int(payload.get("issueId", 0) or 0)
            item_hours = round_hours(float(payload.get("hours", 0) or 0), step)
            if pid <= 0:
                raise BizRuleError("请选择项目")
            if item_hours <= 0:
                raise BizRuleError("每条明细的工时需大于 0")
            if tid and iid:
                raise BizRuleError("任务与 Bug/生产问题只能关联一个")
            # 同一项目可以按任务/问题拆多条明细，只拦完全重复的同一对象
            if (pid, tid, iid) in seen:
                raise BizRuleError("同一项目下的同一任务/问题只能填写一条工时")
            seen.add((pid, tid, iid))
            # 多项目时前端按「@项目名」拆好每段内容：
            # 传了 content 就按传的来（空串表示该项目不写内容）；
            # 没传（老客户端）才整段带过去。
            raw_content = payload.get("content", None)
            item_content = content if raw_content is None else str(raw_content or "").strip()
            normalized.append(
                {
                    "projectId": pid,
                    "taskId": tid,
                    "issueId": iid,
                    "hours": item_hours,
                    "content": item_content,
                    "progressAfter": float(payload.get("progressAfter", 0) or 0),
                }
            )
        for payload in normalized:
            await _ensure_project_target(
                session,
                context,
                int(payload["projectId"]),
                int(payload["taskId"]),
                int(payload["issueId"]),
            )
        project_id = int(normalized[0]["projectId"])
        task_id = int(normalized[0]["taskId"])
        issue_id = int(normalized[0]["issueId"])
        hours = sum(float(payload["hours"]) for payload in normalized)
    else:
        project_id = 0
        task_id = 0
        issue_id = 0
        hours = float(total_hours)

    items = normalized

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
    worklog.issue_id = issue_id
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
    # 工作内容与明日计划必填：前端已拦截，这里兜底防止绕过草稿提交空日志
    errors.extend(validate_required_text(worklog.content, worklog.plan))
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

    if not log_type_meta(worklog.log_type).requires_project:
        # 个人/学习/外出/会议日志不进入确认队列，提交即生效
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


async def worklog_item_projects(
    session: AsyncSession, worklog_ids: list[int]
) -> dict[int, list[dict[str, object]]]:
    """批量取日志的多项目明细（列表展示「项目A、项目B」用，避免逐条查询）。"""
    ids = [int(item) for item in worklog_ids if item]
    if not ids:
        return {}
    rows = await session.execute(
        select(WlItem.worklog_id, WlItem.project_id, WlItem.hours, WlItem.content)
        .where(WlItem.worklog_id.in_(ids), WlItem.deleted == 0)
        .order_by(WlItem.id)
    )
    result: dict[int, list[dict[str, object]]] = {}
    for worklog_id, project_id, hours, content in rows.all():
        result.setdefault(int(worklog_id), []).append(
            {
                "projectId": int(project_id or 0),
                "hours": float(hours or 0),
                # 按项目填写的内容（用 @项目 分段时才有），周报据此避免串项
                "content": str(content or ""),
            }
        )
    return result


async def project_actual_hours_map(
    session: AsyncSession, project_ids: set[int] | list[int]
) -> dict[int, float]:
    """项目实际工时（批量）。

    口径：**日志明细是工时的唯一事实来源**——只统计已生效日志（`CONFIRMED`）
    中落到该项目的明细工时，要求绑定项目但**不要求绑定任务**，
    因此没建任务的项目同样有实际工时。
    """
    ids = {int(project_id) for project_id in project_ids if project_id}
    if not ids:
        return {}
    result = await session.execute(
        select(WlItem.project_id, func.sum(WlItem.hours))
        .join(WlWorklog, WlWorklog.id == WlItem.worklog_id)
        .where(
            WlItem.project_id.in_(ids),
            WlItem.deleted == 0,
            WlWorklog.deleted == 0,
            WlWorklog.status == WorklogStatus.CONFIRMED,
        )
        .group_by(WlItem.project_id)
    )
    return {int(project_id): float(hours or 0) for project_id, hours in result.all()}


async def project_actual_hours(session: AsyncSession, project_id: int) -> float:
    """单个项目的实际工时（口径同 `project_actual_hours_map`）。"""
    totals = await project_actual_hours_map(session, [project_id])
    return totals.get(int(project_id), 0.0)


async def _recalc_task_hours(session: AsyncSession, task_ids: set[int]) -> None:
    """按已生效日志明细重算任务实际工时（覆盖写，幂等）。

    任务工时只是日志工时的下钻视图：确认、撤销确认、驳回都走同一套重算，
    不再做 ± 累加，避免日志反复修改导致工时漂移。
    工时变化后同步刷新任务进度（进度 = 实际工时 / 计划工时），
    因此写日志就等于报进度，不用再单独填。
    """
    ids = {int(task_id) for task_id in task_ids if task_id}
    if not ids:
        return
    # 先把日志状态变更刷到库里，保证聚合查询读到的状态是最新的
    await session.flush()
    result = await session.execute(
        select(WlItem.task_id, func.sum(WlItem.hours))
        .join(WlWorklog, WlWorklog.id == WlItem.worklog_id)
        .where(
            WlItem.task_id.in_(ids),
            WlItem.deleted == 0,
            WlWorklog.deleted == 0,
            WlWorklog.status == WorklogStatus.CONFIRMED,
        )
        .group_by(WlItem.task_id)
    )
    totals = {int(task_id): float(hours or 0) for task_id, hours in result.all()}
    for task_id in ids:
        task = await session.get(PrjTask, task_id)
        if task is not None:
            task.actual_hours = totals.get(task_id, 0.0)
            project_service.sync_task_progress_from_hours(task)
    await session.flush()


async def _recalc_issue_hours(session: AsyncSession, issue_ids: set[int]) -> None:
    """按已生效日志明细重算问题单累计工时（覆盖写，幂等）。

    与任务口径一致：问题单上的工时只是日志的下钻视图，
    确认 / 撤销确认 / 驳回都重算，避免日志反复修改导致工时漂移。
    """
    ids = {int(issue_id) for issue_id in issue_ids if issue_id}
    if not ids:
        return
    await session.flush()
    result = await session.execute(
        select(WlItem.issue_id, func.sum(WlItem.hours))
        .join(WlWorklog, WlWorklog.id == WlItem.worklog_id)
        .where(
            WlItem.issue_id.in_(ids),
            WlItem.deleted == 0,
            WlWorklog.deleted == 0,
            WlWorklog.status == WorklogStatus.CONFIRMED,
        )
        .group_by(WlItem.issue_id)
    )
    totals = {int(issue_id): float(hours or 0) for issue_id, hours in result.all()}
    for issue_id in ids:
        issue = await session.get(IssIssue, issue_id)
        if issue is not None:
            issue.actual_hours = totals.get(issue_id, 0.0)
    await session.flush()


async def _apply_confirm_effects(
    session: AsyncSession, worklog: WlWorklog, operator_id: int
) -> None:
    """确认生效：重算任务/问题工时、回填任务进度、生成风险项、重算项目进度。"""
    items = await list_items(session, worklog.id)
    await _recalc_task_hours(
        session, {int(item.task_id) for item in items if item.task_id}
    )
    # Bug / 生产问题只统计工时，不参与任务进度推算，也不影响项目进度
    await _recalc_issue_hours(
        session, {int(item.issue_id) for item in items if item.issue_id}
    )
    for item in items:
        if item.task_id:
            task = await session.get(PrjTask, item.task_id)
            # 进度默认由工时推算；日志里手工填了更高进度时以其为准（老入口，前端已不再展示）
            if task is not None and float(item.progress_after or 0) > float(task.progress):
                project_service.apply_task_progress(task, float(item.progress_after))
    # 日志风险：一条日志只落一条风险（按日志编号幂等，避免多明细重复建/重复确认再建），
    # 标题取「问题与阻塞」摘要，等级按关键词初判，来源标 WORKLOG 便于与人工登记区分
    if worklog.risk_flag:
        project_ids = {
            int(item.project_id or worklog.project_id)
            for item in items
            if (item.project_id or worklog.project_id)
        }
        problem = str(worklog.problem or "").strip()
        for project_id in project_ids:
            key = f"WORKLOG:{worklog.worklog_no}"
            if await project_service.find_risk_by_source_key(session, project_id, key):
                continue
            await project_service.create_risk(
                session,
                project_id,
                operator_id,
                risk_type="RISK",
                title=(
                    f"日志问题：{problem_summary(problem)}"
                    if problem
                    else f"日志风险：{worklog.worklog_no}"
                ),
                description=problem,
                level=log_risk_level(problem),
                owner_id=worklog.user_id,
                source="WORKLOG",
                source_key=key,
            )
    await session.flush()
    for item in items:
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
    was_confirmed = worklog.status == WorklogStatus.CONFIRMED
    worklog.status = WorklogStatus.REJECTED
    worklog.reject_reason = reason
    worklog.update_by = operator_id
    await session.flush()
    if was_confirmed:
        await _rollback_effort(session, worklog)
    return worklog


async def unconfirm(session: AsyncSession, worklog_id: int, operator_id: int) -> WlWorklog:
    """撤销确认：工时随状态重算归零后回到待确认（R-LOG-08）。"""
    worklog = await _get(session, worklog_id)
    if worklog.status != WorklogStatus.CONFIRMED:
        raise ConflictError("仅已确认日志可撤销确认")
    worklog.status = WorklogStatus.SUBMITTED
    worklog.confirm_by = 0
    worklog.confirm_time = None
    worklog.update_by = operator_id
    await session.flush()
    await _rollback_effort(session, worklog)
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


#: 管理者/领导岗权限点：拥有日志确认或日志管理的人不被系统催办
_LEADER_PERM_CODES: Final[tuple[str, ...]] = ("worklog:confirm", "worklog:manage")


async def leader_user_ids(session: AsyncSession) -> set[int]:
    """管理者/领导岗用户：全公司数据范围，或具备日志确认/管理权限。

    这些人自己安排补填，系统不发催办（自动任务与手动催办对象都排除）。
    """
    from pms.org.models import (
        SysPermission,
        SysRole,
        SysRolePermission,
        SysUserRole,
    )

    ids: set[int] = set()
    scope_rows = await session.execute(
        select(SysUserRole.user_id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(
            SysUserRole.deleted == 0,
            SysRole.deleted == 0,
            SysRole.status == "ENABLED",
            SysRole.data_scope == "ALL",
        )
    )
    ids.update(int(row[0]) for row in scope_rows.all())
    perm_rows = await session.execute(
        select(SysUserRole.user_id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .join(SysRolePermission, SysRolePermission.role_id == SysRole.id)
        .join(SysPermission, SysPermission.id == SysRolePermission.perm_id)
        .where(
            SysUserRole.deleted == 0,
            SysRole.deleted == 0,
            SysRole.status == "ENABLED",
            SysRolePermission.deleted == 0,
            SysPermission.deleted == 0,
            SysPermission.perm_code.in_(_LEADER_PERM_CODES),
        )
    )
    ids.update(int(row[0]) for row in perm_rows.all())
    return ids


async def reminder_targets(
    session: AsyncSession,
    *,
    log_date: str,
    dept_ids: list[int] | None = None,
) -> list[dict[str, object]]:
    """待催办人员：在岗、未提交该日日志、且该日尚未催办（管理者/领导岗不再催办）。"""
    from pms.org.models import SysDept, SysUser

    day = _as_date(log_date)
    leaders = await leader_user_ids(session)
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
    if leaders:
        stmt = stmt.where(SysUser.id.not_in(leaders))
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


async def team_summary(
    session: AsyncSession,
    *,
    project_id: int,
    user_ids: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str = "",
    keyword: str = "",
    log_type: str = "",
) -> dict[str, object]:
    """项目团队日志汇总（不分页）：条数、工时、参与人、按人 / 按天聚合。

    供项目周报详情里的「团队日志」页签展示，口径与列表筛选完全一致。
    """
    rows = await list_worklogs(
        session,
        user_ids=user_ids,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        keyword=keyword,
        log_type=log_type,
        limit=0,
    )
    item_map = await worklog_item_projects(session, [int(row.id) for row in rows])

    def hours_of(row: WlWorklog) -> float:
        """只统计本项目工时：多项目日志按明细拆分，老日志回落主表。"""
        entries = item_map.get(int(row.id), [])
        if not entries:
            return float(row.total_hours) if int(row.project_id) == project_id else 0.0
        return sum(
            float(entry["hours"])
            for entry in entries
            if int(entry["projectId"]) == project_id
        )

    member_hours: dict[int, float] = {}
    member_counts: dict[int, int] = {}
    day_hours: dict[str, float] = {}
    day_counts: dict[str, int] = {}
    for row in rows:
        hours = hours_of(row)
        member_hours[row.user_id] = member_hours.get(row.user_id, 0.0) + hours
        member_counts[row.user_id] = member_counts.get(row.user_id, 0) + 1
        day_text = (
            row.log_date.isoformat() if hasattr(row.log_date, "isoformat") else str(row.log_date)
        )
        day_hours[day_text] = day_hours.get(day_text, 0.0) + hours
        day_counts[day_text] = day_counts.get(day_text, 0) + 1

    names = await user_names(session, set(member_hours))
    members = [
        {
            "userId": int(user_id),
            "name": _display_name(names.get(int(user_id), ("", "")), int(user_id)),
            "logCount": member_counts.get(int(user_id), 0),
            "hours": round_hours(hours),
        }
        for user_id, hours in sorted(
            member_hours.items(), key=lambda item: item[1], reverse=True
        )
    ]
    by_day = [
        {
            "date": day_text,
            "count": day_counts[day_text],
            "hours": round_hours(day_hours[day_text]),
        }
        for day_text in sorted(day_hours)
    ]
    return {
        "logCount": len(rows),
        "totalHours": round_hours(sum(member_hours.values())),
        "memberCount": len(members),
        "members": members,
        "byDay": by_day,
    }


def _display_name(pair: tuple[str, str], user_id: int) -> str:
    """取人员显示名：真实姓名优先，其次登录名，最后兜底。"""
    username, real_name = pair
    return real_name or username or f"用户{user_id}"


async def can_view(
    session: AsyncSession, context: AuthContext, worklog: WlWorklog
) -> bool:
    """日志可见性：个人日志仅本人；其他日志按本人/下级/部门/项目组规则。"""
    if log_type_meta(worklog.log_type).personal_only:
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

    # 与项目可见性联动：一条日志可能覆盖多个项目，只要有一个项目本人可见即可
    dept_visible = await config.get_bool("project.dept.visible")
    public_visible = await config.get_bool("project.public.visible")
    is_project_owner = False
    any_visible = False
    for project_id in project_ids:
        project = await session.get(PrjProject, project_id)
        if project is None:
            continue
        if project.pm_id == context.user_id:
            is_project_owner = True
        if project_visible(
            secret_level=project.secret_level,
            is_member=await project_service.is_member(session, project_id, context.user_id),
            is_pm=project.pm_id == context.user_id,
            is_dept_visible=dept_visible,
            is_owner_dept_visible=context.can_see_dept(project.dept_id),
            is_all_scope=context.is_all_scope,
            public_visible=public_visible,
        ):
            any_visible = True
    if project_ids and not any_visible:
        return False

    # 团队日志角色隔离：同项目组内，普通成员只看与自身组内角色有交集的日志；
    # 本人 / 直属下级 / 项目负责人 / 部门领导 / PMO / 公司领导不受限制。
    privileged = (
        worklog.user_id == context.user_id
        or is_subordinate
        or is_project_owner
        or context.is_dept_head
        or context.is_privileged
    )
    if (
        same_project
        and not privileged
        and await config.get_bool("worklog.team.roleScope")
        and not await _same_project_role(session, context, project_ids, worklog.user_id)
    ):
        return False
    return True


async def _same_project_role(
    session: AsyncSession,
    context: AuthContext,
    project_ids: set[int],
    author_id: int,
) -> bool:
    """作者与查看者在同一项目里是否有相同的组内角色。

    组内角色取 `t_prj_member.role_in_project`（开发 / 测试 / 实施 / 运维 / 设计 / 销售 / 成员）。
    查看者是组内 PM / 总监时放行全部；作者或查看者不在项目组内时视为无共同角色，
    避免靠"补个成员身份"绕过隔离。
    """
    if not project_ids:
        return False
    rows = (
        await session.execute(
            select(PrjMember.project_id, PrjMember.user_id, PrjMember.role_in_project).where(
                PrjMember.project_id.in_(project_ids),
                PrjMember.user_id.in_({author_id, context.user_id}),
                PrjMember.deleted == 0,
            )
        )
    ).all()
    roles: dict[int, dict[int, set[str]]] = {}
    for project_id, user_id, role in rows:
        roles.setdefault(int(project_id), {}).setdefault(int(user_id), set()).add(
            _normalize_member_role(role)
        )
    viewer_roles = {role for members in roles.values() for role in members.get(context.user_id, set())}
    if viewer_roles & _TEAM_MANAGER_ROLES:
        return True
    for members in roles.values():
        if members.get(author_id, set()) & members.get(context.user_id, set()):
            return True
    return False


def _normalize_member_role(value: object) -> str:
    """组内角色归一化：历史数据里有中文值（如「成员」），统一映射回编码。"""
    text = str(value or "").strip()
    return _MEMBER_ROLE_ALIASES.get(text, text)


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

    # 一条日志可覆盖多个项目：按明细把工时拆到各项目，老日志回落主表
    item_map = await worklog_item_projects(session, [int(row.id) for row in rows])

    # 项目日志按项目聚合；个人/学习/外出/会议按类型聚合，避免都挤进「个人 / 其他」
    by_project: dict[str, dict[str, object]] = {}
    by_status: dict[str, int] = {}
    late_count = 0

    def bucket_of(key: str, project_id: int = 0, name: str = "") -> dict[str, object]:
        """取（或建）一个统计桶。"""
        return by_project.setdefault(
            key,
            {
                "projectId": project_id,
                "projectName": name,
                "hours": 0.0,
                "logCount": 0,
            },
        )

    for row in rows:
        meta = log_type_meta(row.log_type)
        entries = item_map.get(int(row.id), [])
        if meta.requires_project and entries:
            for entry in entries:
                project_id = int(entry["projectId"])
                bucket = bucket_of(f"project:{project_id}", project_id)
                bucket["hours"] = float(bucket["hours"]) + float(entry["hours"])
                bucket["logCount"] = int(bucket["logCount"]) + 1
        elif meta.requires_project:
            project_id = int(row.project_id or 0)
            bucket = bucket_of(f"project:{project_id}", project_id)
            bucket["hours"] = float(bucket["hours"]) + float(row.total_hours)
            bucket["logCount"] = int(bucket["logCount"]) + 1
        else:
            key = f"type:{(row.log_type or 'PERSONAL').upper()}"
            bucket = bucket_of(key, 0, meta.label)
            bucket["hours"] = float(bucket["hours"]) + float(row.total_hours)
            bucket["logCount"] = int(bucket["logCount"]) + 1
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.is_late:
            late_count += 1

    names = await project_names(
        session,
        {int(item["projectId"]) for item in by_project.values() if int(item["projectId"])},
    )
    projects = [
        {
            "projectId": item["projectId"],
            "projectName": names.get(int(item["projectId"]), "")
            or str(item["projectName"] or "个人 / 其他"),
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


async def issue_meta(
    session: AsyncSession, issue_ids: set[int]
) -> dict[int, dict[str, str]]:
    """批量取问题单编号/标题/类型（日志详情展示用）。"""
    ids = {int(issue_id) for issue_id in issue_ids if issue_id}
    if not ids:
        return {}
    result = await session.execute(
        select(IssIssue.id, IssIssue.issue_no, IssIssue.title, IssIssue.issue_type).where(
            IssIssue.id.in_(ids)
        )
    )
    return {
        int(issue_id): {
            "issueNo": str(issue_no or ""),
            "issueTitle": str(title or ""),
            "issueType": str(issue_type or ""),
        }
        for issue_id, issue_no, title, issue_type in result.all()
    }


async def list_target_issues(
    session: AsyncSession, project_id: int, user_id: int
) -> list[dict[str, object]]:
    """项目下可被日志关联的问题单（Bug / 生产问题），填报下拉用。"""
    if project_id <= 0:
        return []
    project = await session.get(PrjProject, project_id)
    if project is None or project.deleted:
        raise NotFoundError("项目不存在")
    is_member = await project_service.is_member(session, project_id, user_id)
    if project.pm_id != user_id and not is_member:
        raise BizRuleError("不是该项目成员，不能查看该项目问题")
    result = await session.execute(
        select(
            IssIssue.id,
            IssIssue.issue_no,
            IssIssue.title,
            IssIssue.issue_type,
            IssIssue.status,
        )
        .where(IssIssue.deleted == 0, IssIssue.project_id == project_id)
        .order_by(IssIssue.issue_type, IssIssue.id.desc())
        .limit(200)
    )
    return [
        {
            "id": int(issue_id),
            "issueNo": str(issue_no or ""),
            "title": str(title or ""),
            "issueType": str(issue_type or ""),
            "status": str(status or ""),
        }
        for issue_id, issue_no, title, issue_type, status in result.all()
    ]


async def my_issues(
    session: AsyncSession, user_id: int, issue_type: str = ""
) -> list[dict[str, object]]:
    """我负责或我提报的问题（左栏「我的 Bug / 我的生产问题」快捷入口）。

    只返回已关联项目且未关闭的问题：日志明细必须先落到项目，
    只挂产品的生产问题暂时无法在这里报工时。
    """
    conditions = [
        IssIssue.deleted == 0,
        IssIssue.project_id > 0,
        or_(IssIssue.owner_id == user_id, IssIssue.reporter_id == user_id),
        IssIssue.status != IssueStatus.CLOSED,
    ]
    kind = (issue_type or "").upper()
    if kind in (IssueType.BUG, IssueType.PROD):
        conditions.append(IssIssue.issue_type == kind)
    result = await session.execute(
        select(
            IssIssue.id,
            IssIssue.issue_no,
            IssIssue.title,
            IssIssue.issue_type,
            IssIssue.status,
            IssIssue.project_id,
        )
        .where(*conditions)
        .order_by(IssIssue.issue_type, IssIssue.id.desc())
        .limit(100)
    )
    rows = result.all()
    names = await project_names(session, {int(row.project_id) for row in rows})
    return [
        {
            "id": int(issue_id),
            "issueNo": str(issue_no or ""),
            "title": str(title or ""),
            "issueType": str(issue_type),
            "status": str(status or ""),
            "projectId": int(project_id),
            "projectName": names.get(int(project_id), ""),
        }
        for issue_id, issue_no, title, issue_type, status, project_id in rows
    ]


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
    session: AsyncSession,
    context: AuthContext,
    project_id: int,
    task_id: int,
    issue_id: int = 0,
) -> None:
    """校验填报对象：项目存在且本人参与（R-LOG-07），任务/问题归属一致。"""
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
    if issue_id:
        issue = await session.get(IssIssue, issue_id)
        if issue is None or issue.deleted:
            raise NotFoundError("Bug/生产问题不存在")
        if project_id and issue.project_id and issue.project_id != project_id:
            raise BizRuleError("所选 Bug/生产问题不属于该项目")


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
                issue_id=int(payload.get("issueId", 0) or 0),
                hours=round_hours(float(payload.get("hours", 0) or 0), step),
                content=str(payload.get("content", "")),
                progress_after=float(payload.get("progressAfter", 0) or 0),
            )
        )
    await session.flush()


async def _rollback_effort(session: AsyncSession, worklog: WlWorklog) -> None:
    """撤销/驳回后按新状态重算任务与问题的工时（该日志不再计入即自然归零）。

    工时归零会带着任务进度一起回落，所以这里必须同步重算项目进度，
    否则阶段/项目进度会停在撤销前的数值。
    """
    items = await list_items(session, worklog.id)
    await _recalc_task_hours(
        session, {int(item.task_id) for item in items if item.task_id}
    )
    await _recalc_issue_hours(
        session, {int(item.issue_id) for item in items if item.issue_id}
    )
    project_ids = {
        int(item.project_id or worklog.project_id)
        for item in items
        if item.project_id or worklog.project_id
    }
    for project_id in project_ids:
        await project_service.recalc_progress(session, project_id)


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
