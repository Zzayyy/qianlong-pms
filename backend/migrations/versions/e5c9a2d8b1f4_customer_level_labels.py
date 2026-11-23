"""customer level labels

Revision ID: e5c9a2d8b1f4
Revises: d4e8b1c7a2f9
Create Date: 2026-11-23 15:00:00.000000

变更说明（v1.1.22）：
- 客户等级显示名由「A 类 / B 类 / C 类」改为「重要 / 一般 / 次要」。
  值仍是 A/B/C（`t_crm_customer.customer_level` 不动），老数据无需迁移。
- 只覆盖仍是旧默认显示名的字典项，管理员已自定义过的标签不覆盖。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5c9a2d8b1f4'
down_revision: str | None = 'd4e8b1c7a2f9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (值, 新显示名, 旧显示名候选)
_LABELS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('A', '重要', ('A 类', 'A类')),
    ('B', '一般', ('B 类', 'B类')),
    ('C', '次要', ('C 类', 'C类')),
)


def _set_label(value: str, label: str, old_labels: tuple[str, ...]) -> None:
    """仅把旧默认显示名改成新名字，避免覆盖后台自定义过的标签。"""
    op.execute(
        sa.text(
            'UPDATE t_sys_dict_item SET item_label = :label '
            "WHERE dict_code = 'dict_customer_level' AND item_value = :value "
            'AND item_label IN :old_labels'
        ).bindparams(
            sa.bindparam('label', label),
            sa.bindparam('value', value),
            sa.bindparam('old_labels', old_labels, expanding=True),
        )
    )


def upgrade() -> None:
    for value, label, old_labels in _LABELS:
        _set_label(value, label, old_labels)


def downgrade() -> None:
    for value, label, _old_labels in _LABELS:
        op.execute(
            sa.text(
                'UPDATE t_sys_dict_item SET item_label = :label '
                "WHERE dict_code = 'dict_customer_level' AND item_value = :value"
            ).bindparams(sa.bindparam('label', f'{value} 类'), sa.bindparam('value', value))
        )
