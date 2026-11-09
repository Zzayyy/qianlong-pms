"""worklog submit at

Revision ID: d9e6a4b3c2f1
Revises: c8d5f3a2b1e0
Create Date: 2026-11-09 16:10:00.000000

变更说明（v1.1.18）：
- `t_wl_worklog` 增加 `submit_at`，记录实际提交时间；
- 用于 `worklog.daily.deadlineHour` 判断当日提交是否超过截止时间；
- 历史日志保持 NULL，及时率继续沿用原有 `is_late`。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e6a4b3c2f1"
down_revision: str | None = "c8d5f3a2b1e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("t_wl_worklog", "submit_at"):
        op.add_column(
            "t_wl_worklog",
            sa.Column("submit_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("t_wl_worklog", "submit_at")
