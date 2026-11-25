"""问题跟踪数据模型（Bug 与生产问题共用一张表）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin
from pms.issue.state import IssueStatus, IssueType, Priority, Severity


class IssIssue(Base, CommonMixin):
    """问题单 `t_iss_issue`。

    `issue_type` 区分 BUG（项目内缺陷）与 PROD（上线后的生产问题），
    两者字段一致，列表页按类型过滤即可，避免维护两套结构。
    """

    __tablename__ = "t_iss_issue"

    issue_no: Mapped[str] = mapped_column(String(32), default="")
    issue_type: Mapped[str] = mapped_column(String(8), default=IssueType.BUG)
    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    #: 关联产品（`t_crm_product.id`）：项目交付后的问题靠产品归集，0 表示未关联
    product_id: Mapped[int] = mapped_column(BigInteger, default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default=Severity.MEDIUM)
    priority: Mapped[str] = mapped_column(String(16), default=Priority.MEDIUM)
    status: Mapped[str] = mapped_column(String(16), default=IssueStatus.OPEN)
    owner_id: Mapped[int] = mapped_column(BigInteger, default=0)
    reporter_id: Mapped[int] = mapped_column(BigInteger, default=0)
    found_date: Mapped[str | None] = mapped_column(Date, default=None)
    close_date: Mapped[str | None] = mapped_column(Date, default=None)
    remark: Mapped[str] = mapped_column(String(500), default="")


class IssLog(Base, CommonMixin):
    """问题操作历史 `t_iss_issue_log`。

    `action`：CREATE 建单 / UPDATE 改字段 / STATUS 状态流转 / DELETE 删除；
    `field` 为变更字段（title/ownerId/status…），`old_value`/`new_value` 存人可读文本。
    """

    __tablename__ = "t_iss_issue_log"

    issue_id: Mapped[int] = mapped_column(BigInteger, default=0)
    action: Mapped[str] = mapped_column(String(16), default="")
    field: Mapped[str] = mapped_column(String(32), default="")
    old_value: Mapped[str] = mapped_column(String(500), default="")
    new_value: Mapped[str] = mapped_column(String(500), default="")
    operator_id: Mapped[int] = mapped_column(BigInteger, default=0)
