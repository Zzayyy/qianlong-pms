"""工作日志数据模型（设计稿 07 §2）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin
from pms.worklog.rules import WorklogStatus


class WlWorklog(Base, CommonMixin):
    """日志主表 `t_wl_worklog`（项目日志 / 个人日志，一人一天可多条）。"""

    __tablename__ = "t_wl_worklog"

    worklog_no: Mapped[str] = mapped_column(String(32), default="")
    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    log_type: Mapped[str] = mapped_column(String(16), default="PROJECT")
    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    task_id: Mapped[int] = mapped_column(BigInteger, default=0)
    log_date: Mapped[str | None] = mapped_column(Date, default=None)
    total_hours: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    problem: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=WorklogStatus.DRAFT)
    is_late: Mapped[int] = mapped_column(Integer, default=0)
    late_days: Mapped[int] = mapped_column(Integer, default=0)
    risk_flag: Mapped[int] = mapped_column(Integer, default=0)
    submit_time: Mapped[str | None] = mapped_column(Date, default=None)
    submit_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    confirm_by: Mapped[int] = mapped_column(BigInteger, default=0)
    confirm_time: Mapped[str | None] = mapped_column(Date, default=None)
    reject_reason: Mapped[str] = mapped_column(String(500), default="")


class WlItem(Base, CommonMixin):
    """日志明细 `t_wl_item`（任务级拆分；每条日志至少一条明细）。"""

    __tablename__ = "t_wl_item"

    worklog_id: Mapped[int] = mapped_column(BigInteger, default=0)
    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    task_id: Mapped[int] = mapped_column(BigInteger, default=0)
    hours: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    content: Mapped[str] = mapped_column(String(1000), default="")
    progress_after: Mapped[float] = mapped_column(Numeric(5, 2), default=0)


class WlComment(Base, CommonMixin):
    """日志评论 `t_wl_comment`。"""

    __tablename__ = "t_wl_comment"

    worklog_id: Mapped[int] = mapped_column(BigInteger, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    content: Mapped[str] = mapped_column(String(1000), default="")


class WlReminder(Base, CommonMixin):
    """日志催办 `t_wl_reminder`。"""

    __tablename__ = "t_wl_reminder"

    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    log_date: Mapped[str | None] = mapped_column(Date, default=None)
    remind_type: Mapped[str] = mapped_column(String(16), default="AUTO")
    remind_by: Mapped[int] = mapped_column(BigInteger, default=0)
    content: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
