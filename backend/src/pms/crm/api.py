"""CRM 接口：客户、联系人、商机、跟进、商机转项目（设计稿 09 §2.2）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.mask import mask_email, mask_mobile, mask_amount
from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.crm import service

router = APIRouter(prefix="/api/v1/crm", tags=["客户与商机"])


def _scope(context: AuthContext) -> set[int] | None:
    """数据范围转部门集合；`None` 表示全公司。"""
    return None if context.visible_dept_ids is None else set(context.visible_dept_ids)


def _plain_sensitive(context: AuthContext, owner_user_id: int) -> bool:
    """字段级脱敏判定：本人、部门领导、PMO/公司领导可见明文。"""
    return context.user_id == owner_user_id or context.is_dept_head or context.is_privileged


class CustomerIn(BaseModel):
    """客户入参。"""

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
    remark: str = ""


class ContactIn(BaseModel):
    """联系人入参。"""

    name: str = Field(min_length=1, max_length=64)
    title: str = ""
    mobile: str = ""
    email: str = ""
    wechat: str = ""
    isPrimary: bool = False


class OpportunityIn(BaseModel):
    """商机入参。"""

    oppName: str = Field(min_length=1, max_length=200)
    customerId: int
    expectAmount: float = 0
    expectSignDate: str | None = None
    stage: str = "LEAD"
    winRate: float = 0
    source: str = ""
    remark: str = ""


class StageIn(BaseModel):
    """商机阶段入参。"""

    stage: str = Field(min_length=2, max_length=32)


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


def _customer_out(item: object, context: AuthContext) -> dict[str, object]:
    """客户出参（敏感字段按角色脱敏）。"""
    from pms.crm.models import CrmCustomer

    assert isinstance(item, CrmCustomer)
    plain = _plain_sensitive(context, item.owner_user_id)
    return {
        "id": item.id,
        "customerCode": item.customer_code,
        "customerName": item.customer_name,
        "customerLevel": item.customer_level,
        "industry": item.industry,
        "ownerUserId": item.owner_user_id,
        "ownerDeptId": item.owner_dept_id,
        "contactName": item.contact_name,
        "contactMobile": item.contact_mobile if plain else mask_mobile(item.contact_mobile),
        "contactEmail": item.contact_email if plain else mask_email(item.contact_email),
        "status": item.status,
    }


@router.get("/customers", summary="客户列表")
async def customers(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    keyword: Annotated[str, Query()] = "",
) -> object:
    """分页查询客户，**按数据范围过滤**。"""
    visible = _scope(context)
    total = await service.count_customers(session, visible, keyword)
    items = await service.list_customers(
        session, visible, keyword, pagination.offset, pagination.limit
    )
    return paged(
        [_customer_out(item, context) for item in items],
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
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": customer.id, "customerCode": customer.customer_code})


@router.get("/customers/{customer_id}/contacts", summary="客户联系人")
async def contacts(
    customer_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:customer:view"))],
) -> object:
    """联系人列表（手机/邮箱默认脱敏）。"""
    items = await service.list_contacts(session, customer_id)
    plain = context.is_dept_head or context.is_privileged
    return ok(
        [
            {
                "id": item.id,
                "name": item.name,
                "title": item.title,
                "mobile": item.mobile if plain else mask_mobile(item.mobile),
                "email": item.email if plain else mask_email(item.email),
                "isPrimary": item.is_primary,
            }
            for item in items
        ]
    )


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
    )
    await session.commit()
    return ok({"id": contact.id})


@router.get("/opportunities", summary="商机列表")
async def opportunities(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    customerId: Annotated[int | None, Query()] = None,
    keyword: Annotated[str, Query()] = "",
) -> object:
    """分页查询商机，**按数据范围过滤**，金额按角色脱敏。"""
    visible = _scope(context)
    total = await service.count_opportunities(session, visible, customerId, keyword)
    items = await service.list_opportunities(
        session, visible, customerId, keyword, pagination.offset, pagination.limit
    )
    plain = context.is_dept_head or context.is_privileged
    payload = [
        {
            "id": item.id,
            "oppCode": item.opp_code,
            "oppName": item.opp_name,
            "customerId": item.customer_id,
            "stage": item.stage,
            "status": item.status,
            "winRate": float(item.win_rate),
            "expectAmount": (
                float(item.expect_amount) if plain else mask_amount(float(item.expect_amount))
            ),
            "convertedProjectId": item.converted_project_id,
        }
        for item in items
    ]
    return paged(payload, total, pagination.page_num, pagination.page_size)


@router.post("/opportunities", summary="创建商机")
async def create_opportunity(
    body: OpportunityIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """创建商机。"""
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
        remark=body.remark,
    )
    await session.commit()
    return ok({"id": opportunity.id, "oppCode": opportunity.opp_code})


@router.put("/opportunities/{opportunity_id}/stage", summary="推进商机阶段")
async def update_stage(
    opportunity_id: int,
    body: StageIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:opp:manage"))],
) -> object:
    """推进阶段；WON/LOST 同步商机状态。"""
    opportunity = await service.update_stage(
        session, opportunity_id, body.stage, operator_id=context.user_id
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
            "status": project.status,
        }
    )


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
    )
    await session.commit()
    return ok({"id": record.id})
