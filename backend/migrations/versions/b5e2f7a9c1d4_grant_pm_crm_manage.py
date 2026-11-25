"""grant PM crm manage

Revision ID: b5e2f7a9c1d4
Revises: e2b7c9d4a6f1
Create Date: 2026-11-25 10:00:00.000000

变更说明：产品经理（PM 角色）要能新增客户、原始需求与商机。
- 补 `crm:customer:view` / `crm:customer:manage`：客户与商机菜单可见，且可新增、维护客户；
- 补 `crm:opp:view` / `crm:opp:manage`：原始需求与商机共用该权限点，可新增、维护。

数据范围不变（PM 仍为 PROJECT，只看到本人部门名下的客户 / 商机 / 需求）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'b5e2f7a9c1d4'
down_revision: str | None = 'e2b7c9d4a6f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (角色编码, 权限编码)
_GRANTS: tuple[tuple[str, str], ...] = (
    ('PM', 'crm:customer:view'),
    ('PM', 'crm:customer:manage'),
    ('PM', 'crm:opp:view'),
    ('PM', 'crm:opp:manage'),
)


def upgrade() -> None:
    for role_code, perm_code in _GRANTS:
        op.execute(
            f"""
            INSERT INTO t_sys_role_permission
                (id, role_id, perm_id, create_by, update_by, deleted, tenant_id)
            SELECT UUID_SHORT(), r.id, p.id, NULL, NULL, 0, 1
            FROM t_sys_role r
            JOIN t_sys_permission p
              ON p.deleted = 0
             AND p.perm_code = '{perm_code}'
            WHERE r.role_code = '{role_code}'
              AND r.deleted = 0
              AND NOT EXISTS (
                  SELECT 1 FROM t_sys_role_permission rp
                  WHERE rp.role_id = r.id AND rp.perm_id = p.id AND rp.deleted = 0
              )
            """
        )


def downgrade() -> None:
    for role_code, perm_code in _GRANTS:
        op.execute(
            f"""
            DELETE FROM t_sys_role_permission
            WHERE role_id IN (SELECT id FROM t_sys_role WHERE role_code = '{role_code}')
              AND perm_id IN (SELECT id FROM t_sys_permission WHERE perm_code = '{perm_code}')
            """
        )
