"""weekly report table

Revision ID: b8f3d2a6c9e1
Revises: c4e7a1f9b2d6
Create Date: 2026-11-17 10:00:00.000000

周报总结（v1.4.0）：
- `t_wk_weekly`：项目周报与个人周总结共用；
- 同一「项目/人 + 周一」只保留一条，重新生成时覆盖正文并累加 `revision`；
- `status` 区分 `GENERATED`（待确认，可编辑）与 `CONFIRMED`（已确认归档）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8f3d2a6c9e1"
down_revision: str | None = "c4e7a1f9b2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "t_wk_weekly",
        sa.Column("report_no", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("dept_id", sa.BigInteger(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=True),
        sa.Column("week_end", sa.Date(), nullable=True),
        sa.Column("week_label", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ai_used", sa.Integer(), nullable=False),
        sa.Column("ai_model", sa.String(length=64), nullable=False),
        sa.Column("ai_message", sa.String(length=500), nullable=False),
        sa.Column("confirm_by", sa.BigInteger(), nullable=False),
        sa.Column("confirm_time", sa.DateTime(), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("create_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "create_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column("update_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "update_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column("deleted", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_t_wk_weekly")),
    )
    op.create_index(
        op.f("ix_t_wk_weekly_week_start"),
        "t_wk_weekly",
        ["week_start"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_wk_weekly_scope"),
        "t_wk_weekly",
        ["scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_wk_weekly_project_id"),
        "t_wk_weekly",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_wk_weekly_user_id"),
        "t_wk_weekly",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_t_wk_weekly_user_id"), table_name="t_wk_weekly")
    op.drop_index(op.f("ix_t_wk_weekly_project_id"), table_name="t_wk_weekly")
    op.drop_index(op.f("ix_t_wk_weekly_scope"), table_name="t_wk_weekly")
    op.drop_index(op.f("ix_t_wk_weekly_week_start"), table_name="t_wk_weekly")
    op.drop_table("t_wk_weekly")
