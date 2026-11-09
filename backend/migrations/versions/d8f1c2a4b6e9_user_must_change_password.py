"""user must change password

Revision ID: d8f1c2a4b6e9
Revises: a7d3e5c9b2f4
Create Date: 2026-11-09 11:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd8f1c2a4b6e9'
down_revision: Union[str, None] = 'a7d3e5c9b2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        't_sys_user',
        sa.Column(
            'must_change_password',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )


def downgrade() -> None:
    op.drop_column('t_sys_user', 'must_change_password')
