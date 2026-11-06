"""project director and project docs

Revision ID: a7d3e5c9b2f4
Revises: f2c9a1b7d3e8
Create Date: 2026-11-03 14:00:00.000000

变更说明（v1.1.16）：
- 新增 `t_prj_director`：项目总监（项目级授权、可多人，变更审批会签）；
- 新增权限点 `project:stage:edit` / `project:doc:upload` / `project:doc:manage` 并授权；
- 为 EXEC/PMO/DEPT_HEAD 补 `worklog:create`（日志全员可填）；
- 新增参数 `project.stage.docRequired` 与 `worklog.remind.enabled`。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a7d3e5c9b2f4'
down_revision: str | None = 'f2c9a1b7d3e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ('project:stage:edit', '阶段与里程碑维护'),
    ('project:doc:upload', '项目文档上传'),
    ('project:doc:manage', '项目文档管理'),
)

_NEW_CONFIGS: tuple[tuple[str, str, str, str], ...] = (
    ('project.stage.docRequired', 'true', 'BOOL', '项目'),
    ('worklog.remind.enabled', 'true', 'BOOL', '工作日志'),
)


def _has_table(table: str) -> bool:
    """表是否已存在（MySQL DDL 非事务，失败重跑时避免重复建表）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    """索引是否已存在。"""
    return index in {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_table('t_prj_director'):
        op.create_table(
            't_prj_director',
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
            sa.Column('user_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('assigned_by', sa.BigInteger(), server_default='0', nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_t_prj_director')),
        )
    if not _has_index('t_prj_director', 'ix_t_prj_director_project_user'):
        op.create_index(
            'ix_t_prj_director_project_user',
            't_prj_director',
            ['project_id', 'user_id'],
        )

    # 权限点
    for code, name in _NEW_PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO t_sys_permission
                (id, perm_code, perm_name, perm_type, parent_id, path, component, icon, sort,
                 create_by, update_by, deleted, tenant_id)
            SELECT UUID_SHORT(), '{code}', '{name}', 'API', 0, '', '', '', 0,
                   NULL, NULL, 0, 1
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM t_sys_permission x
                WHERE x.perm_code = '{code}' AND x.deleted = 0
            )
            """
        )

    # 角色授权（只补缺失组合）
    op.execute(
        """
        INSERT INTO t_sys_role_permission
            (id, role_id, perm_id, create_by, update_by, deleted, tenant_id)
        SELECT UUID_SHORT(), r.id, p.id, NULL, NULL, 0, 1
        FROM t_sys_role r
        JOIN t_sys_permission p
          ON p.deleted = 0
         AND (
              (r.role_code IN ('ADMIN', 'PMO', 'PM')
               AND p.perm_code IN (
                   'project:stage:edit', 'project:doc:upload', 'project:doc:manage'
               ))
           OR (r.role_code IN ('EXEC', 'DEPT_HEAD', 'SALES', 'DEV', 'TEST', 'OPS')
               AND p.perm_code = 'project:doc:upload')
           OR (r.role_code IN ('EXEC', 'PMO', 'DEPT_HEAD')
               AND p.perm_code = 'worklog:create')
         )
        WHERE r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM t_sys_role_permission rp
              WHERE rp.role_id = r.id AND rp.perm_id = p.id AND rp.deleted = 0
          )
        """
    )

    # 参数
    for key, value, value_type, group in _NEW_CONFIGS:
        op.execute(
            f"""
            INSERT INTO t_sys_config
                (id, config_key, config_value, value_type, group_name, remark, builtin,
                 create_by, update_by, deleted, tenant_id)
            SELECT (SELECT COALESCE(MAX(c.id), 0) + 1 FROM t_sys_config c),
                   '{key}', '{value}', '{value_type}', '{group}',
                   'v1.1.16 新增参数', 1, NULL, NULL, 0, 1
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM t_sys_config x
                WHERE x.config_key = '{key}' AND x.deleted = 0
            )
            """
        )


def downgrade() -> None:
    for key, _, _, _ in _NEW_CONFIGS:
        op.execute(
            f"DELETE FROM t_sys_config WHERE config_key = '{key}' AND deleted = 0"
        )
    codes = "', '".join(code for code, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM t_sys_role_permission
        WHERE perm_id IN (SELECT id FROM t_sys_permission WHERE perm_code IN ('{codes}'))
        """
    )
    op.execute(f"DELETE FROM t_sys_permission WHERE perm_code IN ('{codes}')")
    if _has_index('t_prj_director', 'ix_t_prj_director_project_user'):
        op.drop_index('ix_t_prj_director_project_user', table_name='t_prj_director')
    if _has_table('t_prj_director'):
        op.drop_table('t_prj_director')
