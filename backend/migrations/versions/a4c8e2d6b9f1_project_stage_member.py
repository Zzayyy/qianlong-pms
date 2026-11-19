"""project stage member

Revision ID: a4c8e2d6b9f1
Revises: e1a7c9d3f5b8
Create Date: 2026-11-19 10:00:00.000000

变更说明（v1.1.19）：
- 新增 `t_prj_stage_member`：阶段参与人。与 `t_prj_stage.owner_id`（阶段负责人）
  共同构成「负责人 + 参与人」的两层分工，立项建阶段时可一并指定，
  新建任务时优先从该阶段成员里选负责人。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a4c8e2d6b9f1'
down_revision: str | None = 'e1a7c9d3f5b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    """表是否已存在（MySQL DDL 非事务，失败重跑时避免重复建表）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    """索引是否已存在。"""
    return index in {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_table('t_prj_stage_member'):
        op.create_table(
            't_prj_stage_member',
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
            sa.Column('stage_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('user_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column(
                'role_in_stage', sa.String(length=32), server_default='MEMBER', nullable=False
            ),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_t_prj_stage_member')),
        )
    if not _has_index('t_prj_stage_member', 'ix_t_prj_stage_member_stage'):
        op.create_index('ix_t_prj_stage_member_stage', 't_prj_stage_member', ['stage_id'])
    if not _has_index('t_prj_stage_member', 'ix_t_prj_stage_member_user'):
        op.create_index('ix_t_prj_stage_member_user', 't_prj_stage_member', ['user_id'])


def downgrade() -> None:
    if _has_index('t_prj_stage_member', 'ix_t_prj_stage_member_user'):
        op.drop_index('ix_t_prj_stage_member_user', table_name='t_prj_stage_member')
    if _has_index('t_prj_stage_member', 'ix_t_prj_stage_member_stage'):
        op.drop_index('ix_t_prj_stage_member_stage', table_name='t_prj_stage_member')
    if _has_table('t_prj_stage_member'):
        op.drop_table('t_prj_stage_member')
