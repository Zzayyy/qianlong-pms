"""issue tracking table

Revision ID: e7b3d5c9a1f2
Revises: c3f7a2d8e5b1
Create Date: 2026-11-24 10:00:00.000000

变更说明（v1.2.x）：
- 新增 `t_iss_issue`：Bug 与生产问题共用一张单，`issue_type` 区分 BUG / PROD；
- 新增权限点 `issue:view`（查看与提报，所有角色）与 `issue:manage`（维护与关闭）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e7b3d5c9a1f2'
down_revision: str | None = 'c3f7a2d8e5b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (权限编码, 权限名称)
_NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ('issue:view', '问题查看与提报'),
    ('issue:manage', '问题维护'),
)

#: 所有角色都能提报与查看
_ALL_ROLES: tuple[str, ...] = (
    'ADMIN',
    'EXEC',
    'PRODUCT_DIRECTOR',
    'PMO',
    'DEPT_HEAD',
    'SALES',
    'PM',
    'DEV',
    'TEST',
    'OPS',
)

#: 管理 / 关闭权限
_MANAGE_ROLES: tuple[str, ...] = ('ADMIN', 'PMO', 'PM', 'DEPT_HEAD', 'OPS')


def _has_table(table: str) -> bool:
    """表是否已存在。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    """索引是否已存在。"""
    return index in {item['name'] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _grant(role_code: str, perm_code: str) -> None:
    """给角色补权限（只补缺失组合，可重复执行）。"""
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


def upgrade() -> None:
    if not _has_table('t_iss_issue'):
        op.create_table(
            't_iss_issue',
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
            sa.Column('issue_no', sa.String(length=32), server_default='', nullable=False),
            sa.Column('issue_type', sa.String(length=8), server_default='BUG', nullable=False),
            sa.Column('project_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('title', sa.String(length=200), server_default='', nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('severity', sa.String(length=16), server_default='MEDIUM', nullable=False),
            sa.Column('priority', sa.String(length=16), server_default='MEDIUM', nullable=False),
            sa.Column('status', sa.String(length=16), server_default='OPEN', nullable=False),
            sa.Column('owner_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('reporter_id', sa.BigInteger(), server_default='0', nullable=False),
            sa.Column('found_date', sa.Date(), nullable=True),
            sa.Column('close_date', sa.Date(), nullable=True),
            sa.Column('remark', sa.String(length=500), server_default='', nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_t_iss_issue')),
        )
    if not _has_index('t_iss_issue', 'ix_t_iss_issue_project'):
        op.create_index('ix_t_iss_issue_project', 't_iss_issue', ['project_id'])
    if not _has_index('t_iss_issue', 'ix_t_iss_issue_type_status'):
        op.create_index('ix_t_iss_issue_type_status', 't_iss_issue', ['issue_type', 'status'])

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

    for role_code in _ALL_ROLES:
        _grant(role_code, 'issue:view')
    for role_code in _MANAGE_ROLES:
        _grant(role_code, 'issue:manage')


def downgrade() -> None:
    for role_code in _ALL_ROLES + _MANAGE_ROLES:
        op.execute(
            f"""
            DELETE FROM t_sys_role_permission
            WHERE role_id IN (SELECT id FROM t_sys_role WHERE role_code = '{role_code}')
              AND perm_id IN (
                  SELECT id FROM t_sys_permission
                  WHERE perm_code IN ('issue:view', 'issue:manage')
              )
            """
        )
    op.execute("DELETE FROM t_sys_permission WHERE perm_code IN ('issue:view', 'issue:manage')")
    if _has_table('t_iss_issue'):
        if _has_index('t_iss_issue', 'ix_t_iss_issue_type_status'):
            op.drop_index('ix_t_iss_issue_type_status', table_name='t_iss_issue')
        if _has_index('t_iss_issue', 'ix_t_iss_issue_project'):
            op.drop_index('ix_t_iss_issue_project', table_name='t_iss_issue')
        op.drop_table('t_iss_issue')
