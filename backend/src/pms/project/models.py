"""项目周期数据模型（设计稿 04 §4.2）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Date, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin
from pms.project.state import MilestoneStatus, ProjectStatus, TaskStatus


class PrjProject(Base, CommonMixin):
    """项目 `t_prj_project`。"""

    __tablename__ = "t_prj_project"

    project_code: Mapped[str] = mapped_column(String(32), default="")
    project_name: Mapped[str] = mapped_column(String(200), default="")
    project_type: Mapped[str] = mapped_column(String(32), default="DEV")
    secret_level: Mapped[str] = mapped_column(String(16), default="INTERNAL")
    level: Mapped[str] = mapped_column(String(16), default="NORMAL")
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    pm_id: Mapped[int] = mapped_column(BigInteger, default=0)
    sponsor_id: Mapped[int] = mapped_column(BigInteger, default=0)
    customer_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    opportunity_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    contract_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    budget_man_month: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    actual_man_month: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    plan_start: Mapped[str | None] = mapped_column(Date, default=None)
    plan_end: Mapped[str | None] = mapped_column(Date, default=None)
    actual_start: Mapped[str | None] = mapped_column(Date, default=None)
    actual_end: Mapped[str | None] = mapped_column(Date, default=None)
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    health: Mapped[str] = mapped_column(String(16), default="GREEN")
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.DRAFT)
    approval_level: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str] = mapped_column(Text, default="")
    terminate_reason: Mapped[str] = mapped_column(Text, default="")


class PrjMember(Base, CommonMixin):
    """项目成员 `t_prj_member`。"""

    __tablename__ = "t_prj_member"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    role_in_project: Mapped[str] = mapped_column(String(32), default="MEMBER")
    allocation: Mapped[float] = mapped_column(Numeric(5, 2), default=100)
    join_date: Mapped[str | None] = mapped_column(Date, default=None)
    leave_date: Mapped[str | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class PrjDirector(Base, CommonMixin):
    """项目总监 `t_prj_director`（项目级授权，一个项目可多人，变更审批会签）。

    「项目总监」是**权限而非岗位**：由管理员/PMO 在项目内指派，被指派者自动进入项目组
    并取得该项目变更申请的审核权（`change` 审批链第一节点，多人会签）。
    """

    __tablename__ = "t_prj_director"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    assigned_by: Mapped[int] = mapped_column(BigInteger, default=0)


class PrjStage(Base, CommonMixin):
    """项目阶段 `t_prj_stage`。"""

    __tablename__ = "t_prj_stage"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    stage_name: Mapped[str] = mapped_column(String(128), default="")
    seq: Mapped[int] = mapped_column(Integer, default=1)
    weight: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    plan_start: Mapped[str | None] = mapped_column(Date, default=None)
    plan_end: Mapped[str | None] = mapped_column(Date, default=None)
    actual_start: Mapped[str | None] = mapped_column(Date, default=None)
    actual_end: Mapped[str | None] = mapped_column(Date, default=None)
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.NOT_STARTED)


class PrjMilestone(Base, CommonMixin):
    """里程碑 `t_prj_milestone`。"""

    __tablename__ = "t_prj_milestone"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    milestone_name: Mapped[str] = mapped_column(String(128), default="")
    milestone_type: Mapped[str] = mapped_column(String(32), default="NORMAL")
    plan_date: Mapped[str | None] = mapped_column(Date, default=None)
    actual_date: Mapped[str | None] = mapped_column(Date, default=None)
    owner_id: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(32), default=MilestoneStatus.PENDING)
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str] = mapped_column(String(500), default="")


class PrjTask(Base, CommonMixin):
    """WBS 任务 `t_prj_task`。"""

    __tablename__ = "t_prj_task"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    stage_id: Mapped[int] = mapped_column(BigInteger, default=0)
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    task_code: Mapped[str] = mapped_column(String(64), default="")
    task_name: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[int] = mapped_column(BigInteger, default=0)
    plan_start: Mapped[str | None] = mapped_column(Date, default=None)
    plan_end: Mapped[str | None] = mapped_column(Date, default=None)
    plan_hours: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    actual_hours: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    weight: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.NOT_STARTED)
    depend_on: Mapped[str] = mapped_column(String(256), default="")


class PrjRisk(Base, CommonMixin):
    """风险与问题 `t_prj_risk`（`risk_type` 区分 RISK / ISSUE）。"""

    __tablename__ = "t_prj_risk"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    risk_type: Mapped[str] = mapped_column(String(16), default="RISK")
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    probability: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    impact: Mapped[str] = mapped_column(String(256), default="")
    strategy: Mapped[str] = mapped_column(String(256), default="")
    owner_id: Mapped[int] = mapped_column(BigInteger, default=0)
    due_date: Mapped[str | None] = mapped_column(Date, default=None)
    close_time: Mapped[str | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")


class PrjBaseline(Base, CommonMixin):
    """基线 `t_prj_baseline`（立项/变更时冻结）。"""

    __tablename__ = "t_prj_baseline"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    baseline_type: Mapped[str] = mapped_column(String(32), default="SCOPE")
    baseline_name: Mapped[str] = mapped_column(String(128), default="")
    version: Mapped[str] = mapped_column(String(32), default="V1.0")
    content_json: Mapped[str] = mapped_column(Text, default="")
    frozen_by: Mapped[int] = mapped_column(BigInteger, default=0)
    frozen_time: Mapped[str] = mapped_column(String(32), default="")
    change_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class PrjAttachment(Base, CommonMixin):
    """项目附件 `t_prj_attachment`（关联 `t_sys_file`）。"""

    __tablename__ = "t_prj_attachment"

    project_id: Mapped[int] = mapped_column(BigInteger, default=0)
    biz_type: Mapped[str] = mapped_column(String(32), default="PROJECT")
    biz_id: Mapped[int] = mapped_column(BigInteger, default=0)
    file_id: Mapped[int] = mapped_column(BigInteger, default=0)
    file_name: Mapped[str] = mapped_column(String(256), default="")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
