"""weekly prompt template table

Revision ID: d3a8c6e2f7b1
Revises: b5e2f7a9c1d4
Create Date: 2026-11-26 10:00:00.000000

周报提示词可配置：
- `t_wk_prompt`：按「范围 + 部门」存放提示词模板，`dept_id=0` 为全公司默认；
- 同一 `scope + dept_id` 只保留一条，匹配时按「本部门 → 上级部门 → 全公司默认 → 代码内置」；
- 默认模板由接口首次访问时幂等补齐，迁移不写死业务文案，便于后续调整。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a8c6e2f7b1"
down_revision: str | None = "b5e2f7a9c1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "t_wk_prompt",
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("dept_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("builtin", sa.Integer(), nullable=False),
        sa.Column("remark", sa.String(length=200), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_t_wk_prompt")),
    )
    op.create_index(
        op.f("ix_t_wk_prompt_scope"),
        "t_wk_prompt",
        ["scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_t_wk_prompt_dept_id"),
        "t_wk_prompt",
        ["dept_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_t_wk_prompt_dept_id"), table_name="t_wk_prompt")
    op.drop_index(op.f("ix_t_wk_prompt_scope"), table_name="t_wk_prompt")
    op.drop_table("t_wk_prompt")
