"""product description and director role

Revision ID: f2a7c4d9e1b3
Revises: e5c9a2d8b1f4
Create Date: 2026-11-23 16:00:00.000000

变更说明（v1.1.23）：
- `t_crm_product.description`：产品说明（新增/编辑必填，至少 500 字）。
- 产品档案维护权限收口：
  - 新增角色 `PRODUCT_DIRECTOR`（产品总监），拥有 `crm:product:manage`；
  - 其它角色（PMO / 部门领导 / 销售 / 项目经理）收回维护权，只保留查看；
  - `crm:product:view` 补齐给所有角色（产品菜单全员可见）；
  - 产品部的部门负责人自动获得「产品总监」角色（可在人员管理中调整）。
- 参考价字段停用（列保留历史数据，接口与界面不再使用）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pms.common.snowflake import next_id

revision: str = 'f2a7c4d9e1b3'
down_revision: str | None = 'e5c9a2d8b1f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_CODE = 'PRODUCT_DIRECTOR'
_ROLE_NAME = '产品总监'
_PRODUCT_VIEW = 'crm:product:view'
_PRODUCT_MANAGE = 'crm:product:manage'
#: 收回维护权的角色（ADMIN 与 PRODUCT_DIRECTOR 保留）
_REVOKE_ROLES = ('PMO', 'DEPT_HEAD', 'SALES', 'PM')


def _columns(table: str) -> set[str]:
    """现有列名集合（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    return {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _scalar(sql: str, **params: object) -> object:
    """取单值。"""
    return op.get_bind().execute(sa.text(sql), params).scalar()


def _rows(sql: str, **params: object) -> list[tuple]:
    """取多行。"""
    return [tuple(row) for row in op.get_bind().execute(sa.text(sql), params).all()]


def _insert_role_permission(role_id: int, perm_id: int) -> None:
    """补一条角色-权限关联（主键用雪花 ID）。"""
    op.execute(
        sa.text(
            'INSERT INTO t_sys_role_permission '
            '(role_id, perm_id, id, create_time, update_time, deleted, tenant_id) '
            'VALUES (:role_id, :perm_id, :id, NOW(), NOW(), 0, 1)'
        ).bindparams(role_id=role_id, perm_id=perm_id, id=next_id())
    )


def _insert_user_role(user_id: int, role_id: int) -> None:
    """补一条用户-角色关联。"""
    op.execute(
        sa.text(
            'INSERT INTO t_sys_user_role '
            '(user_id, role_id, id, create_time, update_time, deleted, tenant_id) '
            'VALUES (:user_id, :role_id, :id, NOW(), NOW(), 0, 1)'
        ).bindparams(user_id=user_id, role_id=role_id, id=next_id())
    )


def upgrade() -> None:
    if 'description' not in _columns('t_crm_product'):
        op.add_column('t_crm_product', sa.Column('description', sa.Text(), nullable=True))

    # 1) 产品总监角色
    role_id = _scalar(
        'SELECT id FROM t_sys_role WHERE role_code = :code AND deleted = 0', code=_ROLE_CODE
    )
    if role_id is None:
        role_id = next_id()
        op.execute(
            sa.text(
                'INSERT INTO t_sys_role '
                '(role_code, role_name, data_scope, custom_dept_ids, field_whitelist, '
                'builtin, sort, status, id, create_time, update_time, deleted, tenant_id) '
                "VALUES (:code, :name, 'ALL', '', '', 1, 60, 'ENABLED', :id, NOW(), NOW(), 0, 1)"
            ).bindparams(code=_ROLE_CODE, name=_ROLE_NAME, id=role_id)
        )

    view_id = _scalar(
        'SELECT id FROM t_sys_permission WHERE perm_code = :code AND deleted = 0',
        code=_PRODUCT_VIEW,
    )
    manage_id = _scalar(
        'SELECT id FROM t_sys_permission WHERE perm_code = :code AND deleted = 0',
        code=_PRODUCT_MANAGE,
    )

    # 2) 查看权限补齐全员（产品菜单全员可见）
    if view_id is not None:
        granted = {
            int(row[0])
            for row in _rows(
                'SELECT role_id FROM t_sys_role_permission '
                'WHERE perm_id = :perm_id AND deleted = 0',
                perm_id=view_id,
            )
        }
        for (role,) in _rows('SELECT id FROM t_sys_role WHERE deleted = 0'):
            if int(role) not in granted:
                _insert_role_permission(int(role), int(view_id))

    # 3) 维护权限收口：只留 ADMIN / 产品总监
    if manage_id is not None:
        if not _scalar(
            'SELECT id FROM t_sys_role_permission '
            'WHERE role_id = :role_id AND perm_id = :perm_id AND deleted = 0',
            role_id=role_id,
            perm_id=manage_id,
        ):
            _insert_role_permission(int(role_id), int(manage_id))
        placeholders = ', '.join(f':role_{index}' for index in range(len(_REVOKE_ROLES)))
        params: dict[str, object] = {'perm_id': manage_id}
        params.update(
            {f'role_{index}': code for index, code in enumerate(_REVOKE_ROLES)}
        )
        op.execute(
            sa.text(
                'UPDATE t_sys_role_permission rp '
                'JOIN t_sys_role r ON r.id = rp.role_id '
                'SET rp.deleted = 1, rp.update_time = NOW() '
                f'WHERE rp.perm_id = :perm_id AND rp.deleted = 0 AND r.role_code IN ({placeholders})'
            ).bindparams(**params)
        )

    # 4) 产品部负责人自动获得产品总监角色（人员管理里可再调整）
    product_leads = _rows(
        'SELECT DISTINCT u.id FROM t_sys_user u '
        'JOIN t_sys_user_role ur ON ur.user_id = u.id AND ur.deleted = 0 '
        'JOIN t_sys_role r ON r.id = ur.role_id AND r.deleted = 0 '
        'JOIN t_sys_dept d ON d.id = u.dept_id AND d.deleted = 0 '
        "WHERE r.role_code = 'DEPT_HEAD' AND d.dept_code = 'PRODUCT' AND u.deleted = 0"
    )
    for (user_id,) in product_leads:
        exists = _scalar(
            'SELECT id FROM t_sys_user_role '
            'WHERE user_id = :user_id AND role_id = :role_id AND deleted = 0',
            user_id=user_id,
            role_id=role_id,
        )
        if exists is None:
            _insert_user_role(int(user_id), int(role_id))


def downgrade() -> None:
    # 恢复历史维护权（仅覆盖内置角色，自定义角色需人工授予）
    manage_id = _scalar(
        'SELECT id FROM t_sys_permission WHERE perm_code = :code AND deleted = 0',
        code=_PRODUCT_MANAGE,
    )
    if manage_id is not None:
        for role_code in _REVOKE_ROLES:
            role_id = _scalar(
                'SELECT id FROM t_sys_role WHERE role_code = :code AND deleted = 0',
                code=role_code,
            )
            if role_id is None:
                continue
            exists = _scalar(
                'SELECT id FROM t_sys_role_permission '
                'WHERE role_id = :role_id AND perm_id = :perm_id AND deleted = 0',
                role_id=role_id,
                perm_id=manage_id,
            )
            if exists is None:
                _insert_role_permission(int(role_id), int(manage_id))

    # 删除产品总监角色及其关联
    role_id = _scalar(
        'SELECT id FROM t_sys_role WHERE role_code = :code AND deleted = 0', code=_ROLE_CODE
    )
    if role_id is not None:
        op.execute(
            sa.text(
                'UPDATE t_sys_user_role SET deleted = 1, update_time = NOW() '
                'WHERE role_id = :role_id AND deleted = 0'
            ).bindparams(role_id=role_id)
        )
        op.execute(
            sa.text(
                'UPDATE t_sys_role_permission SET deleted = 1, update_time = NOW() '
                'WHERE role_id = :role_id AND deleted = 0'
            ).bindparams(role_id=role_id)
        )
        op.execute(
            sa.text(
                'UPDATE t_sys_role SET deleted = 1, update_time = NOW() WHERE id = :role_id'
            ).bindparams(role_id=role_id)
        )

    if 'description' in _columns('t_crm_product'):
        op.drop_column('t_crm_product', 'description')
