"""crm product

Revision ID: b7d2f4a6c8e1
Revises: a1c9e5f7b3d6
Create Date: 2026-11-19 14:00:00.000000

变更说明：
- 新增 `t_crm_product`（产品档案）：报价与方案引用的基础资料；
  产品为全公司共享档案，按权限点 `crm:product:view` / `crm:product:manage` 控制。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2f4a6c8e1"
down_revision: str | None = "a1c9e5f7b3d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    """表是否已存在（MySQL DDL 非事务，失败重跑时避免重复建表）。"""
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("t_crm_product"):
        return
    op.create_table(
        "t_crm_product",
        sa.Column("product_code", sa.String(length=32), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("spec", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("remark", sa.Text(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("create_by", sa.BigInteger(), nullable=True),
        sa.Column("create_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("update_by", sa.BigInteger(), nullable=True),
        sa.Column("update_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("deleted", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_t_crm_product")),
    )
    op.create_index(
        op.f("ix_t_crm_product_product_code"), "t_crm_product", ["product_code"]
    )


def downgrade() -> None:
    if _has_table("t_crm_product"):
        op.drop_table("t_crm_product")
