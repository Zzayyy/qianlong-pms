"""worklog issue target

Revision ID: e2b7c9d4a6f1
Revises: c8e4f1a2b6d3
Create Date: 2026-11-25 15:30:00.000000

变更说明：
- `t_wl_item` / `t_wl_worklog` 增加 `issue_id`：日志明细除任务外还可挂
  Bug / 生产问题（`t_iss_issue`），与 `task_id` 二选一；
- `t_iss_issue` 增加 `actual_hours`：由已生效日志明细汇总回写，用于反查缺陷修复工时。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e2b7c9d4a6f1'
down_revision: str | None = 'c8e4f1a2b6d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    """现有列名集合（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    """现有索引名集合。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if 'issue_id' not in _columns('t_wl_worklog'):
        op.add_column(
            't_wl_worklog',
            sa.Column('issue_id', sa.BigInteger(), nullable=False, server_default='0'),
        )
    op.alter_column('t_wl_worklog', 'issue_id', server_default=None)

    if 'issue_id' not in _columns('t_wl_item'):
        op.add_column(
            't_wl_item',
            sa.Column('issue_id', sa.BigInteger(), nullable=False, server_default='0'),
        )
    op.alter_column('t_wl_item', 'issue_id', server_default=None)
    if 'idx_wl_item_issue' not in _indexes('t_wl_item'):
        op.create_index('idx_wl_item_issue', 't_wl_item', ['issue_id'])

    if 'actual_hours' not in _columns('t_iss_issue'):
        op.add_column(
            't_iss_issue',
            sa.Column('actual_hours', sa.Numeric(5, 2), nullable=False, server_default='0'),
        )
    op.alter_column('t_iss_issue', 'actual_hours', server_default=None)


def downgrade() -> None:
    if 'actual_hours' in _columns('t_iss_issue'):
        op.drop_column('t_iss_issue', 'actual_hours')
    if 'idx_wl_item_issue' in _indexes('t_wl_item'):
        op.drop_index('idx_wl_item_issue', table_name='t_wl_item')
    if 'issue_id' in _columns('t_wl_item'):
        op.drop_column('t_wl_item', 'issue_id')
    if 'issue_id' in _columns('t_wl_worklog'):
        op.drop_column('t_wl_worklog', 'issue_id')
