"""CRM 服务：客户、联系人、商机、跟进、商机转项目（设计稿 04 §4.2.1）。"""

from __future__ import annotations

from datetime import date
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ConflictError, NotFoundError
from pms.core.context import AuthContext
from pms.crm.models import (
    OpportunityStage,
    CrmContact,
    CrmCustomer,
    CrmFollow,
    CrmOpportunity,
    CustomerStatus,
    OpportunityStatus,
)
from pms.project import service as project_service
from pms.system.config_service import ConfigService

_CUSTOMER_PREFIX: Final[str] = "CUS"
_OPP_PREFIX: Final[str] = "OPP"
_DEFAULT_WIN_STAGE: Final[str] = "WON"


async def next_customer_code(session: AsyncSession) -> str:
    """生成客户编码 `CUS-0001`。"""
    stmt = select(func.count(CrmCustomer.id)).where(CrmCustomer.deleted == 0)
    result = await session.execute(stmt)
    return f"{_CUSTOMER_PREFIX}-{int(result.scalar_one()) + 1:04d}"


async def next_opportunity_code(session: AsyncSession) -> str:
    """生成商机编码 `OPP-2026-0001`。"""
    year = date.today().year
    pattern = f"{_OPP_PREFIX}-{year}-%"
    stmt = select(func.count(CrmOpportunity.id)).where(
        CrmOpportunity.deleted == 0, CrmOpportunity.opp_code.like(pattern)
    )
    result = await session.execute(stmt)
    return f"{_OPP_PREFIX}-{year}-{int(result.scalar_one()) + 1:04d}"


async def list_customers(
    session: AsyncSession,
    visible: set[int] | None,
    keyword: str = "",
    offset: int = 0,
    limit: int = 20,
) -> list[CrmCustomer]:
    """客户列表（受数据范围约束）。"""
    stmt = select(CrmCustomer).where(CrmCustomer.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmCustomer.owner_dept_id.in_(visible))
    if keyword:
        stmt = stmt.where(CrmCustomer.customer_name.like(f"%{keyword}%"))
    stmt = stmt.order_by(CrmCustomer.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_customers(
    session: AsyncSession, visible: set[int] | None, keyword: str = ""
) -> int:
    """客户总数（受数据范围约束）。"""
    stmt = select(func.count(CrmCustomer.id)).where(CrmCustomer.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmCustomer.owner_dept_id.in_(visible))
    if keyword:
        stmt = stmt.where(CrmCustomer.customer_name.like(f"%{keyword}%"))
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def create_customer(
    session: AsyncSession,
    context: AuthContext,
    *,
    customer_name: str,
    customer_level: str = "C",
    industry: str = "",
    owner_user_id: int = 0,
    owner_dept_id: int = 0,
    contact_name: str = "",
    contact_mobile: str = "",
    contact_email: str = "",
    province: str = "",
    city: str = "",
    address: str = "",
    source: str = "",
    remark: str = "",
) -> CrmCustomer:
    """创建客户（名称唯一校验）。"""
    exists = await session.execute(
        select(CrmCustomer.id).where(
            CrmCustomer.customer_name == customer_name, CrmCustomer.deleted == 0
        )
    )
    if exists.scalar_one_or_none() is not None:
        raise ConflictError(f"客户已存在：{customer_name}")

    customer = CrmCustomer(
        customer_code=await next_customer_code(session),
        customer_name=customer_name,
        customer_level=customer_level,
        industry=industry,
        owner_user_id=owner_user_id or context.user_id,
        owner_dept_id=owner_dept_id or context.dept_id,
        contact_name=contact_name,
        contact_mobile=contact_mobile,
        contact_email=contact_email,
        province=province,
        city=city,
        address=address,
        source=source,
        remark=remark,
        create_by=context.user_id,
    )
    session.add(customer)
    await session.flush()
    return customer


async def list_contacts(session: AsyncSession, customer_id: int) -> list[CrmContact]:
    """客户联系人列表，主联系人优先。"""
    stmt = (
        select(CrmContact)
        .where(CrmContact.customer_id == customer_id, CrmContact.deleted == 0)
        .order_by(CrmContact.is_primary.desc(), CrmContact.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_contact(
    session: AsyncSession,
    context: AuthContext,
    customer_id: int,
    *,
    name: str,
    title: str = "",
    mobile: str = "",
    email: str = "",
    wechat: str = "",
    is_primary: bool = False,
) -> CrmContact:
    """新增联系人；设为主联系人时取消同客户其他主联系人。"""
    if is_primary:
        others = await list_contacts(session, customer_id)
        for item in others:
            item.is_primary = 0
    contact = CrmContact(
        customer_id=customer_id,
        name=name,
        title=title,
        mobile=mobile,
        email=email,
        wechat=wechat,
        is_primary=1 if is_primary else 0,
        create_by=context.user_id,
    )
    session.add(contact)
    await session.flush()
    return contact


async def list_opportunities(
    session: AsyncSession,
    visible: set[int] | None,
    customer_id: int | None = None,
    keyword: str = "",
    offset: int = 0,
    limit: int = 20,
) -> list[CrmOpportunity]:
    """商机列表（受数据范围约束）。"""
    stmt = select(CrmOpportunity).where(CrmOpportunity.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmOpportunity.owner_dept_id.in_(visible))
    if customer_id:
        stmt = stmt.where(CrmOpportunity.customer_id == customer_id)
    if keyword:
        stmt = stmt.where(CrmOpportunity.opp_name.like(f"%{keyword}%"))
    stmt = stmt.order_by(CrmOpportunity.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_opportunities(
    session: AsyncSession,
    visible: set[int] | None,
    customer_id: int | None = None,
    keyword: str = "",
) -> int:
    """商机总数。"""
    stmt = select(func.count(CrmOpportunity.id)).where(CrmOpportunity.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmOpportunity.owner_dept_id.in_(visible))
    if customer_id:
        stmt = stmt.where(CrmOpportunity.customer_id == customer_id)
    if keyword:
        stmt = stmt.where(CrmOpportunity.opp_name.like(f"%{keyword}%"))
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def create_opportunity(
    session: AsyncSession,
    context: AuthContext,
    *,
    opp_name: str,
    customer_id: int,
    expect_amount: float = 0,
    expect_sign_date: str | None = None,
    stage: str = "LEAD",
    win_rate: float = 0,
    source: str = "",
    owner_user_id: int = 0,
    owner_dept_id: int = 0,
    remark: str = "",
) -> CrmOpportunity:
    """创建商机。"""
    opportunity = CrmOpportunity(
        opp_code=await next_opportunity_code(session),
        opp_name=opp_name,
        customer_id=customer_id,
        owner_user_id=owner_user_id or context.user_id,
        owner_dept_id=owner_dept_id or context.dept_id,
        expect_amount=expect_amount,
        expect_sign_date=expect_sign_date,
        stage=stage,
        win_rate=win_rate,
        source=source,
        remark=remark,
        create_by=context.user_id,
    )
    session.add(opportunity)
    await session.flush()
    return opportunity


async def update_stage(
    session: AsyncSession, opportunity_id: int, stage: str, operator_id: int = 0
) -> CrmOpportunity:
    """推进商机阶段（WON/LOST 同步状态）。

    阶段值必须属于 `OpportunityStage`：否则会被静默写入脏数据，
    导致「赢单后仍无法转项目」（例如误传 `WIN`）。
    """
    opportunity = await session.get(CrmOpportunity, opportunity_id)
    if opportunity is None or opportunity.deleted:
        raise NotFoundError("商机不存在")
    normalized = str(stage or "").strip().upper()
    if normalized not in set(OpportunityStage):
        raise BizRuleError(
            f"非法的商机阶段：{stage}（可选 {'/'.join(OpportunityStage)}）"
        )
    opportunity.stage = normalized
    if normalized == OpportunityStatus.WON:
        opportunity.status = OpportunityStatus.WON
    elif normalized == OpportunityStatus.LOST:
        opportunity.status = OpportunityStatus.LOST
    opportunity.update_by = operator_id
    await session.flush()
    return opportunity


async def convert_to_project(
    session: AsyncSession,
    context: AuthContext,
    opportunity_id: int,
    *,
    project_name: str = "",
    pm_id: int = 0,
    plan_start: str | None = None,
    plan_end: str | None = None,
) -> object:
    """商机转项目（设计稿 04：赢单后一键生成项目草稿）。"""
    opportunity = await session.get(CrmOpportunity, opportunity_id)
    if opportunity is None or opportunity.deleted:
        raise NotFoundError("商机不存在")

    config = ConfigService(session)
    win_stage = (await config.get_str("crm.opp.winStage")) or _DEFAULT_WIN_STAGE
    if opportunity.stage != win_stage:
        raise ConflictError(f"商机未到 {win_stage} 阶段，不能转化")
    if opportunity.converted_project_id:
        raise ConflictError("该商机已转化，禁止重复转化")

    customer = await session.get(CrmCustomer, opportunity.customer_id)
    name = project_name or (f"{customer.customer_name}-{opportunity.opp_name}" if customer else opportunity.opp_name)

    project = await project_service.create_project(
        session,
        context,
        project_name=name,
        dept_id=opportunity.owner_dept_id,
        pm_id=pm_id or opportunity.owner_user_id,
        sponsor_id=opportunity.owner_user_id,
        customer_id=opportunity.customer_id,
        opportunity_id=opportunity.id,
        contract_amount=float(opportunity.expect_amount),
        plan_start=plan_start,
        plan_end=plan_end,
    )

    opportunity.converted_project_id = project.id
    opportunity.converted_time = date.today()
    opportunity.status = OpportunityStatus.CLOSED
    opportunity.update_by = context.user_id

    if customer is not None and await config.get_bool("crm.convert.autoCooperating"):
        customer.status = CustomerStatus.COOPERATING
        customer.update_by = context.user_id

    await session.flush()
    return project


async def add_follow(
    session: AsyncSession,
    context: AuthContext,
    opportunity_id: int,
    *,
    content: str,
    follow_type: str = "PHONE",
    next_plan: str = "",
) -> CrmFollow:
    """新增商机跟进记录。"""
    follow = CrmFollow(
        opp_id=opportunity_id,
        follow_type=follow_type,
        content=content,
        follow_time=date.today(),
        next_plan=next_plan,
        create_by=context.user_id,
    )
    session.add(follow)
    await session.flush()
    return follow
