"""issue product link

Revision ID: c8e4f1a2b6d3
Revises: b1d3e5f7a9c2
Create Date: 2026-11-25 10:00:00.000000

变更说明：`t_iss_issue` 新增 `product_id`（关联 `t_crm_product`），
让生产问题在项目结束之后仍能按产品归集；历史数据留 0 表示未关联产品。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c8e4f1a2b6d3'
down_revision: str | None = 'b1d3e5f7a9c2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    """现有列名集合（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    """现有索引名集合。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if 'product_id' not in _columns('t_iss_issue'):
        op.add_column(
            't_iss_issue',
            sa.Column('product_id', sa.BigInteger(), server_default='0', nullable=False),
        )
    if 'idx_iss_issue_product' not in _indexes('t_iss_issue'):
        op.create_index('idx_iss_issue_product', 't_iss_issue', ['product_id'])


def downgrade() -> None:
    if 'idx_iss_issue_product' in _indexes('t_iss_issue'):
        op.drop_index('idx_iss_issue_product', table_name='t_iss_issue')
    if 'product_id' in _columns('t_iss_issue'):
        op.drop_column('t_iss_issue', 'product_id')
