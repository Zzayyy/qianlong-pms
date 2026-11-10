"""role permission matrix tune

Revision ID: f1a4b7c9d2e6
Revises: d6b2c8e14f97
Create Date: 2026-11-10 17:20:00.000000

变更说明（v1.2.2）：按角色职责补齐三处权限缺口
- SALES（销售）：补 `change:view`，客户商机转化的项目发生变更时可查看进度；
- DEPT_HEAD（部门领导）：补 `project:approve`，与「L2 立项需部门负责人审批」规则对齐；
- PMO：补 `change:create`，PMO 可代项目经理发起变更（数据层本就允许其发起）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'f1a4b7c9d2e6'
down_revision: str | None = 'd6b2c8e14f97'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (角色编码, 权限编码)
_GRANTS: tuple[tuple[str, str], ...] = (
    ('SALES', 'change:view'),
    ('DEPT_HEAD', 'project:approve'),
    ('PMO', 'change:create'),
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
