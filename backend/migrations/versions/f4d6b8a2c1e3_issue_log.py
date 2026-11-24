"""issue operation log

Revision ID: f4d6b8a2c1e3
Revises: e7b3d5c9a1f2
Create Date: 2026-11-24 14:00:00.000000

变更说明：新增 `t_iss_issue_log`，记录问题的创建、字段修改（含指派）、状态流转与删除，
供问题详情页「历史记录」展示。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f4d6b8a2c1e3'
down_revision: str | None = 'e7b3d5c9a1f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    """表是否已存在。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    """索引是否已存在。"""
    return index in {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_table('t_iss_issue_log'):
        op.create_table(
            't_iss_issue_log',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('create_by', sa.BigInteger(), nullable=True),
            sa.Column(
                'create_time',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=True,
            ),
            sa.Column('update_by', sa.BigInteger(), nullable=True),
            sa.Column(
                'update_time',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=True,
            ),
            sa.Column('deleted', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('tenant_id', sa.BigInteger(), server_default='1', nullable=False),
            sa.Column('issue_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('action', sa.String(length=16), server_default='', nullable=False),
            sa.Column('field', sa.String(length=32), server_default='', nullable=False),
            sa.Column('old_value', sa.String(length=500), server_default='', nullable=False),
            sa.Column('new_value', sa.String(length=500), server_default='', nullable=False),
            sa.Column('operator_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_t_iss_issue_log')),
        )
    if not _has_index('t_iss_issue_log', 'ix_t_iss_issue_log_issue'):
        op.create_index('ix_t_iss_issue_log_issue', 't_iss_issue_log', ['issue_id'])


def downgrade() -> None:
    if _has_table('t_iss_issue_log'):
        if _has_index('t_iss_issue_log', 'ix_t_iss_issue_log_issue'):
            op.drop_index('ix_t_iss_issue_log_issue', table_name='t_iss_issue_log')
        op.drop_table('t_iss_issue_log')
