"""project retro approval

Revision ID: c6f2a8d4b7e1
Revises: a4c8e2d6b9f1
Create Date: 2026-11-19 21:30:00.000000

变更说明（v1.1.20）：
- 立项审批支持「先开工后补审批」：
  - `t_prj_project.retro_approval`：0=不涉及，1=待补审批，2=补审批被驳回（项目仍执行中）
  - `t_prj_project.retro_due`：补审批期限，逾期仅提示不阻断
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c6f2a8d4b7e1'
down_revision: str | None = 'a4c8e2d6b9f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    """现有列名集合（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns('t_prj_project')
    if 'retro_approval' not in columns:
        op.add_column(
            't_prj_project',
            sa.Column('retro_approval', sa.Integer(), server_default='0', nullable=False),
        )
    if 'retro_due' not in columns:
        op.add_column('t_prj_project', sa.Column('retro_due', sa.Date(), nullable=True))


def downgrade() -> None:
    columns = _columns('t_prj_project')
    if 'retro_due' in columns:
        op.drop_column('t_prj_project', 'retro_due')
    if 'retro_approval' in columns:
        op.drop_column('t_prj_project', 'retro_approval')
