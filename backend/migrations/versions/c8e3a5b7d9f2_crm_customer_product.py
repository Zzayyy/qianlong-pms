"""crm customer product

Revision ID: c8e3a5b7d9f2
Revises: b7d2f4a6c8e1
Create Date: 2026-11-19 15:00:00.000000

变更说明：
- 新增 `t_crm_customer_product`：客户关注产品（客户档案与产品档案的多对多）。
  只表达关注关系，数量与报价由商机明细承载。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e3a5b7d9f2"
down_revision: str | None = "b7d2f4a6c8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    """表是否已存在（MySQL DDL 非事务，失败重跑时避免重复建表）。"""
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("t_crm_customer_product"):
        return
    op.create_table(
        "t_crm_customer_product",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("create_by", sa.BigInteger(), nullable=True),
        sa.Column("create_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("update_by", sa.BigInteger(), nullable=True),
        sa.Column("update_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("deleted", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_t_crm_customer_product")),
    )
    op.create_index(
        op.f("ix_t_crm_customer_product_customer_id"),
        "t_crm_customer_product",
        ["customer_id"],
    )


def downgrade() -> None:
    if _has_table("t_crm_customer_product"):
        op.drop_table("t_crm_customer_product")
