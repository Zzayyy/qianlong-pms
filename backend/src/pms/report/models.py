"""统计预聚合表（设计稿 08 §3）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Date, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin


class StProjectDaily(Base, CommonMixin):
    """项目日快照 `t_st_project_daily`。"""

    __tablename__ = "t_st_project_daily"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    stat_date: Mapped[str | None] = mapped_column(Date, default=None)
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    spi: Mapped[float] = mapped_column(Numeric(8, 4), default=1)
    cpi: Mapped[float] = mapped_column(Numeric(8, 4), default=1)
    health: Mapped[str] = mapped_column(String(16), default="GREEN")
    planned_hours: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    actual_hours: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    delay_days: Mapped[int] = mapped_column(Integer, default=0)


class StWorklogDaily(Base, CommonMixin):
    """人员 × 项目 日工时 `t_st_worklog_daily`。"""

    __tablename__ = "t_st_worklog_daily"

    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    stat_date: Mapped[str | None] = mapped_column(Date, default=None)
    hours: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    is_late: Mapped[int] = mapped_column(Integer, default=0)
    log_status: Mapped[str] = mapped_column(String(32), default="CONFIRMED")
