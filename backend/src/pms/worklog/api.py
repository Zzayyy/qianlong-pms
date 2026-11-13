"""工作日志接口：填报、提交、确认、补填审批、评论、催办、统计（设计稿 07）。

v1.1.15 起：一人一天可多条日志（每条绑定一个项目），当日累计工时超阈值**仅提示不禁止**，
补填窗口由参数 `worklog.backfill.maxDays`（默认 5 天）控制。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import DataForbiddenError, ParamError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.notice import service as notice_service
from pms.org.models import SysUser
from pms.worklog import service
from pms.worklog.models import WlComment

router = APIRouter(prefix="/api/v1/worklogs", tags=["工作日志"])


class WorklogIn(BaseModel):
    """日志入参（新增或按 `id` 更新）。"""

    id: int = 0
    logDate: str = Field(min_length=8, max_length=10)
    logType: str = "PROJECT"
    projectId: int = 0
    taskId: int = 0
    totalHours: float = 0
    content: str = ""
    problem: str = ""
    plan: str = ""
    riskFlag: bool = False
    progressAfter: float = 0
    items: list[dict[str, object]] | None = None


class ReasonIn(BaseModel):
    """带意见的入参。"""

    reason: str = ""


class CommentIn(BaseModel):
    """评论入参（`parentId` 非 0 表示回复）。"""

    content: str = Field(min_length=1, max_length=1000)
    parentId: int = 0


class RemindIn(BaseModel):
    """催办入参。"""

    userId: int
    logDate: str = Field(min_length=8, max_length=10)
    content: str = ""


def _out(
    worklog: object,
    project_name: str = "",
    *,
    user_name: str = "",
    real_name: str = "",
    task_name: str = "",
) -> dict[str, object]:
    """日志出参。"""
    from pms.worklog.models import WlWorklog

    assert isinstance(worklog, WlWorklog)
    return {
        "id": worklog.id,
        "worklogNo": worklog.worklog_no,
        "userId": worklog.user_id,
        "userName": user_name,
        "realName": real_name,
        "deptId": worklog.dept_id,
        "logType": worklog.log_type,
        "projectId": worklog.project_id,
        "projectName": project_name,
        "taskId": worklog.task_id,
        "taskName": task_name,
        "logDate": worklog.log_date,
        "totalHours": float(worklog.total_hours),
        "content": worklog.content,
        "problem": worklog.problem,
        "plan": worklog.plan,
        "status": worklog.status,
        "isLate": worklog.is_late,
        "lateDays": worklog.late_days,
        "riskFlag": worklog.risk_flag,
        "submitTime": worklog.submit_time.isoformat() if worklog.submit_time else "",
        "confirmTime": worklog.confirm_time.isoformat() if worklog.confirm_time else "",
        "rejectReason": worklog.reject_reason,
    }


@router.get("/options", summary="填报选项")
async def options(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:create"))],
) -> object:
    """补填天数上限、工时阈值与我参与的项目（下拉数据源）。

    注：必须定义在 `/{worklog_id}` 之前，否则会被路径参数路由抢先匹配。
    """
    return ok(await service.fill_options(session, user_id=context.user_id))


@router.get("/day-summary", summary="某天累计工时")
async def day_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    date: Annotated[str, Query(min_length=8, max_length=10)],
    userId: Annotated[int | None, Query()] = None,
) -> object:
    """按人统计某天累计工时；超过阈值返回提示文案（不禁止提交）。"""
    target = userId or context.user_id
    if target != context.user_id and not (context.is_privileged or context.is_dept_head):
        raise DataForbiddenError("无该用户日志访问权限")
    return ok(await service.day_summary(session, user_id=target, log_date=date))


async def _save_worklog(
    body: WorklogIn,
    session: AsyncSession,
    context: AuthContext,
) -> object:
    """保存日志（新增或更新）并返回当日累计提示。"""
    worklog = await service.save_draft(
        session,
        context,
        worklog_id=body.id,
        log_date=body.logDate,
        log_type=body.logType,
        project_id=body.projectId,
        task_id=body.taskId,
        total_hours=body.totalHours,
        content=body.content,
        problem=body.problem,
        plan=body.plan,
        risk_flag=body.riskFlag,
        progress_after=body.progressAfter,
        items=body.items,
    )
    summary = await service.day_summary(
        session, user_id=context.user_id, log_date=body.logDate
    )
    await session.commit()
    return ok(
        {
            "id": worklog.id,
            "worklogNo": worklog.worklog_no,
            "status": worklog.status,
            "totalHours": float(worklog.total_hours),
            "dayTotalHours": summary["totalHours"],
            "warning": summary["warning"],
        }
    )


@router.post("", summary="保存日志草稿")
async def save(
    body: WorklogIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:create"))],
) -> object:
    """保存一条日志（新增）。一人一天可多条，每条选择一个项目。"""
    return await _save_worklog(body, session, context)


@router.put("/{worklog_id}", summary="更新日志")
async def update(
    worklog_id: int,
    body: WorklogIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:create"))],
) -> object:
    """更新自己的草稿 / 被驳回日志（仅本人可改）。"""
    body.id = worklog_id
    return await _save_worklog(body, session, context)


@router.post("/{worklog_id}/submit", summary="提交日志")
async def submit(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:create"))],
) -> object:
    """提交：校验工时与明细合计；T+3 以上进入补填待审批；当日超 8h 仅提示。"""
    worklog = await service.submit(session, worklog_id, context.user_id)
    summary = await service.day_summary(
        session, user_id=worklog.user_id, log_date=str(worklog.log_date)
    )
    await session.commit()
    return ok(
        {
            "id": worklog.id,
            "status": worklog.status,
            "lateDays": worklog.late_days,
            "dayTotalHours": summary["totalHours"],
            "warnHours": summary["warnHours"],
            "warning": summary["warning"],
        }
    )


@router.delete("/{worklog_id}", summary="删除日志草稿")
async def remove(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:create"))],
) -> object:
    """删除自己的草稿/被驳回日志。"""
    await service.delete_worklog(session, worklog_id, context.user_id)
    await session.commit()
    return ok({"id": worklog_id})


@router.post("/{worklog_id}/confirm", summary="确认日志")
async def confirm(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:confirm"))],
) -> object:
    """PM 确认：回填任务工时与进度，生成风险项，重算项目进度。"""
    worklog = await service.confirm(session, worklog_id, context.user_id)
    await session.commit()
    return ok({"id": worklog.id, "status": worklog.status})


@router.post("/{worklog_id}/reject", summary="驳回日志")
async def reject(
    worklog_id: int,
    body: ReasonIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:confirm"))],
) -> object:
    """PM 驳回；已确认的驳回会反向扣减工时。"""
    worklog = await service.reject(session, worklog_id, context.user_id, body.reason)
    await session.commit()
    return ok({"id": worklog.id, "status": worklog.status})


@router.post("/{worklog_id}/unconfirm", summary="撤销确认")
async def unconfirm(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:confirm"))],
) -> object:
    """撤销确认后可修改重提（R-LOG-08）。"""
    worklog = await service.unconfirm(session, worklog_id, context.user_id)
    await session.commit()
    return ok({"id": worklog.id, "status": worklog.status})


@router.post("/{worklog_id}/approve-late", summary="补填审批通过")
async def approve_late(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:confirm"))],
) -> object:
    """逾期补填审批通过：进入待确认。"""
    worklog = await service.approve_late(session, worklog_id, context.user_id)
    await session.commit()
    return ok({"id": worklog.id, "status": worklog.status})


@router.get("", summary="日志列表")
async def list_worklogs(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    scope: Annotated[str, Query(pattern="^(mine|visible)$")] = "visible",
    userId: Annotated[int | None, Query()] = None,
    projectId: Annotated[int | None, Query()] = None,
    status: Annotated[str, Query()] = "",
    keyword: Annotated[str, Query()] = "",
    logType: Annotated[str, Query()] = "",
    excludeUserId: Annotated[int | None, Query()] = None,
    dateFrom: Annotated[str | None, Query()] = None,
    dateTo: Annotated[str | None, Query()] = None,
) -> object:
    """日志列表。

    - `scope=mine`：只返回本人日志（SQL 分页，数据按用户隔离）
    - `scope=visible`：返回当前用户可见范围（本人/下级/部门/项目组），逐条校验后分页
    """
    if scope == "mine":
        target_ids: list[int] = [context.user_id]
        total = await service.count_worklogs(
            session,
            user_ids=target_ids,
            project_id=projectId,
            date_from=dateFrom,
            date_to=dateTo,
            status=status,
            keyword=keyword,
            log_type=logType,
        )
        rows = await service.list_worklogs(
            session,
            user_ids=target_ids,
            project_id=projectId,
            date_from=dateFrom,
            date_to=dateTo,
            status=status,
            keyword=keyword,
            log_type=logType,
            offset=pagination.offset,
            limit=pagination.page_size,
        )
        visible = rows
    else:
        candidates = await service.list_worklogs(
            session,
            user_ids=[userId] if userId else None,
            project_id=projectId,
            date_from=dateFrom,
            date_to=dateTo,
            status=status,
            keyword=keyword,
            log_type=logType,
            exclude_user_id=excludeUserId or 0,
            limit=0,
        )
        matched = [
            row for row in candidates if await service.can_view(session, context, row)
        ]
        total = len(matched)
        visible = matched[pagination.offset : pagination.offset + pagination.page_size]

    names = await service.project_names(session, {row.project_id for row in visible})
    users = await service.user_names(session, {row.user_id for row in visible})
    tasks = await service.task_names(session, {row.task_id for row in visible})
    return paged(
        [
            _out(
                row,
                names.get(row.project_id, ""),
                user_name=users.get(row.user_id, ("", ""))[0],
                real_name=users.get(row.user_id, ("", ""))[1],
                task_name=tasks.get(row.task_id, ""),
            )
            for row in visible
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


_STATUS_LABELS = {
    "DRAFT": "草稿",
    "SUBMITTED": "待确认",
    "PENDING_APPROVE": "补填待审批",
    "CONFIRMED": "已确认",
    "REJECTED": "已驳回",
}


@router.get("/export", summary="导出工作日志")
async def export_worklogs(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    scope: Annotated[str, Query(pattern="^(mine|visible)$")] = "mine",
    userId: Annotated[int | None, Query()] = None,
    projectId: Annotated[int | None, Query()] = None,
    status: Annotated[str, Query()] = "",
    keyword: Annotated[str, Query()] = "",
    logType: Annotated[str, Query()] = "",
    excludeUserId: Annotated[int | None, Query()] = None,
    dateFrom: Annotated[str | None, Query()] = None,
    dateTo: Annotated[str | None, Query()] = None,
) -> Response:
    """按当前筛选条件导出 CSV（UTF-8 BOM，Excel 可直接打开）。"""
    query = {
        "project_id": projectId,
        "date_from": dateFrom,
        "date_to": dateTo,
        "status": status,
        "keyword": keyword,
        "log_type": logType,
        "exclude_user_id": excludeUserId or 0,
        "limit": 0,
    }
    if scope == "mine":
        rows = await service.list_worklogs(
            session, user_ids=[context.user_id], **query
        )
    else:
        candidates = await service.list_worklogs(
            session,
            user_ids=[userId] if userId else None,
            **query,
        )
        rows = [
            row
            for row in candidates
            if await service.can_view(session, context, row)
        ]

    projects = await service.project_names(session, {row.project_id for row in rows})
    users = await service.user_names(session, {row.user_id for row in rows})
    tasks = await service.task_names(session, {row.task_id for row in rows})

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "日期",
            "编号",
            "提交人",
            "类型",
            "项目",
            "任务",
            "工时",
            "状态",
            "补填",
            "补填天数",
            "工作内容",
            "问题与阻塞",
            "明日计划",
            "提交时间",
            "确认时间",
        ]
    )
    for row in rows:
        meta = service.log_type_meta(row.log_type)
        user_name, real_name = users.get(row.user_id, ("", ""))
        submit_at = (
            row.submit_at.strftime("%Y-%m-%d %H:%M:%S")
            if row.submit_at
            else (row.submit_time.isoformat() if row.submit_time else "")
        )
        writer.writerow(
            [
                row.log_date.isoformat() if row.log_date else "",
                row.worklog_no,
                real_name or user_name,
                meta.label,
                (projects.get(row.project_id, "") or "非项目")
                if meta.requires_project
                else meta.label,
                tasks.get(row.task_id, ""),
                float(row.total_hours),
                _STATUS_LABELS.get(row.status, row.status),
                "是" if row.is_late else "否",
                row.late_days,
                row.content,
                row.problem,
                row.plan,
                submit_at,
                row.confirm_time.isoformat() if row.confirm_time else "",
            ]
        )

    content = "\ufeff" + output.getvalue()
    filename = f"worklogs-{date.today().isoformat()}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary", summary="个人工时汇总")
async def summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    period: Annotated[str, Query(pattern="^(day|week|month|custom)$")] = "day",
    dateText: Annotated[str | None, Query(alias="date")] = None,
    dateFrom: Annotated[str | None, Query()] = None,
    dateTo: Annotated[str | None, Query()] = None,
    userId: Annotated[int | None, Query()] = None,
) -> object:
    """按当日 / 本周 / 本月 / 自定义区间汇总个人工时与填报情况。

    注：必须定义在 `/{worklog_id}` 之前，否则会被路径参数路由抢先匹配。
    """
    target = userId or context.user_id
    if target != context.user_id and not (context.is_privileged or context.is_dept_head):
        raise DataForbiddenError("无该用户日志访问权限")
    try:
        anchor = date.fromisoformat(dateText) if dateText else None
        start, end = service.period_bounds(
            period,
            anchor,
            date_from=dateFrom or "",
            date_to=dateTo or "",
        )
    except ValueError as exc:
        raise ParamError("日期格式应为 YYYY-MM-DD") from exc
    data = await service.period_summary(
        session,
        user_id=target,
        date_from=start,
        date_to=end,
        period=period,
    )
    return ok(data)


@router.get("/stats", summary="填写率与及时率")
async def stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    dateFrom: Annotated[str, Query()],
    dateTo: Annotated[str, Query()],
    userId: Annotated[int | None, Query()] = None,
) -> object:
    """个人填写率 / 及时率（R-LOG-12，按自然日去重）。"""
    target = userId or context.user_id
    if target != context.user_id and not (context.is_privileged or context.is_dept_head):
        raise DataForbiddenError("无该用户日志访问权限")
    data = await service.stats(
        session, user_id=target, date_from=dateFrom, date_to=dateTo
    )
    return ok(data)


@router.get("/reminders", summary="催办列表")
async def reminders(
    pagination: Annotated[Pagination, Depends(get_pagination)],
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    status: Annotated[str, Query()] = "OPEN",
    userId: Annotated[int | None, Query()] = None,
) -> object:
    """查看催办提醒：默认本人待处理，管理员可查看指定用户。

    注：必须定义在 `/{worklog_id}` 之前，否则会被路径参数路由抢先匹配。
    """
    target = userId or context.user_id
    if target != context.user_id and not (
        context.is_privileged
        or context.is_dept_head
        or context.has_permission("worklog:manage")
    ):
        raise DataForbiddenError("无该用户催办查看权限")
    total = await service.count_reminders(session, user_id=target, status=status)
    rows = await service.list_reminders(
        session,
        user_id=target,
        status=status,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    users = await service.user_names(session, {row.user_id for row in rows})
    return paged(
        [
            {
                "id": row.id,
                "userId": row.user_id,
                "userName": users.get(row.user_id, ("", ""))[0],
                "realName": users.get(row.user_id, ("", ""))[1],
                "logDate": row.log_date.isoformat() if row.log_date else "",
                "remindType": row.remind_type,
                "content": row.content,
                "status": row.status,
                "createTime": row.create_time.isoformat() if row.create_time else "",
            }
            for row in rows
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/reminder-targets", summary="待催办人员")
async def reminder_targets(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:manage"))],
    dateText: Annotated[str | None, Query(alias="date")] = None,
) -> object:
    """指定日期尚未提交日志、且此前未催办的在岗人员（管理端发起催办用）。"""
    text = dateText or date.today().isoformat()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ParamError("日期格式应为 YYYY-MM-DD") from exc
    dept_ids = (
        None
        if context.is_all_scope
        else sorted(context.visible_dept_ids or {context.dept_id})
    )
    return ok(
        await service.reminder_targets(
            session, log_date=text, dept_ids=dept_ids
        )
    )


@router.get("/{worklog_id}", summary="日志详情")
async def detail(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """日志详情与明细；不可见返回 40302。"""
    worklog = await service.get_worklog(session, worklog_id)
    if not await service.can_view(session, context, worklog):
        raise DataForbiddenError("无该日志访问权限")
    items = await service.list_items(session, worklog_id)
    names = await service.project_names(
        session, {worklog.project_id, *(item.project_id for item in items)}
    )
    tasks = await service.task_names(
        session, {worklog.task_id, *(item.task_id for item in items)}
    )
    users = await service.user_names(session, {worklog.user_id})
    user_name, real_name = users.get(worklog.user_id, ("", ""))
    return ok(
        {
            "worklog": _out(
                worklog,
                names.get(worklog.project_id, ""),
                user_name=user_name,
                real_name=real_name,
                task_name=tasks.get(worklog.task_id, ""),
            ),
            "items": [
                {
                    "projectId": item.project_id,
                    "projectName": names.get(item.project_id, ""),
                    "taskId": item.task_id,
                    "taskName": tasks.get(item.task_id, ""),
                    "hours": float(item.hours),
                    "content": item.content,
                    "progressAfter": float(item.progress_after),
                }
                for item in items
            ],
        }
    )


@router.post("/{worklog_id}/comments", summary="日志评论")
async def comment(
    worklog_id: int,
    body: CommentIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """新增评论（需对该日志有查看权限）。"""
    worklog = await service.get_worklog(session, worklog_id)
    if not await service.can_view(session, context, worklog):
        raise DataForbiddenError("无该日志访问权限")
    row = await service.add_comment(
        session, worklog_id, context, body.content, parent_id=body.parentId
    )

    # 站内通知：日志作者 + 被回复评论作者（自己评论自己不通知）
    receivers = {worklog.user_id}
    parent = (
        await session.get(WlComment, body.parentId) if body.parentId else None
    )
    if parent is not None:
        receivers.add(parent.user_id)
    snippet = body.content.strip()[:80]
    actor = context.real_name or context.username
    for receiver in receivers:
        if receiver == context.user_id:
            continue
        if receiver == worklog.user_id:
            title = "工作日志收到新评论"
            content = f"{actor} 评论了你的日志 {worklog.worklog_no}：{snippet}"
        else:
            title = "你的评论收到回复"
            content = f"{actor} 回复了你在日志 {worklog.worklog_no} 中的评论：{snippet}"
        await notice_service.create_notice(
            session,
            receiver_id=receiver,
            title=title,
            content=content,
            notice_type="COMMENT",
            biz_type="WORKLOG",
            biz_id=worklog_id,
        )

    await session.commit()
    return ok({"id": row.id, "parentId": row.parent_id})


@router.get("/{worklog_id}/comments", summary="评论列表")
async def comments(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """评论列表（带评论人姓名）。"""
    worklog = await service.get_worklog(session, worklog_id)
    if not await service.can_view(session, context, worklog):
        raise DataForbiddenError("无该日志访问权限")
    rows = await service.list_comments(session, worklog_id)
    users = await service.user_names(session, {row.user_id for row in rows})
    return ok(
        [
            {
                "id": row.id,
                "userId": row.user_id,
                "userName": users.get(row.user_id, ("", ""))[0],
                "realName": users.get(row.user_id, ("", ""))[1],
                "content": row.content,
                "parentId": row.parent_id,
                "createTime": row.create_time.isoformat() if row.create_time else "",
            }
            for row in rows
        ]
    )


@router.delete("/{worklog_id}/comments/{comment_id}", summary="删除评论")
async def delete_comment(
    worklog_id: int,
    comment_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """删除评论：本人可删；`worklog:manage` 可管理他人评论，根评论级联删除回复。"""
    worklog = await service.get_worklog(session, worklog_id)
    if not await service.can_view(session, context, worklog):
        raise DataForbiddenError("无该日志访问权限")
    await service.delete_comment(
        session,
        worklog_id,
        comment_id,
        context.user_id,
        can_manage=context.has_permission("worklog:manage"),
    )
    await session.commit()
    return ok({"id": comment_id})


@router.post("/reminders/read-all", summary="全部催办已读")
async def read_all_reminders(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """把本人全部待处理催办标记为已读。"""
    count = await service.mark_all_reminders_read(session, context.user_id)
    await session.commit()
    return ok({"count": count})


@router.post("/reminders/{reminder_id}/read", summary="催办已读")
async def read_reminder(
    reminder_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """标记本人某条催办已读。"""
    row = await service.mark_reminder_read(session, reminder_id, context.user_id)
    await session.commit()
    return ok({"id": row.id, "status": row.status})


@router.post("/reminders", summary="催办")
async def remind(
    body: RemindIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:manage"))],
) -> object:
    """手动催办（自动催办由定时任务调用服务层）。"""
    target = await session.get(SysUser, body.userId)
    if target is None or target.deleted or target.status != "ENABLED":
        raise ParamError("催办对象不存在或已停用")
    if not context.can_see_dept(target.dept_id):
        raise DataForbiddenError("无该用户催办权限")
    content = body.content.strip() or f"请补填 {body.logDate} 的工作日志"
    row = await service.create_reminder(
        session,
        user_id=body.userId,
        log_date=body.logDate,
        remind_type="MANUAL",
        remind_by=context.user_id,
        content=content,
    )
    if target.id != context.user_id:
        await notice_service.create_notice(
            session,
            receiver_id=target.id,
            title="工作日志催办",
            content=content,
            notice_type="REMINDER",
            biz_type="WORKLOG_REMINDER",
            biz_id=row.id,
        )
    await session.commit()
    return ok({"id": row.id})
