"""project summary and requirement link

Revision ID: b7d2e5a1c9f4
Revises: d3a8c6e2f7b1
Create Date: 2026-11-27 10:00:00.000000

立项表单改造（v1.2）：
- `t_prj_project` 新增 `summary`：一句话简要说明（前端限 200 字）；
- 新增 `t_prj_requirement`：项目与原始需求的多对多关联（立项时可选、可多条）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2e5a1c9f4"
down_revision: str | None = "d3a8c6e2f7b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """列是否已存在（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_table(table: str) -> bool:
    """表是否已存在（同上，便于脚本重跑）。"""
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has_column("t_prj_project", "summary"):
        op.add_column(
            "t_prj_project",
            sa.Column("summary", sa.String(length=200), server_default="", nullable=False),
        )
    if not _has_table("t_prj_requirement"):
        op.create_table(
            "t_prj_requirement",
            sa.Column("project_id", sa.BigInteger(), nullable=False),
            sa.Column("requirement_id", sa.BigInteger(), nullable=False),
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("create_by", sa.BigInteger(), nullable=True),
            sa.Column("create_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.Column("update_by", sa.BigInteger(), nullable=True),
            sa.Column("update_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.Column("deleted", sa.BigInteger(), nullable=False),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_t_prj_requirement")),
        )
        op.create_index(
            op.f("ix_t_prj_requirement_project_id"),
            "t_prj_requirement",
            ["project_id"],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("t_prj_requirement"):
        op.drop_index(op.f("ix_t_prj_requirement_project_id"), table_name="t_prj_requirement")
        op.drop_table("t_prj_requirement")
    if _has_column("t_prj_project", "summary"):
        op.drop_column("t_prj_project", "summary")
