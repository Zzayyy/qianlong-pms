"""CRM 数据模型（设计稿 04 §4.2.1）。"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import BigInteger, Date, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin


class CustomerStatus(StrEnum):
    """客户状态。"""

    POTENTIAL = "POTENTIAL"
    COOPERATING = "COOPERATING"
    LOST = "LOST"
    BLACKLIST = "BLACKLIST"


class OpportunityStage(StrEnum):
    """商机阶段。"""

    LEAD = "LEAD"
    CONTACT = "CONTACT"
    PROPOSAL = "PROPOSAL"
    QUOTE = "QUOTE"
    WON = "WON"
    LOST = "LOST"


class OpportunityStatus(StrEnum):
    """商机状态。"""

    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    CLOSED = "CLOSED"


class CrmCustomer(Base, CommonMixin):
    """客户 `t_crm_customer`。"""

    __tablename__ = "t_crm_customer"

    customer_code: Mapped[str] = mapped_column(String(32), default="")
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    customer_level: Mapped[str] = mapped_column(String(16), default="C")
    industry: Mapped[str] = mapped_column(String(64), default="")
    owner_user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    owner_dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    contact_name: Mapped[str] = mapped_column(String(64), default="")
    contact_mobile: Mapped[str] = mapped_column(String(32), default="")
    contact_email: Mapped[str] = mapped_column(String(128), default="")
    province: Mapped[str] = mapped_column(String(64), default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(String(256), default="")
    source: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default=CustomerStatus.POTENTIAL)
    remark: Mapped[str] = mapped_column(Text, default="")


class CrmContact(Base, CommonMixin):
    """客户联系人 `t_crm_contact`（手机/邮箱为敏感字段，出口脱敏）。"""

    __tablename__ = "t_crm_contact"

    customer_id: Mapped[int] = mapped_column(BigInteger, default=0)
    name: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(64), default="")
    mobile: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    wechat: Mapped[str] = mapped_column(String(64), default="")
    is_primary: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str] = mapped_column(String(256), default="")


class CrmOpportunity(Base, CommonMixin):
    """商机 `t_crm_opportunity`。"""

    __tablename__ = "t_crm_opportunity"

    opp_code: Mapped[str] = mapped_column(String(32), default="")
    opp_name: Mapped[str] = mapped_column(String(200), default="")
    customer_id: Mapped[int] = mapped_column(BigInteger, default=0)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    owner_dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    expect_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    expect_sign_date: Mapped[str | None] = mapped_column(Date, default=None)
    stage: Mapped[str] = mapped_column(String(32), default=OpportunityStage.LEAD)
    win_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    source: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default=OpportunityStatus.OPEN)
    converted_project_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    converted_time: Mapped[str | None] = mapped_column(Date, default=None)
    lost_reason: Mapped[str] = mapped_column(String(500), default="")
    remark: Mapped[str] = mapped_column(Text, default="")


class CrmFollow(Base, CommonMixin):
    """商机跟进 `t_crm_follow`。"""

    __tablename__ = "t_crm_follow"

    opp_id: Mapped[int] = mapped_column(BigInteger, default=0)
    follow_type: Mapped[str] = mapped_column(String(32), default="PHONE")
    content: Mapped[str] = mapped_column(Text, default="")
    follow_time: Mapped[str | None] = mapped_column(Date, default=None)
    next_plan: Mapped[str] = mapped_column(String(500), default="")
