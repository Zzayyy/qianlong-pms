"""CRM 服务：客户、联系人、商机、跟进、商机转项目（设计稿 04 §4.2.1）。"""

from __future__ import annotations

from datetime import date
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ConflictError, NotFoundError
from pms.core.context import AuthContext
from pms.crm.models import (
    CrmContact,
    CrmCustomer,
    CrmFollow,
    CrmOpportunity,
    CustomerStatus,
    OpportunityStage,
    OpportunityStatus,
)
from pms.org.models import SysUser
from pms.project import service as project_service
from pms.system.config_service import ConfigService

_CUSTOMER_PREFIX: Final[str] = "CUS"
_OPP_PREFIX: Final[str] = "OPP"
_DEFAULT_WIN_STAGE: Final[str] = "WON"
_CUSTOMER_LEVELS: Final[frozenset[str]] = frozenset({"A", "B", "C"})
_STATUS_VALUES: Final[frozenset[str]] = frozenset(item.value for item in CustomerStatus)
_STAGE_VALUES: Final[frozenset[str]] = frozenset(item.value for item in OpportunityStage)
_OPP_STATUS_VALUES: Final[frozenset[str]] = frozenset(item.value for item in OpportunityStatus)


def _enum_value(value: str, allowed: frozenset[str], label: str) -> str:
    """校验并归一化枚举值，避免脏值落库。"""
    normalized = str(value or "").strip().upper()
    if normalized not in allowed:
        raise BizRuleError(f"非法的{label}：{value}（可选 {'/'.join(sorted(allowed))}）")
    return normalized


def _keyword_like(keyword: str) -> str:
    """关键字模糊匹配串。"""
    return f"%{keyword.strip()}%"


async def next_customer_code(session: AsyncSession) -> str:
    """生成客户编码 `CUS-0001`（取已用最大序号 +1，删除后也不复用）。"""
    result = await session.execute(
        select(CrmCustomer.customer_code).where(
            CrmCustomer.customer_code.like(f"{_CUSTOMER_PREFIX}-%")
        )
    )
    used: list[int] = []
    for code in result.scalars():
        suffix = str(code or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            used.append(int(suffix))
    return f"{_CUSTOMER_PREFIX}-{max(used, default=0) + 1:04d}"


async def next_opportunity_code(session: AsyncSession) -> str:
    """生成商机编码 `OPP-2026-0001`（按年度序号递增）。"""
    year = date.today().year
    pattern = f"{_OPP_PREFIX}-{year}-%"
    result = await session.execute(
        select(CrmOpportunity.opp_code).where(CrmOpportunity.opp_code.like(pattern))
    )
    used: list[int] = []
    for code in result.scalars():
        suffix = str(code or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            used.append(int(suffix))
    return f"{_OPP_PREFIX}-{year}-{max(used, default=0) + 1:04d}"


async def get_customer(session: AsyncSession, customer_id: int) -> CrmCustomer:
    """取客户，不存在或已删除时抛 `NotFoundError`。"""
    customer = await session.get(CrmCustomer, customer_id)
    if customer is None or customer.deleted:
        raise NotFoundError("客户不存在")
    return customer


async def list_customers(
    session: AsyncSession,
    visible: set[int] | None,
    keyword: str = "",
    offset: int = 0,
    limit: int = 20,
    status: str = "",
    level: str = "",
    owner_id: int = 0,
) -> list[CrmCustomer]:
    """客户列表（受数据范围约束，支持状态/等级/负责人筛选）。"""
    stmt = select(CrmCustomer).where(CrmCustomer.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmCustomer.owner_dept_id.in_(visible))
    if keyword:
        like = _keyword_like(keyword)
        stmt = stmt.where(
            or_(
                CrmCustomer.customer_name.like(like),
                CrmCustomer.customer_code.like(like),
                CrmCustomer.contact_name.like(like),
                CrmCustomer.contact_mobile.like(like),
            )
        )
    if status:
        stmt = stmt.where(CrmCustomer.status == _enum_value(status, _STATUS_VALUES, "客户状态"))
    if level:
        stmt = stmt.where(
            CrmCustomer.customer_level == _enum_value(level, _CUSTOMER_LEVELS, "客户等级")
        )
    if owner_id:
        stmt = stmt.where(CrmCustomer.owner_user_id == owner_id)
    stmt = stmt.order_by(CrmCustomer.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_customers(
    session: AsyncSession,
    visible: set[int] | None,
    keyword: str = "",
    status: str = "",
    level: str = "",
    owner_id: int = 0,
) -> int:
    """客户总数（筛选条件与列表保持一致）。"""
    stmt = select(func.count(CrmCustomer.id)).where(CrmCustomer.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmCustomer.owner_dept_id.in_(visible))
    if keyword:
        like = _keyword_like(keyword)
        stmt = stmt.where(
            or_(
                CrmCustomer.customer_name.like(like),
                CrmCustomer.customer_code.like(like),
                CrmCustomer.contact_name.like(like),
                CrmCustomer.contact_mobile.like(like),
            )
        )
    if status:
        stmt = stmt.where(CrmCustomer.status == _enum_value(status, _STATUS_VALUES, "客户状态"))
    if level:
        stmt = stmt.where(
            CrmCustomer.customer_level == _enum_value(level, _CUSTOMER_LEVELS, "客户等级")
        )
    if owner_id:
        stmt = stmt.where(CrmCustomer.owner_user_id == owner_id)
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
    status: str = "POTENTIAL",
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
        customer_level=_enum_value(customer_level or "C", _CUSTOMER_LEVELS, "客户等级"),
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
        status=_enum_value(status or "POTENTIAL", _STATUS_VALUES, "客户状态"),
        remark=remark,
        create_by=context.user_id,
    )
    session.add(customer)
    await session.flush()
    return customer


async def update_customer(
    session: AsyncSession,
    context: AuthContext,
    customer_id: int,
    *,
    customer_name: str | None = None,
    customer_level: str | None = None,
    industry: str | None = None,
    owner_user_id: int | None = None,
    owner_dept_id: int | None = None,
    contact_name: str | None = None,
    contact_mobile: str | None = None,
    contact_email: str | None = None,
    province: str | None = None,
    city: str | None = None,
    address: str | None = None,
    source: str | None = None,
    status: str | None = None,
    remark: str | None = None,
) -> CrmCustomer:
    """编辑客户（未传字段保持不变，名称变更时重新校验唯一性）。"""
    customer = await get_customer(session, customer_id)
    if customer_name is not None and customer_name != customer.customer_name:
        exists = await session.execute(
            select(CrmCustomer.id).where(
                CrmCustomer.customer_name == customer_name,
                CrmCustomer.deleted == 0,
                CrmCustomer.id != customer_id,
            )
        )
        if exists.scalar_one_or_none() is not None:
            raise ConflictError(f"客户已存在：{customer_name}")
        customer.customer_name = customer_name
    if customer_level is not None:
        customer.customer_level = _enum_value(customer_level, _CUSTOMER_LEVELS, "客户等级")
    if industry is not None:
        customer.industry = industry
    if owner_user_id is not None:
        customer.owner_user_id = owner_user_id
    if owner_dept_id is not None:
        customer.owner_dept_id = owner_dept_id
    if contact_name is not None:
        customer.contact_name = contact_name
    if contact_mobile is not None:
        customer.contact_mobile = contact_mobile
    if contact_email is not None:
        customer.contact_email = contact_email
    if province is not None:
        customer.province = province
    if city is not None:
        customer.city = city
    if address is not None:
        customer.address = address
    if source is not None:
        customer.source = source
    if status is not None:
        customer.status = _enum_value(status, _STATUS_VALUES, "客户状态")
    if remark is not None:
        customer.remark = remark
    customer.update_by = context.user_id
    await session.flush()
    return customer


async def set_customer_status(
    session: AsyncSession, context: AuthContext, customer_id: int, status: str
) -> CrmCustomer:
    """修改客户状态（潜在 / 合作中 / 流失 / 黑名单）。"""
    customer = await get_customer(session, customer_id)
    customer.status = _enum_value(status, _STATUS_VALUES, "客户状态")
    customer.update_by = context.user_id
    await session.flush()
    return customer


async def delete_customer(
    session: AsyncSession, context: AuthContext, customer_id: int
) -> CrmCustomer:
    """逻辑删除客户（存在未删除商机时禁止，避免商机悬空）。"""
    customer = await get_customer(session, customer_id)
    count = await session.execute(
        select(func.count(CrmOpportunity.id)).where(
            CrmOpportunity.customer_id == customer_id, CrmOpportunity.deleted == 0
        )
    )
    if int(count.scalar_one()) > 0:
        raise ConflictError("该客户下仍有商机，请先删除或转移商机")
    for contact in await list_contacts(session, customer_id):
        contact.deleted = 1
        contact.update_by = context.user_id
    customer.deleted = 1
    customer.update_by = context.user_id
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


async def get_contact(session: AsyncSession, contact_id: int) -> CrmContact:
    """取联系人。"""
    contact = await session.get(CrmContact, contact_id)
    if contact is None or contact.deleted:
        raise NotFoundError("联系人不存在")
    return contact


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
    remark: str = "",
) -> CrmContact:
    """新增联系人；设为主联系人时取消同客户其他主联系人。"""
    await get_customer(session, customer_id)
    if is_primary:
        for item in await list_contacts(session, customer_id):
            item.is_primary = 0
    contact = CrmContact(
        customer_id=customer_id,
        name=name,
        title=title,
        mobile=mobile,
        email=email,
        wechat=wechat,
        is_primary=1 if is_primary else 0,
        remark=remark,
        create_by=context.user_id,
    )
    session.add(contact)
    await session.flush()
    return contact


async def update_contact(
    session: AsyncSession,
    context: AuthContext,
    contact_id: int,
    *,
    name: str | None = None,
    title: str | None = None,
    mobile: str | None = None,
    email: str | None = None,
    wechat: str | None = None,
    is_primary: bool | None = None,
    remark: str | None = None,
) -> CrmContact:
    """编辑联系人；设为主联系人时取消同客户其他主联系人。"""
    contact = await get_contact(session, contact_id)
    if name is not None:
        contact.name = name
    if title is not None:
        contact.title = title
    if mobile is not None:
        contact.mobile = mobile
    if email is not None:
        contact.email = email
    if wechat is not None:
        contact.wechat = wechat
    if remark is not None:
        contact.remark = remark
    if is_primary is not None:
        if is_primary:
            for item in await list_contacts(session, contact.customer_id):
                item.is_primary = 1 if item.id == contact_id else 0
        else:
            contact.is_primary = 0
    contact.update_by = context.user_id
    await session.flush()
    return contact


async def delete_contact(
    session: AsyncSession, context: AuthContext, contact_id: int
) -> CrmContact:
    """逻辑删除联系人。"""
    contact = await get_contact(session, contact_id)
    contact.deleted = 1
    contact.update_by = context.user_id
    await session.flush()
    return contact


async def get_opportunity(session: AsyncSession, opportunity_id: int) -> CrmOpportunity:
    """取商机，不存在或已删除时抛 `NotFoundError`。"""
    opportunity = await session.get(CrmOpportunity, opportunity_id)
    if opportunity is None or opportunity.deleted:
        raise NotFoundError("商机不存在")
    return opportunity


async def list_opportunities(
    session: AsyncSession,
    visible: set[int] | None,
    customer_id: int | None = None,
    keyword: str = "",
    offset: int = 0,
    limit: int = 20,
    stage: str = "",
    status: str = "",
    owner_id: int = 0,
) -> list[CrmOpportunity]:
    """商机列表（受数据范围约束，支持阶段/状态/负责人筛选）。"""
    stmt = select(CrmOpportunity).where(CrmOpportunity.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmOpportunity.owner_dept_id.in_(visible))
    if customer_id:
        stmt = stmt.where(CrmOpportunity.customer_id == customer_id)
    if keyword:
        like = _keyword_like(keyword)
        stmt = stmt.where(
            or_(CrmOpportunity.opp_name.like(like), CrmOpportunity.opp_code.like(like))
        )
    if stage:
        stmt = stmt.where(CrmOpportunity.stage == _enum_value(stage, _STAGE_VALUES, "商机阶段"))
    if status:
        stmt = stmt.where(
            CrmOpportunity.status == _enum_value(status, _OPP_STATUS_VALUES, "商机状态")
        )
    if owner_id:
        stmt = stmt.where(CrmOpportunity.owner_user_id == owner_id)
    stmt = stmt.order_by(CrmOpportunity.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_opportunities(
    session: AsyncSession,
    visible: set[int] | None,
    customer_id: int | None = None,
    keyword: str = "",
    stage: str = "",
    status: str = "",
    owner_id: int = 0,
) -> int:
    """商机总数（筛选条件与列表保持一致）。"""
    stmt = select(func.count(CrmOpportunity.id)).where(CrmOpportunity.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmOpportunity.owner_dept_id.in_(visible))
    if customer_id:
        stmt = stmt.where(CrmOpportunity.customer_id == customer_id)
    if keyword:
        like = _keyword_like(keyword)
        stmt = stmt.where(
            or_(CrmOpportunity.opp_name.like(like), CrmOpportunity.opp_code.like(like))
        )
    if stage:
        stmt = stmt.where(CrmOpportunity.stage == _enum_value(stage, _STAGE_VALUES, "商机阶段"))
    if status:
        stmt = stmt.where(
            CrmOpportunity.status == _enum_value(status, _OPP_STATUS_VALUES, "商机状态")
        )
    if owner_id:
        stmt = stmt.where(CrmOpportunity.owner_user_id == owner_id)
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
    """创建商机（校验客户存在与阶段/赢率合法）。"""
    await get_customer(session, customer_id)
    normalized_stage = _enum_value(stage or "LEAD", _STAGE_VALUES, "商机阶段")
    status = OpportunityStatus.OPEN.value
    if normalized_stage == OpportunityStage.WON.value:
        status = OpportunityStatus.WON.value
    elif normalized_stage == OpportunityStage.LOST.value:
        status = OpportunityStatus.LOST.value
    opportunity = CrmOpportunity(
        opp_code=await next_opportunity_code(session),
        opp_name=opp_name,
        customer_id=customer_id,
        owner_user_id=owner_user_id or context.user_id,
        owner_dept_id=owner_dept_id or context.dept_id,
        expect_amount=expect_amount,
        expect_sign_date=expect_sign_date or None,
        stage=normalized_stage,
        win_rate=max(0, min(100, float(win_rate))),
        source=source,
        status=status,
        remark=remark,
        create_by=context.user_id,
    )
    session.add(opportunity)
    await session.flush()
    return opportunity


async def update_opportunity(
    session: AsyncSession,
    context: AuthContext,
    opportunity_id: int,
    *,
    opp_name: str | None = None,
    customer_id: int | None = None,
    expect_amount: float | None = None,
    expect_sign_date: str | None = None,
    stage: str | None = None,
    win_rate: float | None = None,
    source: str | None = None,
    status: str | None = None,
    lost_reason: str | None = None,
    owner_user_id: int | None = None,
    owner_dept_id: int | None = None,
    remark: str | None = None,
) -> CrmOpportunity:
    """编辑商机（阶段推进时同步状态）。"""
    opportunity = await get_opportunity(session, opportunity_id)
    if opp_name is not None:
        opportunity.opp_name = opp_name
    if customer_id is not None and customer_id != opportunity.customer_id:
        await get_customer(session, customer_id)
        opportunity.customer_id = customer_id
    if expect_amount is not None:
        opportunity.expect_amount = expect_amount
    if expect_sign_date is not None:
        opportunity.expect_sign_date = expect_sign_date or None
    if stage is not None:
        _apply_stage(opportunity, stage)
    if win_rate is not None:
        opportunity.win_rate = max(0, min(100, float(win_rate)))
    if source is not None:
        opportunity.source = source
    if status is not None:
        opportunity.status = _enum_value(status, _OPP_STATUS_VALUES, "商机状态")
    if lost_reason is not None:
        opportunity.lost_reason = lost_reason
    if owner_user_id is not None:
        opportunity.owner_user_id = owner_user_id
    if owner_dept_id is not None:
        opportunity.owner_dept_id = owner_dept_id
    if remark is not None:
        opportunity.remark = remark
    opportunity.update_by = context.user_id
    await session.flush()
    return opportunity


def _apply_stage(opportunity: CrmOpportunity, stage: str) -> None:
    """写入阶段并同步商机状态（WON/LOST 联动）。"""
    normalized = _enum_value(stage, _STAGE_VALUES, "商机阶段")
    opportunity.stage = normalized
    if normalized == OpportunityStage.WON.value:
        opportunity.status = OpportunityStatus.WON.value
    elif normalized == OpportunityStage.LOST.value:
        opportunity.status = OpportunityStatus.LOST.value
    elif (
        opportunity.status in {OpportunityStatus.WON.value, OpportunityStatus.LOST.value}
        and not opportunity.converted_project_id
    ):
        opportunity.status = OpportunityStatus.OPEN.value


async def update_stage(
    session: AsyncSession,
    opportunity_id: int,
    stage: str,
    operator_id: int = 0,
    *,
    lost_reason: str = "",
) -> CrmOpportunity:
    """推进商机阶段（WON/LOST 同步状态）。"""
    opportunity = await get_opportunity(session, opportunity_id)
    _apply_stage(opportunity, stage)
    if lost_reason:
        opportunity.lost_reason = lost_reason
    opportunity.update_by = operator_id
    await session.flush()
    return opportunity


async def set_opportunity_status(
    session: AsyncSession,
    context: AuthContext,
    opportunity_id: int,
    status: str,
    lost_reason: str = "",
) -> CrmOpportunity:
    """修改商机状态（赢单/输单时同步阶段，输单可记录原因）。"""
    opportunity = await get_opportunity(session, opportunity_id)
    normalized = _enum_value(status, _OPP_STATUS_VALUES, "商机状态")
    opportunity.status = normalized
    if normalized == OpportunityStatus.WON.value:
        opportunity.stage = OpportunityStage.WON.value
    elif normalized == OpportunityStatus.LOST.value:
        opportunity.stage = OpportunityStage.LOST.value
        if lost_reason:
            opportunity.lost_reason = lost_reason
    opportunity.update_by = context.user_id
    await session.flush()
    return opportunity


async def delete_opportunity(
    session: AsyncSession, context: AuthContext, opportunity_id: int
) -> CrmOpportunity:
    """逻辑删除商机（已转项目的商机禁止删除）。"""
    opportunity = await get_opportunity(session, opportunity_id)
    if opportunity.converted_project_id:
        raise ConflictError("该商机已转为项目，禁止删除")
    opportunity.deleted = 1
    opportunity.update_by = context.user_id
    await session.flush()
    return opportunity


async def list_follows(session: AsyncSession, opportunity_id: int) -> list[CrmFollow]:
    """商机跟进记录，按跟进时间倒序。"""
    stmt = (
        select(CrmFollow)
        .where(CrmFollow.opp_id == opportunity_id, CrmFollow.deleted == 0)
        .order_by(CrmFollow.follow_time.desc(), CrmFollow.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_follow(
    session: AsyncSession, context: AuthContext, follow_id: int
) -> CrmFollow:
    """逻辑删除跟进记录。"""
    follow = await session.get(CrmFollow, follow_id)
    if follow is None or follow.deleted:
        raise NotFoundError("跟进记录不存在")
    follow.deleted = 1
    follow.update_by = context.user_id
    await session.flush()
    return follow


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
    opportunity = await get_opportunity(session, opportunity_id)

    config = ConfigService(session)
    win_stage = (await config.get_str("crm.opp.winStage")) or _DEFAULT_WIN_STAGE
    if opportunity.stage != win_stage:
        raise ConflictError(f"商机未到 {win_stage} 阶段，不能转化")
    if opportunity.converted_project_id:
        raise ConflictError("该商机已转化，禁止重复转化")

    customer = await session.get(CrmCustomer, opportunity.customer_id)
    name = (
        project_name
        or (
            f"{customer.customer_name}-{opportunity.opp_name}"
            if customer is not None
            else opportunity.opp_name
        )
    )

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
    opportunity.converted_time = date.today().isoformat()
    opportunity.status = OpportunityStatus.CLOSED.value
    opportunity.update_by = context.user_id

    if customer is not None and await config.get_bool("crm.convert.autoCooperating"):
        customer.status = CustomerStatus.COOPERATING.value
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
    follow_time: str | None = None,
) -> CrmFollow:
    """新增商机跟进记录。"""
    await get_opportunity(session, opportunity_id)
    follow = CrmFollow(
        opp_id=opportunity_id,
        follow_type=str(follow_type or "PHONE").strip().upper(),
        content=content,
        follow_time=follow_time or date.today().isoformat(),
        next_plan=next_plan,
        create_by=context.user_id,
    )
    session.add(follow)
    await session.flush()
    return follow


async def staff_options(
    session: AsyncSession, visible: set[int] | None
) -> list[SysUser]:
    """商机转化/负责人可选人员（按数据范围返回启用用户，供前端下拉）。"""
    stmt = select(SysUser).where(SysUser.deleted == 0, SysUser.status == "ENABLED")
    if visible is not None:
        stmt = stmt.where(SysUser.dept_id.in_(visible))
    stmt = stmt.order_by(SysUser.dept_id, SysUser.id).limit(500)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def crm_summary(
    session: AsyncSession, visible: set[int] | None
) -> dict[str, object]:
    """客户与商机概览（列表顶部统计卡片）。"""
    customer_stmt = select(CrmCustomer.status, func.count(CrmCustomer.id)).where(
        CrmCustomer.deleted == 0
    )
    if visible is not None:
        customer_stmt = customer_stmt.where(CrmCustomer.owner_dept_id.in_(visible))
    customer_rows = (await session.execute(customer_stmt.group_by(CrmCustomer.status))).all()
    customer_map = {str(status): int(count) for status, count in customer_rows}

    opp_stmt = (
        select(
            CrmOpportunity.status,
            func.count(CrmOpportunity.id),
            func.coalesce(func.sum(CrmOpportunity.expect_amount), 0),
        )
        .where(CrmOpportunity.deleted == 0)
    )
    if visible is not None:
        opp_stmt = opp_stmt.where(CrmOpportunity.owner_dept_id.in_(visible))
    opp_rows = (
        await session.execute(
            opp_stmt.group_by(CrmOpportunity.status)
        )
    ).all()

    pipeline_amount = 0.0
    won_amount = 0.0
    opp_map: dict[str, int] = {}
    for status, count, amount in opp_rows:
        key = str(status)
        opp_map[key] = int(count)
        if key == OpportunityStatus.OPEN.value:
            pipeline_amount += float(amount)
        elif key == OpportunityStatus.WON.value:
            won_amount += float(amount)

    return {
        "customers": {
            "total": sum(customer_map.values()),
            "potential": customer_map.get(CustomerStatus.POTENTIAL.value, 0),
            "cooperating": customer_map.get(CustomerStatus.COOPERATING.value, 0),
            "lost": customer_map.get(CustomerStatus.LOST.value, 0),
            "blacklist": customer_map.get(CustomerStatus.BLACKLIST.value, 0),
        },
        "opportunities": {
            "total": sum(opp_map.values()),
            "open": opp_map.get(OpportunityStatus.OPEN.value, 0),
            "won": opp_map.get(OpportunityStatus.WON.value, 0),
            "lost": opp_map.get(OpportunityStatus.LOST.value, 0),
            "closed": opp_map.get(OpportunityStatus.CLOSED.value, 0),
            "pipelineAmount": round(pipeline_amount, 2),
            "wonAmount": round(won_amount, 2),
        },
    }
