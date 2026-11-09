"""worklog sync main target from detail

Revision ID: b7c4e2f9a1d0
Revises: d8f1c2a4b6e9
Create Date: 2026-11-09 14:30:00.000000

变更说明（v1.1.16）：
- 日志模型明确为「一条日志 = 一个项目 / 一个任务」，`t_wl_item` 作为该日志的唯一明细；
- 历史数据中主表 `project_id` / `task_id` / `total_hours` 为 0、但只有一条有效明细的行，
  按明细回填主表，避免列表与详情显示“非项目/未关联”。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7c4e2f9a1d0"
down_revision: str | None = "d8f1c2a4b6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 仅处理“恰好一条有效明细”的历史日志，多条明细保持原样，避免误合并
    op.execute(
        """
        UPDATE t_wl_worklog w
        JOIN (
            SELECT worklog_id,
                   MIN(project_id) AS project_id,
                   MIN(task_id) AS task_id,
                   SUM(hours) AS hours
            FROM t_wl_item
            WHERE deleted = 0
            GROUP BY worklog_id
            HAVING COUNT(*) = 1
        ) i ON i.worklog_id = w.id
        SET w.project_id = CASE WHEN w.project_id = 0 THEN i.project_id ELSE w.project_id END,
            w.task_id = CASE WHEN w.task_id = 0 THEN i.task_id ELSE w.task_id END,
            w.total_hours = CASE WHEN w.total_hours = 0 THEN i.hours ELSE w.total_hours END
        WHERE w.deleted = 0
          AND (w.project_id = 0 OR w.task_id = 0 OR w.total_hours = 0)
        """
    )


def downgrade() -> None:
    """数据回填不做逆向处理（避免把原本有值的字段误清零）。"""
