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
    #: 竞争对手（可写多家，仅作信息记录，不参与统计）
    competitor: Mapped[str] = mapped_column(String(200), default="")
    #: 招标时间 / 计划上线时间（金融类项目常见节点）
    bid_date: Mapped[str | None] = mapped_column(Date, default=None)
    launch_date: Mapped[str | None] = mapped_column(Date, default=None)
    #: 钱龙优势（相对竞品的差异化说明，投标/汇报时直接引用）
    #: 注：MySQL 的 TEXT 列不支持默认值，这里用 VARCHAR 承载，长度足够写几条卖点
    advantage: Mapped[str] = mapped_column(String(2000), default="")
    #: 产品线（多选，逗号分隔存库，前端按标签拆分展示）
    product_line: Mapped[str] = mapped_column(String(500), default="")
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


class ProductStatus(StrEnum):
    """产品状态。"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CrmProduct(Base, CommonMixin):
    """产品档案 `t_crm_product`（报价与方案的基础资料）。

    产品是全公司共享的基础档案，不做部门数据范围隔离：
    有 `crm:product:view` 的角色看到同一份清单。
    """

    __tablename__ = "t_crm_product"

    product_code: Mapped[str] = mapped_column(String(32), default="")
    product_name: Mapped[str] = mapped_column(String(200), default="")
    #: 产品类别：SOFTWARE / HARDWARE / SERVICE / SOLUTION / OTHER
    category: Mapped[str] = mapped_column(String(32), default="SOFTWARE")
    #: 当前版本（沿用历史的 spec 列，避免老数据迁移）
    spec: Mapped[str] = mapped_column(String(200), default="")
    #: 计量单位：套 / 人天 / 年 …
    unit: Mapped[str] = mapped_column(String(16), default="")
    #: 参考价已停用：列保留用于历史数据，新数据不再采集
    price: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(16), default=ProductStatus.ACTIVE)
    #: 产品说明（新增/编辑时必填，至少 500 字）
    description: Mapped[str] = mapped_column(Text, default="")
    remark: Mapped[str] = mapped_column(Text, default="")


class CrmCustomerProduct(Base, CommonMixin):
    """客户关注产品 `t_crm_customer_product`（客户与产品的多对多）。

    只表达"这个客户关注/在用哪些产品"，数量与报价走商机明细，避免两处口径打架。
    """

    __tablename__ = "t_crm_customer_product"

    customer_id: Mapped[int] = mapped_column(BigInteger, default=0)
    product_id: Mapped[int] = mapped_column(BigInteger, default=0)
