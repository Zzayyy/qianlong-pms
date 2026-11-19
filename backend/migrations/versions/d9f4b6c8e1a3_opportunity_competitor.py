"""opportunity competitor

Revision ID: d9f4b6c8e1a3
Revises: c8e3a5b7d9f2
Create Date: 2026-11-19 16:00:00.000000

变更说明：
- `t_crm_opportunity` 新增 `competitor`：商机竞争对手（自由文本，可写多家）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f4b6c8e1a3"
down_revision: str | None = "c8e3a5b7d9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """列是否已存在（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("t_crm_opportunity", "competitor"):
        op.add_column(
            "t_crm_opportunity",
            sa.Column("competitor", sa.String(200), server_default="", nullable=False),
        )


def downgrade() -> None:
    if _has_column("t_crm_opportunity", "competitor"):
        op.drop_column("t_crm_opportunity", "competitor")
