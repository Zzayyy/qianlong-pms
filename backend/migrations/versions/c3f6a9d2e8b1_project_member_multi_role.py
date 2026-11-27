"""project member multi roles

Revision ID: c3f6a9d2e8b1
Revises: b7d2e5a1c9f4
Create Date: 2026-11-27 12:00:00.000000

一人多角色（v1.2）：
- `t_prj_member.role_in_project` 32 → 64 字符，多个角色码用英文逗号拼接（`DEV,TEST`）；
- 历史数据是单值，语义不变，无需回填。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f6a9d2e8b1"
down_revision: str | None = "b7d2e5a1c9f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_length(table: str, column: str) -> int:
    """取列当前长度（读不到时返回 0，按需要加宽处理）。"""
    for item in sa.inspect(op.get_bind()).get_columns(table):
        if item["name"] == column:
            return int(getattr(item["type"], "length", 0) or 0)
    return 0


def upgrade() -> None:
    length = _column_length("t_prj_member", "role_in_project")
    if 0 < length < 64:
        op.alter_column(
            "t_prj_member",
            "role_in_project",
            existing_type=sa.String(length=length),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    length = _column_length("t_prj_member", "role_in_project")
    if length > 32:
        op.alter_column(
            "t_prj_member",
            "role_in_project",
            existing_type=sa.String(length=length),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
