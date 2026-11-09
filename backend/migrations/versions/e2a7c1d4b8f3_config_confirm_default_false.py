"""config worklog confirm default false

Revision ID: e2a7c1d4b8f3
Revises: d9e6a4b3c2f1
Create Date: 2026-11-09 17:10:00.000000

变更说明（v1.1.19）：
- 工作日志暂不需要项目经理确认，`worklog.confirm.required` 默认改为 false；
- 同时把已有环境中的该参数更新为 false，避免代码默认值与数据库旧值不一致。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2a7c1d4b8f3"
down_revision: str | None = "d9e6a4b3c2f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE t_sys_config
        SET config_value = 'false'
        WHERE config_key = 'worklog.confirm.required'
          AND deleted = 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE t_sys_config
        SET config_value = 'true'
        WHERE config_key = 'worklog.confirm.required'
          AND config_value = 'false'
          AND deleted = 0
        """
    )
