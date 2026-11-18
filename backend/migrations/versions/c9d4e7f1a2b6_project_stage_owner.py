"""project stage owner

Revision ID: c9d4e7f1a2b6
Revises: b8f3d2a6c9e1
Create Date: 2026-11-17 09:00:00.000000

变更说明（v1.2.4）：新建项目时可一次录入四个阶段的负责人，
`t_prj_stage` 增加 `owner_id` 保存阶段负责人。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c9d4e7f1a2b6'
down_revision: str | None = 'b8f3d2a6c9e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        't_prj_stage',
        sa.Column(
            'owner_id', sa.BigInteger(), server_default='0', nullable=False, comment='阶段负责人用户ID'
        ),
    )


def downgrade() -> None:
    op.drop_column('t_prj_stage', 'owner_id')
