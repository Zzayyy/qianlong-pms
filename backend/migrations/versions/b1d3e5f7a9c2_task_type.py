"""task type column

Revision ID: b1d3e5f7a9c2
Revises: f4d6b8a2c1e3
Create Date: 2026-11-24 16:00:00.000000

变更说明：`t_prj_task` 新增 `task_type`（REQ/DEV/TEST/DOC/OPS），
仅作任务分类标签，不参与进度与工时计算；历史任务留空表示未分类。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b1d3e5f7a9c2'
down_revision: str | None = 'f4d6b8a2c1e3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    """现有列名集合（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if 'task_type' not in _columns('t_prj_task'):
        op.add_column(
            't_prj_task',
            sa.Column(
                'task_type',
                sa.String(length=16),
                server_default='',
                nullable=False,
            ),
        )


def downgrade() -> None:
    if 'task_type' in _columns('t_prj_task'):
        op.drop_column('t_prj_task', 'task_type')
