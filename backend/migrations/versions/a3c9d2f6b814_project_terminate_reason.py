"""project terminate reason

Revision ID: a3c9d2f6b814
Revises: f1a4b7c9d2e6
Create Date: 2026-11-11 10:40:00.000000

变更说明（v1.2.3）：项目支持「终止」，需要留痕。
`t_prj_project` 增加 `terminate_reason`，终止时由 `change_status` 写入。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a3c9d2f6b814'
down_revision: str | None = 'f1a4b7c9d2e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        't_prj_project',
        sa.Column('terminate_reason', sa.Text(), nullable=True, comment='终止原因'),
    )


def downgrade() -> None:
    op.drop_column('t_prj_project', 'terminate_reason')
