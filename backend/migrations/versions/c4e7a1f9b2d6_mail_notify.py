"""mail notify tables

Revision ID: c4e7a1f9b2d6
Revises: a3c9d2f6b814
Create Date: 2026-11-13 16:30:00.000000

邮件通知（v1.3.0）：
- `t_sys_mail_template`：按事件编码配置的主题/正文模板；
- `t_sys_mail_log`：发送记录，同时作为待发队列（outbox）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e7a1f9b2d6'
down_revision: Union[str, None] = 'a3c9d2f6b814'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        't_sys_mail_template',
        sa.Column('event_code', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('subject', sa.String(length=512), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('receiver_roles', sa.String(length=255), nullable=False),
        sa.Column('enabled', sa.Integer(), nullable=False),
        sa.Column('builtin', sa.Integer(), nullable=False),
        sa.Column('remark', sa.String(length=255), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('create_by', sa.BigInteger(), nullable=True),
        sa.Column('create_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('update_by', sa.BigInteger(), nullable=True),
        sa.Column('update_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('deleted', sa.BigInteger(), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_t_sys_mail_template')),
    )
    op.create_index(
        op.f('ix_t_sys_mail_template_event_code'),
        't_sys_mail_template',
        ['event_code'],
        unique=False,
    )
    op.create_table(
        't_sys_mail_log',
        sa.Column('event_code', sa.String(length=64), nullable=False),
        sa.Column('biz_type', sa.String(length=64), nullable=False),
        sa.Column('biz_id', sa.BigInteger(), nullable=False),
        sa.Column('recipient', sa.String(length=128), nullable=False),
        sa.Column('recipient_name', sa.String(length=128), nullable=False),
        sa.Column('subject', sa.String(length=512), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.String(length=512), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('create_by', sa.BigInteger(), nullable=True),
        sa.Column('create_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('update_by', sa.BigInteger(), nullable=True),
        sa.Column('update_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('deleted', sa.BigInteger(), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_t_sys_mail_log')),
    )
    op.create_index(
        op.f('ix_t_sys_mail_log_event_code'),
        't_sys_mail_log',
        ['event_code'],
        unique=False,
    )
    op.create_index(
        op.f('ix_t_sys_mail_log_status'),
        't_sys_mail_log',
        ['status'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_t_sys_mail_log_status'), table_name='t_sys_mail_log')
    op.drop_index(op.f('ix_t_sys_mail_log_event_code'), table_name='t_sys_mail_log')
    op.drop_table('t_sys_mail_log')
    op.drop_index(
        op.f('ix_t_sys_mail_template_event_code'), table_name='t_sys_mail_template'
    )
    op.drop_table('t_sys_mail_template')
