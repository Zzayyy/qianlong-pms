"""project notify switch

Revision ID: f3a7d1c8e5b2
Revises: e5b1c7a9d406
Create Date: 2026-11-18 10:00:00.000000

变更说明（v1.1.18）：
- `t_prj_project` 新增 `notify_enabled`：项目级「自动通知」开关（默认 1=开启）。
  关闭后该项目不再为立项提交 / 审批结果 / 状态变更等事件排队邮件，
  其它项目不受影响（全局 SMTP 与事件模板开关仍然生效）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f3a7d1c8e5b2'
down_revision: str | None = 'e5b1c7a9d406'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """列是否已存在（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return column in {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column('t_prj_project', 'notify_enabled'):
        op.add_column(
            't_prj_project',
            sa.Column('notify_enabled', sa.Integer(), server_default='1', nullable=False),
        )


def downgrade() -> None:
    if _has_column('t_prj_project', 'notify_enabled'):
        op.drop_column('t_prj_project', 'notify_enabled')
