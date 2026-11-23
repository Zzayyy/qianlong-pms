"""CRM 服务：客户、联系人、商机、跟进、商机转项目（设计稿 04 §4.2.1）。"""

from __future__ import annotations

from datetime import date
from typing import Final

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.exceptions import BizRuleError, ConflictError, NotFoundError
from pms.core.context import AuthContext
from pms.crm.models import (
    CrmContact,
    CrmCustomer,
    CrmCustomerProduct,
    CrmFollow,
    CrmOpportunity,
    CrmProduct,
    CrmRequirement,
    CrmRequirementFile,
    CustomerStatus,
    OpportunityStage,
    OpportunityStatus,
    ProductStatus,
    RequirementPriority,
    RequirementStatus,
)
from pms.file.storage import resolve_storage_path, save_upload
from pms.org.models import SysUser
from pms.project import service as project_service
from pms.system.config_service import ConfigService
from pms.system.models import SysFile

_CUSTOMER_PREFIX: Final[str] = "CUS"
_OPP_PREFIX: Final[str] = "OPP"
_REQ_PREFIX: Final[str] = "REQ"
#: 需求附件磁盘目录（不挂项目，单独一个根目录便于管理员翻阅）
_REQ_UPLOAD_FOLDER: Final[str] = "requirements"
_DEFAULT_WIN_STAGE: Final[str] = "WON"
_CUSTOMER_LEVELS: Final[frozenset[str]] = frozenset({"A", "B", "C"})
_STATUS_VALUES: Final[frozenset[str]] = frozenset(item.value for item in CustomerStatus)
_STAGE_VALUES: Final[frozenset[str]] = frozenset(item.value for item in OpportunityStage)
_OPP_STATUS_VALUES: Final[frozenset[str]] = frozenset(item.value for item in OpportunityStatus)
_REQ_STATUS_VALUES: Final[frozenset[str]] = frozenset(item.value for item in RequirementStatus)
_REQ_PRIORITY_VALUES: Final[frozenset[str]] = frozenset(
    item.value for item in RequirementPriority
)


def _enum_value(value: str, allowed: frozenset[str], label: str) -> str:
    """校验并归一化枚举值，避免脏值落库。"""
    normalized = str(value or "").strip().upper()
    if normalized not in allowed:
        raise BizRuleError(f"非法的{label}：{value}（可选 {'/'.join(sorted(allowed))}）")
    return normalized


def _keyword_like(keyword: str) -> str:
    """关键字模糊匹配串。"""
    return f"%{keyword.strip()}%"


async def _win_stage(config: ConfigService) -> str:
    """赢单阶段编码（参数 `crm.opp.winStage` 可调，统一大写便于与库中值比较）。"""
    value = await config.get_str("crm.opp.winStage")
    return str(value or _DEFAULT_WIN_STAGE).strip().upper()


async def crm_options(session: AsyncSession) -> dict[str, object]:
    """客户与商机页面参数（前端据此判断能否转项目，避免阶段编码硬编码）。"""
    return {"winStage": await _win_stage(ConfigService(session))}


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


async def next_requirement_code(session: AsyncSession) -> str:
    """生成原始需求编码 `REQ-2026-0001`（按年度序号递增）。"""
    year = date.today().year
    pattern = f"{_REQ_PREFIX}-{year}-%"
    result = await session.execute(
        select(CrmRequirement.req_code).where(CrmRequirement.req_code.like(pattern))
    )
    used: list[int] = []
    for code in result.scalars():
        suffix = str(code or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            used.append(int(suffix))
    return f"{_REQ_PREFIX}-{year}-{max(used, default=0) + 1:04d}"


async def get_customer(session: AsyncSession, customer_id: int) -> CrmCustomer:
    """取客户，不存在或已删除时抛 `NotFoundError`。"""
    customer = await session.get(CrmCustomer, customer_id)
    if customer is None or customer.deleted:
        raise NotFoundError("客户不存在")
    return customer


async def _primary_contact(session: AsyncSession, customer_id: int) -> CrmContact | None:
    """取客户当前的主联系人（最多一条）。"""
    stmt = (
        select(CrmContact)
        .where(
            CrmContact.customer_id == customer_id,
            CrmContact.deleted == 0,
            CrmContact.is_primary == 1,
        )
        .order_by(CrmContact.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


def _apply_snapshot(customer: CrmCustomer, contact: CrmContact) -> None:
    """把主联系人写回客户快照字段（列表展示用，避免两处数据不一致）。"""
    customer.contact_name = contact.name or ""
    customer.contact_mobile = contact.mobile or ""
    customer.contact_email = contact.email or ""


async def _sync_primary_contact(
    session: AsyncSession,
    context: AuthContext,
    customer: CrmCustomer,
    *,
    name: str | None = None,
    mobile: str | None = None,
    email: str | None = None,
) -> CrmContact | None:
    """客户表单里的联系人字段与主联系人同源双向：没有主联系人且填了姓名则新建。"""
    contact = await _primary_contact(session, customer.id)
    if contact is None:
        if not str(name or "").strip():
            return None
        contact = CrmContact(
            customer_id=customer.id,
            name=str(name).strip(),
            mobile=mobile or "",
            email=email or "",
            is_primary=1,
            create_by=context.user_id,
        )
        session.add(contact)
        await session.flush()
        return contact
    # 姓名不允许清空，其余字段按传入值覆盖
    if name is not None and str(name).strip():
        contact.name = str(name).strip()
    if mobile is not None:
        contact.mobile = mobile
    if email is not None:
        contact.email = email
    contact.update_by = context.user_id
    await session.flush()
    return contact


async def _promote_primary(
    session: AsyncSession, context: AuthContext, customer_id: int
) -> CrmContact | None:
    """主联系人被删除后顺延一位（优先已有主联系人，其次最早创建者）并同步快照。"""
    customer = await session.get(CrmCustomer, customer_id)
    if customer is None or customer.deleted:
        return None
    remaining = await list_contacts(session, customer_id)
    if not remaining:
        return None
    target = next((item for item in remaining if item.is_primary), remaining[0])
    if not target.is_primary:
        target.is_primary = 1
        target.update_by = context.user_id
    _apply_snapshot(customer, target)
    await session.flush()
    return target


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
    """创建客户（名称唯一校验；联系人必填，没有对接人无法跟进）。"""
    if not str(contact_name or "").strip():
        raise BizRuleError("请填写联系人")
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
        contact_name=str(contact_name).strip(),
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
    # 新建时就填了联系人信息，则同步生成主联系人，两处数据从一开始就一致
    if contact_name:
        await _sync_primary_contact(
            session,
            context,
            customer,
            name=contact_name,
            mobile=contact_mobile,
            email=contact_email,
        )
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
        if not str(contact_name).strip():
            raise BizRuleError("请填写联系人")
        customer.contact_name = contact_name.strip()
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
    # 客户表单里改了联系人信息，同步到主联系人（没有则新建）
    if contact_name is not None or contact_mobile is not None or contact_email is not None:
        await _sync_primary_contact(
            session,
            context,
            customer,
            name=contact_name,
            mobile=contact_mobile,
            email=contact_email,
        )
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
    """新增联系人；设为主联系人时取消同客户其他主联系人并回写客户快照。"""
    customer = await get_customer(session, customer_id)
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
    if is_primary:
        _apply_snapshot(customer, contact)
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
    """编辑联系人；设为主联系人时取消同客户其他主联系人并回写客户快照。"""
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
    customer = await session.get(CrmCustomer, contact.customer_id)
    if contact.is_primary and customer is not None and not customer.deleted:
        _apply_snapshot(customer, contact)
    await session.flush()
    return contact


async def delete_contact(
    session: AsyncSession, context: AuthContext, contact_id: int
) -> CrmContact:
    """逻辑删除联系人（删除主联系人时顺延下一位并同步客户快照）。"""
    contact = await get_contact(session, contact_id)
    was_primary = bool(contact.is_primary)
    customer_id = int(contact.customer_id)
    contact.deleted = 1
    contact.update_by = context.user_id
    await session.flush()
    if was_primary:
        await _promote_primary(session, context, customer_id)
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
    competitor: str = "",
    bid_date: str | None = None,
    launch_date: str | None = None,
    advantage: str = "",
    product_line: str = "",
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
        competitor=(competitor or "").strip()[:200],
        bid_date=bid_date or None,
        launch_date=launch_date or None,
        advantage=advantage or "",
        product_line=(product_line or "").strip()[:500],
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
    competitor: str | None = None,
    bid_date: str | None = None,
    launch_date: str | None = None,
    advantage: str | None = None,
    product_line: str | None = None,
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
    if competitor is not None:
        opportunity.competitor = (competitor or "").strip()[:200]
    if bid_date is not None:
        opportunity.bid_date = bid_date or None
    if launch_date is not None:
        opportunity.launch_date = launch_date or None
    if advantage is not None:
        opportunity.advantage = advantage
    if product_line is not None:
        opportunity.product_line = (product_line or "").strip()[:500]
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
    win_stage = await _win_stage(config)
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


# ---------------------------------------------------------------- 原始需求


async def get_requirement(session: AsyncSession, requirement_id: int) -> CrmRequirement:
    """取原始需求，不存在或已删除时抛 `NotFoundError`。"""
    requirement = await session.get(CrmRequirement, requirement_id)
    if requirement is None or requirement.deleted:
        raise NotFoundError("原始需求不存在")
    return requirement


def _requirement_filters(
    stmt,
    visible: set[int] | None,
    *,
    customer_id: int | None = None,
    keyword: str = "",
    status: str = "",
    priority: str = "",
    owner_id: int = 0,
):
    """原始需求列表/计数共用的过滤条件（口径必须一致）。"""
    stmt = stmt.where(CrmRequirement.deleted == 0)
    if visible is not None:
        stmt = stmt.where(CrmRequirement.owner_dept_id.in_(visible))
    if customer_id:
        stmt = stmt.where(CrmRequirement.customer_id == customer_id)
    if keyword:
        like = _keyword_like(keyword)
        stmt = stmt.where(
            or_(CrmRequirement.req_name.like(like), CrmRequirement.req_code.like(like))
        )
    if status:
        stmt = stmt.where(
            CrmRequirement.status == _enum_value(status, _REQ_STATUS_VALUES, "需求状态")
        )
    if priority:
        stmt = stmt.where(
            CrmRequirement.priority == _enum_value(priority, _REQ_PRIORITY_VALUES, "优先级")
        )
    if owner_id:
        stmt = stmt.where(CrmRequirement.owner_user_id == owner_id)
    return stmt


async def list_requirements(
    session: AsyncSession,
    visible: set[int] | None,
    customer_id: int | None = None,
    keyword: str = "",
    offset: int = 0,
    limit: int = 20,
    status: str = "",
    priority: str = "",
    owner_id: int = 0,
) -> list[CrmRequirement]:
    """原始需求列表（受数据范围约束）。"""
    stmt = _requirement_filters(
        select(CrmRequirement),
        visible,
        customer_id=customer_id,
        keyword=keyword,
        status=status,
        priority=priority,
        owner_id=owner_id,
    )
    stmt = stmt.order_by(CrmRequirement.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_requirements(
    session: AsyncSession,
    visible: set[int] | None,
    customer_id: int | None = None,
    keyword: str = "",
    status: str = "",
    priority: str = "",
    owner_id: int = 0,
) -> int:
    """原始需求总数（筛选条件与列表保持一致）。"""
    stmt = _requirement_filters(
        select(func.count(CrmRequirement.id)),
        visible,
        customer_id=customer_id,
        keyword=keyword,
        status=status,
        priority=priority,
        owner_id=owner_id,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def create_requirement(
    session: AsyncSession,
    context: AuthContext,
    *,
    req_name: str,
    customer_id: int = 0,
    source: str = "",
    priority: str = "MIDDLE",
    expect_finish_date: str | None = None,
    expect_launch_date: str | None = None,
    expect_amount: float = 0,
    requirement: str = "",
    owner_user_id: int = 0,
    owner_dept_id: int = 0,
) -> CrmRequirement:
    """创建原始需求（客户可选，填了才校验存在性）。"""
    if customer_id:
        await get_customer(session, customer_id)
    item = CrmRequirement(
        req_code=await next_requirement_code(session),
        req_name=req_name,
        customer_id=customer_id,
        owner_user_id=owner_user_id or context.user_id,
        owner_dept_id=owner_dept_id or context.dept_id,
        source=source or "",
        priority=_enum_value(priority or "MIDDLE", _REQ_PRIORITY_VALUES, "优先级"),
        expect_finish_date=expect_finish_date or None,
        expect_launch_date=expect_launch_date or None,
        expect_amount=expect_amount,
        requirement=requirement or "",
        status=RequirementStatus.OPEN.value,
        create_by=context.user_id,
    )
    session.add(item)
    await session.flush()
    return item


async def update_requirement(
    session: AsyncSession,
    context: AuthContext,
    requirement_id: int,
    *,
    req_name: str | None = None,
    customer_id: int | None = None,
    source: str | None = None,
    priority: str | None = None,
    expect_finish_date: str | None = None,
    expect_launch_date: str | None = None,
    expect_amount: float | None = None,
    requirement: str | None = None,
    status: str | None = None,
    owner_user_id: int | None = None,
    owner_dept_id: int | None = None,
) -> CrmRequirement:
    """编辑原始需求（未传字段保持不变）。"""
    item = await get_requirement(session, requirement_id)
    if req_name is not None:
        item.req_name = req_name
    if customer_id is not None and customer_id != item.customer_id:
        if customer_id:
            await get_customer(session, customer_id)
        item.customer_id = customer_id
    if source is not None:
        item.source = source
    if priority is not None:
        item.priority = _enum_value(priority, _REQ_PRIORITY_VALUES, "优先级")
    if expect_finish_date is not None:
        item.expect_finish_date = expect_finish_date or None
    if expect_launch_date is not None:
        item.expect_launch_date = expect_launch_date or None
    if expect_amount is not None:
        item.expect_amount = expect_amount
    if requirement is not None:
        item.requirement = requirement
    if status is not None:
        item.status = _enum_value(status, _REQ_STATUS_VALUES, "需求状态")
    if owner_user_id is not None:
        item.owner_user_id = owner_user_id
    if owner_dept_id is not None:
        item.owner_dept_id = owner_dept_id
    item.update_by = context.user_id
    await session.flush()
    return item


async def delete_requirement(
    session: AsyncSession, context: AuthContext, requirement_id: int
) -> CrmRequirement:
    """逻辑删除原始需求（附件一并逻辑删除）。"""
    item = await get_requirement(session, requirement_id)
    item.deleted = 1
    item.update_by = context.user_id
    links = (
        await session.execute(
            select(CrmRequirementFile).where(
                CrmRequirementFile.requirement_id == requirement_id,
                CrmRequirementFile.deleted == 0,
            )
        )
    ).scalars()
    for link in links:
        link.deleted = 1
        link.update_by = context.user_id
    await session.flush()
    return item


def _requirement_file_out(
    link: CrmRequirementFile, file: SysFile, uploader: str = ""
) -> dict[str, object]:
    """需求附件出参。"""
    return {
        "id": link.id,
        "fileId": link.file_id,
        "fileName": link.file_name,
        "size": int(link.size),
        "mime": file.mime,
        "uploader": uploader,
        "uploadTime": file.create_time.isoformat(sep=" ", timespec="seconds")
        if file.create_time
        else "",
    }


async def list_requirement_files(
    session: AsyncSession, requirement_id: int
) -> list[dict[str, object]]:
    """需求附件列表（含上传人姓名）。"""
    rows = (
        await session.execute(
            select(CrmRequirementFile, SysFile)
            .join(SysFile, SysFile.id == CrmRequirementFile.file_id)
            .where(
                CrmRequirementFile.requirement_id == requirement_id,
                CrmRequirementFile.deleted == 0,
                SysFile.deleted == 0,
            )
            .order_by(CrmRequirementFile.id.desc())
        )
    ).all()
    uploader_ids = {int(file.create_by or 0) for _, file in rows}
    names: dict[int, str] = {}
    if uploader_ids:
        name_rows = await session.execute(
            select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(uploader_ids))
        )
        names = {int(row[0]): str(row[1] or "") for row in name_rows.all()}
    return [
        _requirement_file_out(link, file, names.get(int(file.create_by or 0), ""))
        for link, file in rows
    ]


async def requirement_file_counts(
    session: AsyncSession, requirement_ids: set[int]
) -> dict[int, int]:
    """批量统计需求附件数量（列表展示用，避免逐行查询）。"""
    ids = {item for item in requirement_ids if item}
    if not ids:
        return {}
    rows = await session.execute(
        select(CrmRequirementFile.requirement_id, func.count(CrmRequirementFile.id))
        .where(CrmRequirementFile.requirement_id.in_(ids), CrmRequirementFile.deleted == 0)
        .group_by(CrmRequirementFile.requirement_id)
    )
    return {int(req_id): int(count) for req_id, count in rows.all()}


async def add_requirement_file(
    session: AsyncSession, context: AuthContext, requirement_id: int, upload: UploadFile
) -> dict[str, object]:
    """上传需求附件：落 `t_sys_file` + `t_crm_requirement_file`。"""
    item = await get_requirement(session, requirement_id)
    stored = await save_upload(
        upload,
        0,
        project_code=_REQ_UPLOAD_FOLDER,
        biz_type="REQUIREMENT",
    )
    file = SysFile(
        file_key=stored.file_key,
        origin_name=stored.origin_name,
        storage_path=stored.storage_path,
        size=stored.size,
        mime=stored.mime,
        bucket="local",
        biz_type="REQUIREMENT",
        biz_id=item.id,
        create_by=context.user_id,
    )
    session.add(file)
    await session.flush()
    await session.refresh(file)
    link = CrmRequirementFile(
        requirement_id=item.id,
        file_id=file.id,
        file_name=stored.origin_name,
        size=stored.size,
        create_by=context.user_id,
    )
    session.add(link)
    await session.flush()
    return _requirement_file_out(link, file, context.real_name)


async def get_requirement_file(
    session: AsyncSession, file_id: int
) -> tuple[CrmRequirementFile, SysFile]:
    """按文件 ID 取附件关联与文件记录（含软删校验）。"""
    link = (
        await session.execute(
            select(CrmRequirementFile).where(
                CrmRequirementFile.file_id == file_id, CrmRequirementFile.deleted == 0
            )
        )
    ).scalars().first()
    if link is None:
        raise NotFoundError("附件不存在")
    file = await session.get(SysFile, file_id)
    if file is None or file.deleted:
        raise NotFoundError("文件不存在")
    return link, file


async def requirement_file_path(session: AsyncSession, file_id: int):
    """取下载所需的文件记录与磁盘绝对路径。"""
    link, file = await get_requirement_file(session, file_id)
    path = resolve_storage_path(file.storage_path)
    return link, file, path


async def delete_requirement_file(
    session: AsyncSession, context: AuthContext, file_id: int
) -> None:
    """逻辑删除需求附件（上传人本人或需求管理员）。"""
    link, file = await get_requirement_file(session, file_id)
    link.deleted = 1
    link.update_by = context.user_id
    file.deleted = 1
    file.update_by = context.user_id
    await session.flush()


# ---------------------------------------------------------------- 产品档案

_PRODUCT_PREFIX: Final[str] = "PD"
_PRODUCT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"SOFTWARE", "HARDWARE", "SERVICE", "SOLUTION", "OTHER"}
)
_PRODUCT_STATUS_VALUES: Final[frozenset[str]] = frozenset(
    item.value for item in ProductStatus
)
#: 产品说明字数下限 / 上限：太短的说明对报价与方案没有参考价值
_PRODUCT_DESC_MIN: Final[int] = 500
_PRODUCT_DESC_MAX: Final[int] = 5000


async def next_product_code(session: AsyncSession) -> str:
    """生成产品编码 `PD-0001`（取已用最大序号 +1，删除后也不复用）。"""
    result = await session.execute(
        select(CrmProduct.product_code).where(
            CrmProduct.product_code.like(f"{_PRODUCT_PREFIX}-%")
        )
    )
    used: list[int] = []
    for code in result.scalars():
        suffix = str(code or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            used.append(int(suffix))
    return f"{_PRODUCT_PREFIX}-{max(used, default=0) + 1:04d}"


def _product_filters(keyword: str = "", category: str = "", status: str = "") -> list[object]:
    """产品查询条件（列表与计数共用）。"""
    clauses: list[object] = [CrmProduct.deleted == 0]
    if keyword:
        like = _keyword_like(keyword)
        clauses.append(
            or_(
                CrmProduct.product_name.like(like),
                CrmProduct.product_code.like(like),
                CrmProduct.spec.like(like),
            )
        )
    if category:
        clauses.append(
            CrmProduct.category == _enum_value(category, _PRODUCT_CATEGORIES, "产品类别")
        )
    if status:
        clauses.append(
            CrmProduct.status == _enum_value(status, _PRODUCT_STATUS_VALUES, "产品状态")
        )
    return clauses


async def list_products(
    session: AsyncSession,
    keyword: str = "",
    category: str = "",
    status: str = "",
    offset: int = 0,
    limit: int = 20,
) -> list[CrmProduct]:
    """产品列表（关键字 / 类别 / 状态筛选）。"""
    stmt = (
        select(CrmProduct)
        .where(*_product_filters(keyword, category, status))
        .order_by(CrmProduct.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_products(
    session: AsyncSession,
    keyword: str = "",
    category: str = "",
    status: str = "",
) -> int:
    """产品总数（筛选条件与列表一致）。"""
    stmt = select(func.count(CrmProduct.id)).where(
        *_product_filters(keyword, category, status)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_product(session: AsyncSession, product_id: int) -> CrmProduct:
    """取产品，不存在时抛 404。"""
    product = await session.get(CrmProduct, product_id)
    if product is None or product.deleted:
        raise NotFoundError("产品不存在")
    return product


def _validate_product(
    *, product_name: str, category: str, status: str, description: str
) -> tuple[str, str, str, str]:
    """校验产品入参：名称必填、类别/状态合法、产品说明至少 500 字。"""
    name = (product_name or "").strip()
    if not name:
        raise BizRuleError("请填写产品名称")
    if len(name) > 200:
        raise BizRuleError("产品名称不能超过 200 字")
    desc = (description or "").strip()
    if len(desc) < _PRODUCT_DESC_MIN:
        raise BizRuleError(
            f"产品说明至少 {_PRODUCT_DESC_MIN} 字（当前 {len(desc)} 字），"
            "请补充产品定位、功能范围与适用场景"
        )
    if len(desc) > _PRODUCT_DESC_MAX:
        raise BizRuleError(f"产品说明不能超过 {_PRODUCT_DESC_MAX} 字")
    return (
        name,
        _enum_value(category or "SOFTWARE", _PRODUCT_CATEGORIES, "产品类别"),
        _enum_value(status or ProductStatus.ACTIVE, _PRODUCT_STATUS_VALUES, "产品状态"),
        desc,
    )


async def create_product(
    session: AsyncSession,
    context: AuthContext,
    *,
    product_name: str,
    category: str = "SOFTWARE",
    spec: str = "",
    unit: str = "",
    description: str = "",
    status: str = ProductStatus.ACTIVE,
    remark: str = "",
) -> CrmProduct:
    """新增产品档案。"""
    name, category_value, status_value, desc = _validate_product(
        product_name=product_name, category=category, status=status, description=description
    )
    product = CrmProduct(
        product_code=await next_product_code(session),
        product_name=name,
        category=category_value,
        spec=(spec or "").strip()[:200],
        unit=(unit or "").strip()[:16],
        description=desc,
        status=status_value,
        remark=remark or "",
        create_by=context.user_id,
    )
    session.add(product)
    await session.flush()
    return product


async def update_product(
    session: AsyncSession,
    context: AuthContext,
    product_id: int,
    *,
    product_name: str,
    category: str = "SOFTWARE",
    spec: str = "",
    unit: str = "",
    description: str = "",
    status: str = ProductStatus.ACTIVE,
    remark: str = "",
) -> CrmProduct:
    """编辑产品档案（整体覆盖）。"""
    product = await get_product(session, product_id)
    name, category_value, status_value, desc = _validate_product(
        product_name=product_name, category=category, status=status, description=description
    )
    product.product_name = name
    product.category = category_value
    product.spec = (spec or "").strip()[:200]
    product.unit = (unit or "").strip()[:16]
    product.description = desc
    product.status = status_value
    product.remark = remark or ""
    product.update_by = context.user_id
    await session.flush()
    return product


async def delete_product(
    session: AsyncSession, context: AuthContext, product_id: int
) -> None:
    """删除产品（软删）。"""
    product = await get_product(session, product_id)
    product.deleted = 1
    product.update_by = context.user_id
    await session.flush()


# ---------------------------------------------------------------- 客户关注产品


async def list_customer_products(
    session: AsyncSession, customer_id: int
) -> list[CrmProduct]:
    """客户关注的产品（按产品编码排序，已删除产品不再返回）。"""
    stmt = (
        select(CrmProduct)
        .join(CrmCustomerProduct, CrmCustomerProduct.product_id == CrmProduct.id)
        .where(
            CrmCustomerProduct.customer_id == customer_id,
            CrmCustomerProduct.deleted == 0,
            CrmProduct.deleted == 0,
        )
        .order_by(CrmProduct.product_code)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def customer_product_counts(
    session: AsyncSession, customer_ids: set[int]
) -> dict[int, int]:
    """客户关注产品数量（列表批量统计，避免逐行查询）。"""
    ids = {item for item in customer_ids if item}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(CrmCustomerProduct.customer_id, func.count(CrmCustomerProduct.id))
            .where(
                CrmCustomerProduct.customer_id.in_(ids),
                CrmCustomerProduct.deleted == 0,
            )
            .group_by(CrmCustomerProduct.customer_id)
        )
    ).all()
    return {int(customer_id): int(count) for customer_id, count in rows}


async def replace_customer_products(
    session: AsyncSession,
    context: AuthContext,
    customer_id: int,
    product_ids: list[int],
) -> None:
    """整体覆盖客户关注的产品：去掉未选中的关联，补充新选的产品。

    产品必须真实存在，避免前端传脏 ID 后留一条查不到产品的关联。
    """
    await get_customer(session, customer_id)
    wanted = {int(item) for item in product_ids if item}
    existing = (
        await session.execute(
            select(CrmCustomerProduct).where(
                CrmCustomerProduct.customer_id == customer_id,
                CrmCustomerProduct.deleted == 0,
            )
        )
    ).scalars().all()
    current = {int(row.product_id) for row in existing}
    for row in existing:
        if int(row.product_id) not in wanted:
            row.deleted = 1
            row.update_by = context.user_id

    missing = wanted - current
    if missing:
        found = {
            int(item)
            for item in (
                await session.execute(
                    select(CrmProduct.id).where(
                        CrmProduct.id.in_(missing), CrmProduct.deleted == 0
                    )
                )
            ).scalars().all()
        }
        if found != missing:
            raise BizRuleError("选择的产品不存在或已删除")
        for product_id in sorted(found):
            session.add(
                CrmCustomerProduct(
                    customer_id=customer_id,
                    product_id=product_id,
                    create_by=context.user_id,
                )
            )
    await session.flush()
