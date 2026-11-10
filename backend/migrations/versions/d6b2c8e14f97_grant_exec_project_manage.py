"""grant exec project manage permissions

Revision ID: d6b2c8e14f97
Revises: b3f8c1d5a7e2
Create Date: 2026-11-10 15:00:00.000000

变更说明（v1.2.1）：
- 公司领导（EXEC）补齐项目维护权限：`project:edit` / `project:stage:edit` / `project:doc:manage`；
  数据层已把 EXEC 视为项目管理者，缺功能权限点会导致「能看不能动」并报 40301；
- 系统管理员（ADMIN）本就拥有全部权限点，代码层补齐项目管理者兜底判定（见 `is_project_manager`）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'd6b2c8e14f97'
down_revision: str | None = 'b3f8c1d5a7e2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERM_CODES: tuple[str, ...] = (
    'project:edit',
    'project:stage:edit',
    'project:doc:manage',
)


def upgrade() -> None:
    codes = "', '".join(_PERM_CODES)
    op.execute(
        f"""
        INSERT INTO t_sys_role_permission
            (id, role_id, perm_id, create_by, update_by, deleted, tenant_id)
        SELECT UUID_SHORT(), r.id, p.id, NULL, NULL, 0, 1
        FROM t_sys_role r
        JOIN t_sys_permission p
          ON p.deleted = 0
         AND p.perm_code IN ('{codes}')
        WHERE r.role_code = 'EXEC'
          AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM t_sys_role_permission rp
              WHERE rp.role_id = r.id AND rp.perm_id = p.id AND rp.deleted = 0
          )
        """
    )


def downgrade() -> None:
    codes = "', '".join(_PERM_CODES)
    op.execute(
        f"""
        DELETE FROM t_sys_role_permission
        WHERE role_id IN (SELECT id FROM t_sys_role WHERE role_code = 'EXEC')
          AND perm_id IN (SELECT id FROM t_sys_permission WHERE perm_code IN ('{codes}'))
        """
    )
