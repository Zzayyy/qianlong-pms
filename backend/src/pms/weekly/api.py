"""周报接口：项目周报 / 个人周总结的 AI 生成、编辑、确认。

权限口径：
- 页面入口复用 `worklog:view`（人人可用）；
- 项目周报的生成 / 编辑 / 确认走项目级校验（项目经理、PMO、系统管理员）；
- 个人周总结只允许本人操作。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import ParamError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.weekly import service
from pms.weekly.rules import WeeklySource

router = APIRouter(prefix="/api/v1/weeklies", tags=["周报总结"])


class GenerateIn(BaseModel):
    """生成周报入参。"""

    scope: str = "PROJECT"
    projectId: int = 0
    weekStart: str = ""


class WeeklyUpdateIn(BaseModel):
    """编辑周报正文。"""

    title: str = ""
    content: str = Field(min_length=1, max_length=20000)


def _week_start(text: str) -> date | None:
    """解析周起始日期（任意一天均可，服务层会归一到周一）。"""
    value = (text or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ParamError("日期格式应为 YYYY-MM-DD") from exc


@router.get("/options", summary="周报初始化数据")
async def options(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """默认周区间、可生成周报的项目、自动任务开关与 AI 配置状态。

    注：必须定义在 `/{report_id}` 之前，否则会被路径参数路由抢先匹配。
    """
    return ok(await service.list_options(session, context))


@router.get("", summary="周报列表")
async def list_weeklies(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    scope: Annotated[str, Query(pattern="^(PROJECT|PERSONAL)$")] = "PROJECT",
    weekStart: Annotated[str, Query()] = "",
    projectId: Annotated[int | None, Query()] = None,
    status: Annotated[str, Query()] = "",
    keyword: Annotated[str, Query()] = "",
) -> object:
    """周报列表：项目周报按项目可见性过滤，个人周总结只返回本人。"""
    items, total = await service.list_reports(
        session,
        context,
        scope=scope,
        week_start=weekStart,
        project_id=projectId or 0,
        status=status,
        keyword=keyword,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return paged(items, total, pagination.page_num, pagination.page_size)


@router.post("/generate", summary="生成周报")
async def generate(
    body: GenerateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """按范围生成（或重新生成）周报：项目周报需项目经理，个人周总结限本人。"""
    project = await service.ensure_can_generate(
        session, context, scope=body.scope, project_id=body.projectId
    )
    owner_id = (project.pm_id or context.user_id) if project else context.user_id
    report = await service.generate(
        session,
        scope=body.scope,
        project_id=body.projectId,
        user_id=owner_id,
        operator_id=context.user_id,
        week_start=_week_start(body.weekStart),
        source=WeeklySource.MANUAL,
    )
    await session.commit()
    return ok(await service.get_report(session, context, report.id))


@router.get("/{report_id}", summary="周报详情")
async def detail(
    report_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """返回周报正文与统计快照。"""
    return ok(await service.get_report(session, context, report_id))


@router.put("/{report_id}", summary="编辑周报")
async def update(
    report_id: int,
    body: WeeklyUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """确认前修改正文（项目经理 / 本人）。"""
    data = await service.update_content(
        session, context, report_id, title=body.title, content=body.content
    )
    await session.commit()
    return ok(data)


@router.post("/{report_id}/confirm", summary="确认周报")
async def confirm(
    report_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("worklog:view"))],
) -> object:
    """确认后归档，不再随日志自动变化。"""
    data = await service.confirm_report(session, context, report_id)
    await session.commit()
    return ok(data)
