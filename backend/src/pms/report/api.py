"""统计看板接口：公司 / 部门 / 项目 / 个人（设计稿 08）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import DataForbiddenError
from pms.common.response import ok
from pms.core.context import AuthContext
from pms.core.deps import get_session, require_permissions
from pms.org.models import SysDept
from pms.report import service

router = APIRouter(prefix="/api/v1/reports", tags=["统计看板"])


class AggregateIn(BaseModel):
    """日聚合入参。"""

    statDate: str = ""


@router.get("/company", summary="公司看板")
async def company(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:view"))],
) -> object:
    """全公司项目汇总、部门分布与延期 Top10。"""
    return ok(await service.company_dashboard(session))


@router.get("/depts", summary="看板可选部门")
async def depts(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:view"))],
) -> object:
    """返回当前用户数据范围内可查看的部门（部门看板筛选器数据源）。"""
    result = await session.execute(
        select(SysDept)
        .where(SysDept.deleted == 0)
        .order_by(SysDept.level, SysDept.sort, SysDept.id)
    )
    rows = [
        {
            "id": dept.id,
            "parentId": dept.parent_id,
            "deptName": dept.dept_name,
        }
        for dept in result.scalars().all()
        if context.can_see_dept(dept.id)
    ]
    return ok(rows)


@router.get("/dept", summary="部门看板")
async def dept(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:view"))],
    deptIds: Annotated[str, Query()] = "",
) -> object:
    """按部门看板；不传 `deptIds` 时默认当前用户所属部门。

    仅允许查看数据范围内的部门，越权查询返回 40302。
    """
    ids = [int(item) for item in deptIds.split(",") if item.strip().isdigit()]
    if not ids:
        ids = [context.dept_id]
    if any(not context.can_see_dept(dept_id) for dept_id in ids):
        raise DataForbiddenError("无该部门看板访问权限")
    return ok(await service.dept_dashboard(session, ids))


@router.get("/project/{project_id}", summary="项目看板")
async def project(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:view"))],
) -> object:
    """项目看板：指标 + 阶段 + 里程碑。"""
    return ok(await service.project_dashboard(session, project_id))


@router.get("/personal", summary="个人看板")
async def personal(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:view"))],
    dateFrom: Annotated[str, Query()],
    dateTo: Annotated[str, Query()],
    userId: Annotated[int | None, Query()] = None,
) -> object:
    """个人工时、项目分布、填写率与及时率。"""
    return ok(
        await service.personal_summary(
            session, user_id=userId or context.user_id, date_from=dateFrom, date_to=dateTo
        )
    )


@router.post("/aggregate", summary="日预聚合")
async def aggregate(
    body: AggregateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:export"))],
) -> object:
    """按天生成项目与工时快照（定时任务可调用服务层）。"""
    return ok(await service.aggregate_daily(session, body.statDate or None))
