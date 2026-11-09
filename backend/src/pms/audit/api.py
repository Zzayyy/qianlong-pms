"""审计留痕接口（设计稿 03 §7 / 11 §4）。

查询维度：
- 操作审计：模块 / 结果 / 操作人 / 关键字（操作、URL、参数、traceId）/ 时间范围
- 登录日志：账号（模糊）/ 状态 / 时间范围

写操作由 `pms.audit.middleware` 自动留痕，本模块只负责查询与按月归档。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.audit.archive import ARCHIVE_TABLES, DEFAULT_KEEP_MONTHS, archive_audit
from pms.common.exceptions import ParamError
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.org.models import SysOperateLog, SysUser
from pms.system.config_service import ConfigService
from pms.system.models import SysLoginLog

router = APIRouter(prefix="/api/v1", tags=["审计留痕"])

_DAY_FORMAT = "%Y-%m-%d"


def _parse_day(value: str | None, label: str) -> datetime | None:
    """解析 `YYYY-MM-DD`；空值返回 None。"""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _DAY_FORMAT)
    except ValueError as exc:
        raise ParamError(f"{label}格式应为 YYYY-MM-DD：{text}") from exc


def _day_range(
    date_from: str | None, date_to: str | None
) -> tuple[datetime | None, datetime | None]:
    """把日期区间转成左闭右开的时间区间（含结束当天）。"""
    start = _parse_day(date_from, "开始日期")
    end = _parse_day(date_to, "结束日期")
    if start and end and start > end:
        raise ParamError("开始日期不能晚于结束日期")
    return start, end + timedelta(days=1) if end else None


def _operate_conditions(
    *,
    module: str = "",
    result: str = "",
    user_id: int = 0,
    keyword: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[ColumnElement[bool]]:
    """构造操作审计查询条件（列表与总数共用）。"""
    conditions: list[ColumnElement[bool]] = [SysOperateLog.deleted == 0]
    if module:
        conditions.append(SysOperateLog.module == module)
    if result:
        conditions.append(SysOperateLog.result == result)
    if user_id:
        conditions.append(SysOperateLog.user_id == user_id)
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        conditions.append(
            or_(
                SysOperateLog.operation.like(like),
                SysOperateLog.url.like(like),
                SysOperateLog.trace_id.like(like),
                SysOperateLog.params.like(like),
            )
        )
    start, end = _day_range(date_from, date_to)
    if start:
        conditions.append(SysOperateLog.create_time >= start)
    if end:
        conditions.append(SysOperateLog.create_time < end)
    return conditions


def _login_conditions(
    *,
    username: str = "",
    status: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[ColumnElement[bool]]:
    """构造登录日志查询条件（列表与总数共用）。"""
    conditions: list[ColumnElement[bool]] = [SysLoginLog.deleted == 0]
    text = (username or "").strip()
    if text:
        conditions.append(SysLoginLog.username.like(f"%{text}%"))
    if status:
        conditions.append(SysLoginLog.status == status)
    start, end = _day_range(date_from, date_to)
    if start:
        conditions.append(SysLoginLog.create_time >= start)
    if end:
        conditions.append(SysLoginLog.create_time < end)
    return conditions


@router.get("/audit/modules", summary="操作审计模块列表")
async def list_audit_modules(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:log:view"))],
) -> object:
    """返回审计日志中出现过的模块（供筛选下拉使用）。"""
    rows = (
        await session.execute(
            select(SysOperateLog.module)
            .where(SysOperateLog.deleted == 0, SysOperateLog.module != "")
            .group_by(SysOperateLog.module)
            .order_by(SysOperateLog.module)
        )
    ).scalars()
    del context
    return ok([str(item) for item in rows.all()])


@router.get("/audit/operate-logs", summary="操作审计查询")
async def list_operate_logs(
    pagination: Annotated[Pagination, Depends(get_pagination)],
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:log:view"))],
    module: Annotated[str, Query()] = "",
    result: Annotated[str, Query()] = "",
    user_id: Annotated[int, Query()] = 0,
    keyword: Annotated[str, Query()] = "",
    dateFrom: Annotated[str | None, Query()] = None,  # noqa: N803 对外参数名
    dateTo: Annotated[str | None, Query()] = None,  # noqa: N803 对外参数名
) -> object:
    """按模块 / 结果 / 操作人 / 关键字 / 时间范围查询操作审计，倒序返回。"""
    conditions = _operate_conditions(
        module=module,
        result=result,
        user_id=user_id,
        keyword=keyword,
        date_from=dateFrom,
        date_to=dateTo,
    )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(SysOperateLog).where(*conditions)
            )
        ).scalar()
        or 0
    )
    rows = (
        await session.execute(
            select(SysOperateLog, SysUser.username, SysUser.real_name)
            .outerjoin(SysUser, SysUser.id == SysOperateLog.user_id)
            .where(*conditions)
            .order_by(SysOperateLog.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
    ).all()
    del context
    return paged(
        [
            {
                "id": row[0].id,
                "module": row[0].module,
                "operation": row[0].operation,
                "method": row[0].method,
                "url": row[0].url,
                "params": row[0].params,
                "result": row[0].result,
                "ip": row[0].ip,
                "userId": row[0].user_id,
                "userName": row[1] or "",
                "realName": row[2] or "",
                "costMs": row[0].cost_ms,
                "traceId": row[0].trace_id,
                "createTime": row[0].create_time.isoformat() if row[0].create_time else "",
            }
            for row in rows
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/audit/login-logs", summary="登录日志查询")
async def list_login_logs(
    pagination: Annotated[Pagination, Depends(get_pagination)],
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:log:view"))],
    username: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    dateFrom: Annotated[str | None, Query()] = None,  # noqa: N803 对外参数名
    dateTo: Annotated[str | None, Query()] = None,  # noqa: N803 对外参数名
) -> object:
    """按账号 / 状态 / 时间范围查询登录日志（成功、失败、登出）。"""
    conditions = _login_conditions(
        username=username,
        status=status,
        date_from=dateFrom,
        date_to=dateTo,
    )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(SysLoginLog).where(*conditions)
            )
        ).scalar()
        or 0
    )
    rows = (
        (
            await session.execute(
                select(SysLoginLog)
                .where(*conditions)
                .order_by(SysLoginLog.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        )
        .scalars()
        .all()
    )
    del context
    return paged(
        [
            {
                "id": row.id,
                "username": row.username,
                "ip": row.ip,
                "userAgent": row.user_agent,
                "status": row.status,
                "message": row.message,
                "traceId": row.trace_id,
                "createTime": row.create_time.isoformat() if row.create_time else "",
            }
            for row in rows
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/audit/archive/policy", summary="审计归档策略")
async def archive_policy(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:log:view"))],
) -> object:
    """返回当前保留月数（`audit.keepMonths`）与参与归档的表。"""
    keep_months = await ConfigService(session).get_int("audit.keepMonths")
    del context
    return ok(
        {
            "keepMonths": max(1, keep_months),
            "defaultKeepMonths": DEFAULT_KEEP_MONTHS,
            "tables": list(ARCHIVE_TABLES),
        }
    )


class ArchiveIn(BaseModel):
    """归档入参。"""

    keepMonths: int | None = Field(default=None, ge=1, le=120)
    dryRun: bool = True


@router.post("/audit/archive", summary="审计表按月归档")
async def archive_logs(
    body: ArchiveIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("sys:config"))],
) -> object:
    """手动归档：默认预演（`dryRun=true`），确认后再置 false 真正搬移。"""
    keep_months = body.keepMonths or await ConfigService(session).get_int("audit.keepMonths")
    report = await archive_audit(
        session,
        keep_months=max(1, keep_months),
        dry_run=body.dryRun,
    )
    del context
    return ok(report)
