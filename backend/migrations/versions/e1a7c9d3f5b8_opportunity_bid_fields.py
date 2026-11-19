"""opportunity bid fields

Revision ID: e1a7c9d3f5b8
Revises: d9f4b6c8e1a3
Create Date: 2026-11-19 17:00:00.000000

变更说明：
- `t_crm_opportunity` 新增招标与产品线相关字段：
  `bid_date`（招标时间）、`launch_date`（上线时间）、
  `advantage`（钱龙优势）、`product_line`（产品线，逗号分隔多选）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a7c9d3f5b8"
down_revision: str | None = "d9f4b6c8e1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """列是否已存在（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("t_crm_opportunity", "bid_date"):
        op.add_column(
            "t_crm_opportunity", sa.Column("bid_date", sa.Date(), nullable=True)
        )
    if not _has_column("t_crm_opportunity", "launch_date"):
        op.add_column(
            "t_crm_opportunity", sa.Column("launch_date", sa.Date(), nullable=True)
        )
    if not _has_column("t_crm_opportunity", "advantage"):
        # MySQL 的 TEXT/BLOB 列不支持 DEFAULT，用 VARCHAR 承载优势说明
        op.add_column(
            "t_crm_opportunity",
            sa.Column("advantage", sa.String(2000), server_default="", nullable=False),
        )
    if not _has_column("t_crm_opportunity", "product_line"):
        op.add_column(
            "t_crm_opportunity",
            sa.Column("product_line", sa.String(500), server_default="", nullable=False),
        )


def downgrade() -> None:
    for column in ("product_line", "advantage", "launch_date", "bid_date"):
        if _has_column("t_crm_opportunity", column):
            op.drop_column("t_crm_opportunity", column)
