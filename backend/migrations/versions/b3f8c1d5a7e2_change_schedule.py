"""change schedule detail

Revision ID: b3f8c1d5a7e2
Revises: e2a7c1d4b8f3
Create Date: 2026-11-10 10:00:00.000000

变更说明（v1.2.0）：
- 新增 `t_chg_schedule`：周期变更按「角色（开发/测试/…）+ 负责人 + 日期范围」登记排期，
  审批通过后折算为影响项落到项目计划起止与同名阶段的计划起止；
- 新增参数 `change.schedule.roles`（排期可选角色，英文逗号分隔）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b3f8c1d5a7e2'
down_revision: str | None = 'e2a7c1d4b8f3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = 'change.schedule.roles'
_CONFIG_VALUE = '开发,测试,实施,运维'


def _has_table(table: str) -> bool:
    """表是否已存在（MySQL DDL 非事务，失败重跑时避免重复建表）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    """索引是否已存在。"""
    return index in {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_table('t_chg_schedule'):
        op.create_table(
            't_chg_schedule',
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
            sa.Column('request_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('role_name', sa.String(length=32), server_default='', nullable=False),
            sa.Column('owner_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('plan_start', sa.Date(), nullable=True),
            sa.Column('plan_end', sa.Date(), nullable=True),
            sa.Column('remark', sa.String(length=255), server_default='', nullable=False),
            sa.Column('applied', sa.Integer(), server_default='0', nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_t_chg_schedule')),
        )
    if not _has_index('t_chg_schedule', 'ix_t_chg_schedule_request'):
        op.create_index('ix_t_chg_schedule_request', 't_chg_schedule', ['request_id'])

    op.execute(
        f"""
        INSERT INTO t_sys_config
            (id, config_key, config_value, value_type, group_name, remark, builtin,
             create_by, update_by, deleted, tenant_id)
        SELECT (SELECT COALESCE(MAX(c.id), 0) + 1 FROM t_sys_config c),
               '{_CONFIG_KEY}', '{_CONFIG_VALUE}', 'STRING', '变更管理',
               '周期变更排期可选角色（英文逗号分隔），如「开发,测试,实施,运维」', 1,
               NULL, NULL, 0, 1
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM t_sys_config x
            WHERE x.config_key = '{_CONFIG_KEY}' AND x.deleted = 0
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM t_sys_config WHERE config_key = '{_CONFIG_KEY}' AND deleted = 0")
    if _has_index('t_chg_schedule', 'ix_t_chg_schedule_request'):
        op.drop_index('ix_t_chg_schedule_request', table_name='t_chg_schedule')
    if _has_table('t_chg_schedule'):
        op.drop_table('t_chg_schedule')
