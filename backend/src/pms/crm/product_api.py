"""产品列表接口：报价与方案的基础档案（设计稿 04 §4.2.1）。

权限口径：
- 查看 `crm:product:view`（销售、项目经理、部门领导、PMO、公司领导、管理员）；
- 新增 / 编辑 / 删除 `crm:product:manage`（公司领导只读）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pms.common.response import ok, paged
from pms.core.context import AuthContext
from pms.core.deps import Pagination, get_pagination, get_session, require_permissions
from pms.crm import service
from pms.crm.models import CrmProduct, ProductStatus

router = APIRouter(prefix="/api/v1/products", tags=["产品列表"])


class ProductIn(BaseModel):
    """产品新增 / 编辑入参（整体覆盖）。"""

    productName: str = Field(min_length=1, max_length=200)
    category: str = "SOFTWARE"
    spec: str = Field(default="", max_length=200)
    unit: str = Field(default="", max_length=16)
    price: float = Field(default=0, ge=0)
    status: str = ProductStatus.ACTIVE
    remark: str = Field(default="", max_length=2000)


def _out(item: CrmProduct) -> dict[str, object]:
    """产品出参。"""
    return {
        "id": item.id,
        "productCode": item.product_code,
        "productName": item.product_name,
        "category": item.category,
        "spec": item.spec,
        "unit": item.unit,
        "price": float(item.price),
        "status": item.status,
        "remark": item.remark,
        "createTime": item.create_time.isoformat() if item.create_time else "",
    }


@router.get("", summary="产品列表")
async def list_products(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:product:view"))],
    pagination: Annotated[Pagination, Depends(get_pagination)],
    keyword: Annotated[str, Query()] = "",
    category: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
) -> object:
    """分页查询产品档案；支持名称 / 编码 / 规格关键字与类别、状态筛选。"""
    total = await service.count_products(session, keyword, category, status)
    items = await service.list_products(
        session,
        keyword,
        category,
        status,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return paged(
        [_out(item) for item in items],
        total,
        pagination.page_num,
        pagination.page_size,
    )


@router.get("/{product_id}", summary="产品详情")
async def product_detail(
    product_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:product:view"))],
) -> object:
    """产品详情。"""
    return ok(_out(await service.get_product(session, product_id)))


@router.post("", summary="新增产品")
async def create_product(
    body: ProductIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:product:manage"))],
) -> object:
    """新增产品档案，编码自动生成 `PD-0001`。"""
    product = await service.create_product(
        session,
        context,
        product_name=body.productName,
        category=body.category,
        spec=body.spec,
        unit=body.unit,
        price=body.price,
        status=body.status,
        remark=body.remark,
    )
    await session.commit()
    return ok(_out(product))


@router.put("/{product_id}", summary="编辑产品")
async def update_product(
    product_id: int,
    body: ProductIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:product:manage"))],
) -> object:
    """编辑产品档案（整体覆盖，编码不变）。"""
    product = await service.update_product(
        session,
        context,
        product_id,
        product_name=body.productName,
        category=body.category,
        spec=body.spec,
        unit=body.unit,
        price=body.price,
        status=body.status,
        remark=body.remark,
    )
    await session.commit()
    return ok(_out(product))


@router.delete("/{product_id}", summary="删除产品")
async def delete_product(
    product_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AuthContext, Depends(require_permissions("crm:product:manage"))],
) -> object:
    """删除产品（软删）。"""
    await service.delete_product(session, context, product_id)
    await session.commit()
    return ok(message="产品已删除")
