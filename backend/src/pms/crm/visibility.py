"""客户与商机的数据可见性判定（口径与项目模块一致：按负责人 / 负责人部门）。

列表接口在 SQL 层按 ``owner_dept_id`` 过滤；详情与写操作需要在拿到实体后
再做一次校验，否则跨部门拿到 ID 即可读写，属于越权。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import DataForbiddenError, NotFoundError
from pms.core.context import AuthContext
from pms.crm import service
from pms.crm.models import CrmContact, CrmCustomer, CrmFollow, CrmOpportunity


def can_view_customer(context: AuthContext, customer: CrmCustomer) -> bool:
    """客户可见性：本人负责，或负责人部门在数据范围内。"""
    if int(customer.owner_user_id or 0) == context.user_id:
        return True
    return context.can_see_dept(int(customer.owner_dept_id or 0))


def ensure_customer_visible(context: AuthContext, customer: CrmCustomer) -> None:
    """不可见时抛数据越权（40302）。"""
    if not can_view_customer(context, customer):
        raise DataForbiddenError("无该客户访问权限")


def can_view_opportunity(context: AuthContext, opportunity: CrmOpportunity) -> bool:
    """商机可见性：本人负责，或负责人部门在数据范围内。"""
    if int(opportunity.owner_user_id or 0) == context.user_id:
        return True
    return context.can_see_dept(int(opportunity.owner_dept_id or 0))


def ensure_opportunity_visible(context: AuthContext, opportunity: CrmOpportunity) -> None:
    """不可见时抛数据越权（40302）。"""
    if not can_view_opportunity(context, opportunity):
        raise DataForbiddenError("无该商机访问权限")


def ensure_dept_assignable(context: AuthContext, dept_id: int) -> None:
    """写入时校验负责人部门不越界，避免把数据写进看不见的部门。"""
    if dept_id and not context.can_see_dept(int(dept_id)):
        raise DataForbiddenError("负责人部门超出可见数据范围")


async def ensure_customer_access(
    session: AsyncSession, context: AuthContext, customer_id: int
) -> CrmCustomer:
    """按 ID 取客户并校验可见性（详情/写接口统一入口）。"""
    customer = await service.get_customer(session, customer_id)
    ensure_customer_visible(context, customer)
    return customer


async def ensure_opportunity_access(
    session: AsyncSession, context: AuthContext, opportunity_id: int
) -> CrmOpportunity:
    """按 ID 取商机并校验可见性（详情/写接口统一入口）。"""
    opportunity = await service.get_opportunity(session, opportunity_id)
    ensure_opportunity_visible(context, opportunity)
    return opportunity


async def ensure_contact_access(
    session: AsyncSession, context: AuthContext, contact_id: int
) -> CrmContact:
    """按 ID 取联系人，并按所属客户校验可见性。"""
    contact = await service.get_contact(session, contact_id)
    await ensure_customer_access(session, context, int(contact.customer_id))
    return contact


async def ensure_follow_access(
    session: AsyncSession, context: AuthContext, follow_id: int
) -> CrmFollow:
    """按 ID 取跟进记录，并按所属商机校验可见性。"""
    follow = await session.get(CrmFollow, follow_id)
    if follow is None or follow.deleted:
        raise NotFoundError("跟进记录不存在")
    await ensure_opportunity_access(session, context, int(follow.opp_id))
    return follow
