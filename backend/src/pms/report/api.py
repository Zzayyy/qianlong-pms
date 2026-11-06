"""统计看板接口：公司 / 部门 / 项目 / 个人（设计稿 08）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.response import ok
from pms.core.context import AuthContext
from pms.core.deps import get_session, require_permissions
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


@router.get("/dept", summary="部门看板")
async def dept(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("report:view"))],
    deptIds: Annotated[str, Query()] = "",
) -> object:
    """按部门看板；不传 `deptIds` 时按当前用户可见部门。"""
    ids = [int(item) for item in deptIds.split(",") if item.strip().isdigit()]
    if not ids:
        ids = [context.dept_id]
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
