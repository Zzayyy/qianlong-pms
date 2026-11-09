"""CRM 接口：客户、联系人、商机、跟进、商机转项目（设计稿 09 §2.2）。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.mask import mask_amount, mask_email, mask_mobile
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.database import get_session
from pms.core.deps import Pagination, get_pagination, require_permissions
from pms.crm import service
from pms.crm.models import CrmContact, CrmCustomer, CrmFollow, CrmOpportunity
from pms.org.models import SysUser

router = APIRouter(prefix="/api/v1/crm", tags=["客户与商机"])

_MASK_TEXT = "****"


def _scope(context: AuthContext) -> set[int] | None:
    """数据范围转部门集合；`None` 表示全公司。"""
    return None if context.visible_dept_ids is None else set(context.visible_dept_ids)


def _plain_sensitive(context: AuthContext, owner_user_id: int) -> bool:
    """字段级脱敏判定：本人、部门领导、全公司范围、PMO/公司领导可见明文。"""
    return (
        context.user_id == owner_user_id
        or context.is_dept_head
        or context.is_privileged
        or context.is_all_scope
    )


def _date_text(value: object) -> str:
    """日期/时间统一转 ISO 文本（统一响应体不做 datetime 序列化）。"""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _masked(value: str, masker: Callable[[str], str], plain: bool) -> str:
    """空值不脱敏；无权限时按字段类型脱敏。"""
    if not value:
        return ""
    return value if plain else masker(value)


async def _user_names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """批量取用户姓名，避免列表 N+1 查询。"""
    ids = {item for item in user_ids if item}
    if not ids:
        return {}
    result = await session.execute(
        select(SysUser.id, SysUser.real_name).where(SysUser.id.in_(ids))
    )
    return {int(user_id): str(name or "") for user_id, name in result.all()}


async def _customer_names(session: AsyncSession, customer_ids: set[int]) -> dict[int, str]:
    """批量取客户名称。"""
    ids = {item for item in customer_ids if item}
    if not ids:
        return {}
    result = await session.execute(
        select(CrmCustomer.id, CrmCustomer.customer_name).where(CrmCustomer.id.in_(ids))
    )
    return {int(customer_id): str(name or "") for customer_id, name in result.all()}


class CustomerIn(BaseModel):
    """客户入参（覆盖 `t_crm_customer` 业务字段）。"""

    customerName: str = Field(min_length=1, max_length=200)
    customerLevel: str = "C"
    industry: str = ""
    ownerUserId: int = 0
    ownerDeptId: int = 0
    contactName: str = ""
    contactMobile: str = ""
    contactEmail: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    source: str = ""
    status: str = "POTENTIAL"
    remark: str = ""


class CustomerUpdateIn(BaseModel):
    """客户编辑入参（未传字段保持不变）。"""

    customerName: str | None = Field(default=None, min_length=1, max_length=200)
    customerLevel: str | None = None
    industry: str | None = None
    ownerUserId: int | None = None
    ownerDeptId: int | None = None
    contactName: str | None = None
    contactMobile: str | None = None
    contactEmail: str | None = None
    province: str | None = None
    city: str | None = None
    address: str | None = None
    source: str | None = None
    status: str | None = None
    remark: str | None = None


class CustomerStatusIn(BaseModel):
    """客户状态入参。"""

    status: str = Field(min_length=2, max_length=16)


class ContactIn(BaseModel):
    """联系人入参。"""

    name: str = Field(min_length=1, max_length=64)
    title: str = ""
    mobile: str = ""
    email: str = ""
    wechat: str = ""
    isPrimary: bool = False
    remark: str = ""


class ContactUpdateIn(BaseModel):
    """联系人编辑入参。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = None
    mobile: str | None = None
    email: str | None = None
    wechat: str | None = None
    isPrimary: bool | None = None
    remark: str | None = None


class OpportunityIn(BaseModel):
    """商机入参（覆盖 `t_crm_opportunity` 业务字段）。"""

    oppName: str = Field(min_length=1, max_length=200)
    customerId: int
    expectAmount: float = 0
    expectSignDate: str | None = None
    stage: str = "LEAD"
    winRate: float = 0
    source: str = ""
    ownerUserId: int = 0
    ownerDeptId: int = 0
    remark: str = ""


class OpportunityUpdateIn(BaseModel):
    """商机编辑入参（未传字段保持不变）。"""

    oppName: str | None = Field(default=None, min_length=1, max_length=200)
    customerId: int | None = None
    expectAmount: float | None = None
    expectSignDate: str | None = None
    stage: str | None = None
    winRate: float | None = None
    source: str | None = None
    status: str | None = None
    lostReason: str | None = None
    ownerUserId: int | None = None
    ownerDeptId: int | None = None
    remark: str | None = None


class StageIn(BaseModel):
    """商机阶段入参。"""

    stage: str = Field(min_length=2, max_length=32)
    lostReason: str = ""


class OppStatusIn(BaseModel):
    """商机状态入参。"""

    status: str = Field(min_length=2, max_length=16)
    lostReason: str = ""


class ConvertIn(BaseModel):
    """商机转项目入参。"""

    projectName: str = ""
    pmId: int = 0
    planStart: str | None = None
    planEnd: str | None = None


class FollowIn(BaseModel):
    """跟进入参。"""

    content: str = Field(min_length=1)
    followType: str = "PHONE"
    nextPlan: str = ""
    followTime: str | None = None


def _customer_out(
    item: CrmCustomer, context: AuthContext, owner_name: str = "", plain: bool | None = None
) -> dict[str, object]:
    """客户出参（敏感字段按角色脱敏，字段覆盖数据库表）。"""
    visible = _plain_sensitive(context, item.owner_user_id) if plain is None else plain
    return {
        "id": item.id,
        "customerCode": item.customer_code,
        "customerName": item.customer_name,
        "customerLevel": item.customer_level,
        "industry": item.industry,
        "ownerUserId": item.owner_user_id,
        "ownerDeptId": item.owner_dept_id,
        "ownerName": owner_name,
        "contactName": item.contact_name,
        "contactMobile": _masked(item.contact_mobile, mask_mobile, visible),
        "contactEmail": _masked(item.contact_email, mask_email, visible),
        "province": item.province,
        "city": item.city,
        "address": item.address,
        "source": item.source,
        "status": item.status,
        "remark": item.remark,
        "createTime": _date_text(item.create_time),
        "updateTime": _date_text(item.update_time),
    }


def _contact_out(item: CrmContact, plain: bool) -> dict[str, object]:
    """联系人出参（手机/邮箱/微信默认脱敏）。"""
    return {
        "id": item.id,
        "customerId": item.customer_id,
        "name": item.name,
        "title": item.title,
        "mobile": _masked(item.mobile, mask_mobile, plain),
        "email": _masked(item.email, mask_email, plain),
        "wechat": item.wechat if plain or not item.wechat else _MASK_TEXT,
        "isPrimary": item.is_primary,
        "remark": item.remark,
        "createTime": _date_text(item.create_time),
    }


def _opportunity_out(
    item: CrmOpportunity,
    context: AuthContext,
    owner_name: str = "",
    customer_name: str = "",
) -> dict[str, object]:
    """商机出参（金额按字段权限脱敏，字段覆盖数据库表）。"""
    plain = _plain_sensitive(context, item.owner_user_id)
    amount = float(item.expect_amount)
    return {
        "id": item.id,
        "oppCode": item.opp_code,
        "oppName": item.opp_name,
        "customerId": item.customer_id,
        "customerName": customer_name,
        "ownerUserId": item.owner_user_id,
        "ownerDeptId": item.owner_dept_id,
        "ownerName": owner_name,
        "expectAmount": amount if plain else mask_amount(amount),
        "expectSignDate": _date_text(item.expect_sign_date),
        "stage": item.stage,
        "winRate": float(item.win_rate),
        "source": item.source,
        "status": item.status,
        "convertedProjectId": item.converted_project_id,
        "convertedTime": _date_text(item.converted_time),
        "lostReason": item.lost_reason,
        "remark": item.remark,
        "createTime": _date_text(item.create_time),
        "updateTime": _date_text(item.update_time),
    }


def _follow_out(item: CrmFollow, creator_name: str) -> dict[str, object]:
    """跟进记录出参。"""
    return {
        "id": item.id,
        "oppId": item.opp_id,
        "followType": item.follow_type,
        "content": item.content,
        "followTime": _date_text(item.follow_time),
        "nextPlan": item.next_plan,
        "createBy": item.create_by,
        "creatorName": creator_name,
        "createTime": _date_text(item.create_time),
    }


@router.get("/summary", summary="客户与商机概览")
async def summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
) -> object:
    """按数据范围统计客户状态与商机金额（列表顶部卡片）。"""
    return ok(await service.crm_summary(session, _scope(context)))


@router.get("/staff", summary="可选负责人/项目经理")
async def staff(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
) -> object:
    """返回数据范围内启用状态的人员，供负责人与转项目下拉选择。"""
    rows = await service.staff_options(session, _scope(context))
    return ok(
        [
            {
                "id": item.id,
                "username": item.username,
                "realName": item.real_name,
                "deptId": item.dept_id,
            }
            for item in rows
        ]
    )


@router.get("/customers", summary="客户列表")
async def customers(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    keyword: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    level: Annotated[str, Query()] = "",
    ownerId: Annotated[int, Query()] = 0,
) -> object:
    """分页查询客户，**按数据范围过滤**，支持名称/编码/联系人检索与状态、等级筛选。"""
    visible = _scope(context)
    total = await service.count_customers(
        session, visible, keyword=keyword, status=status, level=level, owner_id=ownerId
    )
    items = await service.list_customers(
        session,
        visible,
        keyword,
        pagination.offset,
        pagination.limit,
        status=status,
        level=level,
        owner_id=ownerId,
    )
    names = await _user_names(session, {item.owner_user_id for item in items})
    return paged(
        [_customer_out(item, context, names.get(item.owner_user_id, "")) for item in items],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.post("/customers", summary="创建客户")
async def create_customer(
    body: CustomerIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """创建客户（名称唯一）。"""
    customer = await service.create_customer(
        session,
        context,
        customer_name=body.customerName,
        customer_level=body.customerLevel,
        industry=body.industry,
        owner_user_id=body.ownerUserId,
        owner_dept_id=body.ownerDeptId,
        contact_name=body.contactName,
        contact_mobile=body.contactMobile,
        contact_email=body.contactEmail,
        province=body.province,
        city=body.city,
        address=body.address,
        source=body.source,
        status=body.status,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": customer.id, "customerCode": customer.customer_code})


@router.get("/customers/{customer_id}", summary="客户详情")
async def customer_detail(
    customer_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
) -> object:
    """客户详情（含地址、来源、备注与时间字段）。"""
    customer = await service.get_customer(session, customer_id)
    names = await _user_names(session, {customer.owner_user_id})
    return ok(_customer_out(customer, context, names.get(customer.owner_user_id, "")))


@router.put("/customers/{customer_id}", summary="编辑客户")
async def update_customer(
    customer_id: int,
    body: CustomerUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """编辑客户全部业务字段。"""
    customer = await service.update_customer(
        session,
        context,
        customer_id,
        customer_name=body.customerName,
        customer_level=body.customerLevel,
        industry=body.industry,
        owner_user_id=body.ownerUserId,
        owner_dept_id=body.ownerDeptId,
        contact_name=body.contactName,
        contact_mobile=body.contactMobile,
        contact_email=body.contactEmail,
        province=body.province,
        city=body.city,
        address=body.address,
        source=body.source,
        status=body.status,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": customer.id})


@router.put("/customers/{customer_id}/status", summary="修改客户状态")
async def update_customer_status(
    customer_id: int,
    body: CustomerStatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """快速修改客户状态。"""
    customer = await service.set_customer_status(session, context, customer_id, body.status)
    await session.commit()
    return ok({"id": customer.id, "status": customer.status})


@router.delete("/customers/{customer_id}", summary="删除客户")
async def delete_customer(
    customer_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """逻辑删除客户（存在商机时禁止）。"""
    await service.delete_customer(session, context, customer_id)
    await session.commit()
    return ok({"id": customer_id})


@router.get("/customers/{customer_id}/contacts", summary="客户联系人")
async def contacts(
    customer_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
) -> object:
    """联系人列表（手机/邮箱/微信默认脱敏）。"""
    customer = await service.get_customer(session, customer_id)
    plain = _plain_sensitive(context, customer.owner_user_id)
    items = await service.list_contacts(session, customer_id)
    return ok([_contact_out(item, plain) for item in items])


@router.post("/customers/{customer_id}/contacts", summary="新增联系人")
async def create_contact(
    customer_id: int,
    body: ContactIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """新增联系人，可设为主联系人。"""
    contact = await service.add_contact(
        session,
        context,
        customer_id,
        name=body.name,
        title=body.title,
        mobile=body.mobile,
        email=body.email,
        wechat=body.wechat,
        is_primary=body.isPrimary,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": contact.id})


@router.put("/contacts/{contact_id}", summary="编辑联系人")
async def update_contact(
    contact_id: int,
    body: ContactUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """编辑联系人并可调整主联系人。"""
    contact = await service.update_contact(
        session,
        context,
        contact_id,
        name=body.name,
        title=body.title,
        mobile=body.mobile,
        email=body.email,
        wechat=body.wechat,
        is_primary=body.isPrimary,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": contact.id, "isPrimary": contact.is_primary})


@router.delete("/contacts/{contact_id}", summary="删除联系人")
async def delete_contact(
    contact_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:manage"))],
) -> object:
    """逻辑删除联系人。"""
    await service.delete_contact(session, context, contact_id)
    await session.commit()
    return ok({"id": contact_id})


@router.get("/opportunities", summary="商机列表")
async def opportunities(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    customerId: Annotated[int | None, Query()] = None,
    keyword: Annotated[str, Query()] = "",
    stage: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    ownerId: Annotated[int, Query()] = 0,
) -> object:
    """分页查询商机，**按数据范围过滤**，金额按字段权限脱敏。"""
    visible = _scope(context)
    total = await service.count_opportunities(
        session,
        visible,
        customerId,
        keyword,
        stage=stage,
        status=status,
        owner_id=ownerId,
    )
    items = await service.list_opportunities(
        session,
        visible,
        customerId,
        keyword,
        pagination.offset,
        pagination.limit,
        stage=stage,
        status=status,
        owner_id=ownerId,
    )
    names = await _user_names(session, {item.owner_user_id for item in items})
    customer_names = await _customer_names(session, {item.customer_id for item in items})
    return paged(
        [
            _opportunity_out(
                item,
                context,
                names.get(item.owner_user_id, ""),
                customer_names.get(item.customer_id, ""),
            )
            for item in items
        ],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.post("/opportunities", summary="创建商机")
async def create_opportunity(
    body: OpportunityIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """创建商机（校验客户存在）。"""
    opportunity = await service.create_opportunity(
        session,
        context,
        opp_name=body.oppName,
        customer_id=body.customerId,
        expect_amount=body.expectAmount,
        expect_sign_date=body.expectSignDate,
        stage=body.stage,
        win_rate=body.winRate,
        source=body.source,
        owner_user_id=body.ownerUserId,
        owner_dept_id=body.ownerDeptId,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": opportunity.id, "oppCode": opportunity.opp_code})


@router.get("/opportunities/{opportunity_id}", summary="商机详情")
async def opportunity_detail(
    opportunity_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:view"))],
) -> object:
    """商机详情（含客户、负责人、预计签约、输单原因等字段）。"""
    opportunity = await service.get_opportunity(session, opportunity_id)
    names = await _user_names(session, {opportunity.owner_user_id})
    customer_names = await _customer_names(session, {opportunity.customer_id})
    return ok(
        _opportunity_out(
            opportunity,
            context,
            names.get(opportunity.owner_user_id, ""),
            customer_names.get(opportunity.customer_id, ""),
        )
    )


@router.put("/opportunities/{opportunity_id}", summary="编辑商机")
async def update_opportunity(
    opportunity_id: int,
    body: OpportunityUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """编辑商机全部业务字段（阶段变化时同步状态）。"""
    opportunity = await service.update_opportunity(
        session,
        context,
        opportunity_id,
        opp_name=body.oppName,
        customer_id=body.customerId,
        expect_amount=body.expectAmount,
        expect_sign_date=body.expectSignDate,
        stage=body.stage,
        win_rate=body.winRate,
        source=body.source,
        status=body.status,
        lost_reason=body.lostReason,
        owner_user_id=body.ownerUserId,
        owner_dept_id=body.ownerDeptId,
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": opportunity.id, "stage": opportunity.stage, "status": opportunity.status})


@router.delete("/opportunities/{opportunity_id}", summary="删除商机")
async def delete_opportunity(
    opportunity_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """逻辑删除商机（已转项目时禁止）。"""
    await service.delete_opportunity(session, context, opportunity_id)
    await session.commit()
    return ok({"id": opportunity_id})


@router.put("/opportunities/{opportunity_id}/stage", summary="推进商机阶段")
async def update_stage(
    opportunity_id: int,
    body: StageIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """推进阶段；WON/LOST 同步商机状态，可附带输单原因。"""
    opportunity = await service.update_stage(
        session,
        opportunity_id,
        body.stage,
        operator_id=context.user_id,
        lost_reason=body.lostReason,
    )
    await session.commit()
    return ok({"id": opportunity.id, "stage": opportunity.stage, "status": opportunity.status})


@router.put("/opportunities/{opportunity_id}/status", summary="修改商机状态")
async def update_opportunity_status(
    opportunity_id: int,
    body: OppStatusIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """快速修改商机状态（赢单/输单联动阶段，可记录输单原因）。"""
    opportunity = await service.set_opportunity_status(
        session, context, opportunity_id, body.status, body.lostReason
    )
    await session.commit()
    return ok({"id": opportunity.id, "stage": opportunity.stage, "status": opportunity.status})


@router.post("/opportunities/{opportunity_id}/convert", summary="商机转项目")
async def convert(
    opportunity_id: int,
    body: ConvertIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """赢单商机一键生成项目草稿并回写商机。"""
    from pms.project.models import PrjProject

    project = await service.convert_to_project(
        session,
        context,
        opportunity_id,
        project_name=body.projectName,
        pm_id=body.pmId,
        plan_start=body.planStart,
        plan_end=body.planEnd,
    )
    await session.commit()
    assert isinstance(project, PrjProject)
    return ok(
        {
            "projectId": project.id,
            "projectCode": project.project_code,
            "projectName": project.project_name,
            "status": project.status,
        }
    )


@router.get("/opportunities/{opportunity_id}/follows", summary="商机跟进记录")
async def follows(
    opportunity_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:view"))],
) -> object:
    """跟进记录列表（含跟进人姓名与时间）。"""
    await service.get_opportunity(session, opportunity_id)
    items = await service.list_follows(session, opportunity_id)
    names = await _user_names(session, {int(item.create_by or 0) for item in items})
    return ok([_follow_out(item, names.get(int(item.create_by or 0), "")) for item in items])


@router.post("/opportunities/{opportunity_id}/follows", summary="商机跟进")
async def follow(
    opportunity_id: int,
    body: FollowIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """新增跟进记录。"""
    record = await service.add_follow(
        session,
        context,
        opportunity_id,
        content=body.content,
        follow_type=body.followType,
        next_plan=body.nextPlan,
        follow_time=body.followTime,
    )
    await session.commit()
    return ok({"id": record.id})


@router.delete("/follows/{follow_id}", summary="删除跟进记录")
async def delete_follow(
    follow_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """逻辑删除跟进记录。"""
    await service.delete_follow(session, context, follow_id)
    await session.commit()
    return ok({"id": follow_id})
