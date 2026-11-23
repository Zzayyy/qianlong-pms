"""crm requirement tables

Revision ID: c3f7a2d8e5b1
Revises: f2a7c4d9e1b3
Create Date: 2026-11-23 17:00:00.000000

原始需求（商机前置环节）：
- `t_crm_requirement`：需求名称、客户（可空）、来源、优先级、期望完成/上线时间、
  预估金额、需求说明（原「备注」）、状态、转成的商机；
- `t_crm_requirement_file`：需求附件关联，文件本体仍写 `t_sys_file`，
  磁盘落在 `data/uploads/requirements/`，不占用项目目录。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f7a2d8e5b1"
down_revision: str | None = "f2a7c4d9e1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "t_crm_requirement",
        sa.Column("req_code", sa.String(length=32), nullable=False),
        sa.Column("req_name", sa.String(length=200), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_dept_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("expect_finish_date", sa.Date(), nullable=True),
        sa.Column("expect_launch_date", sa.Date(), nullable=True),
        sa.Column("expect_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opp_id", sa.BigInteger(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_t_crm_requirement")),
    )
    op.create_index(
        op.f("ix_t_crm_requirement_owner_dept_id"),
        "t_crm_requirement",
        ["owner_dept_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_crm_requirement_customer_id"),
        "t_crm_requirement",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_crm_requirement_status"),
        "t_crm_requirement",
        ["status"],
        unique=False,
    )

    op.create_table(
        "t_crm_requirement_file",
        sa.Column("requirement_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("file_name", sa.String(length=256), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_t_crm_requirement_file")),
    )
    op.create_index(
        op.f("ix_t_crm_requirement_file_requirement_id"),
        "t_crm_requirement_file",
        ["requirement_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_crm_requirement_file_file_id"),
        "t_crm_requirement_file",
        ["file_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_t_crm_requirement_file_file_id"), table_name="t_crm_requirement_file"
    )
    op.drop_index(
        op.f("ix_t_crm_requirement_file_requirement_id"),
        table_name="t_crm_requirement_file",
    )
    op.drop_table("t_crm_requirement_file")
    op.drop_index(op.f("ix_t_crm_requirement_status"), table_name="t_crm_requirement")
    op.drop_index(op.f("ix_t_crm_requirement_customer_id"), table_name="t_crm_requirement")
    op.drop_index(op.f("ix_t_crm_requirement_owner_dept_id"), table_name="t_crm_requirement")
    op.drop_table("t_crm_requirement")
