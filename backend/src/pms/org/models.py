"""组织权限域数据模型（设计稿 04 §4.1）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin


class SysDept(Base, CommonMixin):
    """部门 `t_sys_dept`。"""

    __tablename__ = "t_sys_dept"

    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dept_code: Mapped[str] = mapped_column(String(64), default="")
    dept_name: Mapped[str] = mapped_column(String(128), default="")
    dept_type: Mapped[str] = mapped_column(String(32), default="DEPT")
    leader_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    path: Mapped[str] = mapped_column(String(512), default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


class SysPost(Base, CommonMixin):
    """岗位 `t_sys_post`（仅用于展示与汇报关系，不参与鉴权）。"""

    __tablename__ = "t_sys_post"

    post_code: Mapped[str] = mapped_column(String(64), default="")
    post_name: Mapped[str] = mapped_column(String(64), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


class SysUser(Base, CommonMixin):
    """用户 `t_sys_user`。"""

    __tablename__ = "t_sys_user"

    username: Mapped[str] = mapped_column(String(64), default="")
    password_hash: Mapped[str] = mapped_column(String(128), default="")
    real_name: Mapped[str] = mapped_column(String(64), default="")
    mobile: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    dept_id: Mapped[int] = mapped_column(BigInteger, default=0)
    manager_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    post_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    employee_no: Mapped[str] = mapped_column(String(32), default="")
    cost_rate: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")
    login_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[str | None] = mapped_column(String(32), default=None)


class SysRole(Base, CommonMixin):
    """角色 `t_sys_role`（数据范围与字段白名单在此配置）。"""

    __tablename__ = "t_sys_role"

    role_code: Mapped[str] = mapped_column(String(64), default="")
    role_name: Mapped[str] = mapped_column(String(64), default="")
    data_scope: Mapped[str] = mapped_column(String(32), default="SELF")
    custom_dept_ids: Mapped[str] = mapped_column(String(512), default="")
    field_whitelist: Mapped[str] = mapped_column(String(512), default="")
    builtin: Mapped[int] = mapped_column(Integer, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


class SysPermission(Base, CommonMixin):
    """权限点 `t_sys_permission`（菜单/按钮/接口）。"""

    __tablename__ = "t_sys_permission"

    perm_code: Mapped[str] = mapped_column(String(128), default="")
    perm_name: Mapped[str] = mapped_column(String(128), default="")
    perm_type: Mapped[str] = mapped_column(String(16), default="API")
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    path: Mapped[str] = mapped_column(String(512), default="")
    component: Mapped[str] = mapped_column(String(256), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class SysUserRole(Base, CommonMixin):
    """用户-角色 `t_sys_user_role`。"""

    __tablename__ = "t_sys_user_role"

    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    role_id: Mapped[int] = mapped_column(BigInteger, default=0)


class SysRolePermission(Base, CommonMixin):
    """角色-权限 `t_sys_role_permission`。"""

    __tablename__ = "t_sys_role_permission"

    role_id: Mapped[int] = mapped_column(BigInteger, default=0)
    perm_id: Mapped[int] = mapped_column(BigInteger, default=0)


class SysOperateLog(Base, CommonMixin):
    """操作审计 `t_sys_operate_log`（含权限拒绝记录，设计稿 03 §7）。"""

    __tablename__ = "t_sys_operate_log"

    module: Mapped[str] = mapped_column(String(64), default="")
    operation: Mapped[str] = mapped_column(String(128), default="")
    method: Mapped[str] = mapped_column(String(16), default="")
    url: Mapped[str] = mapped_column(String(512), default="")
    params: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(16), default="SUCCESS")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_ms: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
