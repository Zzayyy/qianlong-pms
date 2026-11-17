"""周报数据模型（`t_wk_weekly`）。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin
from pms.weekly.rules import WeeklyScope, WeeklyStatus


class WkWeekly(Base, CommonMixin):
    """周报表 `t_wk_weekly`：项目周报与个人周总结共用，按范围区分。

    一「人」一「项目」一周只保留一条记录：重新生成时覆盖正文并累加 `revision`，
    状态回到 `GENERATED`，需再次确认。
    """

    __tablename__ = "t_wk_weekly"

    report_no: Mapped[str] = mapped_column(String(32), default="")
    scope: Mapped[str] = mapped_column(String(16), default=WeeklyScope.PROJECT)
    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    #: 项目周报为项目经理；个人周总结为本人
    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    week_start: Mapped[date | None] = mapped_column(Date, default=None)
    week_end: Mapped[date | None] = mapped_column(Date, default=None)
    week_label: Mapped[str] = mapped_column(String(16), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    #: 统计快照（JSON 文本），确认后不再随日志变化
    stats_json: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=WeeklyStatus.GENERATED)
    source: Mapped[str] = mapped_column(String(16), default="MANUAL")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    ai_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_model: Mapped[str] = mapped_column(String(64), default="")
    ai_message: Mapped[str] = mapped_column(String(500), default="")
    confirm_by: Mapped[int] = mapped_column(BigInteger, default=0)
    confirm_time: Mapped[datetime | None] = mapped_column(DateTime, default=None)
