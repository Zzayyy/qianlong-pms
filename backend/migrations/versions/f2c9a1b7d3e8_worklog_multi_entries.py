"""worklog multi entries per day

Revision ID: f2c9a1b7d3e8
Revises: 4487470be008
Create Date: 2026-11-03 13:20:00.000000

变更说明（v1.1.15）：
- `t_wl_worklog` 增加 `project_id` / `task_id`：一条日志绑定一个项目，一人一天可多条；
- 按历史明细回填 `project_id`，便于列表与统计直接展示项目；
- 新增参数 `worklog.backfill.maxDays=5`（补填窗口），
  并把 `worklog.hours.warnPerDay` 的旧默认值 12 调整为 8（超过仅提示，不禁止）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f2c9a1b7d3e8'
down_revision: str | None = '4487470be008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """判断列是否已存在（MySQL DDL 非事务，失败重跑时避免重复加列）。"""
    inspector = sa.inspect(op.get_bind())
    return column in {item["name"] for item in inspector.get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    """判断索引是否已存在。"""
    inspector = sa.inspect(op.get_bind())
    return index in {item["name"] for item in inspector.get_indexes(table)}


def upgrade() -> None:
    if not _has_column('t_wl_worklog', 'project_id'):
        op.add_column(
            't_wl_worklog',
            sa.Column('project_id', sa.BigInteger(), nullable=False, server_default='0'),
        )
    if not _has_column('t_wl_worklog', 'task_id'):
        op.add_column(
            't_wl_worklog',
            sa.Column('task_id', sa.BigInteger(), nullable=False, server_default='0'),
        )
    op.alter_column('t_wl_worklog', 'project_id', server_default=None)
    op.alter_column('t_wl_worklog', 'task_id', server_default=None)
    if not _has_index('t_wl_worklog', 'ix_t_wl_worklog_user_date'):
        op.create_index(
            'ix_t_wl_worklog_user_date', 't_wl_worklog', ['user_id', 'log_date']
        )

    # 历史数据回填：明细只对应一个项目时写入主表（无明细的行保持 0）
    op.execute(
        """
        UPDATE t_wl_worklog w
        SET w.project_id = COALESCE((
            SELECT MIN(i.project_id) FROM t_wl_item i
            WHERE i.worklog_id = w.id AND i.project_id > 0 AND i.deleted = 0
        ), 0)
        WHERE w.project_id = 0
        """
    )

    # 新增补填窗口参数（后台可调）
    op.execute(
        """
        INSERT INTO t_sys_config
            (id, config_key, config_value, value_type, group_name, remark, builtin,
             create_by, update_by, deleted, tenant_id)
        SELECT
            (SELECT COALESCE(MAX(c.id), 0) + 1 FROM t_sys_config c),
            'worklog.backfill.maxDays', '5', 'INT', '工作日志',
            '允许补填的最大天数（含当日，默认 5 天）', 1, NULL, NULL, 0, 1
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM t_sys_config x
            WHERE x.config_key = 'worklog.backfill.maxDays' AND x.deleted = 0
        )
        """
    )
    # 旧默认值 12h 调整为 8h；已被人工改过的值保持不动
    op.execute(
        """
        UPDATE t_sys_config
        SET config_value = '8'
        WHERE config_key = 'worklog.hours.warnPerDay'
          AND config_value = '12' AND deleted = 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM t_sys_config
        WHERE config_key = 'worklog.backfill.maxDays' AND config_value = '5'
        """
    )
    op.execute(
        """
        UPDATE t_sys_config
        SET config_value = '12'
        WHERE config_key = 'worklog.hours.warnPerDay'
          AND config_value = '8' AND deleted = 0
        """
    )
    op.drop_index('ix_t_wl_worklog_user_date', table_name='t_wl_worklog')
    op.drop_column('t_wl_worklog', 'task_id')
    op.drop_column('t_wl_worklog', 'project_id')
