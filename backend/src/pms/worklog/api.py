"""工作日志接口：填报、提交、确认、补填审批、评论、催办、统计（设计稿 07）。

v1.1.15 起：一人一天可多条日志（每条绑定一个项目），当日累计工时超阈值**仅提示不禁止**，
补填窗口由参数 `worklog.backfill.maxDays`（默认 5 天）控制。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import DataForbiddenError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.worklog import service

router = APIRouter(prefix="/api/v1/worklogs", tags=["工作日志"])


class WorklogIn(BaseModel):
    """日志入参（新增或按 `id` 更新）。"""

    id: int = 0
    logDate: str = Field(min_length=8, max_length=10)
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
    """评论入参。"""

    content: str = Field(min_length=1, max_length=1000)


class RemindIn(BaseModel):
    """催办入参。"""

    userId: int
    logDate: str = Field(min_length=8, max_length=10)
    content: str = ""


def _out(worklog: object, project_name: str = "") -> dict[str, object]:
    """日志出参。"""
    from pms.worklog.models import WlWorklog

    assert isinstance(worklog, WlWorklog)
    return {
        "id": worklog.id,
        "worklogNo": worklog.worklog_no,
        "userId": worklog.user_id,
        "deptId": worklog.dept_id,
        "projectId": worklog.project_id,
        "projectName": project_name,
        "taskId": worklog.task_id,
        "logDate": worklog.log_date,
        "totalHours": float(worklog.total_hours),
        "content": worklog.content,
        "problem": worklog.problem,
        "plan": worklog.plan,
        "status": worklog.status,
        "isLate": worklog.is_late,
        "lateDays": worklog.late_days,
        "riskFlag": worklog.risk_flag,
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


@router.post("", summary="保存日志草稿")
async def save(
    body: WorklogIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:create"))],
) -> object:
    """保存一条日志（新增或更新）。一人一天可多条，每条选择一个项目。"""
    worklog = await service.save_draft(
        session,
        context,
        worklog_id=body.id,
        log_date=body.logDate,
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
    userId: Annotated[int | None, Query()] = None,
    projectId: Annotated[int | None, Query()] = None,
    dateFrom: Annotated[str | None, Query()] = None,
    dateTo: Annotated[str | None, Query()] = None,
) -> object:
    """日志列表，**逐条按 07 §5 可见性过滤**（本人/下级/部门/项目组）。"""
    rows = await service.list_worklogs(
        session,
        user_ids=[userId] if userId else None,
        project_id=projectId,
        date_from=dateFrom,
        date_to=dateTo,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    visible = [row for row in rows if await service.can_view(session, context, row)]
    names = await service.project_names(session, {row.project_id for row in visible})
    return paged(
        [_out(row, names.get(row.project_id, "")) for row in visible],
        len(visible),
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/stats", summary="填写率与及时率")
async def stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    dateFrom: Annotated[str, Query()],
    dateTo: Annotated[str, Query()],
    userId: Annotated[int | None, Query()] = None,
) -> object:
    """个人填写率 / 及时率（R-LOG-12，按自然日去重）。

    注：必须定义在 `/{worklog_id}` 之前，否则会被路径参数路由抢先匹配。
    """
    data = await service.stats(
        session, user_id=userId or context.user_id, date_from=dateFrom, date_to=dateTo
    )
    return ok(data)


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
    names = await service.project_names(session, {worklog.project_id})
    return ok(
        {
            "worklog": _out(worklog, names.get(worklog.project_id, "")),
            "items": [
                {
                    "projectId": item.project_id,
                    "taskId": item.task_id,
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
    """新增评论。"""
    row = await service.add_comment(session, worklog_id, context, body.content)
    await session.commit()
    return ok({"id": row.id})


@router.get("/{worklog_id}/comments", summary="评论列表")
async def comments(
    worklog_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """评论列表。"""
    rows = await service.list_comments(session, worklog_id)
    return ok([{"id": row.id, "userId": row.user_id, "content": row.content} for row in rows])


@router.post("/reminders", summary="催办")
async def remind(
    body: RemindIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:manage"))],
) -> object:
    """手动催办（自动催办由定时任务调用服务层）。"""
    row = await service.create_reminder(
        session,
        user_id=body.userId,
        log_date=body.logDate,
        remind_type="MANUAL",
        remind_by=context.user_id,
        content=body.content,
    )
    await session.commit()
    return ok({"id": row.id})
