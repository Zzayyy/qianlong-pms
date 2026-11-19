"""change origin

Revision ID: a1c9e5f7b3d6
Revises: f3a7d1c8e5b2
Create Date: 2026-11-19 10:00:00.000000

变更说明：
- `t_chg_request` 新增 `origin`：区分「走审批链的变更申请」（APPROVAL，默认）与
  「项目详情编辑直接生效的留痕」（INLINE）；存量数据全部按 APPROVAL 处理，
  不影响既有台账与审批状态。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c9e5f7b3d6"
down_revision: str | None = "f3a7d1c8e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """列是否已存在（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("t_chg_request", "origin"):
        op.add_column(
            "t_chg_request",
            sa.Column("origin", sa.String(16), server_default="APPROVAL", nullable=False),
        )


def downgrade() -> None:
    if _has_column("t_chg_request", "origin"):
        op.drop_column("t_chg_request", "origin")
