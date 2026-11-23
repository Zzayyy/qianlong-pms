"""project risk source and alert mute

Revision ID: d4e8b1c7a2f9
Revises: c6f2a8d4b7e1
Create Date: 2026-11-23 10:00:00.000000

变更说明（v1.1.21）：
- 风险台账区分来源：`t_prj_risk.source`（MANUAL 人工 / WORKLOG 日志 / ALERT 预警转正）、
  `t_prj_risk.source_key`（幂等键，同一条日志或同一个预警只落一条风险）。
- 新增 `t_prj_alert_mute`：预警忽略记录，忽略后在 `muted_until` 之前不再重复提示。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e8b1c7a2f9'
down_revision: str | None = 'c6f2a8d4b7e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    """现有列名集合（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_table(table: str) -> bool:
    """表是否已存在。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    """索引是否已存在。"""
    return index in {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    columns = _columns('t_prj_risk')
    if 'source' not in columns:
        op.add_column(
            't_prj_risk',
            sa.Column('source', sa.String(length=16), server_default='MANUAL', nullable=False),
        )
    if 'source_key' not in columns:
        op.add_column(
            't_prj_risk',
            sa.Column('source_key', sa.String(length=128), server_default='', nullable=False),
        )

    # 历史日志风险回填来源（旧标题形如「日志风险：WL2026...」，据此还原 worklog_no）
    op.execute(
        sa.text(
            "UPDATE t_prj_risk SET source = 'WORKLOG', "
            "source_key = CONCAT('WORKLOG:', SUBSTRING(title, 6)) "
            "WHERE title LIKE '日志风险：%' AND source_key = ''"
        )
    )

    if not _has_table('t_prj_alert_mute'):
        op.create_table(
            't_prj_alert_mute',
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
            sa.Column('project_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('alert_key', sa.String(length=128), server_default='', nullable=False),
            sa.Column('muted_until', sa.Date(), nullable=True),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_t_prj_alert_mute')),
        )
    if not _has_index('t_prj_alert_mute', 'ix_t_prj_alert_mute_project'):
        op.create_index('ix_t_prj_alert_mute_project', 't_prj_alert_mute', ['project_id'])


def downgrade() -> None:
    if _has_table('t_prj_alert_mute'):
        if _has_index('t_prj_alert_mute', 'ix_t_prj_alert_mute_project'):
            op.drop_index('ix_t_prj_alert_mute_project', table_name='t_prj_alert_mute')
        op.drop_table('t_prj_alert_mute')

    columns = _columns('t_prj_risk')
    if 'source_key' in columns:
        op.drop_column('t_prj_risk', 'source_key')
    if 'source' in columns:
        op.drop_column('t_prj_risk', 'source')
