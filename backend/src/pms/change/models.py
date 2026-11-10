"""变更管理数据模型（设计稿 06；表结构见 04 §4.3）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Date, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.change.state import ApprovalStatus, ChangeStatus
from pms.core.database import Base, CommonMixin


class ChgRequest(Base, CommonMixin):
    """变更申请 `t_chg_request`。"""

    __tablename__ = "t_chg_request"

    request_code: Mapped[str] = mapped_column(String(32), default="")
    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    change_type: Mapped[str] = mapped_column(String(32), default="OTHER")
    title: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    expect_result: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="INTERNAL")
    level: Mapped[str] = mapped_column(String(8), default="")
    status: Mapped[str] = mapped_column(String(32), default=ChangeStatus.DRAFT)
    is_emergency: Mapped[int] = mapped_column(Integer, default=0)
    emergency_due: Mapped[str | None] = mapped_column(Date, default=None)
    schedule_impact_days: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    cost_impact_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    submitter_id: Mapped[int] = mapped_column(BigInteger, default=0)
    pm_id: Mapped[int] = mapped_column(BigInteger, default=0)
    submit_time: Mapped[str | None] = mapped_column(Date, default=None)
    approve_time: Mapped[str | None] = mapped_column(Date, default=None)
    close_time: Mapped[str | None] = mapped_column(Date, default=None)
    baseline_before: Mapped[str] = mapped_column(String(32), default="")
    baseline_after: Mapped[str] = mapped_column(String(32), default="")


class ChgImpact(Base, CommonMixin):
    """六维影响评估 `t_chg_impact`（06 §5.1）。"""

    __tablename__ = "t_chg_impact"

    request_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dimension: Mapped[str] = mapped_column(String(16), default="SCOPE")
    description: Mapped[str] = mapped_column(Text, default="")
    scope_expanded: Mapped[int] = mapped_column(Integer, default=0)
    deliverable_add: Mapped[int] = mapped_column(Integer, default=0)
    deliverable_del: Mapped[int] = mapped_column(Integer, default=0)
    schedule_impact_days: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    new_end_date: Mapped[str | None] = mapped_column(Date, default=None)
    cost_impact_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    new_budget: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    headcount_delta: Mapped[int] = mapped_column(Integer, default=0)
    role_name: Mapped[str] = mapped_column(String(64), default="")
    allocation: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    quality_desc: Mapped[str] = mapped_column(String(500), default="")


class ChgItem(Base, CommonMixin):
    """影响项明细 `t_chg_item`（与 WBS 联动，06 §5.2）。"""

    __tablename__ = "t_chg_item"

    request_id: Mapped[int] = mapped_column(BigInteger, default=0)
    item_type: Mapped[str] = mapped_column(String(16), default="TASK")
    action: Mapped[str] = mapped_column(String(16), default="UPDATE")
    biz_id: Mapped[int] = mapped_column(BigInteger, default=0)
    field_name: Mapped[str] = mapped_column(String(32), default="")
    before_value: Mapped[str] = mapped_column(String(500), default="")
    after_value: Mapped[str] = mapped_column(String(500), default="")
    applied: Mapped[int] = mapped_column(Integer, default=0)


class ChgSchedule(Base, CommonMixin):
    """周期排期明细 `t_chg_schedule`。

    周期变更按「角色 + 负责人 + 日期范围」逐段登记（如开发、测试各一段），
    审批通过后作为影响项落到项目计划与同名阶段的计划起止上。
    """

    __tablename__ = "t_chg_schedule"

    request_id: Mapped[int] = mapped_column(BigInteger, default=0)
    role_name: Mapped[str] = mapped_column(String(32), default="")
    owner_id: Mapped[int] = mapped_column(BigInteger, default=0)
    plan_start: Mapped[str | None] = mapped_column(Date, default=None)
    plan_end: Mapped[str | None] = mapped_column(Date, default=None)
    remark: Mapped[str] = mapped_column(String(255), default="")
    applied: Mapped[int] = mapped_column(Integer, default=0)


class ChgApproval(Base, CommonMixin):
    """变更审批链节点 `t_chg_approval`（06 §4.3 串行）。"""

    __tablename__ = "t_chg_approval"

    request_id: Mapped[int] = mapped_column(BigInteger, default=0)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    node_role: Mapped[str] = mapped_column(String(32), default="PM")
    approver_id: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING)
    opinion: Mapped[str] = mapped_column(String(500), default="")
    approve_time: Mapped[str | None] = mapped_column(Date, default=None)
    sla_days: Mapped[int] = mapped_column(Integer, default=2)
