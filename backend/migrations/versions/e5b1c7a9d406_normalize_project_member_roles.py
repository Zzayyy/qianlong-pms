"""normalize project member roles

Revision ID: e5b1c7a9d406
Revises: c9d4e7f1a2b6
Create Date: 2026-11-17 11:30:00.000000

变更说明（v1.2.5）：修复历史数据中一个项目存在多个「项目经理」的问题，
只保留当前负责人（`t_prj_project.pm_id`）的 PM 角色，其余降为普通成员。
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'e5b1c7a9d406'
down_revision: str | None = 'c9d4e7f1a2b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE t_prj_member m
        JOIN t_prj_project p ON p.id = m.project_id
        SET m.role_in_project = 'MEMBER', m.update_time = CURRENT_TIMESTAMP
        WHERE m.deleted = 0 AND m.role_in_project = 'PM' AND m.user_id <> p.pm_id
        """
    )


def downgrade() -> None:
    """历史角色无法还原，回滚仅跳过数据修复。"""
