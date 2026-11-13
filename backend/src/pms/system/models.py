"""系统域数据模型（设计稿 04 §4.6）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pms.core.database import Base, CommonMixin


class SysDict(Base, CommonMixin):
    """数据字典 `t_sys_dict`。"""

    __tablename__ = "t_sys_dict"

    dict_code: Mapped[str] = mapped_column(String(64), default="")
    dict_name: Mapped[str] = mapped_column(String(128), default="")
    builtin: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


class SysDictItem(Base, CommonMixin):
    """字典项 `t_sys_dict_item`。"""

    __tablename__ = "t_sys_dict_item"

    dict_id: Mapped[int] = mapped_column(BigInteger, default=0)
    dict_code: Mapped[str] = mapped_column(String(64), default="")
    item_value: Mapped[str] = mapped_column(String(64), default="")
    item_label: Mapped[str] = mapped_column(String(128), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ENABLED")


class SysConfig(Base, CommonMixin):
    """系统参数 `t_sys_config`（**所有业务规则阈值在此配置，禁止硬编码**）。"""

    __tablename__ = "t_sys_config"

    config_key: Mapped[str] = mapped_column(String(128), default="")
    config_value: Mapped[str] = mapped_column(String(1024), default="")
    value_type: Mapped[str] = mapped_column(String(16), default="STRING")
    group_name: Mapped[str] = mapped_column(String(64), default="DEFAULT")
    remark: Mapped[str] = mapped_column(String(512), default="")
    builtin: Mapped[int] = mapped_column(Integer, default=0)


class SysFile(Base, CommonMixin):
    """文件 `t_sys_file`（一期本地磁盘，预留对象存储适配）。"""

    __tablename__ = "t_sys_file"

    file_key: Mapped[str] = mapped_column(String(128), default="")
    origin_name: Mapped[str] = mapped_column(String(256), default="")
    storage_path: Mapped[str] = mapped_column(String(512), default="")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mime: Mapped[str] = mapped_column(String(128), default="")
    bucket: Mapped[str] = mapped_column(String(64), default="local")
    biz_type: Mapped[str] = mapped_column(String(64), default="")
    biz_id: Mapped[int] = mapped_column(BigInteger, default=0)


class SysNotice(Base, CommonMixin):
    """通知 `t_sys_notice`。"""

    __tablename__ = "t_sys_notice"

    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    notice_type: Mapped[str] = mapped_column(String(32), default="SYSTEM")
    receiver_id: Mapped[int] = mapped_column(BigInteger, default=0)
    biz_type: Mapped[str] = mapped_column(String(64), default="")
    biz_id: Mapped[int] = mapped_column(BigInteger, default=0)
    read_status: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(32), default="INBOX")


class SysMailTemplate(Base, CommonMixin):
    """邮件模板 `t_sys_mail_template`（按事件编码保存，内置模板可改不可删）。"""

    __tablename__ = "t_sys_mail_template"

    event_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    subject: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    receiver_roles: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    builtin: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str] = mapped_column(String(255), default="")


class SysMailLog(Base, CommonMixin):
    """邮件发送记录 `t_sys_mail_log`：同时作为待发队列（outbox）。"""

    __tablename__ = "t_sys_mail_log"

    event_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    biz_type: Mapped[str] = mapped_column(String(64), default="")
    biz_id: Mapped[int] = mapped_column(BigInteger, default=0)
    recipient: Mapped[str] = mapped_column(String(128), default="")
    recipient_name: Mapped[str] = mapped_column(String(128), default="")
    subject: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    error: Mapped[str] = mapped_column(String(512), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class SysLoginLog(Base, CommonMixin):
    """登录日志 `t_sys_login_log`。"""

    __tablename__ = "t_sys_login_log"

    username: Mapped[str] = mapped_column(String(64), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="SUCCESS")
    message: Mapped[str] = mapped_column(String(256), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")


class SysJobLock(Base, CommonMixin):
    """定时任务分布式锁 `t_sys_job_lock`（多实例部署时保证任务只执行一次）。"""

    __tablename__ = "t_sys_job_lock"

    lock_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    owner_token: Mapped[str] = mapped_column(String(128), default="")
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
