"""worklog log type

Revision ID: c8d5f3a2b1e0
Revises: b7c4e2f9a1d0
Create Date: 2026-11-09 15:40:00.000000

变更说明（v1.1.17）：
- `t_wl_worklog` 增加 `log_type`：PROJECT（项目日志）/ PERSONAL（个人日志）；
- 历史日志默认 PROJECT，个人日志不绑定项目，默认仅本人可见。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d5f3a2b1e0"
down_revision: str | None = "b7c4e2f9a1d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """判断列是否已存在，便于失败重跑。"""
    inspector = sa.inspect(op.get_bind())
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("t_wl_worklog", "log_type"):
        op.add_column(
            "t_wl_worklog",
            sa.Column(
                "log_type",
                sa.String(length=16),
                nullable=False,
                server_default="PROJECT",
            ),
        )
    op.alter_column("t_wl_worklog", "log_type", server_default=None)


def downgrade() -> None:
    op.drop_column("t_wl_worklog", "log_type")
